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

if "%~1"=="" (
    "%PY_EXE%" src\pipeline.py run --mode mock --max-records 400 --engine duckdb
) else (
    "%PY_EXE%" src\pipeline.py %*
)
