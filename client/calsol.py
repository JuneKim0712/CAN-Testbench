#!/usr/bin/env python3
"""
CalSol CAN Testbench - Developer Client CLI
Cross-platform tool (Windows / macOS / Linux) for remote flashing, monitoring, and testing.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "host": "stolerpi",
        "remote_user": "jkim",
        "staging_dir": "~/calsol/staging",
        "server_bin_dir": "~/calsol/server",
        "default_board": "esp32_johnathan",
        "baud_rate": 921600
    }

def run_cmd(cmd, check=True):
    print(f"[*] Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)

def cmd_flash(args, config):
    board = args.board or config.get("default_board", "esp32_johnathan")
    bin_path = Path(args.binary) if args.binary else Path(f"build/{board}.bin")

    if not bin_path.exists():
        print(f"[-] Error: Binary not found at {bin_path}. Run your build step first!")
        sys.exit(1)

    host = config["host"]
    remote_staging = config["staging_dir"]
    remote_bin = f"{remote_staging}/{bin_path.name}"

    print(f"[1/2] Transferring {bin_path} -> {host}:{remote_bin}...")
    run_cmd(["ssh", host, f"mkdir -p {remote_staging}"])
    run_cmd(["scp", str(bin_path), f"{host}:{remote_bin}"])

    print(f"[2/2] Triggering remote flash on {board}...")
    run_cmd(["ssh", "-t", host, f"~/CAN-Testbench/server/cal-flash.sh {board} {remote_bin} || cal-flash {board} {remote_bin}"])

def cmd_test(args, config):
    board = args.board or config.get("default_board", "esp32_johnathan")
    bin_path = Path(args.binary) if args.binary else Path(f"build/unit_tests.bin")

    if not bin_path.exists():
        print(f"[-] Error: Test binary not found at {bin_path}.")
        sys.exit(1)

    host = config["host"]
    remote_staging = config["staging_dir"]
    remote_bin = f"{remote_staging}/{bin_path.name}"

    print(f"[1/2] Transferring test binary {bin_path} -> {host}...")
    run_cmd(["ssh", host, f"mkdir -p {remote_staging}"])
    run_cmd(["scp", str(bin_path), f"{host}:{remote_bin}"])

    print(f"[2/2] Running automated Unity tests on {board}...")
    res = subprocess.run(["ssh", host, f"~/CAN-Testbench/server/cal-test.sh {board} {remote_bin} || cal-test {board} {remote_bin}"])
    sys.exit(res.returncode)

def cmd_monitor(args, config):
    board = args.board or config.get("default_board", "esp32_johnathan")
    host = config["host"]
    device = f"/dev/{board}" if not board.startswith("/dev/") else board

    print(f"[*] Connecting to serial monitor on {device} (Press Ctrl+] to exit)...")
    run_cmd(["ssh", "-t", host, f"python3 -m serial.tools.miniterm {device} 115200 || tio {device} -b 115200"], check=False)

def cmd_status(args, config):
    host = config["host"]
    print(f"[*] Querying testbench status on {host}...")
    run_cmd(["ssh", host, "~/CAN-Testbench/server/cal-status.sh 2>/dev/null || cal-status 2>/dev/null || ls -la /dev/esp32* 2>/dev/null || true"])

def cmd_powercycle(args, config):
    host = config["host"]
    print(f"[*] Power-cycling USB testbench hubs on {host}...")
    run_cmd(["ssh", host, "esp32-powercycle || cal-powercycle"])

def main():
    config = load_config()
    parser = argparse.ArgumentParser(description="CalSol CAN Testbench Client CLI")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Flash
    p_flash = subparsers.add_parser("flash", help="Flash a binary to target ESP32 board")
    p_flash.add_argument("board", nargs="?", default=config.get("default_board"), help="Board name or /dev path")
    p_flash.add_argument("--binary", "-b", help="Path to local binary (.bin)")

    # Test
    p_test = subparsers.add_parser("test", help="Flash and run automated Unity unit tests")
    p_test.add_argument("board", nargs="?", default=config.get("default_board"), help="Board name or /dev path")
    p_test.add_argument("--binary", "-b", help="Path to local test binary (.bin)")

    # Monitor
    p_mon = subparsers.add_parser("monitor", help="Open serial monitor to target board")
    p_mon.add_argument("board", nargs="?", default=config.get("default_board"), help="Board name or /dev path")

    # Status
    subparsers.add_parser("status", help="Check hardware board availability and locks")

    # Powercycle
    subparsers.add_parser("powercycle", help="Hard power-cycle hung USB devices on the Pi")

    args = parser.parse_args()

    if args.action == "flash":
        cmd_flash(args, config)
    elif args.action == "test":
        cmd_test(args, config)
    elif args.action == "monitor":
        cmd_monitor(args, config)
    elif args.action == "status":
        cmd_status(args, config)
    elif args.action == "powercycle":
        cmd_powercycle(args, config)

if __name__ == "__main__":
    main()
