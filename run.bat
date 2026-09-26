@echo off
rem Lanzador de Ainslup Assistant (doble clic)
cd /d "%~dp0"
where python >nul 2>nul || (echo Python no encontrado en PATH & pause & exit /b 1)
if not exist cli_entry.py (echo No se encontro cli_entry.py en esta carpeta & pause & exit /b 1)
python -X utf8 cli_entry.py --headless
pause