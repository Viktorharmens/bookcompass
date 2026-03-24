#!/bin/bash
# Start backend + frontend tegelijk.
# Gebruik: ./start.sh
# Stop alles: Ctrl+C

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RESET='\033[0m'

cleanup() {
  echo -e "\n${BLUE}Stoppen…${RESET}"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  echo "Klaar."
  exit 0
}
trap cleanup INT TERM

# ── Backend ────────────────────────────────────────────────────────────────
if [ ! -d "$BACKEND/venv" ]; then
  echo -e "${BLUE}[backend] Virtual environment aanmaken…${RESET}"
  python3 -m venv "$BACKEND/venv"
fi

echo -e "${BLUE}[backend] Dependencies controleren…${RESET}"
"$BACKEND/venv/bin/pip" install -q -r "$BACKEND/requirements.txt"

if [ ! -f "$BACKEND/data/faiss_topic.index" ]; then
  echo -e "${BLUE}[backend] FAISS-index bouwen (eenmalig, ~3-5 min)…${RESET}"
  cd "$BACKEND" || exit 1
  "$BACKEND/venv/bin/python" build_index.py
  cd "$ROOT" || exit 1
fi

echo -e "${GREEN}[backend]  http://localhost:8000${RESET}"
cd "$BACKEND" || exit 1
"$BACKEND/venv/bin/python" -m uvicorn main:app --reload 2>&1 | \
  sed 's/^/[backend] /' &
BACKEND_PID=$!
cd "$ROOT" || exit 1

# ── Frontend ───────────────────────────────────────────────────────────────
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo -e "${BLUE}[frontend] npm install uitvoeren…${RESET}"
  npm --prefix "$FRONTEND" install --silent
fi

echo -e "${GREEN}[frontend] http://localhost:3000${RESET}"
npm --prefix "$FRONTEND" run dev 2>&1 | \
  sed 's/^/[frontend] /' &
FRONTEND_PID=$!

echo -e "\n${BLUE}Druk op Ctrl+C om alles te stoppen.${RESET}\n"
wait
