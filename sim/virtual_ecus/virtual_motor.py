"""
CalSol Virtual Motor Controller (VirtualMotorController)
=======================================================
Simulates a Tritium WaveSculptor 22 motor controller and Gen11 vehicle physics.
Listens for motor drive commands (0x501) and broadcasts motor status (0x502)
and DC bus measurements (0x503).
"""

import struct
from .base_ecu import BaseVirtualECU

class VirtualMotorController(BaseVirtualECU):
    def __init__(self, socket_path: str = "/tmp/calsol_can.sock", tcp_addr: str = None):
        super().__init__("VirtualMotorController", socket_path, tcp_addr)

        # Vehicle physics parameters
        self.vehicle_mass_kg = 320.0       # Gen11 with driver
        self.wheel_radius_m = 0.28         # Standard 16" solar car tire
        self.cd_a = 0.12                   # Low aerodynamic drag area
        self.c_rr = 0.0028                 # Low rolling resistance coefficient
        self.rho_air = 1.225               # Air density kg/m^3
        self.g = 9.81

        # Motor states
        self.target_torque_percent = 0.0   # 0 - 100%
        self.motor_rpm = 0.0
        self.vehicle_speed_mps = 0.0       # m/s
        self.phase_current_a = 0.0
        self.motor_temp_c = 35.0
        self.dc_bus_voltage = 380.0
        self.dc_bus_current = 0.0

        # Broadcast timers
        self.time_since_status = 0.0
        self.time_since_bus = 0.0

    def on_frame_received(self, can_id: int, dlc: int, payload: bytes):
        # 0x501: Drive Command [target_rpm (float), target_torque (float)] or [percent, ...]
        if can_id == 0x501 and dlc >= 4:
            try:
                # If 4 bytes: float torque percentage
                if dlc == 4:
                    torque = struct.unpack(">f", payload[:4])[0]
                    self.target_torque_percent = max(0.0, min(100.0, torque))
                elif dlc == 8:
                    rpm, torque = struct.unpack(">ff", payload[:8])
                    self.target_torque_percent = max(0.0, min(100.0, torque * 100.0 if torque <= 1.0 else torque))
            except Exception:
                pass
        # 0x11: Pedals Position from DUT Pedals ESP32 [raw_position (0-255)]
        elif can_id == 0x11 and dlc >= 1:
            raw_pos = payload[0]
            # Convert 0-255 ADC to 0-100% torque
            self.target_torque_percent = (raw_pos / 255.0) * 100.0

    def on_step(self, dt: float):
        # Integrate vehicle physics
        # Max motor torque ~ 80 Nm
        motor_torque_nm = (self.target_torque_percent / 100.0) * 80.0
        wheel_tractive_force = motor_torque_nm / self.wheel_radius_m

        # Resisting forces
        f_drag = 0.5 * self.rho_air * self.cd_a * (self.vehicle_speed_mps ** 2)
        f_roll = self.c_rr * self.vehicle_mass_kg * self.g
        net_force = wheel_tractive_force - f_drag - f_roll

        # Acceleration
        accel = net_force / self.vehicle_mass_kg
        self.vehicle_speed_mps = max(0.0, self.vehicle_speed_mps + accel * dt)

        # Convert vehicle speed to motor RPM
        wheel_circumference = 2.0 * 3.14159 * self.wheel_radius_m
        wheel_rev_per_sec = self.vehicle_speed_mps / wheel_circumference
        self.motor_rpm = wheel_rev_per_sec * 60.0

        # Estimate phase current (proportional to torque)
        self.phase_current_a = (self.target_torque_percent / 100.0) * 60.0
        # Estimate DC bus current
        mech_power_w = motor_torque_nm * (wheel_rev_per_sec * 2 * 3.14159)
        self.dc_bus_current = (mech_power_w / max(100.0, self.dc_bus_voltage)) if self.dc_bus_voltage > 0 else 0

        self.time_since_status += dt
        self.time_since_bus += dt

        # 1. Motor Status (0x502) @ 20 Hz (50ms)
        if self.time_since_status >= 0.05:
            rpm_int = int(self.motor_rpm)
            phase_current_scaled = int(self.phase_current_a * 10)
            motor_temp_int = int(self.motor_temp_c)
            # Payload: [rpm (int16), phase_current (int16), motor_temp (uint8), error_flags (uint8), 0, 0]
            status_payload = struct.pack(">hhBB2s", rpm_int, phase_current_scaled, motor_temp_int, 0, b'\x00'*2)
            self.send_frame(0x502, status_payload)
            self.time_since_status = 0.0

        # 2. Motor Bus Measurement (0x503) @ 10 Hz (100ms)
        if self.time_since_bus >= 0.10:
            bus_v_scaled = int(self.dc_bus_voltage * 10)
            bus_i_scaled = int(self.dc_bus_current * 10)
            bus_payload = struct.pack(">hh4s", bus_v_scaled, bus_i_scaled, b'\x00'*4)
            self.send_frame(0x503, bus_payload)
            self.time_since_bus = 0.0
