"""
Cyberdeck Tor Suite - Windows System Proxy Manager
Steuert die Proxy-Einstellungen von Windows über PowerShell-Befehle aus WSL heraus.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from config.settings import PRIVOXY_PORT
from core.system_check import SystemChecker

logger = logging.getLogger(__name__)

# Absoluter Interop-Pfad zu PowerShell aus der WSL2-Umgebung heraus (überwindet sudo PATH-Reset)
POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


class WindowsProxyManager:
    """Verwaltet das Aktivieren und Deaktivieren des Windows HTTP/HTTPS Systemproxies."""

    def __init__(self, port: int = PRIVOXY_PORT) -> None:
        self.port = port
        self.checker = SystemChecker()

    def _run_powershell(self, command: str) -> Tuple[bool, str]:
        """Führt ein PowerShell-Kommando auf dem Host aus über den absoluten WSL-Pfad."""
        if not Path(POWERSHELL_PATH).exists():
            err_msg = f"PowerShell Interop-Pfad nicht gefunden: {POWERSHELL_PATH}"
            logger.error(f"[-] {err_msg}")
            return False, err_msg

        try:
            ps_cmd = [
                POWERSHELL_PATH,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
            result = subprocess.run(ps_cmd, capture_output=True, text=True, check=True)
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.strip() or e.stdout.strip()
            logger.error(f"[-] PowerShell-Fehler: {err_msg}")
            return False, err_msg
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei PowerShell-Ausführung: {e}")
            return False, str(e)

    def enable_proxy(self, target_ip: Optional[str] = None) -> bool:
        """
        Aktiviert den Windows-Systemproxy und leitet ihn an Privoxy in WSL weiter.
        Verwendet entweder die WSL-IP oder 127.0.0.1 (wenn Portproxy aktiv ist).
        """
        ip = target_ip or self.checker.get_wsl_ip()
        proxy_address = f"{ip}:{self.port}"

        logger.info(f"Setze Windows-Systemproxy auf {proxy_address}...")

        # Registry-Befehle via PowerShell zur Proxy-Aktivierung
        ps_cmd = (
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyEnable -Value 1; '
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyServer -Value "{proxy_address}"'
        )

        success, _ = self._run_powershell(ps_cmd)
        if success:
            logger.info(f"[+] Windows-Systemproxy erfolgreich aktiviert ({proxy_address}).")
            return True
        else:
            logger.error("[-] Aktivieren des Windows-Systemproxies fehlgeschlagen.")
            return False

    def disable_proxy(self) -> bool:
        """Deaktiviert den Windows-Systemproxy sauber."""
        logger.info("Deaktiviere Windows-Systemproxy...")

        ps_cmd = (
            'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" -Name ProxyEnable -Value 0'
        )

        success, _ = self._run_powershell(ps_cmd)
        if success:
            logger.info("[+] Windows-Systemproxy erfolgreich deaktiviert.")
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