"""
Cyberdeck Tor Suite - Windows System Proxy Manager
Steuert die Proxy-Einstellungen von Windows über PowerShell-Befehle aus WSL heraus.
Gehärtet nach dem EVA-Prinzip, mit WinINet Instant-Refresh und Anti-Leak Protection.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from config.settings import PRIVOXY_PORT
from core.system_check import SystemChecker

logger = logging.getLogger(__name__)

# Primary Interop-Pfad zu PowerShell aus der WSL2-Umgebung heraus
PRIMARY_POWERSHELL_PATH = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")


class WindowsProxyManager:
    """Verwaltet das Aktivieren und Deaktivieren des Windows HTTP/HTTPS Systemproxies."""

    def __init__(self, port: int = PRIVOXY_PORT) -> None:
        # E: Eingabe - Ports und System-Checker
        self.port: int = port
        self.checker: SystemChecker = SystemChecker()
        self._ps_executable: Optional[str] = self._resolve_powershell_binary()

    def _resolve_powershell_binary(self) -> Optional[str]:
        """
        Eingabe (E): Ermittelt den validen Pfad zur Windows Executable.
        Prüft erst den direkten Mount-Pfad, dann den PATH-Fallback.
        """
        if PRIMARY_POWERSHELL_PATH.exists():
            return str(PRIMARY_POWERSHELL_PATH)
        
        # Fallback über den System-PATH
        fallback = shutil.which("powershell.exe")
        if fallback:
            return fallback

        logger.error("[-] Kritischer Fehler: powershell.exe konnte weder in /mnt/c noch im PATH gefunden werden.")
        return None

    def _run_powershell(self, command: str, timeout_sec: int = 10) -> Tuple[bool, str]:
        """
        Verarbeitung (V): Führt ein PowerShell-Kommando auf dem Host aus.
        Nutzt Timeouts und Encoding-Hardening gegen Deadlocks.
        """
        if not self._ps_executable:
            return False, "PowerShell Interop-Pfad nicht aufgelöst."

        # C#-Snippet zum Triggern von InternetSetOption (Sofortige Übernahme ohne Browser-Neustart)
        wininet_refresh_code = """
        $signature = '[DllImport("wininet.dll", SetLastError = true, CharSet = CharSet.Auto)] public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);'
        $type = Add-Type -MemberDefinition $signature -Name WinInet -Namespace Native -PassThru
        $type::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
        $type::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
        """

        full_command = f"{command}; {wininet_refresh_code}"

        try:
            ps_cmd = [
                self._ps_executable,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                full_command,
            ]
            
            result = subprocess.run(
                ps_cmd, 
                capture_output=True, 
                text=True, 
                encoding="utf-8", 
                errors="replace", 
                timeout=timeout_sec, 
                check=True
            )
            return True, result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            err_msg = f"PowerShell-Aufruf nach {timeout_sec}s wegen Timeout abgebrochen."
            logger.error(f"[-] {err_msg}")
            return False, err_msg
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.strip() or e.stdout.strip()
            logger.error(f"[-] PowerShell-Fehler (Code {e.returncode}): {err_msg}")
            return False, err_msg
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei PowerShell-Ausführung: {e}")
            return False, str(e)

    def enable_proxy(self, target_ip: Optional[str] = None) -> bool:
        """
        Ausgabe (A): Aktiviert den Windows-Systemproxy und leitet ihn an Privoxy in WSL weiter.
        Inklusive ProxyOverride Bypass-Regeln zur Vermeidung von lokalen Schleifen.
        """
        ip = target_ip or self.checker.get_wsl_ip()
        proxy_address = f"{ip}:{self.port}"
        bypass_list = "<local>;127.0.0.1;localhost;172.16.*"

        logger.info(f"Setze Windows-Systemproxy auf {proxy_address}...")

        # Registry-Befehle via PowerShell zur Proxy-Aktivierung + Bypass
        ps_cmd = (
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyEnable -Value 1; '
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyServer -Value "{proxy_address}"; '
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyOverride -Value "{bypass_list}"'
        )

        success, _ = self._run_powershell(ps_cmd)
        if success:
            logger.info(f"[+] Windows-Systemproxy erfolgreich aktiviert ({proxy_address}) mit Instant-WinINet-Refresh.")
            return True
        else:
            logger.error("[-] Aktivieren des Windows-Systemproxies fehlgeschlagen.")
            return False

    def disable_proxy(self) -> bool:
        """Ausgabe (A): Deaktiviert den Windows-Systemproxy sauber und erzwingt GUI-Refresh."""
        logger.info("Deaktiviere Windows-Systemproxy...")

        ps_cmd = (
            'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyEnable -Value 0'
        )

        success, _ = self._run_powershell(ps_cmd)
        if success:
            logger.info("[+] Windows-Systemproxy erfolgreich deaktiviert & System-Settings aktualisiert.")
            return True
        else:
            logger.error("[-] Deaktivieren des Windows-Systemproxies fehlgeschlagen.")
            return False


if __name__ == "__main__":
    # Einzeltest des Moduls
    logging.basicConfig(level=logging.INFO)
    win_proxy = WindowsProxyManager()

    # Test-Routine
    if win_proxy.enable_proxy():
        print("[+] Proxy-Enable Test erfolgreich.")
        win_proxy.disable_proxy()
        print("[+] Proxy-Disable Test erfolgreich.")