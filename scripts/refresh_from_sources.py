#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_from_sources.py - Renueva tokens/URLs m3u8 desde fuentes configurables.

La idea es simple: tú pones en `config/sources.json` la página o API de cada
canal y un patrón para encontrar la URL m3u8. El script:

  1. Descarga cada fuente.
  2. Extrae las URLs que coincidan con los patrones.
  3. Valida cada candidata (HTTP 200 + #EXTM3U).
  4. Solo si valida, reemplaza la URL correspondiente en la lista.
  5. Escribe de forma atómica: si algo falla, la lista queda intacta.

No borra canales, no reordena la lista y no toca líneas que no correspondan.

Uso:
  python3 scripts/refresh_from_sources.py --dry-run
  python3 scripts/refresh_from_sources.py
  python3 scripts/refresh_from_sources.py --config config/sources.local.json

Variables de entorno:
  SOURCES_FILE   Ruta del JSON de fuentes (default: config/sources.json o
                 config/sources.local.json si existe).
  M3U_FILE       Lista a actualizar (default: el "playlist" del JSON).
  DRY_RUN        "1" para probar sin escribir.
  STRICT         "1" para devolver error si alguna fuente falló.
  USER_AGENT     User-Agent personalizado.

Formato del JSON: ver config/sources.example.json y docs/RENOVAR_TOKENS.md.
"""

import argparse
import gzip
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update_playlist import (  # noqa: E402
    DEFAULT_UA,
    channel_name,
    normalize_name,
    safe_error,
    sanitize_url,
)

DEFAULT_PLAYLIST = "canales.m3u"
DEFAULT_CONFIG = "config/sources.json"
LOCAL_CONFIG = "config/sources.local.json"
MAX_BODY_BYTES = 4 * 1024 * 1024
HLS_ACCEPT = (
    "application/x-mpegURL, application/vnd.apple.mpegurl, "
    "text/plain, */*"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "si", "sí", "on")


def expand_env(value):
    """Reemplaza ${VAR} por variables de entorno (para cookies/API keys)."""
    if not isinstance(value, str):
        return value
    return ENV_RE.sub(lambda match: os.environ.get(match.group(1), ""), value)


def build_headers(source, accept=HTML_ACCEPT):
    headers = {
        "User-Agent": os.environ.get("USER_AGENT", "").strip() or DEFAULT_UA,
        "Accept": accept,
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }
    extra = source.get("headers") or {}
    if isinstance(extra, dict):
        headers.update(
            {str(key): expand_env(str(value)) for key, value in extra.items()}
        )
    return headers


def fetch(url, headers, timeout, retries):
    """GET con reintentos. Devuelve (status, body, error)."""
    context = ssl.create_default_context()
    last_error = "Error desconocido"

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(
                request, timeout=timeout, context=context
            ) as response:
                raw = response.read(MAX_BODY_BYTES)
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    raw = zlib.decompress(raw)

                charset = response.headers.get_content_charset() or "utf-8"
                return (
                    response.getcode(),
                    raw.decode(charset, errors="replace"),
                    "",
                )

        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return exc.code, "", last_error

        except (urllib.error.URLError, OSError) as exc:
            last_error = safe_error(exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue

    return 0, "", last_error


def extract_candidates(page_url, body, patterns):
    """Extrae URLs candidatas del HTML/JSON de una fuente."""
    text = html.unescape(body).replace("\\/", "/")
    candidates = []
    seen = set()

    for pattern in patterns:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"patrón inválido ({pattern!r}): {exc}") from exc

        for match in regex.finditer(text):
            if match.groups() and match.group(1):
                value = match.group(1)
            else:
                value = match.group(0)

            value = value.strip().strip("'\"<>()[],;")
            if not value:
                continue

            value = urljoin(page_url, value)
            if not value.lower().startswith(("http://", "https://")):
                continue
            if value not in seen:
                seen.add(value)
                candidates.append(value)

    return candidates


def validate_hls(url, source, timeout, retries):
    """Confirma que la URL entrega un playlist HLS real."""
    status, body, error = fetch(
        url, build_headers(source, accept=HLS_ACCEPT), timeout, retries
    )
    if status != 200:
        detail = f"HTTP {status}" if status else error
        return False, detail

    if not body.lstrip("\ufeff \t\r\n").upper().startswith("#EXTM3U"):
        return False, "la respuesta no es un M3U8"

    return True, "OK"


def line_ending(line):
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def all_blocks(lines):
    """Genera (inicio, fin) de cada bloque #EXTINF."""
    starts = [
        index
        for index, line in enumerate(lines)
        if line.upper().startswith("#EXTINF:")
    ]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        yield start, end


def find_channel_blocks(lines, name):
    """Devuelve los bloques cuyo nombre de canal coincide (normalizado)."""
    key = normalize_name(name)
    return [
        (start, end)
        for start, end in all_blocks(lines)
        if normalize_name(channel_name(lines[start])) == key
    ]


def replace_in_block(lines, start, end, candidate, markers, add_if_missing):
    """Reemplaza la URL objetivo dentro de un bloque. Devuelve (cambiado, detalle)."""
    url_indexes = [
        index
        for index in range(start + 1, end)
        if lines[index].lstrip().lower().startswith(("http://", "https://"))
    ]

    targets = []
    if markers:
        lowered = [marker.lower() for marker in markers]
        targets = [
            index
            for index in url_indexes
            if any(marker in lines[index].lower() for marker in lowered)
        ]
    else:
        targets = url_indexes[:1]

    if not targets:
        if any(lines[index].strip() == candidate for index in url_indexes):
            return False, "ya estaba actualizado"
        if not add_if_missing:
            return False, "no se encontró una URL que coincida"
        insert_at = (url_indexes[-1] + 1) if url_indexes else (start + 1)
        ending = line_ending(lines[url_indexes[-1]]) if url_indexes else "\n"
        lines.insert(insert_at, candidate + ending)
        return True, "URL agregada"

    changed = False
    for index in targets:
        if lines[index].strip() != candidate:
            lines[index] = candidate + line_ending(lines[index])
            changed = True

    # Evita dejar dos veces la misma URL dentro del mismo bloque.
    seen = set()
    remove = []
    for index in range(start + 1, end):
        value = lines[index].strip()
        if value.lower().startswith(("http://", "https://")):
            if value in seen:
                remove.append(index)
            else:
                seen.add(value)
    for index in reversed(remove):
        del lines[index]

    if changed or remove:
        return True, "token/URL renovado"
    return False, "ya estaba actualizado"


def count_extinf(text):
    return sum(
        1 for line in text.splitlines() if line.upper().startswith("#EXTINF:")
    )


def load_config(path):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"no se encontró {path}. Copia config/sources.example.json "
            "a config/sources.json y agrega tus fuentes."
        )

    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    if not isinstance(config, dict):
        raise ValueError("la configuración debe ser un objeto JSON")
    if not isinstance(config.get("sources"), list) or not config["sources"]:
        raise ValueError("la configuración no tiene una lista 'sources' con fuentes")

    return config


def resolve_config_path(explicit):
    if explicit:
        return explicit
    env_path = os.environ.get("SOURCES_FILE", "").strip()
    if env_path:
        return env_path
    if os.path.exists(LOCAL_CONFIG):
        return LOCAL_CONFIG
    return DEFAULT_CONFIG


def process_source(source, lines, timeout, retries, delay, log):
    """Procesa una fuente. Devuelve (cambiada, error)."""
    name = str(source.get("name", "")).strip()
    page = expand_env(str(source.get("page", "")).strip())
    patterns = source.get("patterns") or []

    if not name:
        return False, "falta 'name'"
    if not page.lower().startswith(("http://", "https://")):
        return False, "falta 'page' o no es una URL http(s)"
    if not isinstance(patterns, list) or not patterns:
        return False, "falta 'patterns' (lista de expresiones regulares)"

    log(f"  Fuente: {sanitize_url(page)}")
    status, body, error = fetch(
        page, build_headers(source), timeout, retries
    )
    if status != 200:
        detail = f"HTTP {status}" if status else error
        return False, f"no se pudo descargar la fuente ({detail})"

    try:
        candidates = extract_candidates(page, body, patterns)
    except ValueError as exc:
        return False, str(exc)

    if not candidates:
        return False, "la fuente no entregó ninguna URL que coincida"

    log(f"  Candidatas encontradas: {len(candidates)}")

    candidate = None
    last_detail = ""
    for possible in candidates:
        ok, detail = validate_hls(possible, source, timeout, retries)
        if ok:
            candidate = possible
            break
        last_detail = detail

    if not candidate:
        return False, f"ninguna candidata validó ({last_detail})"

    log(f"  URL validada: {sanitize_url(candidate)}")

    blocks = find_channel_blocks(lines, name)
    if not blocks:
        return False, f"no se encontró el canal '{name}' en la lista"

    markers = source.get("replace_urls_containing") or []
    if isinstance(markers, str):
        markers = [markers]
    markers = [str(marker) for marker in markers if str(marker).strip()]
    add_if_missing = bool(source.get("add_if_missing", False))

    changed = False
    details = []
    for start, end in reversed(blocks):
        block_changed, detail = replace_in_block(
            lines, start, end, candidate, markers, add_if_missing
        )
        changed = changed or block_changed
        details.append(detail)

    if delay > 0:
        time.sleep(delay)

    return changed, "; ".join(dict.fromkeys(details))


def main():
    parser = argparse.ArgumentParser(
        description="Renueva tokens/URLs m3u8 desde fuentes configurables."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="JSON de fuentes (default: config/sources.local.json o sources.json).",
    )
    parser.add_argument(
        "--playlist",
        default=None,
        help="Lista M3U a actualizar (default: el 'playlist' del JSON).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Muestra los cambios sin escribir el archivo.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=None,
        help="Devuelve error si alguna fuente falla.",
    )
    args = parser.parse_args()

    dry_run = args.dry_run if args.dry_run is not None else env_bool("DRY_RUN")
    strict = args.strict if args.strict is not None else env_bool("STRICT")

    config_path = resolve_config_path(args.config)
    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Error leyendo la configuración: {safe_error(exc)}")
        return 1

    playlist_path = (
        args.playlist
        or os.environ.get("M3U_FILE", "").strip()
        or str(config.get("playlist") or DEFAULT_PLAYLIST)
    )
    timeout = max(5, int(config.get("timeout", 20)))
    retries = max(1, int(config.get("retries", 2)))
    delay = max(0.0, float(config.get("delay_seconds", 1)))

    if not os.path.exists(playlist_path):
        print(f"Error: no se encontró la lista {playlist_path}")
        return 1

    try:
        with open(
            playlist_path, "r", encoding="utf-8", errors="replace", newline=""
        ) as handle:
            original_text = handle.read()
    except OSError as exc:
        print(f"Error leyendo {playlist_path}: {safe_error(exc)}")
        return 1

    lines = original_text.splitlines(keepends=True)
    sources = [
        source
        for source in config["sources"]
        if isinstance(source, dict) and source.get("enabled", True)
    ]

    if not sources:
        print("Aviso: no hay fuentes habilitadas en la configuración.")
        return 0

    print(
        f"Renovando desde {len(sources)} fuente(s) "
        f"en {playlist_path} (config: {config_path})..."
    )

    changed_sources = 0
    failures = 0

    for position, source in enumerate(sources, start=1):
        name = str(source.get("name", "")).strip() or "(sin nombre)"
        print(f"[{position}/{len(sources)}] {name}")
        changed, detail = process_source(
            source, lines, timeout, retries, delay, print
        )
        if changed:
            changed_sources += 1
            print(f"  Resultado: {detail}")
        else:
            if detail and "ya estaba actualizado" in detail:
                print(f"  Resultado: {detail}")
            else:
                failures += 1
                print(f"  Aviso: {detail}")

    if changed_sources == 0:
        print(
            f"Sin cambios. Fuentes con problemas: {failures}. "
            "La lista quedó intacta."
        )
        return 1 if strict and failures else 0

    new_text = "".join(lines)

    if not new_text.lstrip("\ufeff").upper().startswith("#EXTM3U"):
        print("Error: el resultado no empieza con #EXTM3U; se aborta.")
        return 1
    if count_extinf(new_text) != count_extinf(original_text):
        print("Error: cambió la cantidad de canales; se aborta.")
        return 1

    if dry_run:
        print(
            f"[dry-run] Se actualizaría {playlist_path}: "
            f"{changed_sources} fuente(s) renovada(s), {failures} con problemas."
        )
        return 1 if strict and failures else 0

    temp_path = playlist_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        os.replace(temp_path, playlist_path)
    except OSError as exc:
        print(f"Error escribiendo {playlist_path}: {safe_error(exc)}")
        return 1

    print(
        f"Lista actualizada: {playlist_path}. "
        f"Fuentes renovadas: {changed_sources}. Con problemas: {failures}."
    )
    return 1 if strict and failures else 0


if __name__ == "__main__":
    sys.exit(main())
