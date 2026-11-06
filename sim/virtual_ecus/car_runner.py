#!/usr/bin/env python3
"""
CalSol Virtual Vehicle Simulator: Car Runner
Runs software-defined Virtual ECUs (BMS, Motor, Steering) in a single loop.
"""

import os
import sys
import time
import json
import socket
import select
import signal
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sim.virtual_ecus.virtual_bms import VirtualBMS
from sim.virtual_ecus.virtual_motor import VirtualMotorController
from sim.virtual_ecus.virtual_steering import VirtualSteering


def connect_socket(socket_path: str, tcp: str | None = None) -> socket.socket:
    if tcp:
        host, port = tcp.split(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, int(port)))
        return s
    if hasattr(socket, "AF_UNIX") and os.path.exists(socket_path):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(socket_path)
        return s
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 5555))
    return s


def main():
    parser = argparse.ArgumentParser(description="CalSol Virtual Car Runner")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp", help="TCP address (host:port)")
    parser.add_argument("--no-bms", action="store_true", help="Disable Virtual BMS")
    parser.add_argument("--no-motor", action="store_true", help="Disable Virtual Motor")
    parser.add_argument("--no-steering", action="store_true", help="Disable Virtual Steering")
    parser.add_argument("--duration", type=float, default=0.0, help="Run duration in seconds (0 = infinite)")
    args = parser.parse_args()

    ecus = []
    if not args.no_bms:
        ecus.append(VirtualBMS())
    if not args.no_motor:
        ecus.append(VirtualMotorController())
    if not args.no_steering:
        ecus.append(VirtualSteering())

    sock = connect_socket(args.socket, args.tcp)
    sock.setblocking(False)
    print(f"[*] Virtual Car Runner connected with {len(ecus)} active ECUs.")

    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    buf = ""
    start_t = time.time()
    last_tick = time.time()

    try:
        while running:
            now = time.time()
            if args.duration > 0 and (now - start_t) >= args.duration:
                break

            dt = now - last_tick
            last_tick = now

            # 1. Read incoming CAN traffic from daemon
            try:
                readable, _, _ = select.select([sock], [], [], 0.01)
                if readable:
                    data = sock.recv(2048)
                    if data:
                        buf += data.decode("utf-8", errors="replace")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            if line.strip():
                                ev = json.loads(line)
                                if ev.get("event") == "frame":
                                    can_id = ev.get("id", 0)
                                    payload = bytes.fromhex(ev.get("data", ""))
                                    for ecu in ecus:
                                        ecu.on_frame(can_id, payload)
            except Exception:
                pass

            # 2. Step ECUs and dispatch outgoing frames
            for ecu in ecus:
                for can_id, payload in ecu.step(dt):
                    msg = json.dumps({"cmd": "inject", "id": can_id, "data": payload.hex()}) + "\n"
                    try:
                        sock.sendall(msg.encode("utf-8"))
                    except Exception:
                        pass

            time.sleep(0.02)  # ~50 Hz simulation clock
    finally:
        sock.close()
        print("[*] Virtual Car Runner stopped.")


if __name__ == "__main__":
    main()
