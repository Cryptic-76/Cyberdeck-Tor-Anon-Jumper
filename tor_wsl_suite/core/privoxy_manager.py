"""
Cyberdeck Tor Suite - Privoxy Manager
Generiert die gehärtete Privoxy-Config in der RAM-Disk und steuert den Privoxy-Prozess.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from config.settings import (
    GENERATED_PRIVOXY_CONF,
    LOG_DIR,
    PRIVOXY_ACTION_TEMPLATE,
    PRIVOXY_HOST,
    PRIVOXY_PORT,
    PRIVOXY_TEMPLATE,
    RAMDISK_MOUNT_POINT,
    TOR_SOCKS_HOST,
    TOR_SOCKS_PORT,
)

logger = logging.getLogger(__name__)


class PrivoxyManager:
    """Verwaltet die Erstellung der gehärteten Privoxy-Konfiguration und deren Prozess lifecycle."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None

    def generate_config(self) -> bool:
        """Liest das Privoxy-Template und schreibt die gehärtete Config in die RAM-Disk."""
        try:
            template_path = Path(PRIVOXY_TEMPLATE)
            if not template_path.exists():
                logger.error(f"[-] Privoxy Template nicht gefunden: {template_path}")
                return False

            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            # Ersetze Variablen im Template
            conf_content = template_content.format(
                privoxy_host=PRIVOXY_HOST,
                privoxy_port=PRIVOXY_PORT,
                socks_host=TOR_SOCKS_HOST,
                socks_port=TOR_SOCKS_PORT,
                data_directory=RAMDISK_MOUNT_POINT,
            )

            # Pfad-Existenz in der RAM-Disk vor dem Schreiben garantieren
            target_path = Path(GENERATED_PRIVOXY_CONF)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(conf_content)

            # Echtes Härtungs-Set (user.action) ebenfalls in die RAM-Disk schreiben –
            # privoxy.conf referenziert es über die actionsfile-Direktive.
            action_src = Path(PRIVOXY_ACTION_TEMPLATE)
            if not action_src.exists():
                logger.error(f"[-] Actions-Template nicht gefunden: {action_src}")
                return False
            action_target = Path(RAMDISK_MOUNT_POINT) / "user.action"
            action_target.parent.mkdir(parents=True, exist_ok=True)
            action_target.write_text(action_src.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info(f"[+] Privoxy user.action (Härtung) in RAM-Disk erzeugt: {action_target}")

            logger.info(f"[+] Gehärtete Privoxy-Config in RAM-Disk erzeugt: {target_path}")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Generieren der Privoxy-Config: {e}")
            return False

    def start_privoxy(self) -> bool:
        """
        Startet Privoxy als direkten Prozess mit der generierten, gehärteten Config aus der
        RAM-Disk. Der systemd-Dienst 'privoxy.service' liest auf Debian/Kali die
        System-Config '/etc/privoxy/config' statt unserer gehärteten Config – daher wird er
        hier bewusst NICHT genutzt (analog zur Tor-Behandlung).
        """
        if not self.generate_config():
            return False

        try:
            logger.info("Starte Privoxy als direkten Prozess mit RAM-Disk-Config...")
            cmd = ["privoxy", "--no-daemon", GENERATED_PRIVOXY_CONF]

            log_path = Path(LOG_DIR) / "privoxy_direct.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._privoxy_log_handle = open(log_path, "w", encoding="utf-8")

            self.process = subprocess.Popen(
                cmd,
                stdout=self._privoxy_log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

            time.sleep(1.5)

            if self.process.poll() is not None:
                logger.error("[-] Privoxy-Prozess ist abgebrochen. Letzte Log-Zeilen:")
                try:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    for line in lines[-10:]:
                        logger.error(f"    {line}")
                except Exception:
                    pass
                return False

            logger.info(f"[+] Privoxy erfolgreich gestartet (Hört auf {PRIVOXY_HOST}:{PRIVOXY_PORT}).")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim direkten Starten von Privoxy: {e}")
            return False

    def stop_privoxy(self) -> None:
        """Stoppt den Privoxy-Prozess sauber."""
        logger.info("Stoppe Privoxy-Dienst...")

        # Direkten Subprozess beenden (falls vorhanden)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        # Log-Datei-Handle schließen
        if getattr(self, "_privoxy_log_handle", None) is not None:
            try:
                self._privoxy_log_handle.close()
            except Exception:
                pass

        logger.info("[+] Privoxy sauber beendet.")


if __name__ == "__main__":
    # Einzeltest des Moduls
    logging.basicConfig(level=logging.INFO)
    privoxy = PrivoxyManager()
    if privoxy.generate_config():
        print("[+] Privoxy-Config Generierung erfolgreich.")