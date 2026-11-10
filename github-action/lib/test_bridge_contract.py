"""Software-only regression fixtures; never publish these as physical captures."""
import unittest
from can_bridge_daemon import CANBridgeDaemon, pack_frame, unpack_frame, cobs_decode


class BridgeContractTests(unittest.TestCase):
    def test_codec_boundaries(self):
        for identifier in (0, 0x7FF):
            for data in (b"", b"\0", bytes(range(8))):
                self.assertEqual((identifier, len(data), data),
                                 unpack_frame(cobs_decode(pack_frame(identifier, data)[:-1])))

    def test_invalid_transmissions(self):
        for identifier, data in ((-1, b""), (0x800, b""), (True, b""), (1, bytes(9))):
            with self.assertRaises(ValueError):
                pack_frame(identifier, data)

    def test_disconnected_injection(self):
        daemon = CANBridgeDaemon(log_path=None, json_out=None)
        self.assertFalse(daemon.inject_frame(1, b"\x01"))
        self.assertEqual([], list(daemon.recent_frames))

    def test_capture_identity_preserves_repeated_frames(self):
        daemon = CANBridgeDaemon(log_path=None, json_out=None)
        daemon.broadcast = lambda event: None
        daemon._handle_rx_frame(1, 1, b"\0")
        daemon._handle_rx_frame(1, 1, b"\0")
        newest, previous = daemon.recent_frames
        self.assertEqual(previous['session_id'], newest['session_id'])
        self.assertEqual(previous['sequence'] + 1, newest['sequence'])

    def test_virtual_requests_never_enter_capture(self):
        daemon = CANBridgeDaemon(log_path=None, json_out=None, virtual=True)
        events = []
        daemon.broadcast = events.append
        self.assertTrue(daemon.inject_frame(1, b"\0"))
        self.assertEqual('injection_request', events[0]['event'])
        self.assertEqual([], list(daemon.recent_frames))


if __name__ == '__main__':
    unittest.main()
