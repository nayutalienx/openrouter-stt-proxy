@echo off
setlocal
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

for /f "usebackq delims=" %%v in (`py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"` ) do set "PY_VER=%%v"
if errorlevel 1 goto :python_error
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if %PY_MAJOR% LSS 3 goto :python_version_error
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 goto :python_version_error

if not exist "%PYTHON_EXE%" (
    echo Creating virtual environment in .venv ...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
)

echo Installing dependencies ...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
    echo.
    echo Missing .env file.
    echo Create it from .env.example and set OPENROUTER_API_KEY.
    echo Example:
    echo   copy .env.example .env
    goto :error
)

echo Starting proxy on http://127.0.0.1:8787 ...
"%PYTHON_EXE%" -m uvicorn app:app --host 127.0.0.1 --port 8787
goto :eof

:python_error
echo Python 3.10+ is required, but the py launcher is not available.
goto :error

:python_version_error
echo Python 3.10+ is required. Current default py -3 version: %PY_VER%
goto :error

:error
echo.
pause
exit /b 1
