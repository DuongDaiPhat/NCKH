@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================================================
echo               RESET MOI TRUONG CAI DAT (THREADS CRAWLER)
echo ====================================================================
echo Script nay giup don dep cac tep bi loi hoac do dang do mat mang:
echo   [+] Xoa moi truong ao .venv bi hong
echo   [+] Xoa bo nho dem tai do cua pip
echo   [+] Xoa bo nho dem Chromium tai do cua Playwright
echo.
echo Cac du lieu quan trong sau se duoc GIU NGUYEN - KHONG BI ANH HUONG:
echo   - File khoa va thong tin nhay cam: secrets, .env
echo   - File cau hinh phan cong: configs, config.yaml
echo   - Du lieu crawl va phien dang nhap: crawled_data, user_data
echo ====================================================================
echo.
echo Nhan phim bat ky de bat dau don dep, hoac dong cua so nay de huy...
pause >nul
echo.

echo [1/4] Dong cac tien trinh Python dang chay ngam de tranh khoa file...
taskkill /F /IM python.exe >nul 2>&1
echo       - Hoan tat.

echo [2/4] Dang xoa thu muc moi truong ao .venv...
if exist ".venv" (
    rd /s /q ".venv" >nul 2>&1
)
if exist ".venv" (
    echo [CANH BAO] Khong the xoa hoan toan .venv do file dang bi khoa boi tien trinh khac.
    echo           Vui long khoi dong lai may tinh roi chay lai file reset.bat nay!
    echo.
    pause
    exit /b 1
) else (
    echo       - Da xoa sach thu muc .venv.
)

echo [3/4] Dang xoa cache tai do cua pip...
if exist "%LOCALAPPDATA%\pip\cache" (
    rd /s /q "%LOCALAPPDATA%\pip\cache" >nul 2>&1
    echo       - Da don sach cache cua pip.
) else (
    echo       - Khong co cache pip ton dong.
)

echo [4/4] Dang xoa cache tai do cua Playwright Chromium...
if exist "%LOCALAPPDATA%\ms-playwright" (
    rd /s /q "%LOCALAPPDATA%\ms-playwright" >nul 2>&1
    echo       - Da don sach cache Playwright Chromium.
) else (
    echo       - Khong co cache Playwright ton dong.
)

echo Dang don dep cac tep tam Python...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
echo       - Da don sach tep tam.

echo.
echo ====================================================================
echo DA RESET THANH CONG!
echo Bay gio ban hay dam bao ket noi Internet on dinh, sau do
echo nhap dup chuot vao setup_windows.bat de cai dat lai tu dau.
echo ====================================================================
echo.
pause
exit /b 0
