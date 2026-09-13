"""
Cyberdeck Tor Suite - Tor Service Lifecycle Controller
Verwaltet das Aktivieren, Bereinigen und Starten des Tor-Systemd-Dienstes.
"""

import logging
import subprocess
import time
from typing import Tuple

logger = logging.getLogger(__name__)


class TorServiceManager:
    """Steuert den Systemd-Dienst von Tor und löst Port-Konflikte automatisch."""

    # Echte, laufende Tor-Instanz auf Debian/Kali (tor.service ist dort nur ein No-Op-Target)
    SERVICE_NAME = "tor@default"

    def _run_cmd(self, cmd: list) -> Tuple[bool, str]:
        """Führt ein System-Kommando sicher aus."""
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, res.stdout.strip()
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() or e.stdout.strip()
            return False, err
        except Exception as e:
            return False, str(e)

    def cleanup_dangling_processes(self) -> None:
        """Beendet verwaiste Tor-Prozesse, die Ports wie 9050/9051 blockieren könnten."""
        logger.info("Prüfe auf verwaiste Tor-Prozesse und gebe Ports frei...")
        subprocess.run(["pkill", "-9", "-u", "debian-tor"], capture_output=True)
        subprocess.run(["pkill", "-9", "tor"], capture_output=True)
        time.sleep(0.5)

    def ensure_service_running(self) -> bool:
        """
        Stoppt den System-Tor-Dienst (tor@default) und räumt verwaiste Tor-Prozesse ab,
        damit die Suite ihren eigenen, direkt gestarteten Tor (RAM-Disk-torrc) über
        Ports 9050/9051 ohne Konflikt betreiben kann.

        Hinweis: Der Unit 'tor.service' wird BEWUSST nicht mehr gestartet – er ist auf
        Debian/Kali nur ein systemd-Target-Ersatz (`ExecStart=/bin/true`) und startet
        keinen echten Tor-Prozess.
        """
        # 1. Echte System-Tor-Instanz sauber stoppen (kein Auto-Restart im laufenden Betrieb)
        logger.info(f"Stoppe System-Tor-Instanz ({self.SERVICE_NAME})...")
        self._run_cmd(["systemctl", "stop", self.SERVICE_NAME])

        # 2. Altlasten/Zombies beenden, um Port-Conflicts (9050/9051) zu vermeiden
        self.cleanup_dangling_processes()

        # 3. Kein zusätzlicher systemd-Dienst – die Suite startet Tor selbst.
        logger.info("[+] System-Tor gestoppt – Ports frei für den Suite-eigenen Tor (RAM-Disk).")
        return True

    def stop_service(self) -> bool:
        """Stoppt die System-Tor-Instanz und wahllose Tor-Prozesse sauber."""
        logger.info(f"Stoppe {self.SERVICE_NAME}...")
        self._run_cmd(["systemctl", "stop", self.SERVICE_NAME])
        self.cleanup_dangling_processes()
        logger.info(f"[+] {self.SERVICE_NAME} beendet.")
        return True