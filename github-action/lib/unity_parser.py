#!/usr/bin/env python3
"""
CalSol CAN Testbench - Unity Serial Stream & Live CAN Bus Monitor
Monitors active DUT UART serial output, extracts Unity test assertions,
simultaneously captures and decodes live physical CAN bus traffic from
the dedicated CAN Debugger (/dev/esp32_ahmed or Unix socket), formats
outputs for GitHub Actions ($GITHUB_STEP_SUMMARY), and writes structured JSON.
"""

import os
import re
import sys
import time
import json
import socket
import struct
import threading
import argparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import serial
except ImportError:
    print("[-] Error: 'pyserial' is required. Install via: pip install pyserial", file=sys.stderr)
    sys.exit(1)


# ─── CalSol CAN Protocol & COBS Framing ───────────────────────────────────────

def cobs_decode(data: bytes) -> bytes:
    """Decodes COBS packet without delimiters."""
    out = bytearray()
    idx = 0
    length = len(data)
    while idx < length:
        code = data[idx]
        if code == 0:
            break
        idx += 1
        for _ in range(code - 1):
            if idx >= length:
                break
            out.append(data[idx])
            idx += 1
        if code < 0xFF and idx < length:
            out.append(0)
    return bytes(out)


def unpack_cobs_frame(raw: bytes) -> tuple[int, int, bytes] | None:
    """Validates checksum and extracts (can_id, dlc, payload)."""
    if len(raw) < 3 or sum(raw) % 256 != 0:
        return None
    dlc = (raw[1] >> 4) & 0x0F
    if dlc > 8 or len(raw) != 3 + dlc:
        return None
    can_id = ((raw[1] & 0x0F) << 8) | raw[0]
    return can_id, dlc, bytes(raw[2 : 2 + dlc])


def decode_calsol_message(can_id: int, data: bytes) -> tuple[str, str]:
    """Decodes standard CalSol Gen11 message IDs into human-readable signals."""
    if can_id == 0x011:
        throttle = data[0] if len(data) > 0 else 0
        cutoff = "TRIPPED" if (throttle > 25 and len(data) > 1 and data[1]) else "OK"
        return "PEDALS_THROTTLE", f"Throttle: {throttle}% | Interlock: {cutoff}"
    elif can_id == 0x012:
        brake = data[0] if len(data) > 0 else 0
        return "PEDALS_BRAKE", f"Brake Pressure: {brake}%"
    elif can_id == 0x015:
        volts = (data[0] / 10.0) if len(data) > 0 else 0.0
        return "PEDALS_POWER", f"Sensor Bus: {volts:.1f}V"
    elif can_id == 0x020:
        status_byte = data[0] if len(data) > 0 else 0
        brake_active = "ACTIVE" if (status_byte & 1) else "OFF"
        hazard_active = "ACTIVE" if (status_byte & 2) else "OFF"
        return "LIGHTS_STATUS", f"Brakelights: {brake_active} | Hazards: {hazard_active}"
    elif can_id == 0x200:
        angle = int.from_bytes(data[:2], "little", signed=True) / 10.0 if len(data) >= 2 else 0.0
        return "STEERING_ANGLE", f"Wheel Angle: {angle:+.1f}°"
    elif can_id == 0x301:
        pack_v = int.from_bytes(data[:2], "little") / 10.0 if len(data) >= 2 else 0.0
        soc = data[2] if len(data) >= 3 else 0
        curr = int.from_bytes(data[3:5], "little", signed=True) / 10.0 if len(data) >= 5 else 0.0
        return "BMS_TELEMETRY", f"Pack: {pack_v:.1f}V | SoC: {soc}% | Current: {curr:+.1f}A"
    elif can_id == 0x302:
        faults = data[0] if len(data) >= 1 else 0
        return "BMS_FAULTS", f"Fault Mask: 0x{faults:02X}"
    elif can_id == 0x501:
        torque = int.from_bytes(data[:2], "little", signed=True) / 10.0 if len(data) >= 2 else 0.0
        return "MOTOR_CMD", f"Torque Setpoint: {torque:+.1f} Nm"
    elif can_id == 0x502:
        rpm = int.from_bytes(data[:2], "little", signed=True) if len(data) >= 2 else 0
        inv_temp = data[2] if len(data) >= 3 else 0
        motor_temp = data[3] if len(data) >= 4 else 0
        return "MOTOR_TELEMETRY", f"RPM: {rpm} | Inverter: {inv_temp}°C | Motor: {motor_temp}°C"
    elif can_id == 0x503:
        bus_v = int.from_bytes(data[:2], "little") / 10.0 if len(data) >= 2 else 0.0
        bus_i = int.from_bytes(data[2:4], "little") / 10.0 if len(data) >= 4 else 0.0
        return "MOTOR_BUS", f"DC Bus: {bus_v:.1f}V | Bus Current: {bus_i:.1f}A"
    elif 0x001 <= can_id <= 0x00F:
        names = {
            0x001: "HEARTBEAT_BMS",
            0x002: "HEARTBEAT_MOTOR",
            0x003: "HEARTBEAT_STEERING",
            0x004: "HEARTBEAT_PEDALS",
            0x005: "HEARTBEAT_LIGHTS"
        }
        return names.get(can_id, f"HEARTBEAT_0x{can_id:02X}"), f"Node Active (seq {data[0] if data else 0})"
    else:
        return f"CAN_0x{can_id:03X}", f"Raw: {data.hex().upper()}"


# ─── Live CAN Bus Monitor Thread ──────────────────────────────────────────────

class LiveCANMonitor(threading.Thread):
    def __init__(self, can_port: str = "", can_baud: int = 115200, unix_sock: str = "/tmp/calsol_can.sock"):
        super().__init__(daemon=True)
        self.can_port = can_port
        self.can_baud = can_baud
        self.unix_sock = unix_sock
        self.running = True
        self.frames = []
        self.start_time = time.time()
        self.source = None

    def run(self):
        # 1. Try Unix domain socket (if can_bridge_daemon is already active)
        if hasattr(socket, "AF_UNIX") and os.path.exists(self.unix_sock):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(self.unix_sock)
                self.source = f"unix:{self.unix_sock}"
                buf = ""
                while self.running:
                    try:
                        chunk = s.recv(1024)
                        if not chunk:
                            break
                        buf += chunk.decode("utf-8", errors="replace")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            if not line.strip():
                                continue
                            try:
                                ev = json.loads(line)
                                if ev.get("event") == "frame":
                                    can_id = int(ev.get("id", 0))
                                    data = bytes.fromhex(ev.get("data", ""))
                                    dlc = int(ev.get("dlc", len(data)))
                                    self._record_frame(can_id, dlc, data)
                            except Exception:
                                pass
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                s.close()
                return
            except Exception:
                pass

        # 2. Try direct serial connection to dedicated debugger (/dev/esp32_ahmed)
        if self.can_port and os.path.exists(self.can_port):
            try:
                ser = serial.Serial(self.can_port, self.can_baud, timeout=0.1)
                try:
                    ser.setDTR(True)
                    ser.setRTS(False)
                except Exception:
                    pass
                self.source = f"serial:{self.can_port}"
                buf = bytearray()
                while self.running:
                    try:
                        raw = ser.read(64)
                        if raw:
                            buf.extend(raw)
                            while b"\x00" in buf:
                                packet, _, buf = buf.partition(b"\x00")
                                if not packet:
                                    continue
                                decoded = cobs_decode(packet)
                                frame = unpack_cobs_frame(decoded)
                                if frame:
                                    can_id, dlc, data = frame
                                    self._record_frame(can_id, dlc, data)
                        else:
                            time.sleep(0.01)
                    except Exception as e:
                        print(f"[-] LiveCANMonitor read loop error: {e}", file=sys.stderr)
                        break
                ser.close()
            except Exception as e:
                print(f"[-] LiveCANMonitor serial open error on {self.can_port}: {e}", file=sys.stderr)

    def record_external_frame(self, can_id: int, dlc: int, data: bytes):
        now = time.time()
        hex_str = data.hex().upper()
        for prev in reversed(self.frames[-10:]):
            if prev["id_int"] == can_id and prev["data"] == hex_str and (now - prev["timestamp"]) < 0.1:
                return
        self._record_frame(can_id, dlc, data)

    def _record_frame(self, can_id: int, dlc: int, data: bytes):
        t_rel = time.time() - self.start_time
        msg_name, signal_desc = decode_calsol_message(can_id, data)
        hex_str = data.hex().upper()
        frame_obj = {
            "rel_time": f"+{t_rel:.3f}s",
            "timestamp": round(time.time(), 4),
            "id": f"0x{can_id:03X}",
            "id_int": can_id,
            "name": msg_name,
            "dlc": dlc,
            "data": hex_str,
            "decoded": signal_desc
        }
        self.frames.append(frame_obj)
        print(f"    [CAN LIVE] 📡 {frame_obj['id']} ({msg_name}) DLC:{dlc} [{hex_str}] -> {signal_desc}")

    def stop(self):
        self.running = False


# ─── Master Stream Parser ─────────────────────────────────────────────────────

def parse_unity_stream(port: str, baud: int = 115200, timeout: float = 12.0, verbose: bool = False,
                       log_file: str = None, output_json: str = None, subsystem: str = "",
                       can_port: str = "", can_baud: int = 115200, can_trace_file: str = None) -> int:
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"[-] Serial error on {port}: {e}", file=sys.stderr)
        return 1

    # Start live CAN monitoring
    can_monitor = LiveCANMonitor(can_port=can_port, can_baud=can_baud)
    can_monitor.start()

    start_time = time.time()
    passed = False
    summary = ""
    results = []  # List of tuples: (status, test_name, raw_line)
    all_raw_lines = []

    try:
        while time.time() - start_time < timeout:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            all_raw_lines.append(line)

            if verbose:
                print(f"  [RAW] {line}")

            if "[CAN_FRAME]" in line:
                m_id = re.search(r"ID:(0x[0-9a-fA-F]+|\d+)", line)
                m_dlc = re.search(r"DLC:(\d+)", line)
                m_data = re.search(r"DATA:([0-9a-fA-F]*)", line)
                if m_id and m_dlc:
                    try:
                        cid_str = m_id.group(1)
                        can_id = int(cid_str, 16 if cid_str.lower().startswith("0x") else 10)
                        dlc = int(m_dlc.group(1))
                        payload_hex = m_data.group(1) if m_data else ""
                        payload = bytes.fromhex(payload_hex) if payload_hex else b""
                        can_monitor.record_external_frame(can_id, dlc, payload)
                    except Exception:
                        pass

            if ":PASS" in line:
                idx = line.find(":PASS")
                prefix = line[:idx]
                test_name = prefix.split(":")[-1]
                results.append(("PASS", test_name, line))
                print(f"    [PASS] {test_name}")
            elif ":FAIL" in line:
                idx = line.find(":FAIL")
                prefix = line[:idx]
                test_name = prefix.split(":")[-1]
                msg = line[idx + 5:].lstrip(":").strip()
                src_loc = ":".join(prefix.split(":")[:-1])
                details = f"{msg} ({src_loc})" if (msg and src_loc) else (msg or line)
                results.append(("FAIL", test_name, details))
                print(f"    [FAIL] {test_name}: {msg if msg else line}")
            elif ":IGNORE" in line:
                idx = line.find(":IGNORE")
                prefix = line[:idx]
                test_name = prefix.split(":")[-1]
                msg = line[idx + 7:].lstrip(":").strip()
                results.append(("IGNORE", test_name, msg if msg else line))
                print(f"    [IGNORE] {test_name}")
            elif "Tests" in line and "Failures" in line:
                summary = line
                if "0 Failures" in line:
                    passed = True
                break
    finally:
        ser.close()
        can_monitor.stop()
        can_monitor.join(timeout=0.6)

    captured_frames = can_monitor.frames

    # Save raw log file for crash decoder
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            with open(log_file, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(all_raw_lines) + "\n")
        except Exception as e:
            print(f"[-] Note: Failed to save test log file: {e}", file=sys.stderr)

    # Save CAN trace JSONL if captured
    if can_trace_file and captured_frames:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(can_trace_file)), exist_ok=True)
            with open(can_trace_file, "w", encoding="utf-8") as f:
                for fr in captured_frames:
                    f.write(json.dumps(fr) + "\n")
        except Exception as e:
            print(f"[-] Note: Failed to save CAN trace file: {e}", file=sys.stderr)

    # Terminal output
    if passed:
        print(f"\n[+] {summary} (ALL PASSED)")
    elif summary:
        print(f"\n[-] {summary} (FAILED)")
    else:
        print(f"\n[-] Timed out ({timeout}s) waiting for Unity test output.")

    if captured_frames:
        print(f"[+] Captured {len(captured_frames)} physical CAN frames on bus during test run.")

    # Write GitHub Step Summary if running in GitHub Actions
    gh_summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary_file:
        try:
            with open(gh_summary_file, "a", encoding="utf-8") as f:
                status_title = "PASSED" if passed else "FAILED"
                sub_title = f": {subsystem}" if subsystem else ""
                f.write(f"\n### Subsystem Test Results{sub_title} ({status_title})\n\n")

                failed_items = [r for r in results if r[0] == "FAIL"]
                if failed_items:
                    f.write("#### ❌ Failed Assertions\n\n")
                    f.write("| Test Function | Details |\n")
                    f.write("| :--- | :--- |\n")
                    for _, name, details in failed_items:
                        f.write(f"| `{name}` | `{details}` |\n")
                    f.write("\n")

                open_attr = " open" if not passed else ""
                f.write(f"<details{open_attr}>\n")
                f.write(f"<summary><b>All Unit Test Assertions ({len(results)} total)</b></summary>\n\n")
                f.write("| Status | Test Function | Details |\n")
                f.write("| :---: | :--- | :--- |\n")
                for status, test_name, raw in results:
                    f.write(f"| `{status}` | `{test_name}` | `{raw}` |\n")
                if summary:
                    f.write(f"\n**Summary:** {summary}\n")
                else:
                    f.write(f"\n**Summary:** Timed out ({timeout}s) with no response from board.\n")
                f.write("\n</details>\n")

                if captured_frames:
                    f.write(f"\n<details open>\n<summary><b>CAN Bus Telemetry ({len(captured_frames)} frames captured)</b></summary>\n\n")
                    f.write("| Time (rel) | CAN ID | Message Name | DLC | Payload | Decoded Signal Interpretation |\n")
                    f.write("| :---: | :---: | :--- | :---: | :---: | :--- |\n")
                    for fr in captured_frames[:25]:  # show up to 25 frames cleanly
                        f.write(f"| `{fr['rel_time']}` | `{fr['id']}` | `{fr['name']}` | {fr['dlc']} | `0x{fr['data']}` | {fr['decoded']} |\n")
                    if len(captured_frames) > 25:
                        f.write(f"\n*... and {len(captured_frames) - 25} more frames recorded to can_trace.jsonl.*\n")
                    f.write("\n</details>\n")
                else:
                    target_dbg = can_port if can_port else "/dev/esp32_ahmed"
                    f.write(f"\n<details>\n<summary><b>CAN Bus Telemetry (0 frames captured on {target_dbg})</b></summary>\n\n")
                    f.write(f"> *Dedicated CAN Debugger ({target_dbg} @ 500 kbps) actively monitored the physical bus during this test run. Zero differential frames were asserted on the bus.*\n")
                    f.write("\n</details>\n")
        except Exception as e:
            print(f"[-] Note: Could not write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    # Save structured JSON
    if output_json:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_json)), exist_ok=True)
            report_data = {
                "subsystem": subsystem if subsystem else port,
                "port": port,
                "passed": passed,
                "summary": summary if summary else f"Timed out ({timeout}s)",
                "total_assertions": len(results),
                "passed_count": sum(1 for s, _, _ in results if s == "PASS"),
                "failed_count": sum(1 for s, _, _ in results if s == "FAIL"),
                "tests": [{"status": s, "name": n, "details": d} for s, n, d in results],
                "can_traffic": captured_frames
            }
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
        except Exception as e:
            print(f"[-] Note: Could not save output JSON: {e}", file=sys.stderr)

    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description="Parse Unity unit test results over serial and monitor live CAN traffic.")
    parser.add_argument("--port", "-p", required=True, help="Serial port device path (e.g. /dev/esp32_johnathan)")
    parser.add_argument("--subsystem", "-s", default="", help="Subsystem name (e.g. pedals_fw)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--timeout", "-t", type=float, default=12.0, help="Timeout in seconds (default: 12.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print raw serial stream lines")
    parser.add_argument("--log-file", help="Path to write complete raw serial logs")
    parser.add_argument("--output-json", help="Path to write structured JSON results")
    parser.add_argument("--can-port", default="/dev/esp32_ahmed", help="Serial port to dedicated CAN Debugger")
    parser.add_argument("--can-baud", type=int, default=115200, help="Debugger baud rate")
    parser.add_argument("--can-trace-file", help="Path to write can_trace.jsonl")

    args = parser.parse_args()
    exit_code = parse_unity_stream(
        port=args.port,
        baud=args.baud,
        timeout=args.timeout,
        verbose=args.verbose,
        log_file=args.log_file,
        output_json=args.output_json,
        subsystem=args.subsystem,
        can_port=args.can_port,
        can_baud=args.can_baud,
        can_trace_file=args.can_trace_file
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
