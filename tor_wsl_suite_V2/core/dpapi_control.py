"""
Cyberdeck Tor Suite - DPAPI-geschützte Ablage des Tor-Control-Port-Passworts.

Damit dein Windows-Tool die Suite steuern kann, ohne ein Klartext-Passwort
auf der Platte zu haben:

  - Die Suite generiert beim Start ein Passwort und legt es VERSCHLÜSSELT
    (Windows DPAPI, User-Scope, symmetrisch per Betriebssystem-Key) in
    einer Datei mit Endung .enc ab.
  - Dasselbe Windows-Konto entschlüsselt es vollautomatisch (ohne Eingabe)
    via DPAPI wieder – dein Tool braucht nur den Entschlüsselungs-Helper.

Gehärtet nach Zero-Trust-Grundsätzen und mit sicherem Anti-Forensik-Cleanup.
"""

import base64
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Standardpfad zur PowerShell auf dem Windows-Host aus WSL-Sicht (Interop)
DEFAULT_POWERSHELL_EXE = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


class ControlPasswordVault:
    """
    Speichert das Control-Port-Passwort verschlüsselt (DPAPI) in einer Datei.
    """

    def __init__(self, enc_path: Path):
        self.enc_path = Path(enc_path)
        self.powershell_bin = self._resolve_powershell()

    def _resolve_powershell(self) -> str:
        """Ermittelt dynamisch den Pfad zur Windows PowerShell via WSL-Interop."""
        if Path(DEFAULT_POWERSHELL_EXE).exists():
            return DEFAULT_POWERSHELL_EXE
        
        # Fallback auf systemweiten PATH (falls in WSL-Interop freigegeben)
        ps_path = shutil.which("powershell.exe")
        if ps_path:
            return ps_path
            
        logger.warning("[!] Windows PowerShell nicht direkt gefunden. Nutze Standardpfad.")
        return DEFAULT_POWERSHELL_EXE

    # ------------------------------------------------------------------
    # PowerShell-Helfer (Windows DPAPI via System.Security.ProtectedData)
    # ------------------------------------------------------------------

    def _run_dpapi(self, protect: bool, data_b64: str = "") -> str:
        """
        Führt Protect/Unprotect über PowerShell aus.
        :param protect: True=verschlüsseln, False=entschlüsseln
        :param data_b64: bei protect=Base64 des Klartextes; bei unprotect=Base64 des Blobs
        """
        if not self.powershell_bin:
            logger.error("[-] DPAPI abgebrochen: keine gültige PowerShell-Executable.")
            return ""

        ps_cmd = (
            "Add-Type -AssemblyName System.Security; "
            f"$bytes = [Convert]::FromBase64String('{data_b64}'); "
            f"$res = [System.Security.Cryptography.ProtectedData]::{'Protect' if protect else 'Unprotect'}("
            "$bytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser); "
            "[Convert]::ToBase64String($res)"
        )

        try:
            proc = subprocess.run(
                [
                    self.powershell_bin,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_cmd,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                logger.error(f"[-] DPAPI-PowerShell-Fehler: {proc.stderr.strip()}")
                return ""

            out = proc.stdout.strip()
            # Ergebnis ist die letzte Zeile (Base64)
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
            logger.error("[-] DPAPI-PowerShell Timeout.")
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

            self.enc_path.parent.mkdir(parents=True, exist_ok=True)
            self.enc_path.write_text(enc_b64 + "\n", encoding="ascii")
            
            # Zero-Trust: Rechte streng auf 0600 einschränken
            os.chmod(self.enc_path, 0o600)

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
        """Überschreibt und entfernt die verschlüsselte Datei sicher (z. B. beim Shutdown)."""
        try:
            if self.enc_path.exists():
                # Anti-Forensik: Überschreibe Inhalt vor Unlink
                size = self.enc_path.stat().st_size
                with open(self.enc_path, "wb") as f:
                    f.write(os.urandom(size))
                self.enc_path.unlink()
                logger.info("[+] DPAPI-Passwort-Datei sicher überschrieben und entfernt (Shutdown).")
        except Exception as e:
            logger.warning(f"[!] DPAPI-Löschen fehlgeschlagen: {e}")


if __name__ == "__main__":
    # Einzeltest des Moduls
    logging.basicConfig(level=logging.INFO)
    test_vault_path = Path("/dev/shm/test_control.enc")
    vault = ControlPasswordVault(test_vault_path)
    
    test_pwd = "SecretCyberdeckPassword123!"
    if vault.encrypt_password(test_pwd):
        decrypted = vault.decrypt_password()
        if decrypted == test_pwd:
            print("[+] DPAPI Vault Test ERFOLGREICH!")
        else:
            print("[-] Entschlüsselung ergab falsches Ergebnis.")
        vault.delete()