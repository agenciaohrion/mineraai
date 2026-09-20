#!/usr/bin/env bash
# MineraAI — sobe o ecossistema completo
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# carrega .env manualmente (sem dependência extra em runtime)
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

exec .venv/bin/uvicorn server.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
