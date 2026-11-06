"""CalSol Virtual Steering Wheel Controls"""
import struct

class VirtualSteering:
    def __init__(self):
        self.drive_mode = 1  # 0: NEUTRAL, 1: DRIVE, 2: REVERSE
        self.cruise_active = False
        self.cruise_speed = 0
        self._t_tx = 0.0

    def on_frame(self, can_id: int, payload: bytes):
        pass

    def step(self, dt: float) -> list[tuple[int, bytes]]:
        self._t_tx += dt
        if self._t_tx >= 0.10:  # 10 Hz Controls (0x200)
            self._t_tx = 0.0
            flags = (1 if self.cruise_active else 0)
            return [(0x200, struct.pack(">BBBB4s", self.drive_mode, flags, 2, int(self.cruise_speed), b'\x00' * 4))]
        return []
