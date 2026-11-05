#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: On-Target Unity Unit Test Runner (Concise Mode)
# Usage: cal-test <board_name> <test_binary_path>
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

# 1. Flash the test binary
"$FLASH_RUNNER" "$BOARD" "$TEST_BIN"

# Resolve device path
DEVICE=""
for dev_candidate in "/dev/${BOARD}" "/dev/esp32_${BOARD}" "/dev/calsol_${BOARD}"; do
    if [ -e "$dev_candidate" ]; then
        DEVICE="$dev_candidate"
        break
    fi
done

echo "[*] Running Unity tests on ${BOARD}..."

python3 - <<EOF
import serial, sys, time

device = "$DEVICE"
try:
    ser = serial.Serial(device, 115200, timeout=0.5)
except Exception as e:
    print(f"[-] Could not open serial port {device}: {e}")
    sys.exit(1)

start_time = time.time()
passed = False
summary = ""

while time.time() - start_time < 12:
    line = ser.readline().decode('utf-8', errors='replace').strip()
    if not line:
        continue
    if ":PASS" in line:
        parts = line.split(":")
        name = parts[-2] if len(parts) >= 2 else line
        print(f"    ✓ {name}")
    elif ":FAIL" in line:
        parts = line.split(":")
        name = parts[-2] if len(parts) >= 2 else line
        print(f"    ✗ {name} (FAILED)")
        print(f"      {line}")
    elif "Tests" in line and "Failures" in line:
        summary = line
        if "0 Failures" in line:
            passed = True
        break

if passed:
    print(f"\n[+] {summary} (ALL PASSED)")
    sys.exit(0)
elif summary:
    print(f"\n[-] {summary} (FAILED)")
    sys.exit(1)
else:
    print("\n[-] Timed out waiting for test completion.")
    sys.exit(1)
EOF
