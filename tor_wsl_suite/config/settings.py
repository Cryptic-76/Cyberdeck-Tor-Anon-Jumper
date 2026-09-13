"""
Cyberdeck Tor Suite - Central Configuration Settings
Ausgelagerte Variablen und Parameter nach dem EVA-Prinzip.
"""

import functools
import hashlib
import logging
import os
import secrets
from pathlib import Path

# --- BASIS-PFADE ---
BASE_DIR: Path = Path(__file__).resolve().parent.parent

CONFIG_DIR: Path = BASE_DIR / "config"
LOG_DIR: Path = BASE_DIR / "logs"

# Persistente, DPAPI-verschlüsselte Datei mit dem generierten Control-Port-Passwort.
# Kein Klartext auf der Platte: nur dasselbe Windows-Konto kann sie via DPAPI öffnen.
# Dein Windows-IP/Status-Tool entschlüsselt diese Datei und nutzt das Passwort
# für AUTHENTICATE auf dem Tor-ControlPort.
RESTRICTED_PASSWORD_FILE_ENC: Path = BASE_DIR / "control_password.enc"
# Überholt (falls aus früheren Versionen übrig) – nur noch für einmalige Migration.
RESTRICTED_PASSWORD_FILE: Path = BASE_DIR / "control_password.txt"

# Vorlagen
TORRC_TEMPLATE: Path = CONFIG_DIR / "torrc.template"
PRIVOXY_TEMPLATE: Path = CONFIG_DIR / "privoxy.conf.template"
# Echtes Privoxy-Härtungs-Set (Actions) – wird zusätzlich in die RAM-Disk geschrieben.
PRIVOXY_ACTION_TEMPLATE: Path = CONFIG_DIR / "privoxy-user.action.template"

# --- RAM-DISK & FLÜCHTIGE DATEN (tmpfs) ---
RAMDISK_MOUNT_POINT: str = "/mnt/tor_ramdisk"
RAMDISK_SIZE_MB: int = 256

# Basis- & Unterordner in der RAM-Disk (werden u.a. von security.py benötigt,
# damit dort NICHT auf die alten Fallback-Pfade /run/cyberdeck* zurückgegriffen wird)
RAMDISK_BASE_DIR: Path = Path(RAMDISK_MOUNT_POINT)
RAMDISK_TOR_DIR: Path = RAMDISK_BASE_DIR / "tor"

# Pfade innerhalb der RAM-Disk
TOR_DATA_DIR: str = f"{RAMDISK_MOUNT_POINT}/tor_data"
GENERATED_TORRC: str = f"{RAMDISK_MOUNT_POINT}/torrc"
GENERATED_PRIVOXY_CONF: str = f"{RAMDISK_MOUNT_POINT}/privoxy.conf"

# --- NETZWERK & PORTS ---
# Tor Ports
TOR_SOCKS_HOST: str = "127.0.0.1"
TOR_SOCKS_PORT: int = 9050
TOR_CONTROL_PORT: int = 9051
TOR_DNS_PORT: int = 5353

# =============================================================================
# GEOIP & EXIT-NODE CONFIGURATION
# =============================================================================
# Europäische Ländercodes nach ISO-3166-1 alpha-2
EUROPEAN_EXIT_NODES = (
    "{at},{be},{bg},{ch},{cy},{cz},{de},{dk},{ee},{es},{fi},{fr},{gb},{gr},"
    "{hr},{hu},{ie},{is},{it},{lt},{lu},{lv},{nl},{no},{pl},{pt},{ro},{se},{si},{sk}"
)

# Stealth Relay Port (Custom ORPort zur Umgehung von Standard-Monitoring auf 9001)
TOR_OR_PORT: int = 8443
TOR_RELAY_NICKNAME: str = "CyberdeckRelay"

# Privoxy Settings
PRIVOXY_HOST: str = "0.0.0.0"  # Hört auf allen WSL-Schnittstellen
PRIVOXY_PORT: int = 8118

# WSL Subnetz-Erlaubnis für Tor SOCKS Policy
WSL_IP_RANGE: str = "172.16.0.0/12"

# --- IP-ROTATION & INTERVALLE ---
# Rotationsintervall (Sekunden). Vom User auf 120s gesetzt (bewährt getestet):
# 60s war wegen der NOROUTE-langsamen Pfade zu häufig; 120s lässt neue Circuits sauber aufbauen.
IP_ROTATION_INTERVAL_SEC: int = 120

# --- DYNAMISCHE CONTROLPORT-AUTHENTIFIZIERUNG ---
def generate_random_password(length: int = 32) -> str:
    """Generiert ein kryptografisch sicheres Zufallspasswort."""
    return secrets.token_urlsafe(length)


def hash_tor_control_password(password: str) -> str:
    """
    Erzeugt einen Tor-kompatiblen HashedControlPassword-String (S2K / Salted Hash algorithm).
    Implementiert das RFC 2440 / Tor Specs Format (16: Hex Salt + Hash).
    
    HINWEIS FÜR SECURITY SCANNERS:
    SHA-1 ist vom Tor-Protokoll-Standard (S2K) zwingend vorgegeben.
    """
    salt = os.urandom(8)
    count = 96  # Standard Tor S2K Iterationszahl Code (96 = 65536 Bytes Expansion)
    
    # S2K Algorithm nach Tor Spec
    c = 65536
    data = salt + password.encode("utf-8")
    d = b""
    while len(d) < c:
        d += data
    d = d[:c]
    
    # codeql[py/weak-sensitive-data-hashing] - SHA1 is strictly required by Tor S2K specification
    hashed = hashlib.sha1(d).digest()
    
    # Format: 16: + Salt(Hex) + Hash(Hex)
    salt_hex = salt.hex().upper()
    count_hex = f"{count:02X}"
    hash_hex = hashed.hex().upper()
    
    return f"16:{salt_hex}{count_hex}{hash_hex}"


def load_or_create_control_password() -> str:
    """
    Liefert das DPAPI-geschützte Control-Port-Passwort:

      - Existiert bereits die verschlüsselte Datei control_password.enc
        (RESTRICTED_PASSWORD_FILE_ENC), entschlüsselt und zurückgegeben.
      - Andernfalls wird ein NEUES Passwort erzeugt, mit Windows-DPAPI
        verschlüsselt abgelegt (kein Klartext auf Platte) und zurückgegeben.

    Dein externes Windows-Tool kann dasselbe Passwort via DPAPI entschlüsseln
    (gleiche Windows-Konto / gleicher PC) und sich am Tor-ControlPort anmelden.
    """
    # Lokaler Import: bricht den Zirkular-Import settings -> core -> settings auf.
    from core.dpapi_control import ControlPasswordVault

    vault = ControlPasswordVault(RESTRICTED_PASSWORD_FILE_ENC)

    # 1) Verschlüsselte Datei vorhanden und entschlüsselbar? -> Passwort wiederverwenden.
    if RESTRICTED_PASSWORD_FILE_ENC.exists():
        existing = vault.decrypt_password()
        if existing:
            return existing
        # Nicht entschlüsselbar (fremdes Konto/Rechner) -> als kaputt behandeln & neu erzeugen.
        logging.getLogger("settings").warning(
            "[!] DPAPI-Passwort-Datei nicht entschlüsselbar – erzeuge neues Passwort."
        )

    # 2) Neu erzeugen + verschlüsselt ablegen.
    password = generate_random_password()
    if vault.encrypt_password(password):
        logging.getLogger("settings").info(
            f"[+] Neues Control-Passwort erzeugt und DPAPI-verschlüsselt gespeichert: "
            f"{RESTRICTED_PASSWORD_FILE_ENC.name}"
        )
    return password


def persist_control_password(password: str) -> None:
    """Aktualisiert die DPAPI-verschlüsselte Passwort-Ablage (für externe Tools)."""
    from core.dpapi_control import ControlPasswordVault

    vault = ControlPasswordVault(RESTRICTED_PASSWORD_FILE_ENC)
    if not vault.encrypt_password(password):
        logging.getLogger("settings").warning("[!] Konnte DPAPI-Passwort-Datei nicht aktualisieren.")


# --- LAZY CONTROL-PORT-PASSWORT (Option 1: kein Import-Zeit-Effekt) ---
#
# Wichtig: Das Passwort wird NICHT beim Import von config.settings erzeugt.
# Das verhindert den Zirkular-Import:  config -> core (DPAPI) -> config.
# Erzeugung + DPAPI-Ablage erfolgen erst beim ersten Zugriff (lazy), d.h.
# wenn die Suite tatsächlich läuft oder dein externes Tool danach fragt.


@functools.lru_cache(maxsize=1)
def get_control_password_raw() -> str:
    """Liefert das Control-Port-Klartext-Passwort (lazy, gecacht, DPAPI-gesichert)."""
    return load_or_create_control_password()


@functools.lru_cache(maxsize=1)
def get_control_password_hashed() -> str:
    """Liefert den Tor-kompatiblen S2K-Hash des Control-Port-Passworts (lazy, gecacht)."""
    return hash_tor_control_password(get_control_password_raw())

# --- LOGGING ---
LOG_FILE: Path = LOG_DIR / "tor_suite.log"