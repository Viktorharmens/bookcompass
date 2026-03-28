#!/bin/bash
# Synchroniseer grote databestanden naar de Hetzner server.
#
# Gebruik:
#   ./sync_data.sh <server-ip>
#   SERVER=1.2.3.4 ./sync_data.sh

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="$ROOT/backend/data"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

# ── Server IP ────────────────────────────────────────────────────────────────
SERVER="${1:-$SERVER}"
if [ -z "$SERVER" ]; then
  echo -e "${RED}Fout: geef het server IP-adres mee.${RESET}"
  echo "  Gebruik: ./sync_data.sh <server-ip>"
  echo "  Of:      SERVER=1.2.3.4 ./sync_data.sh"
  exit 1
fi

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PATH="${REMOTE_PATH:-/data/bookcompass/backend-data}"

# ── Bestanden die overgezet worden ────────────────────────────────────────────
FILES=(
  "books.db"
  "faiss_combined.index"
)

# ── Controleer of bestanden lokaal bestaan ────────────────────────────────────
echo -e "${BLUE}Controleren welke bestanden aanwezig zijn…${RESET}"
MISSING=0
for FILE in "${FILES[@]}"; do
  if [ -f "$DATA/$FILE" ]; then
    SIZE=$(du -sh "$DATA/$FILE" | cut -f1)
    echo -e "  ${GREEN}✓${RESET} $FILE ($SIZE)"
  else
    echo -e "  ${RED}✗ $FILE — niet gevonden in backend/data/${RESET}"
    MISSING=1
  fi
done

if [ "$MISSING" -eq 1 ]; then
  echo -e "\n${RED}Een of meer bestanden ontbreken. Voer eerst rebuild_index.sh uit.${RESET}"
  exit 1
fi

# ── Bevestiging ───────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Bestemming: ${REMOTE_USER}@${SERVER}:${REMOTE_PATH}${RESET}"
echo ""
read -r -p "Doorgaan? (j/n) " CONFIRM
if [[ "$CONFIRM" != "j" && "$CONFIRM" != "J" ]]; then
  echo "Afgebroken."
  exit 0
fi

# ── Map aanmaken op server ────────────────────────────────────────────────────
echo -e "\n${BLUE}Map aanmaken op server…${RESET}"
ssh "${REMOTE_USER}@${SERVER}" "mkdir -p ${REMOTE_PATH}"

# ── Rsync ─────────────────────────────────────────────────────────────────────
echo -e "${BLUE}Bestanden overzetten…${RESET}\n"
for FILE in "${FILES[@]}"; do
  echo -e "${BLUE}→ $FILE${RESET}"
  rsync -avz --progress \
    "$DATA/$FILE" \
    "${REMOTE_USER}@${SERVER}:${REMOTE_PATH}/$FILE"
  echo ""
done

echo -e "${GREEN}Klaar. Bestanden staan op ${SERVER}:${REMOTE_PATH}${RESET}"
echo ""
echo -e "Stel in Coolify het volgende volume in:"
echo -e "  ${BLUE}Source:      ${REMOTE_PATH}${RESET}"
echo -e "  ${BLUE}Destination: /app/data${RESET}"
