"""
Cyberdeck Tor Suite - Main Application Entry Point
Orchestriert den gesamten Lebenszyklus: Auto-Root, Checks, RAM-Disk, Tor, Privoxy, Windows-Proxy, DNS-Lock, nftables Kill-Switch und Cleanup.
"""

import logging
import os
import signal
import sys
import time
from typing import NoReturn

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

# stem logt beim Polling des ControlPorts störend zur INFO-Stufe (SocketClosed u.ä.)
logging.getLogger("stem").setLevel(logging.WARNING)


def ensure_root() -> None:
    """Prüft auf Root-Rechte unter Linux/WSL und startet das Skript ggf. automatisch mit sudo neu."""
    if os.name != "posix":
        return  # Unter reinem Windows bricht das hier ab (läuft ja via WSL)

    if os.geteuid() != 0:
        logger.warning("[!] Skript läuft nicht als Root. Eskaliere Privilegien via sudo...")
        try:
            # Ersetzt den aktuellen Prozess durch 'sudo python3 [skript] [argumente]'
            os.execvp("sudo", ["sudo", "python3"] + sys.argv)
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

    def start(self) -> bool:
        """Startet alle Komponenten in der korrekten Reihenfolge."""
        print("==================================================================")
        print("         CYBERDECK TOR SUITE (WSL2 / RAM-DISK EDITION)          ")
        print("==================================================================\n")

        # 0. Stale-State abräumen: Wenn eine vorherige Sitzung unsauber endete (WSL-/Windows-
        #    Absturz), bleibt der Windows-Systemproxy in der Registry aktiv, obwohl weder Tor
        #    noch Privoxy laufen. Erst deaktivieren, damit der Browser nicht auf eine tote
        #    Kette zeigt, bis Tor bootstrapped ist – gesetzt wird er erst in Schritt 9.
        logger.info("[Vorbereitung] Entferne ggf. übrig gebliebenen Windows-Systemproxy (Stale-State)...")
        self.win_proxy_mgr.disable_proxy()

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

        # 7. Tor-Dienst starten und auf 100% Bootstrap warten.
        #    Der Windows-Systemproxy wird erst NACH diesem Schritt aktiviert – so muss der
        #    Browser nie durch eine noch nicht stehende Kette laufen (Root-Cause-Fix).
        logger.info("[Verarbeitung] Starte Tor-Dienst und Stealth-Relay (warte auf Bootstrap 100%)...")
        if not self.tor_mgr.start_tor():
            self.shutdown()
            return False

        # 8. ERST NACH erfolgreichem Tor-Bootstrap: DNS-Leak-Schutz, DNS-Redirect (53->5353)
        #    & nftables Kill-Switch aktivieren. Vorher umzuverdrahten würde den Egress schon
        #    kappen, solange Tor noch bootstrapped (Root-Cause-Fix).
        logger.info("[Verarbeitung] Tor bootstrapped (100%) – aktiviere DNS-Leak-Schutz & Kill-Switch...")
        self.sec_mgr.apply_tor_dns()
        self.sec_mgr.setup_dns_redirect()
        self.sec_mgr.setup_nftables_killswitch()

        # 9. Privoxy-Dienst starten (sieht jetzt die bereite Tor-SOCKS 9050)
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

    def shutdown(self, signum=None, frame=None) -> None:
        """
        Führt einen geordneten, spurenfreien Shutdown durch.
        Läuft auch dann vollständig, wenn der Start fehlgeschlagen ist (is_running=False),
        damit nie Firewall-/DNS-/Kill-Switch-Reste zurückbleiben.
        """
        if getattr(self, "_cleanup_done", False):
            return
        self._cleanup_done = True

        print("\n")
        logger.info("[Cleanup] Fahre Cyberdeck Tor Suite herunter...")

        # 1. Windows Systemproxy deaktivieren
        self.win_proxy_mgr.disable_proxy()

        # 2. Windows Firewall-Regeln & nftables/DNS-Redirect/Kill-Switch + resolv.conf wiederherstellen
        self.sec_mgr.remove_firewall_rules()
        self.sec_mgr.remove_dns_redirect()
        self.sec_mgr.remove_nftables_killswitch()
        self.sec_mgr.restore_dns()

        # 3. Privoxy stoppen
        self.privoxy_mgr.stop_privoxy()

        # 4. Tor stoppen & Service beenden
        self.tor_mgr.stop_tor()
        self.tor_service_mgr.stop_service()

        # 5. RAM-Disk unmounten und Spuren vernichten
        self.ramdisk_mgr.cleanup()

        logger.info("[+] Shutdown abgeschlossen. Sämtliche temporären Daten wurden aus dem RAM gelöscht.")
        self.is_running = False
        sys.exit(0)


def main() -> None:
    # Vor dem Start prüfen ob Root-Rechte da sind (Auto-Sudo)
    ensure_root()

    orchestrator = TorSuiteOrchestrator()

    # Signal-Handler für sauberes CTRL+C (Graceful Shutdown)
    signal.signal(signal.SIGINT, orchestrator.shutdown)
    signal.signal(signal.SIGTERM, orchestrator.shutdown)

    if orchestrator.start():
        # Hauptschleife zum Offenhalten des Prozesses
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            orchestrator.shutdown()


if __name__ == "__main__":
    main()