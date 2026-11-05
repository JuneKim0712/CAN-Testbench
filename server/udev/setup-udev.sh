#!/usr/bin/env bash
# Install CalSol udev rules on the Raspberry Pi host

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_FILE="${SCRIPT_DIR}/99-calsol.rules"
TARGET_DIR="/etc/udev/rules.d"

if [ "$EUID" -ne 0 ]; then
    echo "[-] Please run as root (sudo ./setup-udev.sh)"
    exit 1
fi

echo "[*] Installing udev rules to ${TARGET_DIR}..."
cp "$RULE_FILE" "${TARGET_DIR}/"

echo "[*] Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

echo "[+] Successfully installed CalSol udev rules!"
ls -la /dev/esp32_* /dev/calsol_* 2>/dev/null || true
