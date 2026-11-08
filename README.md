# 📡 IPTV Chile — Guardián 24/7

Lista M3U de canales chilenos que se **verifica y actualiza sola** cada 3 horas
con GitHub Actions. Si una señal principal se cae, el bot conmuta a un respaldo
y, si hace falta, agrega señales nuevas desde listas públicas que se mantienen
al día.

## Lista para tu reproductor

```
https://raw.githubusercontent.com/Amaroo00/canales-tvchi/main/canales.m3u
```

Pega esa URL en VLC, TiviMate, IPTV Smarters, MiTV, Kodi o cualquier
reproductor compatible con M3U/HLS.

Estado de los canales: [STATUS.md](STATUS.md)

## Qué hace el bot

Cada 3 horas (y cuando lo ejecutes a mano) el workflow
`.github/workflows/guardian.yml`:

1. **Sincroniza** `canales.m3u` con listas públicas que se actualizan solas:
   - [iptv-org Chile](https://iptv-org.github.io/iptv/countries/cl.m3u)
   - [m3u.cl Chile](https://cdn.m3u.cl/lista/CL.m3u)
2. **Renueva** el token de TVN HD desde la página oficial de TVN.
3. **Verifica** cada canal y cada respaldo (HTTP 200 + `#EXTM3U`).
4. **Conmuta** al respaldo que funcione y deja las señales caídas al final.
5. **Publica** `canales.m3u` y `STATUS.md` con el resultado.

Reglas de seguridad del bot:

- Nunca borra canales ni cambia sus cabeceras `#EXTINF`.
- Solo reemplaza una URL si la nueva fue validada.
- Si una fuente falla, deja la lista intacta y sigue con las demás.
- Escribe de forma atómica (`tmp` + reemplazo), así que un error no rompe la lista.

## Estructura del repositorio

| Archivo | Para qué sirve |
| :--- | :--- |
| `canales.m3u` | Lista final que consume tu reproductor. |
| `STATUS.md` | Reporte de salud, latencia y respaldos de cada canal. |
| `config/public_sources.json` | Listas públicas y alias de nombres de canales. |
| `scripts/sync_public_sources.py` | Agrega/renueva señales desde las listas públicas. |
| `scripts/refresh_tokens.py` | Renueva el token de TVN HD. |
| `scripts/guardian.py` | Verifica canales, conmuta respaldos y genera `STATUS.md`. |
| `scripts/update_playlist.py` | (Opcional) Descarga una lista privada desde un secret. |
| `scripts/refresh_from_sources.py` | (Opcional) Renueva URLs desde páginas/API propias. |
| `.github/workflows/guardian.yml` | Automatización en GitHub Actions. |

## Ejecutarlo en tu PC

Requisitos: Python 3.9 o superior.

```powershell
python scripts\sync_public_sources.py
python scripts\refresh_tokens.py
python scripts\guardian.py
```

O simplemente haz doble clic en `run_bot.bat`.

Para probar sin escribir nada:

```powershell
python scripts\sync_public_sources.py --dry-run
```

## Cómo agregar o quitar canales

1. Agrega el bloque en `canales.m3u`:

   ```m3u
   #EXTINF:-1 tvg-logo="https://..." group-title="Noticias", Mi Canal
   https://cdn.ejemplo.cl/micanal/index.m3u8
   ```

2. Si el nombre del canal no coincide con el que usan las listas públicas,
   agrégalo en `config/public_sources.json` → `aliases`:

   ```json
   "Mi Canal": ["Nombre en iptv-org", "Nombre en m3u.cl"]
   ```

3. Listo: en la próxima ejecución el bot le buscará respaldos automáticamente.

## Activar la automatización en GitHub

La primera vez hay que habilitar el workflow:

1. Repo → pestaña **Actions**.
2. Si aparece un aviso, pulsa **I understand my workflows, go ahead and enable them**.
3. Entra a **Guardián 24/7 - IPTV Chile** → **Run workflow** para probarlo.
4. Revisa que el commit aparezca en la rama `main`.

No se necesitan secretos para las fuentes públicas. Si algún día quieres usar
una lista privada, sigue [docs/ACTUALIZAR_LISTA.md](docs/ACTUALIZAR_LISTA.md).

## Notas importantes

- Este repo es **público**. No pongas tokens, cookies ni listas privadas en
  `canales.m3u`: cualquiera podría verlos. Usa un repo privado o un secret.
- Usa el proyecto solo con canales públicos/abiertos o servicios donde tengas
  autorización. El bot no salta DRM, paywalls ni protecciones de acceso.
- Los canales privados (por ejemplo ESPN Premium) no tienen señal pública
  estable; por eso el bot usa la señal pública más parecida que encuentre.
- GitHub Actions puede retrasar unos minutos las ejecuciones programadas; es
  normal. El bot corre igual varias veces al día.
