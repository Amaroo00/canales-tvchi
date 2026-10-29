#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardián 24/7 - Monitoreo, Redundancia y Failover Automático para IPTV-chile
Revisa el estado de cada canal en canales.m3u y conmuta a señales de respaldo si la principal cae.
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

# Contexto SSL que no falla con certificados autofirmados o de CDNs locales
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def test_stream(url, timeout=TIMEOUT):
    """Prueba si una URL de streaming responde correctamente."""
    if not url or not url.startswith("http"):
        return False, "URL inválida", 0
    try:
        t0 = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    urls = ch["urls"]

    primary_url = urls[0]
    backups = urls[1:]

    # Extraer también de parámetro backup-url="url" en el header si existe
    m_back = re.search(r'(?:backup-url|alt-url)="([^"]*)"', ch["header"])
    if m_back and m_back.group(1) not in backups and m_back.group(1) != primary_url:
        backups.append(m_back.group(1))

    # Probar URL primaria
    ok, msg, ms = test_stream(primary_url)
    used_backup = False
    active_url = primary_url

    if not ok and backups:
        # Intentar con respaldos disponibles
        for idx, b_url in enumerate(backups):
            b_ok, b_msg, b_ms = test_stream(b_url)
            if b_ok:
                used_backup = True
                active_url = b_url
                ok = True
                msg = f"Respaldo #{idx+1} Activo"
                ms = b_ms
                # Intercambiar para que la URL activa sea la primaria en canales.m3u
                new_urls = [b_url] + [u for u in urls if u != b_url]
                ch["urls"] = new_urls
                break

    return {
        "channel": ch,
        "name": name,
        "group": group,
        "active_url": active_url,
        "online": ok,
        "status_msg": msg,
        "latency_ms": ms,
        "used_backup": used_backup
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

    # Contadores
    total = len(results)
    online_count = sum(1 for r in results if r["online"])
    failover_count = sum(1 for r in results if r["used_backup"])
    offline_count = total - online_count

    print(f"\n--- Resumen del Guardián ---")
    print(f"Total canales: {total}")
    print(f"En línea: {online_count} ({(online_count/total*100):.1f}%)")
    print(f"Respaldo activado (Failover): {failover_count}")
    print(f"Caídos temporalmente: {offline_count}")

    # 1. Reescribir canales.m3u con el orden optimizado (y backups ordenados)
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n\n")
        for r in results:
            ch = r["channel"]
            f.write(f"{ch['header']}\n")
            for u in ch["urls"]:
                f.write(f"{u}\n")
            f.write("\n")

    # 2. Generar reporte STATUS.md para ver en GitHub
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write("# 📡 Estado de Canales - Guardián 24/7 IPTV-chile\n\n")
        f.write(f"> **Última verificación:** `{now_str}`  \n")
        f.write(f"> **Salud de la red:** **{online_count}/{total} canales operativos** ({(online_count/total*100):.1f}% en línea)\n\n")
        f.write("| Canal | Categoría | Estado | Latencia | Detalle |\n")
        f.write("| :--- | :--- | :---: | :---: | :--- |\n")
        for r in results:
            icon = "🟢" if r["online"] else "🔴"
            lat = f"{r['latency_ms']} ms" if r["online"] and r["latency_ms"] > 0 else "-"
            f.write(f"| **{r['name']}** | {r['group']} | {icon} | {lat} | {r['status_msg']} |\n")

        f.write("\n---\n*Generado automáticamente por el Guardián de GitHub Actions de IPTV-chile.* \n")

    print(f"Archivos {M3U_FILE} y {STATUS_FILE} actualizados exitosamente.")

if __name__ == "__main__":
    main()
