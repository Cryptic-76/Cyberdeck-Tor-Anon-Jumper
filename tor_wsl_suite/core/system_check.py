"""
Cyberdeck Tor Suite - System Check & Validation Module
Überprüft Abhängigkeiten, System-Rechte und WSL-Umgebung vor der Ausführung.
"""

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Tuple


class SystemChecker:
    """Überprüft die Voraussetzungen für den Betrieb der Tor Suite unter WSL/Linux."""

    REQUIRED_BINARIES: List[str] = ["tor", "privoxy", "mount", "umount", "ip"]

    def __init__(self) -> None:
        self.check_results: Dict[str, bool] = {}

    def is_root(self) -> bool:
        """Prüft, ob das Skript mit Root-Rechten (sudo) ausgeführt wird."""
        return os.geteuid() == 0

    def check_binary_installed(self, binary_name: str) -> bool:
        """Prüft, ob eine benötigte Anwendung im PATH verfügbar ist."""
        return shutil.which(binary_name) is not None

    def get_wsl_ip(self) -> str:
        """Ermittelt die IP-Adresse der WSL2-Instanz zur Bindung an den Host."""
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", "eth0"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    # Format: inet 172.x.x.x/20 scope global eth0
                    return line.split()[1].split("/")[0]
        except Exception:
            pass
        return "127.0.0.1"

    def run_all_checks(self) -> Tuple[bool, List[str]]:
        """
        Führt alle Systemprüfungen durch.
        Rückgabe: (Erfolg: bool, Liste von Fehlermeldungen: List[str])
        """
        errors: List[str] = []

        # 1. Root-Rechte Prüfung
        if not self.is_root():
            errors.append(
                "Keine Root-Rechte! Bitte starte das Skript mit 'sudo python3 main.py'."
            )

        # 2. Binaries Prüfung
        missing_binaries = [
            bin_name
            for bin_name in self.REQUIRED_BINARIES
            if not self.check_binary_installed(bin_name)
        ]
        if missing_binaries:
            errors.append(
                f"Fehlende System-Tools: {', '.join(missing_binaries)}. "
                f"Bitte installiere sie via 'sudo apt install tor privoxy'."
            )

        success = len(errors) == 0
        return success, errors


if __name__ == "__main__":
    # Einzeltest des Moduls
    checker = SystemChecker()
    is_ok, errs = checker.run_all_checks()
    if is_ok:
        print(f"[+] Systemcheck erfolgreich! WSL-IP: {checker.get_wsl_ip()}")
    else:
        print("[-] Systemcheck fehlgeschlagen:")
        for err in errs:
            print(f"    - {err}")