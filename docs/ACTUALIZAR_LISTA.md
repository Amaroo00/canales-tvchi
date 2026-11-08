# Actualización desde una lista privada (opcional)

> **Nota:** el workflow actual usa por defecto las listas públicas
> (`scripts/sync_public_sources.py`). Esta guía es solo para cuando tengas una
> lista privada propia y quieras descargarla desde un secret de GitHub.

El script `scripts/update_playlist.py` puede hacer dos cosas en cada ejecución:

1. Descargar la última lista M3U desde la URL privada que configures.
2. Fusionarla con `canales.m3u` (modo `merge`), conservando tus canales.

La URL no se guarda en el repositorio: se lee desde un **secret** de GitHub.

## Configurar la URL

1. Abre el repo en GitHub: `Settings` → `Secrets and variables` → `Actions`.
2. Pulsa `New repository secret`.
3. Nombre: `PLAYLIST_URL`.
4. Valor: la URL completa de tu lista M3U.
5. Guarda.

Con eso, la próxima ejecución del workflow ya descarga la lista.

### Headers opcionales

Si el servidor exige `Referer`, `Origin`, `User-Agent` o una cookie, crea estos
secrets adicionales:

- `PLAYLIST_HEADERS`: un JSON, por ejemplo:

  ```json
  {"Referer": "https://ejemplo.cl/", "Origin": "https://ejemplo.cl"}
  ```

- `PLAYLIST_COOKIE`: el valor completo del header `Cookie`, si hace falta.

No pongas estos datos en `canales.m3u` ni en el código.

## Cómo se actualiza el archivo

Por defecto se usa **merge**:

- Los canales de la lista nueva se agregan o actualizan.
- Los canales que ya tenías y no vienen en la lista nueva se conservan.
- Si un canal existe en ambos, se mantienen sus URLs de respaldo.

Si prefieres que la lista descargada reemplace todo, cambia en
`.github/workflows/guardian.yml`:

```yaml
MERGE_MODE: replace
```

También puedes filtrar solo algunos canales de la lista descargada:

```yaml
ONLY_CHANNELS: "TNT Sport"
```

## Ejecutarlo a mano

En GitHub: `Actions` → `Guardián 24/7 - IPTV Chile` → `Run workflow`.

El workflow corre automáticamente cada 6 horas (00:00, 06:00, 12:00 y 18:00 UTC).

## Probarlo en tu PC

```sh
cd canales-tvchi
PLAYLIST_URL='https://tu-url-privada' MERGE_MODE=merge python3 scripts/update_playlist.py
```

Para ver qué haría sin escribir nada:

```sh
PLAYLIST_URL='https://tu-url-privada' DRY_RUN=1 python3 scripts/update_playlist.py
```

## Seguridad importante

El repo `Amaroo00/canales-tvchi` es **público**. Si la lista descargada lleva
tokens, usuario/contraseña o cookies dentro de las URLs de cada canal, al hacer
commit esos datos quedan visibles para cualquiera.

Si eso te importa:

- usa un repo privado para la lista privada, o
- guarda la lista como *artifact* del workflow en vez de hacer commit, o
- pon un proxy (por ejemplo Threadfin) que guarde las credenciales y exponga
  solo una URL local.

La URL de descarga en sí nunca se escribe en el repo: va siempre como secret.

## Nota

Usa esto únicamente con listas propias o de servicios autorizados. El script no
salta DRM, paywalls ni protecciones de acceso.
