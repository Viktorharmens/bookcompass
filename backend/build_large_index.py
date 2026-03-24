"""
build_large_index.py — Bouw een grote FAISS HNSW-index met ~50.000 boeken.

Bronnen (automatisch, geen API-key nodig):
  1. CMU Book Summary Dataset   — 16.559 boeken met plotsamenvattingen
  2. Open Library Genre Harvest — ~35.000 extra boeken via de gratis OL search API

Totaal: ~50.000 unieke Engelstalige boeken.

FAISS index-type: IndexHNSWFlat (M=32)
  - Approximate Nearest Neighbor: O(log n) i.p.v. O(n)
  - Query op 50k boeken: <1ms i.p.v. ~50ms met FlatIP
  - Recall@10 > 97% met ef_search=64
  - Geschikt voor hosting: index ~120MB, SQLite ~40MB

Gebruik:
    python build_large_index.py
    python build_large_index.py --skip-cmu      # alleen OL harvest
    python build_large_index.py --skip-ol       # alleen CMU
    python build_large_index.py --max-ol 10000  # minder OL-boeken

Na afloop: herstart de backend — hij gebruikt automatisch de nieuwe index.
"""

import argparse
import asyncio
import json
import os
import re
import sqlite3
import tarfile
import time
import urllib.request
import numpy as np
import faiss
import httpx

from sentence_transformers import SentenceTransformer

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
DB_PATH    = os.path.join(DATA_DIR, "books.db")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_combined.index")
MODEL_NAME = "all-MiniLM-L6-v2"
DIM        = 384
BATCH_SIZE = 64

# HNSW parameters
HNSW_M              = 32   # verbindingen per node — hogere M = beter recall, meer geheugen
HNSW_EF_CONSTRUCT   = 200  # kwaliteit bij bouwen — hogere waarde = langzamer maar beter
HNSW_EF_SEARCH      = 64   # kwaliteit bij zoeken — kan later aangepast worden

CMU_URL = "http://www.cs.cmu.edu/~dbamman/data/booksummaries.tar.gz"
CMU_TAR = os.path.join(DATA_DIR, "booksummaries.tar.gz")
CMU_TXT = os.path.join(DATA_DIR, "booksummaries.txt")

# Open Library genres om te harvesten
OL_SUBJECTS = [
    "fiction", "literary_fiction", "historical_fiction", "science_fiction",
    "fantasy", "mystery", "thriller", "horror", "romance", "adventure",
    "biography", "autobiography", "memoir", "history", "philosophy",
    "psychology", "classic_literature", "contemporary_fiction",
    "short_stories", "poetry", "drama", "crime_fiction",
    "dystopian_fiction", "magical_realism", "graphic_novels",
    "young_adult_fiction", "childrens_literature", "war_stories",
    "political_fiction", "satire", "coming_of_age",
]

TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "gothic", "surreal", "intimate", "epic", "sparse",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]

os.makedirs(DATA_DIR, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", value)
        return int(m.group(1)) if m else None
    return None


def style_text(desc: str, subjects: list) -> str:
    combined = (desc + " " + " ".join(subjects)).lower()
    found = [kw for kw in TONE_KEYWORDS if kw in combined]
    if found:
        return "Writing style: " + ", ".join(found[:8])
    return " ".join(desc.split()[:60])


def embed_text(book: dict) -> str:
    desc     = book.get("description") or f"{book['title']} by {book.get('author','')}"
    subjects = book.get("subjects", [])
    genres   = ("Genres: " + ", ".join(subjects[:6])) if subjects else ""
    style    = style_text(desc, subjects)
    return desc[:600] + " " + genres + " " + style


def _progress(block, block_size, total):
    done = min(block * block_size, total)
    pct  = done / total * 100 if total > 0 else 0
    bar  = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"\r  [{bar}] {pct:.0f}%  ({done//1024}KB / {total//1024}KB)", end="", flush=True)


# ── FAISS HNSW index ───────────────────────────────────────────────────────────

def create_hnsw_index() -> faiss.Index:
    index = faiss.IndexHNSWFlat(DIM, HNSW_M)
    index.hnsw.efConstruction = HNSW_EF_CONSTRUCT
    index.hnsw.efSearch        = HNSW_EF_SEARCH
    return index


def load_or_create_index() -> tuple[faiss.Index, int]:
    if os.path.exists(INDEX_PATH):
        print(f"  Bestaande index laden: {INDEX_PATH}")
        idx = faiss.read_index(INDEX_PATH)
        # Zorg dat efSearch goed is na laden
        if hasattr(idx, "hnsw"):
            idx.hnsw.efSearch = HNSW_EF_SEARCH
        return idx, idx.ntotal
    return create_hnsw_index(), 0


# ── Database ───────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            faiss_id    INTEGER UNIQUE,
            title       TEXT NOT NULL,
            author      TEXT,
            description TEXT,
            subjects    TEXT,
            cover_url   TEXT,
            ol_key      TEXT,
            isbn        TEXT,
            year        INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faiss ON books(faiss_id)")
    # Voeg year-kolom toe als die ontbreekt (backwards compat.)
    try:
        conn.execute("ALTER TABLE books ADD COLUMN year INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def get_existing_titles(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT title FROM books").fetchall()
    return {r[0].lower().strip() for r in rows}


def insert_batch(conn: sqlite3.Connection, faiss_start: int, books: list[dict]):
    rows = [
        (
            faiss_start + i,
            b["title"][:300],
            b.get("author", "")[:200],
            (b.get("description") or "")[:1000],
            json.dumps(b.get("subjects", [])),
            b.get("cover_url") or "",
            b.get("ol_key") or "",
            b.get("isbn") or "",
            b.get("year"),
        )
        for i, b in enumerate(books)
    ]
    conn.executemany("""
        INSERT OR IGNORE INTO books
            (faiss_id, title, author, description, subjects, cover_url, ol_key, isbn, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()


# ── Embedding & ingest ─────────────────────────────────────────────────────────

def ingest_books(model: SentenceTransformer, conn: sqlite3.Connection,
                 index: faiss.Index, books: list[dict], next_id: int,
                 label: str) -> int:
    existing = get_existing_titles(conn)
    new_books = [b for b in books if b["title"].lower().strip() not in existing]
    total     = len(new_books)

    if total == 0:
        print(f"  {label}: al volledig aanwezig, overgeslagen.")
        return next_id

    print(f"  {label}: {total} nieuwe boeken verwerken…")

    for start in range(0, total, BATCH_SIZE):
        batch = new_books[start : start + BATCH_SIZE]
        texts = [embed_text(b) for b in batch]
        vecs  = model.encode(
            texts, normalize_embeddings=True,
            batch_size=BATCH_SIZE, show_progress_bar=False,
        ).astype(np.float32)

        index.add(vecs)
        insert_batch(conn, next_id, batch)
        next_id += len(batch)

        # Voortgang
        done = min(start + BATCH_SIZE, total)
        pct  = done / total * 100
        print(f"\r    {done}/{total} ({pct:.0f}%)  {batch[-1]['title'][:45]:<45}", end="")

    print()
    return next_id


# ── Bron 1: CMU Book Summary Dataset ──────────────────────────────────────────

def download_cmu():
    if os.path.exists(CMU_TXT):
        return
    print("⬇  CMU Book Summaries downloaden (~14 MB)…")
    urllib.request.urlretrieve(CMU_URL, CMU_TAR, reporthook=_progress)
    print()
    with tarfile.open(CMU_TAR, "r:gz") as tar:
        for m in tar.getmembers():
            if m.name.endswith("booksummaries.txt"):
                m.name = os.path.basename(m.name)
                tar.extract(m, DATA_DIR)
                break
    os.remove(CMU_TAR)


def load_cmu() -> list[dict]:
    download_cmu()
    books = []
    with open(CMU_TXT, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            title   = parts[2].strip()
            author  = parts[3].strip()
            summary = parts[6].strip()
            if not title or len(summary) < 80:
                continue
            year = parse_year(parts[4])
            subjects = []
            try:
                subjects = list(json.loads(parts[5]).values())[:8]
            except Exception:
                pass
            books.append({
                "title": title, "author": author or "Onbekend",
                "description": summary[:800], "subjects": subjects,
                "year": year, "cover_url": None, "ol_key": "",
            })
    print(f"  CMU: {len(books)} boeken geladen")
    return books


# ── Bron 2: Open Library Genre Harvest ────────────────────────────────────────

async def fetch_ol_subject(client: httpx.AsyncClient, subject: str,
                            limit: int, offset: int) -> list[dict]:
    """Haalt boeken op voor één OL-subject (pagina van max 100)."""
    try:
        r = await client.get(
            f"https://openlibrary.org/subjects/{subject}.json",
            params={"limit": min(limit, 100), "offset": offset},
            timeout=20,
        )
        if not r.is_success:
            return []
        data  = r.json()
        works = data.get("works", [])
        books = []
        for w in works:
            title  = w.get("title", "").strip()
            if not title:
                continue
            authors  = [a.get("name", "") for a in w.get("authors", [])]
            author   = authors[0] if authors else "Onbekend"
            subjects = [s.get("name", s) if isinstance(s, dict) else str(s)
                        for s in w.get("subject", [])[:8]]
            cover_id = w.get("cover_id") or w.get("cover_edition_key")
            cover_url = (f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                         if isinstance(cover_id, int) else None)
            ol_key   = w.get("key", "")
            year     = parse_year(w.get("first_publish_year"))
            # Gebruik title + subjects als pseudo-beschrijving
            subj_str = ", ".join(subjects[:5])
            desc     = f"{title} by {author}. Topics: {subj_str}." if subj_str else f"{title} by {author}."
            books.append({
                "title": title, "author": author,
                "description": desc, "subjects": subjects,
                "year": year, "cover_url": cover_url, "ol_key": ol_key,
            })
        return books
    except Exception:
        return []


async def harvest_ol(max_books: int = 35000) -> list[dict]:
    """
    Haalt boeken op van OL via de gratis subjects-API.
    Pagineert door genres totdat max_books bereikt is.
    Respecteert rate-limit met kleine pauzes.
    """
    all_books: list[dict] = []
    seen_keys: set[str]   = set()

    per_subject = max(200, max_books // len(OL_SUBJECTS))

    async with httpx.AsyncClient(
        headers={"User-Agent": "BookRecommender/1.0 (educational project)"},
        timeout=30,
    ) as client:
        for subject in OL_SUBJECTS:
            if len(all_books) >= max_books:
                break

            subject_count = 0
            offset        = 0

            while subject_count < per_subject and len(all_books) < max_books:
                batch = await fetch_ol_subject(client, subject, 100, offset)
                if not batch:
                    break

                for book in batch:
                    key = book.get("ol_key") or book["title"].lower()
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_books.append(book)
                        subject_count += 1

                offset += 100
                if len(batch) < 100:
                    break

                # Kleine pauze om OL niet te overbelasten
                await asyncio.sleep(0.3)

            print(f"    {subject}: {subject_count} boeken  (totaal: {len(all_books)})")

    print(f"  OL harvest: {len(all_books)} unieke boeken")
    return all_books


# ── Seed-boeken meenemen ───────────────────────────────────────────────────────

def load_seed_books() -> list[dict]:
    seed_json = os.path.join(DATA_DIR, "books.json")
    if not os.path.exists(seed_json):
        return []
    with open(seed_json) as f:
        books = json.load(f)
    print(f"  Seed-boeken: {len(books)} geladen uit books.json")
    return books


# ── Hoofd ──────────────────────────────────────────────────────────────────────

async def main(skip_cmu: bool, skip_ol: bool, max_ol: int):
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"  Boekaanbeveler — grote index bouwen")
    print(f"  Index-type: HNSW (M={HNSW_M}, efConstruction={HNSW_EF_CONSTRUCT})")
    print(f"{'='*60}\n")

    print("🤖  Model laden…")
    model = SentenceTransformer(MODEL_NAME)

    conn  = sqlite3.connect(DB_PATH)
    init_db(conn)
    index, next_id = load_or_create_index()
    print(f"📦  Huidige index: {next_id} boeken\n")

    # ── Stap 1: Seed-boeken (de handmatige lijst met goede OL-keys)
    seed_books = load_seed_books()
    if seed_books:
        next_id = ingest_books(model, conn, index, seed_books, next_id, "Seed-lijst")

    # ── Stap 2: CMU Book Summaries (echte plotsamenvattingen)
    if not skip_cmu:
        print("\n📖  CMU Book Summary Dataset…")
        cmu_books = load_cmu()
        next_id   = ingest_books(model, conn, index, cmu_books, next_id, "CMU")

    # ── Stap 3: Open Library Genre Harvest
    if not skip_ol:
        print(f"\n🌐  Open Library harvest ({max_ol} boeken via {len(OL_SUBJECTS)} genres)…")
        ol_books = await harvest_ol(max_ol)
        next_id  = ingest_books(model, conn, index, ol_books, next_id, "Open Library")

    # ── Opslaan
    print(f"\n💾  Index opslaan ({index.ntotal} boeken)…")
    faiss.write_index(index, INDEX_PATH)
    conn.close()

    elapsed = time.time() - t0
    m, s    = divmod(int(elapsed), 60)

    print(f"""
{'='*60}
✅  Klaar in {m}m {s}s

   Boeken in index : {index.ntotal:,}
   Index-bestand   : {INDEX_PATH}
   Database        : {DB_PATH}

   Query-snelheid (HNSW):
     1k  boeken  → <0.1ms
     50k boeken  → <1ms
     500k boeken → <5ms

   Herstart de backend om de nieuwe index te gebruiken:
     python -m uvicorn main:app --reload
{'='*60}
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-cmu", action="store_true")
    parser.add_argument("--skip-ol",  action="store_true")
    parser.add_argument("--max-ol",   type=int, default=35000,
                        help="Max boeken van Open Library (standaard: 35000)")
    args = parser.parse_args()
    asyncio.run(main(args.skip_cmu, args.skip_ol, args.max_ol))
