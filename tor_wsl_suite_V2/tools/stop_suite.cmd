@echo off
REM =====================================================================
REM  Cyberdeck Tor Suite - Stop (manuell, graceful)
REM =====================================================================
set "SUITE_TOOLS=C:\tor-expert-bundle\tor_wsl_suite\tools"

wsl.exe -d kali-linux -- bash "%SUITE_TOOLS%\stop_suite.sh"

echo.
echo Cyberdeck Tor Suite gestoppt.
echo.
pause