# Renovación de tokens (canales públicos)

`scripts/refresh_tokens.py` renueva el token de TVN HD antes de que caduque.
Se ejecuta en el workflow **antes** del guardián, para que este último siempre
vea la señal más fresca.

## Qué hace

1. Lee `canales.m3u` y ubica el bloque de **TVN HD**.
2. Entra a `https://live.tvn.cl/?tvn_subseccion=senal-tvn` (con `Referer` y
   `Origin` de `tvn.cl`) y extrae el `id` y el `access_token` vigentes.
3. Arma la URL `https://mdstrm.com/live-stream-playlist/<id>.m3u8?access_token=...`.
4. **Valida** esa URL: debe responder `200` y entregar un `#EXTM3U` real.
5. Solo entonces reemplaza la línea del token en `canales.m3u`.
6. Escribe con `tmp` + `os.replace` (atómico).

## Por qué no se cae

- Si la página de TVN falla (por ejemplo, un `403` de Cloudflare desde los
  runners de GitHub), no cambia nada: queda la URL anterior y el guardián
  conmuta a `iptv.bitred.cl` o a la IP de respaldo.
- Si el token nuevo no valida, tampoco cambia nada.
- No borra canales, no reordena URLs y no toca otras líneas del archivo.
- Solo modifica la línea de `mdstrm.com` dentro del bloque de TVN HD.

> Como el token rota en cada ejecución, es normal que el workflow haga un
> commit nuevo cada 6 horas. El commit lleva `[skip ci]`, así que no dispara
> una ejecución extra.

## Ejecutarlo a mano

```sh
cd canales-tvchi-nuevo

# Ver qué haría, sin escribir
DRY_RUN=1 python3 scripts/refresh_tokens.py

# Aplicar
python3 scripts/refresh_tokens.py
```

Variables opcionales: `M3U_FILE`, `TIMEOUT`, `RETRIES`, `USER_AGENT`,
`STRICT=1` (devuelve error si no pudo renovar).

## Agregar otro canal público

Agrega un resolver en `scripts/refresh_tokens.py`, por ejemplo:

```python
def resolve_mi_canal(timeout, retries):
    status, html, error = fetch(
        "https://sitio-oficial.cl/envivo",
        build_headers({"Referer": "https://sitio-oficial.cl/"}),
        timeout,
        retries,
    )
    if status != 200:
        return None, f"HTTP {status}"

    match = re.search(r"access_token\s*=\s*['\"]([^'\"]+)", html)
    if not match:
        return None, "no se encontró el token"

    return f"https://cdn-oficial.cl/canal.m3u8?token={match.group(1)}", "ok"
```

Después agrégalo al bloque de `main()` junto a TVN, con su propia función
`is_mi_canal(name)` y su validación previa.

> Este script es solo para canales públicos/abiertos cuya señal oficial esté
> disponible libremente. No salta DRM, paywalls ni tokens de canales premium.
