#!/bin/bash
# Creates the raw ESC/POS queues from env vars, then runs cupsd in the foreground.
# Idempotent: lpadmin -p on an existing queue just updates it, so restarts are safe.
set -euo pipefail

: "${PRINTER_RECEIPT_URI:?PRINTER_RECEIPT_URI is required (e.g. socket://printer-ip:9100)}"
: "${PRINTER_KITCHEN_URI:?PRINTER_KITCHEN_URI is required (e.g. socket://printer-ip:9100)}"

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

make_queue receipt "$PRINTER_RECEIPT_URI"
make_queue kitchen "$PRINTER_KITCHEN_URI"

lpstat -v

wait "$CUPSD_PID"
