"""
search_engine.py — Zoekmodule op basis van de FAISS-index + SQLite metadata.

Werkt met de index gebouwd door ingest_data.py (grote CSV-datasets)
én met de klassieke build_index.py (kleine seed-dataset via JSON).

Gebruik als module:
    from search_engine import SearchEngine
    engine = SearchEngine()
    results = engine.recommend("A melancholic story about loss and memory", top_k=5)
"""

import json
import os
import sqlite3
import numpy as np
import faiss
from dataclasses import dataclass
from functools import lru_cache
from sentence_transformers import SentenceTransformer

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
MODEL_NAME = "all-MiniLM-L6-v2"

# Paden — gebruikt de grote index als die bestaat, anders de seed-index
LARGE_INDEX_PATH = os.path.join(DATA_DIR, "faiss_combined.index")
SEED_TOPIC_PATH  = os.path.join(DATA_DIR, "faiss_topic.index")
SEED_STYLE_PATH  = os.path.join(DATA_DIR, "faiss_style.index")
SEED_JSON_PATH   = os.path.join(DATA_DIR, "books.json")
DB_PATH          = os.path.join(DATA_DIR, "books.db")

TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "gothic", "surreal", "intimate", "epic", "sparse",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]


@dataclass
class BookResult:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    score: float
    explanation: str
    year: int | None = None


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def _style_text(description: str) -> str:
    desc_lower = description.lower()
    found = [kw for kw in TONE_KEYWORDS if kw in desc_lower]
    if found:
        return "Writing style: " + ", ".join(found[:8])
    return "Writing style based on: " + " ".join(description.split()[:80])


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


def _similarity_label(score: float) -> str:
    if score > 0.90: return "nagenoeg identiek"
    if score > 0.80: return "sterk vergelijkbaar"
    if score > 0.70: return "behoorlijk vergelijkbaar"
    if score > 0.60: return "enigszins vergelijkbaar"
    return "licht vergelijkbaar"


def _build_explanation(score: float, style_score: float, topic_score: float,
                        style_w: float, topic_w: float, shared: list[str]) -> str:
    total = style_w + topic_w
    sr, tr = style_w / total, topic_w / total
    lines = []
    if sr >= 0.6:
        lines.append(f"De schrijfstijl is {_similarity_label(style_score)} ({style_score:.0%} overeenkomst).")
    elif tr >= 0.6:
        lines.append(f"Het onderwerp en de thematiek zijn {_similarity_label(topic_score)} ({topic_score:.0%} overeenkomst).")
    else:
        lines.append(f"Zowel stijl ({style_score:.0%}) als onderwerp ({topic_score:.0%}) vertonen gelijkenissen.")
    if shared:
        lines.append(f"Gedeelde thema's: {', '.join(repr(s) for s in shared)}.")
    return " ".join(lines)


class SearchEngine:
    """
    Universele zoekmotor — kiest automatisch tussen:
      • Grote index (ingest_data.py / CSV)
      • Seed-index (build_index.py / handmatige lijst)
    """

    def __init__(self):
        self._model   = None
        self._index   = None
        self._mode    = None   # "large" | "seed"
        self._books   = None   # lijst van dicts (seed-modus)
        self._db_conn = None   # SQLite-verbinding (large-modus)
        self._seed_topic_index = None
        self._seed_style_index = None
        self._load()

    def _load(self):
        self._model = _get_model()

        if os.path.exists(LARGE_INDEX_PATH) and os.path.exists(DB_PATH):
            self._mode  = "large"
            self._index = faiss.read_index(LARGE_INDEX_PATH)
            self._db_conn = sqlite3.connect(DB_PATH)
            print(f"[SearchEngine] Grote index geladen: {self._index.ntotal} boeken (SQLite)")

        elif os.path.exists(SEED_TOPIC_PATH):
            self._mode = "seed"
            self._seed_topic_index = faiss.read_index(SEED_TOPIC_PATH)
            self._seed_style_index = faiss.read_index(SEED_STYLE_PATH)
            with open(SEED_JSON_PATH) as f:
                self._books = json.load(f)
            print(f"[SearchEngine] Seed-index geladen: {len(self._books)} boeken (JSON)")

        else:
            raise FileNotFoundError(
                "Geen FAISS-index gevonden. Voer eerst build_index.py of ingest_data.py uit."
            )

    # ── Publieke API ────────────────────────────────────────────────────────

    def recommend(
        self,
        description: str,
        subjects: list[str] | None = None,
        style_weight: float = 3.0,
        topic_weight: float = 3.0,
        top_k: int = 5,
        exclude_key: str | None = None,
        exclude_title: str | None = None,
    ) -> list[BookResult]:
        exclude_title_norm = exclude_title.strip().lower() if exclude_title else None
        if self._mode == "large":
            results = self._recommend_large(description, subjects or [], style_weight, topic_weight, top_k, exclude_key, exclude_title_norm)
        else:
            results = self._recommend_seed(description, subjects or [], style_weight, topic_weight, top_k, exclude_key, exclude_title_norm)
        return sorted(results, key=lambda r: r.score, reverse=True)

    # ── Large-modus (CSV / SQLite) ──────────────────────────────────────────

    def _recommend_large(self, description, subjects, style_w, topic_w, top_k, exclude_key, exclude_title_norm):
        style = _style_text(description)
        combined = description + " " + style
        vec = self._model.encode(combined, normalize_embeddings=True).astype(np.float32).reshape(1, -1)

        scores, ids = self._index.search(vec, top_k + 20)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0 or len(results) >= top_k:
                break
            book = self._fetch_book(int(idx))
            if not book:
                continue
            if exclude_key and book.get("ol_key") == exclude_key:
                continue
            if exclude_title_norm and book["title"].strip().lower() == exclude_title_norm:
                continue

            book_subjects = json.loads(book.get("subjects") or "[]")
            shared = list(set(s.lower() for s in subjects) & set(s.lower() for s in book_subjects))[:3]

            results.append(BookResult(
                title=book["title"],
                author=book["author"] or "Onbekend",
                description=(book["description"] or "")[:300],
                subjects=book_subjects,
                cover_url=book.get("cover_url"),
                ol_key=book.get("ol_key", ""),
                score=round(_clamp(float(score)), 4),
                explanation=_build_explanation(_clamp(float(score)), _clamp(float(score)), _clamp(float(score)),
                                               style_w, topic_w, shared),
                year=book.get("year"),
            ))
        return results

    def _fetch_book(self, faiss_id: int) -> dict | None:
        row = self._db_conn.execute(
            "SELECT title, author, description, subjects, cover_url, ol_key, year FROM books WHERE faiss_id=?",
            (faiss_id,)
        ).fetchone()
        if not row:
            return None
        return dict(zip(["title", "author", "description", "subjects", "cover_url", "ol_key", "year"], row))

    # ── Seed-modus (JSON / twee indexes) ────────────────────────────────────

    def _recommend_seed(self, description, subjects, style_w, topic_w, top_k, exclude_key, exclude_title_norm):
        topic_vec = self._model.encode(description, normalize_embeddings=True).astype(np.float32).reshape(1, -1)
        style_vec = self._model.encode(_style_text(description), normalize_embeddings=True).astype(np.float32).reshape(1, -1)

        k = top_k + 20
        t_scores, t_ids = self._seed_topic_index.search(topic_vec, k)
        s_scores, s_ids = self._seed_style_index.search(style_vec, k)

        score_map: dict[int, dict] = {}
        for sc, idx in zip(t_scores[0], t_ids[0]):
            if idx >= 0:
                score_map.setdefault(idx, {"topic": 0.0, "style": 0.0})["topic"] = float(sc)
        for sc, idx in zip(s_scores[0], s_ids[0]):
            if idx >= 0:
                score_map.setdefault(idx, {"topic": 0.0, "style": 0.0})["style"] = float(sc)

        total_w = style_w + topic_w
        ranked = sorted(score_map.items(),
                        key=lambda x: (style_w * x[1]["style"] + topic_w * x[1]["topic"]) / total_w,
                        reverse=True)

        results = []
        for idx, sc in ranked:
            if len(results) >= top_k:
                break
            book = self._books[idx]
            if exclude_key and book.get("ol_key") == exclude_key:
                continue
            if exclude_title_norm and book["title"].strip().lower() == exclude_title_norm:
                continue
            book_subjects = book.get("subjects", [])
            shared = list(set(s.lower() for s in subjects) & set(s.lower() for s in book_subjects))[:3]
            combined_score = _clamp((style_w * sc["style"] + topic_w * sc["topic"]) / total_w)

            results.append(BookResult(
                title=book["title"],
                author=book["author"],
                description=book.get("description", "")[:300],
                subjects=book_subjects,
                cover_url=book.get("cover_url"),
                ol_key=book.get("ol_key", ""),
                score=round(combined_score, 4),
                explanation=_build_explanation(combined_score, _clamp(sc["style"]), _clamp(sc["topic"]),
                                               style_w, topic_w, shared),
                year=book.get("year"),
            ))
        return results
