@echo off
setlocal
cd /d "%~dp0"

if exist ".\.venv\Scripts\python.exe" (
    set "PY_EXE=.\.venv\Scripts\python.exe"
) else if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PY_EXE=%USERPROFILE%\anaconda3\python.exe"
) else (
    set "PY_EXE=python"
)

echo ==========================================================
echo    CivicPulse React & Leaflet Intelligence Dashboard      
echo    Open in Browser: http://localhost:8000                 
echo ==========================================================

"%PY_EXE%" -m uvicorn app.api:app --host 0.0.0.0 --port 8000
