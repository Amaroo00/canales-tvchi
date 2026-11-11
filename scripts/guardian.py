#!/usr/bin/env python3
"""Guardián autónomo: descubre, verifica audio/vídeo y publica listas y diagnóstico."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import shutil
import sys
from urllib.parse import urlsplit

from iptv import (BACKUPS, HEALTH, ROOT, allowed_url, atomic_write, load_catalog,
                  load_json, m3u_entry, verify_stream, write_json)
from refresh_tokens import resolve_tvn
from sync_public_sources import sync_sources

VERIFIED = {"online", "warning"}
ICONS = {"online": "🟢", "warning": "🟡", "unverified": "⚪",
         "offline": "🔴", "restricted": "🔒", "pending": "⏳"}
LABELS = {"online": "Operativo", "warning": "Con aviso", "unverified": "Sin verificar",
          "offline": "Fallo observado", "restricted": "Restringido", "pending": "Sin fuente"}


def public_attempt(candidate, result):
    # Nunca incluir URL completa, token ni stderr del proveedor en el diagnóstico.
    return {"host": urlsplit(candidate["url"]).hostname, "source": candidate["source"],
            **{key: value for key, value in result.items() if key != "preferred_url"}}


def choose_result(attempts):
    order = {"online": 0, "warning": 1, "unverified": 2, "restricted": 3, "offline": 4}
    return min(attempts, key=lambda item: order[item[1]["state"]]) if attempts else None


def check_channel(channel, candidates, previous_url=None, timeout=8, manifest_only=False):
    candidates = list(candidates)
    if previous_url and allowed_url(channel, previous_url):
        # Comprobar primero la última fuente seleccionada, sin perder los demás respaldos.
        candidates.sort(key=lambda item: item["url"] != previous_url)
    attempts = [(candidate, verify_stream(channel, candidate["url"], timeout, manifest_only))
                for candidate in candidates]
    chosen = choose_result(attempts)
    if chosen:
        candidate, result = chosen
        # Publicar la URL del proveedor, no la redirección firmada de una sesión de prueba.
        active_url = candidate["url"]
        state = result["state"]
        detail = result["detail"]
        # Si ninguna funciona no cambiar a un reemplazo "menos malo": conservar la anterior.
        if state not in VERIFIED:
            if previous_url and allowed_url(channel, previous_url):
                active_url = previous_url
            elif channel.get("urls"):
                active_url = channel["urls"][0]
    else:
        active_url, state = None, "pending"
        detail = channel.get("note", "No hay una fuente pública aprobada")
    health = {"id": channel["id"], "name": channel["name"], "group": channel["group"],
              "state": state, "detail": detail,
              "verified_backups": max(0, sum(result["state"] in VERIFIED for _, result in attempts) - 1),
              "candidate_count": len(candidates),
              "attempts": [public_attempt(candidate, result) for candidate, result in attempts]}
    if chosen:
        for key in ("audio", "video", "latency_ms"):
            if key in chosen[1]:
                health[key] = chosen[1][key]
    return channel, active_url, health


def markdown_cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_status(results, timestamp, warnings, excluded):
    counts = {state: sum(item[2]["state"] == state for item in results) for state in ICONS}
    verified = counts["online"] + counts["warning"]
    lines = ["# 📡 Estado de canales — Guardián IPTV Chile", "",
             f"> Última comprobación: **{timestamp}** (UTC).",
             f"> **{verified}/{len(results)} señales verificadas con vídeo y audio**; "
             f"{counts['unverified']} sin verificar, {counts['offline']} con fallo, "
             f"{counts['restricted']} restringidas y {counts['pending']} sin fuente.", "",
             "Un 401/403 no se considera operativo ni demuestra geobloqueo. Las pruebas reflejan la IP del runner de GitHub, no una TV en Chile.", "",
             "- `canales.m3u`: catálogo con fuente aprobada; conserva señales no verificadas y la última URL si fallan.",
             "- `canales_verificados.m3u`: únicamente las señales verificadas en esta ejecución.",
             "- Los respaldos contados abajo también se probaron; no son una garantía permanente.",
             "- Audio: muestra de 6 s. Detecta ausencia, silencio y posible saturación; no certifica calidad subjetiva ni corrige el sonido del emisor.", "",
             "| Canal | Grupo | Estado | Audio / vídeo de la muestra | Respaldos verificados | Detalle |",
             "| :--- | :--- | :--- | :--- | ---: | :--- |"]
    for channel, _, health in results:
        state = health["state"]
        audio, video = health.get("audio", {}), health.get("video", {})
        media = (f'{audio.get("codec_name", "?")} {audio.get("channels", "?")}ch, '
                 f'{audio.get("rms_dbfs", "?")} dBFS / {video.get("codec_name", "?")} '
                 f'{video.get("width", "?")}×{video.get("height", "?")}') if audio else "No comprobado"
        detail = health["detail"]
        if channel.get("not_24_7"):
            detail += "; puede no emitir las 24 h"
        lines.append("| " + " | ".join(map(markdown_cell, [channel["name"], channel["group"],
                     ICONS[state] + " " + LABELS[state], media, health["verified_backups"], detail])) + " |")
    if warnings:
        lines.extend(["", "## Avisos de actualización", ""] + ["- " + markdown_cell(item) for item in warnings])
    if excluded:
        lines.extend(["", "## Canales no publicados", ""] +
                     [f'- **{item["name"]}**: {item["reason"]}' for item in excluded])
    lines.extend(["", "Diagnóstico por fuente: [data/health.json](data/health.json).",
                  "Se conserva el catálogo aunque una señal falle; no se sustituye por otro canal.", ""])
    return "\n".join(lines)


def existing_urls(path):
    from update_playlist import parse_m3u
    import re
    if not path.exists():
        return {}
    entries = parse_m3u(path.read_text(encoding="utf-8-sig"))
    urls = {}
    for entry in entries:
        match = re.search(r'tvg-id="([^"]+)"', entry["header"])
        if match:
            urls[match.group(1)] = entry["urls"][0]
    return urls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No escribe archivos")
    parser.add_argument("--offline", action="store_true", help="Usa respaldos guardados, sin descargar listas ni renovar TVN")
    parser.add_argument("--manifest-only", action="store_true", help="Diagnóstico HLS sin declarar canales operativos")
    parser.add_argument("--require-media-tools", action="store_true", help="Falla si faltan ffmpeg/ffprobe (CI)")
    args = parser.parse_args()
    if args.require_media_tools and not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        parser.error("FFmpeg y FFprobe son obligatorios para publicar el diagnóstico en Actions")
    catalog = load_catalog()
    config = load_json(ROOT / "config/public_sources.json")
    bank = load_json(BACKUPS, {})
    if not args.offline:
        bank = sync_sources(catalog, config, bank)
    if not bank.get("channels"):
        bank = sync_sources(catalog, {"lists": [], "discover_pages": False}, {})
    warnings = list(bank.get("source_warnings", []))
    candidates = {key: list(value) for key, value in bank["channels"].items()}
    if not args.offline:
        for channel in catalog["channels"]:
            if channel.get("resolver") == "tvn":
                url, detail = resolve_tvn(timeout=config.get("timeout", 8), retries=2)
                if url and allowed_url(channel, url):
                    candidates.setdefault(channel["id"], []).insert(0, {"url": url, "source": "Reproductor público de TVN"})
                else:
                    warnings.append("TVN: " + detail + "; se conservan las fuentes aprobadas")
    playlist_path = ROOT / "canales.m3u"
    previous = existing_urls(playlist_path)
    workers = max(1, min(12, int(os.environ.get("GUARDIAN_WORKERS", "6"))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda ch: check_channel(
            ch, candidates.get(ch["id"], []), previous.get(ch["id"]),
            config.get("timeout", 8), args.manifest_only), catalog["channels"]))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    status = render_status(results, timestamp, warnings, catalog.get("excluded", []))
    health = {"version": 1, "checked_at": timestamp + " UTC", "vantage": "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") else "local",
              "warnings": warnings, "channels": [item[2] for item in results]}
    playlist = "#EXTM3U\n\n" + "".join(m3u_entry(ch, url) for ch, url, _ in results if url)
    verified_playlist = "#EXTM3U\n\n" + "".join(m3u_entry(ch, url) for ch, url, state in results
                                                 if url and state["state"] in VERIFIED)
    playlist = playlist.rstrip() + "\n"
    verified_playlist = verified_playlist.rstrip() + "\n"
    verified_count = sum(item[2]["state"] in VERIFIED for item in results)
    print(f"Verificados con vídeo/audio: {verified_count}/{len(results)}")
    for ch, _, state in results:
        print(f'{ch["name"]}: {state["state"]} — {state["detail"]}')
    if args.dry_run:
        print("Simulación: no se escribieron archivos.")
        return 0
    if not any(url for _, url, _ in results):
        raise ValueError("No hay fuentes aprobadas; se evita publicar una lista principal vacía")
    # Cada archivo se reemplaza de forma atómica; Git publica todos en un único commit.
    write_json(BACKUPS, bank)
    write_json(HEALTH, health)
    atomic_write(ROOT / "STATUS.md", status)
    atomic_write(ROOT / "canales_verificados.m3u", verified_playlist)
    atomic_write(playlist_path, playlist)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
