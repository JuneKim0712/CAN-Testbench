"""Isolated software fixtures. These events never enter production telemetry."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from can_bridge_daemon import CANBridgeDaemon, cobs_decode, unpack_frame


class BridgeRuntimeTests(unittest.TestCase):
    def test_corruption_and_truncation(self):
        self.assertEqual(b'', cobs_decode(b'\x04\x01'))
        self.assertIsNone(unpack_frame(b'\x01\x10\x00'))
        # Reserved diagnostic response can never be interpreted as CAN.
        self.assertIsNone(unpack_frame(bytes.fromhex('f1f001000000010100')))

    def test_queue_overload_is_visible_and_bounded(self):
        daemon = CANBridgeDaemon(log_path=None, json_out=None, virtual=True)
        for i in range(5000):
            daemon.broadcast(dict(event='software_fixture', index=i))
        self.assertEqual(4096, daemon.events.qsize())
        self.assertEqual(904, daemon.metrics['delivery_drops'])

    def test_background_log_and_atomic_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'capture.jsonl'
            snapshot = Path(directory) / 'snapshot.json'
            daemon = CANBridgeDaemon(unix_socket='', tcp_port=0, ws_port=0,
                                     log_path=str(log), json_out=str(snapshot), virtual=True)
            daemon.start()
            try:
                for _ in range(100):
                    daemon._handle_rx_frame(1, 1, b'\0')
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if snapshot.exists() and json.loads(snapshot.read_text())['total_captured'] == 100:
                        break
                    time.sleep(0.01)
                data = json.loads(snapshot.read_text())
                self.assertEqual(100, data['total_captured'])
                self.assertEqual(100, len(data['frames']))
                self.assertEqual(0, daemon.metrics['delivery_drops'])
            finally:
                daemon.stop()
            self.assertEqual(100, len(log.read_text().splitlines()))

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            CANBridgeDaemon(max_frames=0)
