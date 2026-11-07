#!/usr/bin/env python3
"""
CalSol Hardware CAN Testbench: High-Speed CAN Bridge Daemon
Connects to ESP32 CAN Debugger (/dev/esp32_ahmed), decodes COBS frames,
exposes Unix / TCP sockets for injection and live event broadcasting,
and logs traffic to can_trace.jsonl.
"""

import os
import sys
import time
import json
import socket
import select
import signal
import threading
import argparse

# ─── COBS Codec & Wire Protocol ───────────────────────────────────────────────

def cobs_encode(data: bytes) -> bytes:
    out = bytearray([1])
    code_idx = 0
    for b in data:
        if b == 0:
            out.append(1)
            code_idx = len(out) - 1
        else:
            out.append(b)
            out[code_idx] += 1
            if out[code_idx] == 0xFF:
                out.append(1)
                code_idx = len(out) - 1
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        code = data[i]
        if code == 0:
            return bytes()
        i += 1
        for _ in range(code - 1):
            if i >= n:
                return bytes()
            out.append(data[i])
            i += 1
        if code < 0xFF and i < n:
            out.append(0)
    return bytes(out)


def pack_frame(can_id: int, payload: bytes) -> bytes:
    dlc = min(len(payload), 8)
    raw = bytearray([can_id & 0xFF, ((dlc & 0x0F) << 4) | ((can_id >> 8) & 0x0F)])
    raw.extend(payload[:dlc] + b'\x00' * (dlc - len(payload[:dlc])))
    raw.append((256 - (sum(raw) % 256)) % 256)
    return cobs_encode(bytes(raw)) + b'\x00'


def unpack_frame(raw: bytes) -> tuple[int, int, bytes] | None:
    if len(raw) < 3 or sum(raw) % 256 != 0:
        return None
    dlc = (raw[1] >> 4) & 0x0F
    if dlc > 8 or len(raw) != 3 + dlc:
        return None
    can_id = ((raw[1] & 0x0F) << 8) | raw[0]
    return can_id, dlc, bytes(raw[2 : 2 + dlc])


# ─── CAN Bridge Daemon ────────────────────────────────────────────────────────

class CANBridgeDaemon:
    def __init__(self, port: str = "/dev/esp32_ahmed", baud: int = 115200,
                 unix_socket: str = "/tmp/calsol_can.sock", tcp_port: int = 0,
                 log_path: str = "can_trace.jsonl", virtual: bool = False):
        self.port = port
        self.baud = baud
        self.unix_socket_path = unix_socket
        self.tcp_port = tcp_port
        self.log_path = log_path
        self.virtual = virtual

        self.running = False
        self.serial = None
        self.log_file = None
        self.clients: list[socket.socket] = []
        self.servers: list[socket.socket] = []

    def start(self):
        self.running = True

        # Rolling log
        if self.log_path:
            log_dir = os.path.dirname(os.path.abspath(self.log_path))
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self.log_file = open(self.log_path, "a", buffering=1, encoding="utf-8")

        # Serial port
        if not self.virtual:
            try:
                import serial
                self.serial = serial.Serial(self.port, baudrate=self.baud, timeout=0.1)
                try:
                    self.serial.setDTR(True)
                    self.serial.setRTS(False)
                except Exception:
                    pass
                print(f"[*] Connected to CAN Debugger on {self.port}")
            except Exception as e:
                print(f"[-] Serial unavailable ({e}), using virtual mode.")
                self.virtual = True

        # Unix Domain Socket Server
        if self.unix_socket_path and hasattr(socket, "AF_UNIX"):
            sock_dir = os.path.dirname(os.path.abspath(self.unix_socket_path))
            if sock_dir:
                os.makedirs(sock_dir, exist_ok=True)
            if os.path.exists(self.unix_socket_path):
                try:
                    os.remove(self.unix_socket_path)
                except Exception:
                    pass
            us = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            us.bind(self.unix_socket_path)
            us.listen(10)
            us.setblocking(False)
            try:
                os.chmod(self.unix_socket_path, 0o666)
            except Exception:
                pass
            self.servers.append(us)
            print(f"[*] Listening on Unix socket: {self.unix_socket_path}")

        # TCP Socket Server
        port = self.tcp_port or (5555 if not hasattr(socket, "AF_UNIX") else 0)
        if port > 0:
            ts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ts.bind(("0.0.0.0", port))
            ts.listen(10)
            ts.setblocking(False)
            self.servers.append(ts)
            print(f"[*] Listening on TCP port: {port}")

        # Serial RX background thread
        if not self.virtual and self.serial:
            threading.Thread(target=self._serial_rx_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        for c in self.clients:
            try:
                c.close()
            except Exception:
                pass
        self.clients.clear()
        for s in self.servers:
            try:
                s.close()
            except Exception:
                pass
        if self.unix_socket_path and os.path.exists(self.unix_socket_path):
            try:
                os.remove(self.unix_socket_path)
            except Exception:
                pass
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
        print("[*] CAN Bridge Daemon stopped.")

    def broadcast(self, event: dict):
        text_line = json.dumps(event) + "\n"
        if self.log_file:
            self.log_file.write(text_line)
        line = text_line.encode("utf-8")
        dead = []
        for c in self.clients:
            try:
                c.sendall(line)
            except Exception:
                dead.append(c)
        for d in dead:
            if d in self.clients:
                self.clients.remove(d)
                try:
                    d.close()
                except Exception:
                    pass

    def inject_frame(self, can_id: int, payload: bytes) -> bool:
        if not self.virtual and self.serial:
            try:
                self.serial.write(pack_frame(can_id, payload))
                self.serial.flush()
            except Exception as e:
                print(f"[-] Serial write error: {e}")
                return False

        self.broadcast({
            "event": "frame",
            "direction": "tx",
            "timestamp": time.time(),
            "id": can_id,
            "id_hex": f"0x{can_id:03X}",
            "dlc": len(payload),
            "data": payload.hex()
        })
        return True

    def _serial_rx_loop(self):
        buf = bytearray()
        while self.running:
            try:
                chunk = self.serial.read(64)
                if not chunk:
                    continue
                buf.extend(chunk)
                while b'\x00' in buf:
                    raw_cobs, _, buf = buf.partition(b'\x00')
                    if not raw_cobs:
                        continue
                    decoded = cobs_decode(raw_cobs)
                    unpacked = unpack_frame(decoded)
                    if unpacked:
                        can_id, dlc, payload = unpacked
                        self.broadcast({
                            "event": "frame",
                            "direction": "rx",
                            "timestamp": time.time(),
                            "id": can_id,
                            "id_hex": f"0x{can_id:03X}",
                            "dlc": dlc,
                            "data": payload.hex()
                        })
            except Exception:
                time.sleep(0.1)

    def run(self):
        self.start()
        buffers = {}

        try:
            while self.running:
                readable, _, _ = select.select(self.servers + self.clients, [], [], 0.1)
                for s in readable:
                    if s in self.servers:
                        conn, _ = s.accept()
                        conn.setblocking(False)
                        self.clients.append(conn)
                        buffers[conn] = ""
                    else:
                        try:
                            data = s.recv(1024)
                            if not data:
                                self._disconnect(s, buffers)
                                continue
                            buffers[s] = buffers.get(s, "") + data.decode("utf-8", errors="replace")
                            while "\n" in buffers[s]:
                                line, buffers[s] = buffers[s].split("\n", 1)
                                line = line.strip()
                                if not line:
                                    continue
                                self._handle_client_msg(s, line)
                        except Exception:
                            self._disconnect(s, buffers)
        finally:
            self.stop()

    def _disconnect(self, client: socket.socket, buffers: dict):
        if client in self.clients:
            self.clients.remove(client)
        buffers.pop(client, None)
        try:
            client.close()
        except Exception:
            pass

    def _handle_client_msg(self, client: socket.socket, line: str):
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "inject":
                cid = req.get("id")
                if isinstance(cid, str):
                    cid = int(cid, 16 if cid.startswith("0x") else 10)
                data_hex = req.get("data", "")
                payload = bytes.fromhex(data_hex) if isinstance(data_hex, str) else bytes(data_hex)
                ok = self.inject_frame(cid, payload)
                client.sendall((json.dumps({"status": "ok" if ok else "error"}) + "\n").encode("utf-8"))
            elif cmd == "ping":
                client.sendall(b'{"status": "pong"}\n')
        except Exception as ex:
            client.sendall((json.dumps({"status": "error", "message": str(ex)}) + "\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="CalSol CAN Bridge Daemon")
    parser.add_argument("--port", default="/dev/esp32_ahmed", help="Serial port to ESP32 CAN Debugger")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default 115200)")
    parser.add_argument("--unix-socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp-port", type=int, default=0, help="TCP port (0 to disable)")
    parser.add_argument("--log-file", default="/tmp/can_trace.jsonl", help="Rolling trace log file")
    parser.add_argument("--virtual", action="store_true", help="Run in pure software virtual loopback mode")
    args = parser.parse_args()

    daemon = CANBridgeDaemon(
        port=args.port, baud=args.baud, unix_socket=args.unix_socket,
        tcp_port=args.tcp_port, log_path=args.log_file, virtual=args.virtual
    )

    def handle_sig(sig, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    daemon.run()


if __name__ == "__main__":
    main()
