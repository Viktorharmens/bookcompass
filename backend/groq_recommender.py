"""
groq_recommender.py — Aanbevelingen via Groq LLM, gecontroleerd tegen Open Library en Google Books.

Workflow:
  1. Vraag Groq (GPT-OSS 120B) om meer kandidaten dan nodig (k + CANDIDATE_EXTRA)
  2. Controleer elke kandidaat concurrent: eerst Open Library, dan Google Books als terugval.
     Titel én auteur moeten kloppen; anders is het boek vrijwel zeker verzonnen.
  3. Zijn er na controle minder dan k over, dan vragen we één keer bij (zonder de al genoemde titels)
  4. Geef de eerste k gecontroleerde boeken terug, in de volgorde van het model
"""

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

GROQ_MODEL = 'openai/gpt-oss-120b'

log = logging.getLogger('uvicorn.error')

# Open Library vraagt om een herkenbare User-Agent (zonder persoonsgegevens).
USER_AGENT = 'BookCompass/1.0 (https://bookcompass.nl)'

# Zoveel kandidaten meer vragen we dan we tonen, omdat een deel de controle niet haalt.
CANDIDATE_EXTRA = 8
# Bijvragen gebeurt maar één keer, en alleen als de eerste ronde snel genoeg was.
REFILL_EXTRA = 6
REFILL_BUDGET_SECONDS = 15.0
# Open Library niet overbelasten: hooguit zoveel zoekopdrachten tegelijk.
LOOKUP_CONCURRENCY = 8
LOOKUP_TIMEOUT = 8


@dataclass
class Recommendation:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    score: float
    explanation: str
    year: int | None = None
    # Waar het boek gecontroleerd is: "openlibrary" (ol_key gevuld) of "google_books" (source_id = volume-id).
    source: str = 'openlibrary'
    source_id: str = ''
    isbn: str = ''


# ── Hulpfuncties voor vergelijken ─────────────────────────────────────────────

def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = re.search(r'\b(1[0-9]{3}|20[0-9]{2})\b', value)
        return _parse_year(int(m.group(1))) if m else None
    return None


def _ascii(value: str) -> str:
    return unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode().lower()


def _words(value: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', _ascii(value))


def _norm(value: str) -> str:
    return ''.join(_words(value))


def _surname(author: str) -> str:
    """Achternaam, genormaliseerd. 'Reve, Gerard' en 'Gerard Reve' geven allebei 'reve'."""
    author = (author or '').strip()
    if ',' in author:
        author = author.split(',')[0]
    words = _words(author)
    return words[-1] if words else ''


def _main_title(title: str) -> str:
    """Titel zonder ondertitel ('Tirza: roman' -> 'Tirza')."""
    return re.split(r'\s*[:;(\[]\s*|\s+[-–—]\s+', title or '', maxsplit=1)[0]


def title_matches(wanted: str, found: str) -> bool:
    """
    Kloppen twee titels? Op woordniveau, zonder ondertitel, lidwoorden en accenten.
    De ene titel mag de andere als begin hebben ('Lijmen' / 'Lijmen; Het been').
    """
    a, b = _words(_main_title(wanted)), _words(_main_title(found))
    articles = {'the', 'a', 'an', 'de', 'het', 'een', 'der', 'die', 'das', 'le', 'la', 'les', 'el'}
    if len(a) > 1 and a[0] in articles:
        a = a[1:]
    if len(b) > 1 and b[0] in articles:
        b = b[1:]
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_[:len(short)] == short


def author_matches(wanted: str, found_authors: list[str]) -> bool:
    """De achternaam moet gelijk zijn aan die van een gevonden auteur (niet alleen 'zit erin')."""
    surname = _surname(wanted)
    return bool(surname) and any(_surname(name) == surname for name in found_authors or [])


def same_book(title: str, author: str, found_title: str, found_authors: list[str]) -> bool:
    return title_matches(title, found_title) and author_matches(author, found_authors)


def _clean_query(value: str) -> str:
    return re.sub(r'[()":\\\[\]]', ' ', value or '').strip()


# ── Controle tegen bronnen ────────────────────────────────────────────────────

async def _ol_lookup(title: str, author: str, client: httpx.AsyncClient) -> dict:
    """Zoek de kandidaat in Open Library; alleen een treffer met dezelfde titel én auteur telt."""
    try:
        r = await client.get(
            'https://openlibrary.org/search.json',
            params={
                'title': _clean_query(_main_title(title)),
                'author': _clean_query(_surname(author) or author),
                'limit': 5,
                'fields': 'key,title,author_name,cover_i,subject,first_publish_year',
            },
            timeout=LOOKUP_TIMEOUT,
        )
        if not r.is_success:
            return {}
        for doc in r.json().get('docs', []):
            if not doc.get('key') or not same_book(title, author, doc.get('title', ''), doc.get('author_name', [])):
                continue
            cover_id = doc.get('cover_i')
            return {
                'source': 'openlibrary',
                'ol_key': doc['key'],
                'subjects': (doc.get('subject') or [])[:8],
                'cover_url': f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None,
                'year': _parse_year(doc.get('first_publish_year')),
            }
    except Exception as e:  # time-out of kapotte JSON: dan proberen we Google Books
        log.info('Open Library lookup failed for "%s" (%s)', title, type(e).__name__)
    return {}


async def _gb_lookup(title: str, author: str, client: httpx.AsyncClient) -> dict:
    """Terugval voor boeken die Open Library niet kent (vaak Nederlandstalige uitgaven)."""
    params = {
        'q': f'intitle:"{_clean_query(_main_title(title))}" inauthor:"{_clean_query(_surname(author) or author)}"',
        'maxResults': 5,
        'printType': 'books',
        'fields': 'items(id,volumeInfo(title,authors,publishedDate,categories,imageLinks/thumbnail,industryIdentifiers))',
    }
    key = os.getenv('GOOGLE_BOOKS_API_KEY', '')
    if key:
        params['key'] = key
    try:
        r = await client.get('https://www.googleapis.com/books/v1/volumes', params=params, timeout=LOOKUP_TIMEOUT)
        if not r.is_success:  # 429 = quotum op: stil falen
            return {}
        for item in r.json().get('items', []) or []:
            info = item.get('volumeInfo', {})
            if not same_book(title, author, info.get('title', ''), info.get('authors', [])):
                continue
            ids = info.get('industryIdentifiers', []) or []
            isbn = next((i.get('identifier', '') for i in ids if i.get('type') == 'ISBN_13'), '')
            thumb = (info.get('imageLinks') or {}).get('thumbnail', '').replace('http://', 'https://')
            return {
                'source': 'google_books',
                'ol_key': '',
                'source_id': item.get('id', ''),
                'isbn': isbn,
                'subjects': (info.get('categories') or [])[:8],
                'cover_url': thumb or None,
                'year': _parse_year(info.get('publishedDate', '')),
            }
    except Exception as e:
        log.info('Google Books lookup failed for "%s" (%s)', title, type(e).__name__)
    return {}


async def _verify(item: dict, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> dict:
    async with sem:
        meta = await _ol_lookup(item['title'], item['author'], client)
        if not meta:
            meta = await _gb_lookup(item['title'], item['author'], client)
    return meta


def _year(item: dict, meta: dict) -> int | None:
    """
    Jaar van eerste verschijning. Het model kent dat meestal beter dan de bronnen: Google Books geeft
    het jaar van een editie (vaak een herdruk) en Open Library soms een te vroeg jaar door een verkeerd
    gekoppelde editie (1969 voor The Idiot van Elif Batuman uit 2017). Het bronjaar is de terugval.
    """
    return _parse_year(item.get('year')) or meta.get('year')


# ── Modelantwoord ─────────────────────────────────────────────────────────────

def parse_books(raw: str) -> list[dict]:
    """
    Lees de JSON-lijst van het model. Is de lijst als geheel ongeldig (afgekapt of één kapot object),
    dan lezen we de objecten los, zodat één fout niet alle tips kost.
    """
    raw = raw or ''
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [b for b in data if isinstance(b, dict)]
        except json.JSONDecodeError:
            pass
    books, decoder = [], json.JSONDecoder()
    for m in re.finditer(r'\{', raw):
        try:
            obj, _ = decoder.raw_decode(raw, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get('title'):
            books.append(obj)
    return books


def filter_candidates(
    books: list[dict],
    book_title: str,
    book_author: str,
    blocked_titles: list[str],
    seen: set[str],
) -> list[dict]:
    """
    Gooi weg: lege of kapotte objecten, het invoerboek, boeken van dezelfde auteur,
    titels uit `blocked_titles` (exclude-lijst van de site) en een tweede boek van een auteur
    die al genoemd is (`seen` wordt bijgewerkt, zodat ook een tweede ronde geen dubbelen geeft).
    """
    input_surname = _surname(book_author)
    out = []
    for b in books:
        title, author = b.get('title'), b.get('author')
        if not isinstance(title, str) or not isinstance(author, str):
            continue
        title, author = ' '.join(title.split()), ' '.join(author.split())
        if not title or not author:
            continue
        if input_surname and _surname(author) == input_surname:
            continue
        if book_title and title_matches(title, book_title):
            continue
        if any(title_matches(title, t) for t in blocked_titles if t):
            continue
        # Eén boek per auteur: zo blijven er meer verschillende ontdekkingen over.
        key = 'author:' + _surname(author)
        if key in seen:
            continue
        seen.add(key)
        out.append({**b, 'title': title, 'author': author})
    return out


def _build_prompt(
    n: int,
    book_title: str,
    book_author: str,
    book_description: str,
    book_subjects: list[str],
    style_weight: float,
    selected_subjects: list[str] | None,
    lang: str,
    heaviness: str,
    avoid_titles: list[str],
) -> str:
    lang_name = LANG_NAMES.get(lang, LANG_NAMES['nl'])

    # Vertaal slider (1-5) direct naar een expliciete focusinstructie
    style_level = round(style_weight)  # 1-5
    if style_level == 1:
        focus = "Focus strongly on similar themes, ideas, and subject matter. Writing style is not important."
    elif style_level == 2:
        focus = "Focus mostly on similar themes and subject matter. Writing style may play a minor role."
    elif style_level == 3:
        focus = "Balance equally between similar writing style and similar themes."
    elif style_level == 4:
        focus = "Focus mostly on similar writing style, tone, and narrative voice. Themes are secondary."
    else:
        focus = "Focus strongly on similar writing style, tone, prose, and narrative voice. Themes are less important."

    # Zwaarte van de inhoud: licht = luchtig, zwaar = heftiger mag (maar niet per se loodzwaar)
    if heaviness == 'light':
        heaviness_note = (
            "\nThe user wants a light read: only recommend light-hearted, uplifting or easy-going books. "
            "Avoid books centred on heavy themes such as war, abuse, violence, grief, suicide or trauma."
        )
    elif heaviness == 'heavy':
        heaviness_note = (
            "\nThe user is open to a heavier read: prefer books with real emotional weight and more intense themes "
            "(e.g. loss, trauma, war, moral conflict). They do not all need to be relentlessly dark."
        )
    else:
        heaviness_note = ''

    subjects_str = ', '.join(book_subjects[:8]) if book_subjects else 'not specified'
    selected_note = (
        f'\nThe user is especially interested in: {", ".join(selected_subjects)}.'
        if selected_subjects else ''
    )
    avoid_note = (
        '\n- Do NOT recommend any of these (already shown or rejected): '
        + '; '.join(f'"{t}"' for t in avoid_titles)
        if avoid_titles else ''
    )

    return f"""You are an expert book recommender with precise knowledge of published literature. \
Recommend {n} books similar to the one below.

Book: "{book_title}" by {book_author}
Genres/subjects: {subjects_str}
Description: {book_description[:600]}

{focus}{selected_note}{heaviness_note}

Rules:
- Only real, published books that you are certain exist. Each title and author is checked against \
library catalogues; invented or misattributed books are discarded, so never guess
- Give the exact title as it was originally published, and the correct author's full name. \
Double-check that this author really wrote this book
- Do NOT translate titles yourself. Use the original-language title; a Dutch title only if the book \
was originally written in Dutch
- Do NOT recommend any book by {book_author}, and not "{book_title}" itself or a translation of it{avoid_note}
- Every book by a different author: at most one book per author
- Prefer books you know well over obscure ones you are unsure about. Include both well-known and lesser-known books
- Vary the time periods and geographic origins
- Best match first
- The "reason" field must be in {lang_name} (2-3 sentences explaining why this book fits)

Return ONLY a valid JSON array, no other text:
[
  {{
    "title": "Original Title",
    "author": "Author Full Name",
    "year": 1999,
    "reason": "{lang_name} explanation of why this book fits the input book."
  }}
]"""


LANG_NAMES = {'nl': 'Dutch', 'en': 'English'}


async def _ask_model(groq_client: AsyncGroq, prompt: str) -> list[dict]:
    response = await groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.4,
        max_tokens=4000,
        reasoning_effort='low',
    )
    raw = (response.choices[0].message.content or '').strip()
    books = parse_books(raw)
    if not books:
        log.warning('recommend: no books in model output (finish_reason=%s, %d chars)',
                    response.choices[0].finish_reason, len(raw))
    return books


# ── Publieke API ──────────────────────────────────────────────────────────────

async def recommend(
    book_title: str,
    book_author: str,
    book_description: str,
    book_subjects: list[str],
    style_weight: float = 3.0,
    topic_weight: float = 3.0,
    selected_subjects: list[str] | None = None,
    k: int = 10,
    lang: str = 'nl',
    heaviness: str = 'any',
    exclude: list[str] | None = None,
) -> list[Recommendation]:
    started = time.monotonic()
    exclude = [t.strip() for t in (exclude or []) if isinstance(t, str) and t.strip()]

    def prompt(n: int, avoid: list[str]) -> str:
        return _build_prompt(
            n, book_title, book_author, book_description, book_subjects, style_weight,
            selected_subjects, lang, heaviness, avoid,
        )

    seen: set[str] = set()
    verified: list[tuple[dict, dict]] = []
    rejected: list[dict] = []
    proposed: list[str] = []

    async with (
        AsyncGroq(api_key=os.getenv('GROQ_API_KEY')) as groq_client,
        httpx.AsyncClient(timeout=LOOKUP_TIMEOUT, headers={'User-Agent': USER_AGENT}) as http,
    ):
        sem = asyncio.Semaphore(LOOKUP_CONCURRENCY)
        records: set[str] = set()

        async def round_(n: int, avoid: list[str]) -> None:
            books = await _ask_model(groq_client, prompt(n, avoid))
            candidates = filter_candidates(books, book_title, book_author, exclude, seen)
            proposed.extend(c['title'] for c in candidates)
            metas = await asyncio.gather(*(_verify(c, http, sem) for c in candidates))
            for item, meta in zip(candidates, metas):
                record = (meta.get('ol_key') or meta.get('source_id')) if meta else ''
                if not record:
                    rejected.append(item)
                elif record not in records:  # zelfde werk twee keer genoemd
                    records.add(record)
                    verified.append((item, meta))

        await round_(k + CANDIDATE_EXTRA, exclude)
        rounds = 1

        # Te weinig over na controle: één keer bijvragen, zonder alles wat al genoemd is.
        if len(verified) < k and time.monotonic() - started < REFILL_BUDGET_SECONDS:
            await round_(k - len(verified) + REFILL_EXTRA, exclude + proposed)
            rounds = 2

    log.info(
        'recommend "%s": %d rounds, %d verified (%d Open Library, %d Google Books), '
        '%d rejected in %.1fs; rejected: %s',
        book_title, rounds, len(verified),
        sum(m['source'] == 'openlibrary' for _, m in verified),
        sum(m['source'] == 'google_books' for _, m in verified),
        len(rejected), time.monotonic() - started,
        '; '.join(f"{c['title']} ({c['author']})" for c in rejected) or '-',
    )

    results = []
    for i, (item, meta) in enumerate(verified[:k]):
        results.append(Recommendation(
            title=item['title'],
            author=item['author'],
            description='',
            subjects=meta.get('subjects', []),
            cover_url=meta.get('cover_url'),
            ol_key=meta.get('ol_key', ''),
            score=round(max(0.5, 1.0 - i * 0.04), 2),
            explanation=item.get('reason', '') if isinstance(item.get('reason'), str) else '',
            year=_year(item, meta),
            source=meta.get('source', 'openlibrary'),
            source_id=meta.get('source_id', ''),
            isbn=meta.get('isbn', ''),
        ))

    return results
