@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  IPTV Chile - Guardian 24/7 (modo local)
echo ============================================
echo.

echo [1/3] Sincronizando canales desde listas publicas...
python scripts\sync_public_sources.py
if errorlevel 1 echo Aviso: la sincronizacion tuvo problemas; se continua.

echo.
echo [2/3] Renovando token de TVN...
python scripts\refresh_tokens.py
if errorlevel 1 echo Aviso: no se pudo renovar el token; se continua.

echo.
echo [3/3] Verificando canales y generando STATUS.md...
python scripts\guardian.py

echo.
echo Listo. Revisa STATUS.md para ver el estado de los canales.
pause
