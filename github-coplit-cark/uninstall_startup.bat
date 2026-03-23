@echo off
setlocal

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_FILE=%STARTUP_DIR%\copilot_human_gate_bridge_startup.cmd"

if exist "%STARTUP_FILE%" (
    del /f /q "%STARTUP_FILE%"
    if errorlevel 1 (
        echo [ERROR] Failed to remove startup file:
        echo [ERROR] %STARTUP_FILE%
        exit /b 1
    )
    echo [INFO] Removed startup file:
    echo [INFO] %STARTUP_FILE%
) else (
    echo [INFO] Startup file not found. Nothing to remove.
)

endlocal
