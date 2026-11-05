#!/usr/bin/env python3
"""
CalSol Panic & Crash Backtrace Auto-Decoder
Detects ESP32 Guru Meditation Errors, aborts, and panics in serial logs.
Uses xtensa-esp32s3-elf-addr2line to decode raw hexadecimal addresses into
exact C source files, function names, and line numbers.
"""

import os
import sys
import re
import glob
import shutil
import subprocess
import argparse
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CRASH_PATTERNS = [
    r"Guru Meditation Error:\s*(.*)",
    r"(abort\(\)\s*was called at.*)",
    r"(assert failed:\s*.*)",
    r"(Core\s+\d+\s+panic'ed\s*\(.*?\))"
]

BACKTRACE_REGEX = re.compile(r"Backtrace:\s+((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)")

def find_addr2line():
    # 1. Check in PATH
    for name in ["xtensa-esp32s3-elf-addr2line", "xtensa-esp32-elf-addr2line", "addr2line"]:
        path = shutil.which(name)
        if path:
            return path

    # 2. Search Espressif tools directory in ~/.espressif
    home = os.path.expanduser("~")
    search_path = os.path.join(home, ".espressif", "tools", "**", "*addr2line*")
    matches = glob.glob(search_path, recursive=True)
    for m in matches:
        if os.path.isfile(m) and os.access(m, os.X_OK):
            return m

    return None

def scan_log_for_crash(log_content):
    crash_reason = None
    for line in log_content.splitlines():
        for pat in CRASH_PATTERNS:
            match = re.search(pat, line)
            if match:
                crash_reason = match.group(1).strip()
                break
        if crash_reason:
            break

    # Look for Backtrace
    bt_match = BACKTRACE_REGEX.search(log_content)
    addresses = []
    if bt_match:
        pairs = bt_match.group(1).strip().split()
        for p in pairs:
            if ":" in p:
                pc_addr = p.split(":")[0]
                addresses.append(pc_addr)

    return crash_reason, addresses

def decode_backtrace(addr2line_bin, elf_file, addresses):
    if not addr2line_bin or not os.path.exists(elf_file) or not addresses:
        return []

    cmd = [addr2line_bin, "-pfia", "-e", elf_file] + addresses
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        
        frames = []
        for idx, line in enumerate(lines):
            addr_match = re.match(r"(0x[0-9a-fA-F]+):\s*(.*?)\s+at\s+(.*)", line)
            if addr_match:
                frames.append({
                    "frame": f"#{idx}",
                    "address": addr_match.group(1),
                    "function": addr_match.group(2),
                    "location": addr_match.group(3)
                })
            else:
                frames.append({
                    "frame": f"#{idx}",
                    "address": addresses[idx] if idx < len(addresses) else "",
                    "function": line,
                    "location": "unknown"
                })
        return frames
    except Exception as e:
        print(f"[-] addr2line execution failed: {e}")
        return []

def format_crash_markdown(crash_reason, frames, elf_file):
    md = []
    md.append("### Firmware Crash Post-Mortem & Decoded Stack Backtrace\n")
    if crash_reason:
        md.append(f"> **Panic Reason:** `{crash_reason}`\n")
    else:
        md.append("> **Panic Detected:** An unhandled hardware fault or FreeRTOS abort occurred.\n")

    if frames:
        md.append("| Frame | Program Counter (PC) | Function Name | Source Location |")
        md.append("| :---: | :---: | :--- | :--- |")
        for f in frames:
            md.append(f"| **{f['frame']}** | `{f['address']}` | `{f['function']}` | `{f['location']}` |")
        md.append("")
    else:
        md.append("*No decoded backtrace frames available (symbols missing or addr2line not found).*")

    return "\n".join(md)

def main():
    parser = argparse.ArgumentParser(description="CalSol Crash & Backtrace Decoder")
    parser.add_argument("--log-file", required=True, help="Serial test log file")
    parser.add_argument("--elf-file", required=True, help="Target application ELF file")
    parser.add_argument("--output-json", help="Optional JSON crash report output")
    args = parser.parse_args()

    if not os.path.exists(args.log_file):
        print(f"[-] Log file {args.log_file} does not exist.")
        sys.exit(0)

    with open(args.log_file, "r", encoding="utf-8", errors="replace") as f:
        log_content = f.read()

    crash_reason, addresses = scan_log_for_crash(log_content)

    if not crash_reason and not addresses:
        sys.exit(0)

    print(f"[!] Crash detected: {crash_reason or 'Backtrace found'}")
    print(f"[*] Raw Backtrace addresses: {addresses}")

    addr2line_bin = find_addr2line()
    if addr2line_bin:
        print(f"[*] Using addr2line: {addr2line_bin}")
    else:
        print("[-] Warning: addr2line tool not found.")

    frames = decode_backtrace(addr2line_bin, args.elf_file, addresses)
    md_report = format_crash_markdown(crash_reason, frames, args.elf_file)
    print("\n" + md_report)

    # Write to GITHUB_STEP_SUMMARY
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md_report + "\n")

    # Output JSON if requested
    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        report_data = {
            "has_crashed": True,
            "crash_reason": crash_reason,
            "raw_addresses": addresses,
            "frames": frames
        }
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"[+] Crash report JSON saved to {args.output_json}")

if __name__ == "__main__":
    main()
