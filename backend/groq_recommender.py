"""
groq_recommender.py — Aanbevelingen via Groq LLM + Google Books verrijking.

Workflow:
  1. Stuur boekmetadata naar Groq (Llama 3.3 70B)
  2. Groq geeft een JSON-lijst terug met aanbevelingen + Nederlandse uitleg
  3. Verrijk elk resultaat concurrent met covers en metadata via Google Books API
"""

import asyncio
import json
import os
import re
import httpx
from dataclasses import dataclass
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

GROQ_MODEL = 'llama-3.3-70b-versatile'


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


def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = re.search(r'\b(1[0-9]{3}|20[0-2][0-9])\b', value)
        return int(m.group(1)) if m else None
    return None


async def _enrich(title: str, author: str, client: httpx.AsyncClient) -> dict:
    """Haal cover, beschrijving en metadata op via Open Library Search API."""
    query = f'{title} {author}'
    try:
        r = await client.get(
            'https://openlibrary.org/search.json',
            params={'q': query, 'limit': 1, 'fields': 'title,author_name,cover_i,subject,first_publish_year,isbn,key'},
            timeout=8,
        )
        if not r.is_success:
            return {}
        docs = r.json().get('docs', [])
        if not docs:
            return {}
        doc = docs[0]
        cover_id = doc.get('cover_i')
        cover = f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None
        isbns = doc.get('isbn', [])
        isbn = next((i for i in isbns if len(i) == 13), isbns[0] if isbns else '')
        ol_key = doc.get('key', f'/isbn/{isbn}' if isbn else '')
        return {
            'description': '',
            'subjects': doc.get('subject', [])[:8],
            'cover_url': cover,
            'year': _parse_year(doc.get('first_publish_year')),
            'ol_key': ol_key,
        }
    except Exception:
        return {}


async def recommend(
    book_title: str,
    book_author: str,
    book_description: str,
    book_subjects: list[str],
    style_weight: float = 3.0,
    topic_weight: float = 3.0,
    selected_subjects: list[str] | None = None,
    k: int = 10,
) -> list[Recommendation]:

    groq_client = AsyncGroq(api_key=os.getenv('GROQ_API_KEY'))

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

    subjects_str = ', '.join(book_subjects[:8]) if book_subjects else 'not specified'
    selected_note = (
        f'\nThe user is especially interested in: {", ".join(selected_subjects)}.'
        if selected_subjects else ''
    )

    prompt = f"""You are an expert book recommender. Recommend {k} books similar to the one below.

Book: "{book_title}" by {book_author}
Genres/subjects: {subjects_str}
Description: {book_description[:600]}

{focus}{selected_note}

Rules:
- Do NOT recommend books by {book_author}
- Do NOT recommend "{book_title}" itself
- Include both well-known and lesser-known books
- Vary the time periods and geographic origins
- The "reason" field must be in Dutch (2-3 sentences explaining why this book fits)

Return ONLY a valid JSON array, no other text:
[
  {{
    "title": "Book Title",
    "author": "Author Name",
    "reason": "Nederlandse uitleg waarom dit boek aansluit bij het invoerboek."
  }}
]"""

    response = await groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.7,
        max_tokens=2048,
    )

    raw = response.choices[0].message.content.strip()

    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        return []
    try:
        books_raw = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return []

    valid = [b for b in books_raw[:k] if b.get('title') and b.get('author')]

    # Verrijk alle boeken concurrent via Google Books
    async with httpx.AsyncClient(timeout=10) as http:
        metas = await asyncio.gather(*(
            _enrich(b['title'], b['author'], http) for b in valid
        ))

    results = []
    for i, (item, meta) in enumerate(zip(valid, metas)):
        results.append(Recommendation(
            title=item['title'].strip(),
            author=item['author'].strip(),
            description=meta.get('description', ''),
            subjects=meta.get('subjects', []),
            cover_url=meta.get('cover_url'),
            ol_key=meta.get('ol_key', ''),
            score=round(max(0.5, 1.0 - i * 0.04), 2),
            explanation=item.get('reason', ''),
            year=meta.get('year'),
        ))

    return results
