"""
Cyberdeck Tor Suite - RAM-Disk Manager (tmpfs)
Erstellt und verwaltet den flüchtigen Speicher im RAM für Tor- und Privoxy-Daten.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

# Nur existierende Variablen aus settings importieren
from config.settings import (
    RAMDISK_MOUNT_POINT,
    RAMDISK_SIZE_MB,
    TOR_DATA_DIR,
)

logger = logging.getLogger(__name__)


class RAMDiskManager:
    """Sorgt für die Bereitstellung und das sichere Löschen der RAM-Disk (tmpfs)."""

    def __init__(self, mount_point: str = RAMDISK_MOUNT_POINT, size_mb: int = RAMDISK_SIZE_MB) -> None:
        self.mount_point = Path(mount_point)
        self.size_mb = size_mb

    def is_mounted(self) -> bool:
        """Prüft, ob der Mount-Point bereits als tmpfs eingebunden ist."""
        if not self.mount_point.exists():
            return False
        try:
            with open("/proc/mounts", "r", encoding="utf-8") as f:
                mounts = f.read()
                return str(self.mount_point) in mounts
        except Exception as e:
            logger.error(f"Fehler beim Lesen von /proc/mounts: {e}")
            return False

    def setup(self) -> bool:
        """Erstellt den Mount-Point und bindet die RAM-Disk ein."""
        try:
            self.mount_point.mkdir(parents=True, exist_ok=True)

            if not self.is_mounted():
                logger.info(f"Mounte {self.size_mb}MB tmpfs auf {self.mount_point}...")
                cmd = [
                    "mount",
                    "-t", "tmpfs",
                    "-o", f"size={self.size_mb}M,mode=0755",
                    "tmpfs",
                    str(self.mount_point)
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                logger.info("[+] RAM-Disk erfolgreich gemountet.")
            else:
                logger.info("[*] RAM-Disk ist bereits gemountet.")

            # 1. Unterverzeichnis für Tor erzeugen (0700 Rechte)
            tor_dir = Path(TOR_DATA_DIR)
            tor_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(tor_dir, 0o700)

            # 2. Unterverzeichnis für Privoxy dynamisch im Mountpoint erzeugen (0755 Rechte)
            privoxy_dir = self.mount_point / "privoxy"
            privoxy_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(privoxy_dir, 0o755)

            logger.info(f"[+] Unterstrukturen für Tor ({tor_dir}) und Privoxy ({privoxy_dir}) vorbereitet.")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[-] Fehler beim Mounten der RAM-Disk: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler beim RAM-Disk Setup: {e}")
            return False

    def cleanup(self) -> bool:
        """Unmountet die RAM-Disk und entfernt flüchtige Ordner spurlos."""
        if not self.is_mounted():
            logger.info("[*] RAM-Disk war nicht gemountet. Cleanup übersprungen.")
            return True

        try:
            logger.info(f"Unmounte RAM-Disk unter {self.mount_point}...")
            cmd = ["umount", "-f", str(self.mount_point)]
            subprocess.run(cmd, check=True, capture_output=True, text=True)

            if self.mount_point.exists():
                shutil.rmtree(self.mount_point, ignore_errors=True)

            logger.info("[+] RAM-Disk sauber unmountet und Spuren beseitigt.")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[-] Fehler beim Unmounten der RAM-Disk: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler beim RAM-Disk Cleanup: {e}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ramdisk = RAMDiskManager()
    if ramdisk.setup():
        print("[+] Setup-Test erfolgreich.")
        ramdisk.cleanup()
        print("[+] Cleanup-Test erfolgreich.")