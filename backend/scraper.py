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
import httpx
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

_GOOGLE_BOOKS_KEY = os.getenv('GOOGLE_BOOKS_API_KEY', '')


@dataclass
class BookData:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    year: int | None


def _detect(text: str) -> str:
    t = text.strip()
    if re.match(r'https?://', t):
        if 'openlibrary.org' in t:
            return 'openlibrary'
        if 'bol.com' in t:
            return 'bol'
        if re.search(r'amazon\.(com|nl|de|co\.uk|fr|it|es)', t):
            return 'amazon'
        if 'goodreads.com' in t:
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

async def _ol_search(query: str, client: httpx.AsyncClient) -> BookData | None:
    """Zoek een boek via de Open Library Search API (gratis, geen key)."""
    try:
        r = await client.get(
            'https://openlibrary.org/search.json',
            params={'q': query, 'limit': 1, 'fields': 'title,author_name,cover_i,subject,first_publish_year,isbn,key,description'},
            timeout=10,
        )
        if not r.is_success:
            return None
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
        r = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
        html = r.text

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
                    q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else '')
                    book = await _ol_search(q, client)
                    if book:
                        return book
            except (json.JSONDecodeError, KeyError):
                continue

        title_match = re.search(r'id="productTitle"[^>]*>\s*(.*?)\s*</span>', html, re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            book = await _ol_search(f'intitle:"{title}"', client)
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
    r = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
    html = r.text

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
                q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else '')
                book = await _ol_search(q, client)
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
    r = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
    html = r.text

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
                book = await _ol_search(f'intitle:"{title}"', client)
                if book:
                    return book
        except (json.JSONDecodeError, KeyError):
            continue

    og_match = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
    if og_match:
        title = og_match.group(1).strip()
        book = await _ol_search(f'intitle:"{title}"', client)
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
            book = await _ol_search(f'isbn:{isbn}', client)
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
        # Vrije tekst — probeer verschillende query-vormen
        q = query.strip()

        # Detecteer "titel - auteur" of "titel by auteur" patroon
        sep = re.split(r'\s+(?:by|-)\s+', q, maxsplit=1, flags=re.I)
        if len(sep) == 2:
            title_part, author_part = sep
            book = await _ol_search(
                f'intitle:"{title_part.strip()}" inauthor:"{author_part.strip()}"', client
            )
            if book:
                return book

        # Probeer als losse zoekterm (meest flexibel)
        book = await _ol_search(q, client)
        if book:
            return book

        raise ValueError(f'Geen boek gevonden voor: {query}')
