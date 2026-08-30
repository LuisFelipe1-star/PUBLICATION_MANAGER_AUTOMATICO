@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (echo Execute install_windows.bat primeiro.& pause & exit /b 1)
call "%~dp0cuda_env.bat"
start "Publication Manager" .venv\Scripts\pythonw.exe main.py
