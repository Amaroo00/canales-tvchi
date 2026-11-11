# 📡 IPTV Chile — Guardián autónomo

Lista de señales chilenas con **42 canales en el catálogo**, incluidos 16 nuevos
canales nacionales, temáticos, universitarios y regionales.
El bot corre **cada hora en GitHub Actions**: no depende de un PC, ADB, una TV,
un servidor propio ni tareas locales. No necesita secretos para las fuentes públicas.

## Lista para tu reproductor

Lista principal (conserva las señales aprobadas aunque el runner no pueda comprobarlas):

```text
https://raw.githubusercontent.com/Amaroo00/canales-tvchi/main/canales.m3u
```

Solo señales con vídeo y audio comprobados en la última ejecución:

```text
https://raw.githubusercontent.com/Amaroo00/canales-tvchi/main/canales_verificados.m3u
```

Usa la URL, no una copia descargada, y activa la recarga periódica de la lista en
tu reproductor. Cambiarla en GitHub no actualiza automáticamente las copias o
cachés del televisor. Cada entrada contiene **una única URL**; los respaldos no
se mezclan dentro del M3U.

Estado real: [STATUS.md](STATUS.md). Diagnóstico por fuente:
[data/health.json](data/health.json). Ejecuciones:
[GitHub Actions](https://github.com/Amaroo00/canales-tvchi/actions).

## Nuevos canales

- **Nacionales:** TVR y Wapp TV.
- **Entretenimiento:** 13 Entretención, 13 Teleseries y 13 Prime.
- **Cultura:** TV Usach.
- **Radio con imagen:** ADN TV, Cooperativa TV, Agricultura TV y Pauta.
- **Regionales:** Canal 9 Bío Bío, Antofagasta TV, Iquique TV, ITV Patagonia,
  El Pingüino TV y UMAG TV.

Estar en el catálogo no significa estar siempre al aire. Mega 2 permanece
catalogado, pero no se publica hasta encontrar una fuente pública aprobada.
TNT Sports y ESPN no se sustituyen por otras señales: requieren una fuente
autorizada y no se publican retransmisores desconocidos de canales de pago.

## Qué comprueba y actualiza el bot

1. Descubre URLs en iptv-org y m3u.cl **solo para los canales aprobados**.
   Para La Red y Cooperativa también consulta su página pública, sin ejecutar scripts.
2. Exige que coincidan nombre/ID, dominio y ruta del stream. No importa toda una
   lista externa ni acepta una radio distinta como respaldo de un noticiario.
3. Intenta renovar TVN desde su reproductor público, sin login ni evasión de bloqueos.
4. Valida HTTPS con certificados, el contenido HLS, sus variantes y dos segmentos
   recientes. No basta un HTTP 200 ni un archivo que solo empieza con `#EXTM3U`.
5. Con FFprobe comprueba paquetes de vídeo/audio; con FFmpeg decodifica 6 s de
   audio y mide nivel y posible saturación. Prefiere probar H.264/AAC y bitrate
   moderado. Un respaldo verificado sin avisos tiene prioridad sobre uno con avisos.
6. Prueba también los respaldos y selecciona la mejor fuente comprobada. Si todas
   fallan, conserva la URL anterior aprobada y **reporta el fallo**, sin fingir éxito.
7. Publica las dos listas, respaldos, estado y diagnóstico en un mismo commit.
   Las escrituras locales son atómicas y nunca se hace push forzado.

### Cómo interpretar el estado

| Estado | Significado |
| :--- | :--- |
| 🟢 Operativo | HLS, segmentos, paquetes de vídeo y audio decodificado comprobados. |
| 🟡 Con aviso | Reproduce en la prueba, pero hay silencio, posible saturación o un códec menos compatible. |
| ⚪ Sin verificar | Acceso restringido (401/403/451) o comprobación multimedia incompleta. **No cuenta como operativo.** |
| 🔴 Fallo observado | Error de red, HLS/segmentos inválidos o falta de vídeo/audio en la prueba. |
| 🔒 Restringido | Cifrado o fuente no permitida; se respeta la restricción. |
| ⏳ Sin fuente | Sigue en el catálogo, pero no hay una URL pública aprobada que publicar. |

**Límites importantes:** GitHub suele probar desde fuera de Chile. Un 403 no
prueba geobloqueo, y que algo falle allí no implica que falle en tu TV chilena.
La lista verificada puede por eso ser más corta. Algunos canales no emiten 24/7.
Los respaldos son URLs comprobadas, no necesariamente CDNs independientes.
La identidad se filtra por el catálogo: no se hace reconocimiento visual del contenido.

Una muestra de audio no certifica su calidad subjetiva. El bot **no puede mejorar
el sonido del emisor ni reparar una transmisión**: puede detectar problemas,
avisar y cambiar a un respaldo mejor. Tampoco retransmite ni transcodifica canales.
Para pistas de audio externas se prueba la española cuando está declarada; la
selección final de idioma y códec depende también del reproductor.

## Archivos y mantenimiento

| Archivo | Función |
| :--- | :--- |
| `config/channels.json` | Catálogo, aliases, páginas, hosts y rutas aprobados; fuente de verdad. |
| `config/logos.json` | Logotipos preservados de la lista anterior. |
| `config/public_sources.json` | Listas de descubrimiento, límites y timeout. |
| `config/backups.json` | Banco de candidatos sin tokens de sesión; no implica que todos funcionen. |
| `scripts/guardian.py` | Pipeline completo: descubrimiento, renovación, verificación y publicación. |
| `scripts/iptv.py` | HLS, HTTPS, FFprobe/FFmpeg, audio y escritura atómica. |
| `scripts/sync_public_sources.py` | Descubrimiento restringido al catálogo. |
| `scripts/refresh_tokens.py` | Resolución del reproductor público de TVN, integrada en el guardián. |
| `.github/workflows/guardian.yml` | Ejecución horaria, pruebas y publicación en `main`. |
| `.github/workflows/tests.yml` | Pruebas en Python 3.11, 3.12 y 3.13; también en pull requests. |
| `tests/test_iptv.py` | Pruebas deterministas sin depender de emisiones reales. |

Para agregar un canal, edita `config/channels.json`, no el M3U generado.
Usa un ID único, nombre, grupo, página pública, aliases, hosts aprobados,
`stream_keys` específicos y URLs HTTPS públicas/autorizadas. El próximo push
activa el bot. Si una emisora cambia de dominio o identificador, revisa su fuente
oficial y actualiza esa aprobación; no se amplía automáticamente por seguridad.

## Activación y ejecución manual en GitHub

1. **Actions → Guardián 24/7 - IPTV Chile → Run workflow**.
2. Verifica que termina correctamente y aparece el commit del bot.
3. Revisa `STATUS.md`, el resumen de Actions y el artefacto de diagnóstico.

Si Actions está deshabilitado, hay que habilitarlo. Si una regla de protección
impide escribir en `main`, hay que autorizar al bot o cambiar el flujo de publicación.
El workflow declara `contents: write` únicamente para el job de publicación.
GitHub puede retrasar o desactivar programaciones por sus políticas, incluida la
inactividad; no es una garantía de servicio continuo. Si `main` cambia mientras
se están comprobando señales, el push se rechaza en vez de sobrescribirlo: vuelve
a ejecutar el workflow con la configuración nueva.

## Pruebas locales opcionales

No son necesarias para que el bot funcione en GitHub. Python 3.11+:

```powershell
python -m unittest discover -s tests -v
python scripts/guardian.py --dry-run
```

FFmpeg y FFprobe son necesarios para verificar audio/vídeo (Actions los instala).
`--manifest-only` permite revisar HLS sin declararlo operativo; `--offline`
evita descargar listas y renovar TVN, pero **sigue haciendo pruebas de red**.
`--dry-run` no escribe ni la lista, ni respaldos, ni el diagnóstico.

## Seguridad

- No publicar claves ADB, certificados de emparejamiento, cookies, credenciales de
  usuarios ni tokens privados. Están excluidos los archivos locales de control de TV.
- El token eventual de TVN procede únicamente de su reproductor público: es
  temporal y solo se publica en la URL si pasa las comprobaciones. No se registra
  en logs, diagnóstico ni respaldos. No se usan sesiones de cuentas personales.
- Se rechazan URLs con credenciales, IPs literales y fuentes que no sean HTTPS.
- No se eluden DRM, geobloqueos, paywalls, captchas ni controles de acceso.
- `update_playlist.py`, `refresh_from_sources.py` y `deploy/` son utilidades
  heredadas/opcionales: **no forman parte del bot público**. No las uses para
  publicar listas o secretos privados; el guardián regenera el M3U desde el catálogo.

Guía de operación: [docs/CONFIGURAR_BOT.md](docs/CONFIGURAR_BOT.md).
