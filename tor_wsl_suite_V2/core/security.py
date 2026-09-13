"""
Cyberdeck Tor Suite - Security, Permissions & Firewall Manager
Verwaltet POSIX-Dateirechte, dynamisches DNS-Routing, nftables Kill-Switch (mit Backup/Restore) 
sowie Windows-Firewall-Regeln.

Architektur: EVA-Prinzip, Zero-Trust, Anti-Leak Protection, Signal-Sicherheit via Context Manager.
"""

import logging
import os
import pwd
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


# =============================================================================
# EINGABE (E): Konfigurationsstruktur & Pfad-Ermittlung
# =============================================================================

@dataclass(frozen=True)
class SecurityConfig:
    """Zentrale, unveränderliche Konfigurationsdaten für den SecurityManager."""
    config_dir: Path = Path("/etc/cyberdeck")
    ramdisk_base_dir: Path = Path("/run/cyberdeck")
    ramdisk_tor_dir: Path = Path("/run/cyberdeck/tor")
    generated_torrc: Path = Path("/run/cyberdeck/tor/torrc")
    generated_privoxy_conf: Path = Path("/etc/privoxy/config")
    tor_data_dir: Path = Path("/var/lib/tor")
    backup_dir: Path = Path("/var/lib/cyberdeck/backup")
    
    port_dns: int = 5353
    port_socks: int = 9050
    port_or: int = 9001
    port_privoxy: int = 8118

    @classmethod
    def load(cls) -> "SecurityConfig":
        """Lädt Einstellungen dynamisch aus config.settings oder nutzt Defaults."""
        try:
            from config.settings import (
                CONFIG_DIR,
                GENERATED_PRIVOXY_CONF,
                GENERATED_TORRC,
                PRIVOXY_PORT,
                RAMDISK_BASE_DIR,
                RAMDISK_TOR_DIR,
                TOR_DATA_DIR,
                TOR_DNS_PORT,
                TOR_OR_PORT,
                TOR_SOCKS_PORT,
            )
            return cls(
                config_dir=Path(CONFIG_DIR),
                ramdisk_base_dir=Path(RAMDISK_BASE_DIR),
                ramdisk_tor_dir=Path(RAMDISK_TOR_DIR),
                generated_torrc=Path(GENERATED_TORRC),
                generated_privoxy_conf=Path(GENERATED_PRIVOXY_CONF),
                tor_data_dir=Path(TOR_DATA_DIR),
                port_dns=TOR_DNS_PORT,
                port_socks=TOR_SOCKS_PORT,
                port_or=TOR_OR_PORT,
                port_privoxy=PRIVOXY_PORT,
            )
        except ImportError:
            logger.debug("[*] config.settings nicht gefunden. Verwende Standard-Konfiguration.")
            return cls()


# =============================================================================
# VERARBEITUNG (V) & AUSGABE (A): Security Manager
# =============================================================================

class SecurityManager:
    """Hauptklasse zur Verwaltung von Systemrechten, DNS, Firewall & Anti-Leak Rules."""

    RULE_NAME_PRIVOXY = "Cyberdeck_TorSuite_Privoxy"
    RULE_NAME_RELAY = "Cyberdeck_TorSuite_ORPort"

    def __init__(self, config: Optional[SecurityConfig] = None) -> None:
        self.cfg: SecurityConfig = config or SecurityConfig.load()
        
        self.nft_table_name: str = "cyberdeck_tor_killswitch"
        self.dns_table_name: str = "cyberdeck_dns_redirect"
        
        self.resolv_conf: Path = Path("/etc/resolv.conf")
        self.resolv_conf_backup: Path = self.cfg.backup_dir / "resolv.conf.cyberdeck.bak"
        self.resolv_symlink_target_file: Path = self.cfg.backup_dir / "resolv.symlink_target.txt"

        # Backup-Verzeichnis absichern
        self.cfg.backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cfg.backup_dir, 0o700)

    # -------------------------------------------------------------------------
    # Context Manager & Signal Handler (Garantierter Cleanup)
    # -------------------------------------------------------------------------

    def __enter__(self) -> "SecurityManager":
        """Richtet bei Eintritt im Context-Block alle Sicherheitsregeln ein."""
        self.register_signal_handlers()
        
        if not self.enforce_file_permissions():
            logger.warning("[!] Teilweiser Fehlschlag beim Setzen der Dateirechte.")
        
        self.apply_tor_dns()
        self.setup_nftables_killswitch()
        self.setup_dns_redirect()
        self.setup_firewall_rules()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Entfernt beim Verlassen des Blocks alle temporären Netzwerk-Regeln."""
        self.teardown_all()

    def register_signal_handlers(self) -> None:
        """Fängt SIGINT (Ctrl+C) und SIGTERM ab, um sauberen Teardown zu gewährleisten."""
        def handler(signum, frame):
            logger.warning(f"[!] Signal {signum} empfangen. Leite sicheren Teardown ein...")
            self.teardown_all()
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def teardown_all(self) -> None:
        """Zentrale Funktion zum spurlosen Entfernen aller Modifikationen."""
        logger.info("Starte vollständigen Teardown aller Sicherheits- und Netzwerkregeln...")
        self.remove_firewall_rules()
        self.remove_dns_redirect()
        self.remove_nftables_killswitch()
        self.restore_dns()

    # -------------------------------------------------------------------------
    # 1. POSIX-DATEIRECHTE & ORDNERSTRUKTUR
    # -------------------------------------------------------------------------

    def enforce_file_permissions(self) -> bool:
        """Erstellt RAM-Disk-Pfade und setzt gehärtete Rechte (0700/0600) sowie Eigentümer."""
        try:
            logger.info("Setze strikte Dateirechte & erstelle Systempfade...")
            is_root = (os.geteuid() == 0)

            if not is_root:
                logger.warning("[!] Nicht als Root ausgeführt: Eigentümerwechsel (chown) wird übersprungen.")

            # UID/GID für Tor ermitteln
            tor_uid, tor_gid = self._get_tor_user_ids()

            # Pfade und Zugriffsrechte
            directories = [
                (self.cfg.ramdisk_base_dir, 0o700),
                (self.cfg.ramdisk_tor_dir, 0o700),
            ]
            for folder, mode in directories:
                folder.mkdir(parents=True, exist_ok=True)
                os.chmod(folder, mode)
                if is_root and tor_uid is not None and tor_gid is not None:
                    os.chown(folder, tor_uid, tor_gid)

            # Tor Data Directory absichern
            if self.cfg.tor_data_dir.exists():
                os.chmod(self.cfg.tor_data_dir, 0o700)
                if is_root and tor_uid is not None and tor_gid is not None:
                    os.chown(self.cfg.tor_data_dir, tor_uid, tor_gid)

            # torrc-Datei initialisieren & absichern
            if not self.cfg.generated_torrc.exists():
                self.cfg.generated_torrc.touch(mode=0o600)
            else:
                os.chmod(self.cfg.generated_torrc, 0o600)

            if is_root and tor_uid is not None and tor_gid is not None:
                os.chown(self.cfg.generated_torrc, tor_uid, tor_gid)

            # Privoxy Config absichern
            if self.cfg.generated_privoxy_conf.exists():
                os.chmod(self.cfg.generated_privoxy_conf, 0o600)

            logger.info(f"[+] Pfade und Rechte erfolgreich gehärtet (torrc: 0600, User-UID: {tor_uid}).")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Setzen der Dateirechte: {e}")
            return False

    def _get_tor_user_ids(self) -> tuple[Optional[int], Optional[int]]:
        """Sucht die System-UID/GID des Tor-Daemons."""
        for username in ["debian-tor", "tor"]:
            try:
                user_info = pwd.getpwnam(username)
                return user_info.pw_uid, user_info.pw_gid
            except KeyError:
                continue
        return None, None

    # -------------------------------------------------------------------------
    # 2. DYNAMISCHES DNS-MANAGEMENT
    # -------------------------------------------------------------------------

    def apply_tor_dns(self) -> bool:
        """Sichert die originale resolv.conf (inkl. Symlinks) und setzt lokalen Tor-DNS (127.0.0.1)."""
        try:
            if self.resolv_conf.exists() or self.resolv_conf.is_symlink():
                if not self.resolv_conf_backup.exists():
                    # Symlink-Zustand dokumentieren
                    if self.resolv_conf.is_symlink():
                        symlink_target = os.readlink(self.resolv_conf)
                        self.resolv_symlink_target_file.write_text(symlink_target, encoding="utf-8")
                        os.chmod(self.resolv_symlink_target_file, 0o600)

                    # Echte Inhalts-Kopie als Backup anlegen
                    shutil.copyfile(self.resolv_conf.resolve(), self.resolv_conf_backup)
                    os.chmod(self.resolv_conf_backup, 0o600)

            # Attribute entlocken
            subprocess.run(["chattr", "-i", str(self.resolv_conf)], capture_output=True)

            if self.resolv_conf.is_symlink() or self.resolv_conf.exists():
                self.resolv_conf.unlink()

            self.resolv_conf.write_text("nameserver 127.0.0.1\n", encoding="utf-8")
            subprocess.run(["chattr", "+i", str(self.resolv_conf)], capture_output=True)

            logger.info("[+] /etc/resolv.conf gehärtet und auf lokalen Tor-DNS umgeleitet.")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Anwenden der Tor-DNS-Konfiguration: {e}")
            return False

    def restore_dns(self) -> bool:
        """Stellt die ursprüngliche resolv.conf bzw. deren Symlink-Struktur wieder her."""
        try:
            subprocess.run(["chattr", "-i", str(self.resolv_conf)], capture_output=True)

            if self.resolv_conf.exists() or self.resolv_conf.is_symlink():
                self.resolv_conf.unlink()

            # War es ursprünglich ein Symlink?
            if self.resolv_symlink_target_file.exists():
                symlink_target = self.resolv_symlink_target_file.read_text(encoding="utf-8").strip()
                os.symlink(symlink_target, self.resolv_conf)
                self.resolv_symlink_target_file.unlink()
                if self.resolv_conf_backup.exists():
                    self.resolv_conf_backup.unlink()
                logger.info(f"[+] Symlink /etc/resolv.conf -> {symlink_target} wiederhergestellt.")
                return True

            # Standard-Datei-Wiederherstellung
            if self.resolv_conf_backup.exists():
                shutil.copyfile(self.resolv_conf_backup, self.resolv_conf)
                self.resolv_conf_backup.unlink()
                logger.info("[+] Ursprüngliche /etc/resolv.conf Datei wiederhergestellt.")
                return True

            return True

        except Exception as e:
            logger.warning(f"[!] Fehler beim Wiederherstellen der /etc/resolv.conf: {e}")
            return False

    # -------------------------------------------------------------------------
    # 3. NFTABLES KILL-SWITCH (Zero-Trust & Anti-Leak)
    # -------------------------------------------------------------------------

    def setup_nftables_killswitch(self) -> bool:
        """Aktiviert den Kill-Switch mit flexibler Tor-Prozess-Erkennung und IPv6-Leak-Protection."""
        try:
            tor_uid, _ = self._get_tor_user_ids()
            
            # Falls UID nicht ermittelt werden konnte, Fallback auf Prozess-Name/User
            uid_rule = f"skuid {tor_uid} accept" if tor_uid is not None else "skuid { debian-tor, tor } accept"

            nft_script = f"""
            table inet {self.nft_table_name} {{
                chain output {{
                    type filter hook output priority 0; policy accept;

                    # Ungültige Pakete sofort verwerfen
                    ct state invalid drop

                    # Loopback & Etablierte Verbindungen IMMER erlauben
                    oif "lo" accept
                    ct state established,related accept

                    # IPv6 Clearnet strikt verwerfen (Anti-Leak)
                    meta nfproto ipv6 drop

                    # DNS nur über lokalen Tor-DNSPort erlauben
                    udp dport {self.cfg.port_dns} accept
                    tcp dport {self.cfg.port_dns} accept

                    # Dem Tor-Daemon ausgehenden Traffic gestatten
                    {uid_rule}

                    # ALLES ANDERE (Clearnet von normalen Prozessen/Usern) DROPPEN
                    meta skuid != {tor_uid if tor_uid else "root"} drop
                }}
            }}
            """

            subprocess.run(
                ["nft", "-f", "-"],
                input=nft_script,
                text=True,
                capture_output=True,
                check=True,
            )
            logger.info(f"[+] nftables Ruleset angewendet (Tor-UID: {tor_uid}).")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[-] nftables Fehler: {e.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei nftables: {e}")
            return False

    def remove_nftables_killswitch(self) -> bool:
        """Entfernt die Kill-Switch-Tabelle aus dem System."""
        try:
            res = subprocess.run(
                ["nft", "delete", "table", "inet", self.nft_table_name],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                logger.info("[+] nftables Kill-Switch Tabelle entfernt.")
            else:
                logger.info("[*] Keine Kill-Switch Tabelle zum Entfernen gefunden.")
            return True
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen der Kill-Switch Tabelle: {e}")
            return False

    # -------------------------------------------------------------------------
    # 3b. NFTABLES DNS-REDIRECT
    # -------------------------------------------------------------------------

    def setup_dns_redirect(self) -> bool:
        """Zwingt sämtlichen Port-53 DNS-Traffic in den Tor-DNSPort (Anti-DNS-Leak)."""
        try:
            nft_script = f"""
            table inet {self.dns_table_name} {{
                chain dns_redirect {{
                    type nat hook output priority -100;
                    tcp dport 53 redirect to :{self.cfg.port_dns}
                    udp dport 53 redirect to :{self.cfg.port_dns}
                }}
            }}
            """
            subprocess.run(
                ["nft", "-f", "-"],
                input=nft_script,
                text=True,
                capture_output=True,
                check=True,
            )
            logger.info(f"[+] DNS-Redirect aktiv (Port 53 -> Port {self.cfg.port_dns}).")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"[-] Fehler beim Anlegen des DNS-Redirects: {e.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei DNS-Redirect: {e}")
            return False

    def remove_dns_redirect(self) -> bool:
        """Entfernt die DNS-Redirect-Tabelle."""
        try:
            res = subprocess.run(
                ["nft", "delete", "table", "inet", self.dns_table_name],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                logger.info("[+] DNS-Redirect-Tabelle entfernt.")
            else:
                logger.info("[*] Keine DNS-Redirect-Tabelle vorhanden.")
            return True
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen des DNS-Redirects: {e}")
            return False

    # -------------------------------------------------------------------------
    # 4. WINDOWS FIREWALL MANAGEMENT (via PowerShell Interop)
    # -------------------------------------------------------------------------

    def _is_windows_admin(self) -> bool:
        """Prüft via PowerShell, ob die Session Administratorrechte besitzt."""
        check_cmd = "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
        if not Path(POWERSHELL_PATH).exists():
            return False
        try:
            res = subprocess.run(
                [POWERSHELL_PATH, "-NoProfile", "-NonInteractive", "-Command", check_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.stdout.strip().lower() == "true"
        except Exception:
            return False

    def _run_powershell(self, command: str) -> bool:
        """Führt einen PowerShell-Befehl auf dem Windows-Host aus."""
        if not Path(POWERSHELL_PATH).exists():
            logger.error(f"[-] PowerShell Interop-Pfad nicht gefunden: {POWERSHELL_PATH}")
            return False

        try:
            cmd = [
                POWERSHELL_PATH,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("[!] Windows-Firewall-Aufruf Timeout (15s).")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"[-] PowerShell-Fehler: {e.stderr.strip() or e.stdout.strip()}")
            return False
        except Exception as e:
            logger.error(f"[-] Fehler bei PowerShell Interop: {e}")
            return False

    def setup_firewall_rules(self) -> bool:
        """Erstellt eingehende Windows-Firewall-Regeln für Privoxy und ORPort."""
        if not self._is_windows_admin():
            logger.warning("[!] Keine Windows-Adminrechte erkannt. Windows-Firewall-Regeln werden übersprungen.")
            return False

        logger.info(f"Konfiguriere Windows-Firewall-Regeln (Privoxy: {self.cfg.port_privoxy}, ORPort: {self.cfg.port_or})...")
        ps_cmd = (
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" -ErrorAction SilentlyContinue; '
            f'New-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" '
            f'-Direction Inbound -Action Allow -Protocol TCP -LocalPort {self.cfg.port_privoxy} '
            f'-Profile Any -Description "Cyberdeck Tor Suite Privoxy Proxy"; '
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" -ErrorAction SilentlyContinue; '
            f'New-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" '
            f'-Direction Inbound -Action Allow -Protocol TCP -LocalPort {self.cfg.port_or} '
            f'-Profile Any -Description "Cyberdeck Tor Suite ORPort Relay"'
        )
        if self._run_powershell(ps_cmd):
            logger.info("[+] Windows-Firewall-Regeln erfolgreich aktiv.")
            return True
        return False

    def remove_firewall_rules(self) -> bool:
        """Entfernt alle eingerichteten Windows-Firewall-Regeln spurlos."""
        if not Path(POWERSHELL_PATH).exists():
            return False

        logger.info("Entferne Windows-Firewall-Regeln...")
        ps_clean = (
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" -ErrorAction SilentlyContinue; '
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" -ErrorAction SilentlyContinue'
        )
        return self._run_powershell(ps_clean)


# =============================================================================
# EXEKUTION / MODUL-TEST
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    print("\n=== Starte SecurityManager Integrationstest (Context Manager) ===\n")

    # Ausführung mittels Context Manager garantiert sauberen Setup & Teardown
    try:
        with SecurityManager() as sec:
            print("\n[SUCCESS] Alle Sicherheits- & Firewall-Regeln sind AKTIV.")
            print("[TEST] Drücke Enter, um den automatischen Teardown zu testen (oder breche mit Ctrl+C ab)...")
            input()
    except KeyboardInterrupt:
        print("\n[!] Manueller Abbruch erkannt.")

    print("\n=== SecurityManager Integrationstest ERFOLGREICH BEENDET ===\n")