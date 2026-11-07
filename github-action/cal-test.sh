#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench: Automated On-Target Unit Test & Live CAN Runner
# Designed for both GitHub Actions (CI) and local bench engineering.
# Supports per-folder testbench.json configurations and live CAN tapping.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# GitHub Actions log grouping helpers
gh_group() {
    if [ -n "$GITHUB_ACTIONS" ]; then
        echo "::group::$1"
    else
        echo "=================================================="
        echo " $1"
        echo "=================================================="
    fi
}
gh_endgroup() {
    if [ -n "$GITHUB_ACTIONS" ]; then
        echo "::endgroup::"
    fi
}

# 1. Resolve target directory or binary
INPUT_TARGET="${1:-pedals_fw/test}"
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
TIMEOUT="${CLI_TIMEOUT:-${CONFIG_TIMEOUT:-15}}"
BAUD="${CONFIG_BAUD:-921600}"
SUBSYSTEM_SLUG="${CONFIG_NAME:-$(basename "$TARGET")}"
CAN_DEBUGGER_PORT="/dev/esp32_ahmed"

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
    # Dedicated CAN Debugger (/dev/esp32_ahmed / ttyACM0) is permanently reserved.
    # Only probe valid DUT candidate ports:
    for candidate in "/dev/steering" "/dev/esp32_johnathan" "/dev/bms" "/dev/ttyACM1"; do
        if [ "$candidate" != "$CAN_DEBUGGER_PORT" ] && [ -e "$candidate" ]; then
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

echo "=================================================="
echo "CalSol Hardware Testbench: ${SUBSYSTEM_SLUG}"
echo " DUT Port:     ${PORT} (${BOARD_NAME})"
echo " Debugger Port: ${CAN_DEBUGGER_PORT}"
echo " Target Path:  ${TARGET}"
echo " Flashing:     ${BAUD} baud"
echo " Test Timeout: ${TIMEOUT}s"
echo "=================================================="

# 5. Build Firmware (Host compilation does not require hardware serial lock)
if [ -d "$TARGET" ]; then
    cd "$TARGET"
    gh_group "Building Firmware (${SUBSYSTEM_SLUG})"
    export IDF_CCACHE_ENABLE=1
    export CCACHE_DIR="${HOME}/.ccache"
    export CCACHE_BASEDIR="$REPO_ROOT"
    export CCACHE_NOHASHDIR=1
    export CCACHE_SLOPPINESS="time_macros,file_macro,include_file_mtime"

    # Fast target resolution: skip redundant set-target if target is already configured
    if [ ! -f "sdkconfig" ] && [ ! -f "sdkconfig.defaults" ]; then
        idf.py set-target esp32s3 > "$LOG_DIR/build.log" 2>&1
    fi
    if idf.py build > "$LOG_DIR/build.log" 2>&1; then
        echo "[+] Build completed successfully."
    else
        echo "[-] Build failed!"
        cat "$LOG_DIR/build.log"
        gh_endgroup
        exit 1
    fi
    gh_endgroup

    # Stage trackside flashable binaries
    ARTIFACTS_DIR="${TARGET}/build/artifacts"
    mkdir -p "$ARTIFACTS_DIR"
    cp -f build/*.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/*.elf "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/bootloader/bootloader.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/partition_table/partition-table.bin "$ARTIFACTS_DIR/" 2>/dev/null || true
    cp -f build/flasher_args.json "$ARTIFACTS_DIR/" 2>/dev/null || true
fi

# 6. Ensure persistent CAN bridge daemon is listening BEFORE flashing DUT so boot traffic is never lost
if [ -S "/tmp/calsol_can.sock" ]; then
    if ! python3 -c "import socket; s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect('/tmp/calsol_can.sock'); s.close()" 2>/dev/null; then
        rm -f "/tmp/calsol_can.sock" 2>/dev/null || true
    fi
fi

if [ ! -S "/tmp/calsol_can.sock" ] && [ -e "$CAN_DEBUGGER_PORT" ]; then
    echo "[*] Launching permanent CAN Debugger daemon on ${CAN_DEBUGGER_PORT} before DUT boot..."
    python3 "${SCRIPT_DIR}/lib/can_bridge_daemon.py" \
        --port "$CAN_DEBUGGER_PORT" \
        --unix-socket "/tmp/calsol_can.sock" \
        --tcp-port 5555 \
        --ws-port 8765 \
        --json-out "${REPO_ROOT}/web/data/live_stream.json" > /tmp/calsol_can_daemon.log 2>&1 &
    sleep 0.8
fi

# 7. Unified Hardware Mutex Lock (Derived from resolved canonical device path)
REAL_PORT=$(readlink -f "$PORT" 2>/dev/null || realpath "$PORT" 2>/dev/null || echo "$PORT")
PORT_TAG=$(echo "$REAL_PORT" | tr '/' '_')
LOCK_DIR="/tmp/calsol_locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="${LOCK_DIR}/hw${PORT_TAG}.lock"

exec 200>"$LOCK_FILE"
if ! flock -w 30 200; then
    echo "[-] ERROR: Board '${BOARD_NAME}' (${PORT} -> ${REAL_PORT}) is currently in use by another process!"
    exit 1
fi

# 8. Flash Silicon
if [ -d "$TARGET" ]; then
    gh_group "Flashing Silicon (${BOARD_NAME} @ ${BAUD} baud)"
    # Try high-speed app partition flashing first; fallback to full flash if needed
    if idf.py -p "$PORT" -b "$BAUD" app-flash > "$LOG_DIR/flash.log" 2>&1; then
        echo "[+] Fast differential app-flash succeeded."
    elif idf.py -p "$PORT" -b "$BAUD" flash > "$LOG_DIR/flash.log" 2>&1; then
        echo "[+] Full partition flash succeeded."
    else
        echo "[-] Flashing failed!"
        cat "$LOG_DIR/flash.log"
        gh_endgroup
        exit 1
    fi
    gh_endgroup
elif [ -f "$TARGET" ]; then
    gh_group "Flashing Pre-built Binary (${BOARD_NAME})"
    if esptool.py --port "$PORT" --baud "$BAUD" write_flash 0x10000 "$TARGET" > "$LOG_DIR/flash.log" 2>&1; then
        echo "[+] Flash succeeded."
    else
        echo "[-] Flash failed!"
        cat "$LOG_DIR/flash.log"
        gh_endgroup
        exit 1
    fi
    gh_endgroup
fi

# 9. Parse Unity test results over serial & live CAN stream
PARSER="${SCRIPT_DIR}/lib/unity_parser.py"
SERIAL_LOG="${LOG_DIR}/${SUBSYSTEM_SLUG}_serial.log"
RESULTS_JSON="${LOG_DIR}/${SUBSYSTEM_SLUG}_test_results.json"
CAN_TRACE_FILE="${LOG_DIR}/${SUBSYSTEM_SLUG}_can_trace.jsonl"

gh_group "On-Target Silicon Execution & Live CAN Stream (${SUBSYSTEM_SLUG})"
echo "[*] Monitoring DUT UART output & physical CAN bus traffic..."
set +e
python3 "$PARSER" \
    --port "$PORT" \
    --subsystem "$SUBSYSTEM_SLUG" \
    --timeout "$TIMEOUT" \
    --log-file "$SERIAL_LOG" \
    --output-json "$RESULTS_JSON" \
    --can-port "$CAN_DEBUGGER_PORT" \
    --can-trace-file "$CAN_TRACE_FILE"
TEST_EXIT_CODE=$?
set -e
gh_endgroup

# Note: The dedicated CAN bridge daemon (/dev/esp32_ahmed) is kept permanently
# active across runs to provide continuous 24/7 bus streaming to the web dashboard.

# Stage test results, serial logs, and CAN trace into artifacts
if [ -d "${TARGET}/build/artifacts" ]; then
    [ -f "$RESULTS_JSON" ] && cp -f "$RESULTS_JSON" "${TARGET}/build/artifacts/" 2>/dev/null || true
    [ -f "$SERIAL_LOG" ] && cp -f "$SERIAL_LOG" "${TARGET}/build/artifacts/" 2>/dev/null || true
    [ -f "$CAN_TRACE_FILE" ] && cp -f "$CAN_TRACE_FILE" "${TARGET}/build/artifacts/" 2>/dev/null || true
fi

# 8. Post-mortem Crash Decoding on Failure
ELF_FILE=""
if [ -d "$TARGET" ]; then
    ELF_FILE=$(ls "${TARGET}/build"/*.elf 2>/dev/null | head -n 1 || true)
fi

if [ "$TEST_EXIT_CODE" -ne 0 ] && [ -n "$ELF_FILE" ] && [ -f "$SERIAL_LOG" ]; then
    gh_group "Post-Mortem Crash Backtrace Decoder"
    CRASH_JSON="${LOG_DIR}/${SUBSYSTEM_SLUG}_crash_report.json"
    python3 "${SCRIPT_DIR}/lib/crash_decoder.py" \
        --log-file "$SERIAL_LOG" \
        --elf-file "$ELF_FILE" \
        --output-json "$CRASH_JSON" || true

    if [ -f "$CRASH_JSON" ] && [ -d "${TARGET}/build/artifacts" ]; then
        cp -f "$CRASH_JSON" "${TARGET}/build/artifacts/" 2>/dev/null || true
    fi
    gh_endgroup
fi

# Copy test result JSON into artifacts
if [ -f "$RESULTS_JSON" ] && [ -d "${TARGET}/build/artifacts" ]; then
    cp -f "$RESULTS_JSON" "${TARGET}/build/artifacts/" 2>/dev/null || true
fi

if [ "$TEST_EXIT_CODE" -ne 0 ]; then
    if [ -n "$GITHUB_ACTIONS" ]; then
        echo "::error file=${SUBSYSTEM_SLUG}::Hardware test failure detected on ${BOARD_NAME} (exit code ${TEST_EXIT_CODE})"
    fi
    exit "$TEST_EXIT_CODE"
fi

exit 0
