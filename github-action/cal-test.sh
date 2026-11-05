#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench: Automated On-Target Unit Test Runner
# Designed for both GitHub Actions (CI) and local terminal execution.
# Supports per-folder testbench.json configurations.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 1. Resolve target directory or binary
INPUT_TARGET="${1:-lights_fw/test}"
CLI_PORT="${2}"
CLI_TIMEOUT="${3}"

if [ -d "${REPO_ROOT}/${INPUT_TARGET}" ]; then
    TARGET="${REPO_ROOT}/${INPUT_TARGET}"
elif [ -d "$INPUT_TARGET" ]; then
    TARGET="$(cd "$INPUT_TARGET" && pwd)"
elif [ -f "${REPO_ROOT}/${INPUT_TARGET}" ]; then
    TARGET="${REPO_ROOT}/${INPUT_TARGET}"
elif [ -f "$INPUT_TARGET" ]; then
    TARGET="$INPUT_TARGET"
else
    echo "[-] Error: Target path not found: ${INPUT_TARGET}"
    exit 1
fi

# 2. Check for folder-specific testbench.json configuration
CONFIG_FILE=""
if [ -d "$TARGET" ] && [ -f "${TARGET}/testbench.json" ]; then
    CONFIG_FILE="${TARGET}/testbench.json"
elif [ -d "$TARGET" ] && [ -f "$(dirname "$TARGET")/testbench.json" ]; then
    CONFIG_FILE="$(dirname "$TARGET")/testbench.json"
fi

CONFIG_PORT=""
CONFIG_TIMEOUT=""
CONFIG_BAUD=""
CONFIG_NAME=""

if [ -n "$CONFIG_FILE" ]; then
    echo "[*] Found subsystem testbench configuration: ${CONFIG_FILE}"
    CONFIG_PORT=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('port',''))" 2>/dev/null || true)
    CONFIG_TIMEOUT=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('timeout',''))" 2>/dev/null || true)
    CONFIG_BAUD=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('baud',''))" 2>/dev/null || true)
    CONFIG_NAME=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('name',''))" 2>/dev/null || true)
fi

PORT="${CLI_PORT:-$CONFIG_PORT}"
TIMEOUT="${CLI_TIMEOUT:-${CONFIG_TIMEOUT:-12}}"
BAUD="${CONFIG_BAUD:-921600}"

# 3. Source ESP-IDF if idf.py is not in PATH
if ! command -v idf.py >/dev/null 2>&1; then
    if [ -f "/opt/esp-idf/export.sh" ]; then
        source /opt/esp-idf/export.sh >/dev/null 2>&1
    elif [ -f "${HOME}/esp/esp-idf/export.sh" ]; then
        source "${HOME}/esp/esp-idf/export.sh" >/dev/null 2>&1
    else
        echo "[-] Error: idf.py not found and could not locate export.sh in /opt/esp-idf or ~/esp/esp-idf."
        exit 1
    fi
fi

# 4. Validate or auto-detect serial port
if [ -n "$PORT" ] && [ ! -e "$PORT" ]; then
    echo "[-] Warning: Configured port '${PORT}' not currently connected. Falling back to auto-detection..."
    PORT=""
fi

if [ -z "$PORT" ]; then
    for candidate in "/dev/steering" "/dev/esp32_johnathan" "/dev/bms" "/dev/esp32_ahmed" "/dev/ttyACM0" "/dev/ttyACM1"; do
        if [ -e "$candidate" ]; then
            PORT="$candidate"
            break
        fi
    done
fi

if [ -z "$PORT" ]; then
    echo "[-] Error: No ESP32 serial device found in /dev."
    exit 1
fi

BOARD_NAME="$(basename "$PORT")"
LOG_DIR="${SCRIPT_DIR}/.logs"
mkdir -p "$LOG_DIR"

# 5. Mutex lock on the hardware device to prevent concurrent flashing
LOCK_DIR="/tmp/calsol_locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="${LOCK_DIR}/${BOARD_NAME}.lock"
exec 200>"$LOCK_FILE"
if ! flock -w 15 200; then
    echo "[-] ERROR: Board '${BOARD_NAME}' is currently in use by another process!"
    exit 1
fi

echo "=================================================="
echo " CalSol Hardware Testbench: ${CONFIG_NAME:-$BOARD_NAME}"
echo " Port:    ${PORT} (${BOARD_NAME})"
echo " Target:  ${TARGET}"
echo " Baud:    ${BAUD}"
echo " Timeout: ${TIMEOUT}s"
echo "=================================================="

# 6. Build & Flash
if [ -d "$TARGET" ]; then
    cd "$TARGET"
    printf "[*] Building firmware... "
    [ ! -f "sdkconfig" ] && idf.py set-target esp32s3 > "$LOG_DIR/build.log" 2>&1
    if idf.py build > "$LOG_DIR/build.log" 2>&1; then
        echo "OK"
    else
        echo "FAILED"
        echo "=== Build Error Log ==="
        tail -n 30 "$LOG_DIR/build.log"
        exit 1
    fi

    printf "[*] Flashing %s (%s baud)... " "$BOARD_NAME" "$BAUD"
    if idf.py -p "$PORT" -b "$BAUD" flash > "$LOG_DIR/flash.log" 2>&1; then
        echo "OK"
    else
        echo "FAILED"
        echo "=== Flash Error Log ==="
        tail -n 30 "$LOG_DIR/flash.log"
        exit 1
    fi
elif [ -f "$TARGET" ]; then
    printf "[*] Flashing pre-built binary %s... " "$BOARD_NAME"
    if esptool.py --port "$PORT" --baud "$BAUD" write_flash 0x10000 "$TARGET" > "$LOG_DIR/flash.log" 2>&1; then
        echo "OK"
    else
        echo "FAILED"
        echo "=== Flash Error Log ==="
        tail -n 30 "$LOG_DIR/flash.log"
        exit 1
    fi
fi

# 7. Parse Unity test results over serial
PARSER="${SCRIPT_DIR}/lib/unity_parser.py"
echo "[*] Monitoring Unity test output (${TIMEOUT}s timeout)..."
python3 "$PARSER" --port "$PORT" --timeout "$TIMEOUT"
