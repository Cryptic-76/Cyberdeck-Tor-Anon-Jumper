#!/bin/bash
# =============================================================================
# Cyberdeck Tor Suite - Start (idempotent, daemonized)
#
# Wird von Windows aus via  wsl.exe bash tools/start_suite.sh  aufgerufen
# (per Autostart oder manuell). Startet die Suite einmalig im Hintergrund.
# Läuft die Suite schon, tut das Skript nichts (kein Doppelstart).
# =============================================================================

SUITE_DIR="/mnt/c/tor-expert-bundle/tor_wsl_suite"
LOG_DIR_SUITE="$SUITE_DIR/logs"
mkdir -p "$LOG_DIR_SUITE"
LOGFILE="$LOG_DIR_SUITE/suite_start.log"
PIDFILE="/tmp/cyberdeck_suite.pid"
PY="python3"
MAIN="$SUITE_DIR/main.py"

echo "[$(date '+%H:%M:%S')] start_suite.sh" >> "$LOGFILE"

# 1) Läuft die Suite bereits? -> nichts tun.
if pgrep -f "python3 $MAIN" >/dev/null 2>&1; then
    pid=$(pgrep -f "python3 $MAIN" | head -1)
    echo "already-running pid=$pid (kein Doppelstart)" >> "$LOGFILE"
    exit 0
fi

# 2) main.py vorhanden?
if [ ! -f "$MAIN" ]; then
    echo "ERROR: $MAIN fehlt" >> "$LOGFILE"
    exit 1
fi

# 3) Falls Skript nicht als root: mit sudo -n hochstufen (root kann RAM-Disk, nft, tor-uid).
if [ "$(id -u)" -ne 0 ]; then
    echo "noch nicht root -> sudo -n (NOPASSWD)" >> "$LOGFILE"
    exec sudo -n bash "$0" "$@"
fi

# 4) Als root: Suite daemonisieren (setsid/nohup) und PID merken.
cd "$SUITE_DIR" || exit 1
nohup setsid python3 "$MAIN" >> "$LOGFILE" 2>&1 &
pid=$!
echo "$pid" > "$PIDFILE"
echo "gestartet pid=$pid (root)" >> "$LOGFILE"
exit 0