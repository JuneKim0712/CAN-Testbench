#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: On-Target Unity Unit Test Runner & Assertion Parser
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

# 1. Flash the test binary to target board
echo "=========================================================="
echo " [HIL Test] Flashing Unity Binary to ${BOARD}"
echo "=========================================================="
"$FLASH_RUNNER" "$BOARD" "$TEST_BIN"

# Resolve device path
DEVICE=""
for dev_candidate in "/dev/${BOARD}" "/dev/esp32_${BOARD}" "/dev/calsol_${BOARD}"; do
    if [ -e "$dev_candidate" ]; then
        DEVICE="$dev_candidate"
        break
    fi
done

echo "[*] Monitoring ${DEVICE} for Unity test completion (15s timeout)..."

python3 - <<EOF
import serial, sys, time

device = "$DEVICE"
try:
    ser = serial.Serial(device, 115200, timeout=1)
except Exception as e:
    print(f"[-] Could not open serial port {device}: {e}")
    sys.exit(1)

start_time = time.time()
passed = False
timed_out = True

while time.time() - start_time < 15:
    line = ser.readline().decode('utf-8', errors='replace').strip()
    if line:
        print("  | " + line)
    if "Tests 0 Failures 0 Ignored" in line:
        passed = True
        timed_out = False
        break
    if "Failures" in line and "0 Failures" not in line:
        passed = False
        timed_out = False
        break

if passed:
    print("\n[+] SUCCESS: All Unity unit tests passed on physical hardware!")
    sys.exit(0)
elif timed_out:
    print("\n[-] TIMEOUT: Target did not complete tests within 15 seconds.")
    sys.exit(1)
else:
    print("\n[-] FAILURE: One or more unit tests failed.")
    sys.exit(1)
EOF
