@echo off
REM =====================================================================
REM  Cyberdeck Tor Suite - Start (manuell)
REM  Startet die Suite in WSL (idempotent, versteckt, ohne Fenster).
REM =====================================================================
set "SUITE_TOOLS=C:\tor-expert-bundle\tor_wsl_suite\tools"

wsl.exe -d kali-linux -- bash "%SUITE_TOOLS%\start_suite.sh"

echo.
echo Cyberdeck Tor Suite gestartet (oder laeuft bereits).
echo Status:  powershell -ExecutionPolicy Bypass -File "%SUITE_TOOLS%\tor_status.ps1"
echo.
pause