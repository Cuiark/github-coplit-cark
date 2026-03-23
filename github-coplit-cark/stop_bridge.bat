@echo off
setlocal

for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "RUNTIME_DIR=%REPO_DIR%\.runtime"
set "PID_FILE=%RUNTIME_DIR%\bridge.pid"
set "FOUND_ANY="

if exist "%PID_FILE%" (
    set /p BRIDGE_PID=<"%PID_FILE%"
    if defined BRIDGE_PID (
        echo [INFO] Stopping bridge PID %BRIDGE_PID% from pid file...
        taskkill /PID %BRIDGE_PID% /T /F >nul 2>nul
        set "FOUND_ANY=1"
    )
    del /f /q "%PID_FILE%" >nul 2>nul
)

for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:"127.0.0.1:4317 .*LISTENING"') do (
    echo [INFO] Stopping bridge PID %%P from port 4317...
    taskkill /PID %%P /T /F >nul 2>nul
    set "FOUND_ANY=1"
)

if not defined FOUND_ANY (
    echo [INFO] No running bridge process was found.
) else (
    echo [INFO] Bridge service stopped.
)

endlocal
