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

# ==============================================================================
# EINGABE (E) - Systempfade & Verzeichnisstrukturen
# ==============================================================================

# Basis-Pfade
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

# ==============================================================================
# EINGABE (E) - Netzwerkeinstellungen, Ports & ISO-3166 Exit-Nodes
# ==============================================================================

# Tor Ports
TOR_SOCKS_HOST: str = "127.0.0.1"
TOR_SOCKS_PORT: int = 9050
TOR_CONTROL_PORT: int = 9051
TOR_DNS_PORT: int = 5353

# Europäische Ländercodes nach ISO-3166-1 alpha-2 für gehärtete Exit-Node-Auswahl
EUROPEAN_EXIT_NODES: str = (
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

# --- LOGGING ---
LOG_FILE: Path = LOG_DIR / "tor_suite.log"


# ==============================================================================
# VERARBEITUNG (V) - Kryptografische Generierung & DPAPI Vault-Handling
# ==============================================================================

def generate_random_password(length: int = 32) -> str:
    """
    Generiert ein kryptografisch sicheres Zufallspasswort via CSPRNG.
    """
    return secrets.token_urlsafe(length)


def hash_tor_control_password(password: str) -> str:
    """
    Kryptografisch exakte, speicherschonende Implementierung des Tor RFC 2440 S2K-Algorithmus.
    Vermeidet große Speicher-Allokationen im RAM zur Minimierung forensischer Spuren.
    """
    salt: bytes = os.urandom(8)
    count_byte: int = 96  # 96 entspricht 65536 Bytes Expansion
    expansion_bytes: int = 65536

    pass_bytes: bytes = password.encode("utf-8")
    data_block: bytes = salt + pass_bytes
    data_len: int = len(data_block)

    hasher = hashlib.sha1()
    written: int = 0

    while written < expansion_bytes:
        to_write: int = min(data_len, expansion_bytes - written)
        hasher.update(data_block[:to_write])
        written += to_write

    hashed: bytes = hasher.digest()
    return f"16:{salt.hex().upper()}{count_byte:02X}{hashed.hex().upper()}"


def load_or_create_control_password() -> str:
    """
    Liefert das DPAPI-geschützte Control-Port-Passwort:

      - Existiert bereits die verschlüsselte Datei control_password.enc
        (RESTRICTED_PASSWORD_FILE_ENC), wird sie entschlüsselt und zurückgegeben.
      - Andernfalls wird ein NEUES Passwort erzeugt, mit Windows-DPAPI
        verschlüsselt abgelegt (kein Klartext auf Platte) und zurückgegeben.

    Dein externes Windows-Tool kann dasselbe Passwort via DPAPI entschlüsseln
    (gleiches Windows-Konto / gleicher PC) und sich am Tor-ControlPort anmelden.
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
    password: str = generate_random_password()
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


# ==============================================================================
# AUSGABE (A) - Lazy Evaluated Getters (LRU Cache für Memory-Performance)
# ==============================================================================

# Wichtig: Das Passwort wird NICHT beim Import von config.settings erzeugt.
# Das verhindert den Zirkular-Import: config -> core (DPAPI) -> config.
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