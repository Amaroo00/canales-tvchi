#!/usr/bin/env python3
"""Utilidades compartidas. Solo biblioteca estándar; FFmpeg se instala en Actions."""

import array
import gzip
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from update_playlist import DEFAULT_UA, normalize_name, safe_error

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config/channels.json"
BACKUPS = ROOT / "config/backups.json"
HEALTH = ROOT / "data/health.json"
MAX_BODY = 4 * 1024 * 1024
SECRET_KEYS = {"access_token", "token", "auth", "authorization", "password", "cookie", "signature"}


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_catalog(path=CATALOG):
    catalog = load_json(path)
    if not catalog or not catalog.get("channels"):
        raise ValueError("El catálogo no contiene canales")
    seen = set()
    logos = load_json(ROOT / "config/logos.json", {})
    for channel in catalog["channels"]:
        if channel["id"] in seen:
            raise ValueError("ID de canal duplicado: " + channel["id"])
        seen.add(channel["id"])
        if channel["id"] in logos:
            channel["logo"] = logos[channel["id"]]
        for field in ("name", "group", "id"):
            if any(c in channel[field] for c in '\r\n"'):
                raise ValueError("Metadatos M3U inválidos")
        if not channel.get("page", "").startswith("https://"):
            raise ValueError("Falta la página pública del canal")
        if any(not allowed_url(channel, url) for url in channel.get("urls", [])):
            raise ValueError("URL fuera de los hosts/rutas aprobados: " + channel["name"])
    return catalog


def host_matches(host, suffix):
    return host == suffix or host.endswith("." + suffix)


def public_url(url):
    """Rechaza credenciales, hosts locales, IPs y protocolos no HTTPS."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return False
        if any(c in url for c in '\r\n\\') or host == "localhost" or "." not in host:
            return False
        if re.fullmatch(r"[0-9.]+", host):
            return False
        if host.endswith((".local", ".internal", ".localhost")):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return True
    except ValueError:
        return False


def allowed_url(channel, url):
    if not public_url(url):
        return False
    parts = urllib.parse.urlsplit(url)
    return (
        any(host_matches(parts.hostname.lower(), host) for host in channel.get("hosts", []))
        and any(key in parts.path for key in channel.get("stream_keys", []))
    )


def stable_url(url):
    """No guardar tokens de sesión de fuentes externas en el banco de respaldos."""
    if not public_url(url):
        return None
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if any(key.lower() in SECRET_KEYS for key, _ in query):
        return None
    # Estos marcadores de las listas no son respaldos diferentes.
    query = [(key, value) for key, value in query if key.lower() != "playlistm3ucl"]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                   urllib.parse.urlencode(query), ""))


def channel_headers(channel):
    page = channel["page"]
    parts = urllib.parse.urlsplit(page)
    return {"User-Agent": DEFAULT_UA, "Referer": page,
            "Origin": f"{parts.scheme}://{parts.netloc}"}


class StreamError(Exception):
    def __init__(self, state, detail):
        super().__init__(detail)
        self.state = state
        self.detail = detail


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_url(newurl):
            raise StreamError("restricted", "Redirección fuera de HTTPS público")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, headers=None, timeout=10, limit=MAX_BODY, retries=2):
    if not public_url(url):
        raise StreamError("restricted", "URL no pública o no HTTPS")
    opener = urllib.request.build_opener(
        SafeRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers or {"User-Agent": DEFAULT_UA})
            with opener.open(request, timeout=timeout) as response:
                body = response.read(limit)
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    # gzip.GzipFile.read acota también el tamaño descomprimido.
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                        body = compressed.read(limit)
                return body, response.geturl(), response.headers
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 451):
                raise StreamError("unverified", f"HTTP {exc.code}: acceso restringido; no prueba geobloqueo") from exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 == retries:
                raise StreamError("offline", f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt + 1 == retries:
                raise StreamError("offline", safe_error(exc)) from exc
        time.sleep(0.5 * (attempt + 1))


def attributes(line):
    return dict((match.group(1), match.group(2) if match.group(2) is not None else match.group(3))
                for match in re.finditer(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line.split(":", 1)[-1]))


def read_manifest(url, headers, timeout):
    raw, final_url, _ = fetch(url, headers, timeout)
    text = raw.decode("utf-8-sig", errors="replace").lstrip()
    if not text.startswith("#EXTM3U"):
        raise StreamError("offline", "HTTP responde pero no entrega un manifiesto HLS")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:"))
           and attributes(line).get("METHOD", "NONE") != "NONE" for line in lines):
        raise StreamError("restricted", "HLS cifrado: requiere reproductor/autorización del proveedor")
    return lines, final_url


def variant_rank(variant):
    info, _ = variant
    codecs = info.get("CODECS", "").lower()
    incompatible = any(codec in codecs for codec in ("hvc1", "hev1", "av01", "ac-3", "ec-3"))
    bandwidth = positive_int(info.get("AVERAGE-BANDWIDTH", info.get("BANDWIDTH", "0")))
    # Prefiere H.264/AAC y bitrate moderado, sin modificar ni retransmitir contenido.
    return incompatible, bandwidth > 5000000, abs(bandwidth - 2500000)


def positive_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def inspect_hls(url, headers, timeout=10, depth=0):
    if depth > 3:
        raise StreamError("offline", "Demasiados niveles de manifiestos HLS")
    lines, final_url = read_manifest(url, headers, timeout)
    variants = []
    renditions = []
    pending = None
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = attributes(line)
        elif line.startswith("#EXT-X-MEDIA:"):
            renditions.append(attributes(line))
        elif not line.startswith("#") and pending is not None:
            variants.append((pending, urllib.parse.urljoin(final_url, line)))
            pending = None
    if variants:
        last_error = None
        for info, variant_url in sorted(variants, key=variant_rank)[:3]:
            try:
                result = inspect_hls(variant_url, headers, timeout, depth + 1)
                audio = [item for item in renditions if item.get("TYPE") == "AUDIO"
                         and item.get("GROUP-ID") == info.get("AUDIO") and item.get("URI")]
                audio.sort(key=lambda item: (item.get("LANGUAGE", "").lower() not in ("es", "spa", "es-cl"),
                                            item.get("DEFAULT") != "YES"))
                if audio:
                    audio_url = urllib.parse.urljoin(final_url, audio[0]["URI"])
                    audio_result = inspect_hls(audio_url, headers, timeout, depth + 1)
                    result["audio_url"] = audio_result["video_url"]
                    result["audio_language"] = audio[0].get("LANGUAGE", "")
                result["variant"] = info
                return result
            except StreamError as exc:
                last_error = exc
        raise last_error or StreamError("offline", "Sin variantes reproducibles")
    segments = [urllib.parse.urljoin(final_url, line) for line in lines if not line.startswith("#")]
    if not any(line.startswith("#EXT-X-TARGETDURATION:") for line in lines) or not segments:
        raise StreamError("offline", "El manifiesto HLS no tiene segmentos")
    # Muestreo acotado de dos segmentos recientes; no descarga la transmisión entera.
    for segment in segments[-3:-1] or segments[-1:]:
        raw, _, response_headers = fetch(segment, headers, timeout, limit=65536)
        content_type = response_headers.get("Content-Type", "").lower()
        if len(raw) < 188 or "text/html" in content_type or raw.lstrip().startswith((b"<", b"{", b"#EXTM3U")):
            raise StreamError("offline", "Segmento vacío o respuesta que no es multimedia")
    return {"video_url": final_url, "audio_url": None, "variant": {}}


def ffmpeg_input(url, headers, timeout):
    if not public_url(url):
        raise StreamError("restricted", "Entrada multimedia no pública")
    # Impide leer archivos locales o ejecutar protocolos ajenos a HLS/HTTPS.
    return ["-protocol_whitelist", "https,tls,tcp,crypto", "-tls_verify", "1",
            "-rw_timeout", str(int(timeout * 1000000)),
            "-headers", "".join(f"{key}: {value}\r\n" for key, value in headers.items()),
            "-i", url]


def probe_media(url, headers, timeout=10):
    command = ["ffprobe", "-v", "error"] + ffmpeg_input(url, headers, timeout) + [
        "-read_intervals", "%+6", "-count_packets", "-show_entries",
        "stream=codec_type,codec_name,channels,sample_rate,width,height,nb_read_packets",
        "-of", "json"]
    try:
        process = subprocess.run(command, capture_output=True, timeout=timeout + 20, check=False)
        if process.returncode:
            raise StreamError("offline", "FFprobe no pudo leer paquetes multimedia")
        return json.loads(process.stdout).get("streams", [])
    except subprocess.TimeoutExpired as exc:
        raise StreamError("offline", "Tiempo agotado al leer paquetes multimedia") from exc
    except (ValueError, OSError) as exc:
        raise StreamError("unverified", "FFprobe no disponible o respuesta inválida") from exc


def audio_metrics(pcm):
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < 16000:
        raise StreamError("offline", "Menos de un segundo de audio decodificable")
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    db = round(20 * math.log10(max(rms, 1e-9)), 1)
    clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
    warnings = []
    if db < -60:
        warnings.append("Muestra casi silenciosa; puede ser una pausa de programación")
    if clipping > 0.01:
        warnings.append("Posible saturación en la muestra de audio")
    return {"rms_dbfs": db, "clipping_percent": round(clipping * 100, 2), "warnings": warnings}


def decode_audio(url, headers, timeout=10):
    command = ["ffmpeg", "-nostdin", "-v", "error"] + ffmpeg_input(url, headers, timeout) + [
        "-t", "6", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=timeout + 20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise StreamError("offline", "Tiempo agotado al decodificar audio") from exc
    except OSError as exc:
        raise StreamError("unverified", "FFmpeg no disponible") from exc
    if process.returncode:
        raise StreamError("offline", "No se pudo decodificar la pista de audio")
    return audio_metrics(process.stdout)


def verify_stream(channel, url, timeout=10, manifest_only=False):
    started = time.monotonic()
    try:
        if not allowed_url(channel, url):
            raise StreamError("restricted", "La URL no coincide con el canal y sus hosts aprobados")
        headers = channel_headers(channel)
        hls = inspect_hls(url, headers, timeout)
        if manifest_only or not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
            raise StreamError("unverified", "HLS y segmentos accesibles; falta verificar vídeo/audio con FFmpeg")
        streams = probe_media(hls["video_url"], headers, timeout)
        video = next((item for item in streams if item.get("codec_type") == "video"
                      and positive_int(item.get("nb_read_packets")) > 0), None)
        audio_streams = (probe_media(hls["audio_url"], headers, timeout) if hls["audio_url"] else streams)
        audio = next((item for item in audio_streams if item.get("codec_type") == "audio"
                      and positive_int(item.get("nb_read_packets")) > 0), None)
        if not video or not audio:
            raise StreamError("offline", "Faltan paquetes de vídeo o una pista de audio")
        metrics = decode_audio(hls["audio_url"] or hls["video_url"], headers, timeout)
        warnings = list(metrics.pop("warnings"))
        if audio.get("codec_name") not in ("aac", "mp3", "mp2"):
            warnings.append("Códec de audio menos compatible: " + audio.get("codec_name", "desconocido"))
        if video.get("codec_name") not in ("h264", "mpeg2video"):
            warnings.append("Códec de vídeo menos compatible: " + video.get("codec_name", "desconocido"))
        return {"state": "warning" if warnings else "online", "detail": "; ".join(warnings) or "HLS, segmentos, vídeo y audio comprobados",
                "latency_ms": int((time.monotonic() - started) * 1000),
                "video": video, "audio": dict(audio, **metrics),
                "preferred_url": url}
    except StreamError as exc:
        return {"state": exc.state, "detail": exc.detail,
                "latency_ms": int((time.monotonic() - started) * 1000)}


def name_key(name):
    name = re.sub(r"\[[^]]*\]|\([^)]*\)", " ", name)
    name = re.sub(r"\|\s*(?:CL|Chile)\s*$", " ", name, flags=re.I)
    name = re.sub(r"[✪★●•]", " ", name)
    name = re.sub(r"\b(?:HD|SD|FHD|UHD)\b", " ", name, flags=re.I)
    return normalize_name(name.replace("+", " plus "))


def m3u_entry(channel, url, group=None):
    # Una entrada, una URL. Los respaldos viven exclusivamente en backups.json.
    logo = channel.get("logo", "")
    logo_attr = f' tvg-logo="{logo}"' if logo and public_url(logo) and '"' not in logo else ""
    return (f'#EXTINF:-1 tvg-id="{channel["id"]}" tvg-name="{channel["name"]}"'
            f'{logo_attr} group-title="{group or channel["group"]}",{channel["name"]}\n'
            f'#EXTVLCOPT:http-referrer={channel["page"]}\n'
            f'#EXTVLCOPT:http-user-agent={DEFAULT_UA}\n{url}\n\n')
