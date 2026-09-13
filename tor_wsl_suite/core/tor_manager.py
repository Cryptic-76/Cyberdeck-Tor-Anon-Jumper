"""
Cyberdeck Tor Suite - Tor Process & ControlPort Manager
Generiert die torrc in der RAM-Disk, steuert den Tor-Dienst und rotiert minütlich die Exit-IP.
"""

import logging
import os
import pwd
import grp
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from stem.control import Controller

from config.settings import (
    EUROPEAN_EXIT_NODES,
    GENERATED_TORRC,
    get_control_password_hashed,
    get_control_password_raw,
    IP_ROTATION_INTERVAL_SEC,
    LOG_DIR,
    TOR_CONTROL_PORT,
    TOR_DATA_DIR,
    TOR_DNS_PORT,
    TOR_OR_PORT,
    TOR_RELAY_NICKNAME,
    TOR_SOCKS_HOST,
    TOR_SOCKS_PORT,
    TORRC_TEMPLATE,
    WSL_IP_RANGE,
)

logger = logging.getLogger(__name__)


class TorManager:
    """Verwaltet den Tor-Prozess und die IP-Rotations-Logik via ControlPort."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.rotation_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def _ensure_permissions(self, path: Path, is_directory: bool = False) -> None:
        """Setzt erforderliche POSIX-Rechte und weist den Besitz dem Tor-Systemuser zu."""
        try:
            # Rechteregel: 0700 für Verzeichnisse, 0600 für Konfigurationsdateien
            mode = 0o700 if is_directory else 0o600
            os.chmod(path, mode)

            # Prüfen, ob der System-User 'debian-tor' oder 'tor' auf dem System existiert
            tor_user = None
            for username in ["debian-tor", "tor"]:
                try:
                    pwd.getpwnam(username)
                    tor_user = username
                    break
                except KeyError:
                    continue

            if tor_user:
                shutil.chown(path, user=tor_user, group=tor_user)
        except Exception as e:
            logger.debug(f"[*] Hinweis bei Rechtevergabe für {path}: {e}")

    def generate_torrc(self) -> bool:
        """Liest das torrc.template und injiziert dynamische Pfade, Passwörter und Ports."""
        try:
            template_path = Path(TORRC_TEMPLATE)
            if not template_path.exists():
                logger.error(f"[-] Template-Datei nicht gefunden: {template_path}")
                return False

            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            # Datendir in RAM-Disk garantieren und berechtigen
            data_dir_path = Path(TOR_DATA_DIR)
            data_dir_path.mkdir(parents=True, exist_ok=True)
            self._ensure_permissions(data_dir_path, is_directory=True)

            # Platzhalter im Template ersetzen
            torrc_content = template_content.format(
                data_directory=TOR_DATA_DIR,
                socks_host=TOR_SOCKS_HOST,
                socks_port=TOR_SOCKS_PORT,
                wsl_ip_range=WSL_IP_RANGE,
                dns_port=TOR_DNS_PORT,
                control_port=TOR_CONTROL_PORT,
                hashed_control_password=get_control_password_hashed(),
                or_port=TOR_OR_PORT,
                public_ip_or_auto="auto",
                relay_nickname=TOR_RELAY_NICKNAME,
                european_exit_nodes=EUROPEAN_EXIT_NODES,
            )

            # In die RAM-Disk schreiben
            target_path = Path(GENERATED_TORRC)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(torrc_content)

            self._ensure_permissions(target_path, is_directory=False)

            logger.info(f"[+] Dynamische torrc erfolgreich in RAM-Disk erzeugt: {target_path}")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Generieren der torrc: {e}")
            return False

    def start_tor(self) -> bool:
        """
        Startet Tor als direkten Subprozess mit der in der RAM-Disk erzeugten, gehärteten
        torrc und wartet via stem auf den vollständigen Bootstrap (100%).

        Hintergrund: Debian/Kali betreiben Tor als systemd-Instanz `tor@default`, die eine
        unix ControlSocket (kein TCP-ControlPort) nutzt und NICHT die generierte torrc liest.
        Der `tor.service`-Unit ist dort zudem nur ein No-Op (`/bin/true`). Daher wird Tor hier
        bewusst direkt gestartet – so bindet die Suite ihren eigenen Tor mit ControlPort 9051
        (IP-Rotation via NEWNYM) und dem RAM-Disk-DataDirectory.
        """
        if not self.generate_torrc():
            return False

        # Tor direkt als Subprozess starten. 'User debian-tor' in der torrc sorgt dafür,
        # dass Tor nach dem Konfig-Lesen selbst auf den Tor-Systemuser downgradet.
        try:
            log_path = Path(LOG_DIR) / "tor_direct.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._tor_log_handle = open(log_path, "w", encoding="utf-8")

            logger.info(f"Starte Tor als direkten Prozess: tor -f {GENERATED_TORRC}")
            self.process = subprocess.Popen(
                ["tor", "-f", str(GENERATED_TORRC)],
                stdout=self._tor_log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as e:
            logger.error(f"[-] Direkter Tor-Start fehlgeschlagen: {e}")
            return False

        # Kurz warten, damit ein sofortiger Konfig-Fehler sichtbar wird (statt 60s Timeout).
        time.sleep(2)
        if self.process.poll() is not None:
            logger.error("[-] Tor-Prozess ist sofort abgebrochen. Letzte Log-Zeilen:")
            self._dump_tor_log(tail=15)
            return False

        # Warten auf erfolgreichen Bootstrap via stem ControlPort
        logger.info("Warte auf Tor-Bootstrap (kann bei europäischen Exit-Nodes einen Moment dauern)...")
        start_time = time.time()
        # 120s, da StrictNodes/Europa-Pfade den Bootstrap realistisch bis ~40-60s kosten können
        max_wait = 120  # Maximal 120 Sekunden warten

        while time.time() - start_time < max_wait:
            try:
                with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
                    controller.authenticate(password=get_control_password_raw())

                    # Prüfe aktuellen Bootstrap-Status
                    status = controller.get_info("status/bootstrap-phase")
                    if "PROGRESS=100" in status:
                        logger.info("[+] Tor erfolgreich gestartet und zu 100% bootstrapped.")

                        # Starte automatische IP-Rotation im Hintergrund
                        self.stop_event.clear()
                        self.rotation_thread = threading.Thread(target=self._ip_rotation_loop, daemon=True)
                        self.rotation_thread.start()
                        return True
            except Exception:
                # Tor baut den ControlPort auf oder ist noch im Bootstrap
                pass

            time.sleep(1)

        logger.error("[-] Timeout beim Tor-Bootstrap erreicht.")
        self._dump_tor_log(tail=10)
        return False

    def _dump_tor_log(self, tail: int) -> None:
        """Gibt die letzten Zeilen des direkten Tor-Logs für die Diagnose aus."""
        try:
            log_path = Path(LOG_DIR) / "tor_direct.log"
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-tail:]:
                    logger.error(f"    {line}")
        except Exception:
            pass

    def send_newnym(self) -> bool:
        """Sendet das SIGNAL NEWNYM an den Tor ControlPort zur Erzwingung einer neuen Exit-IP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((TOR_SOCKS_HOST, TOR_CONTROL_PORT))

                # Authentifizierung am ControlPort
                auth_cmd = f'AUTHENTICATE "{get_control_password_raw()}"\r\n'
                s.sendall(auth_cmd.encode("utf-8"))
                response = s.recv(1024).decode("utf-8")

                if not response.startswith("250"):
                    logger.error(f"[-] ControlPort Authentifizierung fehlgeschlagen: {response.strip()}")
                    return False

                # Signal NEWNYM senden
                s.sendall(b"SIGNAL NEWNYM\r\n")
                response = s.recv(1024).decode("utf-8")

                if response.startswith("250"):
                    logger.info("[+] Signal NEWNYM gesendet: Tor Exit-IP gewechselt.")
                    return True
                else:
                    logger.error(f"[-] Signal NEWNYM abgelehnt: {response.strip()}")
                    return False

        except Exception as e:
            logger.error(f"[-] Fehler beim Verbinden mit ControlPort ({TOR_CONTROL_PORT}): {e}")
            return False

    def _ip_rotation_loop(self) -> None:
        """Schleife für das automatische IP-Rotations-Intervall (läuft im Hintergrund)."""
        logger.info(f"[*] IP-Changer gestartet (Rotation alle {IP_ROTATION_INTERVAL_SEC} Sekunden).")
        while not self.stop_event.is_set():
            for _ in range(IP_ROTATION_INTERVAL_SEC):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

            if not self.stop_event.is_set():
                self.send_newnym()

    def stop_tor(self) -> None:
        """Stoppt den IP-Changer-Thread und beendet den Tor-Prozess sauber."""
        logger.info("Stoppe Tor-Prozess und IP-Changer...")
        self.stop_event.set()

        # System-Tor-Instanz stoppen (frei von Port-Konflikten, falls noch aktiv)
        subprocess.run(["systemctl", "stop", "tor@default"], capture_output=True, check=False)

        # Direkten Suite-Tor-Subprozess beenden
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        # Log-Datei-Handle schließen
        if getattr(self, "_tor_log_handle", None) is not None:
            try:
                self._tor_log_handle.close()
            except Exception:
                pass

        logger.info("[+] Tor-Prozess sauber beendet.")


if __name__ == "__main__":
    # Einzeltest des Moduls
    logging.basicConfig(level=logging.INFO)
    tor = TorManager()
    if tor.generate_torrc():
        print("[+] torrc-Generierung erfolgreich.")