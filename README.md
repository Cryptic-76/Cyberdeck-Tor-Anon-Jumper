<img width="1408" height="768" alt="Gemini_Generated_Image_ougi7wougi7wougi" src="https://github.com/user-attachments/assets/557d9e67-d01d-42e7-be70-640a696550ed" />

# Cyberdeck Tor Anon Jumper

*Cyberdeck Tor Suite (WSL2 / RAM-Disk Edition)* – Anonymous browsing setup for Windows 11 + WSL2 (Kali Linux). The suite launches a dedicated Tor daemon in the RAM-disk, routes all Windows traffic through Privoxy → Tor SOCKS5 (remote DNS) and secures it with an nftables kill-switch, DNS-leak protection and strict file- and password handling. The exit IP rotates automatically.

> ⚠️ **Privacy tooling – not a tool for bypassing system or network policies.** Intended for use in authorized/privacy scenarios and your own research.

---

## Data Flow (Architecture)

```
Windows Browser
     │  System proxy (Registry) -> http://<WSL-IP>:8118
     ▼
Privoxy  (WSL, port 8118, hardened actions in user.action)
     │  forward-socks5t  ->  remote DNS (no DNS leak)
     ▼
Tor SOCKS5 (127.0.0.1:9050)  ── ControlPort 9051: NEWNYM rotation ──► Tor exit 🇪🇺
     │
     ├─ DNSPort 5353  (Tor DNS, resolved via /etc/resolv.conf)
     └─ ORPort 8443   (stealth relay, no published descriptor)
```

**Start order (root-cause aware):** Tor bootstrap **100 %** → DNS-leak protection + DNS redirect + nftables kill-switch → *then* Privoxy → system proxy. The browser never has to run through a chain that is not ready yet.

---

## Features

- Dedicated Tor daemon in a **256 MB tmpfs RAM-disk** (configs + DataDirectory are volatile)
- Automatic **exit-IP rotation every 120 s** via `SIGNAL NEWNYM` (controlled through the Tor control port)
- **nftables kill-switch** (isolated table, `policy drop`): outbound traffic only for the Tor UID; loopback and Tor-DNS-port 5353 are explicit exceptions – everything else is dropped
- **DNS-leak protection on two layers:** `/etc/resolv.conf` → `127.0.0.1` (with `chattr +i`) **plus** an nftables NAT redirect that forces every port-53 packet to the Tor DNSPort
- **Privoxy hardening** via `user.action` (Referer, From, X-Real-IP, X-Forwarded-For, If-Modified-Since are stripped), `forward-socks5t` enforces remote DNS
- **Stealth relay:** Tor runs as a relay with custom ORPort `8443` but publishes **no descriptor** (`PublishServerDescriptor 0`) – avoids WSL2-NAT problems on high ports
- **Control-password handled via Windows DPAPI** – no plaintext on disk
- Windows 11's system proxy is wired to Privoxy (running in Linux) and enabled automatically – don't be surprised :)
- Clean **graceful shutdown**: firewall rules, kill-switch, DNS redirect, resolv.conf and system proxy are fully reset, RAM-disk is unmounted
- **Windows firewall rules** (inbound 8118 Privoxy + 8443 relay) are set via PowerShell interop and removed again on shutdown

---

## Requirements

| Component | Requirement |
|---|---|
| OS | Windows 10/11 with WSL2 + **Kali Linux** distro (name `kali-linux`) |
| Packages in WSL | `tor`, `privoxy`, `nftables`, `curl`, `python3-pip` |
| Python | 3.10+, `stem`, `requests` |
| sudo | `NOPASSWD` for startup (autostart/RAM-disk/kill-switch require root) |
| Path | Install the suite to `C:\tor-expert-bundle\tor_wsl_suite\` (hard-coded in `tools/*.cmd`, `_autostart.vbs` and `config/settings.py`) |
| Note | Optionally open ORPort **8443** for incoming and outgoing connections in your router / Fritz!Box |
| Note | You must setup ignoredPorts 9050,9051,8118,8443 in your .wslconfig

---

## Installation

### 1. Set up WSL2 + Kali

```powershell
wsl --install -d kali-linux
```

### 2. Packages inside Kali

```bash
sudo apt update
sudo apt install -y tor privoxy nftables curl python3-pip
python3 -m pip install -r requirements.txt   # contains: stem
# if requirements.txt is empty:
python3 -m pip install stem requests
```

### 3. Place the suite

Copy the folder to `C:\tor-expert-bundle\tor_wsl_suite\` (Windows side).

### 4. sudo NOPASSWD (so `start_suite.sh` works from autostart/VBS without a TTY)

```bash
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/cyberdeck
sudo chmod 440 /etc/sudoers.d/cyberdeck
```

### 5. Autostart on Windows logon (optional)

```powershell
# Windows PowerShell (as the user)
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\install_autostart.ps1
# Remove it with:
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\install_autostart.ps1 -Remove
```

`install_autostart.ps1` drops an invisible VBS launcher into the Startup folder; the VBS waits until WSL is ready and then calls `start_suite.sh` (with 3 retries).

---

## Start / Stop / Status

| Action | Command |
|---|---|
| Start (Windows) | `C:\tor-expert-bundle\tor_wsl_suite\tools\start_suite.cmd` |
| Start (WSL) | `cd /mnt/c/tor-expert-bundle/tor_wsl_suite && bash tools/start_suite.sh` |
| Manual start (foreground) | `cd /mnt/c/tor-expert-bundle/tor_wsl_suite && sudo python3 main.py` |
| Stop (graceful, Windows) | `C:\tor-expert-bundle\tor_wsl_suite\tools\stop_suite.cmd` |
| Stop (WSL) | `bash tools/stop_suite.sh` |

Status/IP tool (Windows PowerShell, queries the suite internally from within WSL):

```powershell
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\tor_status.ps1
# force a new exit IP immediately:
powershell -ExecutionPolicy Bypass -File C:\tor-expert-bundle\tor_wsl_suite\tools\tor_status.ps1 -Rotate
```

Verify against check.torproject.org **without** any additional text:

```bash
curl -x http://<WSL-IP>:8118 https://check.torproject.org/api/ip
# -> {"IsTor":true,"IP":"..."} – the exit IP changes with every rotation
```

---

## Configuration

All central values live in `config/settings.py`:

| Parameter | Value | Meaning |
|---|---|---|
| `IP_ROTATION_INTERVAL_SEC` | 120 | rotation every 120 s |
| `PRIVOXY_PORT` | 8118 | HTTP proxy of the suite (binds `0.0.0.0`) |
| `TOR_SOCKS_PORT` / `TOR_CONTROL_PORT` | 9050 / 9051 | SOCKS5 resp. control port (password protected) |
| `TOR_DNS_PORT` | 5353 | Tor DNSPort used for leak protection |
| `TOR_OR_PORT` | 8443 | stealth-relay ORPort |
| `EUROPEAN_EXIT_NODES` | EU country list | `ExitNodes` restriction (torrc) |
| `RAMDISK_MOUNT_POINT` | `/mnt/tor_ramdisk` | 256 MB tmpfs |

**Templates** (rendered into the RAM-disk):

- `config/torrc.template` → `/mnt/tor_ramdisk/torrc`
- `config/privoxy.conf.template` → `/mnt/tor_ramdisk/privoxy.conf` (contains `confdir /etc/privoxy` for error-page templates and the `actionsfile …/user.action`)
- `config/privoxy-user.action.template` → `/mnt/tor_ramdisk/user.action`
  (single-line action block, URL pattern on its own line – only these actions are verified against Privoxy 4.2.0!)

---

## Security Details

1. **RAM-disk** (`core/ramdisk.py`): torrc, privoxy.conf, `user.action` and Tor data live exclusively in the tmpfs – everything is unmounted and destroyed on shutdown.
2. **Kill-switch** (`core/security.py`): dedicated nftables table, `policy drop`; exceptions: loopback, `ct state established,related accept` (answers to the Windows client!), UDP/TCP 5353, `skuid <tor-uid>`. Tor runs as the system user `debian-tor` (via `User debian-tor` in torrc) so the UID rule applies.
3. **Forced DNS** (`setup_dns_redirect`): every DNS query is re-routed via a NAT hook to the Tor DNSPort `5353` – a leak over clearnet resolvers is ruled out.
4. **Control password**: randomly generated, only stored as a Windows-DPAPI ciphertext on disk (`control_password.enc`); Tor receives the S2K hash in the torrc.
5. **Firewall**: Windows inbound rules for `8118`/`8443` are created on start and removed on shutdown.
6. **Hardening actions (Privoxy)**: referer/filter, From resp. X-Real-IP/X-Forwarded-For and If-Modified-Since are stripped. **Note:** actions only apply to unencrypted HTTP – HTTPS/CONNECT is transparent to Privoxy.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| "No internet, although Tor bootstrapped" | The kill-switch drops proxy answers → check the line `ct state established,related accept` in `setup_nftables_killswitch()`; restart the suite once cleanly |
| `500 Could not load template file forwarding-failed` | `confdir /etc/privoxy` is missing in the privoxy.conf → regenerate the template (it is in the template; error pages come from `/etc/privoxy/templates`) |
| Bootstrap stays at 30–50 % / `NOROUTE` | Without `PublishServerDescriptor 0`, Tor tries high ORPorts (9001/8500/9030) which are unreachable in WSL2-NAT → that line is mandatory |
| Port conflict 9050/9051 | `tor.service` on Debian is a no-op; orphaned processes are cleaned by `TorServiceManager.cleanup_dangling_processes()` (`pkill -9 tor`) |
| Windows PowerShell interop hangs | Firewall calls have a 15 s timeout (see `security.py`); proxy/status calls use the same PowerShell path |
| Real Firefox user-agent (compromise) | `hide-user-agent` is silently ignored by Privoxy 4.2.0 and `clobber-user-agent` even prevents startup → Firefox `about:config → privacy.resistFingerprinting = true` |

Logs: `logs/tor_suite.log` (main log), `logs/tor_direct.log`, `logs/privoxy_direct.log`; `tools/start_suite.sh` writes to `logs/suite_start.log`.

---

## Project Structure

```
tor_wsl_suite/
├── main.py                        # orchestration (start 0–10, graceful shutdown)
├── config/
│   ├── settings.py                # ports, paths, interval, exit nodes, DPAPI password
│   ├── torrc.template             # Tor config (RAM-disk)
│   ├── privoxy.conf.template      # Privoxy config (forward-socks5t, actionsfile, confdir)
│   └── privoxy-user.action.template  # real hardening actions
├── core/
│   ├── ramdisk.py                 # tmpfs mount/unmount
│   ├── tor_manager.py             # Tor start, bootstrap wait (stem), NEWNYM rotation
│   ├── privoxy_manager.py         # config generation + Privoxy start
│   ├── security.py                # kill-switch, forced DNS, firewall, permissions
│   ├── win_proxy.py               # Windows system proxy (registry via PowerShell)
│   ├── service_manager.py         # stop system Tor, free orphaned processes
│   ├── system_check.py            # root/binary checks, WSL IP
│   └── dpapi_control.py           # DPAPI ciphertext of the control password
├── tools/
│   ├── start_suite.sh / stop_suite.sh     # idempotent daemon start/stop (WSL)
│   ├── start_suite.cmd / stop_suite.cmd   # Windows wrappers
│   ├── install_autostart.ps1              # autostart (VBS launcher)
│   ├── tor_status.ps1 + tor_status_helper.py   # status/IP tool
└── _autostart.vbs                 # hidden launcher (in the Startup folder)
```
© 2026 Jörn Andre Peters
