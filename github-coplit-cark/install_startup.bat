@echo off
setlocal

for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "START_SCRIPT=%REPO_DIR%\start_bridge.bat"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_FILE=%STARTUP_DIR%\copilot_human_gate_bridge_startup.cmd"

if not exist "%START_SCRIPT%" (
    echo [ERROR] Could not find "%START_SCRIPT%".
    exit /b 1
)

if not exist "%STARTUP_DIR%" (
    echo [ERROR] Could not find Startup folder:
    echo [ERROR] %STARTUP_DIR%
    exit /b 1
)

(
    echo @echo off
    echo call "%START_SCRIPT%"
) > "%STARTUP_FILE%"

if errorlevel 1 (
    echo [ERROR] Failed to write startup file.
    exit /b 1
)

echo [INFO] Startup script installed:
echo [INFO] %STARTUP_FILE%
echo [INFO] Windows logon will now call:
echo [INFO] %START_SCRIPT%

endlocal
