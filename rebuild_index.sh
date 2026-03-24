#!/bin/bash
# Bouw de FAISS-index opnieuw op.
#
# Gebruik:
#   ./rebuild_index.sh            # volledige rebuild (download als nodig)
#   ./rebuild_index.sh --no-download  # hergebruik al gedownloade dump-bestanden
#   ./rebuild_index.sh --resume   # hervat een onderbroken rebuild

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
DATA="$BACKEND/data"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

# ── Argumenten doorgeven aan het Python-script ──────────────────────────────
ARGS="$*"

# ── Bevestiging (tenzij --resume, dan is er geen destructieve stap) ──────────
if [[ "$ARGS" != *"--resume"* ]]; then
  echo -e "${YELLOW}⚠  Dit verwijdert de huidige index en database en bouwt alles opnieuw op."
  echo -e "   Dit kan 3-6 uur duren.${RESET}"
  echo ""
  read -r -p "Doorgaan? (j/n) " CONFIRM
  if [[ "$CONFIRM" != "j" && "$CONFIRM" != "J" ]]; then
    echo "Afgebroken."
    exit 0
  fi

  # Back-up van bestaande bestanden
  if [ -f "$DATA/faiss_combined.index" ] || [ -f "$DATA/books.db" ]; then
    BACKUP="$DATA/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP"
    [ -f "$DATA/faiss_combined.index" ] && mv "$DATA/faiss_combined.index" "$BACKUP/"
    [ -f "$DATA/books.db" ]             && mv "$DATA/books.db"             "$BACKUP/"
    echo -e "${BLUE}💾  Bestaande index opgeslagen in: $BACKUP${RESET}"
  fi
fi

# ── Venv controleren ────────────────────────────────────────────────────────
if [ ! -d "$BACKEND/venv" ]; then
  echo -e "${BLUE}Virtual environment aanmaken…${RESET}"
  python3 -m venv "$BACKEND/venv"
fi

echo -e "${BLUE}Dependencies controleren…${RESET}"
"$BACKEND/venv/bin/pip" install -q -r "$BACKEND/requirements.txt"

# ── Index bouwen ─────────────────────────────────────────────────────────────
echo ""
if [ -f "$DATA/ol_dump_works_latest.txt.gz" ]; then
  echo -e "${GREEN}📚  OL dump gevonden — ingest_ol_dump.py gebruiken${RESET}"
  echo -e "${BLUE}    Gestart om $(date '+%H:%M'). Verwachte duur: 3-6 uur.${RESET}"
  echo ""
  cd "$BACKEND" || exit 1
  "$BACKEND/venv/bin/python" ingest_ol_dump.py --no-download $ARGS
else
  echo -e "${GREEN}📚  Geen OL dump gevonden — build_large_index.py gebruiken (~2 uur)${RESET}"
  echo ""
  cd "$BACKEND" || exit 1
  "$BACKEND/venv/bin/python" build_large_index.py
fi

echo ""
echo -e "${GREEN}✅  Index klaar. Herstart de backend om hem te gebruiken:${RESET}"
echo -e "    ${BLUE}lsof -ti:8000 | xargs kill -9${RESET}"
echo -e "    ${BLUE}cd backend && source venv/bin/activate && python -m uvicorn main:app --reload${RESET}"
