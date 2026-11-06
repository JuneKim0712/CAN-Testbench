#!/usr/bin/env python3
"""
CalSol Virtual Vehicle Simulator: Car Runner
============================================
Launches and orchestrates the software-defined Virtual ECUs (BMS, Motor, Steering).
Enables the physical DUT on the bench to interact with an entire simulated vehicle.
"""

import os
import sys
import time
import signal
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sim.virtual_ecus.virtual_bms import VirtualBMS
from sim.virtual_ecus.virtual_motor import VirtualMotorController
from sim.virtual_ecus.virtual_steering import VirtualSteering

def main():
    parser = argparse.ArgumentParser(description="CalSol Virtual Car Runner")
    parser.add_argument("--socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp", help="TCP address (host:port)")
    parser.add_argument("--no-bms", action="store_true", help="Disable Virtual BMS")
    parser.add_argument("--no-motor", action="store_true", help="Disable Virtual Motor Controller")
    parser.add_argument("--no-steering", action="store_true", help="Disable Virtual Steering")
    parser.add_argument("--duration", type=float, default=0.0, help="Run duration in seconds (0 = infinite)")

    args = parser.parse_args()

    ecus = []
    if not args.no_bms:
        ecus.append(VirtualBMS(socket_path=args.socket, tcp_addr=args.tcp))
    if not args.no_motor:
        ecus.append(VirtualMotorController(socket_path=args.socket, tcp_addr=args.tcp))
    if not args.no_steering:
        ecus.append(VirtualSteering(socket_path=args.socket, tcp_addr=args.tcp))

    if not ecus:
        print("[-] No ECUs selected to run.")
        sys.exit(1)

    print(f"[*] Starting CalSol Virtual Vehicle ({len(ecus)} active Virtual ECUs)...")
    for ecu in ecus:
        ecu.start()

    def handle_sig(sig, frame):
        print("\n[*] Shutting down Virtual Vehicle...")
        for e in ecus:
            e.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    start_time = time.time()
    try:
        while True:
            time.sleep(1.0)
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                break
    finally:
        for e in ecus:
            e.stop()
        print("[+] Virtual vehicle simulation finished.")

if __name__ == "__main__":
    main()
