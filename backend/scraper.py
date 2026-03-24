import re
import httpx
from dataclasses import dataclass


@dataclass
class BookData:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    year: int | None


def _extract_key(url: str) -> tuple[str, str]:
    match = re.search(r"openlibrary\.org/(works|books)/(OL\w+)", url)
    if not match:
        raise ValueError(f"Geen geldige Open Library URL: {url}")
    return match.group(1), match.group(2)


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get("value", "")
    return value or ""


def _parse_year(value) -> int | None:
    """Haalt een 4-cijferig jaar uit een string of int."""
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", value)
        return int(m.group(1)) if m else None
    return None


async def fetch_book(url: str) -> BookData:
    kind, ol_id = _extract_key(url)

    async with httpx.AsyncClient(timeout=10) as client:
        if kind == "works":
            r = await client.get(f"https://openlibrary.org/works/{ol_id}.json")
            r.raise_for_status()
            work = r.json()

            title       = work.get("title", "Onbekend")
            description = _text(work.get("description", ""))
            subjects    = work.get("subjects", [])[:10]
            cover_id    = (work.get("covers") or [None])[0]
            year        = _parse_year(work.get("first_publish_date"))

            # Jaar via search-API als het werk het niet heeft
            if not year:
                sr = await client.get(
                    "https://openlibrary.org/search.json",
                    params={"q": f"key:/works/{ol_id}", "fields": "first_publish_year", "limit": 1},
                )
                if sr.is_success:
                    docs = sr.json().get("docs", [])
                    if docs:
                        year = _parse_year(docs[0].get("first_publish_year"))

            author = "Onbekend"
            authors_ref = work.get("authors", [])
            if authors_ref:
                author_key = authors_ref[0].get("author", {}).get("key", "")
                if author_key:
                    ar = await client.get(f"https://openlibrary.org{author_key}.json")
                    if ar.is_success:
                        author = ar.json().get("name", "Onbekend")

        else:
            r = await client.get(f"https://openlibrary.org/books/{ol_id}.json")
            r.raise_for_status()
            edition = r.json()

            title       = edition.get("title", "Onbekend")
            description = _text(edition.get("description", ""))
            subjects    = edition.get("subjects", [])[:10]
            cover_id    = (edition.get("covers") or [None])[0]
            year        = _parse_year(
                edition.get("publish_date") or edition.get("first_publish_date")
            )

            work_key = (edition.get("works") or [{}])[0].get("key", "")
            if work_key and not description:
                wr = await client.get(f"https://openlibrary.org{work_key}.json")
                if wr.is_success:
                    work_data = wr.json()
                    description = _text(work_data.get("description", ""))
                    subjects    = subjects or work_data.get("subjects", [])[:10]
                    if not year:
                        year = _parse_year(work_data.get("first_publish_date"))

            author = "Onbekend"
            author_keys = edition.get("authors", [])
            if author_keys:
                ak = author_keys[0].get("key", "")
                if ak:
                    ar = await client.get(f"https://openlibrary.org{ak}.json")
                    if ar.is_success:
                        author = ar.json().get("name", "Onbekend")

    cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None

    if not description:
        description = f"{title} by {author}. Subjects: {', '.join(subjects)}"

    return BookData(
        title=title,
        author=author,
        description=description,
        subjects=subjects,
        cover_url=cover_url,
        ol_key=f"/{kind}/{ol_id}",
        year=year,
    )
