#!/usr/bin/env python3
"""Spoof an example ECU through the existing bridge; standard library only."""
import argparse
import json
import socket
import time


def response_for(event):
    """Only physical RX events can trigger a reply; never respond to TX echoes."""
    if event.get("event") != "frame" or event.get("direction") != "rx":
        return None
    raw_id = event.get("id_int", event.get("id"))
    can_id = int(raw_id, 0) if isinstance(raw_id, str) else int(raw_id)
    data = bytes.fromhex(event.get("data", event.get("raw", "")))
    if can_id == 0x601 and event.get("dlc") == 1 and data == b"\xA5":
        return {"cmd": "inject", "id": 0x600, "data": "32"}
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/tmp/calsol_can.sock")
    parser.add_argument("--tcp", nargs=2, metavar=("HOST", "PORT"))
    parser.add_argument("--duration", type=float, default=180)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be positive")

    if args.tcp:
        connection = socket.create_connection((args.tcp[0], int(args.tcp[1])), timeout=2)
    else:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(2)
        connection.connect(args.socket)

    with connection:
        connection.settimeout(0.5)
        print("Responder ready: RX 0x601 [A5] -> inject 0x600 [32]", flush=True)
        deadline = time.monotonic() + args.duration
        pending = bytearray()
        while time.monotonic() < deadline:
            try:
                chunk = connection.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("Bridge disconnected")
            pending.extend(chunk)
            if len(pending) > 65536:
                raise RuntimeError("Bridge line buffer exceeded 64 KiB")
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("status") == "error":
                    raise RuntimeError(f"Bridge rejected injection: {event}")
                reply = response_for(event)
                if reply is not None:
                    connection.sendall((json.dumps(reply) + "\n").encode())
                    print("Requested injection: 0x600 [32]; DUT verifies reception", flush=True)


if __name__ == "__main__":
    main()
