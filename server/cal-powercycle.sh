#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: Powercycle USB Hubs via uhubctl
# ==============================================================================

set -e

if ! command -v uhubctl >/dev/null 2>&1 && [ ! -x "/usr/sbin/uhubctl" ]; then
    echo "[-] Error: uhubctl is not installed or not in PATH."
    exit 1
fi

UHUBCTL="uhubctl"
[ -x "/usr/sbin/uhubctl" ] && UHUBCTL="/usr/sbin/uhubctl"

echo "[*] Powering down USB hubs (ports 2, 3, 4, 5)..."
for h in 2 3 4 5; do
    "$UHUBCTL" -l "$h" -a off 2>/dev/null || true
done

echo "[*] Waiting 3 seconds for power discharge..."
sleep 3

echo "[*] Powering up USB hubs..."
for h in 2 3 4 5; do
    "$UHUBCTL" -l "$h" -a on 2>/dev/null || true
done

echo "[+] USB Powercycle completed. Boards re-enumerating."
