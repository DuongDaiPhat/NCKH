@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Dang cai dat. Qua trinh nay chi can lam mot lan...
py -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
python -m playwright install chromium
if errorlevel 1 goto :error
echo.
echo Cai dat thanh cong. Bay gio co the mo run_windows.bat.
pause
exit /b 0

:error
echo.
echo Cai dat chua thanh cong. Hay chup man hinh loi va gui cho nguoi phu trach.
pause
exit /b 1
