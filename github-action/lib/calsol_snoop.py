#!/usr/bin/env python3
"""
CalSol CAN Testbench: Remote CAN Snooper CLI
============================================
Connects to the CAN Bridge Daemon via Unix socket or TCP,
streaming live CAN bus traffic with microsecond timestamps.
"""

import sys
import json
import socket
import argparse
from datetime import datetime

def parse_id(val: str) -> int:
    return int(val, 16 if val.lower().startswith("0x") else 10)

def main():
    parser = argparse.ArgumentParser(description="CalSol Remote CAN Snooper")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp", help="Connect via TCP (host:port, e.g. 100.120.92.102:5555)")
    parser.add_argument("--id", type=parse_id, help="Filter for a specific CAN ID")
    parser.add_argument("--count", type=int, default=0, help="Exit after receiving N frames (0 = continuous)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON events")

    args = parser.parse_args()

    sock = None
    if args.tcp:
        host, port = args.tcp.split(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))
        print(f"[*] Connected to CAN bridge via TCP at {args.tcp}")
    else:
        if not hasattr(socket, "AF_UNIX"):
            print("[-] Unix sockets not supported on this platform. Use --tcp host:port.")
            sys.exit(1)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(args.socket)
        print(f"[*] Connected to CAN bridge via Unix socket: {args.socket}")

    print("----------------------------------------------------------------------")
    print(" Timestamp      Dir  CAN ID  DLC  Payload Data")
    print("----------------------------------------------------------------------")

    received = 0
    buf = ""
    try:
        while True:
            data = sock.recv(2048)
            if not data:
                break
            buf += data.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("event") != "frame":
                        continue

                    can_id = event.get("id")
                    if args.id is not None and can_id != args.id:
                        continue

                    received += 1
                    if args.json:
                        print(line)
                    else:
                        ts = datetime.fromtimestamp(event.get("timestamp", 0)).strftime("%H:%M:%S.%f")[:-3]
                        direction = event.get("direction", "rx").upper()
                        id_hex = event.get("id_hex", f"0x{can_id:03X}")
                        dlc = event.get("dlc", 0)
                        raw_data = event.get("data", "")
                        # Space-separate hex bytes
                        spaced_data = " ".join(raw_data[i:i+2] for i in range(0, len(raw_data), 2)).upper()
                        print(f"[{ts}]  {direction:2}   {id_hex:>6}   {dlc}    {spaced_data}")

                    if args.count > 0 and received >= args.count:
                        return
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print(f"\n[*] Stopped snooper. Total frames captured: {received}")

if __name__ == "__main__":
    main()
