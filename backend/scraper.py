"""
scraper.py — Universele boek-metadata fetcher.

Ondersteunde invoer:
  - OpenLibrary URL (works/books)
  - bol.com product URL
  - Amazon URL (amazon.com / amazon.nl / amazon.de / ...)
  - Goodreads URL
  - Elke andere URL met JSON-LD of Open Graph data
  - ISBN (10 of 13 cijfers)
  - Vrije tekst (titel of "titel - auteur")
"""

import os
import re
import json
import socket
import asyncio
import logging
import ipaddress
import unicodedata
import httpx
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger('uvicorn.error')

_GOOGLE_BOOKS_KEY = os.getenv('GOOGLE_BOOKS_API_KEY', '')

# Open Library vraagt om een herkenbare User-Agent (zonder persoonsgegevens).
USER_AGENT = 'BookCompass/1.0 (https://bookcompass.nl)'


@dataclass
class BookData:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    year: int | None


_MAX_BODY = 2_000_000  # bytes; een productpagina is zelden groter dan een paar honderd kB
_MAX_HOPS = 4


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def _host_is(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith('.' + d) for d in domains)


async def _public_ip(url: str) -> str:
    """
    Het adres waar deze link naartoe wijst. Weigert alles wat niet publiek is (SSRF): geen interne hosts,
    loopback of metadata-adressen.
    """
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('Deze link kunnen we niet gebruiken.')
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        raise ValueError('Deze link kunnen we niet gebruiken.')
    ips = [ipaddress.ip_address(info[4][0].split('%')[0]) for info in infos]
    if not ips or not all(ip.is_global for ip in ips):
        raise ValueError('Deze link kunnen we niet gebruiken.')
    # IPv4 eerst: binnen een container is IPv6 naar buiten vaak niet beschikbaar.
    return str(sorted(ips, key=lambda ip: ip.version)[0])


async def _get_public(client: httpx.AsyncClient, url: str, headers: dict) -> str:
    """
    Haal een door de gebruiker opgegeven pagina op: elke redirect opnieuw gecontroleerd, met een limiet op de grootte.
    We verbinden met het adres dat we zelf hebben gecontroleerd, niet opnieuw met de hostnaam: anders kan een
    DNS-server bij de tweede keer opzoeken alsnog een intern adres teruggeven (DNS-rebinding).
    Het certificaat wordt gewoon tegen de hostnaam gecontroleerd.
    """
    for _ in range(_MAX_HOPS):
        ip = await _public_ip(url)
        parts = urlsplit(url)
        netloc = f'[{ip}]' if ':' in ip else ip
        if parts.port:
            netloc += f':{parts.port}'
        pinned = parts._replace(netloc=netloc).geturl()
        host = parts.hostname if not parts.port else f'{parts.hostname}:{parts.port}'
        async with client.stream(
            'GET', pinned, headers={**headers, 'Host': host}, follow_redirects=False, timeout=15,
            extensions={'sni_hostname': parts.hostname},
        ) as r:
            if r.is_redirect and r.headers.get('location'):
                url = urljoin(url, r.headers['location'])
                continue
            body = b''
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > _MAX_BODY:
                    break
            return body[:_MAX_BODY].decode(r.encoding or 'utf-8', errors='replace')
    raise ValueError('Deze link kunnen we niet gebruiken.')


def _detect(text: str) -> str:
    t = text.strip()
    if re.fullmatch(r'OL\d+[WM]', t, re.I):
        return 'olid'
    if re.match(r'https?://', t):
        host = _host(t)
        if _host_is(host, 'openlibrary.org'):
            return 'openlibrary'
        if _host_is(host, 'bol.com'):
            return 'bol'
        if re.search(r'(^|\.)amazon\.(com|nl|de|co\.uk|fr|it|es)$', host):
            return 'amazon'
        if _host_is(host, 'goodreads.com'):
            return 'goodreads'
        return 'url'
    isbn = re.sub(r'[-\s]', '', t)
    if re.match(r'^(97[89])?\d{9}[\dX]$', isbn, re.I):
        return 'isbn'
    return 'title'


def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = re.search(r'\b(1[0-9]{3}|20[0-2][0-9])\b', value)
        return int(m.group(1)) if m else None
    return None


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get('value', '')
    return value or ''


def _author_from_ld(author_data) -> str:
    if isinstance(author_data, list):
        author_data = author_data[0] if author_data else {}
    if isinstance(author_data, dict):
        return author_data.get('name', '')
    return str(author_data) if author_data else ''


# ── Google Books API (fallback voor ISBN) ─────────────────────────────────────

async def _google_books_isbn(isbn: str, client: httpx.AsyncClient) -> BookData | None:
    """ISBN-lookup via Google Books API als Open Library niets vindt."""
    try:
        params = {'q': f'isbn:{isbn}', 'maxResults': 1}
        if _GOOGLE_BOOKS_KEY:
            params['key'] = _GOOGLE_BOOKS_KEY
        r = await client.get(
            'https://www.googleapis.com/books/v1/volumes',
            params=params,
            timeout=10,
        )
        # 429 = dagelijks quotum vol — stil falen
        if r.status_code == 429 or not r.is_success:
            return None
        items = r.json().get('items', [])
        if not items:
            return None
        info = items[0].get('volumeInfo', {})
        title = info.get('title', 'Onbekend')
        authors = info.get('authors', [])
        author = authors[0] if authors else 'Onbekend'
        description = info.get('description', '')
        subjects = info.get('categories', [])
        cover_url = info.get('imageLinks', {}).get('thumbnail', '').replace('http://', 'https://') or None
        year = _parse_year(str(info.get('publishedDate', '')))
        isbns = info.get('industryIdentifiers', [])
        found_isbn = next((i['identifier'] for i in isbns if i['type'] == 'ISBN_13'), isbn)
        if not description:
            description = f'{title} by {author}. Genres: {", ".join(subjects)}'
        return BookData(
            title=title, author=author, description=description,
            subjects=subjects, cover_url=cover_url,
            ol_key=f'/isbn/{found_isbn}', year=year,
        )
    except Exception:
        return None


# ── Open Library Search API ───────────────────────────────────────────────────

class SourceUnavailable(Exception):
    """Open Library reageerde niet (time-out of serverfout). Dat is iets anders dan 'boek bestaat niet'."""


async def _ol_search(query: str, client: httpx.AsyncClient) -> BookData | None:
    """Zoek een boek via de Open Library Search API (gratis, geen key). Eén herkansing bij een time-out of 5xx."""
    for attempt in range(2):
        try:
            r = await client.get(
                'https://openlibrary.org/search.json',
                params={'q': query, 'limit': 1, 'fields': 'title,author_name,cover_i,subject,first_publish_year,isbn,key,description'},
                headers={'User-Agent': USER_AGENT},
                timeout=12,
            )
        except httpx.HTTPError as e:
            log.warning('Open Library search failed (%s): %s', type(e).__name__, query)
            if attempt:
                raise SourceUnavailable(query)
            continue
        if r.status_code >= 500 or r.status_code == 429:
            log.warning('Open Library search returned %s: %s', r.status_code, query)
            if attempt:
                raise SourceUnavailable(query)
            continue
        if not r.is_success:
            return None
        break

    try:
        docs = r.json().get('docs', [])
        if not docs:
            return None
        doc = docs[0]

        title = doc.get('title', 'Onbekend')
        authors = doc.get('author_name', [])
        author = authors[0] if authors else 'Onbekend'
        subjects = doc.get('subject', [])[:10]
        year = doc.get('first_publish_year')
        cover_id = doc.get('cover_i')
        cover_url = f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None
        isbns = doc.get('isbn', [])
        isbn = next((i for i in isbns if len(i) == 13), isbns[0] if isbns else '')
        ol_key = doc.get('key', f'/isbn/{isbn}' if isbn else '')
        description = doc.get('description', '')
        if isinstance(description, dict):
            description = description.get('value', '')
        if not description:
            description = f'{title} by {author}. Subjects: {", ".join(subjects[:5])}'

        return BookData(
            title=title, author=author, description=description,
            subjects=subjects, cover_url=cover_url, ol_key=ol_key, year=year,
        )
    except Exception:
        return None


def _ol_title_query(title: str, author: str = '') -> str:
    """Veldzoekopdracht in Open Library-syntax (niet de Google-syntax intitle:/inauthor:, die geeft 0 resultaten)."""
    clean = lambda v: re.sub(r'[()":\\]', ' ', v).strip()
    q = f'title:({clean(title)})'
    return q + (f' author:({clean(author)})' if author.strip() else '')


def _norm(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode().lower())


async def _google_books_text(query: str, title: str, author: str, client: httpx.AsyncClient) -> BookData | None:
    """
    Vrije tekst via Google Books, als Open Library het boek niet kent (vaak Nederlandstalige boeken)
    of niet reageert. Alleen een resultaat waarvan de auteur in de zoektekst staat, of waarvan de titel
    precies de zoektekst is: anders krijg je zomaar een vertaling met de vertaler als auteur.
    """
    q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else '') if author else query
    params = {'q': q, 'maxResults': 5, 'printType': 'books'}
    if _GOOGLE_BOOKS_KEY:
        params['key'] = _GOOGLE_BOOKS_KEY
    try:
        r = await client.get('https://www.googleapis.com/books/v1/volumes', params=params, timeout=10)
        if not r.is_success:
            return None
        wanted = _norm(query)
        for item in r.json().get('items', []):
            info = item.get('volumeInfo', {})
            found_title = info.get('title', '')
            authors = info.get('authors', [])
            if not found_title or not authors:
                continue
            surnames = [_norm(a.split()[-1]) for a in authors if a.split()]
            if not (any(s and s in wanted for s in surnames) or _norm(found_title) == wanted):
                continue
            subjects = info.get('categories', [])
            description = info.get('description', '') or f'{found_title} by {authors[0]}. Genres: {", ".join(subjects)}'
            isbns = info.get('industryIdentifiers', [])
            isbn = next((i['identifier'] for i in isbns if i['type'] == 'ISBN_13'), '')
            return BookData(
                title=found_title, author=authors[0], description=description, subjects=subjects,
                cover_url=info.get('imageLinks', {}).get('thumbnail', '').replace('http://', 'https://') or None,
                ol_key=f'/isbn/{isbn}' if isbn else '', year=_parse_year(str(info.get('publishedDate', ''))),
            )
    except Exception:
        return None
    return None


# ── OpenLibrary URL ───────────────────────────────────────────────────────────

async def _fetch_openlibrary(url: str, client: httpx.AsyncClient) -> BookData:
    match = re.search(r'openlibrary\.org/(works|books)/(OL\w+)', url)
    if not match:
        raise ValueError(f'Geen geldige Open Library URL: {url}')
    kind, ol_id = match.group(1), match.group(2)

    if kind == 'works':
        r = await client.get(f'https://openlibrary.org/works/{ol_id}.json')
        r.raise_for_status()
        work = r.json()
        title = work.get('title', 'Onbekend')
        description = _text(work.get('description', ''))
        subjects = work.get('subjects', [])[:10]
        cover_id = (work.get('covers') or [None])[0]
        year = _parse_year(work.get('first_publish_date'))
        if not year:
            sr = await client.get(
                'https://openlibrary.org/search.json',
                params={'q': f'key:/works/{ol_id}', 'fields': 'first_publish_year', 'limit': 1},
            )
            if sr.is_success:
                docs = sr.json().get('docs', [])
                if docs:
                    year = _parse_year(docs[0].get('first_publish_year'))
        author = 'Onbekend'
        authors_ref = work.get('authors', [])
        if authors_ref:
            author_key = authors_ref[0].get('author', {}).get('key', '')
            if author_key:
                ar = await client.get(f'https://openlibrary.org{author_key}.json')
                if ar.is_success:
                    author = ar.json().get('name', 'Onbekend')
    else:
        r = await client.get(f'https://openlibrary.org/books/{ol_id}.json')
        r.raise_for_status()
        edition = r.json()
        title = edition.get('title', 'Onbekend')
        description = _text(edition.get('description', ''))
        subjects = edition.get('subjects', [])[:10]
        cover_id = (edition.get('covers') or [None])[0]
        year = _parse_year(edition.get('publish_date') or edition.get('first_publish_date'))
        work_key = (edition.get('works') or [{}])[0].get('key', '')
        if work_key and not description:
            wr = await client.get(f'https://openlibrary.org{work_key}.json')
            if wr.is_success:
                work_data = wr.json()
                description = _text(work_data.get('description', ''))
                subjects = subjects or work_data.get('subjects', [])[:10]
                if not year:
                    year = _parse_year(work_data.get('first_publish_date'))
        author = 'Onbekend'
        author_keys = edition.get('authors', [])
        if author_keys:
            ak = author_keys[0].get('key', '')
            if ak:
                ar = await client.get(f'https://openlibrary.org{ak}.json')
                if ar.is_success:
                    author = ar.json().get('name', 'Onbekend')

    cover_url = f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None
    if not description:
        description = f'{title} by {author}. Subjects: {", ".join(subjects)}'

    return BookData(
        title=title, author=author, description=description,
        subjects=subjects, cover_url=cover_url,
        ol_key=f'/{kind}/{ol_id}', year=year,
    )


# ── bol.com ───────────────────────────────────────────────────────────────────

async def _fetch_bol(url: str, client: httpx.AsyncClient) -> BookData:
    # Bol.com rendert client-side — extraheer de titel uit de URL-slug.
    # URL-patroon: /nl/nl/p/{slug}/{product-id}/
    slug_match = re.search(r'/p/([a-z0-9][a-z0-9\-]+)/\d', url)
    if slug_match:
        slug = slug_match.group(1)

        # Probeer meerdere varianten van de slug als zoekterm:
        # 1. Volledig (slug zonder koppeltekens)
        # 2. Deel na een serienummer: "reeks-1-boektitel" → "boektitel"
        # 3. Deel vóór een serienummer: "reeks-1-boektitel" → "reeks"
        candidates = [slug.replace('-', ' ')]
        series_split = re.split(r'-\d+-', slug, maxsplit=1)
        if len(series_split) == 2:
            candidates.append(series_split[1].replace('-', ' '))
            candidates.append(series_split[0].replace('-', ' '))

        for term in candidates:
            book = await _ol_search(term, client)
            if book:
                return book

    raise ValueError('Kon geen boekinfo ophalen van bol.com — probeer de boektitel direct in te typen')


# ── Amazon ────────────────────────────────────────────────────────────────────

async def _fetch_amazon(url: str, client: httpx.AsyncClient) -> BookData:
    # ASIN uit URL (voor boeken = ISBN-10)
    asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
    if asin_match:
        book = await _ol_search(f'isbn:{asin_match.group(1)}', client)
        if book:
            return book

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    try:
        html = await _get_public(client, url, headers)

        for ld_match in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
        ):
            try:
                data = json.loads(ld_match.group(1))
                if isinstance(data, list):
                    data = data[0]
                title = data.get('name', '')
                author = _author_from_ld(data.get('author', {}))
                isbn = data.get('isbn', '')
                if isbn:
                    book = await _ol_search(f'isbn:{isbn}', client)
                    if book:
                        return book
                if title:
                    book = await _ol_search(_ol_title_query(title, author), client)
                    if book:
                        return book
            except (json.JSONDecodeError, KeyError):
                continue

        title_match = re.search(r'id="productTitle"[^>]*>\s*(.*?)\s*</span>', html, re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            book = await _ol_search(_ol_title_query(title), client)
            if book:
                return book
    except Exception:
        pass

    raise ValueError('Kon geen boekinfo ophalen van Amazon')


# ── Goodreads ─────────────────────────────────────────────────────────────────

async def _fetch_goodreads(url: str, client: httpx.AsyncClient) -> BookData:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    html = await _get_public(client, url, headers)

    for ld_match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(ld_match.group(1))
            if isinstance(data, list):
                data = data[0]
            title = data.get('name', '')
            author = _author_from_ld(data.get('author', {}))
            isbn = data.get('isbn', '')
            if isbn:
                book = await _ol_search(f'isbn:{isbn}', client)
                if book:
                    return book
            if title:
                book = await _ol_search(_ol_title_query(title, author), client)
                if book:
                    return book
        except (json.JSONDecodeError, KeyError):
            continue

    raise ValueError('Kon geen boekinfo ophalen van Goodreads')


# ── Generieke URL ─────────────────────────────────────────────────────────────

async def _fetch_url(url: str, client: httpx.AsyncClient) -> BookData:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    html = await _get_public(client, url, headers)

    for ld_match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(ld_match.group(1))
            if isinstance(data, list):
                data = data[0]
            isbn = data.get('isbn') or data.get('gtin13', '')
            if isbn:
                book = await _ol_search(f'isbn:{re.sub(r"[^0-9X]", "", isbn)}', client)
                if book:
                    return book
            title = data.get('name', '')
            if title:
                book = await _ol_search(_ol_title_query(title), client)
                if book:
                    return book
        except (json.JSONDecodeError, KeyError):
            continue

    og_match = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
    if og_match:
        title = og_match.group(1).strip()
        book = await _ol_search(_ol_title_query(title), client)
        if book:
            return book

    raise ValueError(f'Kon geen boekinfo ophalen van: {url}')


# ── Publieke API ──────────────────────────────────────────────────────────────

async def fetch_book(query: str) -> BookData:
    """
    Haal boekdata op voor willekeurige invoer:
    URL (OL, bol.com, Amazon, Goodreads, overig), ISBN, of vrije tekst (titel).
    """
    kind = _detect(query.strip())
    async with httpx.AsyncClient(timeout=15) as client:
        if kind == 'openlibrary':
            return await _fetch_openlibrary(query, client)
        if kind == 'bol':
            return await _fetch_bol(query, client)
        if kind == 'amazon':
            return await _fetch_amazon(query, client)
        if kind == 'goodreads':
            return await _fetch_goodreads(query, client)
        if kind == 'url':
            return await _fetch_url(query, client)
        if kind == 'isbn':
            isbn = re.sub(r'[-\s]', '', query)
            try:
                book = await _ol_search(f'isbn:{isbn}', client)
            except SourceUnavailable:
                book = None
            if book:
                return book
            # Fallback: Google Books (betere ISBN-dekking voor nieuwe/buitenlandse edities)
            book = await _google_books_isbn(isbn, client)
            if book:
                return book
            raise ValueError(
                f'ISBN {isbn} niet gevonden. '
                'Typ de boektitel rechtstreeks in het zoekveld.'
            )
        if kind == 'olid':
            olid = query.strip().upper()
            return await _fetch_openlibrary(f'https://openlibrary.org/{"works" if olid.endswith("W") else "books"}/{olid}', client)

        return await _fetch_text(query.strip(), client)


async def _fetch_text(q: str, client: httpx.AsyncClient) -> BookData:
    """
    Vrije tekst: "titel", "titel auteur", "titel - auteur", "titel by/van/door auteur" of "titel, auteur".
    Open Library zoekt met EN tussen alle woorden, en een losse '-' betekent daar NIET.
    Daarom halen we scheidingstekens weg en zoeken we waar mogelijk op titel- en auteurveld.
    """
    # Eerst de hele tekst (zonder losse streepjes): dan blijft een titel als "De ontdekking van de hemel" heel.
    attempts: list[str] = [re.sub(r'\s+[-–—]\s+', ' ', q)]
    sep = re.split(r'\s+(?:by|van|door|[-–—])\s+|\s*,\s+', q, maxsplit=1, flags=re.I)
    if len(sep) == 2 and all(part.strip() for part in sep):
        title_part, author_part = (part.strip() for part in sep)
        attempts += [_ol_title_query(title_part, author_part), f'{title_part} {author_part}']

    unavailable = False
    for attempt in dict.fromkeys(attempts):
        try:
            book = await _ol_search(attempt, client)
        except SourceUnavailable:
            unavailable = True
            continue
        if book:
            return book

    # Tweede bron: Google Books (kent meer Nederlandstalige uitgaven).
    title_part, author_part = (sep[0], sep[1]) if len(sep) == 2 else (q, '')
    book = await _google_books_text(q, title_part.strip(), author_part.strip(), client)
    if book:
        return book

    if unavailable:
        # Geen 'niet gevonden' tonen als Open Library gewoon even niet reageerde.
        raise SourceUnavailable(q)
    raise ValueError(f'Geen boek gevonden voor: {q}')
