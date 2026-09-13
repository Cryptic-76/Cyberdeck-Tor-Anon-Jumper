<#
.SYNOPSIS
  Cyberdeck Tor Suite - Autostart installieren.

  Legt einen versteckten VBS-Launcher in den Windows-Startup-Ordner.
  Bei jeder Windows-Anmeldung startet die Suite damit automatisch (ohne Fenster).

.PARAMETER Remove
  Entfernt die Autostart-Verknuepfung wieder.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install_autostart.ps1
  powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
#>
param(
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

$suiteRoot  = "C:\tor-expert-bundle\tor_wsl_suite"
$src        = Join-Path $suiteRoot "_autostart.vbs"
$startupDir = [Environment]::GetFolderPath('Startup')
$dst        = Join-Path $startupDir "Cyberdeck_TorSuite_Autostart.vbs"

if ($Remove) {
    if (Test-Path -LiteralPath $dst) {
        Remove-Item -LiteralPath $dst -Force
        Write-Output "Autostart entfernt: $dst"
    } else {
        Write-Output "Autostart war nicht installiert."
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $src)) {
    Write-Output "[FEHLER] Quell-VBS fehlt: $src" -ForegroundColor Red
    exit 1
}

Copy-Item -LiteralPath $src -Destination $dst -Force
Write-Output "Autostart installiert: $dst"
Write-Output "Die Suite startet nun automatisch bei jeder Windows-Anmeldung (versteckt)."