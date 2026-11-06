"""
CalSol Virtual ECU: Base Engine
===============================
Provides socket connection to CAN Bridge Daemon, packet reception callbacks,
and deterministic timed broadcast loops for software-defined mock ECUs.
"""

import time
import json
import socket
import select
import threading
from abc import ABC, abstractmethod

class BaseVirtualECU(ABC):
    def __init__(self, name: str, socket_path: str = "/tmp/calsol_can.sock", tcp_addr: str = None):
        self.name = name
        self.socket_path = socket_path
        self.tcp_addr = tcp_addr
        self.running = False
        self.sock = None
        self.thread = None
        self.tx_lock = threading.Lock()

    def connect(self):
        if self.tcp_addr:
            host, port = self.tcp_addr.split(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, int(port)))
        elif hasattr(socket, "AF_UNIX") and self.socket_path:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.socket_path)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect(("127.0.0.1", 5555))
        self.sock.setblocking(False)

    def send_frame(self, can_id: int, payload: bytes):
        """Transmit a CAN frame through the daemon."""
        if not self.sock:
            return
        clean_hex = payload.hex()
        msg = {
            "cmd": "inject",
            "id": can_id,
            "data": clean_hex
        }
        data = (json.dumps(msg) + "\n").encode("utf-8")
        with self.tx_lock:
            try:
                self.sock.sendall(data)
            except Exception as e:
                print(f"[-] [{self.name}] Error sending frame: {e}")

    @abstractmethod
    def on_step(self, dt: float):
        """Called periodically by the simulation clock."""
        pass

    def on_frame_received(self, can_id: int, dlc: int, payload: bytes):
        """Called when any node transmits on the CAN bus."""
        pass

    def start(self, step_rate_hz: float = 20.0):
        self.running = True
        self.connect()
        self.step_interval = 1.0 / step_rate_hz
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"[+] [{self.name}] Virtual ECU online (@ {step_rate_hz:.1f} Hz).")

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        print(f"[*] [{self.name}] Virtual ECU stopped.")

    def _run_loop(self):
        buf = ""
        last_step = time.time()

        while self.running:
            now = time.time()
            dt = now - last_step
            if dt >= self.step_interval:
                self.on_step(dt)
                last_step = now

            # Poll for incoming CAN traffic from daemon
            try:
                readable, _, _ = select.select([self.sock], [], [], 0.01)
                if readable:
                    data = self.sock.recv(1024)
                    if not data:
                        break
                    buf += data.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                            if ev.get("event") == "frame":
                                can_id = ev.get("id")
                                dlc = ev.get("dlc", 0)
                                payload = bytes.fromhex(ev.get("data", ""))
                                self.on_frame_received(can_id, dlc, payload)
                        except Exception:
                            pass
            except Exception:
                break
