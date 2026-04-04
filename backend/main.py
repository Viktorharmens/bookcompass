"""
FastAPI backend — semantische boekaanbeveler.

Endpoints:
  POST /book-info   — haal boekinfo + onderwerpen op (voor tag-selectie)
  POST /recommend   — geef een query + sliders + tags, krijg aanbevelingen
  GET  /health      — liveness check

Invoer voor /book-info en /recommend (veld "url") kan zijn:
  - OpenLibrary URL
  - bol.com / Amazon / Goodreads URL
  - ISBN (10 of 13 cijfers)
  - Vrije tekst (boektitel)
"""

import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from scraper import fetch_book
import groq_recommender

app = FastAPI(title="BookCompass API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schema's ──────────────────────────────────────────────────────────────────

class BookInfoRequest(BaseModel):
    url: str  # accepteert URL, ISBN of vrije titel


class BookInfoResponse(BaseModel):
    title: str
    author: str
    subjects: list[str]
    cover_url: str | None


class RecommendRequest(BaseModel):
    url: str  # accepteert URL, ISBN of vrije titel
    style_weight: float = 3.0
    topic_weight: float = 3.0
    selected_subjects: list[str] = []

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


@app.post("/book-info", response_model=BookInfoResponse)
async def get_book_info(req: BookInfoRequest):
    try:
        book = await fetch_book(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kon boek niet ophalen: {e}")

    return BookInfoResponse(
        title=book.title,
        author=book.author,
        subjects=book.subjects[:12],
        cover_url=book.cover_url,
    )


@app.post("/recommend", response_model=RecommendResponse)
async def get_recommendations(req: RecommendRequest):
    try:
        book = await fetch_book(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kon boek niet ophalen: {e}")

    try:
        recs = await groq_recommender.recommend(
            book_title=book.title,
            book_author=book.author,
            book_description=book.description,
            book_subjects=book.subjects,
            style_weight=req.style_weight,
            topic_weight=req.topic_weight,
            selected_subjects=req.selected_subjects,
            k=10,
        )
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
                description=r.description,
                subjects=r.subjects,
                cover_url=r.cover_url,
                ol_key=r.ol_key,
                score=r.score,
                explanation=r.explanation,
                year=r.year,
            )
            for r in recs
        ],
    )
