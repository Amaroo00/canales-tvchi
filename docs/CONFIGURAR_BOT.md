# Bot autónomo en GitHub Actions

El flujo vigente es `.github/workflows/guardian.yml`. Corre cada hora, al minuto
17, y también por ejecución manual o cambios del catálogo/código en `main`.
No necesita tu PC encendido, ADB, systemd, cron ni credenciales de una TV.

## Comprobar que funciona

1. Abre **Actions → Guardián 24/7 - IPTV Chile**.
2. Habilita el workflow si GitHub lo muestra desactivado.
3. Pulsa **Run workflow**, rama `main`.
4. Revisa los tests y el paso **Descubrir fuentes y verificar HLS, vídeo y audio**.
5. Comprueba el commit generado y `STATUS.md`.

Las pruebas reales pueden tardar varios minutos, sobre todo con fuentes que
no responden. El job tiene un límite de 35 minutos y paralelismo acotado.
El resumen de la ejecución y su artefacto conservan el diagnóstico durante 7 días.

## Archivos que publica

- `canales.m3u`: una URL por canal aprobado con fuente; mantiene también las
  señales que el runner no puede verificar y la URL anterior si fallan todas.
- `canales_verificados.m3u`: solo las señales verificadas en esa ejecución.
- `config/backups.json`: candidatos sin secretos de sesión.
- `STATUS.md` y `data/health.json`: resultados y avisos de fuentes/renovación.

Un 403 aparece **sin verificar**, no como señal operativa. Las comprobaciones
se realizan desde la IP del runner, normalmente fuera de Chile. Para verificar
que un canal georrestringido funciona en Chile hace falta observarlo allí; no
se puede afirmar a partir del 403 ni se evade el bloqueo.

## Agregar o corregir canales

Edita `config/channels.json` en GitHub. El bot no requiere archivos locales.

```json
{
  "id": "MiCanal.cl",
  "name": "Mi Canal",
  "group": "Regionales",
  "page": "https://www.emisora.cl/",
  "aliases": ["Nombre en catálogo externo"],
  "hosts": ["cdn.emisora.cl"],
  "stream_keys": ["/micanal/"],
  "urls": ["https://cdn.emisora.cl/micanal/master.m3u8"]
}
```

`stream_keys` compara rutas (no query strings) y evita intercambiar señales del
mismo CDN. No uses `/` o claves genéricas para aprobar todo un proveedor.
`hosts` acepta el dominio exacto y sus subdominios, no coincidencias de texto.
La fuente debe ser pública o contar con autorización para publicarse.

Puedes agregar un logo en `config/logos.json`. Los M3U y respaldos son archivos
generados: no edites directamente una URL para mantenerla permanentemente.

## Fallos frecuentes

- **Una lista pública no responde:** se conserva el catálogo y el banco previo.
  El diagnóstico deja el aviso y el bot prueba las fuentes guardadas.
- **TVN no renueva:** se respeta el error y se prueban las URLs aprobadas. No se
  considera válido un token por el mero hecho de haberlo encontrado en HTML.
- **Audio ausente o no decodificable:** se intenta un respaldo. El silencio o
  saturación observados se marcan como aviso; una pausa no demuestra una avería.
- **403/451:** acceso restringido, no una confirmación de geobloqueo ni de éxito.
- **Cambio de CDN/ruta:** revisa la página de la emisora y actualiza el catálogo.
- **Push rechazado:** comprueba reglas de rama/permisos; si hubo un cambio en
  `main` durante la ejecución, repite el workflow. Nunca se hace push forzado.
- **No hay ejecuciones programadas:** revisa que el workflow esté habilitado y
  presente en la rama por defecto. GitHub puede retrasar o desactivar horarios.
- **La TV muestra lo anterior:** recarga la URL de lista y revisa su caché.

No hace falta configurar secretos para este bot público. Nunca subas claves ADB,
certificados, cookies o sesiones personales para resolver un canal caído.

Las utilidades de `deploy/` y las guías de fuentes privadas son heredadas y no
son requisitos de este flujo. Usa el pipeline integrado para la lista pública.
