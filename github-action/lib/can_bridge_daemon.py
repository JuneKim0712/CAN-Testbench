#!/usr/bin/env python3
"""
CalSol Hardware CAN Testbench: High-Speed CAN Bridge Daemon
============================================================
Connects to the dedicated ESP32 CAN Bus Debugger (/dev/esp32_debugger),
decodes incoming COBS-framed CAN messages, broadcasts live JSON events
over Unix Domain / TCP sockets, accepts packet injection requests,
and records rolling logs to can_trace.jsonl.
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

# ─── COBS Codec ───────────────────────────────────────────────────────────────

def cobs_encode(data: bytes) -> bytes:
    """Standard COBS encoding without trailing zero delimiter."""
    out = bytearray()
    read_index = 0
    code_index = 0
    out.append(1)  # placeholder for first code byte
    code = 1

    while read_index < len(data):
        b = data[read_index]
        read_index += 1
        if b == 0:
            out[code_index] = code
            code = 1
            code_index = len(out)
            out.append(1)
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_index] = code
                code = 1
                code_index = len(out)
                out.append(1)

    out[code_index] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """Standard COBS decoding."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        code = data[i]
        if code == 0:
            raise ValueError("Zero byte in COBS body")
        i += 1
        for _ in range(code - 1):
            if i >= n:
                raise ValueError("Truncated COBS frame")
            out.append(data[i])
            i += 1
        if code < 0xFF and i < n:
            out.append(0)
    return bytes(out)


def pack_frame(can_id: int, payload: bytes) -> bytes:
    """Pack CAN ID and payload into wire format with checksum and COBS."""
    dlc = min(len(payload), 8)
    id_lo = can_id & 0xFF
    id_hi = (can_id >> 8) & 0x0F
    header_byte2 = ((dlc & 0x0F) << 4) | id_hi

    raw = bytearray([id_lo, header_byte2])
    raw.extend(payload[:dlc])
    # Pad to dlc if payload is shorter
    if len(raw) < 2 + dlc:
        raw.extend(b'\x00' * (2 + dlc - len(raw)))

    checksum = (256 - (sum(raw) % 256)) % 256
    raw.append(checksum)

    encoded = cobs_encode(bytes(raw))
    return encoded + b'\x00'


def unpack_frame(raw: bytes) -> tuple[int, int, bytes] | None:
    """Validate checksum and unpack into (can_id, dlc, payload)."""
    if len(raw) < 3:
        return None
    if sum(raw) % 256 != 0:
        return None

    id_lo = raw[0]
    id_hi = raw[1] & 0x0F
    dlc = (raw[1] >> 4) & 0x0F
    if dlc > 8 or len(raw) != 3 + dlc:
        return None

    can_id = (id_hi << 8) | id_lo
    payload = bytes(raw[2 : 2 + dlc])
    return can_id, dlc, payload


# ─── CAN Bridge Daemon Class ──────────────────────────────────────────────────

class CANBridgeDaemon:
    def __init__(self, port: str = "/dev/esp32_johnathan", baud: int = 115200,
                 unix_socket: str = "/tmp/calsol_can.sock",
                 tcp_port: int = 0, log_path: str = "can_trace.jsonl",
                 virtual: bool = False):
        self.port = port
        self.baud = baud
        self.unix_socket_path = unix_socket
        self.tcp_port = tcp_port
        self.log_path = log_path
        self.virtual = virtual

        self.running = False
        self.serial_handle = None
        self.log_file = None
        self.clients: list[socket.socket] = []
        self.clients_lock = threading.Lock()

        self.unix_server = None
        self.tcp_server = None
        self.rx_thread = None
        self.tx_lock = threading.Lock()

    def start(self):
        self.running = True

        # 1. Open rolling trace log
        if self.log_path:
            log_dir = os.path.dirname(os.path.abspath(self.log_path))
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self.log_file = open(self.log_path, "a", buffering=1, encoding="utf-8")

        # 2. Open serial connection if physical
        if not self.virtual:
            try:
                import serial
                self.serial_handle = serial.Serial(self.port, baudrate=self.baud, timeout=0.1)
                # Ensure RTS/DTR don't keep board in reset
                self.serial_handle.setDTR(False)
                self.serial_handle.setRTS(False)
                print(f"[*] Connected to CAN Debugger on {self.port} ({self.baud} baud)")
            except Exception as e:
                print(f"[-] Error opening serial port {self.port}: {e}")
                print("[*] Falling back to virtual bus mode.")
                self.virtual = True

        # 3. Setup Unix domain socket server
        if self.unix_socket_path and hasattr(socket, "AF_UNIX"):
            sock_dir = os.path.dirname(os.path.abspath(self.unix_socket_path))
            if sock_dir:
                os.makedirs(sock_dir, exist_ok=True)
            if os.path.exists(self.unix_socket_path):
                try:
                    os.remove(self.unix_socket_path)
                except Exception:
                    pass
            self.unix_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.unix_server.bind(self.unix_socket_path)
            self.unix_server.listen(5)
            # Allow any user in dialout/users to read/write socket
            try:
                os.chmod(self.unix_socket_path, 0o666)
            except Exception:
                pass
            print(f"[*] Listening on Unix socket: {self.unix_socket_path}")

        # 4. Setup TCP socket server if requested or if Unix sockets unsupported
        effective_tcp = self.tcp_port
        if not hasattr(socket, "AF_UNIX") and effective_tcp == 0:
            effective_tcp = 5555

        if effective_tcp > 0:
            self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_server.bind(("0.0.0.0", effective_tcp))
            self.tcp_server.listen(5)
            print(f"[*] Listening on TCP port: {effective_tcp}")

        # 5. Start threads
        self.rx_thread = threading.Thread(target=self._serial_rx_loop, daemon=True)
        self.rx_thread.start()

        self.accept_thread = threading.Thread(target=self._socket_accept_loop, daemon=True)
        self.accept_thread.start()

    def stop(self):
        self.running = False
        if self.serial_handle:
            try:
                self.serial_handle.close()
            except Exception:
                pass

        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass

        with self.clients_lock:
            for c in self.clients:
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()

        if self.unix_server:
            try:
                self.unix_server.close()
            except Exception:
                pass
            if os.path.exists(self.unix_socket_path):
                try:
                    os.remove(self.unix_socket_path)
                except Exception:
                    pass

        if self.tcp_server:
            try:
                self.tcp_server.close()
            except Exception:
                pass
        print("[*] CAN Bridge Daemon stopped.")

    def inject_frame(self, can_id: int, payload: bytes) -> bool:
        """Inject a CAN frame onto physical wire (or virtual loopback)."""
        wire_bytes = pack_frame(can_id, payload)
        if not self.virtual and self.serial_handle:
            with self.tx_lock:
                try:
                    self.serial_handle.write(wire_bytes)
                    self.serial_handle.flush()
                except Exception as e:
                    print(f"[-] Serial write error during inject: {e}")
                    return False

        # Emit injected frame as an event to all monitoring clients
        self._broadcast_event({
            "event": "frame",
            "direction": "tx",
            "timestamp": time.time(),
            "id": can_id,
            "id_hex": f"0x{can_id:03X}",
            "dlc": len(payload),
            "data": payload.hex()
        })
        return True

    def _broadcast_event(self, event_dict: dict):
        line = (json.dumps(event_dict) + "\n").encode("utf-8")
        if self.log_file:
            self.log_file.write(line.decode("utf-8"))

        with self.clients_lock:
            dead_clients = []
            for client in self.clients:
                try:
                    client.sendall(line)
                except Exception:
                    dead_clients.append(client)
            for dc in dead_clients:
                self.clients.remove(dc)
                try:
                    dc.close()
                except Exception:
                    pass

    def _serial_rx_loop(self):
        buf = bytearray()
        while self.running:
            if self.virtual:
                time.sleep(0.01)
                continue

            try:
                chunk = self.serial_handle.read(64)
                if not chunk:
                    continue
                buf.extend(chunk)
                while b'\x00' in buf:
                    idx = buf.index(b'\x00')
                    raw_cobs = buf[:idx]
                    buf = buf[idx + 1:]
                    if not raw_cobs:
                        continue
                    try:
                        decoded = cobs_decode(raw_cobs)
                        unpacked = unpack_frame(decoded)
                        if unpacked:
                            can_id, dlc, payload = unpacked
                            self._broadcast_event({
                                "event": "frame",
                                "direction": "rx",
                                "timestamp": time.time(),
                                "id": can_id,
                                "id_hex": f"0x{can_id:03X}",
                                "dlc": dlc,
                                "data": payload.hex()
                            })
                    except Exception:
                        pass
            except Exception as e:
                if self.running:
                    print(f"[-] Serial read exception: {e}")
                    time.sleep(0.5)

    def _socket_accept_loop(self):
        server_socks = []
        if self.unix_server:
            server_socks.append(self.unix_server)
        if self.tcp_server:
            server_socks.append(self.tcp_server)

        while self.running and server_socks:
            try:
                readable, _, _ = select.select(server_socks, [], [], 0.5)
                for s in readable:
                    conn, _ = s.accept()
                    conn.setblocking(False)
                    with self.clients_lock:
                        self.clients.append(conn)
                    threading.Thread(target=self._client_handler, args=(conn,), daemon=True).start()
            except Exception:
                break

    def _client_handler(self, client: socket.socket):
        buf = ""
        while self.running:
            try:
                readable, _, _ = select.select([client], [], [], 0.5)
                if not readable:
                    continue
                data = client.recv(1024)
                if not data:
                    break
                buf += data.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                        cmd = req.get("cmd")
                        if cmd == "inject":
                            can_id = req.get("id")
                            if isinstance(can_id, str):
                                can_id = int(can_id, 16 if can_id.startswith("0x") else 10)
                            data_hex = req.get("data", "")
                            payload = bytes.fromhex(data_hex) if isinstance(data_hex, str) else bytes(data_hex)
                            success = self.inject_frame(can_id, payload)
                            client.sendall((json.dumps({"status": "ok" if success else "error"}) + "\n").encode("utf-8"))
                        elif cmd == "ping":
                            client.sendall(b'{"status": "pong"}\n')
                    except Exception as ex:
                        err_resp = json.dumps({"status": "error", "message": str(ex)}) + "\n"
                        client.sendall(err_resp.encode("utf-8"))
            except Exception:
                break

        with self.clients_lock:
            if client in self.clients:
                self.clients.remove(client)
        try:
            client.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="CalSol CAN Bridge Daemon")
    parser.add_argument("--port", default="/dev/esp32_johnathan", help="Serial port to ESP32 CAN Debugger")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default 115200)")
    parser.add_argument("--unix-socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp-port", type=int, default=0, help="TCP port (0 to disable)")
    parser.add_argument("--log-file", default="/tmp/can_trace.jsonl", help="Rolling trace log file")
    parser.add_argument("--virtual", action="store_true", help="Run in pure software virtual loopback mode")

    args = parser.parse_args()

    daemon = CANBridgeDaemon(
        port=args.port,
        baud=args.baud,
        unix_socket=args.unix_socket,
        tcp_port=args.tcp_port,
        log_path=args.log_file,
        virtual=args.virtual
    )

    def handle_sig(sig, frame):
        print("\n[*] Interrupted by signal, shutting down...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    daemon.start()
    print("[+] CAN Bridge Daemon is running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()

if __name__ == "__main__":
    main()
