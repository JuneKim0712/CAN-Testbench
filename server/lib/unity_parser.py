#!/usr/bin/env python3
"""
CalSol CAN Testbench - Unity Serial Stream Parser
Monitors an active UART serial port, extracts Unity test assertions,
formats output for both terminal and GitHub Actions ($GITHUB_STEP_SUMMARY),
and exits with code 0 (all pass) or code 1 (failure / timeout).
"""

import argparse
import os
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
    results = []  # List of tuples: (status, test_name, raw_line)

    while time.time() - start_time < timeout:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        if verbose:
            print(f"  [RAW] {line}")

        if ":PASS" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            results.append(("PASS", test_name, line))
            print(f"    ✓ {test_name}")
        elif ":FAIL" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            results.append(("FAIL", test_name, line))
            print(f"    ✗ {test_name} (FAILED)")
            print(f"      {line}")
        elif "Tests" in line and "Failures" in line:
            summary = line
            if "0 Failures" in line:
                passed = True
            break

    # Terminal output
    if passed:
        print(f"\n[+] {summary} (ALL PASSED)")
    elif summary:
        print(f"\n[-] {summary} (FAILED)")
    else:
        print(f"\n[-] Timed out ({timeout}s) waiting for Unity test output.")

    # Write GitHub Step Summary if running in GitHub Actions
    gh_summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary_file:
        try:
            with open(gh_summary_file, "a", encoding="utf-8") as f:
                header_icon = "✅" if passed else "❌"
                status_title = "Passed" if passed else "Failed"
                f.write(f"\n### {header_icon} CalSol Testbench Results ({status_title})\n\n")
                f.write(f"| Status | Test Function | Details |\n")
                f.write(f"| :---: | :--- | :--- |\n")
                for status, test_name, raw in results:
                    icon = "✅" if status == "PASS" else "❌"
                    f.write(f"| {icon} | `{test_name}` | `{raw}` |\n")
                if summary:
                    f.write(f"\n**Summary:** {summary}\n")
                else:
                    f.write(f"\n**Summary:** Timed out ({timeout}s) with no response from board.\n")
        except Exception as e:
            print(f"[-] Note: Could not write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    return 0 if passed else 1


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
