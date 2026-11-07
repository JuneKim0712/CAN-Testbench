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
import collections
import argparse

# Pre-compiled regular expressions for high-speed UART parsing
RE_CAN_FRAME = re.compile(r"\[CAN_FRAME\]")
RE_CAN_ID = re.compile(r"ID:(0x[0-9a-fA-F]+|\d+)")
RE_CAN_DLC = re.compile(r"DLC:(\d+)")
RE_CAN_DATA = re.compile(r"DATA:([0-9a-fA-F]*)")

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


def format_raw_payload(can_id: int, data: bytes) -> tuple[str, str]:
    """Formats raw CAN packet payload into precise hexadecimal and decimal representation without assumptions."""
    msg_name = f"FRAME_0x{can_id:03X}"
    if not data:
        return msg_name, "Empty Payload (DLC 0)"
    
    hex_str = data.hex().upper()
    if len(data) == 1:
        return msg_name, f"0x{hex_str} (Dec: {data[0]})"
    
    dec_list = list(data)
    return msg_name, f"0x{hex_str} (Dec: {dec_list})"


# ─── Live CAN Bus Monitor Thread ──────────────────────────────────────────────

class LiveCANMonitor(threading.Thread):
    def __init__(self, can_port: str = "", can_baud: int = 115200, unix_sock: str = "/tmp/calsol_can.sock"):
        super().__init__(daemon=True)
        self.can_port = can_port
        self.can_baud = can_baud
        self.unix_sock = unix_sock
        self.running = True
        self.frames = []
        self._lock = threading.Lock()
        self._recent_keys = collections.deque(maxlen=16)
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
        with self._lock:
            for cid, hstr, ts in self._recent_keys:
                if cid == can_id and hstr == hex_str and (now - ts) < 0.1:
                    return
            self._recent_keys.append((can_id, hex_str, now))
            self._record_frame_locked(can_id, dlc, data, now)

    def _record_frame(self, can_id: int, dlc: int, data: bytes):
        now = time.time()
        with self._lock:
            self._record_frame_locked(can_id, dlc, data, now)

    def _record_frame_locked(self, can_id: int, dlc: int, data: bytes, now: float):
        t_rel = now - self.start_time
        msg_name, signal_desc = format_raw_payload(can_id, data)
        hex_str = data.hex().upper()
        frame_obj = {
            "rel_time": f"+{t_rel:.3f}s",
            "timestamp": round(now, 4),
            "id": f"0x{can_id:03X}",
            "id_int": can_id,
            "name": msg_name,
            "dlc": dlc,
            "data": hex_str,
            "decoded": signal_desc
        }
        self.frames.append(frame_obj)
        print(f"    [CAN LIVE] {frame_obj['id']} ({msg_name}) DLC:{dlc} [{hex_str}] -> {signal_desc}")

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
                m_id = RE_CAN_ID.search(line)
                m_dlc = RE_CAN_DLC.search(line)
                m_data = RE_CAN_DATA.search(line)
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

    # Step summary is handled centrally by pr_reporter to keep summary dedicated to unit tests
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
