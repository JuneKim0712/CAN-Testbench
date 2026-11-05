#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: On-Target Unity Unit Test Runner (Concise Mode)
# Pure Bash orchestrator that delegates serial parsing to lib/unity_parser.py
# ==============================================================================

set -e

BOARD="$1"
TEST_BIN="$2"

if [ -z "$BOARD" ] || [ -z "$TEST_BIN" ]; then
    echo "Usage: $0 <board_name> <test_binary_path>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASH_RUNNER="${SCRIPT_DIR}/cal-flash.sh"
[ ! -f "$FLASH_RUNNER" ] && FLASH_RUNNER="$(command -v cal-flash || echo "")"

if [ -z "$FLASH_RUNNER" ] || [ ! -f "$FLASH_RUNNER" ]; then
    echo "[-] Error: cal-flash runner not found."
    exit 1
fi

# 1. Flash the test binary via cal-flash
"$FLASH_RUNNER" "$BOARD" "$TEST_BIN"

# 2. Resolve device path
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

# 3. Call modular Python Unity parser
PARSER_BIN="${SCRIPT_DIR}/lib/unity_parser.py"
if [ ! -f "$PARSER_BIN" ]; then
    echo "[-] Error: unity_parser.py not found at $PARSER_BIN"
    exit 1
fi

echo "[*] Running Unity tests on ${BOARD}..."
python3 "$PARSER_BIN" --port "$DEVICE" --timeout 12
