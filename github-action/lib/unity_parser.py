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
import threading
import argparse
import uuid
import subprocess
from pathlib import Path

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


from can_bridge_daemon import decode_can_payload as format_raw_payload


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
        self.start_time = time.time()
        self.source = None
        self.ready = threading.Event()
        self.error = None

    def run(self):
        # 1. Try Unix domain socket (if can_bridge_daemon is already active)
        if hasattr(socket, "AF_UNIX") and os.path.exists(self.unix_sock):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(self.unix_sock)
                s.sendall(b'{"cmd":"ping"}\n')
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
                                if ev.get('status') == 'pong':
                                    if ev.get('serial_connected'):
                                        self.ready.set()
                                    else:
                                        self.error = 'Debugger serial is disconnected'
                                    drops = sum(ev.get('metrics', {}).get(k, 0) for k in
                                                ('delivery_drops', 'serial_overflows', 'serial_disconnects'))
                                    if hasattr(self, '_initial_drops') and drops != self._initial_drops:
                                        self.error = 'Capture gap reported by bridge'
                                    self._initial_drops = drops
                                if (ev.get("event") == "frame" and ev.get("direction") == "rx"
                                        and ev.get("source") == "physical_bus"):
                                    cid_val = ev.get("id_int", ev.get("id", 0))
                                    if isinstance(cid_val, str):
                                        can_id = int(cid_val, 16 if cid_val.lower().startswith("0x") else 10)
                                    else:
                                        can_id = int(cid_val)
                                    data_hex = ev.get("data") or ev.get("raw", "").replace(" ", "")
                                    data = bytes.fromhex(data_hex) if data_hex else b""
                                    dlc = int(ev.get("dlc", len(data)))
                                    src = ev.get("source", "physical_bus")
                                    self._record_frame(can_id, dlc, data, source=src, event=ev)
                            except Exception:
                                self.error = 'Invalid bridge event'
                    except socket.timeout:
                        s.sendall(b'{"cmd":"ping"}\n')
                        continue
                    except Exception:
                        break
                s.close()
                if self.running:
                    self.error = 'Bridge disconnected during capture'
                return
            except Exception:
                pass

        self.error = 'Bridge unavailable; direct debugger serial access is reserved for its service'

    def _record_frame(self, can_id: int, dlc: int, data: bytes, source: str = "physical_bus", event=None):
        now = time.time()
        with self._lock:
            self._record_frame_locked(can_id, dlc, data, now, source=source)
            if event:
                for key in ('schema_version', 'session_id', 'sequence', 'extended', 'rtr', 'timestamp'):
                    if key in event:
                        self.frames[-1][key] = event[key]

    def _record_frame_locked(self, can_id: int, dlc: int, data: bytes, now: float, source: str = "physical_bus"):
        t_rel = now - self.start_time
        msg_name, signal_desc = format_raw_payload(can_id, data)
        hex_str = data.hex().upper()
        frame_obj = {
            "rel_time": f"+{t_rel:.3f}s",
            "timestamp": round(now, 4),
            "source": source,
            "direction": "rx",
            "id": f"0x{can_id:03X}",
            "id_int": can_id,
            "name": msg_name,
            "dlc": dlc,
            "data": hex_str,
            "decoded": signal_desc
        }
        if len(self.frames) >= 100000:
            self.error = 'Capture limit exceeded'
            return
        self.frames.append(frame_obj)
        print(f"    [CAN LIVE] [{source}] {frame_obj['id']} ({msg_name}) DLC:{dlc} [{hex_str}] -> {signal_desc}")

    def stop(self):
        self.running = False


# ─── Master Stream Parser ─────────────────────────────────────────────────────

def parse_unity_stream(port: str, baud: int = 115200, timeout: float = 12.0, verbose: bool = False,
                       log_file: str = None, output_json: str = None, subsystem: str = "",
                       can_port: str = "", can_baud: int = 115200, can_trace_file: str = None,
                       flash_build: str = None, flash_baud: int = 921600, run_id: str = None,
                       manifest: str = None) -> int:
    run_id = run_id or uuid.uuid4().hex
    can_monitor = LiveCANMonitor(can_port=can_port, can_baud=can_baud)
    can_monitor.start()
    if flash_build:
        if not can_monitor.ready.wait(3):
            can_monitor.stop()
            can_monitor.join(timeout=1)
            raise RuntimeError(can_monitor.error or 'Bridge subscription not ready')
        # Flash from generated metadata without starting the application. This
        # subscribes first and avoids assuming a factory partition offset.
        build = Path(flash_build).resolve()
        metadata = json.loads((build / 'flasher_args.json').read_text())
        command = [sys.executable, '-m', 'esptool', '--chip',
                   metadata['extra_esptool_args']['chip'], '--port', port,
                   '--baud', str(flash_baud), '--after', 'no-reset', 'write-flash']
        command += metadata.get('write_flash_args', [])
        for offset, filename in metadata['flash_files'].items():
            command += [offset, str(build / filename)]
        try:
            subprocess.run(command, cwd=build, check=True)
        except BaseException:
            can_monitor.stop()
            can_monitor.join(timeout=1)
            raise
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"[-] Serial error on {port}: {e}", file=sys.stderr)
        can_monitor.stop()
        can_monitor.join(timeout=1)
        return 1

    # Start live CAN monitoring
    if flash_build:
        from esptool.reset import HardReset
        ser.reset_input_buffer()
        # pyserial opens with DTR asserted. Release the download strap before
        # resetting; otherwise native USB re-enters the bootloader.
        ser.dtr = False
        HardReset(ser, uses_usb=True)()

    start_time = time.time()
    deadline = time.monotonic() + timeout
    passed = False
    summary = ""
    results = []  # List of tuples: (status, test_name, raw_line)
    all_raw_lines = []

    try:
        while time.monotonic() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            all_raw_lines.append(line)
            if any(marker in line for marker in ('Guru Meditation', 'abort() was called', 'assert failed:')):
                summary = 'Firmware crashed'
                break

            if verbose:
                print(f"  [RAW] {line}")

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
                results.append(("FAIL", test_name, line))
                print(f"    [FAIL] {test_name}: {msg if msg else line}")
            elif ":IGNORE" in line:
                idx = line.find(":IGNORE")
                prefix = line[:idx]
                test_name = prefix.split(":")[-1]
                msg = line[idx + 7:].lstrip(":").strip()
                results.append(("IGNORE", test_name, line))
                print(f"    [IGNORE] {test_name}")
            elif "Tests" in line and "Failures" in line:
                summary = line
                m_summary = re.fullmatch(r"(\d+)\s+Tests\s+(\d+)\s+Failures\s+(\d+)\s+Ignored", line)
                if m_summary:
                    total_cnt = int(m_summary.group(1))
                    fail_cnt = int(m_summary.group(2))
                    ignored_cnt = int(m_summary.group(3))
                    if (fail_cnt == 0 and total_cnt > 0 and len(results) == total_cnt
                            and total_cnt > ignored_cnt
                            and ignored_cnt == sum(status == 'IGNORE' for status, _, _ in results)
                            and not any(status == "FAIL" for status, _, _ in results)):
                        passed = True
                break
    finally:
        ser.close()
        can_monitor.stop()
        can_monitor.join(timeout=0.6)

    captured_frames = can_monitor.frames
    expected_ok = True
    if manifest:
        config = json.loads(Path(manifest).read_text())
        for expectation in config.get('expected_can', []):
            actual = [fr['data'].upper() for fr in captured_frames if fr['id_int'] == expectation['id']]
            if actual != [data.upper() for data in expectation['data']]:
                expected_ok = False
    passed = passed and expected_ok
    if not expected_ok:
        summary += ' (required physical CAN frames missing or mismatched)'
    if flash_build and can_monitor.error:
        passed = False

    # Save raw log file for crash decoder
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            with open(log_file, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(all_raw_lines) + "\n")
        except Exception as e:
            print(f"[-] Note: Failed to save test log file: {e}", file=sys.stderr)

    # Save CAN trace JSONL if captured
    if can_trace_file:
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
                "run_id": run_id,
                "capture_error": can_monitor.error,
                "physical_expectations_passed": expected_ok,
                "verification_mode": "physical_can" if manifest and config.get("expected_can") else "on_target_logic",
                "started_at": start_time,
                "port": port,
                "passed": passed,
                "summary": summary if summary else f"Timed out ({timeout}s)",
                "total_assertions": len(results),
                "passed_count": sum(1 for s, _, _ in results if s == "PASS"),
                "failed_count": sum(1 for s, _, _ in results if s == "FAIL"),
                "duration": round(time.time() - start_time, 3),
                "tests": [test_record(s, n, d) for s, n, d in results],
                "can_traffic": captured_frames
            }
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
        except Exception as e:
            print(f"[-] Note: Could not save output JSON: {e}", file=sys.stderr)

    return 0 if passed else 1


def test_record(status, name, details):
    match = re.match(r'^(.*?):(\d+):', details)
    return dict(status=status, name=name, details=details,
                file=match.group(1) if match else None,
                line=int(match.group(2)) if match else None)


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
    parser.add_argument("--flash-build", help="Built ESP-IDF directory to flash after capture subscribes")
    parser.add_argument("--flash-baud", type=int, default=921600)
    parser.add_argument("--run-id")
    parser.add_argument("--manifest")

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
        can_trace_file=args.can_trace_file,
        flash_build=args.flash_build, flash_baud=args.flash_baud, run_id=args.run_id,
        manifest=args.manifest
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
