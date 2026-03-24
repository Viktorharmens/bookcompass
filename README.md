# Semantische Boekaanbeveler — MVP

Een webapplicatie die boeken aanbeveelt op basis van schrijfstijl en thematiek,
volledig lokaal draaiend zonder betaalde API's.

## Architectuur

```
Browser (React :3000)
    │
    │  POST /recommend
    ▼
FastAPI Backend (:8000)
    ├── Open Library Scraper   (httpx)
    ├── Embedder               (sentence-transformers / all-MiniLM-L6-v2)
    └── FAISS Vector Search    (faiss-cpu)
            └── data/
                ├── faiss_topic.index
                ├── faiss_style.index
                └── books.json
```

## Installatie

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Eenmalig: bouw de FAISS-index (~200 boeken, duurt 2-5 min)
python build_index.py

# Start de server
uvicorn main:app --reload
```

### 2. Frontend

```bash
cd frontend
npm install
npm start
```

Open [http://localhost:3000](http://localhost:3000).

## Gebruik

1. Kopieer een URL van [openlibrary.org](https://openlibrary.org), bijv.:
   `https://openlibrary.org/works/OL82563W/Never_Let_Me_Go`
2. Stel de sliders in:
   - **Schrijfstijl** — hoe belangrijk is het dat de toon/stijl overeenkomt?
   - **Onderwerp** — hoe belangrijk is thematische gelijkenis?
3. Klik op **Aanbevelingen genereren**.

## Hoe werkt de "Waarom"-uitleg?

We genereren **twee embeddings** per boek:

| Vector      | Inhoud                                              |
|-------------|-----------------------------------------------------|
| `topic`     | Volledige beschrijving → semantische inhoud         |
| `style`     | Toon-sleutelwoorden uit beschrijving (dark, lyrical…)|

Bij het zoeken worden de twee vectors gewogen gecombineerd op basis van
de slider-waarden. De uitleg wordt gegenereerd via template-logica:
- cosine similarity score → label ("sterk vergelijkbaar" etc.)
- gedeelde subjects → "Gedeelde thema's: …"
- dominante slider → focus op stijl of onderwerp in de tekst

Geen LLM-aanroep nodig voor de uitleg — pure wiskunde + templates.

## Uitbreidingsmogelijkheden

- Meer boeken aan `build_index.py` toevoegen (seed-lijst uitbreiden)
- Betere stijl-extractie via NLP (spaCy sentence-length analyse etc.)
- Opslaan van favorieten / gebruikersprofielen
- Vervang FAISS door Qdrant/Chroma voor schaling
