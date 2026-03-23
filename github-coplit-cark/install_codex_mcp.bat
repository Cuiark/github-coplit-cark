@echo off
setlocal

set "SERVER_NAME=copilot_human_gate_bridge"
for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "CONFIG_PATH=%USERPROFILE%\.codex\config.toml"

if not exist "%REPO_DIR%\copilot_bridge\main.py" (
    echo [ERROR] Could not find "%REPO_DIR%\copilot_bridge\main.py".
    echo Put this script in the repository root and rerun it.
    exit /b 1
)

echo [INFO] Repo: %REPO_DIR%
echo [INFO] Writing MCP config for %SERVER_NAME%...
echo [INFO] This script registers the already-running HTTP MCP service at http://127.0.0.1:4317/mcp

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$configDir = [System.IO.Path]::Combine($env:USERPROFILE, '.codex');" ^
  "$path = [System.IO.Path]::Combine($configDir, 'config.toml');" ^
  "New-Item -ItemType Directory -Force -Path $configDir | Out-Null;" ^
  "$content = if (Test-Path $path) { Get-Content -Raw -Encoding UTF8 $path } else { '' };" ^
  "if (Test-Path $path) { Copy-Item $path ($path + '.bak') -Force }" ^
  "$content = [regex]::Replace($content, '(?ms)^\[mcp_servers\.copilot_human_gate_bridge\]\r?\n.*?(?=^\[|\z)', '');" ^
  "$content = [regex]::Replace($content, '(?ms)^\[mcp_servers\.copilot_human_gate_bridge\.env\]\r?\n.*?(?=^\[|\z)', '');" ^
  "$block = \"[mcp_servers.copilot_human_gate_bridge]`r`nurl = 'http://127.0.0.1:4317/mcp'`r`nstartup_timeout_sec = 30\";" ^
  "$updated = $content.TrimEnd();" ^
  "if ($updated.Length -gt 0) { $updated += \"`r`n`r`n\" }" ^
  "$updated += $block.Trim() + \"`r`n\";" ^
  "Set-Content -Encoding UTF8 $path $updated;"

if errorlevel 1 (
    echo [ERROR] Failed to write "%CONFIG_PATH%".
    echo If a backup exists, it is at "%CONFIG_PATH%.bak".
    exit /b 1
)

echo [INFO] MCP server registered successfully.
echo [INFO] Config written to "%CONFIG_PATH%".
echo [INFO] startup_timeout_sec has been set to 30.
echo [INFO] Make sure the bridge service is already running, then restart Codex and verify with: codex mcp list

endlocal
