"""Isolated Unix-socket software tests; no hardware telemetry is published."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from can_bridge_daemon import CANBridgeDaemon


@unittest.skipUnless(os.environ.get('CALSOL_NETWORK_TESTS') == '1', 'Enable on Linux verification host')
class TransportTests(unittest.TestCase):
    def test_commands_and_slow_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'fixture.sock')
            daemon = CANBridgeDaemon(unix_socket=path, tcp_port=0, ws_port=0,
                                     log_path=None, json_out=None, virtual=True)
            thread = threading.Thread(target=daemon.run)
            thread.start()
            try:
                deadline = time.monotonic() + 3
                while not Path(path).exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(2)
                    client.connect(path)
                    with client.makefile('rb') as reader:
                        client.sendall(b'{"cmd":"inject","id":2048,"data":"00"}\n')
                        self.assertEqual('error', json.loads(reader.readline())['status'])
                        client.sendall(b'{"cmd":"inject","id":1,"data":"00"}\n')
                        messages = [json.loads(reader.readline()), json.loads(reader.readline())]
                        self.assertTrue(any(m.get('status') == 'ok' for m in messages))
                        self.assertTrue(any(m.get('event') == 'injection_request' for m in messages))
                        self.assertEqual([], list(daemon.recent_frames))
                    # Deliberately stop reading to exercise bounded fanout.
                    for _ in range(2000):
                        daemon._handle_rx_frame(1, 8, bytes(8))
                    deadline = time.monotonic() + 3
                    while not daemon.metrics['slow_client_disconnects'] and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertGreaterEqual(daemon.metrics['slow_client_disconnects'], 1)
                    self.assertLessEqual(daemon.events.qsize(), 4096)
            finally:
                daemon.running = False
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
