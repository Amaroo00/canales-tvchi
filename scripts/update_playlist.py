#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_playlist.py - Descarga la última lista M3U desde una URL privada
y la guarda en el repositorio.

La URL NUNCA se escribe en el repo: se lee de la variable de entorno
PLAYLIST_URL (en GitHub Actions va como secret).

Uso local:
    PLAYLIST_URL='https://...' python scripts/update_playlist.py

Variables de entorno:
    PLAYLIST_URL       URL de la lista (obligatoria; en CI es un secret).
    PLAYLIST_HEADERS   JSON con headers extra, por ejemplo:
                       {"Referer": "https://ejemplo.cl/", "Origin": "https://ejemplo.cl"}
    PLAYLIST_COOKIE    Valor del header Cookie (opcional; mejor como secret).
    OUTPUT_FILE        Archivo de salida (default: canales.m3u).
    MERGE_MODE         "merge" (default) conserva los canales que ya tienes
                       y agrega/actualiza los de la lista nueva.
                       "replace" deja solamente la lista descargada.
    ONLY_CHANNELS      Lista separada por comas de nombres/partes de nombre
                       a conservar de la lista descargada (ej: "TNT Sport").
    MIN_CHANNELS       Mínimo de canales para aceptar la descarga (default: 1).
    USER_AGENT         User-Agent personalizado.
    TIMEOUT            Timeout en segundos (default: 30).
    RETRIES            Reintentos (default: 3).
    ALLOW_INSECURE_SSL "1" para aceptar certificados SSL inválidos.
    STRICT             "1" para que el script falle si la descarga falla.
    DRY_RUN            "1" para probar sin escribir el archivo.
"""

import gzip
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib

DEFAULT_OUTPUT = "canales.m3u"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "si", "sí", "on")


def env_int(name, default):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def sanitize_url(url):
    """Devuelve solo esquema y dominio, sin path, query ni credenciales."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}/..."
    except Exception:
        return "<url>"


def safe_error(exc):
    """Evita filtrar tokens o credenciales en los mensajes de error."""
    message = str(exc)
    message = re.sub(
        r"https?://[^\s'\"]+",
        lambda match: sanitize_url(match.group(0)),
        message,
    )
    return message[:300]


def build_headers():
    headers = {
        "User-Agent": os.environ.get("USER_AGENT", "").strip() or DEFAULT_UA,
        "Accept": "application/x-mpegURL, application/vnd.apple.mpegurl, text/plain, */*",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }

    raw_headers = os.environ.get("PLAYLIST_HEADERS", "").strip()
    if raw_headers:
        try:
            extra = json.loads(raw_headers)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
            else:
                print("Aviso: PLAYLIST_HEADERS debe ser un objeto JSON; se ignora.")
        except json.JSONDecodeError as exc:
            print(f"Aviso: PLAYLIST_HEADERS no es JSON válido ({exc}); se ignora.")

    cookie = os.environ.get("PLAYLIST_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie

    return headers


def fetch_playlist(url, headers, timeout, retries, insecure_ssl):
    context = ssl.create_default_context()
    if insecure_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    last_error = "Error desconocido"

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    raw = zlib.decompress(raw)

                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")

        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            break

        except (urllib.error.URLError, OSError) as exc:
            last_error = safe_error(exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            break

    raise RuntimeError(last_error)


def parse_m3u(text):
    """Parsea canales conservando header, opciones y todas sus URLs."""
    text = text.lstrip("\ufeff")
    lines = [line.strip() for line in text.splitlines()]
    if not any(line.upper().startswith("#EXTM3U") for line in lines[:5]):
        raise ValueError("La respuesta no parece un M3U: no se encontró #EXTM3U")

    channels = []
    current = None

    for line in lines:
        if not line:
            continue

        if line.upper().startswith("#EXTINF:"):
            if current and current["urls"]:
                channels.append(current)
            current = {"header": line, "extra": [], "urls": []}
        elif current is not None:
            if line.startswith("#"):
                if not line.upper().startswith("#EXTM3U"):
                    current["extra"].append(line)
            elif line.lower().startswith(("http://", "https://")):
                current["urls"].append(line)

    if current and current["urls"]:
        channels.append(current)

    return channels


def split_extinf(header):
    """Separa atributos y nombre en el primer comma fuera de comillas."""
    in_quotes = False
    for index, char in enumerate(header):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            return header[:index], header[index + 1:].strip()
    return header, ""


def channel_name(header):
    return split_extinf(header)[1]


def normalize_name(name):
    name = unicodedata.normalize("NFKD", name)
    name = "".join(char for char in name if not unicodedata.combining(char))
    name = name.casefold()
    name = "".join(char if char.isalnum() else " " for char in name)
    return " ".join(name.split())


def dedupe_urls(urls):
    seen = set()
    result = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def merge_channels(downloaded, existing):
    """Fusiona por nombre: la lista nueva manda, los canales viejos se conservan."""
    merged = []
    index = {}

    for channel in downloaded:
        key = normalize_name(channel_name(channel["header"])) or channel["header"]
        if key in index:
            target = index[key]
            target["urls"] = dedupe_urls(target["urls"] + channel["urls"])
            for extra in channel["extra"]:
                if extra not in target["extra"]:
                    target["extra"].append(extra)
        else:
            item = {
                "header": channel["header"],
                "extra": list(channel["extra"]),
                "urls": list(channel["urls"]),
            }
            index[key] = item
            merged.append(item)

    for channel in existing:
        key = normalize_name(channel_name(channel["header"])) or channel["header"]
        if key in index:
            target = index[key]
            target["urls"] = dedupe_urls(target["urls"] + channel["urls"])
            for extra in channel["extra"]:
                if extra not in target["extra"]:
                    target["extra"].append(extra)
        else:
            item = {
                "header": channel["header"],
                "extra": list(channel["extra"]),
                "urls": list(channel["urls"]),
            }
            index[key] = item
            merged.append(item)

    return merged


def filter_channels(channels, patterns):
    if not patterns:
        return channels

    normalized_patterns = [normalize_name(pattern) for pattern in patterns if pattern.strip()]
    if not normalized_patterns:
        return channels

    result = []
    for channel in channels:
        name = normalize_name(channel_name(channel["header"]))
        if any(pattern in name for pattern in normalized_patterns):
            result.append(channel)
    return result


def render_m3u(channels):
    lines = ["#EXTM3U", ""]
    for channel in channels:
        lines.append(channel["header"])
        lines.extend(channel["extra"])
        lines.extend(channel["urls"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_existing(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return parse_m3u(handle.read())
    except Exception as exc:
        print(f"Aviso: no se pudo leer {path} para fusionar ({safe_error(exc)}); se reemplaza.")
        return []


def main():
    url = os.environ.get("PLAYLIST_URL", "").strip()
    if not url:
        print("PLAYLIST_URL no está configurada; se omite la actualización de la lista.")
        return 0

    output = os.environ.get("OUTPUT_FILE", "").strip() or DEFAULT_OUTPUT
    mode = os.environ.get("MERGE_MODE", "merge").strip().lower()
    if mode not in ("merge", "replace"):
        print(f"Aviso: MERGE_MODE inválido ({mode}); se usa merge.")
        mode = "merge"

    only_channels = [
        item.strip()
        for item in os.environ.get("ONLY_CHANNELS", "").split(",")
        if item.strip()
    ]

    min_channels = max(1, env_int("MIN_CHANNELS", 1))
    timeout = max(5, env_int("TIMEOUT", 30))
    retries = max(1, env_int("RETRIES", 3))
    strict = env_bool("STRICT", False)
    dry_run = env_bool("DRY_RUN", False)
    insecure_ssl = env_bool("ALLOW_INSECURE_SSL", False)

    try:
        print(f"Descargando lista desde {sanitize_url(url)} ...")
        text = fetch_playlist(url, build_headers(), timeout, retries, insecure_ssl)

        downloaded = parse_m3u(text)
        if only_channels:
            downloaded = filter_channels(downloaded, only_channels)

        if len(downloaded) < min_channels:
            raise ValueError(
                f"La lista descargada tiene {len(downloaded)} canales; "
                f"se esperaban al menos {min_channels}"
            )

        if mode == "merge":
            existing = read_existing(output)
            channels = merge_channels(downloaded, existing)
        else:
            channels = downloaded

        new_text = render_m3u(channels)

        old_text = ""
        if os.path.exists(output):
            with open(output, "r", encoding="utf-8", errors="replace") as handle:
                old_text = handle.read()

        if new_text == old_text:
            print(f"Sin cambios: {output} ya está actualizado ({len(channels)} canales).")
            return 0

        if dry_run:
            print(
                f"[dry-run] Se actualizaría {output}: "
                f"{len(downloaded)} descargados, {len(channels)} finales."
            )
            return 0

        temp_path = output + ".tmp"
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(new_text)
        os.replace(temp_path, output)

        print(
            f"Lista actualizada: {output} "
            f"({len(downloaded)} descargados, {len(channels)} finales, "
            f"{len(new_text)} bytes)."
        )
        return 0

    except Exception as exc:
        print(f"Error actualizando la lista: {safe_error(exc)}")
        return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
