#!/usr/bin/env bash
# ==============================================================================
# CalSol CAN Testbench - Bash Client Wrapper
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.json"

PI_HOST="stolerpi"
DEFAULT_BOARD="esp32_johnathan"
STAGING_DIR="~/calsol/staging"

# Parse config.json if jq is available
if command -v jq >/dev/null 2>&1 && [ -f "$CONFIG_FILE" ]; then
    PI_HOST="$(jq -r '.host // "stolerpi"' "$CONFIG_FILE")"
    DEFAULT_BOARD="$(jq -r '.default_board // "esp32_johnathan"' "$CONFIG_FILE")"
    STAGING_DIR="$(jq -r '.staging_dir // "~/calsol/staging"' "$CONFIG_FILE")"
fi

ACTION="$1"
BOARD="${2:-$DEFAULT_BOARD}"
BIN="${3:-build/${BOARD}.bin}"

case "$ACTION" in
    flash)
        if [ ! -f "$BIN" ]; then
            echo "[-] Error: Binary not found at $BIN. Run your build step first!"
            exit 1
        fi
        echo "[1/2] Syncing $BIN to ${PI_HOST}..."
        ssh "$PI_HOST" "mkdir -p ${STAGING_DIR}"
        scp "$BIN" "${PI_HOST}:${STAGING_DIR}/$(basename "$BIN")"
        echo "[2/2] Flashing ${BOARD} on remote testbench..."
        ssh -t "$PI_HOST" "cal-flash ${BOARD} ${STAGING_DIR}/$(basename "$BIN")"
        ;;

    test)
        TEST_BIN="${3:-build/unit_tests.bin}"
        if [ ! -f "$TEST_BIN" ]; then
            echo "[-] Error: Test binary not found at $TEST_BIN."
            exit 1
        fi
        echo "[1/2] Syncing $TEST_BIN to ${PI_HOST}..."
        ssh "$PI_HOST" "mkdir -p ${STAGING_DIR}"
        scp "$TEST_BIN" "${PI_HOST}:${STAGING_DIR}/$(basename "$TEST_BIN")"
        echo "[2/2] Running automated Unity tests on ${BOARD}..."
        ssh "$PI_HOST" "cal-test ${BOARD} ${STAGING_DIR}/$(basename "$TEST_BIN")"
        ;;

    monitor)
        echo "[*] Connecting to serial console on ${BOARD} (Ctrl+] to exit)..."
        ssh -t "$PI_HOST" "tio /dev/${BOARD} -b 115200 || python3 -m serial.tools.miniterm /dev/${BOARD} 115200"
        ;;

    status)
        ssh "$PI_HOST" "cal-status 2>/dev/null || ls -la /dev/esp32* /dev/calsol* 2>/dev/null"
        ;;

    powercycle)
        echo "[*] Power-cycling USB testbench hubs on ${PI_HOST}..."
        ssh "$PI_HOST" "esp32-powercycle || cal-powercycle"
        ;;

    *)
        echo "CalSol CAN Testbench Client"
        echo "Usage: calsol.sh {flash|test|monitor|status|powercycle} [board_name] [binary_path]"
        echo "Default board: ${DEFAULT_BOARD}"
        exit 1
        ;;
esac
