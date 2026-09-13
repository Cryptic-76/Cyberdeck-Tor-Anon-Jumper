<#
.SYNOPSIS
  Cyberdeck Tor Suite - Status Tool for Windows.

  Shows the current Tor exit IP of your suite. Communication with the suite
  (Tor control port + SOCKS proxy) happens INSIDE WSL via the helper script
  tor_status_helper.py. This avoids the Windows<->WSL firewall and is
  deterministic. The control password is handled DPAPI-encrypted in WSL.

.PARAMETER Rotate
  Sends the NEWNYM signal to Tor before querying the (new) IP.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tor_status.ps1
  powershell -ExecutionPolicy Bypass -File tor_status.ps1 -Rotate
#>
param(
    [switch]$Rotate
)
$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$HelperPath = Join-Path $ScriptDir "tor_status_helper.py"
# WSL-seitiger Pfad des Helfer-Skripts (das Windows-Verzeichnis ist /mnt/c/..., klein)
$drive      = $HelperPath.Substring(0,1).ToLower()
$WslHelper  = ($HelperPath -replace '^([A-Za-z]):', ('/mnt/' + $drive)) -replace '\\', '/'

# Sanity: Suite läuft? (Kurzer WSL-Check, ob Tor-ControlPort lebt)
$alive = & wsl.exe -d kali-linux -- bash -c "ss -tln 2>/dev/null | grep -q ':9051 ' && echo UP || echo DOWN" 2>$null | Select-Object -First 1
if ($alive.Trim() -ne "UP") {
    Write-Host "[ERROR] Suite nicht aktiv (Tor-ControlPort 9051 nicht offen)." -ForegroundColor Red
    Write-Host "        Starte die Suite in WSL:  cd /mnt/c/tor-expert-bundle/tor_wsl_suite && python3 main.py" -ForegroundColor Yellow
    exit 1
}

# Helper in WSL aufrufen (mit oder ohne -rotate)
$helperArgs = @("-d", "kali-linux", "--", "python3", $WslHelper)
if ($Rotate) {
    Write-Host "Sende NEWNYM (neue Exit-IP)... " -NoNewline
}
$out = & wsl.exe @helperArgs 2>&1
if ($Rotate) { Write-Host "OK" -ForegroundColor Green }

# Ausgabe parsen
$exitIp = "-"; $isTor = "NO"; $country = "-"
foreach ($line in $out) {
    if ($line -match "^EXIT_IP=(.*)$") { $exitIp  = $matches[1] }
    if ($line -match "^IS_TOR=(.*)$")  { $isTor   = $matches[1] }
    if ($line -match "^COUNTRY=(.*)$") { $country = $matches[1] }
}

# Ausgabe
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "    CYBERDECK TOR SUITE - STATUS" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
if ($isTor -eq "YES") {
    if ($Rotate) { Write-Host "  Exit IP (new):  $exitIp   ($country)" -ForegroundColor Green }
    else          { Write-Host "  Exit IP:        $exitIp   ($country)" -ForegroundColor Green }
    Write-Host "  Traffic through Tor:  YES" -ForegroundColor Green
} else {
    Write-Host "  Exit IP:  $exitIp" -ForegroundColor Yellow
    Write-Host "  Traffic through Tor:  NO (check failed?)" -ForegroundColor Yellow
}
Write-Host "--------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Comm: WSL-internal (no Windows<->WSL firewall problem)" -ForegroundColor DarkGray
Write-Host "  Password: DPAPI-decrypted inside WSL (no plaintext)" -ForegroundColor DarkGray
Write-Host "==============================================================" -ForegroundColor Cyan