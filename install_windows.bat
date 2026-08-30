@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul || (echo Python nao encontrado. Instale Python 3.10 ou 3.11.& pause & exit /b 1)
py -3 -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || exit /b 1
if not exist .env copy .env.example .env >nul
where ffprobe >nul 2>nul || echo AVISO: FFprobe nao esta no PATH.
echo Instalacao concluida.
pause
