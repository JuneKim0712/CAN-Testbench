"""CalSol Virtual Battery Management System (VirtualBMS)"""
import struct

class VirtualBMS:
    def __init__(self):
        self.state = 2       # ACTIVE
        self.contactor = 1   # CLOSED
        self.pack_voltage = 379.2
        self.soc = 88.0
        self.pack_temp = 28.5
        self.faults = 0
        self._t_hb = self._t_v = self._t_t = 0.0

    def trigger_overvoltage(self):
        self.faults |= 1
        self.state, self.contactor = 3, 0

    def trigger_undervoltage(self):
        self.faults |= 2
        self.state, self.contactor = 3, 0

    def trigger_thermal_fault(self):
        self.faults |= 4
        self.pack_temp = 64.0
        self.state, self.contactor = 3, 0

    def on_frame(self, can_id: int, payload: bytes):
        pass

    def step(self, dt: float) -> list[tuple[int, bytes]]:
        self._t_hb += dt
        self._t_v += dt
        self._t_t += dt
        frames = []
        if self._t_hb >= 0.10:  # 10 Hz Heartbeat (0x301)
            frames.append((0x301, struct.pack(">BBBB4s", self.state, self.contactor, self.faults, int(self.soc), b'\x00' * 4)))
            self._t_hb = 0.0
        if self._t_v >= 0.50:   # 2 Hz Voltages (0x302)
            pv = int(self.pack_voltage * 10)
            frames.append((0x302, struct.pack(">HHH2s", pv, 3920, 3980, b'\x00' * 2)))
            self._t_v = 0.0
        if self._t_t >= 1.00:   # 1 Hz Temperatures (0x303)
            frames.append((0x303, struct.pack(">h6s", int(self.pack_temp * 10), b'\x00' * 6)))
            self._t_t = 0.0
        return frames
