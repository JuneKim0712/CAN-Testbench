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
SUBSYSTEM_SLUG="${CONFIG_NAME:-$(basename "$TARGET")}"

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
echo " CalSol Hardware Testbench: ${SUBSYSTEM_SLUG}"
echo " Port:    ${PORT} (${BOARD_NAME})"
echo " Target:  ${TARGET}"
echo " Baud:    ${BAUD}"
echo " Timeout: ${TIMEOUT}s"
echo "=================================================="

# 6. Build & Flash
if [ -d "$TARGET" ]; then
    cd "$TARGET"
    printf "[*] Building firmware (ccache enabled)... "
    export IDF_CCACHE_ENABLE=1
    export CCACHE_DIR="${HOME}/.ccache"
    [ ! -f "sdkconfig" ] && idf.py set-target esp32s3 > "$LOG_DIR/build.log" 2>&1
    if idf.py build > "$LOG_DIR/build.log" 2>&1; then
        echo "OK"
    else
        echo "FAILED"
        echo "=== Build Error Log ==="
        tail -n 30 "$LOG_DIR/build.log"
        exit 1
    fi

    # Feature B: Stage trackside flashable binaries
    ARTIFACTS_DIR="${TARGET}/build/artifacts"
    mkdir -p "$ARTIFACTS_DIR"
    cp -f build/*.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/*.elf "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/bootloader/bootloader.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/partition_table/partition-table.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/flasher_args.json "$ARTIFACTS_DIR/" 2>/dev/null || true

    printf "[*] Flashing %s (%s baud, fast app-flash)... " "$BOARD_NAME" "$BAUD"
    # Try high-speed app partition flashing first; fallback to full flash if needed
    if idf.py -p "$PORT" -b "$BAUD" app-flash > "$LOG_DIR/flash.log" 2>&1; then
        echo "OK"
    elif idf.py -p "$PORT" -b "$BAUD" flash > "$LOG_DIR/flash.log" 2>&1; then
        echo "OK (full flash fallback)"
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

# 7. Parse Unity test results over serial & Feature C Crash Decoding
PARSER="${SCRIPT_DIR}/lib/unity_parser.py"
SERIAL_LOG="${LOG_DIR}/${SUBSYSTEM_SLUG}_serial.log"
RESULTS_JSON="${LOG_DIR}/${SUBSYSTEM_SLUG}_test_results.json"

echo "[*] Monitoring Unity test output (${TIMEOUT}s timeout)..."
set +e
python3 "$PARSER" --port "$PORT" --timeout "$TIMEOUT" --log-file "$SERIAL_LOG" --output-json "$RESULTS_JSON"
TEST_EXIT_CODE=$?
set -e

# Feature C: If test failed or aborted, run crash decoder to extract backtrace
ELF_FILE=""
if [ -d "$TARGET" ]; then
    ELF_FILE=$(ls "${TARGET}/build"/*.elf 2>/dev/null | head -n 1 || true)
fi

if [ -n "$ELF_FILE" ] && [ -f "$SERIAL_LOG" ]; then
    CRASH_JSON="${LOG_DIR}/${SUBSYSTEM_SLUG}_crash_report.json"
    python3 "${SCRIPT_DIR}/lib/crash_decoder.py" \
        --log-file "$SERIAL_LOG" \
        --elf-file "$ELF_FILE" \
        --output-json "$CRASH_JSON" >/dev/null 2>&1 || true

    if [ -f "$CRASH_JSON" ] && [ -d "${TARGET}/build/artifacts" ]; then
        cp -f "$CRASH_JSON" "${TARGET}/build/artifacts/" 2>/dev/null || true
    fi
fi

# Copy test result JSON into artifacts if directory exists
if [ -f "$RESULTS_JSON" ] && [ -d "${TARGET}/build/artifacts" ]; then
    cp -f "$RESULTS_JSON" "${TARGET}/build/artifacts/" 2>/dev/null || true
fi

exit $TEST_EXIT_CODE
