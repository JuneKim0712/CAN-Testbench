#!/usr/bin/env python3
"""
CalSol CAN Testbench - Developer Client CLI
Modular CLI for remote flashing, monitoring, and testing.
"""

import argparse
import sys
from pathlib import Path

# Add package root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config_manager import load_config
from lib.transport import run_ssh, copy_file_to_host


def cmd_flash(args, config: dict):
    board = args.board or config["default_board"]
    bin_path = Path(args.binary) if args.binary else Path(f"build/{board}.bin")

    if not bin_path.exists():
        print(f"[-] Error: Binary not found at {bin_path}. Run build first!", file=sys.stderr)
        sys.exit(1)

    host = config["host"]
    remote_bin = f"{config['staging_dir']}/{bin_path.name}"

    print(f"[*] Syncing {bin_path.name} to {host}... ", end="", flush=True)
    copy_file_to_host(str(bin_path), host, remote_bin)
    print("OK")

    server_flash = f"{config.get('server_bin_dir', '~/CAN_TestBench/server')}/cal-flash.sh"
    cmd = f"{server_flash} {board} {remote_bin} || cal-flash {board} {remote_bin}"
    run_ssh(host, cmd, pty=True)


def cmd_test(args, config: dict):
    board = args.board or config["default_board"]
    bin_path = Path(args.binary) if args.binary else Path(f"build/unit_tests.bin")

    if not bin_path.exists():
        print(f"[-] Error: Test binary not found at {bin_path}.", file=sys.stderr)
        sys.exit(1)

    host = config["host"]
    remote_bin = f"{config['staging_dir']}/{bin_path.name}"

    print(f"[*] Syncing {bin_path.name} to {host}... ", end="", flush=True)
    copy_file_to_host(str(bin_path), host, remote_bin)
    print("OK")

    server_test = f"{config.get('server_bin_dir', '~/CAN_TestBench/server')}/cal-test.sh"
    cmd = f"{server_test} {board} {remote_bin} || cal-test {board} {remote_bin}"
    exit_code = run_ssh(host, cmd, pty=False, check=False)
    sys.exit(exit_code)


def cmd_monitor(args, config: dict):
    board = args.board or config["default_board"]
    host = config["host"]
    device = f"/dev/{board}" if not board.startswith("/dev/") else board

    print(f"[*] Serial monitor on {device} (Ctrl+] to exit):")
    cmd = f"tio {device} -b 115200 || python3 -m serial.tools.miniterm {device} 115200"
    run_ssh(host, cmd, pty=True, check=False)


def cmd_status(args, config: dict):
    host = config["host"]
    server_status = f"{config.get('server_bin_dir', '~/CAN_TestBench/server')}/cal-status.sh"
    cmd = f"{server_status} 2>/dev/null || cal-status 2>/dev/null || ls -la /dev/esp32* 2>/dev/null || true"
    run_ssh(host, cmd, pty=False, check=False)


def cmd_powercycle(args, config: dict):
    host = config["host"]
    print(f"[*] Power-cycling USB hubs on {host}... ", end="", flush=True)
    server_powercycle = f"{config.get('server_bin_dir', '~/CAN_TestBench/server')}/cal-powercycle.sh"
    cmd = f"{server_powercycle} || cal-powercycle || esp32-powercycle"
    run_ssh(host, cmd, pty=False, check=False)
    print("OK")


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description="CalSol CAN Testbench Client")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Flash
    p_flash = subparsers.add_parser("flash", help="Flash firmware binary to target board")
    p_flash.add_argument("board", nargs="?", default=config.get("default_board"), help="Target board name")
    p_flash.add_argument("--binary", "-b", help="Path to local binary (.bin)")

    # Test
    p_test = subparsers.add_parser("test", help="Flash and run automated Unity unit tests")
    p_test.add_argument("board", nargs="?", default=config.get("default_board"), help="Target board name")
    p_test.add_argument("--binary", "-b", help="Path to local test binary (.bin)")

    # Monitor
    p_mon = subparsers.add_parser("monitor", help="Open serial monitor to target board")
    p_mon.add_argument("board", nargs="?", default=config.get("default_board"), help="Target board name")

    # Status
    subparsers.add_parser("status", help="Check hardware board availability and locks")

    # Powercycle
    subparsers.add_parser("powercycle", help="Power-cycle USB hubs on testbench")

    args = parser.parse_args()

    actions = {
        "flash": cmd_flash,
        "test": cmd_test,
        "monitor": cmd_monitor,
        "status": cmd_status,
        "powercycle": cmd_powercycle
    }

    actions[args.action](args, config)


if __name__ == "__main__":
    main()
