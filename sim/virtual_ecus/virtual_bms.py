"""
CalSol Virtual Battery Management System (VirtualBMS)
====================================================
Simulates a 96-cell series lithium-ion battery pack, calculating
dynamic pack voltages, temperatures, contactor states, and safety faults.
Broadcasts standard CalSol BMS CAN telemetry.
"""

import struct
from .base_ecu import BaseVirtualECU

class VirtualBMS(BaseVirtualECU):
    # State constants
    STATE_IDLE = 0
    STATE_PRECHARGE = 1
    STATE_ACTIVE = 2
    STATE_FAULT = 3

    # Contactor constants
    CONTACTOR_OPEN = 0
    CONTACTOR_CLOSED = 1

    def __init__(self, socket_path: str = "/tmp/calsol_can.sock", tcp_addr: str = None):
        super().__init__("VirtualBMS", socket_path, tcp_addr)
        self.state = self.STATE_ACTIVE
        self.contactor = self.CONTACTOR_CLOSED
        self.num_cells = 96
        self.nominal_cell_voltage = 3.95  # Volts
        self.pack_voltage = self.num_cells * self.nominal_cell_voltage  # ~379.2V
        self.min_cell_voltage = 3.92
        self.max_cell_voltage = 3.98
        self.pack_temp_c = 28.5
        self.soc_percent = 88.0
        self.pack_current_a = 0.0

        # Fault flags
        self.fault_overvoltage = False
        self.fault_undervoltage = False
        self.fault_overtemp = False

        # Timers
        self.time_since_hb = 0.0
        self.time_since_volt = 0.0
        self.time_since_temp = 0.0

    def trigger_overvoltage(self):
        """Simulate battery overvoltage fault condition (>4.25V per cell)."""
        self.fault_overvoltage = True
        self.max_cell_voltage = 4.28
        self.pack_voltage = self.num_cells * 4.25
        self.state = self.STATE_FAULT
        self.contactor = self.CONTACTOR_OPEN
        print("[!] [VirtualBMS] Overvoltage fault triggered! Contactors OPENED.")

    def trigger_undervoltage(self):
        """Simulate battery undervoltage fault (<2.80V per cell)."""
        self.fault_undervoltage = True
        self.min_cell_voltage = 2.75
        self.pack_voltage = self.num_cells * 2.78
        self.state = self.STATE_FAULT
        self.contactor = self.CONTACTOR_OPEN
        print("[!] [VirtualBMS] Undervoltage fault triggered! Contactors OPENED.")

    def trigger_thermal_fault(self):
        """Simulate thermal runaway (>60 C)."""
        self.fault_overtemp = True
        self.pack_temp_c = 64.0
        self.state = self.STATE_FAULT
        self.contactor = self.CONTACTOR_OPEN
        print("[!] [VirtualBMS] Thermal runaway fault triggered! Contactors OPENED.")

    def on_step(self, dt: float):
        self.time_since_hb += dt
        self.time_since_volt += dt
        self.time_since_temp += dt

        # 1. BMS Heartbeat (0x301) @ 10 Hz (100ms)
        if self.time_since_hb >= 0.10:
            fault_byte = 0
            if self.fault_overvoltage: fault_byte |= (1 << 0)
            if self.fault_undervoltage: fault_byte |= (1 << 1)
            if self.fault_overtemp: fault_byte |= (1 << 2)

            # Payload: [state, contactor, fault_flags, soc_percent, 0, 0, 0, 0]
            hb_payload = struct.pack(">BBBB4s", self.state, self.contactor, fault_byte, int(self.soc_percent), b'\x00'*4)
            self.send_frame(0x301, hb_payload)
            self.time_since_hb = 0.0

        # 2. BMS Voltages (0x302) @ 2 Hz (500ms)
        if self.time_since_volt >= 0.50:
            # Pack voltage in 0.1V units, min/max in mV
            pack_v_scaled = int(self.pack_voltage * 10)
            min_cell_mv = int(self.min_cell_voltage * 1000)
            max_cell_mv = int(self.max_cell_voltage * 1000)
            volt_payload = struct.pack(">HHH2s", pack_v_scaled, min_cell_mv, max_cell_mv, b'\x00'*2)
            self.send_frame(0x302, volt_payload)
            self.time_since_volt = 0.0

        # 3. BMS Temperatures (0x303) @ 1 Hz (1000ms)
        if self.time_since_temp >= 1.00:
            avg_temp = int(self.pack_temp_c * 10)
            max_temp = int((self.pack_temp_c + 2.5) * 10)
            temp_payload = struct.pack(">HH4s", avg_temp, max_temp, b'\x00'*4)
            self.send_frame(0x303, temp_payload)
            self.time_since_temp = 0.0
