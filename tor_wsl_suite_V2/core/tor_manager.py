"""
Cyberdeck Tor Suite - Tor Process & ControlPort Manager
Generiert die torrc in der RAM-Disk, steuert den Tor-Dienst und rotiert minütlich die Exit-IP.
Gehärtet nach dem EVA-Prinzip mit Native-Stem-Integrität und Anti-Zombie-Management.
"""

import grp
import logging
import os
import pwd
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from stem import Signal
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
        self._tor_log_handle = None

    def _ensure_permissions(self, path: Path, is_directory: bool = False) -> None:
        """Setzt erforderliche POSIX-Rechte und weist den Besitz dem Tor-Systemuser zu."""
        try:
            mode = 0o700 if is_directory else 0o600
            os.chmod(path, mode)

            tor_user = None
            for username in ["debian-tor", "tor"]:
                try:
                    pwd.getpwnam(username)
                    tor_user = username
                    break
                except KeyError:
                    continue

            if tor_user:
                # Nutze pwd/grp um exakte UIDs/GIDs für chown zu garantieren
                user_info = pwd.getpwnam(tor_user)
                shutil.chown(path, user=user_info.pw_uid, group=user_info.pw_gid)
        except Exception as e:
            logger.debug(f"[*] Hinweis bei Rechtevergabe für {path}: {e}")

    def _cleanup_orphaned_ports(self) -> None:
        """Prüft und beendet alte verwaiste Tor-Prozesse auf den Zielports."""
        for port in [TOR_CONTROL_PORT, TOR_SOCKS_PORT]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((TOR_SOCKS_HOST, port)) == 0:
                        logger.warning(f"[!] Port {port} bereits belegt. Versuche alte Instanzen aufzuräumen...")
                        subprocess.run(["pkill", "-f", "tor -f"], capture_output=True, check=False)
                        time.sleep(1)
            except Exception:
                pass

    def generate_torrc(self) -> bool:
        """Liest das torrc.template und injiziert dynamische Pfade, Passwörter und Ports."""
        try:
            template_path = Path(TORRC_TEMPLATE)
            if not template_path.exists():
                logger.error(f"[-] Template-Datei nicht gefunden: {template_path}")
                return False

            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            data_dir_path = Path(TOR_DATA_DIR)
            data_dir_path.mkdir(parents=True, exist_ok=True)
            self._ensure_permissions(data_dir_path, is_directory=True)

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
        """Startet Tor als direkten Subprozess mit der generierten torrc."""
        self._cleanup_orphaned_ports()

        if not self.generate_torrc():
            return False

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

        time.sleep(2)
        if self.process.poll() is not None:
            logger.error("[-] Tor-Prozess ist sofort abgebrochen. Letzte Log-Zeilen:")
            self._dump_tor_log(tail=15)
            return False

        logger.info("Warte auf Tor-Bootstrap (kann bei europäischen Exit-Nodes einen Moment dauern)...")
        start_time = time.time()
        max_wait = 120

        while time.time() - start_time < max_wait:
            try:
                with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
                    controller.authenticate(password=get_control_password_raw())

                    status = controller.get_info("status/bootstrap-phase")
                    if "PROGRESS=100" in status:
                        logger.info("[+] Tor erfolgreich gestartet und zu 100% bootstrapped.")

                        self.stop_event.clear()
                        self.rotation_thread = threading.Thread(target=self._ip_rotation_loop, daemon=True)
                        self.rotation_thread.start()
                        return True
            except Exception:
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
        """Sendet SIGNAL NEWNYM via stem Controller (robuster gegen Rate-Limits)."""
        try:
            with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
                controller.authenticate(password=get_control_password_raw())
                
                if controller.is_newnym_available():
                    controller.signal(Signal.NEWNYM)
                    logger.info("[+] Signal NEWNYM gesendet: Tor Exit-IP gewechselt.")
                    return True
                else:
                    logger.warning("[!] Signal NEWNYM übersprungen (Tor Rate-Limit aktiv, erst in wenigen Sekunden verfügbar).")
                    return False
        except Exception as e:
            logger.error(f"[-] Fehler beim Senden von NEWNYM via ControlPort ({TOR_CONTROL_PORT}): {e}")
            return False

    def _ip_rotation_loop(self) -> None:
        """Schleife für das automatische IP-Rotations-Intervall."""
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

        if self.rotation_thread and self.rotation_thread.is_alive():
            self.rotation_thread.join(timeout=3)

        subprocess.run(["systemctl", "stop", "tor@default"], capture_output=True, check=False)

        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        if self._tor_log_handle is not None:
            try:
                self._tor_log_handle.close()
            except Exception:
                pass

        logger.info("[+] Tor-Prozess sauber beendet.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tor = TorManager()
    if tor.generate_torrc():
        print("[+] torrc-Generierung erfolgreich.")