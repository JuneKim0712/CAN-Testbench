#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: Hardware Flashing Runner with Mutex Locking
# Usage: cal-flash <board_name> <binary_path> [flash_offset]
# ==============================================================================

set -e

BOARD="$1"
BIN_FILE="$2"
OFFSET="${3:-0x10000}"

if [ -z "$BOARD" ] || [ -z "$BIN_FILE" ]; then
    echo "Usage: $0 <board_name> <binary_path> [offset]"
    echo "Example: $0 esp32_johnathan build/app.bin"
    exit 1
fi

if [ ! -f "$BIN_FILE" ]; then
    echo "[-] Error: Binary not found at $BIN_FILE"
    exit 1
fi

# Resolve device path
DEVICE=""
for dev_candidate in "/dev/${BOARD}" "/dev/esp32_${BOARD}" "/dev/calsol_${BOARD}"; do
    if [ -e "$dev_candidate" ]; then
        DEVICE="$dev_candidate"
        break
    fi
done

if [ -z "$DEVICE" ]; then
    echo "[-] Error: Device for '$BOARD' not found in /dev"
    exit 1
fi

# Lock directory (prefer /var/lock, fallback to ~/.calsol/locks)
LOCK_DIR="/var/lock"
[ ! -w "$LOCK_DIR" ] && LOCK_DIR="${HOME}/.calsol/locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="${LOCK_DIR}/calsol_${BOARD}.lock"

# Mutex acquisition using flock
exec 200>"$LOCK_FILE"
echo "[*] Requesting lock for board '${BOARD}'..."
if ! flock -w 15 200; then
    LOCK_OWNER=$(fuser "$LOCK_FILE" 2>/dev/null || echo "another process")
    echo "[-] ERROR: Board '${BOARD}' is currently locked by PID: ${LOCK_OWNER}!"
    exit 1
fi

echo "[+] Lock granted. Flashing ${BOARD} (${DEVICE}) at 921,600 baud..."

# Locate esptool
ESPTOOL_BIN="esptool.py"
if [ -f "${HOME}/.espressif/python_env/idf6.1_py3.13_env/bin/esptool.py" ]; then
    ESPTOOL_BIN="${HOME}/.espressif/python_env/idf6.1_py3.13_env/bin/esptool.py"
elif command -v esptool >/dev/null 2>&1; then
    ESPTOOL_BIN="$(command -v esptool)"
fi

python3 "$ESPTOOL_BIN" \
    --port "$DEVICE" \
    --baud 921600 \
    --before default_reset \
    --after hard_reset \
    write_flash "$OFFSET" "$BIN_FILE"

echo "[+] Flashing of '${BOARD}' completed successfully!"
