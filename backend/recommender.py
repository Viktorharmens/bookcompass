"""
recommender.py — FAISS-gebaseerde zoekmodule + uitleg-generator.

Workflow:
  1. Laad FAISS-indexes en boekmetadata bij opstart (singleton)
  2. Gegeven een query-vector, zoek de top-K dichtstbijzijnde boeken
  3. Genereer een "Waarom"-uitleg op basis van:
     - De cosine-similarity score (hoe dicht bij = hoe gelijkaardig)
     - Gedeelde onderwerpen (subjects overlap)
     - De slider-gewichten (stijl vs. onderwerp)
"""

import json
import os
import numpy as np
import faiss
from dataclasses import dataclass

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@dataclass
class Recommendation:
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    score: float          # 0-1, hoe hoger hoe beter
    explanation: str      # Nederlandstalige "Waarom"-tekst


# ── Singleton state ───────────────────────────────────────────────────────────
_topic_index: faiss.Index | None = None
_style_index: faiss.Index | None = None
_books_meta: list[dict] | None = None


def _load():
    global _topic_index, _style_index, _books_meta
    if _topic_index is not None:
        return

    topic_path = os.path.join(DATA_DIR, "faiss_topic.index")
    style_path = os.path.join(DATA_DIR, "faiss_style.index")
    books_path = os.path.join(DATA_DIR, "books.json")

    if not os.path.exists(topic_path):
        raise FileNotFoundError(
            "FAISS-index niet gevonden. Voer eerst `python build_index.py` uit."
        )

    _topic_index = faiss.read_index(topic_path)
    _style_index = faiss.read_index(style_path)
    with open(books_path) as f:
        _books_meta = json.load(f)


# ── Uitleg-generator ──────────────────────────────────────────────────────────

def _similarity_label(score: float) -> str:
    if score > 0.90:
        return "nagenoeg identiek"
    elif score > 0.80:
        return "sterk vergelijkbaar"
    elif score > 0.70:
        return "behoorlijk vergelijkbaar"
    elif score > 0.60:
        return "enigszins vergelijkbaar"
    else:
        return "licht vergelijkbaar"


def _shared_subjects(a: list[str], b: list[str]) -> list[str]:
    a_set = {s.lower() for s in a}
    b_set = {s.lower() for s in b}
    shared = a_set & b_set
    # Geef de mooie-gespelde versie terug uit lijst b
    return [s for s in b if s.lower() in shared][:3]


def _build_explanation(
    topic_score: float,
    style_score: float,
    style_weight: float,
    topic_weight: float,
    shared: list[str],
    query_subjects: list[str],
    book: dict,
) -> str:
    """
    Bouwt een Nederlandstalige uitleg op basis van scores en gewichten.
    Geen LLM nodig — we gebruiken template-logica op basis van de scores.
    """
    lines = []

    # Hoofd-reden op basis van welke slider dominant is
    total = style_weight + topic_weight
    style_ratio = style_weight / total
    topic_ratio = topic_weight / total

    combined_score = style_ratio * style_score + topic_ratio * topic_score

    # Schrijfstijl-component
    style_label = _similarity_label(style_score)
    topic_label = _similarity_label(topic_score)

    if style_ratio >= 0.6:
        lines.append(
            f"De schrijfstijl van dit boek is {style_label} aan jouw invoer "
            f"(overeenkomst: {style_score:.0%})."
        )
    elif topic_ratio >= 0.6:
        lines.append(
            f"Het onderwerp en de thematiek zijn {topic_label} "
            f"(overeenkomst: {topic_score:.0%})."
        )
    else:
        lines.append(
            f"Zowel stijl ({style_score:.0%}) als onderwerp ({topic_score:.0%}) "
            f"vertonen gelijkenissen met jouw invoer."
        )

    # Gedeelde onderwerpen
    if shared:
        subjects_str = ", ".join(f"'{s}'" for s in shared)
        lines.append(f"Gedeelde thema's: {subjects_str}.")

    return " ".join(lines)


# ── Publieke API ──────────────────────────────────────────────────────────────

def recommend(
    topic_vec: np.ndarray,
    style_vec: np.ndarray,
    style_weight: float,
    topic_weight: float,
    query_subjects: list[str],
    k: int = 5,
    exclude_key: str | None = None,
) -> list[Recommendation]:
    """
    Zoek de top-k aanbevelingen.

    Parameters
    ----------
    topic_vec, style_vec : np.ndarray  — genormaliseerde query-vectors
    style_weight, topic_weight : float — sliderwaarden (1-5)
    query_subjects : list[str]         — onderwerpen van het invoerboek
    k : int                            — aantal resultaten
    exclude_key : str | None           — ol_key van het invoerboek (uitgesloten)
    """
    _load()

    # Zoek meer kandidaten dan we nodig hebben, zodat we het invoerboek kunnen filteren
    search_k = k + 3

    topic_q = topic_vec.reshape(1, -1)
    style_q = style_vec.reshape(1, -1)

    topic_scores, topic_ids = _topic_index.search(topic_q, search_k)
    style_scores, style_ids = _style_index.search(style_q, search_k)

    # Combineer scores per boek-index
    score_map: dict[int, dict] = {}

    for score, idx in zip(topic_scores[0], topic_ids[0]):
        if idx < 0:
            continue
        score_map.setdefault(idx, {"topic": 0.0, "style": 0.0})
        score_map[idx]["topic"] = float(score)

    for score, idx in zip(style_scores[0], style_ids[0]):
        if idx < 0:
            continue
        score_map.setdefault(idx, {"topic": 0.0, "style": 0.0})
        score_map[idx]["style"] = float(score)

    total = style_weight + topic_weight
    w_s = style_weight / total
    w_t = topic_weight / total

    ranked = sorted(
        score_map.items(),
        key=lambda x: w_s * x[1]["style"] + w_t * x[1]["topic"],
        reverse=True,
    )

    results = []
    for idx, scores in ranked:
        if len(results) >= k:
            break
        book = _books_meta[idx]
        if exclude_key and book["ol_key"] == exclude_key:
            continue

        shared = _shared_subjects(query_subjects, book.get("subjects", []))
        explanation = _build_explanation(
            topic_score=scores["topic"],
            style_score=scores["style"],
            style_weight=style_weight,
            topic_weight=topic_weight,
            shared=shared,
            query_subjects=query_subjects,
            book=book,
        )

        results.append(Recommendation(
            title=book["title"],
            author=book["author"],
            description=book["description"],
            subjects=book.get("subjects", []),
            cover_url=book.get("cover_url"),
            ol_key=book["ol_key"],
            score=round(w_s * scores["style"] + w_t * scores["topic"], 4),
            explanation=explanation,
        ))

    return results
