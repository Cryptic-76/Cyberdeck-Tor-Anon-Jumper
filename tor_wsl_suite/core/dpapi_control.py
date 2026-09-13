"""
Cyberdeck Tor Suite - DPAPI-geschützte Ablage des Tor-Control-Port-Passworts.

Damit dein Windows-Tool die Suite steuern kann, ohne ein Klartext-Passwort
auf der Platte zu haben:

  - Die Suite generiert beim Start ein Passwort und legt es VERSCHLÜSSELT
    (Windows DPAPI, User-Scope, symmetrisch per Betriebssystem-Key) in
    einer Datei mit Endung .enc ab.
  - Dasselbe Windows-Konto entschlüsselt es vollautomatisch (ohne Eingabe)
    via DPAPI wieder – dein Tool braucht nur den Entschlüsselungs-Helper.

Hinweis: DPAPI ist an das WINDOWS-Benutzerkonto gekoppelt. Wenn die Suite
(WSL) und dein Tool auf demselben Windows-PC laufen, funktioniert das sofort.
Auf anderen Konten/Rechnern schlägt die Entschlüsselung bewusst fehl.
"""

import base64
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Pfad zur PowerShell auf dem Windows-Host aus WSL-Sicht (Interop).
POWERSHELL_EXE = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


class ControlPasswordVault:
    """
    Speichert das Control-Port-Passwort verschlüsselt (DPAPI) in einer Datei.
    """

    def __init__(self, enc_path: Path):
        self.enc_path = Path(enc_path)

    # ------------------------------------------------------------------
    # PowerShell-Helfer (Windows DPAPI via System.Security.ProtectedData)
    # ------------------------------------------------------------------

    def _run_dpapi(self, protect: bool, data_b64: str = "") -> str:
        """
        Führt Protect/Unprotect über PowerShell aus.
        :param protect: True=verschlüsseln, False=entschlüsseln
        :param data_b64: bei protect=Base64 des Klartextes; bei unprotect=Base64 des Blobs
        """
        ps_cmd = (
            "Add-Type -AssemblyName System.Security; "
            "$bytes = [Convert]::FromBase64String('{data}'); "
            "$res = [System.Security.Cryptography.ProtectedData]::{op}("
            "$bytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser); "
            "[Convert]::ToBase64String($res)"
        ).format(data=data_b64, op="Protect" if protect else "Unprotect")

        try:
            proc = subprocess.run(
                [POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                logger.error(f"[-] DPAPI-PowerShell-Fehler: {proc.stderr.strip()}")
                return ""
            out = proc.stdout.strip()
            # Ergebnis ist die letzte Zeile (Base64); frühe Zeilen sind evtl. Stderr-Logging
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line:
                    try:
                        base64.b64decode(line, validate=True)
                        return line
                    except Exception:
                        continue
            return ""
        except subprocess.TimeoutExpired:
            logger.error("[-] DPAPI-PowerShell timeout.")
            return ""
        except Exception as e:
            logger.error(f"[-] DPAPI-Aufruf fehlgeschlagen: {e}")
            return ""

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def encrypt_password(self, password: str) -> bool:
        """Verschlüsselt das Klartext-Passwort via Windows-DPAPI und legt es ab."""
        try:
            plain_b64 = base64.b64encode(password.encode("utf-8")).decode("ascii")
            enc_b64 = self._run_dpapi(protect=True, data_b64=plain_b64)
            if not enc_b64:
                return False
            self.enc_path.write_text(enc_b64 + "\n", encoding="ascii")
            logger.info(f"[+] Control-Passwort DPAPI-verschlüsselt abgelegt: {self.enc_path}")
            return True
        except Exception as e:
            logger.error(f"[-] DPAPI-Verschlüsselung fehlgeschlagen: {e}")
            return False

    def decrypt_password(self) -> str:
        """Entschlüsselt das DPAPI-Blob und gibt das Klartext-Passwort zurück (nur im RAM!)."""
        try:
            if not self.enc_path.exists():
                logger.error(f"[-] DPAPI-Datei fehlt: {self.enc_path}")
                return ""
            blob_b64 = self.enc_path.read_text(encoding="ascii").strip()
            plain_b64 = self._run_dpapi(protect=False, data_b64=blob_b64)
            if not plain_b64:
                return ""
            # Nur hier im RAM: Klartext entschlüsseln
            return base64.b64decode(plain_b64).decode("utf-8")
        except Exception as e:
            logger.error(f"[-] DPAPI-Entschlüsselung fehlgeschlagen: {e}")
            return ""

    def delete(self) -> None:
        """Entfernt die verschlüsselte Datei (z. B. beim Shutdown)."""
        try:
            if self.enc_path.exists():
                self.enc_path.unlink()
                logger.info("[+] DPAPI-Passwort-Datei entfernt (Shutdown).")
        except Exception as e:
            logger.warning(f"[!] DPAPI-Löschen fehlgeschlagen: {e}")