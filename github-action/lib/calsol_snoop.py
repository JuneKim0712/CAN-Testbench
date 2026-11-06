#!/usr/bin/env python3
"""
CalSol Remote CAN Snooper CLI
Streams live CAN traffic from the CAN Bridge Daemon.
"""

import sys
import json
import socket
import argparse
from datetime import datetime


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
    parser = argparse.ArgumentParser(description="CalSol Remote CAN Snooper")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix socket path")
    parser.add_argument("--tcp", help="TCP address (host:port)")
    parser.add_argument("--id", type=parse_id, help="Filter for specific CAN ID")
    parser.add_argument("--count", type=int, default=0, help="Exit after N frames (0 = continuous)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON events")
    args = parser.parse_args()

    s = connect(args.socket, args.tcp)
    print("Timestamp      Dir  CAN ID  DLC  Payload Data")
    print("-" * 55)

    received = 0
    buf = ""
    try:
        while True:
            data = s.recv(2048)
            if not data:
                break
            buf += data.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("event") != "frame":
                        continue
                    cid = ev.get("id")
                    if args.id is not None and cid != args.id:
                        continue
                    received += 1
                    if args.json:
                        print(line)
                    else:
                        ts = datetime.fromtimestamp(ev.get("timestamp", 0)).strftime("%H:%M:%S.%f")[:-3]
                        d = ev.get("direction", "rx").upper()
                        raw = ev.get("data", "")
                        spaced = " ".join(raw[i:i+2] for i in range(0, len(raw), 2)).upper()
                        print(f"[{ts}]  {d:2}   0x{cid:03X}    {ev.get('dlc', 0)}    {spaced}")

                    if args.count > 0 and received >= args.count:
                        return
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        s.close()
        print(f"\n[*] Stopped. Total frames captured: {received}")


if __name__ == "__main__":
    main()
