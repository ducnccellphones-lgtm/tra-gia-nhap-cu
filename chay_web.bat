@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tra gia nhap cu - web (http://localhost:5000)

set PY=
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo [LOI] May chua cai Python. Tai tai https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) roi chay lai file nay.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Dang tao moi truong Python...
  %PY% -m venv .venv || (echo [LOI] Khong tao duoc venv & pause & exit /b 1)
)

echo Tat ban web cu dang chay (neu co)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5000 .*LISTENING"') do (
  tasklist /fi "pid eq %%p" | findstr /i "python" >nul && taskkill /pid %%p /f >nul
)

echo Dang cai thu vien...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || (echo [LOI] pip install that bai & pause & exit /b 1)

echo.
echo ==== Web dang chay: http://localhost:5000  (dong cua so nay de tat) ====
echo Bang gia DTV dang tai o nen, xem tien do: http://localhost:5000/api/dtv-status
echo.
".venv\Scripts\python.exe" -c "from app import app; app.run(host='127.0.0.1', port=5000)"
pause
