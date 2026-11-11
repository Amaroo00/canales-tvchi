#!/usr/bin/env python3
"""Resuelve solo el reproductor público de TVN, sin login ni eludir restricciones.

La renovación se ejecuta dentro de guardian.py. El token, si existe, es del
reproductor público (no de una cuenta), se prueba antes de seleccionarse y no
se guarda en el banco de respaldos ni en los logs.
"""

import re
import sys
from urllib.parse import quote

from iptv import StreamError, fetch

TVN_PAGE = "https://live.tvn.cl/?tvn_subseccion=senal-tvn"
MEDIA_ID = "57a498c4d7b86d600e5461cb"
MEDIA_ID_RE = re.compile(r"\bid\s*:\s*['\"]([0-9a-f]{24})['\"]")
ACCESS_TOKEN_RE = re.compile(r"\baccess_token\s*:\s*['\"]([^'\"]+)['\"]")


def resolve_tvn(timeout=8, retries=2):
    try:
        raw, _, _ = fetch(TVN_PAGE, {"Referer": "https://www.tvn.cl/",
                                    "Accept": "text/html", "User-Agent": "Mozilla/5.0"},
                          timeout, retries=retries)
    except StreamError as exc:
        return None, "reproductor público: " + exc.detail
    html = raw.decode("utf-8", errors="replace")
    ids = MEDIA_ID_RE.findall(html)
    token = ACCESS_TOKEN_RE.search(html)
    # No tomar el ID de publicidad ni sustituir TVN por otra señal.
    if MEDIA_ID not in ids or not token:
        return None, "no se encontró el ID de TVN y un token en el reproductor público"
    return (f"https://mdstrm.com/live-stream-playlist/{MEDIA_ID}.m3u8"
            f"?access_token={quote(token.group(1), safe='')}", "candidato del reproductor público")


def main():
    print("La renovación de TVN está integrada en scripts/guardian.py; no se modifica canales.m3u por separado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
