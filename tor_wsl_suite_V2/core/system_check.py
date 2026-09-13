"""
Cyberdeck Tor Suite - System Check & Validation Module
Überprüft Abhängigkeiten, System-Rechte und WSL-Umgebung vor der Ausführung.
Gehärtet nach dem EVA-Prinzip, mit dynamischer Interface-Ermittlung und Port-Prechecks.
"""

import os
import shutil
import socket
import subprocess
import sys
from typing import Dict, List, Tuple


class SystemChecker:
    """Überprüft die Voraussetzungen für den Betrieb der Tor Suite unter WSL/Linux."""

    REQUIRED_BINARIES: List[str] = ["tor", "privoxy", "mount", "umount", "ip", "pkill"]
    REQUIRED_PYTHON_MODULES: List[str] = ["stem"]

    def __init__(self) -> None:
        self.check_results: Dict[str, bool] = {}

    def is_root(self) -> bool:
        """Prüft, ob das Skript mit Root-Rechten (sudo) ausgeführt wird."""
        return os.geteuid() == 0

    def check_binary_installed(self, binary_name: str) -> bool:
        """Prüft, ob eine benötigte Anwendung im PATH verfügbar ist."""
        return shutil.which(binary_name) is not None

    def check_python_module(self, module_name: str) -> bool:
        """Prüft, ob ein benötigtes Python-Modul importierbar ist."""
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False

    def get_wsl_ip(self) -> str:
        """
        Ermittelt die primäre IP-Adresse der WSL2-Instanz zur Bindung an den Host.
        Dynamischer Fallback über Socket-Routing, falls eth0 nicht existiert.
        """
        # Versuch 1: Dynamische Abfrage der Route
        try:
            result = subprocess.run(
                ["ip", "-4", "route", "show", "default"],
                capture_output=True,
                text=True,
                check=True,
            )
            out = result.stdout.strip()
            if "dev" in out:
                iface = out.split("dev")[1].split()[0]
                ip_res = subprocess.run(
                    ["ip", "-4", "addr", "show", iface],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in ip_res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("inet "):
                        return line.split()[1].split("/")[0]
        except Exception:
            pass

        # Versuch 2: UDP Socket Interface Routing-Abfrage (sendet keine Pakete)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("1.1.1.1", 80))
                return s.getsockname()[0]
        except Exception:
            pass

        return "127.0.0.1"

    def check_port_free(self, port: int, host: str = "127.0.0.1") -> bool:
        """Prüft, ob ein lokaler Port frei ist."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                return s.connect_ex((host, port)) != 0
        except Exception:
            return True

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
                f"Bitte installiere sie via 'sudo apt install tor privoxy procps'."
            )

        # 3. Python-Module Prüfung
        missing_modules = [
            mod_name
            for mod_name in self.REQUIRED_PYTHON_MODULES
            if not self.check_python_module(mod_name)
        ]
        if missing_modules:
            errors.append(
                f"Fehlende Python-Bibliotheken: {', '.join(missing_modules)}. "
                f"Bitte installiere sie via 'pip install stem'."
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