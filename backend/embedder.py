"""
Embedding-laag — zet tekst om naar vectors met sentence-transformers.

Model: all-MiniLM-L6-v2
  - 384 dimensies
  - Snel, goed voor semantische gelijkenis
  - Draait volledig lokaal, geen API-kosten

Schrijfstijl vs. Onderwerp splitsen
─────────────────────────────────────
We hebben geen directe schrijfstijl-vector, maar we kunnen
twee complementaire teksten maken:

  • ONDERWERP-vector  → de boekbeschrijving zelf (wat het boek gaat over)
  • STIJL-vector      → een samenvatting van toon-gerelateerde sleutelwoorden
                        die we uit de beschrijving extraheren (zie _style_text)

De twee vectors worden later gewogen gecombineerd o.b.v. de slider-waarden.
"""

from functools import lru_cache
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

# Toon/stijl-woordparen: we zoeken deze in de beschrijving
# en bouwen er een beknopte stijlzin van.
TONE_KEYWORDS = [
    "dark", "melancholic", "humorous", "satirical", "lyrical", "poetic",
    "gritty", "hopeful", "suspenseful", "whimsical", "philosophical",
    "minimalist", "verbose", "stream-of-consciousness", "epistolary",
    "gothic", "surreal", "intimate", "epic", "sparse", "dense",
    "ironic", "tragic", "romantic", "thriller", "mystery", "horror",
]


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Laadt het model één keer en cachet het in geheugen."""
    return SentenceTransformer(MODEL_NAME)


def _style_text(description: str, subjects: list[str]) -> str:
    """
    Extraheer toon/stijl-signalen uit beschrijving en subjects.
    Geeft een korte Engelstalige zin terug die de stijl omschrijft.
    """
    desc_lower = description.lower()
    found = [kw for kw in TONE_KEYWORDS if kw in desc_lower]
    subject_style = [s for s in subjects if any(kw in s.lower() for kw in TONE_KEYWORDS)]
    combined = found + subject_style
    if combined:
        return "Writing style: " + ", ".join(combined[:8])
    # Fallback: gebruik eerste 100 woorden van beschrijving
    words = description.split()[:100]
    return "Writing style based on: " + " ".join(words)


def embed_text(text: str) -> np.ndarray:
    """Zet willekeurige tekst om naar een genormaliseerde embedding."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def embed_book(description: str, subjects: list[str]) -> dict[str, np.ndarray]:
    """
    Geeft twee vectors terug:
      'topic'  — semantische inhoud (wat het boek gaat over)
      'style'  — toon/stijl-signalen
    """
    topic_vec = embed_text(description)
    style_text = _style_text(description, subjects)
    style_vec = embed_text(style_text)
    return {"topic": topic_vec, "style": style_vec}


def weighted_vector(
    topic_vec: np.ndarray,
    style_vec: np.ndarray,
    style_weight: float,  # 1-5
    topic_weight: float,  # 1-5
) -> np.ndarray:
    """
    Combineert topic en style vector met de gegeven gewichten.
    Normaliseert het resultaat zodat cosine-distance correct blijft.
    """
    total = style_weight + topic_weight
    w_s = style_weight / total
    w_t = topic_weight / total
    combined = w_s * style_vec + w_t * topic_vec
    norm = np.linalg.norm(combined)
    if norm > 0:
        combined = combined / norm
    return combined.astype(np.float32)
