"""
groq_recommender.py — Aanbevelingen via Groq LLM, gecontroleerd tegen Open Library en Google Books.

Workflow:
  1. Vraag Groq (GPT-OSS 120B) om meer kandidaten dan nodig (k + CANDIDATE_EXTRA), met jaar,
     originele taal en (voor Nederlandse lezers) de titel van de Nederlandse vertaling
  2. Controleer elke kandidaat concurrent: eerst Open Library, dan Google Books als terugval,
     telkens eerst op de Nederlandse titel (dan is die bevestigd) en daarna op de originele titel.
     Titel én auteur moeten kloppen; anders is het boek vrijwel zeker verzonnen.
  3. Zijn er na controle minder dan k over, dan vragen we één keer bij (zonder de al genoemde titels)
  4. Kies de beste k: overwegend recente boeken, hooguit een paar klassiekers, en bij Nederlandse
     lezers een paar oorspronkelijk Nederlandstalige boeken
"""

import asyncio
import datetime
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

# "Recent" = de laatste 25 jaar. Oudere boeken zijn klassiekers; daarvan tonen we er hooguit een paar.
RECENT_YEARS = 25
MAX_CLASSICS = 2
# Bij Nederlandstalige bezoekers proberen we minstens zoveel oorspronkelijk Nederlandstalige boeken te tonen.
MIN_DUTCH = 3


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
    # Titel van de Nederlandse vertaling (alleen als een bron die bevestigt) en originele taal (ISO 639-1).
    dutch_title: str | None = None
    original_language: str | None = None
    # Waar het boek gecontroleerd is: "openlibrary" (ol_key gevuld) of "google_books" (source_id = volume-id).
    source: str = 'openlibrary'
    source_id: str = ''
    isbn: str = ''


# ── Hulpfuncties voor vergelijken ─────────────────────────────────────────────

def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value <= datetime.date.today().year else None
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


def _latin(value: str) -> bool:
    """Alleen titels en namen in Latijns schrift nemen we over uit een bron."""
    return bool(value) and all(ord(c) < 0x250 or not c.isalpha() for c in value)


def _clean_query(value: str) -> str:
    return re.sub(r'[()":\\\[\]]', ' ', value or '').strip()


# ── Controle tegen bronnen ────────────────────────────────────────────────────

def _queries(title: str, dutch_title: str) -> list[tuple[str, bool]]:
    """
    Zoekvolgorde: eerst de Nederlandse titel (als het model die gaf), dan de originele titel.
    Het tweede element zegt of een treffer via die zoekopdracht de Nederlandse titel bevestigt.
    """
    pairs = [(dutch_title, True)] if dutch_title and _norm(dutch_title) != _norm(title) else []
    return pairs + [(title, False)]


def _source_author(author: str, found_authors: list[str]) -> str:
    return next((a for a in found_authors or [] if author_matches(author, [a])), '')


async def _ol_lookup(title: str, author: str, client: httpx.AsyncClient, also_title: str = '') -> dict:
    """
    Zoek de kandidaat in Open Library; alleen een treffer met dezelfde titel én auteur telt.

    Met `also_title` zoeken we op een vertaalde titel (`title`, de Nederlandse) via de veldsyntax
    `title:(...)`: die matcht ook editietitels, de `title=`-parameter niet. Het gevonden werk heeft dan vaak
    de originele titel (`also_title`); die mag ook kloppen. Een treffer bewijst zo dat er een uitgave
    met de Nederlandse titel bestaat.
    """
    search_title = _clean_query(_main_title(title))
    search_author = _clean_query(_surname(author) or author)
    params = {'limit': 5, 'fields': 'key,title,author_name,cover_i,subject,first_publish_year'}
    if also_title:
        params['q'] = f'title:({search_title}) author:({search_author})'
    else:
        params.update(title=search_title, author=search_author)
    try:
        r = await client.get('https://openlibrary.org/search.json', params=params, timeout=LOOKUP_TIMEOUT)
        if not r.is_success:
            return {}
        for doc in r.json().get('docs', []):
            if not doc.get('key') or not any(
                same_book(t, author, doc.get('title', ''), doc.get('author_name', [])) for t in (title, also_title) if t
            ):
                continue
            cover_id = doc.get('cover_i')
            return {
                'source': 'openlibrary',
                'title': doc.get('title', ''),
                'author': _source_author(author, doc.get('author_name', [])),
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
            # Bij Google Books is elke treffer een editie: de gezochte titel zelf moet kloppen.
            return {
                'source': 'google_books',
                'title': info.get('title', ''),
                'author': _source_author(author, info.get('authors', [])),
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
    """
    Eerst Open Library, dan Google Books; per bron eerst de Nederlandse titel, dan de originele.
    `dutch_confirmed` zegt of de treffer via de Nederlandse titel kwam (dan tonen we die titel).
    """
    title, author = item['title'], item['author']
    dutch_title = item.get('dutch_title') if isinstance(item.get('dutch_title'), str) else ''
    dutch_title = ' '.join(dutch_title.split())
    async with sem:
        for query_title, is_dutch in _queries(title, dutch_title):
            meta = await _ol_lookup(query_title, author, client, also_title=title if is_dutch else '')
            if meta:
                return {**meta, 'dutch_confirmed': is_dutch}
        for query_title, is_dutch in _queries(title, dutch_title):
            meta = await _gb_lookup(query_title, author, client)
            if meta:
                return {**meta, 'dutch_confirmed': is_dutch}
    return {}


def _year(item: dict, meta: dict) -> int | None:
    """
    Jaar van eerste verschijning. Het model kent dat meestal beter dan de bronnen: Google Books geeft
    het jaar van een editie (vaak een herdruk) en Open Library soms een te vroeg jaar door een verkeerd
    gekoppelde editie (1969 voor The Idiot van Elif Batuman uit 2017). Het bronjaar is de terugval.
    """
    return _parse_year(item.get('year')) or meta.get('year')


def select(found: list[tuple[dict, dict]], k: int, lang: str) -> list[tuple[dict, dict]]:
    """
    Kies de beste k uit de gecontroleerde kandidaten (die staan al in volgorde van match):
    hooguit MAX_CLASSICS klassiekers en, bij Nederlands, minstens MIN_DUTCH Nederlandstalige boeken als die er zijn.
    Is de lijst daarna niet vol, dan vullen we aan met de overige klassiekers: liever een klassieker dan een lege plek.
    """
    cutoff = datetime.date.today().year - RECENT_YEARS

    def is_old(pair):
        return (_year(*pair) or cutoff) < cutoff

    def is_dutch(pair):
        lang_ = pair[0].get('lang')
        return isinstance(lang_, str) and lang_.strip().lower()[:2] == 'nl'

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
        while dutch_extra and sum(map(is_dutch, top)) < MIN_DUTCH and any(not is_dutch(p) for p in top):
            # Vervang de laagst geplaatste niet-Nederlandse tip door de best passende Nederlandse.
            idx = max(i for i, p in enumerate(top) if not is_dutch(p))
            top[idx] = dutch_extra.pop(0)
        top.sort(key=found.index)
        chosen = top + [p for p in chosen[k:] if p not in top]

    if len(chosen) < k:
        chosen += [p for p in found if p not in chosen][: k - len(chosen)]

    return chosen[:k]


def display_title_author(item: dict, meta: dict) -> tuple[str, str]:
    """
    De titel van het model is meestal netter dan die van de bron (die bevat soms datums of "A Novel").
    Een ondertitel na de dubbele punt laten we weg als de bron het boek ook zonder die ondertitel kent.
    De spelling van de auteursnaam nemen we van de bron als het dezelfde naam is op accenten en hoofdletters
    na ('Leila Slimani' -> 'Leïla Slimani'); een langere of andere vorm ('Gerard Kornelis van het Reve'),
    niet-Latijns schrift of meerdere auteurs laten we bij de naam van het model.
    """
    title = item['title']
    head = title.split(':')[0].strip()
    if head != title and head and _norm(meta.get('title', '')) == _norm(head):
        title = head
    several = re.search(r'\s(?:&|and|en)\s', item['author'])
    source_author = meta.get('author', '')
    same_name = _norm(source_author) == _norm(item['author'])
    author = source_author if same_name and _latin(source_author) and not several else item['author']
    return title.strip(), author.strip()


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
        # Ook de Nederlandse titel telt: de site kent een eerder getoond boek mogelijk onder die titel.
        dutch_title = b.get('dutch_title') if isinstance(b.get('dutch_title'), str) else ''
        names = [title] + ([dutch_title] if dutch_title.strip() else [])
        if any(title_matches(n, t) for n in names for t in blocked_titles if t):
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
    dutch = lang == 'nl'
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
    avoid_note = (
        '\n- Do NOT recommend any of these (already shown or rejected): '
        + '; '.join(f'"{t}"' for t in avoid_titles)
        if avoid_titles else ''
    )

    # Nederlandse lezers: een deel oorspronkelijk Nederlandstalig, de rest bij voorkeur in het Nederlands vertaald.
    dutch_rules = (
        '\n- The reader is Dutch. About a third of the books should be originally written in Dutch '
        '(Dutch or Flemish authors), but only ones that genuinely fit and that you know well: '
        'never make up a plausible-sounding Dutch title. The rest may be translated books, '
        'preferably ones available in Dutch translation'
        '\n- "dutch_title": for a translated book, the title of its published Dutch translation, '
        'only if you are certain it exists; otherwise null. Null for Dutch originals'
    ) if dutch else ''
    dutch_field = '\n    "dutch_title": null,' if dutch else ''

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
- Mostly books first published in {recent_from} or later. At most {MAX_CLASSICS} older classics, \
and only if they fit exceptionally well
- Prefer books you know well over obscure ones you are unsure about. Include both well-known and lesser-known books
- Vary the geographic origins{dutch_rules}
- Best match first
- "year": year of first publication in the original language
- "lang": original language as ISO 639-1 code
- The "reason" field must be in {lang_name} (2-3 sentences explaining why this book fits)

Return ONLY a valid JSON array, no other text:
[
  {{
    "title": "Original Title",
    "author": "Author Full Name",
    "year": 1999,
    "lang": "en",{dutch_field}
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
        '%d with Dutch title (%d confirmed), %d rejected in %.1fs; rejected: %s',
        book_title, rounds, len(verified),
        sum(m['source'] == 'openlibrary' for _, m in verified),
        sum(m['source'] == 'google_books' for _, m in verified),
        sum(bool(i.get('dutch_title')) for i, _ in verified),
        sum(bool(m.get('dutch_confirmed')) for _, m in verified),
        len(rejected), time.monotonic() - started,
        '; '.join(f"{c['title']} ({c['author']})" for c in rejected) or '-',
    )

    results = []
    for i, (item, meta) in enumerate(select(verified, k, lang)):
        title, author = display_title_author(item, meta)
        # Alleen een Nederlandse titel die een bron heeft bevestigd: het model verzint die anders weleens.
        dutch_title = ' '.join(item['dutch_title'].split()) if meta.get('dutch_confirmed') else None
        lang_ = item.get('lang') if isinstance(item.get('lang'), str) else ''
        results.append(Recommendation(
            title=title,
            author=author,
            description='',
            subjects=meta.get('subjects', []),
            cover_url=meta.get('cover_url'),
            ol_key=meta.get('ol_key', ''),
            score=round(max(0.5, 1.0 - i * 0.04), 2),
            explanation=item.get('reason', '') if isinstance(item.get('reason'), str) else '',
            year=_year(item, meta),
            dutch_title=dutch_title if dutch_title and _norm(dutch_title) != _norm(title) else None,
            original_language=lang_.strip().lower()[:2] or None,
            source=meta.get('source', 'openlibrary'),
            source_id=meta.get('source_id', ''),
            isbn=meta.get('isbn', ''),
        ))

    return results
