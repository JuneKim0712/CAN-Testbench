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
    if not 0 <= args.id <= 0x7FF or args.rate < 0 or args.count < 0:
        parser.error("Use standard ID 0..0x7FF and nonnegative rate/count")

    clean_hex = args.data.replace(" ", "").replace("0x", "")
    try:
        if len(bytes.fromhex(clean_hex)) > 8:
            raise ValueError("payload exceeds 8 bytes")
    except ValueError as error:
        parser.error(str(error))
    req = json.dumps({"cmd": "inject", "id": args.id, "data": clean_hex}) + "\n"
    payload = req.encode("utf-8")

    s = connect(args.socket, args.tcp)
    s.settimeout(2)
    reader = s.makefile("rb")
    sent = 0
    interval = (1.0 / args.rate) if args.rate > 0 else 0

    try:
        while True:
            s.sendall(payload)
            deadline = time.monotonic() + 2
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Bridge acknowledgment deadline exceeded")
                s.settimeout(remaining)
                line = reader.readline(65537)
                if not line or len(line) > 65536 or not line.endswith(b"\n"):
                    raise RuntimeError("Missing or oversized bridge acknowledgment")
                event = json.loads(line)
                if "status" not in event:
                    continue
                if event["status"] != "ok":
                    raise RuntimeError(f"Injection rejected: {event}")
                break
            sent += 1
            print(f"[+] Request accepted #{sent}: ID=0x{args.id:03X} Data={clean_hex.upper() or 'empty'} (DUT reception not confirmed)")
            if args.rate == 0 or (args.count > 0 and sent >= args.count):
                break
            time.sleep(interval)
    finally:
        reader.close()
        s.close()
        print(f"[*] Done. Sent {sent} frames.")


if __name__ == "__main__":
    main()
