"""CalSol Virtual WaveSculptor Motor Controller"""
import struct

class VirtualMotorController:
    def __init__(self):
        self.torque_pct = 0.0
        self.speed_mps = 0.0
        self.rpm = 0.0
        self._t_st = self._t_bus = 0.0

    def on_frame(self, can_id: int, payload: bytes):
        if can_id == 0x501 and len(payload) >= 4:
            val = struct.unpack(">f", payload[:4])[0]
            self.torque_pct = max(0.0, min(100.0, val))
        elif can_id == 0x11 and len(payload) >= 1:
            self.torque_pct = (payload[0] / 255.0) * 100.0

    def step(self, dt: float) -> list[tuple[int, bytes]]:
        # Vehicle physics: 320kg, 80Nm max torque, r=0.28m, CdA=0.12, Crr=0.0028
        force = (self.torque_pct / 100.0 * 80.0) / 0.28
        drag = 0.5 * 1.225 * 0.12 * (self.speed_mps ** 2)
        roll = 0.0028 * 320.0 * 9.81
        accel = (force - drag - roll) / 320.0
        self.speed_mps = max(0.0, self.speed_mps + accel * dt)
        self.rpm = (self.speed_mps / (2 * 3.14159 * 0.28)) * 60.0

        self._t_st += dt
        self._t_bus += dt
        frames = []
        if self._t_st >= 0.05:   # 20 Hz Status (0x502)
            frames.append((0x502, struct.pack(">hhhh", int(self.rpm), int(self.speed_mps * 3.6 * 10), int(self.torque_pct * 0.6), 350)))
            self._t_st = 0.0
        if self._t_bus >= 0.10:  # 10 Hz Bus Measurements (0x503)
            frames.append((0x503, struct.pack(">hh4s", 3800, int(self.torque_pct * 0.5), b'\x00' * 4)))
            self._t_bus = 0.0
        return frames
