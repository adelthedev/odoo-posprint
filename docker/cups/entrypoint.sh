#!/bin/bash
# Creates one raw ESC/POS queue per PRINTER_<NAME>_URI env var (queue name =
# <name> lowercased, e.g. PRINTER_RECEIPT_URI -> queue 'receipt'), then runs
# cupsd in the foreground.
# Idempotent: lpadmin -p on an existing queue just updates it, so restarts are
# safe. Queues whose env var was removed are NOT deleted; drop them manually
# with `lpadmin -x <queue>` if needed.
set -euo pipefail

mapfile -t printer_vars < <(compgen -e | grep -E '^PRINTER_[A-Z0-9_]+_URI$' | sort)
if [ "${#printer_vars[@]}" -eq 0 ]; then
    echo "No PRINTER_<NAME>_URI env vars set (e.g. PRINTER_RECEIPT_URI=socket://printer-ip:9100)" >&2
    exit 1
fi

# lpadmin talks IPP to a running cupsd, so start it first, configure, then wait.
/usr/sbin/cupsd -f &
CUPSD_PID=$!

for i in $(seq 1 50); do
    if lpstat -r >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

make_queue() {
    local name="$1" uri="$2"
    # No -m/-P => queue has no PPD/filters: bytes pass through raw, which is
    # what ESC/POS needs. (-m raw is deprecated in CUPS 2.4; see FINDINGS.md.)
    lpadmin -p "$name" -E -v "$uri" \
        -o printer-is-shared=true \
        -o printer-error-policy=retry-job
    # -E after -p enables the queue + accepts jobs; do it explicitly too in case
    # a previous run left the queue paused.
    cupsenable "$name" || true
    cupsaccept "$name" || true
    echo "queue '$name' -> $uri"
}

for var in "${printer_vars[@]}"; do
    queue="${var#PRINTER_}"
    queue="${queue%_URI}"
    queue="$(echo "$queue" | tr '[:upper:]' '[:lower:]')"
    make_queue "$queue" "${!var}"
done

lpstat -v

wait "$CUPSD_PID"
