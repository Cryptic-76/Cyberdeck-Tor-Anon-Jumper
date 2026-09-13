# Security Policy

The **Cyberdeck Tor Suite** is a privacy-oriented browsing setup for
Windows 11 + WSL2 (Kali Linux): it runs a dedicated Tor daemon in a tmpfs
RAM-disk, routes all Windows traffic through Privoxy → Tor SOCKS5
(remote DNS), and enforces an nftables kill-switch, DNS-leak protection,
stricte file permissions and a DPAPI-protected control-port password.

We take the security and privacy properties of this tool seriously.
Thank you for helping to keep it safe by following responsible disclosure.

## Supported Versions

The suite is developed on the `main` branch without tagged releases yet.
Only the currently maintained state is supported:

| Version / Branch | Supported          |
| ---------------- | ------------------ |
| `main`           | :white_check_mark: |
| Other branches   | :x:                |

If you deploy a fork or a copy, please track `main` (or a released tag
once available) and re-verify the configuration before use.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

- **Preferred channel:** open a **private security advisory**
  (repo → *Security* → *Report a vulnerability* on GitHub). This keeps the
  report private until it can be addressed.
- **Alternative:** contact the maintainer directly (e.g. via the email
  address on your GitHub profile / after finding a private announcement
  channel in the repo GitHub profile).

When reporting, please include:

1. A clear, minimal **description** of the issue (component and file).
2. **Steps to reproduce** or a short proof-of-concept.
3. Impact assessment (e.g. anonymity/leak impact, privilege, remote vs. local).
4. Affected version(s) / commit(s).
5. Your suggested fix, if you have one.

### Handling timeline

We try to follow this disclosure schedule:

- Within **72 h**: acknowledge receipt (private channels only).
- Within **7 days**: confirm and assess the finding; share a status update.
- Within **30–90 days**: work toward a fix and/or mitigation. If a fix is
  not possible within 90 days, coordinate public disclosure with you first.

We will **not** make a vulnerability public without coordinating with the
reporter first (unless it is already publicly exploited).

## Scope

In-scope components:

- `main.py` and the whole `core/` package (RAM-disk, Tor manager, Privoxy
  manager, security/nftables/kill-switch, Windows proxy, DNS handling).
- `config/*.template` and generated runtime configuration (torrc,
  privoxy.conf, `user.action`).
- `tools/` helper scripts (start/stop, autostart, status tooling).
- The Windows↔WSL interaction layer (PowerShell interop, environment setup).

Out of scope / explicitly NOT a bug in this repository:

- Issues inherent to the **Tor network** itself, to **Tor/Privoxy** or other
  upstream dependencies (report those to the respective projects).
- General weaknesses of WSL2, Windows, or a managed/enterprise environment
  (e.g. machine tampering or install-time compromise).
- Misconfiguration by the user (see the project README for hardening notes),
  unless our default configuration itself is at fault.

## Known Limitations (by design / documented)

These are intentional and are part of the documented threat model — please
respect them when assessing this suite:

- Privoxy actions only transform **unencrypted HTTP**; HTTPS/CONNECT traffic
  passes through the TLS tunnel untouched (header-level actions do not apply).
- `hide-user-agent` is silently ignored by Privoxy 4.2.0 and
  `clobber-user-agent` even aborts startup — the real browser user-agent stays
  unless you set `privacy.resistFingerprinting` in Firefox.
- An **adversary controlling the Tor exit / an upstream component** can still
  observe and correlate traffic; the suite mitigates leaks but cannot protect
  against a fully compromised endpoint or OS.

## Security Properties Provided

- RAM-disk (tmpfs) keeps torrc, privoxy.conf, `user.action` and Tor datadir
  volatile; clean shutdown unmounts and destroys them.
- nftables kill-switch: only the Tor system user may reach the network;
  loopback and Tor-DNSPort are explicit exceptions.
- Dual DNS-leak protection: `resolv.conf` → local Tor-DNS plus forced
  NAT redirect of every port-53 packet to the Tor DNSPort.
- Control-port password stored as DPAPI ciphertext (no plaintext on disk).
- Windows firewall rules are created on start and removed on shutdown.

## Acknowledgements & Coordination

If you are interested in coordinated disclosure across related privacy
tooling or need a PGP contact, please reach out via the private advisory
channel described above. No compensation is provided; credit will be given
in the advisory and release notes.

---

*Thank you for keeping this tool – and the people using it – safer.*

© 2026 Jörn Andre Peters
