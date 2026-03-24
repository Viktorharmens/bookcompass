"""
ingest_data.py — Verwerk een grote CSV met boeken naar een FAISS-index + SQLite metadata.

CSV-formaat (minimaal):
    title, author, description
    (optioneel: isbn, subjects, cover_url, ol_key)

Gebruik:
    python ingest_data.py --csv books.csv
    python ingest_data.py --csv books.csv --batch-size 64 --resume

Opties:
    --csv          Pad naar het CSV-bestand
    --batch-size   Aantal boeken per embedding-batch (standaard: 32)
    --resume       Sla boeken over die al in de database staan
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH    = os.path.join(DATA_DIR, "books.db")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_combined.index")
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "gothic", "surreal", "intimate", "epic", "sparse",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]


# ── Database ───────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            faiss_id    INTEGER UNIQUE,
            title       TEXT NOT NULL,
            author      TEXT,
            description TEXT,
            subjects    TEXT,   -- JSON array
            cover_url   TEXT,
            ol_key      TEXT,
            isbn        TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faiss ON books(faiss_id)")
    conn.commit()


def get_existing_titles(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT title FROM books").fetchall()
    return {r[0].lower().strip() for r in rows}


def insert_book(conn: sqlite3.Connection, faiss_id: int, row: dict):
    subjects = row.get("subjects", "")
    if isinstance(subjects, str) and subjects.strip().startswith("["):
        subjects_json = subjects
    else:
        subjects_json = json.dumps([s.strip() for s in subjects.split(",") if s.strip()])

    conn.execute("""
        INSERT OR IGNORE INTO books
            (faiss_id, title, author, description, subjects, cover_url, ol_key, isbn)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        faiss_id,
        row.get("title", "").strip(),
        row.get("author", "").strip(),
        row.get("description", "").strip()[:1000],
        subjects_json,
        row.get("cover_url", ""),
        row.get("ol_key", ""),
        row.get("isbn", ""),
    ))


# ── Embedding helpers ──────────────────────────────────────────────────────────

def style_text(description: str, subjects: str) -> str:
    desc_lower = description.lower()
    found = [kw for kw in TONE_KEYWORDS if kw in desc_lower]
    subj_lower = subjects.lower() if subjects else ""
    found += [kw for kw in TONE_KEYWORDS if kw in subj_lower and kw not in found]
    if found:
        return "Writing style: " + ", ".join(found[:8])
    return "Writing style based on: " + " ".join(description.split()[:80])


def combined_text(row: dict) -> str:
    """
    Combineert onderwerp- en stijltekst in één string.
    Bij opslag in één gecombineerde index is dit eenvoudiger dan twee aparte indexes.
    De zoekfunctie in search_engine.py kan ook twee aparte indexes laden als die bestaan.
    """
    desc  = row.get("description", "") or f"{row.get('title','')} by {row.get('author','')}"
    subj  = row.get("subjects", "")
    style = style_text(desc, subj)
    return desc + " " + style


def encode_batch(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.astype(np.float32)


# ── FAISS helpers ──────────────────────────────────────────────────────────────

def load_or_create_index() -> tuple[faiss.Index, int]:
    """Laadt een bestaande index of maakt een nieuwe aan. Geeft (index, next_id) terug."""
    if os.path.exists(INDEX_PATH):
        idx = faiss.read_index(INDEX_PATH)
        return idx, idx.ntotal
    idx = faiss.IndexFlatIP(EMBEDDING_DIM)
    return idx, 0


def save_index(idx: faiss.Index):
    faiss.write_index(idx, INDEX_PATH)


# ── Hoofd-ingest ───────────────────────────────────────────────────────────────

def ingest(csv_path: str, batch_size: int = 32, resume: bool = False):
    if not os.path.exists(csv_path):
        print(f"❌  CSV niet gevonden: {csv_path}")
        sys.exit(1)

    print(f"📖  Model laden: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    existing = get_existing_titles(conn) if resume else set()

    index, next_faiss_id = load_or_create_index()
    print(f"📦  Bestaande index: {next_faiss_id} boeken")

    # Lees CSV
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows_all = list(reader)

    # Filter al verwerkte boeken bij --resume
    if resume:
        rows_all = [r for r in rows_all if r.get("title", "").lower().strip() not in existing]

    total = len(rows_all)
    print(f"➕  Te verwerken: {total} boeken (batch-size: {batch_size})")

    processed = 0
    for batch_start in range(0, total, batch_size):
        batch = rows_all[batch_start : batch_start + batch_size]
        texts = [combined_text(r) for r in batch]

        vecs = encode_batch(model, texts)

        for i, (row, vec) in enumerate(zip(batch, vecs)):
            faiss_id = next_faiss_id + i
            mat = vec.reshape(1, -1)
            index.add(mat)
            insert_book(conn, faiss_id, row)

        next_faiss_id += len(batch)
        processed += len(batch)
        conn.commit()

        pct = processed / total * 100
        print(f"  ✓  {processed}/{total} ({pct:.0f}%)  —  boek: {batch[-1].get('title','?')[:50]}")

    save_index(index)
    conn.close()
    print(f"\n✅  Klaar! {processed} boeken toegevoegd.")
    print(f"   Index:    {INDEX_PATH}  ({index.ntotal} totaal)")
    print(f"   Database: {DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verwerk CSV naar FAISS-index")
    parser.add_argument("--csv",        required=True, help="Pad naar CSV-bestand")
    parser.add_argument("--batch-size", type=int, default=32, help="Boeken per batch (standaard: 32)")
    parser.add_argument("--resume",     action="store_true", help="Sla al verwerkte boeken over")
    args = parser.parse_args()

    ingest(args.csv, args.batch_size, args.resume)
