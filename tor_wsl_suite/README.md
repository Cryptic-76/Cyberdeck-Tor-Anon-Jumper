# Cyberdeck Tor Suite (WSL2 / RAM-Disk Edition)

Anonymes Browsing-Setup für **Windows 11 + WSL2 (Kali Linux)**. Die Suite startet einen
eigenen Tor-Daemon in der RAM-Disk, leitet den gesamten Windows-Verkehr über Privoxy
→ Tor SOCKS5 (Remote-DNS) und sichert das mit nftables-Kill-Switch, DNS-Leak-Schutz
und striktem Datei- und Passwort-Handling. Die **Exit-IP rotiert automatisch**.

> ⚠️ **Privacy-Tooling – kein Werkzeug zur Umgehung von System-/Netzwerkrichtlinien.**
> Für den Einsatz in autorisierten/privacy-Szenarien und eigene Recherche gedacht.

---

## Datenfluss (Architektur)

```
Windows-Browser
     │  Systemproxy (Registry) -> http://<WSL-IP>:8118
     ▼
Privoxy  (WSL, Port 8118, gehärtete Actions in user.action)
     │  forward-socks5t  ->  Remote-DNS (kein DNS-Leak)
     ▼
Tor SOCKS5 (127.0.0.1:9050)  ── ControlPort 9051: NEWNYM-Rotation ──► Tor-Exit 🇪🇺
     │
     ├─ DNSPort 5353  (Tor-DNS, resolved über /etc/resolv.conf)
     └─ ORPort 8443   (Stealth Relay, kein publizierter Descriptor)
```

**Startreihenfolge (Root-Cause-bewusst):**
Tor-Bootstrap **100 %** → DNS-Leak-Schutz + DNS-Redirect + nftables-Kill-Switch → erst dann Privoxy → Systemproxy. So muss der Browser nie durch eine noch nicht einsatzbereite Kette laufen.

---

## Features

- **Eigener Tor-Daemon** in einer 256 MB tmpfs-RAM-Disk (Configs + DataDirectory flüchtig)
- **Automatische Exit-IP-Rotation** alle 120 s über `SIGNAL NEWNYM` (Steuerung via ControlPort)
- **nftables-Kill-Switch** (isolierte Tabelle, `policy drop`): Outbound nur für die Tor-UID,
  Loopback und Tor-DNS-Port 5353 – alles andere fällt durch
- **DNS-Leak-Schutz** in zwei Ebenen: `/etc/resolv.conf` → `127.0.0.1` (mit `chattr +i`) **plus**
  nftables-NAT-Redirect jedes Port-53-Pakets auf den Tor-DNSPort
- **Privoxy-Härtung** per `user.action` (Referer, From, X-Real-IP, X-Forwarded-For,
  If-Modified-Since werden entfernt), `forward-socks5t` erzwingt Remote-DNS
- **Stealth-Relay**: Tor läuft als Relay mit Custom-ORPort `8443`, publiziert aber keinen
  Descriptor (`PublishServerDescriptor 0`) – blockiert WSL2-NAT-Probleme auf hohe Ports
- **Control-Passwort per Windows-DPAPI** – kein Klartext auf der Platte
- Sauberer **Graceful Shutdown**: Firewall-Regeln, Kill-Switch, DNS-Redirect, resolv.conf
  und Systemproxy werden restlos zurückgesetzt, RAM-Disk unmountet
- **Windows-Firewall-Regeln** (inbound 8118 Privoxy + 8443 Relay) werden per PowerShell-Interop gesetzt und wieder entfernt

---

## Voraussetzungen

| Komponente | Anforderung |
|---|---|
| Betriebssystem | Windows 10/11 mit WSL2 + **Kali Linux**-Distro (Name `kali-linux`) |
| Pakete in WSL | `tor`, `privoxy`, `nftables`, `curl`, `python3-pip` |
| Python | 3.10+, `stem` |
| sudo | `NOPASSWD` für den Start (Autostart/RAM-Disk/Kill-Switch brauchen Root) |
| Pfad | Suite installieren nach `C:\tor-expert-bundle\tor_wsl_suite\` (in `tools/*.cmd`, `_autostart.vbs` und `config/settings.py` hart verankert) |

---

## Installation

### 1. WSL2 + Kali einrichten

```powershell
wsl --install -d kali-linux
```

### 2. Pakete in Kali

```bash
sudo apt update
sudo apt install -y tor privoxy nftables curl python3-pip
python3 -m pip install -r requirements.txt   # enthält: stem
# falls requirements.txt leer ist:
python3 -m pip install stem
```

### 3. Suite ablegen

Ordner nach `C:\tor-expert-bundle\tor_wsl_suite\` kopieren (Windows-Seite).

### 4. sudo NOPASSWD (für `start_suite.sh` aus Autostart/VBS ohne TTY)

```bash
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/cyberdeck
sudo chmod 440 /etc/sudoers.d/cyberdeck
```

### 5. Autostart bei Windows-Anmeldung (optional)

```powershell
# Windows PowerShell (als Nutzer)
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\install_autostart.ps1
# Entfernen mit:
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\install_autostart.ps1 -Remove
```

`install_autostart.ps1` legt einen unsichtbaren VBS-Launcher im Startup-Ordner ab; der VBS
wartet bis WSL bereit ist und ruft `start_suite.sh` auf (mit 3 Retries).

---

## Start / Stop / Status

| Aktion | Befehl |
|---|---|
| Start (Windows) | `C:\tor-expert-bundle\tor_wsl_suite\tools\start_suite.cmd` |
| Start (WSL) | `cd /mnt/c/tor-expert-bundle/tor_wsl_suite && bash tools/start_suite.sh` |
| Manueller Start (Foreground) | `cd /mnt/c/tor-expert-bundle/tor_wsl_suite && sudo python3 main.py` |
| Stop (graceful, Windows) | `C:\tor-expert-bundle\tor_wsl_suite\tools\stop_suite.cmd` |
| Stop (WSL) | `bash tools/stop_suite.sh` |

Status-/IP-Tool (Windows PowerShell, fragt die Suite WSL-intern ab):

```powershell
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\tor_status.ps1
# sofort neue Exit-IP erzwingen:
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\tor_status.ps1 -Rotate
```

Verifikation gegencheck.torproject.org **ohne** Zusatztext:

```bash
curl -x http://<WSL-IP>:8118 https://check.torproject.org/api/ip
# -> {"IsTor":true,"IP":"..."} – Exit-IP wechselt mit jeder Rotation
```

---

## Konfiguration

Alle zentralen Werte liegen in `config/settings.py`:

| Parameter | Wert | Bedeutung |
|---|---|---|
| `IP_ROTATION_INTERVAL_SEC` | 120 | Rotation alle 120 s |
| `PRIVOXY_PORT` | 8118 | HTTP-Proxy der Suite (bindet `0.0.0.0`) |
| `TOR_SOCKS_PORT` / `TOR_CONTROL_PORT` | 9050 / 9051 | SOCKS5 bzw. ControlPort (Passwort-geschützt) |
| `TOR_DNS_PORT` | 5353 | Tor-DNSPort für den Leak-Schutz |
| `TOR_OR_PORT` | 8443 | Stealth-Relay ORPort |
| `EUROPEAN_EXIT_NODES` | EU-Länderliste | `ExitNodes`-Einschränkung (torrc) |
| `RAMDISK_MOUNT_POINT` | `/mnt/tor_ramdisk` | 256 MB tmpfs |

**Templates** (werden in die RAM-Disk gerendert):
- `config/torrc.template` → `/mnt/tor_ramdisk/torrc`
- `config/privoxy.conf.template` → `/mnt/tor_ramdisk/privoxy.conf` (enthält `confdir /etc/privoxy` für Fehlerseiten-Templates und `actionsfile …/user.action`)
- `config/privoxy-user.action.template` → `/mnt/tor_ramdisk/user.action`
  (einzeiliger Action-Block, URL-Muster auf eigener Zeile – nur diese Actions sind gegen Privoxy 4.2.0 verifiziert!)

---

## Sicherheits-Details

1. **RAM-Disk** (`core/ramdisk.py`): torrc, privoxy.conf, `user.action`, Tor-Daten liegen
   ausschließlich im tmpfs – beim Shutdown wird alles unmountet und vernichtet.
2. **Kill-Switch** (`core/security.py`): eigene nftables-Tabelle, `policy drop`; Ausnahmen:
   Loopback, `ct state established,related accept` (Antworten an den Windows-Client!),
   UDP/TCP 5353, `skuid <tor-uid>`. **Tor läuft als Systemuser `debian-tor`** (via `User debian-tor` in torrc), damit die UID-Regel greift.
3. **DNS-Zwang** (`setup_dns_redirect`): jede DNS-Anfrage wird per NAT-Hook auf den
   Tor-DNSPort `5353` umgeleitet – ein Leak über Clearnet-Resolver ist ausgeschlossen.
4. **ControlPasswort**: zufällig erzeugt, nur als Windows-DPAPI-Chiffrat
   (`control_password.enc`) auf Platte; Tor bekommt den S2K-Hash in die torrc.
5. **Firewall**: Windows-inbound-Regeln für 8118/8443 werden beim Start erzeugt und beim
   Shutdown wieder entfernt.
6. **Härtungs-Actions** (Privoxy): referer/filter, From bzw. X-Real-IP/X-Forwarded-For und
   If-Modified-Since werden entfernt. **Hinweis:** Actions wirken nur auf unverschlüsseltes
   HTTP – HTTPS/CONNECT ist für Privoxy intransparent.

---

## Troubleshooting

| Symptom | Ursache / Lösung |
|---|---|
| „Kein Internet, obwohl Tor bootstrapped“ | Kill-Switch verwirft Proxy-Antworten → Zeile `ct state established,related accept` in `setup_nftables_killswitch()` prüfen; Suite einmal sauber neu starten |
| `500 Could not load template file forwarding-failed` | `confdir /etc/privoxy` fehlt in der privoxy.conf → Template neu generieren (Steht im Template; Fehlerseiten kommen aus `/etc/privoxy/templates`) |
| Bootstrap bleibt bei 30–50 % / `NOROUTE` | Ohne `PublishServerDescriptor 0` fliegt Tor auf hohe ORPorts (9001/8500/9030), die in WSL2-NAT nicht erreichbar sind → Zeile ist zwingend |
| Port-Konflikt 9050/9051 | `tor.service` auf Debian ist ein No-Op; verwaiste Prozesse räumt `TorServiceManager.cleanup_dangling_processes()` (`pkill -9 tor`) |
| Windows-PowerShell-Interop hängt | Firewall-Aufrufe haben 15-s-Timeout (fabrik im `security.py`); Proxy-/Status-Aufrufe nutzen denselben Powershell-Pfad |
| Für den echten Firefox-UA (Kompromiss) | `hide-user-agent` wird von Privoxy 4.2.0 ignoriert, `clobber-user-agent` verhindert den Start → Firefox `about:config → privacy.resistFingerprinting = true` |

Logs: `logs/tor_suite.log` (Hauptlog), `logs/tor_direct.log`, `logs/privoxy_direct.log`, `tools/start_suite.sh` schreibt nach `logs/suite_start.log`.

---

## Projektstruktur

```
tor_wsl_suite/
├── main.py                        # Orchestrierung (Start 0–10, Graceful Shutdown)
├── config/
│   ├── settings.py                # Ports, Pfade, Intervall, Exit-Nodes, DPAPI-Passwort
│   ├── torrc.template             # Tor-Config (RAM-Disk)
│   ├── privoxy.conf.template      # Privoxy-Config (forward-socks5t, actionsfile, confdir)
│   └── privoxy-user.action.template  # echte Härtungs-Actions
├── core/
│   ├── ramdisk.py                 # tmpfs-Mount/-Unmount
│   ├── tor_manager.py             # Tor-Start, Bootstrap-Wait (stem), NEWNYM-Rotation
│   ├── privoxy_manager.py         # Config-Generierung + Privoxy-Start
│   ├── security.py                # Kill-Switch, DNS-Zwang, Firewall, Rechte
│   ├── win_proxy.py               # Windows-Systemproxy (Registry via PowerShell)
│   ├── service_manager.py         # System-Tor stoppen, Altprozesse freiräumen
│   ├── system_check.py            # Root-/Binär-Prüfungen, WSL-IP
│   └── dpapi_control.py           # DPAPI-Chiffrat des Control-Passworts
├── tools/
│   ├── start_suite.sh / stop_suite.sh     # idempotenter Daemon-Start/-Stop (WSL)
│   ├── start_suite.cmd / stop_suite.cmd   # Windows-Wrapper
│   ├── install_autostart.ps1              # Autostart (VBS-Launcher)
│   ├── tor_status.ps1 + tor_status_helper.py   # Status-/IP-Tool
└── _autostart.vbs                 # versteckter Launcher (im Startup-Ordner)
```