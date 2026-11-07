#!/usr/bin/env python3
"""
CalSol Hardware CAN Testbench: High-Speed CAN Bridge Daemon
Connects permanently to ESP32 CAN Debugger (/dev/esp32_ahmed), decodes COBS frames,
exposes Unix / TCP sockets, a built-in WebSocket & SSE HTTP streaming server,
and continuously writes authentic bus captures to web/data/live_stream.json.
"""

import os
import sys
import time
import json
import socket
import select
import signal
import struct
import base64
import hashlib
import threading
import argparse
import collections
from datetime import datetime, timezone

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


# ─── CAN Payload Decoder ──────────────────────────────────────────────────────

def decode_can_payload(can_id: int, payload: bytes) -> tuple[str, str]:
    """Pure, assumption-free decoding of CAN frame wire contents."""
    msg_name = f"FRAME_0x{can_id:03X}"
    if not payload:
        return msg_name, "Empty Payload (DLC 0)"
    hex_str = payload.hex().upper()
    dec_list = list(payload)
    if len(payload) == 1:
        return msg_name, f"0x{hex_str} (Dec: {dec_list[0]})"
    return msg_name, f"0x{hex_str} (Dec: {dec_list})"


# ─── WebSocket & SSE Protocol Helpers ─────────────────────────────────────────

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def ws_handshake_response(key: str) -> bytes:
    accept = base64.b64encode(hashlib.sha1((key.strip() + WS_GUID).encode()).digest()).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode("ascii")


def ws_encode_frame(payload_str: str) -> bytes:
    payload = payload_str.encode("utf-8")
    length = len(payload)
    if length <= 125:
        header = bytes([0x81, length])
    elif length <= 65535:
        header = struct.pack("!BBH", 0x81, 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 127, length)
    return header + payload


def sse_encode_event(payload_str: str) -> bytes:
    return f"data: {payload_str}\n\n".encode("utf-8")


# ─── CAN Bridge Daemon ────────────────────────────────────────────────────────

class CANBridgeDaemon:
    def __init__(self, port: str = "/dev/esp32_ahmed", baud: int = 115200,
                 unix_socket: str = "/tmp/calsol_can.sock", tcp_port: int = 5555,
                 ws_port: int = 8765, log_path: str = "can_trace.jsonl",
                 json_out: str = None, virtual: bool = False):
        self.port = port
        self.baud = baud
        self.unix_socket_path = unix_socket
        self.tcp_port = tcp_port
        self.ws_port = ws_port
        self.log_path = log_path
        self.json_out = json_out
        self.virtual = virtual

        self.running = False
        self.serial = None
        self.log_file = None
        self._lock = threading.Lock()

        # Multiplexed client lists
        self.raw_clients: list[socket.socket] = []
        self.ws_clients: list[socket.socket] = []
        self.sse_clients: list[socket.socket] = []
        self.listening_servers: list[socket.socket] = []
        self.http_pending: dict[socket.socket, bytearray] = {}

        # Rolling real-frame buffer
        self.recent_frames = collections.deque(maxlen=250)
        self.total_rx_count = 0
        self.last_json_flush = 0.0

    def start(self):
        self.running = True

        # Rolling trace log
        if self.log_path:
            log_dir = os.path.dirname(os.path.abspath(self.log_path))
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self.log_file = open(self.log_path, "a", buffering=1, encoding="utf-8")

        # Start Serial RX background thread with auto-reconnect
        if not self.virtual:
            threading.Thread(target=self._serial_worker, daemon=True).start()

        # Unix Domain Socket Server (for cal-test.sh and unity_parser.py)
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
            self.listening_servers.append(us)
            print(f"[*] Unix socket listener active: {self.unix_socket_path}")

        # TCP Server (Raw line-delimited JSON)
        if self.tcp_port > 0:
            ts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ts.bind(("0.0.0.0", self.tcp_port))
            ts.listen(10)
            ts.setblocking(False)
            self.listening_servers.append(ts)
            print(f"[*] Raw TCP socket listener active: port {self.tcp_port}")

        # Web Streaming Server (WebSocket & SSE on port 8765)
        if self.ws_port > 0:
            ws = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ws.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ws.bind(("0.0.0.0", self.ws_port))
            ws.listen(25)
            ws.setblocking(False)
            self.listening_servers.append(ws)
            print(f"[*] Web live streaming server active: port {self.ws_port} (WebSocket /ws, SSE /events, JSON /data)")

    def stop(self):
        self.running = False
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        with self._lock:
            all_conns = self.raw_clients + self.ws_clients + self.sse_clients + list(self.http_pending.keys())
            for c in all_conns:
                try:
                    c.close()
                except Exception:
                    pass
            self.raw_clients.clear()
            self.ws_clients.clear()
            self.sse_clients.clear()
            self.http_pending.clear()

        for s in self.listening_servers:
            try:
                s.close()
            except Exception:
                pass
        self.listening_servers.clear()

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

    def _serial_worker(self):
        """Persistent background worker that connects to /dev/esp32_ahmed and auto-reconnects on drop."""
        import serial

        while self.running:
            try:
                if not os.path.exists(self.port):
                    print(f"[-] CAN Debugger device {self.port} not found on host. Retrying in 2s...")
                    time.sleep(2)
                    continue

                print(f"[*] Connecting to CAN Debugger on {self.port} ({self.baud} baud)...")
                self.serial = serial.Serial(self.port, baudrate=self.baud, timeout=0.2)
                try:
                    self.serial.setDTR(True)
                    self.serial.setRTS(False)
                except Exception:
                    pass
                print(f"[+] Connected to CAN Debugger on {self.port}. Listening for physical bus traffic...")

                buf = bytearray()
                while self.running:
                    chunk = self.serial.read(128)
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
                            self._handle_rx_frame(can_id, dlc, payload)

            except Exception as e:
                print(f"[-] Serial error on {self.port}: {e}. Reconnecting in 2s...")
                if self.serial:
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
                time.sleep(2)

    def _handle_rx_frame(self, can_id: int, dlc: int, payload: bytes):
        now = time.time()
        now_dt = datetime.now(timezone.utc)
        time_str = now_dt.strftime("%H:%M:%S.%f")[:-3]
        msg_name, signal_desc = decode_can_payload(can_id, payload)
        raw_hex = " ".join(f"{b:02X}" for b in payload)

        frame_obj = {
            "event": "frame",
            "direction": "rx",
            "source": "physical_bus",
            "time": time_str,
            "timestamp": round(now, 4),
            "iface": self.port,
            "id": f"0x{can_id:03X}",
            "id_int": can_id,
            "name": msg_name,
            "dlc": dlc,
            "raw": raw_hex,
            "data": "".join(f"{b:02X}" for b in payload),
            "decoded": signal_desc
        }

        self.total_rx_count += 1
        with self._lock:
            self.recent_frames.appendleft(frame_obj)

        self.broadcast(frame_obj)
        self._flush_json_debounced()

    def _flush_json_debounced(self):
        if not self.json_out:
            return
        now = time.time()
        if now - self.last_json_flush < 0.25:
            return
        self.last_json_flush = now
        try:
            out_dir = os.path.dirname(os.path.abspath(self.json_out))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            tmp_path = self.json_out + ".tmp"
            with self._lock:
                frames_snapshot = list(self.recent_frames)
            data = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "interface": self.port,
                "baud": 500000,
                "total_captured": self.total_rx_count,
                "frames": frames_snapshot
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.json_out)
        except Exception:
            pass

    def broadcast(self, event: dict):
        text_line = json.dumps(event) + "\n"
        if self.log_file:
            self.log_file.write(text_line)

        raw_bytes = text_line.encode("utf-8")
        ws_bytes = ws_encode_frame(json.dumps(event))
        sse_bytes = sse_encode_event(json.dumps(event))

        with self._lock:
            # Broadcast to raw Unix & TCP clients
            dead_raw = []
            for c in self.raw_clients:
                try:
                    c.sendall(raw_bytes)
                except Exception:
                    dead_raw.append(c)
            for d in dead_raw:
                if d in self.raw_clients:
                    self.raw_clients.remove(d)
                try: d.close()
                except Exception: pass

            # Broadcast to WebSocket clients
            dead_ws = []
            for w in self.ws_clients:
                try:
                    w.sendall(ws_bytes)
                except Exception:
                    dead_ws.append(w)
            for d in dead_ws:
                if d in self.ws_clients:
                    self.ws_clients.remove(d)
                try: d.close()
                except Exception: pass

            # Broadcast to SSE clients
            dead_sse = []
            for s in self.sse_clients:
                try:
                    s.sendall(sse_bytes)
                except Exception:
                    dead_sse.append(s)
            for d in dead_sse:
                if d in self.sse_clients:
                    self.sse_clients.remove(d)
                try: d.close()
                except Exception: pass

    def inject_frame(self, can_id: int, payload: bytes) -> bool:
        if not self.virtual and self.serial:
            try:
                self.serial.write(pack_frame(can_id, payload))
                self.serial.flush()
            except Exception as e:
                print(f"[-] Serial write error: {e}")
                return False

        msg_name, signal_desc = decode_can_payload(can_id, payload)
        now = time.time()
        now_dt = datetime.now(timezone.utc)
        frame_obj = {
            "event": "frame",
            "direction": "tx",
            "time": now_dt.strftime("%H:%M:%S.%f")[:-3],
            "timestamp": round(now, 4),
            "iface": self.port,
            "id": f"0x{can_id:03X}",
            "id_int": can_id,
            "name": msg_name,
            "dlc": len(payload),
            "raw": " ".join(f"{b:02X}" for b in payload),
            "decoded": signal_desc
        }
        with self._lock:
            self.recent_frames.appendleft(frame_obj)
        self.broadcast(frame_obj)
        self._flush_json_debounced()
        return True

    def run(self):
        self.start()
        buffers = {}

        try:
            while self.running:
                all_sockets = []
                with self._lock:
                    all_sockets = self.listening_servers + self.raw_clients + self.ws_clients + list(self.http_pending.keys())
                readable, _, _ = select.select(all_sockets, [], [], 0.1)

                for s in readable:
                    if s in self.listening_servers:
                        conn, _ = s.accept()
                        conn.setblocking(False)
                        # Check server type: if port matches ws_port, it is web server
                        is_web = False
                        try:
                            lport = conn.getsockname()[1]
                            if lport == self.ws_port:
                                is_web = True
                        except Exception:
                            pass

                        with self._lock:
                            if is_web:
                                self.http_pending[conn] = bytearray()
                            else:
                                self.raw_clients.append(conn)
                                buffers[conn] = ""
                    elif s in self.http_pending:
                        self._handle_http_client(s)
                    elif s in self.raw_clients:
                        self._handle_raw_client(s, buffers)
                    elif s in self.ws_clients:
                        # Ping / Pong / Close handling on WebSocket
                        try:
                            chunk = s.recv(512)
                            if not chunk:
                                self._disconnect_ws(s)
                        except Exception:
                            self._disconnect_ws(s)
        finally:
            self.stop()

    def _handle_raw_client(self, client: socket.socket, buffers: dict):
        try:
            data = client.recv(1024)
            if not data:
                self._disconnect_raw(client, buffers)
                return
            buffers[client] = buffers.get(client, "") + data.decode("utf-8", errors="replace")
            while "\n" in buffers[client]:
                line, buffers[client] = buffers[client].split("\n", 1)
                line = line.strip()
                if not line:
                    continue
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
        except Exception:
            self._disconnect_raw(client, buffers)

    def _disconnect_raw(self, client: socket.socket, buffers: dict):
        with self._lock:
            if client in self.raw_clients:
                self.raw_clients.remove(client)
        buffers.pop(client, None)
        try: client.close()
        except Exception: pass

    def _disconnect_ws(self, client: socket.socket):
        with self._lock:
            if client in self.ws_clients:
                self.ws_clients.remove(client)
        try: client.close()
        except Exception: pass

    def _handle_http_client(self, client: socket.socket):
        try:
            chunk = client.recv(2048)
            if not chunk:
                self._close_http(client)
                return
            buf = self.http_pending.get(client, bytearray())
            buf.extend(chunk)

            if b"\r\n\r\n" in buf or b"\n\n" in buf:
                req_text = buf.decode("utf-8", errors="replace")
                lines = req_text.splitlines()
                if not lines:
                    self._close_http(client)
                    return
                req_line = lines[0]
                parts = req_line.split()
                method = parts[0] if len(parts) > 0 else "GET"
                path = parts[1] if len(parts) > 1 else "/"

                # Parse headers
                headers = {}
                for l in lines[1:]:
                    if ":" in l:
                        k, v = l.split(":", 1)
                        headers[k.strip().lower()] = v.strip()

                # 1. WebSocket Upgrade
                if headers.get("upgrade", "").lower() == "websocket" and "sec-websocket-key" in headers:
                    key = headers["sec-websocket-key"]
                    resp = ws_handshake_response(key)
                    client.sendall(resp)
                    with self._lock:
                        self.http_pending.pop(client, None)
                        self.ws_clients.append(client)
                    # Send hello status
                    hello = {
                        "event": "connected",
                        "interface": self.port,
                        "status": "online",
                        "total_captured": self.total_rx_count
                    }
                    client.sendall(ws_encode_frame(json.dumps(hello)))
                    return

                # 2. Server-Sent Events (/events or /stream)
                if path in ["/events", "/stream"] or "text/event-stream" in headers.get("accept", ""):
                    sse_hdr = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/event-stream\r\n"
                        "Cache-Control: no-cache\r\n"
                        "Connection: keep-alive\r\n"
                        "Access-Control-Allow-Origin: *\r\n\r\n"
                    ).encode("ascii")
                    client.sendall(sse_hdr)
                    with self._lock:
                        self.http_pending.pop(client, None)
                        self.sse_clients.append(client)
                    return

                # 3. CORS Preflight
                if method == "OPTIONS":
                    opt_resp = (
                        "HTTP/1.1 204 No Content\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                        "Access-Control-Allow-Headers: *\r\n\r\n"
                    ).encode("ascii")
                    client.sendall(opt_resp)
                    self._close_http(client)
                    return

                # 4. JSON REST endpoint (/data, /live_stream.json, /api/frames)
                if path in ["/data", "/live_stream.json", "/api/frames"]:
                    with self._lock:
                        snapshot = list(self.recent_frames)
                    payload = json.dumps({
                        "interface": self.port,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "total_captured": self.total_rx_count,
                        "frames": snapshot
                    })
                    body_bytes = payload.encode("utf-8")
                    json_hdr = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        f"Content-Length: {len(body_bytes)}\r\n\r\n"
                    ).encode("ascii")
                    client.sendall(json_hdr + body_bytes)
                    self._close_http(client)
                    return

                # 5. Default Health / Status Info
                status_payload = json.dumps({
                    "status": "online",
                    "interface": self.port,
                    "baud": self.baud,
                    "total_rx": self.total_rx_count
                })
                body = status_payload.encode("utf-8")
                res = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    f"Content-Length: {len(body)}\r\n\r\n"
                ).encode("ascii") + body
                client.sendall(res)
                self._close_http(client)
        except Exception:
            self._close_http(client)

    def _close_http(self, client: socket.socket):
        with self._lock:
            self.http_pending.pop(client, None)
        try: client.close()
        except Exception: pass


def main():
    parser = argparse.ArgumentParser(description="CalSol CAN Bridge Daemon")
    parser.add_argument("--port", default="/dev/esp32_ahmed", help="Serial port to ESP32 CAN Debugger")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default 115200)")
    parser.add_argument("--unix-socket", default="/tmp/calsol_can.sock", help="Unix domain socket path")
    parser.add_argument("--tcp-port", type=int, default=5555, help="TCP port for raw line-delimited clients (default 5555)")
    parser.add_argument("--ws-port", type=int, default=8765, help="Web streaming port for WebSocket & SSE (default 8765)")
    parser.add_argument("--log-file", default="/tmp/can_trace.jsonl", help="Rolling trace log file")
    parser.add_argument("--json-out", default="web/data/live_stream.json", help="Path to atomically update rolling live frames JSON")
    parser.add_argument("--virtual", action="store_true", help="Run in pure software virtual loopback mode")
    args = parser.parse_args()

    daemon = CANBridgeDaemon(
        port=args.port, baud=args.baud, unix_socket=args.unix_socket,
        tcp_port=args.tcp_port, ws_port=args.ws_port, log_path=args.log_file,
        json_out=args.json_out, virtual=args.virtual
    )

    def handle_sig(sig, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    daemon.run()


if __name__ == "__main__":
    main()
