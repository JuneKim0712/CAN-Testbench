#!/usr/bin/env python3
"""
CalSol CAN Testbench - Unity Serial Stream Parser
Monitors an active UART serial port, extracts Unity test assertions,
and exits with code 0 (all pass) or code 1 (failure / timeout).
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("[-] Error: 'pyserial' is required. Install via: pip install pyserial", file=sys.stderr)
    sys.exit(1)


def parse_unity_stream(port: str, baud: int = 115200, timeout: float = 12.0, verbose: bool = False) -> int:
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"[-] Serial error on {port}: {e}", file=sys.stderr)
        return 1

    start_time = time.time()
    passed = False
    summary = ""

    while time.time() - start_time < timeout:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        if verbose:
            print(f"  [RAW] {line}")

        if ":PASS" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            print(f"    ✓ {test_name}")
        elif ":FAIL" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            print(f"    ✗ {test_name} (FAILED)")
            print(f"      {line}")
        elif "Tests" in line and "Failures" in line:
            summary = line
            if "0 Failures" in line:
                passed = True
            break

    if passed:
        print(f"\n[+] {summary} (ALL PASSED)")
        return 0
    elif summary:
        print(f"\n[-] {summary} (FAILED)")
        return 1
    else:
        print(f"\n[-] Timed out ({timeout}s) waiting for Unity test output.")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Parse Unity unit test results over serial.")
    parser.add_argument("--port", "-p", required=True, help="Serial port device path (e.g. /dev/esp32_johnathan)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--timeout", "-t", type=float, default=12.0, help="Timeout in seconds (default: 12.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print raw serial stream lines")

    args = parser.parse_args()
    exit_code = parse_unity_stream(args.port, args.baud, args.timeout, args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
