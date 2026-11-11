@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo El bot principal corre en GitHub Actions. Tu PC no necesita estar encendido.
echo Esta ejecucion local es opcional. Sin FFmpeg no declara canales operativos.
python scripts\guardian.py
if errorlevel 1 echo ERROR: no se completo la actualizacion. Revisa la salida.
pause
