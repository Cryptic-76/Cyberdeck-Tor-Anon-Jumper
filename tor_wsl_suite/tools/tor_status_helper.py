#!/usr/bin/env python3
"""
Cyberdeck Tor Suite - WSL-seitiger Status-Helper.

Wird von tools/tor_status.ps1 via `wsl.exe` aufgerufen. Läuft INSIDE WSL,
damit die Windows<->WSL-Firewall kein Problem ist (die Suite und dieser
Helper sind im selben WSL-Netzwerk).

Ausgaben:
  - Exit-IP aus check.torproject.org über den Tor-SOCKS-Proxy
  - "durch Tor: JA/NEIN"
  - Falls -rotate: sendet zuerst SIGNAL NEWNYM (neue Exit-IP)
"""
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/c/tor-expert-bundle/tor_wsl_suite")

from core.dpapi_control import ControlPasswordVault

SUITE_ROOT = Path("/mnt/c/tor-expert-bundle/tor_wsl_suite")
ENC_PATH = Path("/mnt/c/tor-expert-bundle/tor_wsl_suite/control_password.enc")
SOCKS = "127.0.0.1:9050"
CONTROL = ("127.0.0.1", 9051)


def read_all(sock, timeout=2.0):
    sock.settimeout(timeout)
    buf = b""
    try:
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    return buf


def send_control(cmd):
    """Authentifiziert am ControlPort und sendet eine Zeile. Gibt Antworten zurück."""
    pw = ControlPasswordVault(ENC_PATH).decrypt_password()
    if not pw:
        return None
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect(CONTROL)
        s.sendall(b"PROTOCOLINFO\r\n")
        read_all(s, timeout=1)
        s.sendall(('AUTHENTICATE "%s"\r\n' % pw).encode())
        auth = read_all(s, timeout=1)
        if not auth.startswith(b"250"):
            return ("auth-failed", auth.strip()[:80])
        s.sendall((cmd + "\r\n").encode())
        resp = read_all(s, timeout=2)
        return resp
    except Exception as e:
        return ("err", str(e)[:100])
    finally:
        try:
            s.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="NEWNYM vor der IP-Abfrage")
    args = ap.parse_args()

    if args.rotate:
        r = send_control("SIGNAL NEWNYM")
        if r and (isinstance(r, bytes) and r.startswith(b"250")):
            time.sleep(8)

    # Exit-IP über Tor-SOCKS
    exit_ip = "-"
    country = "-"
    is_tor = False
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "20", "--socks5-hostname", SOCKS,
             "https://check.torproject.org/api/ip"],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
        if out:
            import json
            d = json.loads(out)
            exit_ip = d.get("IP", "-")
            is_tor = bool(d.get("IsTor"))
            country = d.get("CountryName", "-")
    except Exception:
        pass

    print("EXIT_IP=%s" % exit_ip)
    print("IS_TOR=%s" % ("YES" if is_tor else "NO"))
    print("COUNTRY=%s" % country)
    return 0 if is_tor else 1


if __name__ == "__main__":
    sys.exit(main())