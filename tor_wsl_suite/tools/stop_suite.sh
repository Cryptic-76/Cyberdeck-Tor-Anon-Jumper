#!/bin/bash
# =============================================================================
# Cyberdeck Tor Suite - Stop (graceful)
#
# Schickt SIGTERM an main.py, damit der Shutdown (Firewall-/DNS-/Kill-Switch-
# Reset, RAM-Disk-Unmount) voll durchläuft. Wartet kurz und bestätigt.
# =============================================================================

SUITE_DIR="/mnt/c/tor-expert-bundle/tor_wsl_suite"
LOG_DIR_SUITE="$SUITE_DIR/logs"
mkdir -p "$LOG_DIR_SUITE"
LOGFILE="$LOG_DIR_SUITE/suite_start.log"
PY="python3"
MAIN="$SUITE_DIR/main.py"

echo "[$(date '+%H:%M:%S')] stop_suite.sh" >> "$LOGFILE"
if [ "$(id -u)" -ne 0 ]; then
    exec sudo -n bash "$0" "$@"
fi

if pgrep -f "python3 $MAIN" >/dev/null 2>&1; then
    pkill -TERM -f "python3 $MAIN"
    echo "SIGTERM gesendet, warte auf sauberen Shutdown..." >> "$LOGFILE"
    for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        if ! pgrep -f "python3 $MAIN" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if pgrep -f "python3 $MAIN" >/dev/null 2>&1; then
        echo "process endet nicht -> SIGKILL" >> "$LOGFILE"
        pkill -KILL -f "python3 $MAIN" 2>/dev/null
    fi
    echo "Suite gestoppt." >> "$LOGFILE"
else
    echo "Suite nicht aktiv (nichts zu tun)." >> "$LOGFILE"
fi
exit 0