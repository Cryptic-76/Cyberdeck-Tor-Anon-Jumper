"""
Cyberdeck Tor Suite - Tor Service Lifecycle Controller
Verwaltet das Aktivieren, Bereinigen und Stoppen des Tor-Systemd/Init-Dienstes.
Gehärtet nach dem EVA-Prinzip, mit WSL2-Init-Fallback und gestuftem Prozess-Cleanup.
"""

import logging
import socket
import subprocess
import time
from typing import List, Tuple

from config.settings import TOR_CONTROL_PORT, TOR_SOCKS_PORT

logger = logging.getLogger(__name__)


class TorServiceManager:
    """Steuert den Systemd/Service-Dienst von Tor und löst Port-Konflikte automatisch."""

    SERVICE_NAME = "tor@default"

    def _run_cmd(self, cmd: List[str]) -> Tuple[bool, str]:
        """Führt ein System-Kommando sicher aus."""
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, res.stdout.strip()
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() or e.stdout.strip()
            return False, err
        except Exception as e:
            return False, str(e)

    def _is_port_in_use(self, port: int, host: str = "127.0.0.1") -> bool:
        """Prüft, ob ein spezifischer Port belegt ist."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    def cleanup_dangling_processes(self) -> None:
        """
        Beendet verwaiste Tor-Prozesse gestuft (SIGTERM -> SIGKILL),
        um Datenkorruption in RAM-Disk/Cache-Dateien zu vermeiden.
        """
        logger.info("Prüfe auf verwaiste Tor-Prozesse und gebe Ports frei...")

        # 1. Sanfter Versuch via SIGTERM (15)
        subprocess.run(["pkill", "-15", "-u", "debian-tor"], capture_output=True, check=False)
        subprocess.run(["pkill", "-15", "-f", "tor -f"], capture_output=True, check=False)
        time.sleep(0.5)

        # 2. Hartes Aufräumen via SIGKILL (9) nur bei weiterhin belegten Ports
        if self._is_port_in_use(TOR_SOCKS_PORT) or self._is_port_in_use(TOR_CONTROL_PORT):
            logger.warning("[!] Tor-Ports noch belegt. Erzwinge Prozessende (SIGKILL)...")
            subprocess.run(["pkill", "-9", "-u", "debian-tor"], capture_output=True, check=False)
            subprocess.run(["pkill", "-9", "-f", "tor -f"], capture_output=True, check=False)
            time.sleep(0.5)

    def ensure_service_running(self) -> bool:
        """
        Stoppt den System-Tor-Dienst (tor@default) und räumt verwaiste Tor-Prozesse ab,
        damit die Suite ihren eigenen, direkt gestarteten Tor (RAM-Disk-torrc) betreiben kann.
        Inklusive Service-Fallback für WSL-Umgebungen ohne Systemd.
        """
        logger.info(f"Stoppe System-Tor-Instanz ({self.SERVICE_NAME})...")

        # 1. Stopp-Versuch via systemctl
        success, err = self._run_cmd(["systemctl", "stop", self.SERVICE_NAME])
        
        # Fallback für WSL2 ohne PID-1-Systemd
        if not success and "systemd" in err.lower():
            logger.debug("[*] Systemd nicht aktiv. Versuche Fallback via 'service tor stop'...")
            self._run_cmd(["service", "tor", "stop"])

        # 2. Altlasten/Zombies gestuft beenden
        self.cleanup_dangling_processes()

        # 3. Verifikation der Port-Freigabe
        if self._is_port_in_use(TOR_SOCKS_PORT) or self._is_port_in_use(TOR_CONTROL_PORT):
            logger.error("[-] Fehler: Tor-Ports (9050/9051) sind trotz Cleanup weiterhin blockiert!")
            return False

        logger.info("[+] System-Tor gestoppt – Ports frei für den Suite-eigenen Tor (RAM-Disk).")
        return True

    def stop_service(self) -> bool:
        """Stoppt die System-Tor-Instanz und wahllose Tor-Prozesse sauber."""
        logger.info(f"Stoppe {self.SERVICE_NAME}...")
        
        success, _ = self._run_cmd(["systemctl", "stop", self.SERVICE_NAME])
        if not success:
            self._run_cmd(["service", "tor", "stop"])

        self.cleanup_dangling_processes()
        logger.info(f"[+] {self.SERVICE_NAME} sauber beendet.")
        return True


if __name__ == "__main__":
    # Einzeltest des Moduls
    logging.basicConfig(level=logging.INFO)
    service_mgr = TorServiceManager()
    if service_mgr.ensure_service_running():
        print("[+] TorServiceManager Test erfolgreich: Ports sind frei.")