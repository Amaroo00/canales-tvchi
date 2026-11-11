# TVN y URLs temporales del reproductor público

La renovación está **integrada en `scripts/guardian.py`** y se ejecuta cada hora
en GitHub Actions. No requiere tu PC, cuentas personales ni cookies privadas.
`scripts/refresh_tokens.py` expone el resolver; ejecutarlo solo no modifica el M3U.

## Funcionamiento

1. Consulta `https://live.tvn.cl/?tvn_subseccion=senal-tvn` por HTTPS con
   verificación de certificado, respetando cualquier restricción de acceso.
2. Solo acepta el ID conocido de TVN y un token que publique esa página.
3. Construye una candidata de Mediastream y pasa por las mismas comprobaciones
   de HLS, segmentos, paquetes de vídeo y decodificación de audio que el resto.
4. Solo la selecciona si funciona mejor que las demás fuentes verificadas.
5. No guarda el token en logs, diagnóstico ni `config/backups.json`. Si se
   selecciona, la URL de reproducción pública puede contener ese token temporal.

Un 401/403 no significa éxito ni prueba que el canal esté geobloqueado.
Si falla la página o el candidato, se conserva la fuente anterior aprobada,
se prueban los demás candidatos y se informa el problema. **No se garantiza
que una URL temporal dure hasta la siguiente ejecución.**

No se recurre a retransmisores por IP ni se intercambia TVN por 24 Horas.
No se eluden DRM, paywalls, captchas, geobloqueos ni controles de acceso.

## Diagnóstico

En GitHub: **Actions → Guardián 24/7 - IPTV Chile → Run workflow**.
Consulta el aviso de renovación en `STATUS.md` y el diagnóstico por fuente en
`data/health.json`. Para una simulación local opcional:

```powershell
python scripts/guardian.py --dry-run
```

Guía vigente: [CONFIGURAR_BOT.md](CONFIGURAR_BOT.md).
