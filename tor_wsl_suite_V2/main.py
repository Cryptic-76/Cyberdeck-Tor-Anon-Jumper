"""
Cyberdeck Tor Suite - Main Application Entry Point
Orchestriert den gesamten Lebenszyklus: Auto-Root, Checks, RAM-Disk, Tor, Privoxy, Windows-Proxy, DNS-Lock, nftables Kill-Switch und Cleanup.
"""

import logging
import os
import signal
import sys
import threading
import time

from config import (
    IP_ROTATION_INTERVAL_SEC,
    LOG_DIR,
    LOG_FILE,
    PRIVOXY_PORT,
    TOR_OR_PORT,
)
from core import (
    PrivoxyManager,
    RAMDiskManager,
    SecurityManager,
    SystemChecker,
    TorManager,
    TorServiceManager,
    WindowsProxyManager,
)

# Logging-Setup (Ausgabe auf Konsole und in Log-Datei)
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# stem loggt beim Polling des ControlPorts störend zur INFO-Stufe (SocketClosed u.ä.)
logging.getLogger("stem").setLevel(logging.WARNING)


def ensure_root() -> None:
    """Prüft auf Root-Rechte unter Linux/WSL und startet das Skript ggf. automatisch mit sudo neu."""
    if os.name != "posix":
        return  # Unter reinem Windows bricht das hier ab (läuft via WSL)

    if os.geteuid() != 0:
        logger.warning("[!] Skript läuft nicht als Root. Eskaliere Privilegien via sudo...")
        try:
            # Ersetzt den aktuellen Prozess durch 'sudo [aktueller_python_interpreter] [skript] [argumente]'
            os.execvp("sudo", ["sudo", sys.executable] + sys.argv)
        except Exception as e:
            print(f"[-] Kritischer Fehler bei der sudo-Eskalation: {e}", file=sys.stderr)
            sys.exit(1)


class TorSuiteOrchestrator:
    """Zentrale Steuerungsklasse für alle Module der Tor Suite."""

    def __init__(self) -> None:
        self.system_checker = SystemChecker()
        self.ramdisk_mgr = RAMDiskManager()
        self.tor_service_mgr = TorServiceManager()
        self.tor_mgr = TorManager()
        self.privoxy_mgr = PrivoxyManager()
        self.win_proxy_mgr = WindowsProxyManager()
        self.sec_mgr = SecurityManager()
        self.is_running = False
        self._shutdown_event = threading.Event()
        self._cleanup_done = False

    def start(self) -> bool:
        """Startet alle Komponenten in der korrekten Reihenfolge."""
        print("==================================================================")
        print("         CYBERDECK TOR SUITE (WSL2 / RAM-DISK EDITION)          ")
        print("==================================================================\n")

        # 0. Stale-State abräumen
        logger.info("[Vorbereitung] Entferne ggf. übrig gebliebenen Windows-Systemproxy (Stale-State)...")
        try:
            self.win_proxy_mgr.disable_proxy()
        except Exception as e:
            logger.warning(f"[!] Stale-State Cleanup Warnung: {e}")

        # 1. System- und Rechteprüfung
        logger.info("[Eingabe] Prüfe Systemvoraussetzungen...")
        ok, errors = self.system_checker.run_all_checks()
        if not ok:
            for err in errors:
                logger.error(f"  - {err}")
            return False

        wsl_ip = self.system_checker.get_wsl_ip()
        logger.info(f"[+] Systemcheck erfolgreich. WSL-IP ermittelt: {wsl_ip}")

        # 2. RAM-Disk (tmpfs 256MB) vorbereiten
        logger.info("[Verarbeitung] Initialisiere 256MB RAM-Disk (tmpfs)...")
        if not self.ramdisk_mgr.setup():
            return False

        # 3. Tor- und Privoxy-Dateien generieren
        logger.info("[Verarbeitung] Erzeuge dynamische Konfigurationsdateien in der RAM-Disk...")
        if not self.tor_mgr.generate_torrc() or not self.privoxy_mgr.generate_config():
            return False

        # 4. POSIX-Dateirechte härten (0700 / 0600)
        logger.info("[Verarbeitung] Wende strikte POSIX-Sicherheitsrechte an...")
        self.sec_mgr.enforce_file_permissions()

        # 5. Windows Firewall-Regeln anlegen
        logger.info("[Verarbeitung] Konfiguriere Windows Defender Firewall-Regeln...")
        self.sec_mgr.setup_firewall_rules()

        # 6. Alt-Prozesse bereinigen & Tor-Dienst über Service Manager sicherstellen
        logger.info("[Verarbeitung] Bereinige verwaiste Tor-Prozesse und aktiviere Tor-Dienst...")
        if not self.tor_service_mgr.ensure_service_running():
            self.shutdown()
            return False

        # 7. Tor-Dienst starten und auf 100% Bootstrap warten
        logger.info("[Verarbeitung] Starte Tor-Dienst und Stealth-Relay (warte auf Bootstrap 100%)...")
        if not self.tor_mgr.start_tor():
            self.shutdown()
            return False

        # 8. DNS-Leak-Schutz, DNS-Redirect (53->5353) & nftables Kill-Switch aktivieren
        logger.info("[Verarbeitung] Tor bootstrapped (100%) – aktiviere DNS-Leak-Schutz & Kill-Switch...")
        self.sec_mgr.apply_tor_dns()
        self.sec_mgr.setup_dns_redirect()
        self.sec_mgr.setup_nftables_killswitch()

        # 9. Privoxy-Dienst starten
        logger.info("[Verarbeitung] Starte gehärteten Privoxy-Proxy...")
        if not self.privoxy_mgr.start_privoxy():
            self.shutdown()
            return False

        # 10. Windows System-Proxy aktivieren
        logger.info("[Ausgabe] Aktiviere Windows-Systemproxy...")
        if not self.win_proxy_mgr.enable_proxy(target_ip=wsl_ip):
            logger.warning("[!] Systemproxy konnte nicht gesetzt werden, Dienste laufen jedoch weiter.")

        self.is_running = True
        print("\n==================================================================")
        logger.info("[SUCCESS] Tor Suite ist aktiv!")
        logger.info(f" - Privoxy Proxy: {wsl_ip}:{PRIVOXY_PORT}")
        logger.info(f" - Tor Relay ORPort: {TOR_OR_PORT}")
        logger.info(f" - IP-Rotation: Alle {IP_ROTATION_INTERVAL_SEC} Sekunden")
        logger.info(" - Spurenschutz: Aktive 256MB RAM-Disk (tmpfs) + nftables Kill-Switch")
        print("==================================================================")
        print("Drücke CTRL+C zum Beenden und sauberen Aufräumen.\n")

        return True

    def check_health(self) -> bool:
        """Prüft im laufenden Betrieb, ob alle Unterdienste noch aktiv sind."""
        if not self.is_running:
            return True
        
        # Prüfe Tor (Fallback, falls is_alive() nicht deklariert ist)
        tor_alive = getattr(self.tor_mgr, "is_alive", lambda: getattr(self.tor_mgr, "process", None) and self.tor_mgr.process.poll() is None)()
        if not tor_alive:
            logger.error("[-] Health-Check fehlgeschlagen: Tor-Prozess ist nicht mehr aktiv!")
            return False

        # Prüfe Privoxy (Fallback, falls is_alive() nicht deklariert ist)
        privoxy_alive = getattr(self.privoxy_mgr, "is_alive", lambda: getattr(self.privoxy_mgr, "process", None) and self.privoxy_mgr.process.poll() is None)()
        if not privoxy_alive:
            logger.error("[-] Health-Check fehlgeschlagen: Privoxy-Prozess ist nicht mehr aktiv!")
            return False

        return True

    def shutdown(self, signum=None, frame=None) -> None:
        """
        Führt einen geordneten, spurenfreien Shutdown durch.
        Jeder Teilschritt ist isoliert, damit Abstürze in einzelnen Subsystemen
        niemals verwaiste Firewall- oder DNS-Regeln hinterlassen.
        """
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self.is_running = False
        self._shutdown_event.set()

        print("\n")
        logger.info("[Cleanup] Fahre Cyberdeck Tor Suite herunter...")

        # 1. Windows Proxy zuerst entfernen
        try:
            self.win_proxy_mgr.disable_proxy()
        except Exception as e:
            logger.error(f"[-] Fehler beim Deaktivieren des Windows-Proxys: {e}")

        # 2. Aktive Netzwerkdienste stoppen
        try:
            self.privoxy_mgr.stop_privoxy()
        except Exception as e:
            logger.error(f"[-] Fehler beim Stoppen von Privoxy: {e}")

        try:
            self.tor_mgr.stop_tor()
            self.tor_service_mgr.stop_service()
        except Exception as e:
            logger.error(f"[-] Fehler beim Stoppen von Tor: {e}")

        # 3. Sicherheitsfilter, DNS & Firewall zurücksetzen
        try:
            self.sec_mgr.remove_firewall_rules()
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen der Firewall-Regeln: {e}")

        try:
            self.sec_mgr.remove_dns_redirect()
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen des DNS-Redirects: {e}")

        try:
            self.sec_mgr.remove_nftables_killswitch()
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen des nftables Kill-Switches: {e}")

        try:
            self.sec_mgr.restore_dns()
        except Exception as e:
            logger.error(f"[-] Fehler beim Wiederherstellen der DNS-Konfiguration: {e}")

        # 4. RAM-Disk und Spuren vernichten
        try:
            self.ramdisk_mgr.cleanup()
        except Exception as e:
            logger.error(f"[-] Fehler beim Cleanup der RAM-Disk: {e}")

        logger.info("[+] Shutdown abgeschlossen. Sämtliche temporären Daten wurden aus dem RAM gelöscht.")
        sys.exit(0)


def main() -> None:
    ensure_root()

    orchestrator = TorSuiteOrchestrator()

    # Signals registrieren
    signal.signal(signal.SIGINT, orchestrator.shutdown)
    signal.signal(signal.SIGTERM, orchestrator.shutdown)

    if orchestrator.start():
        try:
            while not orchestrator._shutdown_event.is_set():
                if not orchestrator.check_health():
                    logger.critical("[!] Ausfall erkannt! Starte Notfall-Shutdown...")
                    orchestrator.shutdown()
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            orchestrator.shutdown()


if __name__ == "__main__":
    main()