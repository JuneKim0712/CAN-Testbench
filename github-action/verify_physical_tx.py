#!/usr/bin/env python3
"""Bench acceptance: independent physical RX evidence for the lights sweep."""
import fcntl
import json
import pathlib
import socket
import subprocess
import threading
import time

from lib.unity_parser import parse_unity_stream


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    events = []
    stop = threading.Event()
    output = root / 'verification-results'
    output.mkdir(exist_ok=True)
    # Same device and shared-bus locks as the normal runner.
    lock_dir = pathlib.Path('/tmp/calsol_locks')
    lock_dir.mkdir(exist_ok=True)
    port = pathlib.Path('/dev/esp32_johnathan').resolve()
    with (lock_dir / ('hw' + str(port).replace('/', '_') + '.lock')).open('w') as device_lock, \
            (lock_dir / 'bus.lock').open('w') as bus_lock:
        fcntl.flock(device_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(bus_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(0.2)
            connection.connect('/tmp/calsol_can.sock')

            def capture():
                buffer = b''
                while not stop.is_set():
                    try:
                        data = connection.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buffer += data
                    while b'\n' in buffer:
                        line, _, buffer = buffer.partition(b'\n')
                        event = json.loads(line)
                        if event.get('event') == 'frame' and event.get('direction') == 'rx':
                            events.append(event)

            thread = threading.Thread(target=capture)
            thread.start()
            try:
                with (output / 'flash.log').open('w') as log:
                    subprocess.run(['idf.py', '-C', str(root / 'lights_fw/test'),
                                    '-p', str(port), '-b', '921600', 'flash'],
                                   check=True, stdout=log, stderr=subprocess.STDOUT)
                status = parse_unity_stream(str(port), timeout=15,
                    output_json=str(output / 'lights_test_results.json'),
                    log_file=str(output / 'lights_serial.log'), subsystem='lights_fw')
                time.sleep(0.3)
            finally:
                stop.set()
                thread.join(2)
                (output / 'physical_capture.json').write_text(json.dumps(events, indent=2))
    tokens = [bytes.fromhex(event.get('data') or event.get('raw', ''))
              for event in events if event.get('id_int') == 2 and event.get('dlc') == 1]
    expected = [bytes([i]) for i in range(1, 11)]
    report_path = output / 'lights_test_results.json'
    report = json.loads(report_path.read_text())
    report['unity_passed'] = report['passed']
    report['physical_rx_passed'] = tokens == expected
    report['passed'] = status == 0 and tokens == expected
    report['can_traffic'] = events
    report_path.write_text(json.dumps(report, indent=2))
    if status or tokens != expected:
        raise SystemExit(f'FAIL: Unity exit={status}; physical heartbeat payloads={tokens!r}')
    print('PASS: completed Unity suite and exactly ten independent physical RX tokens 1..10')


if __name__ == '__main__':
    main()
