@echo off
setlocal

for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "DB_PATH=%REPO_DIR%\bridge-runtime.db"
set "RUNTIME_DIR=%REPO_DIR%\.runtime"
set "PID_FILE=%RUNTIME_DIR%\bridge.pid"
set "OUT_LOG=%RUNTIME_DIR%\bridge.out.log"
set "ERR_LOG=%RUNTIME_DIR%\bridge.err.log"
set "HEALTH_URL=http://127.0.0.1:4317/health"

if not exist "%REPO_DIR%\copilot_bridge\main.py" (
    echo [ERROR] Could not find "%REPO_DIR%\copilot_bridge\main.py".
    exit /b 1
)

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $resp = Invoke-WebRequest -UseBasicParsing '%HEALTH_URL%' -TimeoutSec 2; if ($resp.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
    echo [INFO] Bridge is already running at %HEALTH_URL%.
    echo [INFO] Dashboard: http://127.0.0.1:4317/
    echo [INFO] MCP URL:   http://127.0.0.1:4317/mcp
    exit /b 0
)

set "PYTHON_EXE="
for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
)

if not defined PYTHON_EXE (
    echo [ERROR] Unable to find Python from PATH.
    echo [ERROR] Make sure ^`python^` works in this terminal, then rerun this script.
    exit /b 1
)

if exist "%PID_FILE%" del /f /q "%PID_FILE%" >nul 2>nul

echo [INFO] Starting bridge service...
echo [INFO] Repo: %REPO_DIR%
echo [INFO] Python: %PYTHON_EXE%
echo [INFO] DB: %DB_PATH%

set "BRIDGE_REPO_DIR=%REPO_DIR%"
set "BRIDGE_DB_PATH=%DB_PATH%"
set "BRIDGE_OUT_LOG=%OUT_LOG%"
set "BRIDGE_ERR_LOG=%ERR_LOG%"
set "BRIDGE_PID_FILE=%PID_FILE%"
set "BRIDGE_PYTHON_EXE=%PYTHON_EXE%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Start-Process -FilePath $env:BRIDGE_PYTHON_EXE -ArgumentList @('-m','copilot_bridge.main','--web-host','127.0.0.1','--web-port','4317','--sqlite-journal-mode','PERSIST','--db-path',$env:BRIDGE_DB_PATH) -WorkingDirectory $env:BRIDGE_REPO_DIR -WindowStyle Hidden -PassThru -RedirectStandardOutput $env:BRIDGE_OUT_LOG -RedirectStandardError $env:BRIDGE_ERR_LOG;" ^
  "Set-Content -Path $env:BRIDGE_PID_FILE -Value $p.Id -Encoding ASCII;"

if errorlevel 1 (
    echo [ERROR] Failed to start bridge process.
    exit /b 1
)

for /l %%N in (1,1,20) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "try { $resp = Invoke-WebRequest -UseBasicParsing '%HEALTH_URL%' -TimeoutSec 2; if ($resp.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
    if not errorlevel 1 goto started
    timeout /t 1 /nobreak >nul
)

echo [ERROR] Bridge did not become healthy in time.
if exist "%ERR_LOG%" (
    echo [ERROR] Last stderr output:
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%ERR_LOG%' -Tail 30"
)
exit /b 1

:started
echo [INFO] Bridge started successfully.
echo [INFO] Dashboard: http://127.0.0.1:4317/
echo [INFO] MCP URL:   http://127.0.0.1:4317/mcp
echo [INFO] Health:    %HEALTH_URL%
echo [INFO] PID file:  %PID_FILE%
echo [INFO] Logs:      %OUT_LOG%
echo [INFO] Logs:      %ERR_LOG%

endlocal
