@echo off
setlocal

set "SERVER_NAME=copilot_human_gate_bridge"
set "CONFIG_PATH=%USERPROFILE%\.codex\config.toml"

if exist "%CONFIG_PATH%" (
    copy /Y "%CONFIG_PATH%" "%CONFIG_PATH%.bak" >nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$path = [System.IO.Path]::Combine($env:USERPROFILE, '.codex', 'config.toml');" ^
      "$content = Get-Content -Raw -Encoding UTF8 $path;" ^
      "$updated = [regex]::Replace($content, '(?ms)^\[mcp_servers\.copilot_human_gate_bridge\]\r?\n.*?(?=^\[|\z)', '');" ^
      "$updated = [regex]::Replace($updated, '(?ms)^\[mcp_servers\.copilot_human_gate_bridge\.env\]\r?\n.*?(?=^\[|\z)', '');" ^
      "$updated = $updated.TrimEnd() + \"`r`n\";" ^
      "Set-Content -Encoding UTF8 $path $updated;"
    if errorlevel 1 (
        echo [WARN] Failed to remove %SERVER_NAME% from "%CONFIG_PATH%".
        echo [WARN] Backup is available at "%CONFIG_PATH%.bak".
    ) else (
        echo [INFO] Removed %SERVER_NAME% from "%CONFIG_PATH%".
        echo [INFO] Backup written to "%CONFIG_PATH%.bak".
    )
) else (
    echo [INFO] Codex config not found. Nothing to clean.
)

echo [INFO] Done.

endlocal
