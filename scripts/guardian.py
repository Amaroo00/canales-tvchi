#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardián 24/7 - Monitoreo, Redundancia y Failover Automático para IPTV-chile
Revisa el estado de cada canal en canales.m3u, conmuta a respaldos si la señal principal cae
y utiliza un Banco de Señales de Emergencia en caso de contingencia mayor.
"""

import os
import sys
import time
import ssl
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

M3U_FILE = "canales.m3u"
STATUS_FILE = "STATUS.md"
TIMEOUT = 7
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Contexto SSL seguro y tolerante
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Banco de Señales de Emergencia (Se activan solo si tanto la principal como los respaldos fallan)
EMERGENCY_POOL = {
    "canal 13": [
        "https://redirector.dps.live/hls/13cl/playlist.m3u8",
        "https://redirector.dps.live/hls/13cl/13cl.smil/playlist.m3u8",
        "https://origin.dpsgo.com/ssai/event/BBp0VeP6QtOOlH8nu3bWTg/master.m3u8"
    ],
    "mega hd": [
        "https://unlimited2-cl-isp.dps.live/mega/mega.smil/playlist.m3u8?PlaylistM3UCL",
        "https://unlimited1-cl-isp.dps.live/mega/mega.smil/playlist.m3u8",
        "https://redirector.dps.live/hls/mega/playlist.m3u8"
    ],
    "mega 2": [
        "http://15.204.196.147:22880/MEGA2-MEGAMEDIA-EE.UU-PROVEEDOR/index.m3u8"
    ],
    "chilevisión": [
        "https://redirector.rudo.video/hls-video/10b92cafdf3646cbc1e727f3dc76863621a327fd/chv/chv.smil/playlist.m3u8?PlaylistM3UCL",
        "https://redirector.rudo.video/hls-video/339f69c6122f6d8f4574732c235f09b7683e31a5/chvn/chvn.smil/playlist.m3u8?PlaylistM3UCL"
    ],
    "tvn hd": [
        "https://iptv.bitred.cl/tvn/index.m3u8",
        "http://138.121.15.230:9002/TVN/index.m3u8"
    ],
    "tvn 24 horas": [
        "https://mdstrm.com/live-stream-playlist/689ba606ecfe7915e1f8f741.m3u8?PlaylistM3UCL",
        "https://iptv.bitred.cl/tvn/index.m3u8"
    ],
    "meganoticias ahora": [
        "http://15.204.196.147:22880/MEGANOTICIA-MEGAMEDIA-EE.UU-PROVEEDOR/video.m3u8",
        "https://redirector.rudo.video/hls-video/ey6283je82983je9823je8jowowiekldk9838274/921tv/921tv.smil/playlist.m3u8"
    ]
}

def get_headers_for_url(url):
    headers = {"User-Agent": USER_AGENT}
    if "rudo.video" in url:
        headers["Referer"] = "https://rudo.video/"
        headers["Origin"] = "https://rudo.video"
    elif "mdstrm.com" in url:
        headers["Referer"] = "https://www.24horas.cl/"
        headers["Origin"] = "https://www.24horas.cl"
    elif "13cl" in url or "dpsgo.com" in url:
        headers["Referer"] = "https://www.13.cl/"
    elif "uchiletv" in url:
        headers["Referer"] = "https://uchiletv.cl/"
    return headers

def test_stream(url, timeout=TIMEOUT):
    if not url or not url.startswith("http"):
        return False, "URL inválida", 0
    try:
        t0 = time.time()
        headers = get_headers_for_url(url)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            code = resp.getcode()
            elapsed = int((time.time() - t0) * 1000)
            if code in [200, 206, 301, 302, 307, 308]:
                return True, f"OK ({code})", elapsed
            return False, f"HTTP {code}", elapsed
    except Exception as e:
        err_msg = str(e)
        if "HTTP Error" in err_msg:
            err_msg = err_msg.replace("HTTP Error ", "Error ")
        # Tolerancia a Geobloqueo en GitHub Actions (403 Forbidden para CDNs que operan en Chile):
        if "403" in err_msg and any(d in url for d in ["gtd.cl", "rudo.video", "dps.live", "dpsgo.com"]):
            return True, "OK (Geo-CL 403)", int((time.time() - t0) * 1000)
        return False, err_msg[:30], 0

def parse_m3u(file_path):
    channels = []
    if not os.path.exists(file_path):
        return channels

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line.strip() for line in f if line.strip()]

    current_header = None
    current_urls = []

    for line in lines:
        if line.startswith("#EXTINF:"):
            if current_header and current_urls:
                channels.append({"header": current_header, "urls": current_urls})
            current_header = line
            current_urls = []
        elif not line.startswith("#") and (line.startswith("http://") or line.startswith("https://")):
            current_urls.append(line)

    if current_header and current_urls:
        channels.append({"header": current_header, "urls": current_urls})

    return channels

def extract_channel_name(header):
    comma_idx = header.rfind(",")
    if comma_idx != -1:
        return header[comma_idx + 1:].strip()
    return "Canal"

def extract_group(header):
    m = re.search(r'group-title="([^"]*)"', header)
    return m.group(1) if m else "General"

def check_channel(ch):
    name = extract_channel_name(ch["header"])
    group = extract_group(ch["header"])
    urls = list(ch["urls"])

    primary_url = urls[0]
    backups = urls[1:]

    # Probar URL primaria
    ok, msg, ms = test_stream(primary_url)
    active_url = primary_url
    used_backup = False

    # Si la primaria falla, intentar respaldos existentes en el M3U
    if not ok and backups:
        for idx, b_url in enumerate(backups):
            b_ok, b_msg, b_ms = test_stream(b_url)
            if b_ok:
                used_backup = True
                active_url = b_url
                ok = True
                msg = f"Respaldo #{idx+1} Activo"
                ms = b_ms
                # Poner el respaldo activo de primero
                new_urls = [b_url] + [u for u in urls if u != b_url]
                ch["urls"] = new_urls
                break

    # Si aún no funciona, acudir al Banco de Emergencia
    if not ok:
        name_lower = name.lower()
        for key, pool_urls in EMERGENCY_POOL.items():
            if key in name_lower:
                for pool_url in pool_urls:
                    if pool_url not in urls:
                        e_ok, e_msg, e_ms = test_stream(pool_url)
                        if e_ok:
                            used_backup = True
                            active_url = pool_url
                            ok = True
                            msg = "Respaldo de Emergencia Activado"
                            ms = e_ms
                            ch["urls"] = [pool_url] + urls
                            break
            if ok:
                break

    return {
        "channel": ch,
        "name": name,
        "group": group,
        "active_url": active_url,
        "online": ok,
        "status_msg": msg,
        "latency_ms": ms,
        "used_backup": used_backup,
        "total_backups": len(ch["urls"]) - 1
    }

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando Guardián 24/7 de IPTV-chile...")

    if not os.path.exists(M3U_FILE):
        print(f"Error: No se encontró el archivo {M3U_FILE}")
        sys.exit(1)

    channels = parse_m3u(M3U_FILE)
    print(f"Se encontraron {len(channels)} canales en {M3U_FILE}. Verificando estado en paralelo...")

    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(check_channel, ch) for ch in channels]
        for f in futures:
            results.append(f.result())

    total = len(results)
    online_count = sum(1 for r in results if r["online"])
    failover_count = sum(1 for r in results if r["used_backup"])
    offline_count = total - online_count

    print(f"\n--- Resumen del Guardián ---")
    print(f"Total canales: {total}")
    print(f"En línea: {online_count} ({(online_count/total*100):.1f}%)")
    print(f"Respaldos activados (Failover): {failover_count}")
    print(f"Caídos: {offline_count}")

    # 1. Reescribir canales.m3u manteniendo la URL funcional como #1 y preservando respaldos
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")
        for r in results:
            ch = r["channel"]
            f.write(f"{ch['header']}\n")
            for u in ch["urls"]:
                f.write(f"{u}\n")
            f.write("\n")

    # 2. Generar reporte STATUS.md para GitHub
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write("# 📡 Estado de Canales - Guardián 24/7 IPTV-chile\n\n")
        f.write(f"> **Última verificación:** `{now_str}`  \n")
        f.write(f"> **Salud de la red:** **{online_count}/{total} canales operativos** ({(online_count/total*100):.1f}% en línea)  \n")
        f.write(f"> **Redundancia:** Canales blindados con enlaces de respaldo listos para conmutar.\n\n")
        f.write("| Canal | Categoría | Estado | Latencia | Respaldos Listos | Detalle |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :--- |\n")
        for r in results:
            icon = "🟢" if r["online"] else "🔴"
            lat = f"{r['latency_ms']} ms" if r["online"] and r["latency_ms"] > 0 else "-"
            backups_badge = f"🛡️ {r['total_backups']} disp." if r['total_backups'] > 0 else "1 sola señal"
            f.write(f"| **{r['name']}** | {r['group']} | {icon} | {lat} | {backups_badge} | {r['status_msg']} |\n")

        f.write("\n---\n*Generado automáticamente por el Guardián de GitHub Actions de IPTV-chile.* \n")

    print(f"Archivos {M3U_FILE} y {STATUS_FILE} actualizados exitosamente.")

if __name__ == "__main__":
    main()
