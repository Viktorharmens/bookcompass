"""
download_and_ingest.py — Download de CMU Book Summary Dataset en verwerk hem.

De CMU-dataset bevat 16.559 Engelstalige boeken met plotsamenvattingen,
auteurs, genres en publicatiejaar. Ideaal voor semantisch zoeken.

Bron: https://www.cs.cmu.edu/~dbamman/booksummaries.html

Gebruik:
    python download_and_ingest.py

Wat dit script doet:
    1. Download booksummaries.tar.gz (~14 MB)
    2. Extraheer en parse het tab-gescheiden bestand
    3. Genereer embeddings in batches van 32
    4. Sla op als FAISS-index + SQLite database
    5. Combineer met de bestaande seed-boeken (optioneel)

Na afloop gebruikt de app automatisch de grotere index.
"""

import asyncio
import gzip
import json
import os
import shutil
import sqlite3
import tarfile
import urllib.request
import numpy as np
import faiss

from sentence_transformers import SentenceTransformer

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
DB_PATH    = os.path.join(DATA_DIR, "books.db")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_combined.index")
MODEL_NAME = "all-MiniLM-L6-v2"
DIM        = 384

CMU_URL      = "http://www.cs.cmu.edu/~dbamman/data/booksummaries.tar.gz"
CMU_TAR      = os.path.join(DATA_DIR, "booksummaries.tar.gz")
CMU_TXT      = os.path.join(DATA_DIR, "booksummaries.txt")
BATCH_SIZE   = 32

TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "gothic", "surreal", "intimate", "epic", "sparse",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]

os.makedirs(DATA_DIR, exist_ok=True)


# ── Download ───────────────────────────────────────────────────────────────────

def download_cmu():
    if os.path.exists(CMU_TXT):
        print("✓  CMU-dataset al aanwezig, download overgeslagen.")
        return

    print("⬇  Downloaden van CMU Book Summaries (~14 MB)…")
    urllib.request.urlretrieve(CMU_URL, CMU_TAR, reporthook=_progress)
    print()

    print("📦  Uitpakken…")
    with tarfile.open(CMU_TAR, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith("booksummaries.txt"):
                member.name = os.path.basename(member.name)
                tar.extract(member, DATA_DIR)
                break

    os.remove(CMU_TAR)
    print(f"✓  Opgeslagen: {CMU_TXT}")


def _progress(block, block_size, total):
    done = block * block_size
    pct  = min(done / total * 100, 100) if total > 0 else 0
    bar  = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"\r  [{bar}] {pct:.0f}%", end="", flush=True)


# ── Parse CMU ──────────────────────────────────────────────────────────────────

def parse_cmu(max_books: int | None = None) -> list[dict]:
    """
    CMU-formaat (tab-gescheiden, geen header):
        0  Wikipedia article ID
        1  Freebase ID
        2  Book title
        3  Author name
        4  Publication date
        5  Book genres (JSON dict)
        6  Plot summary
    """
    books = []
    with open(CMU_TXT, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue

            title       = parts[2].strip()
            author      = parts[3].strip()
            pub_date    = parts[4].strip()
            genres_raw  = parts[5].strip()
            summary     = parts[6].strip()

            if not title or not summary or len(summary) < 100:
                continue

            # Jaar ophalen
            year = None
            if pub_date:
                import re
                m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", pub_date)
                if m:
                    year = int(m.group(1))

            # Genres als subjects
            subjects = []
            try:
                genres_dict = json.loads(genres_raw)
                subjects = list(genres_dict.values())[:8]
            except Exception:
                pass

            books.append({
                "title":       title,
                "author":      author or "Onbekend",
                "description": summary[:800],
                "subjects":    subjects,
                "year":        year,
                "cover_url":   None,
                "ol_key":      "",
            })

            if max_books and len(books) >= max_books:
                break

    return books


# ── Embedding helpers ──────────────────────────────────────────────────────────

def style_text(desc: str, subjects: list) -> str:
    desc_lower = desc.lower()
    subj_lower = " ".join(subjects).lower()
    found = [kw for kw in TONE_KEYWORDS if kw in desc_lower or kw in subj_lower]
    if found:
        return "Writing style: " + ", ".join(found[:8])
    return "Writing style: " + " ".join(desc.split()[:60])


def combined_text(book: dict) -> str:
    desc     = book["description"]
    subjects = book.get("subjects", [])
    genres   = ("Genres: " + ", ".join(subjects[:6])) if subjects else ""
    return desc + " " + genres + " " + style_text(desc, subjects)


# ── Database ───────────────────────────────────────────────────────────────────

def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            faiss_id  INTEGER UNIQUE,
            title     TEXT NOT NULL,
            author    TEXT,
            description TEXT,
            subjects  TEXT,
            cover_url TEXT,
            ol_key    TEXT,
            isbn      TEXT,
            year      INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faiss ON books(faiss_id)")
    conn.commit()


def get_existing_titles(conn) -> set:
    rows = conn.execute("SELECT title FROM books").fetchall()
    return {r[0].lower().strip() for r in rows}


def insert_books_batch(conn, faiss_start: int, batch: list[dict]):
    rows = [
        (
            faiss_start + i,
            b["title"],
            b.get("author", ""),
            b.get("description", "")[:1000],
            json.dumps(b.get("subjects", [])),
            b.get("cover_url", ""),
            b.get("ol_key", ""),
            "",
            b.get("year"),
        )
        for i, b in enumerate(batch)
    ]
    conn.executemany("""
        INSERT OR IGNORE INTO books
            (faiss_id, title, author, description, subjects, cover_url, ol_key, isbn, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()


# ── Hoofd-ingest ───────────────────────────────────────────────────────────────

def ingest_seed_books(model, conn, index, next_id):
    """Voeg de bestaande seed-boeken (books.json) ook toe aan de gecombineerde index."""
    seed_json = os.path.join(DATA_DIR, "books.json")
    if not os.path.exists(seed_json):
        return next_id

    with open(seed_json) as f:
        seed_books = json.load(f)

    existing = get_existing_titles(conn)
    to_add   = [b for b in seed_books if b["title"].lower().strip() not in existing]
    if not to_add:
        return next_id

    print(f"  + {len(to_add)} seed-boeken toevoegen aan gecombineerde index…")
    texts = [combined_text(b) for b in to_add]
    vecs  = model.encode(texts, normalize_embeddings=True,
                         batch_size=BATCH_SIZE, show_progress_bar=False).astype(np.float32)
    index.add(vecs)
    insert_books_batch(conn, next_id, to_add)
    return next_id + len(to_add)


def run():
    download_cmu()

    print(f"\n📖  CMU-dataset inlezen…")
    books = parse_cmu()
    print(f"   {len(books)} boeken gevonden na filtering")

    print(f"\n🤖  Model laden: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Laad of maak FAISS-index
    if os.path.exists(INDEX_PATH):
        index    = faiss.read_index(INDEX_PATH)
        next_id  = index.ntotal
        print(f"📦  Bestaande index: {next_id} boeken")
    else:
        index   = faiss.IndexFlatIP(DIM)
        next_id = 0

    # Voeg eerst seed-boeken toe (zodat ze ook in SQLite zitten)
    next_id = ingest_seed_books(model, conn, index, next_id)

    # Filter al aanwezige boeken
    existing = get_existing_titles(conn)
    books    = [b for b in books if b["title"].lower().strip() not in existing]
    total    = len(books)
    print(f"\n➕  Nieuwe boeken te verwerken: {total}")

    processed = 0
    for start in range(0, total, BATCH_SIZE):
        batch = books[start : start + BATCH_SIZE]
        texts = [combined_text(b) for b in batch]
        vecs  = model.encode(texts, normalize_embeddings=True,
                             batch_size=BATCH_SIZE, show_progress_bar=False).astype(np.float32)
        index.add(vecs)
        insert_books_batch(conn, next_id, batch)
        next_id   += len(batch)
        processed += len(batch)

        pct = processed / total * 100
        print(f"  ✓  {processed}/{total} ({pct:.0f}%)  —  {batch[-1]['title'][:50]}")

    faiss.write_index(index, INDEX_PATH)
    conn.close()

    print(f"\n✅  Klaar!")
    print(f"   Totaal in index: {index.ntotal} boeken")
    print(f"   Index:    {INDEX_PATH}")
    print(f"   Database: {DB_PATH}")
    print(f"\n   Herstart de backend om de nieuwe index te gebruiken.")


if __name__ == "__main__":
    run()
