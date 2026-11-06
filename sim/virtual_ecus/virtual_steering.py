"""
CalSol Virtual Steering Wheel Controls (VirtualSteering)
========================================================
Simulates the driver controls interface on the steering wheel:
Drive Mode selector (Neutral, Drive, Reverse), Cruise Control status,
and Hazard / Indicator light toggles.
"""

import struct
from .base_ecu import BaseVirtualECU

class VirtualSteering(BaseVirtualECU):
    MODE_NEUTRAL = 0
    MODE_DRIVE = 1
    MODE_REVERSE = 2

    def __init__(self, socket_path: str = "/tmp/calsol_can.sock", tcp_addr: str = None):
        super().__init__("VirtualSteering", socket_path, tcp_addr)
        self.drive_mode = self.MODE_DRIVE
        self.cruise_control_active = False
        self.target_cruise_speed_kph = 0.0
        self.hazards_active = False
        self.regen_level = 2  # 0 to 4
        self.time_since_tx = 0.0

    def set_drive_mode(self, mode_str: str):
        mode_str = mode_str.upper()
        if mode_str == "DRIVE":
            self.drive_mode = self.MODE_DRIVE
        elif mode_str == "NEUTRAL":
            self.drive_mode = self.MODE_NEUTRAL
        elif mode_str == "REVERSE":
            self.drive_mode = self.MODE_REVERSE
        print(f"[*] [VirtualSteering] Drive mode set to: {mode_str}")

    def on_step(self, dt: float):
        self.time_since_tx += dt
        # Steering Controls (0x200) @ 10 Hz (100ms)
        if self.time_since_tx >= 0.10:
            flags = 0
            if self.cruise_control_active: flags |= (1 << 0)
            if self.hazards_active: flags |= (1 << 1)

            # Payload: [drive_mode, flags, regen_level, int(cruise_speed), 0, 0, 0, 0]
            payload = struct.pack(">BBBB4s", self.drive_mode, flags, self.regen_level, int(self.target_cruise_speed_kph), b'\x00'*4)
            self.send_frame(0x200, payload)
            self.time_since_tx = 0.0
