@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua cai dat. Hay mo setup_windows.bat truoc.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
if "%~1"=="" (
  python B1_NLP\crawl.py
) else (
  python B1_NLP\crawl.py --config "%~1"
)
echo.
pause
