# 📡 Estado de canales — Guardián IPTV Chile

> Última comprobación: **2026-11-14 10:37:48** (UTC).
> **25/42 señales verificadas con vídeo y audio**; 9 sin verificar, 7 con fallo, 0 restringidas y 1 sin fuente.

Un 401/403 no se considera operativo ni demuestra geobloqueo. Las pruebas reflejan la IP del runner de GitHub, no una TV en Chile.

- `canales.m3u`: catálogo con fuente aprobada; conserva señales no verificadas y la última URL si fallan.
- `canales_verificados.m3u`: únicamente las señales verificadas en esta ejecución.
- Los respaldos contados abajo también se probaron; no son una garantía permanente.
- Audio: muestra de 6 s. Detecta ausencia, silencio y posible saturación; no certifica calidad subjetiva ni corrige el sonido del emisor.

| Canal | Grupo | Estado | Audio / vídeo de la muestra | Respaldos verificados | Detalle |
| :--- | :--- | :--- | :--- | ---: | :--- |
| Canal 13 HD | Nacionales | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| Mega HD | Nacionales | 🟢 Operativo | aac 2ch, -26.7 dBFS / h264 1920×1080 | 1 | HLS, segmentos, vídeo y audio comprobados |
| Chilevisión (CHV) | Nacionales | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| TV+ (TV Más) | Nacionales | 🟢 Operativo | aac 2ch, -21.2 dBFS / h264 1920×1080 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TVN HD | Nacionales | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| La Red | Nacionales | 🟢 Operativo | aac 2ch, -24.5 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TVR | Nacionales | 🟢 Operativo | aac 2ch, -22.6 dBFS / h264 1920×1080 | 1 | HLS, segmentos, vídeo y audio comprobados; puede no emitir las 24 h |
| Wapp TV | Nacionales | 🟢 Operativo | aac 2ch, -25.6 dBFS / h264 1920×1080 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TVN 24 Horas | Noticias | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| T13 En Vivo | Noticias | 🟢 Operativo | aac 2ch, -18.6 dBFS / h264 1280×720 | 1 | HLS, segmentos, vídeo y audio comprobados |
| CHV Noticias | Noticias | 🟡 Con aviso | aac 2ch, -180.0 dBFS / h264 1280×720 | 0 | Muestra casi silenciosa; puede ser una pausa de programación |
| BioBio TV | Noticias | 🟢 Operativo | aac 2ch, -16.2 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| Meganoticias Ahora | Noticias | ⚪ Sin verificar | No comprobado | 0 | HTTP 401: acceso restringido; no prueba geobloqueo |
| ADN TV | Radio con imagen | 🟡 Con aviso | aac 2ch, -180.0 dBFS / h264 1920×1080 | 0 | Muestra casi silenciosa; puede ser una pausa de programación |
| Cooperativa TV | Radio con imagen | 🔴 Fallo observado | No comprobado | 0 | HTTP 404 |
| Agricultura TV | Radio con imagen | 🟢 Operativo | aac 2ch, -12.5 dBFS / h264 1920×1080 | 0 | HLS, segmentos, vídeo y audio comprobados |
| Pauta | Radio con imagen | 🟢 Operativo | aac 2ch, -24.8 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| CHV Deportes | Deportes | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo; puede no emitir las 24 h |
| NTV (TVN Infantil/Cultural) | Infantil | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| TVN3 Recuerdos | Retro | 🟢 Operativo | aac 2ch, -29.6 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TV Senado | Cultura | 🟢 Operativo | aac 2ch, -25.2 dBFS / h264 640×360 | 0 | HLS, segmentos, vídeo y audio comprobados; puede no emitir las 24 h |
| UChile TV | Cultura | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |
| TVU | Cultura | 🟢 Operativo | aac 2ch, -36.2 dBFS / h264 1920×1080 | 1 | HLS, segmentos, vídeo y audio comprobados |
| UCV TV | Cultura | 🟢 Operativo | aac 2ch, -22.7 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TV Usach | Cultura | 🟢 Operativo | aac 2ch, -13.9 dBFS / h264 640×360 | 1 | HLS, segmentos, vídeo y audio comprobados |
| 13C Cultura | Cultura | 🔴 Fallo observado | No comprobado | 0 | Tiempo agotado al decodificar audio |
| 13 Realities | Entretenimiento | 🔴 Fallo observado | No comprobado | 0 | Tiempo agotado al decodificar audio |
| Mega 2 | Entretenimiento | ⏳ Sin fuente | No comprobado | 0 | Pendiente: no se encontró una URL pública autorizada; no se usan retransmisores por IP. |
| 13 Festival | Música | 🟢 Operativo | aac 2ch, -19.2 dBFS / h264 1280×720 | 1 | HLS, segmentos, vídeo y audio comprobados |
| 13 Humor | Entretenimiento | 🟢 Operativo | aac 2ch, -27.4 dBFS / h264 854×480 | 0 | HLS, segmentos, vídeo y audio comprobados |
| 13 Kids | Infantil | 🔴 Fallo observado | No comprobado | 0 | Faltan paquetes de vídeo o una pista de audio |
| 13 Entretención | Entretenimiento | 🔴 Fallo observado | No comprobado | 0 | HTTP 404 |
| 13 Teleseries | Entretenimiento | 🟢 Operativo | aac 2ch, -31.8 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados |
| 13 Prime | Entretenimiento | 🔴 Fallo observado | No comprobado | 0 | HTTP 404 |
| Canal 9 Bío Bío | Regionales | 🟢 Operativo | aac 2ch, -55.8 dBFS / h264 1280×720 | 0 | HLS, segmentos, vídeo y audio comprobados; puede no emitir las 24 h |
| Antofagasta TV | Regionales | 🟢 Operativo | aac 2ch, -18.9 dBFS / h264 1920×1080 | 1 | HLS, segmentos, vídeo y audio comprobados |
| Iquique TV | Regionales | 🟢 Operativo | aac 2ch, -26.3 dBFS / h264 1920×1080 | 0 | HLS, segmentos, vídeo y audio comprobados |
| ITV Patagonia | Regionales | 🟢 Operativo | aac 2ch, -28.1 dBFS / h264 1280×720 | 2 | HLS, segmentos, vídeo y audio comprobados; puede no emitir las 24 h |
| El Pingüino TV | Regionales | 🔴 Fallo observado | No comprobado | 0 | Faltan paquetes de vídeo o una pista de audio |
| UMAG TV | Regionales | 🟢 Operativo | aac 2ch, -59.6 dBFS / h264 640×360 | 0 | HLS, segmentos, vídeo y audio comprobados |
| DW Español | Internacional | 🟢 Operativo | aac 2ch, -25.4 dBFS / h264 960×540 | 0 | HLS, segmentos, vídeo y audio comprobados |
| TV Chile | Internacional | ⚪ Sin verificar | No comprobado | 0 | HTTP 403: acceso restringido; no prueba geobloqueo |

## Avisos de actualización

- m3u.cl Chile: HTTP 403: acceso restringido; no prueba geobloqueo

## Canales no publicados

- **TNT Sport Chile**: Señal de pago: requiere una fuente autorizada; no se publican retransmisiones por IP.
- **ESPN CHILE**: Señal de pago y alias incorrecto de ESPN 3; requiere una fuente autorizada.
- **ESPN 3**: Señal de pago: requiere una fuente autorizada.

Diagnóstico por fuente: [data/health.json](data/health.json).
Se conserva el catálogo aunque una señal falle; no se sustituye por otro canal.
