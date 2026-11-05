#!/usr/bin/env python3
"""
CalSol CAN Testbench - Unity Serial Stream Parser
Monitors an active UART serial port, extracts Unity test assertions,
formats output for both terminal and GitHub Actions ($GITHUB_STEP_SUMMARY),
records raw serial logs for crash post-mortem analysis, and outputs structured JSON.
"""

import argparse
import os
import sys
import time
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import serial
except ImportError:
    print("[-] Error: 'pyserial' is required. Install via: pip install pyserial", file=sys.stderr)
    sys.exit(1)


def parse_unity_stream(port: str, baud: int = 115200, timeout: float = 12.0, verbose: bool = False, log_file: str = None, output_json: str = None, subsystem: str = "") -> int:
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"[-] Serial error on {port}: {e}", file=sys.stderr)
        return 1

    start_time = time.time()
    passed = False
    summary = ""
    results = []  # List of tuples: (status, test_name, raw_line)
    all_raw_lines = []

    while time.time() - start_time < timeout:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        all_raw_lines.append(line)

        if verbose:
            print(f"  [RAW] {line}")

        if ":PASS" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            results.append(("PASS", test_name, line))
            print(f"    [PASS] {test_name}")
        elif ":FAIL" in line:
            parts = line.split(":")
            test_name = parts[-2] if len(parts) >= 2 else line
            results.append(("FAIL", test_name, line))
            print(f"    [FAIL] {test_name}")
            print(f"      {line}")
        elif "Tests" in line and "Failures" in line:
            summary = line
            if "0 Failures" in line:
                passed = True
            break

    # Save raw log file for crash decoder
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            with open(log_file, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(all_raw_lines) + "\n")
        except Exception as e:
            print(f"[-] Note: Failed to save test log file: {e}", file=sys.stderr)

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
                status_title = "Passed" if passed else "Failed"
                sub_title = f": {subsystem}" if subsystem else ""
                f.write(f"\n### CalSol Testbench Results ({status_title}){sub_title}\n\n")
                f.write(f"| Status | Test Function | Details |\n")
                f.write(f"| :---: | :--- | :--- |\n")
                for status, test_name, raw in results:
                    f.write(f"| {status} | `{test_name}` | `{raw}` |\n")
                if summary:
                    f.write(f"\n**Summary:** {summary}\n")
                else:
                    f.write(f"\n**Summary:** Timed out ({timeout}s) with no response from board.\n")
        except Exception as e:
            print(f"[-] Note: Could not write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    # Save structured JSON
    if output_json:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_json)), exist_ok=True)
            report_data = {
                "subsystem": subsystem if subsystem else port,
                "port": port,
                "passed": passed,
                "summary": summary if summary else f"Timed out ({timeout}s)",
                "total_assertions": len(results),
                "passed_count": sum(1 for s, _, _ in results if s == "PASS"),
                "failed_count": sum(1 for s, _, _ in results if s == "FAIL"),
                "tests": [{"status": s, "name": n, "details": d} for s, n, d in results]
            }
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
        except Exception as e:
            print(f"[-] Note: Could not save output JSON: {e}", file=sys.stderr)

    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description="Parse Unity unit test results over serial.")
    parser.add_argument("--port", "-p", required=True, help="Serial port device path (e.g. /dev/esp32_johnathan)")
    parser.add_argument("--subsystem", "-s", default="", help="Subsystem name (e.g. pedals_fw)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--timeout", "-t", type=float, default=12.0, help="Timeout in seconds (default: 12.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print raw serial stream lines")
    parser.add_argument("--log-file", help="Path to write complete raw serial logs")
    parser.add_argument("--output-json", help="Path to write structured JSON results")

    args = parser.parse_args()
    exit_code = parse_unity_stream(
        port=args.port,
        baud=args.baud,
        timeout=args.timeout,
        verbose=args.verbose,
        log_file=args.log_file,
        output_json=args.output_json,
        subsystem=args.subsystem
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
