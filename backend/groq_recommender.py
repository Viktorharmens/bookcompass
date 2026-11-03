"""
groq_recommender.py — Aanbevelingen via Groq LLM, gecontroleerd tegen Open Library en Google Books.

Workflow:
  1. Vraag Groq (GPT-OSS 120B) om ongeveer 2 × k kandidaten, met jaar, originele taal en Nederlandse titel
  2. Controleer elke kandidaat in Open Library (originele titel, daarna de Nederlandse titel)
  3. Kandidaten zonder Open Library-record controleren we, alleen zolang er nog plekken vrij zijn, in Google Books
  4. Kies de beste k: overwegend recente boeken, hooguit een paar klassiekers, en een paar Nederlandstalige boeken
"""

import asyncio
import datetime
import json
import logging
import os
import re
import unicodedata
import httpx
from dataclasses import dataclass
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

GROQ_MODEL = 'openai/gpt-oss-120b'

log = logging.getLogger('uvicorn.error')

# Zonder persoonsgegevens: Open Library vraagt om een herkenbare User-Agent.
USER_AGENT = 'BookCompass/1.0 (https://bookcompass.nl)'

# Zoveel meer kandidaten vragen we dan we tonen, omdat een deel de controle niet haalt.
CANDIDATE_FACTOR = 2
MAX_CANDIDATES = 20

# "Recent" = de laatste 25 jaar. Oudere boeken zijn klassiekers; daarvan tonen we er hooguit een paar.
RECENT_YEARS = 25
MAX_CLASSICS = 2

# Bij Nederlandstalige bezoekers proberen we minstens zoveel oorspronkelijk Nederlandstalige boeken te tonen.
MIN_DUTCH = 3

# Open Library afremmen we niet: hooguit zoveel zoekopdrachten tegelijk.
OL_CONCURRENCY = 5


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
    dutch_title: str | None = None
    original_language: str | None = None
    source: str = 'openlibrary'
    source_id: str = ''
    isbn: str = ''


def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value <= datetime.date.today().year else None
    if isinstance(value, str):
        m = re.search(r'\b(1[0-9]{3}|20[0-9]{2})\b', value)
        return _parse_year(int(m.group(1))) if m else None
    return None


def _norm(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode().lower())


def _surname(author: str) -> str:
    parts = (author or '').replace(',', ' ').split()
    return _norm(parts[-1]) if parts else ''


def _title_matches(wanted: str, found: str) -> bool:
    """Titels kloppen als de een met de ander begint (ondertitels en 'Lijmen/Het been' tellen mee)."""
    wanted, found = _norm(wanted), _norm(found)
    return bool(wanted and found) and (found.startswith(wanted) or wanted.startswith(found))


def _same_author(author: str, found_authors: list[str]) -> bool:
    """
    De achternaam moet de achternaam van een gevonden auteur zijn (of de volledige naam gelijk).
    Alleen 'zit erin' is te ruim: dan past "Graham Graham" op "Graham Greene".
    """
    surname = _surname(author)
    return bool(surname) and any(
        _surname(name) == surname or _norm(name) == _norm(author) for name in found_authors
    )


def _same_book(titles: list[str], author: str, found_title: str, found_authors: list[str]) -> bool:
    """Klopt een gevonden record echt bij een van de gevraagde titels en de auteur?"""
    return _same_author(author, found_authors) and any(_title_matches(t, found_title) for t in titles if t)


def _latin(value: str) -> bool:
    """Alleen titels en namen in Latijns schrift nemen we over uit een bron."""
    return bool(value) and all(ord(c) < 0x250 or not c.isalpha() for c in value)


def _parse_books(raw: str) -> list[dict]:
    """
    Lees de JSON-lijst van het model. Is de lijst als geheel ongeldig (afgekapt of één kapot object),
    dan lezen we de objecten los, zodat één fout niet alle tips kost.
    """
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


def _queries(title: str, dutch_title: str) -> list[tuple[str, bool]]:
    """
    Zoekvolgorde: eerst de Nederlandse titel (als het model die gaf), dan de originele titel.
    Het tweede element zegt of een match via die zoekopdracht de Nederlandse titel bevestigt.
    """
    pairs = [(dutch_title, True)] if dutch_title and _norm(dutch_title) != _norm(title) else []
    return pairs + [(title, False)]


def _clean(value: str) -> str:
    return re.sub(r'[()":\\]', ' ', value).strip()


async def _ol_lookup(title: str, dutch_title: str, author: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> dict:
    """
    Zoek een kandidaat in Open Library. Een veldzoekopdracht op title: matcht ook de titels van edities,
    dus een treffer op de Nederlandse titel bewijst dat er een Nederlandse uitgave met die titel bestaat.
    """
    for query_title, is_dutch in _queries(title, dutch_title):
        q = f'title:({_clean(query_title)}) author:({_clean(_surname_raw(author))})' if is_dutch else f'{query_title} {author}'
        try:
            async with sem:
                r = await client.get(
                    'https://openlibrary.org/search.json',
                    params={'q': q, 'limit': 3, 'fields': 'title,author_name,cover_i,subject,first_publish_year,key'},
                    timeout=10,
                )
            if not r.is_success:
                continue
            for doc in r.json().get('docs', []):
                if _same_book([title, dutch_title], author, doc.get('title', ''), doc.get('author_name', [])):
                    cover_id = doc.get('cover_i')
                    return {
                        'source': 'openlibrary',
                        'title': doc.get('title', ''),
                        'author': next((a for a in doc.get('author_name', []) if _same_author(author, [a])), ''),
                        'ol_key': doc.get('key', ''),
                        'subjects': doc.get('subject', [])[:8],
                        'cover_url': f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None,
                        'year': _parse_year(doc.get('first_publish_year')),
                        'dutch_confirmed': is_dutch,
                    }
        except Exception:
            continue
    return {}


def _surname_raw(author: str) -> str:
    parts = (author or '').replace(',', ' ').split()
    return parts[-1] if parts else ''


async def _gb_lookup(title: str, dutch_title: str, author: str, client: httpx.AsyncClient) -> dict:
    """Tweede bron voor boeken die Open Library niet kent (vaak Nederlandstalige uitgaven)."""
    key = os.getenv('GOOGLE_BOOKS_API_KEY', '')
    for query_title, is_dutch in _queries(title, dutch_title):
        params = {
            'q': f'intitle:"{_clean(query_title)}" inauthor:"{_clean(_surname_raw(author))}"',
            'maxResults': 5,
            'printType': 'books',
            'fields': 'items(id,volumeInfo(title,authors,publishedDate,categories,imageLinks/thumbnail,language))',
        }
        if key:
            params['key'] = key
        try:
            r = await client.get('https://www.googleapis.com/books/v1/volumes', params=params, timeout=8)
            if r.status_code == 429:  # dagquotum op: stoppen, niet blijven proberen
                return {}
            if not r.is_success:
                continue
            for item in r.json().get('items', []):
                info = item.get('volumeInfo', {})
                # Bij Google Books is elke treffer een editie: voor de Nederlandse titel moet die titel zelf kloppen.
                if _same_book([query_title], author, info.get('title', ''), info.get('authors', [])):
                    thumb = (info.get('imageLinks') or {}).get('thumbnail', '').replace('http://', 'https://')
                    return {
                        'source': 'google_books',
                        'title': info.get('title', ''),
                        'author': next((a for a in info.get('authors', []) if _same_author(author, [a])), ''),
                        'source_id': item.get('id', ''),
                        # ISBN-13, zodat WordPress er een eigen boekrecord van kan maken.
                        'isbn': next((i['identifier'] for i in info.get('industryIdentifiers', []) if i.get('type') == 'ISBN_13'), ''),
                        'ol_key': '',
                        'subjects': info.get('categories', [])[:8],
                        'cover_url': thumb or None,
                        # Het jaar van Google Books is vaak dat van een herdruk; alleen als laatste redmiddel.
                        'year': _parse_year(info.get('publishedDate', '')),
                        'dutch_confirmed': is_dutch,
                    }
        except Exception:
            continue
    return {}


def _year(item: dict, meta: dict) -> int | None:
    """
    Het jaar van eerste verschijning. Het taalmodel kent dat beter dan de bronnen: Open Library geeft vaak
    het jaar van een herdruk of vertaling, en soms een te vroeg jaar door een verkeerd gekoppelde editie
    (1969 voor The Idiot van Elif Batuman uit 2017). Google Books geeft altijd een editiejaar.
    Bronjaren gebruiken we alleen als het model geen jaar gaf. WordPress corrigeert bekende fouten (Book::CORRECTIONS).
    """
    return _parse_year(item.get('year')) or meta.get('year')


def _select(found: list[tuple[dict, dict]], k: int, lang: str) -> list[tuple[dict, dict]]:
    """
    Kies de beste k uit de gecontroleerde kandidaten (die staan al in volgorde van match):
    hooguit MAX_CLASSICS klassiekers en, bij Nederlands, minstens MIN_DUTCH Nederlandstalige boeken als die er zijn.
    Is de lijst daarna niet vol, dan vullen we aan met de overige klassiekers: liever een klassieker dan een lege plek.
    """
    cutoff = datetime.date.today().year - RECENT_YEARS
    is_old = lambda pair: (_year(*pair) or cutoff) < cutoff
    is_dutch = lambda pair: (pair[0].get('lang') or '').lower() == 'nl'

    chosen, old = [], 0
    for pair in found:
        if is_old(pair):
            if old >= MAX_CLASSICS:
                continue
            old += 1
        chosen.append(pair)

    if lang == 'nl':
        top = chosen[:k]
        dutch_extra = [p for p in chosen[k:] if is_dutch(p)]
        while dutch_extra and sum(map(is_dutch, top)) < MIN_DUTCH:
            # Vervang de laagst geplaatste niet-Nederlandse tip door de best passende Nederlandse.
            idx = max(i for i, p in enumerate(top) if not is_dutch(p))
            top[idx] = dutch_extra.pop(0)
        top.sort(key=found.index)
        chosen = top + [p for p in chosen[k:] if p not in top]

    if len(chosen) < k:
        chosen += [p for p in found if p not in chosen][: k - len(chosen)]

    return chosen[:k]


LANG_NAMES = {'nl': 'Dutch', 'en': 'English'}


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
) -> list[Recommendation]:

    groq_client = AsyncGroq(api_key=os.getenv('GROQ_API_KEY'))
    lang_name = LANG_NAMES.get(lang, LANG_NAMES['nl'])
    dutch = lang == 'nl'
    n = min(MAX_CANDIDATES, k * CANDIDATE_FACTOR)
    recent_from = datetime.date.today().year - RECENT_YEARS

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

    # Nederlandse lezers: een deel oorspronkelijk Nederlandstalig, de rest bij voorkeur in het Nederlands vertaald.
    dutch_rules = (
        f'\n- The reader is Dutch. About a third of the books should be originally written in Dutch '
        f'(Dutch or Flemish authors), but only ones that genuinely fit and that you know well: '
        f'never make up a plausible-sounding Dutch title. The rest may be translated books, '
        f'preferably ones available in Dutch translation'
        f'\n- "dutch_title": for a translated book, the title of its published Dutch translation, '
        f'only if you are certain it exists; otherwise null. Null for Dutch originals'
    ) if dutch else ''
    dutch_field = ', "dutch_title": null' if dutch else ''

    prompt = f"""You are an expert book recommender. Suggest {n} existing, published books for a reader who liked:

"{book_title}" by {book_author}
Subjects: {subjects_str}
Description: {book_description[:500]}

{focus}{selected_note}{heaviness_note}

Rules:
- Not by {book_author}, and not "{book_title}" itself
- Only real books you are certain exist, with the exact original title and the correct author. Never invent or guess; fewer books is better than a wrong one
- Mostly books first published in {recent_from} or later. At most 2 older classics, and only if they fit exceptionally well
- Mix well-known and lesser-known books. Best match first{dutch_rules}
- "year": year of first publication in the original language
- "lang": original language as ISO 639-1 code
- "reason": 1-2 sentences in {lang_name} on why it fits

Return ONLY a JSON array:
[{{"title": "", "author": "", "year": 2015, "lang": "en"{dutch_field}, "reason": ""}}]"""

    response = await groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.4,
        max_tokens=4000,
        reasoning_effort='low',
    )

    raw = (response.choices[0].message.content or '').strip()
    books_raw = _parse_books(raw)
    if not books_raw:
        log.warning(
            'recommend "%s": no books in model output (finish_reason=%s, %d chars): %s',
            book_title, response.choices[0].finish_reason, len(raw), raw[:300],
        )
        return []

    input_title, input_surname = _norm(book_title), _surname(book_author)
    candidates, seen = [], set()
    for b in books_raw[:n]:
        if not isinstance(b.get('title'), str) or not isinstance(b.get('author'), str):
            continue
        # Het model zet soms harde spaties of dubbele spaties in namen.
        b['title'], b['author'] = ' '.join(b['title'].split()), ' '.join(b['author'].split())
        if not b['title'] or not b['author']:
            continue
        key = _norm(b['title']) + '|' + _surname(b['author'])
        # Het model noemt soms toch het boek zelf of de auteur; dat is geen ontdekking.
        if key in seen or _surname(b['author']) == input_surname or (input_title and _title_matches(b['title'], book_title)):
            continue
        seen.add(key)
        candidates.append(b)

    def args(b: dict) -> tuple[str, str, str]:
        return b['title'].strip(), (b.get('dutch_title') or '').strip(), b['author']

    headers = {'User-Agent': USER_AGENT}
    async with httpx.AsyncClient(timeout=10, headers=headers) as http:
        sem = asyncio.Semaphore(OL_CONCURRENCY)
        metas = list(await asyncio.gather(*(_ol_lookup(*args(b), http, sem) for b in candidates)))

        # Google Books alleen voor wat Open Library niet kent, en alleen zoveel als nodig om k te halen.
        # Nederlandstalige boeken eerst: die ontbreken het vaakst in Open Library.
        missing = [i for i, m in enumerate(metas) if not m]
        missing.sort(key=lambda i: (candidates[i].get('lang') != 'nl', i))
        needed = k - (len(candidates) - len(missing))
        if needed > 0 and missing:
            todo = missing[: needed + 2]
            extra = await asyncio.gather(*(_gb_lookup(*args(candidates[i]), http) for i in todo))
            for i, meta in zip(todo, extra):
                metas[i] = meta

    # Alleen boeken die in minstens één bron bestaan: liever minder aanbevelingen dan verzonnen titels.
    # Ontdubbelen op het gevonden record: het model noemt hetzelfde boek soms twee keer (bijv. als Engels én Nederlands).
    found, records = [], set()
    for item, meta in zip(candidates, metas):
        record = meta.get('ol_key') or meta.get('source_id')
        if meta and record not in records:
            records.add(record)
            found.append((item, meta))
    selected = _select(found, k, lang)
    usage = getattr(response, 'usage', None)
    log.info(
        'recommend "%s": %d candidates, %d via Open Library, %d via Google Books, %d shown, %s tokens; not found: %s',
        book_title, len(candidates), sum(m.get('source') == 'openlibrary' for m in metas),
        sum(m.get('source') == 'google_books' for m in metas), len(selected), getattr(usage, 'total_tokens', '?'),
        '; '.join(f"{c['title']} ({c['author']})" for c, m in zip(candidates, metas) if not m) or '-',
    )

    results = []
    for i, (item, meta) in enumerate(selected):
        # Alleen een Nederlandse titel die een bron heeft bevestigd: het model verzint die anders weleens.
        dutch_title = (item.get('dutch_title') or '').strip() if meta.get('dutch_confirmed') else None
        # De titel van het model is meestal netter dan die van de bron (die bevat soms datums of "A Novel").
        # Een ondertitel na de dubbele punt laten we weg als de bron het boek ook zonder die ondertitel kent.
        title = item['title']
        head = title.split(':')[0].strip()
        if head != title and _title_matches(head, meta.get('title', '')):
            title = head
        # Bij meerdere auteurs ("A & B") houden we de naam van het model, anders valt er een weg.
        several = re.search(r'\s(?:&|and|en)\s', item['author'])
        author = meta.get('author') if _latin(meta.get('author', '')) and not several else item['author']
        results.append(Recommendation(
            title=title.strip(),
            author=author.strip(),
            description='',
            subjects=meta.get('subjects', []),
            cover_url=meta.get('cover_url'),
            ol_key=meta.get('ol_key', ''),
            score=round(max(0.5, 1.0 - i * 0.04), 2),
            explanation=item.get('reason', ''),
            year=_year(item, meta),
            dutch_title=dutch_title if dutch_title and _norm(dutch_title) != _norm(title) else None,
            original_language=(item.get('lang') or '').lower()[:2] or None,
            source=meta.get('source', 'openlibrary'),
            source_id=meta.get('source_id', ''),
            isbn=meta.get('isbn', ''),
        ))

    return results
