#!/usr/bin/env bash
# Renueva los tokens y sube el cambio al repo.
# Pensado para cron/systemd en un servidor.
set -euo pipefail

# Raíz del repo (este archivo vive en deploy/).
cd "$(dirname "$0")/.."

ARGS=()
if [[ -n "${SOURCES_FILE:-}" ]]; then
    ARGS+=(--config "$SOURCES_FILE")
fi
if [[ -n "${M3U_FILE:-}" ]]; then
    ARGS+=(--playlist "$M3U_FILE")
fi

# Trae lo que haya publicado el bot de GitHub u otro servidor.
git pull --rebase --autostash

python3 scripts/refresh_from_sources.py "${ARGS[@]}"

PLAYLIST="${M3U_FILE:-canales.m3u}"
git add -- "$PLAYLIST"

if git diff --staged --quiet; then
    echo "Sin cambios en $PLAYLIST."
    exit 0
fi

git commit -m "🤖 Tokens renovados [skip ci]"
git push
