# Renovar tokens m3u8 desde tus propias fuentes

> **Guía heredada/opcional.** El bot público actual renueva TVN dentro de
> `scripts/guardian.py` y corre en GitHub Actions sin PC ni servidor propio.
> Consulta [CONFIGURAR_BOT.md](CONFIGURAR_BOT.md). El M3U se regenera desde
> `config/channels.json`; no conectes este motor genérico a la publicación pública
> de credenciales privadas ni uses los pasos de systemd/cron como requisito.

`scripts/refresh_from_sources.py` es el motor genérico. Tú le dices, en un JSON,
de qué página o API sacar la URL de cada canal; el script la descarga, extrae las
candidatas, las valida y solo entonces actualiza `canales.m3u`.

No genera tokens por su cuenta: **lee URLs que la fuente ya publica**. No salta
DRM, paywalls, captchas ni logins.

## Archivos

| Archivo | Para qué |
| :--- | :--- |
| `config/sources.example.json` | Plantilla. Cópiala y edítala. |
| `config/sources.json` | Tus fuentes (puedes commitearla si no tiene secretos). |
| `config/sources.local.json` | Igual, pero ignorada por git. Úsala si lleva cookies/API keys. |
| `scripts/refresh_from_sources.py` | Motor de extracción, validación y reemplazo. |
| `deploy/refresh_and_push.sh` | Ejecuta el script y hace commit/push. |
| `deploy/iptv-tokens.service` | Servicio systemd. |
| `deploy/iptv-tokens.timer` | Timer cada 3 horas. |

El script usa `config/sources.local.json` si existe; si no, `config/sources.json`.
También puedes pasar otro archivo con `--config`.

## 1. Pon tus URLs

```sh
cd /opt/canales-tvchi   # o donde tengas el repo
cp config/sources.example.json config/sources.json
nano config/sources.json
```

Cada fuente va dentro de `sources`:

```json
{
  "name": "TVN HD",
  "enabled": true,
  "page": "https://live.tvn.cl/?tvn_subseccion=senal-tvn",
  "headers": {
    "Referer": "https://www.tvn.cl/",
    "Origin": "https://www.tvn.cl"
  },
  "patterns": [
    "https://mdstrm\\.com/live-stream-playlist/[0-9a-f]{24}\\.m3u8\\?access_token=[^'\"\\s<]+"
  ],
  "replace_urls_containing": "mdstrm.com",
  "add_if_missing": false
}
```

### Campos

| Campo | Obligatorio | Qué hace |
| :--- | :---: | :--- |
| `name` | Sí | Nombre del canal en `canales.m3u`. Se compara sin acentos ni mayúsculas. |
| `page` | Sí | Página o API donde aparece la URL m3u8. |
| `patterns` | Sí | Lista de expresiones regulares para extraer la URL. |
| `headers` | No | Headers extra (`Referer`, `Origin`, `Cookie`, `Authorization`, etc.). |
| `replace_urls_containing` | No | Texto o lista de textos para elegir qué línea(s) reemplazar. Si no está, reemplaza la primera URL del canal. |
| `add_if_missing` | No | `true` para agregar la URL si el canal no tiene ninguna que coincida. Default: `false`. |
| `enabled` | No | `false` para desactivar la fuente. Default: `true`. |

Los valores de `headers` aceptan variables de entorno con `${NOMBRE}`. Así no
guardas cookies ni claves en el JSON:

```json
"headers": {
  "Authorization": "Bearer ${PROVEEDOR_TOKEN}",
  "Cookie": "${PROVEEDOR_COOKIE}"
}
```

## 2. Cómo escribir los `patterns`

Se usa `re.findall` de Python. Si el patrón tiene un grupo `( ... )`, se usa el
grupo 1; si no, se usa el match completo. El script desescapa `&amp;` y `\/`
antes de buscar.

Ejemplos:

```json
"patterns": ["https://[^\"'<> ]+\\.m3u8[^\"'<> ]*"]
```

```json
"patterns": ["\"url\"\\s*:\\s*\"([^\"]+\\.m3u8[^\"]*)\""]
```

```json
"patterns": ["https://[^\"'<> ]+\\?[^\"'<> ]*token=[^\"'<> ]+"]
```

Puedes poner varios patrones; se prueban en orden y se descartan duplicados.

## 3. Probar sin escribir

```sh
python3 scripts/refresh_from_sources.py --dry-run
```

Salida esperada:

```text
Renovando desde 1 fuente(s) en canales.m3u (config: config/sources.json)...
[1/1] TVN HD
  Fuente: https://live.tvn.cl/...
  Candidatas encontradas: 1
  URL validada: https://mdstrm.com/...
  Resultado: token/URL renovado
[dry-run] Se actualizaría canales.m3u: 1 fuente(s) renovada(s), 0 con problemas.
```

Si una fuente falla, el script **no toca la lista** y sigue con las demás. Con
`--strict` devuelve código 1 para que cron/systemd lo marque como fallo.

## 4. Aplicar

```sh
python3 scripts/refresh_from_sources.py
```

El reemplazo es por línea y atómico (`tmp` + `os.replace`). Solo cambia las
líneas de URL que coincidan con `replace_urls_containing`; conserva respaldos,
cabeceras y el resto del archivo.

## 5. Programar cada 3 horas

### systemd (recomendado)

```sh
sudo cp deploy/iptv-tokens.service /etc/systemd/system/
sudo cp deploy/iptv-tokens.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iptv-tokens.timer
```

Comprobar:

```sh
systemctl list-timers iptv-tokens.timer
journalctl -u iptv-tokens.service -n 50 --no-pager
```

Ajusta `User`, `Group` y `WorkingDirectory` en el `.service` a tu servidor.

### cron

```cron
0 */3 * * * cd /opt/canales-tvchi && ./deploy/refresh_and_push.sh >> /var/log/iptv-tokens.log 2>&1
```

## 6. Que el servidor pueda hacer push

El wrapper `deploy/refresh_and_push.sh` hace `git pull --rebase`, ejecuta el
script, y si hay cambios hace commit y `git push`.

Necesitas credenciales de escritura en el servidor. La forma más limpia es una
**Deploy Key** de GitHub con permiso de escritura:

```sh
ssh-keygen -t ed25519 -C "iptv-server" -f ~/.ssh/iptv_deploy
cat ~/.ssh/iptv_deploy.pub
# GitHub → repo → Settings → Deploy keys → Add deploy key (Allow write access)
```

Y en el repo:

```sh
git remote set-url origin git@github.com:Amaroo00/canales-tvchi.git
```

Si el `git push` falla porque el bot de GitHub Actions publicó mientras tanto,
vuelve a ejecutar el wrapper: el `git pull --rebase` lo reconcilia.

## 7. Seguridad y uso

- Usa esto solo con canales públicos/abiertos o servicios donde tengas
  autorización. No es para saltarse DRM, paywalls ni tokens de canales premium.
- No pongas cookies, API keys ni tokens de acceso en `config/sources.json` si el
  repo es público. Usa `${VARIABLES}` y un `EnvironmentFile` de systemd, o
  `config/sources.local.json` (ignorado por git).
- El script no imprime tokens completos: en los logs solo muestra
  `https://host/...`.

## 8. Problemas comunes

| Síntoma | Causa probable |
| :--- | :--- |
| `no se encontró el canal` | El `name` no coincide con el nombre en `canales.m3u`. |
| `la fuente no entregó ninguna URL que coincida` | El `pattern` no encuentra nada; revisa el HTML/JSON de la fuente. |
| `ninguna candidata validó` | La URL extraída da 401/403/404 o no es un M3U8. |
| `no se encontró una URL que coincida` | `replace_urls_containing` no coincide con ninguna línea del canal. |
| `403` de Cloudflare | La fuente bloquea al servidor; prueba desde otra IP o usa la API oficial. |
