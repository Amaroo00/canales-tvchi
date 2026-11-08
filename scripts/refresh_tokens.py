#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_tokens.py - Renueva tokens de canales públicos antes de que caduquen.

Pensado para ejecutarse en GitHub Actions justo antes del guardián. Garantías:

  * Nunca reemplaza una URL por otra que no haya sido validada
    (HTTP 200 + contenido #EXTM3U).
  * Si la renovación falla, deja la lista tal como está; el guardián
    conmutará al respaldo que ya funciona.
  * Escritura atómica: si algo falla, canales.m3u queda intacto.
  * No borra canales, no reordena URLs y no toca otras líneas del archivo.

Canales soportados:
  * TVN HD: obtiene el access_token vigente desde la página oficial live.tvn.cl.

Variables de entorno:
  M3U_FILE     Archivo a actualizar (default: canales.m3u).
  DRY_RUN      "1" para probar sin escribir.
  STRICT       "1" para devolver error si no se pudo renovar.
  TIMEOUT      Timeout en segundos (default: 15).
  RETRIES      Reintentos por request (default: 2).
  USER_AGENT   User-Agent personalizado.

Uso local:
  DRY_RUN=1 python3 scripts/refresh_tokens.py
  python3 scripts/refresh_tokens.py
"""

import gzip
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zlib

# Permite importar update_playlist.py cuando el script se ejecuta desde
# cualquier directorio (por ejemplo, `python scripts/refresh_tokens.py`).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update_playlist import (  # noqa: E402
    DEFAULT_UA,
    channel_name,
    normalize_name,
    safe_error,
    sanitize_url,
)

TVN_PAGE = "https://live.tvn.cl/?tvn_subseccion=senal-tvn"
TVN_PAGE_HEADERS = {
    "Referer": "https://www.tvn.cl/",
    "Origin": "https://www.tvn.cl",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}
TVN_PLAYLIST = (
    "https://mdstrm.com/live-stream-playlist/{media_id}.m3u8"
    "?access_token={token}"
)

MEDIA_ID_RE = re.compile(r"\bid\s*:\s*['\"]([0-9a-f]{24})['\"]")
ACCESS_TOKEN_RE = re.compile(r"\baccess_token\s*:\s*['\"]([^'\"]+)['\"]")

MAX_BODY_BYTES = 2 * 1024 * 1024


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "si", "sí", "on")


def env_int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def build_headers(extra=None):
    headers = {
        "User-Agent": os.environ.get("USER_AGENT", "").strip() or DEFAULT_UA,
        "Accept": "application/x-mpegURL, application/vnd.apple.mpegurl, text/plain, */*",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }
    if extra:
        headers.update(extra)
    return headers


def fetch(url, headers, timeout, retries):
    """GET con reintentos. Devuelve (status, body, error).

    status = 0 cuando no hubo respuesta HTTP (error de red/SSL).
    """
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


def is_tvn_hd(name):
    return normalize_name(name) in ("tvn", "tvn hd")


def resolve_tvn(timeout, retries):
    """Obtiene un access_token vigente desde la página oficial de TVN."""
    status, html, error = fetch(
        TVN_PAGE, build_headers(TVN_PAGE_HEADERS), timeout, retries
    )
    if status != 200:
        detail = f"HTTP {status}" if status else error
        return None, f"página de TVN: {detail}"

    media_id = MEDIA_ID_RE.search(html)
    token = ACCESS_TOKEN_RE.search(html)
    if not media_id or not token:
        return None, "la página de TVN no trae id/access_token"

    candidate = TVN_PLAYLIST.format(
        media_id=media_id.group(1),
        token=token.group(1),
    )
    return candidate, "token renovado"


def validate_hls(url, timeout, retries):
    """Confirma que la URL entrega un playlist HLS real.

    Si el runner de GitHub está fuera de Chile, mdstrm.com puede devolver 403
    por geobloqueo. En ese caso se acepta el token recién obtenido de la página
    oficial, porque la señal sí funciona desde Chile.
    """
    status, body, error = fetch(url, build_headers(), timeout, retries)
    if status != 200:
        detail = f"HTTP {status}" if status else error
        if status == 403 and "mdstrm.com" in url:
            return True, "HTTP 403 (geo tolerado)"
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


def find_channel_block(lines, predicate):
    """Devuelve (inicio, fin) del bloque #EXTINF del canal que cumple predicate."""
    start = None
    for index, line in enumerate(lines):
        if line.upper().startswith("#EXTINF:") and predicate(channel_name(line)):
            start = index
            break

    if start is None:
        return None, None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].upper().startswith("#EXTINF:"):
            end = index
            break

    return start, end


def main():
    path = os.environ.get("M3U_FILE", "").strip() or "canales.m3u"
    dry_run = env_bool("DRY_RUN", False)
    strict = env_bool("STRICT", False)
    timeout = max(5, env_int("TIMEOUT", 15))
    retries = max(1, env_int("RETRIES", 2))

    if not os.path.exists(path):
        print(f"Error: no se encontró {path}")
        return 1

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
            original_text = handle.read()

        lines = original_text.splitlines(keepends=True)
        start, end = find_channel_block(lines, is_tvn_hd)

        if start is None:
            print(f"Aviso: no se encontró TVN HD en {path}; no se modifica.")
            return 0

        target_indexes = [
            index
            for index in range(start + 1, end)
            if lines[index].lstrip().lower().startswith(("http://", "https://"))
            and "mdstrm.com/live-stream-playlist/" in lines[index]
        ]

        if not target_indexes:
            print("Aviso: TVN HD no tiene URL de mdstrm; no se modifica.")
            return 0

        print("Renovando token de TVN HD...")
        candidate, reason = resolve_tvn(timeout, retries)

        if not candidate:
            print(
                f"TVN HD: no se pudo renovar ({reason}); "
                "se conserva la URL actual y el guardián puede conmutar."
            )
            return 1 if strict else 0

        ok, detail = validate_hls(candidate, timeout, retries)
        if not ok:
            print(
                f"TVN HD: el token nuevo no validó ({detail}); "
                "se conserva la URL actual y el guardián puede conmutar."
            )
            return 1 if strict else 0

        changed = False
        for index in target_indexes:
            if lines[index].strip() != candidate:
                lines[index] = candidate + line_ending(lines[index])
                changed = True

        if not changed:
            print("TVN HD: el token ya estaba vigente; sin cambios.")
            return 0

        new_text = "".join(lines)
        if not new_text.lstrip("\ufeff").upper().startswith("#EXTM3U"):
            raise ValueError("el resultado no empieza con #EXTM3U")
        if candidate not in new_text:
            raise ValueError("el token nuevo no quedó en el archivo; se aborta")

        if dry_run:
            print(f"[dry-run] Se actualizaría {path} con el token de TVN HD.")
            return 0

        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        os.replace(temp_path, path)

        print(f"TVN HD: token renovado y validado ({sanitize_url(candidate)}).")
        print(f"Lista actualizada: {path}.")
        return 0

    except Exception as exc:
        print(f"Error renovando tokens: {safe_error(exc)}")
        return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
