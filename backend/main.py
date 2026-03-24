"""
FastAPI backend — semantische boekaanbeveler.

Endpoints:
  POST /recommend   — geef een OL-URL + sliders, krijg 5 aanbevelingen
  GET  /health      — liveness check
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from functools import lru_cache
import traceback

from scraper import fetch_book
from search_engine import SearchEngine

app = FastAPI(title="Semantische Boekaanbeveler", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_engine() -> SearchEngine:
    return SearchEngine()


# ── Schema's ──────────────────────────────────────────────────────────────────

class RecommendRequest(BaseModel):
    url: str
    style_weight: float = 3.0
    topic_weight: float = 3.0

    @field_validator("style_weight", "topic_weight")
    @classmethod
    def clamp(cls, v: float) -> float:
        return max(1.0, min(5.0, v))


class BookResult(BaseModel):
    title: str
    author: str
    description: str
    subjects: list[str]
    cover_url: str | None
    ol_key: str
    score: float
    explanation: str
    year: int | None = None


class RecommendResponse(BaseModel):
    query_book: dict
    recommendations: list[BookResult]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/recommend", response_model=RecommendResponse)
async def get_recommendations(req: RecommendRequest):
    # 1. Scrape het invoerboek van Open Library
    try:
        book = await fetch_book(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kon Open Library niet bereiken: {e}")

    # 2. Zoek aanbevelingen via SearchEngine
    try:
        engine = get_engine()
        recs = engine.recommend(
            description=book.description,
            subjects=book.subjects,
            style_weight=req.style_weight,
            topic_weight=req.topic_weight,
            top_k=5,
            exclude_key=book.ol_key,
            exclude_title=book.title,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())

    return RecommendResponse(
        query_book={
            "title": book.title,
            "author": book.author,
            "description": book.description[:300],
            "subjects": book.subjects,
            "cover_url": book.cover_url,
        },
        recommendations=[
            BookResult(
                title=r.title,
                author=r.author,
                description=r.description[:300],
                subjects=r.subjects,
                cover_url=r.cover_url,
                ol_key=r.ol_key,
                score=r.score,
                explanation=r.explanation,
                year=getattr(r, "year", None),
            )
            for r in recs
        ],
    )
