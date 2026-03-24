"""
ingest_ol_dump.py — Verwerk de Open Library works dump naar FAISS + SQLite.

De OL works dump bevat ~30 miljoen records; na filtering op Engelse beschrijvingen
(>= 150 tekens) houd je ~2-4 miljoen bruikbare boeken over.

Wat dit script doet:
  1. Download ol_dump_works_latest.txt.gz  (~5 GB)
  2. (Optioneel) download ol_dump_authors_latest.txt.gz (~1 GB) voor auteursnamen
  3. Stream + filter lijn voor lijn — geen geheugenprobleem
  4. Genereer embeddings in batches van 64
  5. Sla op in FAISS HNSW-index + SQLite
  6. Ondersteunt --resume om onderbroken runs te hervatten

Vereisten:
  - ~30 GB vrije schijfruimte (download + index)
  - 8 GB RAM aanbevolen
  - Rekentijd: 4-10 uur afhankelijk van CPU/GPU

Gebruik:
    python ingest_ol_dump.py                    # volledig
    python ingest_ol_dump.py --resume           # hervatten na onderbreking
    python ingest_ol_dump.py --max-books 500000 # eerste 500k boeken
    python ingest_ol_dump.py --no-authors       # snel, zonder auteursnamen
    python ingest_ol_dump.py --works-file /pad/naar/dump.txt.gz  # eigen bestand
"""

import argparse
import gzip
import json
import os
import re
import sqlite3
import ssl
import sys
import time
import urllib.request
import numpy as np

# macOS Python.org-installaties missen SSL-certificaten — gebruik certifi als fallback
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
import faiss
from sentence_transformers import SentenceTransformer

# ── Paden ──────────────────────────────────────────────────────────────────────

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
DB_PATH     = os.path.join(DATA_DIR, "books.db")
INDEX_PATH  = os.path.join(DATA_DIR, "faiss_combined.index")
MODEL_NAME  = "all-MiniLM-L6-v2"
DIM         = 384
BATCH_SIZE  = 64
MIN_DESC    = 150       # minimale beschrijvingslengte in tekens

HNSW_M            = 32
HNSW_EF_CONSTRUCT = 200
HNSW_EF_SEARCH    = 64

WORKS_URL   = "https://openlibrary.org/data/ol_dump_works_latest.txt.gz"
AUTHORS_URL = "https://openlibrary.org/data/ol_dump_authors_latest.txt.gz"
WORKS_GZ    = os.path.join(DATA_DIR, "ol_dump_works_latest.txt.gz")
AUTHORS_GZ  = os.path.join(DATA_DIR, "ol_dump_authors_latest.txt.gz")

TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "gothic", "surreal", "intimate", "epic", "sparse",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]

os.makedirs(DATA_DIR, exist_ok=True)


# ── Download helpers ────────────────────────────────────────────────────────────

def _progress(block, block_size, total):
    done = block * block_size
    pct  = min(done / total * 100, 100) if total > 0 else 0
    mb   = done / 1_048_576
    bar  = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"\r  [{bar}] {pct:.0f}%  ({mb:.0f} MB)", end="", flush=True)


def download(url: str, dest: str, label: str):
    if os.path.exists(dest):
        size_mb = os.path.getsize(dest) / 1_048_576
        print(f"✓  {label} al aanwezig ({size_mb:.0f} MB), overgeslagen.")
        return
    print(f"⬇  Downloaden: {label}")
    print(f"   URL: {url}")
    print(f"   Bestemming: {dest}")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX))
    with opener.open(url) as response, open(dest, "wb") as out:
        total     = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1 << 16  # 64 KB
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            _progress(downloaded // chunk_size, chunk_size, total)
    print()
    size_mb = os.path.getsize(dest) / 1_048_576
    print(f"✓  Opgeslagen: {dest} ({size_mb:.0f} MB)")


# ── Authors dump → lookup dict ──────────────────────────────────────────────────

def build_author_map(authors_gz: str) -> dict[str, str]:
    """
    Leest de authors dump en bouwt een dict: /authors/OL123A → "Auteur Naam".
    Verbruikt ~500 MB geheugen voor ~10M auteurs.
    """
    print("👤  Auteurs inlezen…")
    author_map = {}
    t0 = time.time()
    with gzip.open(authors_gz, "rt", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i % 500_000 == 0 and i > 0:
                elapsed = time.time() - t0
                print(f"   {i:,} auteurs gelezen ({elapsed:.0f}s)…", end="\r")
            parts = line.split("\t", 4)
            if len(parts) < 5:
                continue
            try:
                data = json.loads(parts[4])
            except Exception:
                continue
            key  = data.get("key", "").strip()
            name = data.get("name", "").strip()
            if key and name:
                author_map[key] = name
    print(f"\n✓  {len(author_map):,} auteurs geladen.")
    return author_map


# ── Works dump parsing ──────────────────────────────────────────────────────────

_NON_LATIN = re.compile(r'[\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F]')


def _is_english(data: dict, desc: str) -> bool:
    """
    1. Als het 'languages' veld aanwezig is: alleen accepteren als /languages/eng erin staat.
    2. Geen taalveld? Heuristiek: geen Cyrillisch/Arabisch/Chinees/Japans in de beschrijving.
    """
    langs = data.get("languages")
    if langs:
        return any(
            isinstance(l, dict) and l.get("key") == "/languages/eng"
            for l in langs
        )
    # Geen taalveld — val terug op script-detectie
    return not bool(_NON_LATIN.search(desc[:300]))


def parse_work(line: str, author_map: dict[str, str] | None) -> dict | None:
    """
    OL works-dump formaat (tab-gescheiden):
        0  /type/work
        1  /works/OL12345W
        2  revisie-nummer
        3  tijdstempel
        4  JSON payload
    """
    parts = line.split("\t", 4)
    if len(parts) < 5:
        return None

    try:
        data = json.loads(parts[4])
    except Exception:
        return None

    # Titel
    title = (data.get("title") or "").strip()
    if not title:
        return None

    # Beschrijving — kan string of {"type": ..., "value": ...} zijn
    raw_desc = data.get("description", "")
    if isinstance(raw_desc, dict):
        raw_desc = raw_desc.get("value", "")
    desc = (raw_desc or "").strip()
    if len(desc) < MIN_DESC:
        return None

    # Taalfilter — check languages veld, anders heuristiek op beschrijving
    if not _is_english(data, desc):
        return None

    # OL sleutel
    ol_key = (data.get("key") or parts[1]).strip()

    # Omslag
    covers    = data.get("covers", [])
    cover_url = None
    if covers and isinstance(covers[0], int) and covers[0] > 0:
        cover_url = f"https://covers.openlibrary.org/b/id/{covers[0]}-M.jpg"

    # Publicatiejaar
    year = None
    fpd  = str(data.get("first_publish_date") or "")
    if fpd:
        m = re.search(r'\b(1[0-9]{3}|20[0-2][0-9])\b', fpd)
        if m:
            year = int(m.group(1))

    # Subjects
    subjects = []
    for s in data.get("subjects", []):
        if isinstance(s, str) and len(s) < 80:
            subjects.append(s)
        if len(subjects) >= 10:
            break

    # Auteur
    author = "Unknown"
    if author_map is not None:
        for entry in data.get("authors", []):
            if not isinstance(entry, dict):
                continue
            a = entry.get("author", {})
            if isinstance(a, dict):
                k = a.get("key", "")
                if k and k in author_map:
                    author = author_map[k]
                    break

    return {
        "title":       title,
        "author":      author,
        "description": desc[:800],
        "subjects":    subjects,
        "year":        year,
        "cover_url":   cover_url,
        "ol_key":      ol_key,
    }


# ── Embedding ───────────────────────────────────────────────────────────────────

def style_text(desc: str, subjects: list) -> str:
    text = desc.lower() + " " + " ".join(subjects).lower()
    found = [kw for kw in TONE_KEYWORDS if kw in text]
    if found:
        return "Writing style: " + ", ".join(found[:8])
    return "Writing style: " + " ".join(desc.split()[:60])


def combined_text(book: dict) -> str:
    desc     = book["description"]
    subjects = book.get("subjects", [])
    genres   = ("Genres: " + ", ".join(subjects[:6])) if subjects else ""
    return desc + " " + genres + " " + style_text(desc, subjects)


# ── Database ────────────────────────────────────────────────────────────────────

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faiss  ON books(faiss_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ol_key ON books(ol_key)")
    conn.commit()


def get_existing_ol_keys(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT ol_key FROM books WHERE ol_key != ''").fetchall()
    return {r[0] for r in rows}


def insert_batch(conn: sqlite3.Connection, faiss_start: int, batch: list[dict]):
    rows = [
        (
            faiss_start + i,
            b["title"],
            b["author"],
            b["description"][:1000],
            json.dumps(b["subjects"]),
            b.get("cover_url") or "",
            b.get("ol_key") or "",
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


# ── HNSW index ──────────────────────────────────────────────────────────────────

def create_hnsw_index() -> faiss.Index:
    index = faiss.IndexHNSWFlat(DIM, HNSW_M)
    index.hnsw.efConstruction = HNSW_EF_CONSTRUCT
    index.hnsw.efSearch        = HNSW_EF_SEARCH
    return index


# ── Hoofd-logica ────────────────────────────────────────────────────────────────

def run(args):
    works_gz = args.works_file or WORKS_GZ

    # 1. Download
    if not args.no_download:
        download(WORKS_URL, works_gz, "OL works dump (~5 GB)")
        if not args.no_authors:
            download(AUTHORS_URL, AUTHORS_GZ, "OL authors dump (~1 GB)")

    # 2. Auteurs map
    author_map = None
    if not args.no_authors and os.path.exists(AUTHORS_GZ):
        author_map = build_author_map(AUTHORS_GZ)

    # 3. Model
    print(f"\n🤖  Model laden: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    # 4. Database + index
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.resume and os.path.exists(INDEX_PATH):
        index   = faiss.read_index(INDEX_PATH)
        next_id = index.ntotal
        print(f"📦  Bestaande index geladen: {next_id:,} boeken (resume modus)")
    else:
        index   = create_hnsw_index()
        next_id = 0
        print("📦  Nieuwe HNSW-index aangemaakt")

    existing_keys = get_existing_ol_keys(conn) if args.resume else set()

    # 5. Stream works dump
    print(f"\n📖  Works dump inlezen: {works_gz}")
    if not os.path.exists(works_gz):
        print(f"❌  Bestand niet gevonden: {works_gz}")
        print("    Voer het script uit zonder --no-download, of geef --works-file op.")
        sys.exit(1)

    batch          = []
    total_parsed   = 0
    total_skipped  = 0
    total_ingested = 0
    t_start        = time.time()
    save_every     = 50_000   # bewaar tussentijds na elke 50k boeken

    open_fn = gzip.open if works_gz.endswith(".gz") else open

    try:
        with open_fn(works_gz, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                total_parsed += 1

                book = parse_work(line, author_map)
                if book is None:
                    total_skipped += 1
                    continue

                if args.resume and book["ol_key"] in existing_keys:
                    total_skipped += 1
                    continue

                batch.append(book)

                if len(batch) >= BATCH_SIZE:
                    texts = [combined_text(b) for b in batch]
                    vecs  = model.encode(
                        texts, normalize_embeddings=True,
                        batch_size=BATCH_SIZE, show_progress_bar=False
                    ).astype(np.float32)
                    index.add(vecs)
                    insert_batch(conn, next_id, batch)
                    next_id        += len(batch)
                    total_ingested += len(batch)
                    batch           = []

                    # Voortgang tonen
                    if total_ingested % 10_000 == 0:
                        elapsed = time.time() - t_start
                        rate    = total_ingested / elapsed
                        print(
                            f"  ✓  {total_ingested:>8,} boeken | "
                            f"{total_parsed:>10,} regels gelezen | "
                            f"{rate:.0f} boeken/s",
                            end="\r"
                        )

                    # Tussentijds opslaan
                    if total_ingested % save_every == 0:
                        print(f"\n  💾  Tussentijds opgeslagen ({total_ingested:,} boeken)…")
                        faiss.write_index(index, INDEX_PATH)

                if args.max_books and total_ingested >= args.max_books:
                    print(f"\n  ℹ  --max-books {args.max_books} bereikt, gestopt.")
                    break

    except KeyboardInterrupt:
        print("\n\n⚠  Onderbroken door gebruiker. Tussenstand wordt opgeslagen…")

    # Resterende batch
    if batch:
        texts = [combined_text(b) for b in batch]
        vecs  = model.encode(
            texts, normalize_embeddings=True,
            batch_size=BATCH_SIZE, show_progress_bar=False
        ).astype(np.float32)
        index.add(vecs)
        insert_batch(conn, next_id, batch)
        total_ingested += len(batch)

    # Opslaan
    faiss.write_index(index, INDEX_PATH)
    conn.close()

    elapsed = time.time() - t_start
    print(f"\n\n✅  Klaar!")
    print(f"   Gelezen regels : {total_parsed:,}")
    print(f"   Ingested       : {total_ingested:,} boeken")
    print(f"   Overgeslagen   : {total_skipped:,}")
    print(f"   Tijd           : {elapsed/60:.1f} minuten")
    print(f"   Index          : {INDEX_PATH}  ({os.path.getsize(INDEX_PATH)//1_048_576} MB)")
    print(f"   Database       : {DB_PATH}  ({os.path.getsize(DB_PATH)//1_048_576} MB)")
    print(f"\n   Herstart de backend om de nieuwe index te gebruiken.")


# ── CLI ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verwerk OL works dump → FAISS + SQLite")
    parser.add_argument("--resume",       action="store_true",
                        help="Hervat een eerdere run, sla al aanwezige boeken over")
    parser.add_argument("--no-download",  action="store_true",
                        help="Sla de download-stap over (bestand al aanwezig)")
    parser.add_argument("--no-authors",   action="store_true",
                        help="Sla de authors dump over (sneller, geen auteursnamen)")
    parser.add_argument("--max-books",    type=int, default=None,
                        help="Stop na N boeken (bijv. --max-books 500000)")
    parser.add_argument("--works-file",   type=str, default=None,
                        help="Eigen pad naar de works dump (gz of txt)")
    args = parser.parse_args()
    run(args)
