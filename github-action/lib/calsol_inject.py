#!/usr/bin/env python3
"""
CalSol Remote CAN Packet Injector CLI
Injects CAN frames via the CAN Bridge Daemon.
"""

import sys
import time
import json
import socket
import argparse


def connect(sock_path: str, tcp: str | None = None) -> socket.socket:
    if tcp:
        host, port = tcp.split(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, int(port)))
        return s
    if hasattr(socket, "AF_UNIX"):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        return s
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 5555))
    return s


def parse_id(val: str) -> int:
    return int(val, 16 if val.lower().startswith("0x") else 10)


def main():
    parser = argparse.ArgumentParser(description="CalSol Remote CAN Injector")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix socket path")
    parser.add_argument("--tcp", help="TCP address (host:port)")
    parser.add_argument("--id", required=True, type=parse_id, help="CAN ID (e.g. 0x123 or 291)")
    parser.add_argument("--data", default="", help="Hex data payload (e.g. DEADBEEF)")
    parser.add_argument("--rate", type=float, default=0.0, help="Rate in Hz (0 = one-shot)")
    parser.add_argument("--count", type=int, default=1, help="Number of frames (0 = infinite if rate > 0)")
    args = parser.parse_args()

    s = connect(args.socket, args.tcp)
    clean_hex = args.data.replace(" ", "").replace("0x", "")
    req = json.dumps({"cmd": "inject", "id": args.id, "data": clean_hex}) + "\n"
    payload = req.encode("utf-8")

    sent = 0
    interval = (1.0 / args.rate) if args.rate > 0 else 0

    try:
        while True:
            s.sendall(payload)
            sent += 1
            print(f"[+] Injected #{sent}: ID=0x{args.id:03X} Data={clean_hex.upper() or 'empty'}")
            if args.rate == 0 or (args.count > 0 and sent >= args.count):
                break
            time.sleep(interval)
    finally:
        s.close()
        print(f"[*] Done. Sent {sent} frames.")


if __name__ == "__main__":
    main()
