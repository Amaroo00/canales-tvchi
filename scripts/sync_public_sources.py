#!/usr/bin/env python3
"""Descubre respaldos solo para el catálogo aprobado; nunca confunde canales."""

import argparse
from datetime import datetime, timezone
import html
import re
import sys

from iptv import (BACKUPS, ROOT, StreamError, allowed_url, fetch, load_catalog,
                  load_json, name_key, stable_url, write_json)
from update_playlist import channel_name, parse_m3u


def page_candidates(channel, timeout):
    raw, _, _ = fetch(channel["page"], timeout=timeout)
    text = html.unescape(raw.decode("utf-8", errors="replace")).replace("\\/", "/")
    return [(url, "Página pública de la emisora") for url in
            re.findall(r"https://[^\s\"'<>\\]+\.m3u8(?:\?[^\s\"'<>\\]*)?", text)
            if allowed_url(channel, url)]


def sync_sources(catalog, config, previous=None, log=print):
    by_name = {}
    by_id = {}
    warnings = []
    for source in config.get("lists", []):
        if not source.get("enabled", True):
            continue
        try:
            raw, _, _ = fetch(source["url"], timeout=config.get("timeout", 10))
            entries = parse_m3u(raw.decode("utf-8-sig", errors="replace"))
            if not entries:
                raise ValueError("La fuente no entregó canales")
            for entry in entries:
                by_name.setdefault(name_key(channel_name(entry["header"])), []).extend(
                    (url, source["name"]) for url in entry["urls"])
                match = re.search(r'tvg-id="([^"@]+)(?:@[^" ]*)?"', entry["header"])
                if match:
                    by_id.setdefault(match.group(1).casefold(), []).extend(
                        (url, source["name"]) for url in entry["urls"])
            log(f'{source["name"]}: {len(entries)} entradas leídas')
        except (StreamError, ValueError) as exc:
            warnings.append(f'{source["name"]}: {exc}')
            log("Aviso: " + warnings[-1])
    bank = {"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
            "source_warnings": warnings, "channels": {}}
    for channel in catalog["channels"]:
        candidates = []
        if channel.get("discover_page") and config.get("discover_pages", True):
            try:
                candidates.extend(page_candidates(channel, config.get("timeout", 8)))
            except StreamError as exc:
                warnings.append(channel["name"] + ": página pública: " + exc.detail)
        candidates.extend((url, "Catálogo aprobado") for url in channel.get("urls", []))
        candidates.extend((item["url"], item["source"]) for item in
                          (previous or {}).get("channels", {}).get(channel["id"], []))
        candidates.extend(by_id.get(channel["id"].casefold(), []))
        for name in [channel["name"]] + channel.get("aliases", []):
            candidates.extend(by_name.get(name_key(name), []))
        selected = []
        seen = set()
        for url, source in candidates:
            url = stable_url(url)
            if url and url not in seen and allowed_url(channel, url):
                seen.add(url)
                selected.append({"url": url, "source": source})
        bank["channels"][channel["id"]] = selected[:config.get("max_urls_per_channel", 5)]
    return bank


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config/public_sources.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog()
    bank = sync_sources(catalog, load_json(args.config), load_json(BACKUPS, {}))
    print(f'{len(bank["channels"])} canales del catálogo; ningún canal externo se agrega sin aprobación.')
    if not args.dry_run:
        write_json(BACKUPS, bank)
    return 0


if __name__ == "__main__":
    sys.exit(main())
