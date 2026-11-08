# Configurar el bot en GitHub Actions

Esta guía deja el bot funcionando solo, sin depender de tu PC.

## 1. Subir los archivos al repositorio

Sube al repo `Amaroo00/canales-tvchi` (rama `main`) estos archivos:

```
.github/workflows/guardian.yml
config/public_sources.json
scripts/sync_public_sources.py
scripts/refresh_tokens.py
scripts/guardian.py
scripts/update_playlist.py
canales.m3u
STATUS.md
README.md
```

Si no tienes Git instalado, puedes arrastrarlos desde la web de GitHub:
**Add file → Upload files**. GitHub conserva las carpetas si arrastras la
estructura completa.

## 2. Activar Actions

1. Abre el repo en GitHub.
2. Pestaña **Actions**.
3. Si sale el aviso de workflows deshabilitados, pulsa
   **I understand my workflows, go ahead and enable them**.
4. En la lista izquierda elige **Guardián 24/7 - IPTV Chile**.
5. Pulsa **Enable workflow** si aparece ese botón.

## 3. Primera ejecución manual

1. Dentro del workflow, pulsa **Run workflow** → **Run workflow**.
2. Espera 1–3 minutos.
3. Debe aparecer un commit nuevo:
   `🤖 Guardián 24/7: lista actualizada y verificada [skip ci]`.
4. Abre `STATUS.md` y revisa que los canales estén en 🟢.

## 4. Verificar que quedó programado

En **Actions → Guardián 24/7 - IPTV Chile** verás ejecuciones automáticas cada
3 horas (00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00 y 21:00 UTC).

GitHub puede retrasar la ejecución unos minutos si hay mucha carga. Es normal.

## 5. Cómo revisar un fallo

1. Abre la ejecución en **Actions**.
2. Entra al job `check-and-update`.
3. Revisa el paso que falló:
   - **Sincronizar canales**: aviso de una lista pública caída (no rompe nada).
   - **Renovar tokens**: TVN no entregó token (se conserva el anterior).
   - **Ejecutar Guardián**: muestra el resumen y los canales caídos.
4. Si el paso de commit falla por permisos, revisa:
   **Settings → Actions → General → Workflow permissions** →
   **Read and write permissions** → **Save**.

## 6. Cómo agregar un canal

1. Edita `canales.m3u` y agrega:

   ```m3u
   #EXTINF:-1 tvg-logo="https://..." group-title="Noticias", Mi Canal
   https://cdn.ejemplo.cl/micanal/index.m3u8
   ```

2. Si quieres respaldos automáticos, agrega el alias en
   `config/public_sources.json`:

   ```json
   "aliases": {
     "Mi Canal": ["Nombre exacto en iptv-org", "Nombre exacto en m3u.cl"]
   }
   ```

3. Haz commit. En la siguiente ejecución el bot buscará y validará respaldos.

## 7. Cómo cambiar la frecuencia

Edita `.github/workflows/guardian.yml`:

```yaml
on:
  schedule:
    - cron: '0 */3 * * *'   # cada 3 horas
```

Ejemplos:

| Frecuencia | cron |
| :--- | :--- |
| Cada hora | `0 * * * *` |
| Cada 3 horas | `0 */3 * * *` |
| Cada 6 horas | `0 */6 * * *` |
| Cada 30 minutos | `*/30 * * * *` |

> GitHub no garantiza ejecuciones por debajo de 5 minutos y puede retrasar las
> programadas. No hace falta correr más seguido que cada 1–3 horas.

## 8. Ejecutarlo en tu PC

```powershell
python scripts\sync_public_sources.py
python scripts\refresh_tokens.py
python scripts\guardian.py
```

O doble clic en `run_bot.bat`.

## 9. Si GitHub desactiva el workflow por inactividad

GitHub desactiva los workflows programados de repos sin actividad durante
60 días. Como este bot hace un commit cada vez que cambia algo, normalmente no
pasa. Si pasa:

1. Entra a **Actions**.
2. Pulsa **Enable workflow**.
3. Ejecuta **Run workflow** una vez.

## 10. Seguridad

- El repo es público: **no pongas tokens, cookies ni listas privadas** en
  `canales.m3u`.
- Para listas privadas usa un secret `PLAYLIST_URL` y el script
  `scripts/update_playlist.py` (ver `docs/ACTUALIZAR_LISTA.md`).
- Usa solo canales públicos/abiertos o servicios donde tengas autorización.
