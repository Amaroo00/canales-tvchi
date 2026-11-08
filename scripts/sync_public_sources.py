#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_public_sources.py - Mantiene canales.m3u actualizado desde listas públicas.

Qué hace:
  1. Descarga las listas públicas configuradas (iptv-org Chile, m3u.cl Chile...).
  2. Indexa sus canales por nombre normalizado.
  3. Para cada canal de canales.m3u busca sus URLs en esas listas (usando
     `aliases` para los nombres que no coinciden exacto).
  4. Valida las URLs (HTTP 200 + #EXTM3U). Acepta 401/403 de CDNs chilenos
     que suelen geobloquear a los runners de GitHub.
  5. Deja primero las señales que funcionan y conserva hasta
     `max_urls_per_channel` por canal. Nunca borra canales ni cambia sus
     cabeceras #EXTINF.
  6. Escribe de forma atómica: si algo falla, canales.m3u queda intacto.

Uso:
  python scripts/sync_public_sources.py --dry-run
  python scripts/sync_public_sources.py
  python scripts/sync_public_sources.py --config config/public_sources.json
"""

import argparse
import gzip
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update_playlist import (  # noqa: E402
    DEFAULT_UA,
    channel_name,
    normalize_name,
    safe_error,
    sanitize_url,
)

DEFAULT_CONFIG = "config/public_sources.json"
DEFAULT_PLAYLIST = "canales.m3u"
MAX_BODY_BYTES = 8 * 1024 * 1024
HLS_ACCEPT = (
    "application/x-mpegURL, application/vnd.apple.mpegurl, "
    "text/plain, */*"
)

# CDNs chilenos que devuelven 403 a IPs fuera de Chile. Se consideran
# "presuntamente en línea" para no borrar señales buenas desde GitHub Actions.
GEO_403_HOSTS = (
    "gtd.cl",
    "rudo.video",
    "dps.live",
    "dpsgo.com",
    "mdstrm.com",
    "uchiletv.cl",
    "senado.cl",
)

# Prefijos de basura que agregan algunas listas al nombre.
DECOR_RE = re.compile(r"[✪★●•]")


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "si", "sí", "on")


def clean_key(name):
    """Normaliza un nombre de canal para comparar entre listas."""
    name = re.sub(r"\[[^\]]*\]", " ", name)          # [Geo-blocked], [Not 24/7]
    name = re.sub(r"\([^)]*\)", " ", name)           # (1080p), (Chile)
    name = re.sub(r"\|\s*(CL|Chile)\s*$", " ", name, flags=re.I)
    name = name.replace("+", " plus ")
    name = DECOR_RE.sub(" ", name)
    name = re.sub(r"\b(HD|SD|FHD|UHD)\b", " ", name, flags=re.I)
    return normalize_name(name)


def build_headers(url):
    headers = {
        "User-Agent": os.environ.get("USER_AGENT", "").strip() or DEFAULT_UA,
        "Accept": HLS_ACCEPT,
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }
    if "rudo.video" in url:
        headers["Referer"] = "https://rudo.video/"
        headers["Origin"] = "https://rudo.video"
    elif "mdstrm.com" in url:
        headers["Referer"] = "https://www.tvn.cl/"
        headers["Origin"] = "https://www.tvn.cl"
    elif "dps.live" in url or "dpsgo.com" in url or "13.cl" in url:
        headers["Referer"] = "https://www.13.cl/"
    elif "uchiletv" in url:
        headers["Referer"] = "https://uchiletv.cl/"
    elif "senado.cl" in url:
        headers["Referer"] = "https://tv.senado.cl/"
    return headers


def fetch(url, timeout, retries=1):
    """GET con reintentos. Devuelve (status, body, error)."""
    context = ssl.create_default_context()
    last_error = "Error desconocido"

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=build_headers(url))
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
                return response.getcode(), raw.decode(charset, errors="replace"), ""

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


def validate_hls(url, timeout):
    """Devuelve (ok, detalle). Tolera 401/403 de CDNs chilenos."""
    try:
        status, body, error = fetch(url, timeout)
        if status == 200:
            if body.lstrip("\ufeff \t\r\n").upper().startswith("#EXTM3U"):
                return True, "OK"
            return False, "no es M3U8"
        if status in (401, 403) and any(host in url for host in GEO_403_HOSTS):
            return True, f"HTTP {status} (geo tolerado)"
        return False, f"HTTP {status}" if status else error
    except Exception as exc:  # nunca debe tumbar el proceso
        return False, safe_error(exc)


def parse_list(text):
    """Parsea una lista M3U y devuelve [(nombre, [urls])]."""
    lines = [line.strip() for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    channels = []
    current = None
    for line in lines:
        if line.upper().startswith("#EXTINF:"):
            if current:
                channels.append(current)
            current = {"name": channel_name(line), "urls": []}
        elif current is not None and line.lower().startswith(("http://", "https://")):
            current["urls"].append(line)
    if current:
        channels.append(current)
    return channels


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("la configuración debe ser un objeto JSON")
    if not isinstance(config.get("lists"), list) or not config["lists"]:
        raise ValueError("la configuración no tiene una lista 'lists' con fuentes")
    return config


def download_lists(config, timeout, log):
    """Descarga todas las listas habilitadas y arma el índice de URLs."""
    index = {}
    errors = []

    for source in config["lists"]:
        if not isinstance(source, dict) or not source.get("enabled", True):
            continue
        name = str(source.get("name") or source.get("url") or "lista")
        url = str(source.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            errors.append(f"{name}: URL inválida")
            continue

        log(f"Descargando {name}: {sanitize_url(url)}")
        status, body, error = fetch(url, timeout)
        if status != 200:
            detail = f"HTTP {status}" if status else error
            errors.append(f"{name}: {detail}")
            log(f"  Aviso: no se pudo descargar ({detail})")
            continue

        channels = parse_list(body)
        if not channels:
            errors.append(f"{name}: no trajo canales")
            log("  Aviso: la lista no trajo canales")
            continue

        added = 0
        for channel in channels:
            key = clean_key(channel["name"])
            if not key:
                continue
            bucket = index.setdefault(key, [])
            for candidate in channel["urls"]:
                if candidate not in bucket:
                    bucket.append(candidate)
                    added += 1
        log(f"  {len(channels)} canales, {added} URLs indexadas")

    return index, errors


def line_ending(line):
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def iter_blocks(lines):
    starts = [
        index
        for index, line in enumerate(lines)
        if line.upper().startswith("#EXTINF:")
    ]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        yield start, end


def block_urls(lines, start, end):
    return [
        lines[index].strip()
        for index in range(start + 1, end)
        if lines[index].lstrip().lower().startswith(("http://", "https://"))
    ]


def rewrite_block(lines, start, end, final_urls):
    """Reemplaza las líneas de URL del bloque conservando el resto."""
    if not final_urls:
        return

    insert_at = None
    for index in range(start + 1, end):
        if lines[index].lstrip().lower().startswith(("http://", "https://")):
            insert_at = index
            break
    if insert_at is None:
        insert_at = start + 1

    ending = line_ending(lines[insert_at]) or "\n"
    replacement = [url + ending for url in final_urls]

    new_lines = []
    inserted = False
    for index in range(start, end):
        line = lines[index]
        is_url = index > start and line.lstrip().lower().startswith(
            ("http://", "https://")
        )
        if is_url:
            if not inserted:
                new_lines.extend(replacement)
                inserted = True
            continue
        new_lines.append(line)

    if not inserted:
        new_lines = [lines[start]] + replacement + new_lines[1:]

    lines[start:end] = new_lines


def resolve_candidates(channel, aliases, index):
    keys = [clean_key(channel)]
    for alias in aliases.get(channel, []):
        keys.append(clean_key(alias))

    candidates = []
    seen = set()
    for key in keys:
        for url in index.get(key, []):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    return candidates


def main():
    parser = argparse.ArgumentParser(
        description="Sincroniza canales.m3u con listas públicas."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--playlist", default=None)
    parser.add_argument("--dry-run", action="store_true", default=None)
    args = parser.parse_args()

    dry_run = args.dry_run if args.dry_run is not None else env_bool("DRY_RUN")

    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Error leyendo {args.config}: {safe_error(exc)}")
        return 1

    playlist_path = (
        args.playlist
        or os.environ.get("M3U_FILE", "").strip()
        or str(config.get("playlist") or DEFAULT_PLAYLIST)
    )
    if not os.path.exists(playlist_path):
        print(f"Error: no se encontró {playlist_path}")
        return 1

    timeout = max(5, int(config.get("timeout", 12)))
    max_urls = max(1, int(config.get("max_urls_per_channel", 3)))
    aliases = config.get("aliases") or {}
    blocked = [
        str(item)
        for item in (config.get("blocked_url_contains") or [])
        if str(item).strip()
    ]

    index, errors = download_lists(config, timeout, print)
    if not index:
        print("Error: ninguna lista pública entregó canales; se aborta sin tocar la lista.")
        return 1

    with open(playlist_path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        original_text = handle.read()
    lines = original_text.splitlines(keepends=True)

    # 1. Recolectar todas las URLs a validar (existentes + candidatas).
    plan = []
    for start, end in iter_blocks(lines):
        name = channel_name(lines[start].strip())
        original = block_urls(lines, start, end)
        existing = original
        candidates = resolve_candidates(name, aliases, index)
        if blocked:
            filtered = [u for u in existing if not any(b in u for b in blocked)]
            if filtered:
                existing = filtered
            candidates = [u for u in candidates if not any(b in u for b in blocked)]
        plan.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "existing": existing,
                "original": original,
                "candidates": candidates,
            }
        )

    all_urls = []
    seen = set()
    for item in plan:
        for url in item["existing"] + item["candidates"]:
            if url not in seen:
                seen.add(url)
                all_urls.append(url)

    print(f"Validando {len(all_urls)} URLs únicas en {len(plan)} canales...")
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = dict(zip(all_urls, executor.map(lambda u: validate_hls(u, timeout), all_urls)))

    # 2. Calcular la lista final de URLs por canal.
    changed = 0
    report = []
    edits = []
    for item in plan:
        existing = item["existing"]
        candidates = item["candidates"]

        working_existing = [u for u in existing if results.get(u, (False, ""))[0]]
        working_new = [
            u
            for u in candidates
            if u not in existing and results.get(u, (False, ""))[0]
        ]
        dead_existing = [u for u in existing if u not in working_existing]

        working = working_existing + working_new
        if working:
            # Solo señales que respondieron; máximo configurado.
            final = working[:max_urls]
            detail = f"{len(final)} señal(es) OK"
        else:
            # Nada respondió: no se toca el canal (el guardián lo reportará).
            final = existing
            detail = "sin señal verificable (se conserva)"

        if final != item["original"]:
            edits.append((item, final))
            changed += 1

        report.append((item["name"], detail, len(dead_existing)))

    # Se aplican de abajo hacia arriba para no desplazar los índices.
    for item, final in sorted(edits, key=lambda edit: edit[0]["start"], reverse=True):
        rewrite_block(lines, item["start"], item["end"], final)

    new_text = "".join(lines)

    if not new_text.lstrip("\ufeff").upper().startswith("#EXTM3U"):
        print("Error: el resultado no empieza con #EXTM3U; se aborta.")
        return 1

    old_count = sum(1 for line in original_text.splitlines() if line.upper().startswith("#EXTINF:"))
    new_count = sum(1 for line in new_text.splitlines() if line.upper().startswith("#EXTINF:"))
    if old_count != new_count:
        print(f"Error: cambió la cantidad de canales ({old_count} -> {new_count}); se aborta.")
        return 1

    print("\n--- Resultado por canal ---")
    for name, detail, dropped in report:
        suffix = f", {dropped} URL(s) caída(s) retirada(s)" if dropped else ""
        print(f"  {name}: {detail}{suffix}")

    if errors:
        print("\nAvisos de fuentes:")
        for error in errors:
            print(f"  - {error}")

    if changed == 0:
        print("\nSin cambios: canales.m3u ya está actualizado.")
        return 0

    if dry_run:
        print(f"\n[dry-run] Se actualizarían {changed} canal(es) en {playlist_path}.")
        return 0

    temp_path = playlist_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        os.replace(temp_path, playlist_path)
    except OSError as exc:
        print(f"Error escribiendo {playlist_path}: {safe_error(exc)}")
        return 1

    print(f"\nLista actualizada: {playlist_path} ({changed} canal(es) modificado(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
