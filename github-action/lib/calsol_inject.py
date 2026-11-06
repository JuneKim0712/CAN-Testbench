#!/usr/bin/env python3
"""
CalSol CAN Testbench: Remote CAN Packet Injector CLI
====================================================
Connects to the CAN Bridge Daemon and injects custom CAN frames
onto the physical bus (or virtual bus) with rate control.
"""

import sys
import time
import json
import socket
import argparse

def parse_id(val: str) -> int:
    return int(val, 16 if val.lower().startswith("0x") else 10)

def main():
    parser = argparse.ArgumentParser(description="CalSol Remote CAN Injector")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp", help="Connect via TCP (host:port, e.g. 100.120.92.102:5555)")
    parser.add_argument("--id", required=True, type=parse_id, help="CAN ID to inject (e.g. 0x123 or 291)")
    parser.add_argument("--data", default="", help="Hex data payload (e.g. DEADBEEF01020304)")
    parser.add_argument("--rate", type=float, default=0.0, help="Periodic transmission rate in Hz (0 = one-shot)")
    parser.add_argument("--count", type=int, default=1, help="Number of frames to transmit (0 = infinite if rate > 0)")

    args = parser.parse_args()

    sock = None
    if args.tcp:
        host, port = args.tcp.split(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))
    else:
        if not hasattr(socket, "AF_UNIX"):
            print("[-] Unix sockets not supported on this platform. Use --tcp host:port.")
            sys.exit(1)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(args.socket)

    clean_hex = args.data.replace(" ", "").replace("0x", "")
    req = {
        "cmd": "inject",
        "id": args.id,
        "data": clean_hex
    }
    payload_line = (json.dumps(req) + "\n").encode("utf-8")

    sent = 0
    interval = (1.0 / args.rate) if args.rate > 0 else 0

    try:
        while True:
            sock.sendall(payload_line)
            sent += 1
            print(f"[+] Injected frame #{sent}: ID=0x{args.id:03X} Data={clean_hex.upper() or 'empty'}")

            if args.rate == 0 or (args.count > 0 and sent >= args.count):
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print(f"[*] Injection complete. Total frames sent: {sent}")

if __name__ == "__main__":
    main()
