"""
Cyberdeck Tor Suite - Security, Permissions & Firewall Manager
Verwaltet POSIX-Dateirechte, dynamisches DNS-Routing, nftables Kill-Switch (mit Backup/Restore) und Windows-Firewall-Regeln.
"""

import logging
import os
import pwd
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Dynamic Settings Import mit striktem Fallback
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
except ImportError:
    # Standard-Fallback-Pfade & Port-Definitionen
    CONFIG_DIR = "/etc/cyberdeck"
    GENERATED_PRIVOXY_CONF = "/etc/privoxy/config"

    # RAM-Disk-Pfade (/run/cyberdeck/tor)
    RAMDISK_BASE_DIR = Path("/run/cyberdeck")
    RAMDISK_TOR_DIR = RAMDISK_BASE_DIR / "tor"
    GENERATED_TORRC = RAMDISK_TOR_DIR / "torrc"

    TOR_DATA_DIR = "/var/lib/tor"

    # Port-Definitionen
    TOR_DNS_PORT = 5353      # Lokaler Tor DNS-Port
    TOR_SOCKS_PORT = 9050    # Standard Tor SOCKS5-Port
    TOR_OR_PORT = 9001       # Tor Relay / Onion Router Port
    PRIVOXY_PORT = 8118      # Privoxy HTTP Proxy Port

logger = logging.getLogger(__name__)

# Absoluter Interop-Pfad zu PowerShell aus WSL2 heraus
POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


class SecurityManager:
    """Verwaltet POSIX-Rechte, DNS-Umleitung, nftables Kill-Switch mit Backup und Windows-Firewall-Regeln."""

    RULE_NAME_PRIVOXY = "Cyberdeck_TorSuite_Privoxy"
    RULE_NAME_RELAY = "Cyberdeck_TorSuite_ORPort"

    # Explizite Port-Zuweisungen innerhalb der Klasse
    PORT_PRIVOXY: int = PRIVOXY_PORT
    PORT_OR: int = TOR_OR_PORT
    PORT_DNS: int = TOR_DNS_PORT

    def __init__(self) -> None:
        self.nft_table_name = "cyberdeck_tor_killswitch"
        self.dns_table_name = "cyberdeck_dns_redirect"
        self.resolv_conf = Path("/etc/resolv.conf")
        
        # Sicherer Speicherort für Laufzeit-Backups (vermeidet /tmp Symlink-Attacken).
        # BEWUSST AUSSERHALB der tmpfs-RAM-Disk: Ein dortiges Backup würde beim
        # tmpfs-Mount verdeckt und beim Unmount zerstört (Backup wäre nutzlos).
        self.backup_dir = Path("/var/lib/cyberdeck/backup")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.backup_dir, 0o700)

        self.resolv_conf_backup = self.backup_dir / "resolv.conf.cyberdeck.bak"

    # =========================================================================
    # 1. POSIX-DATEIRECHTE & ORDNERSTRUKTUR (Linux / WSL)
    # =========================================================================

    def enforce_file_permissions(self) -> bool:
        """Erstellt nötige RAM-Disk-Ordner und setzt strikte POSIX-Rechte & Eigentümer."""
        try:
            logger.info("Setze strikte Dateirechte & erstelle Systempfade...")

            # 1. UID / GID von debian-tor oder tor ermitteln
            tor_uid: Optional[int] = None
            tor_gid: Optional[int] = None
            for username in ["debian-tor", "tor"]:
                try:
                    user_info = pwd.getpwnam(username)
                    tor_uid, tor_gid = user_info.pw_uid, user_info.pw_gid
                    break
                except KeyError:
                    continue

            # 2. Basis-Ordner /run/cyberdeck (0755)
            RAMDISK_BASE_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(RAMDISK_BASE_DIR, 0o700)

            # 3. Unterordner /run/cyberdeck/tor (0700)
            RAMDISK_TOR_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(RAMDISK_TOR_DIR, 0o700)

            # 4. Eigentümer auf debian-tor übertragen (falls als root ausgeführt)
            if tor_uid is not None and tor_gid is not None and os.geteuid() == 0:
                os.chown(RAMDISK_BASE_DIR, tor_uid, tor_gid)
                os.chown(RAMDISK_TOR_DIR, tor_uid, tor_gid)

            # 5. /var/lib/tor absichern (0700)
            tor_data_path = Path(TOR_DATA_DIR)
            if tor_data_path.exists():
                os.chmod(tor_data_path, 0o700)
                if tor_uid is not None and tor_gid is not None and os.geteuid() == 0:
                    os.chown(tor_data_path, tor_uid, tor_gid)

            # 6. torrc-Datei sicherstellen / anlegen (0600)
            torrc_path = Path(GENERATED_TORRC)
            if not torrc_path.exists():
                torrc_path.touch(mode=0o600)
            else:
                os.chmod(torrc_path, 0o600)

            if tor_uid is not None and tor_gid is not None and os.geteuid() == 0:
                os.chown(torrc_path, tor_uid, tor_gid)

            # 7. Privoxy-Config (0600)
            privoxy_path = Path(GENERATED_PRIVOXY_CONF)
            if privoxy_path.exists():
                os.chmod(privoxy_path, 0o600)

            logger.info(f"[+] Pfad {torrc_path} mit Rechte 0600 & User-UID {tor_uid} vorbereitet.")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Setzen der Dateirechte / Pfade: {e}")
            return False

    # =========================================================================
    # 2. DYNAMISCHES DNS-MANAGEMENT (/etc/resolv.conf)
    # =========================================================================

    def apply_tor_dns(self) -> bool:
        """Sichert die originale resolv.conf und erzwingt lokalen Tor-DNS (127.0.0.1)."""
        try:
            # Sichern, falls Backup noch nicht existiert
            if self.resolv_conf.exists() and not self.resolv_conf_backup.exists():
                shutil.copyfile(self.resolv_conf.resolve(), self.resolv_conf_backup)

            # Schreibschutz aufheben (falls zuvor gesetzt)
            subprocess.run(["chattr", "-i", str(self.resolv_conf)], capture_output=True)

            if self.resolv_conf.is_symlink():
                self.resolv_conf.unlink()

            self.resolv_conf.write_text("nameserver 127.0.0.1\n", encoding="utf-8")
            
            # Schreibschutz gegen automatisches Überschreiben durch WSL2 / NetworkManager aktivieren
            subprocess.run(["chattr", "+i", str(self.resolv_conf)], capture_output=True)

            logger.info("[+] /etc/resolv.conf gehärtet und auf lokalen Tor-DNS umgeleitet.")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Setzen von /etc/resolv.conf: {e}")
            return False

    def restore_dns(self) -> bool:
        """Stellt die ursprüngliche resolv.conf beim Beenden wieder her."""
        try:
            # Schreibschutz aufheben
            subprocess.run(["chattr", "-i", str(self.resolv_conf)], capture_output=True)

            if self.resolv_conf_backup.exists():
                if self.resolv_conf.exists() or self.resolv_conf.is_symlink():
                    self.resolv_conf.unlink()

                shutil.copyfile(self.resolv_conf_backup, self.resolv_conf)
                self.resolv_conf_backup.unlink()
                logger.info("[+] Ursprüngliche /etc/resolv.conf wiederhergestellt.")
            return True

        except Exception as e:
            logger.warning(f"[!] Fehler beim Wiederherstellen der /etc/resolv.conf: {e}")
            return False

    # =========================================================================
    # 3. NFTABLES KILL-SWITCH (Isolierte Tabelle)
    # =========================================================================

    def setup_nftables_killswitch(self) -> bool:
        """
        Aktiviert den Kill-Switch in eigener Tabelle (ohne globale Regeln zu flushen):
        - Loopback erlaubt.
        - DNS über definierten TOR_DNS_PORT erlaubt.
        - Outbound NUR für den Tor-System-User erlaubt.
        """
        try:
            # Tor UID ermitteln
            tor_uid: Optional[int] = None
            for username in ["debian-tor", "tor"]:
                try:
                    tor_uid = pwd.getpwnam(username).pw_uid
                    break
                except KeyError:
                    continue

            if tor_uid is None:
                logger.error("[-] Konnte die System-UID für Tor ('debian-tor' / 'tor') nicht ermitteln.")
                return False

            # Isolierte Kill-Switch Tabelle anwenden
            nft_script = f"""
            table inet {self.nft_table_name} {{
                chain output {{
                    type filter hook output priority 0; policy drop;

                    # Antworten auf etablierte Verbindungen durchlassen (z. B. Privoxy ->
                    # Windows-Client). Ohne diese Zeile verwirft der Kill-Switch die Antwort-/
                    # SYN-ACK-Pakete von Privoxy an den Windows-Host: Tor bootstrapped zwar,
                    # aber der Browser bekommt nie eine Antwort ("im Tor-Netz, kein Internet").
                    ct state established,related accept

                    # Loopback-Traffic gestatten
                    oif "lo" accept

                    # DNS über Tor-DNS Port ({self.PORT_DNS}) erlauben
                    udp dport {self.PORT_DNS} accept
                    tcp dport {self.PORT_DNS} accept

                    # Outbound Traffic nur für den Tor-Prozess (UID {tor_uid})
                    skuid {tor_uid} accept
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
            logger.info(f"[+] nftables Kill-Switch aktiv (Exklusiver Outbound für Tor-UID {tor_uid}, DNS-Port {self.PORT_DNS}).")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[-] Fehler beim Anwenden der nftables-Regeln: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei nftables: {e}")
            return False

    def remove_nftables_killswitch(self) -> bool:
        """Entfernt sauber die Kill-Switch-Tabelle aus dem System."""
        try:
            res = subprocess.run(
                ["nft", "delete", "table", "inet", self.nft_table_name],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                logger.info("[+] nftables Kill-Switch Tabelle erfolgreich gelöscht.")
            else:
                logger.info("[+] Keine aktive Kill-Switch-Tabelle zum Löschen gefunden.")
            return True

        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen der nftables Kill-Switch-Tabelle: {e}")
            return False

    # =========================================================================
    # 3b. DNS-LEAK-SCHUTZ (nftables NAT-Redirect: Port 53 -> Tor-DNSPort 5353)
    # =========================================================================

    def setup_dns_redirect(self) -> bool:
        """
        Leitet sämtliche DNS-Abfragen (UDP/TCP Port 53) transparent und zwangsweise auf
        Tor's DNSPort ({TOR_DNS_PORT}) um. Greift im nat-Output-Hook, bevor der
        Kill-Switch filtert – damit ist ein DNS-Leak über clearnet-Resolver ausgeschlossen,
        selbst wenn eine Anwendung die resolv.conf komplett ignoriert.
        """
        try:
            nft_script = f"""
            table inet {self.dns_table_name} {{
                chain dns_redirect {{
                    type nat hook output priority -100;
                    tcp dport 53 redirect to :{self.PORT_DNS}
                    udp dport 53 redirect to :{self.PORT_DNS}
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
            logger.info(f"[+] DNS-Redirect aktiv: jeder Port-53-Aufruf -> Tor-DNSPort {self.PORT_DNS} (kein DNS-Leak).")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"[-] Fehler beim Anlegen der DNS-Redirect-Tabelle: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei setup_dns_redirect: {e}")
            return False

    def remove_dns_redirect(self) -> bool:
        """Entfernt die DNS-Redirect-Tabelle sauber."""
        try:
            res = subprocess.run(
                ["nft", "delete", "table", "inet", self.dns_table_name],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                logger.info("[+] DNS-Redirect-Tabelle erfolgreich entfernt.")
            else:
                logger.info("[*] Keine aktive DNS-Redirect-Tabelle vorhanden (übersprungen).")
            return True
        except Exception as e:
            logger.error(f"[-] Fehler beim Entfernen der DNS-Redirect-Tabelle: {e}")
            return False

    # =========================================================================
    # 4. WINDOWS FIREWALL MANAGEMENT (via Interop PowerShell)
    # =========================================================================

    def _run_powershell_admin(self, command: str) -> bool:
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
            # Timeout verhindert, dass ein hängendes (nicht-elevates) PowerShell-Interop
            # die komplette Suite blockiert: Firewall-Regeln sind nice-to-have, kein Hard-Blocker.
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("[!] Windows-Firewall-Aufruf timeout (15s) – überspringe Firewall-Einrichtung.")
            return False
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.strip() or e.stdout.strip()
            logger.error(f"[-] PowerShell-Firewall-Fehler: {err_msg}")
            return False
        except Exception as e:
            logger.error(f"[-] Unerwarteter Fehler bei PowerShell-Ausführung: {e}")
            return False

    def setup_firewall_rules(self) -> bool:
        """Erstellt eingehende Windows-Firewall-Regeln für Privoxy und den Tor Relay ORPort."""
        logger.info(f"Konfiguriere Windows-Firewall-Regeln für Ports {self.PORT_PRIVOXY} (Privoxy) & {self.PORT_OR} (ORPort)...")

        ps_cmd = (
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" -ErrorAction SilentlyContinue; '
            f'New-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" '
            f'-Direction Inbound -Action Allow -Protocol TCP -LocalPort {self.PORT_PRIVOXY} '
            f'-Profile Any -Description "Cyberdeck Tor Suite Privoxy Proxy Port {self.PORT_PRIVOXY}"; '
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" -ErrorAction SilentlyContinue; '
            f'New-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" '
            f'-Direction Inbound -Action Allow -Protocol TCP -LocalPort {self.PORT_OR} '
            f'-Profile Any -Description "Cyberdeck Tor Suite Stealth ORPort Relay {self.PORT_OR}"'
        )

        if self._run_powershell_admin(ps_cmd):
            logger.info(f"[+] Firewall-Regeln erfolgreich gesetzt ({self.PORT_PRIVOXY} & {self.PORT_OR} TCP).")
            return True
        else:
            logger.warning("[!] Firewall-Regeln konnten teilweise nicht gesetzt werden (Elevated Admin-Rechte unter Windows erforderlich).")
            return False

    def remove_firewall_rules(self) -> bool:
        """Entfernt alle erstellten Windows-Firewall-Regeln beim Beenden spurlos."""
        logger.info("Entferne temporäre Windows-Firewall-Regeln...")

        ps_clean = (
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_PRIVOXY}" -ErrorAction SilentlyContinue; '
            f'Remove-NetFirewallRule -DisplayName "{self.RULE_NAME_RELAY}" -ErrorAction SilentlyContinue'
        )

        if self._run_powershell_admin(ps_clean):
            logger.info("[+] Windows-Firewall-Regeln sauber gelöscht.")
            return True
        else:
            logger.error("[-] Fehler beim Löschen der Firewall-Regeln.")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sec = SecurityManager()

    # Ausführungstest Setup
    sec.enforce_file_permissions()
    sec.apply_tor_dns()
    sec.setup_nftables_killswitch()
    sec.setup_firewall_rules()

    # Ausführungstest Cleanup
    sec.remove_firewall_rules()
    sec.remove_nftables_killswitch()
    sec.restore_dns()