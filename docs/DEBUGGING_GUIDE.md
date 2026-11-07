# CalSol Hardware Testbench: Script Debugging & Triage Manual

| [Overview](../README.md) | [Tutorial](TUTORIAL.md) | [Contributing](../CONTRIBUTING.md) | [Architecture](CODE_DOCUMENTATION.md) | [Bench Manual](CAN_TESTBENCH_STAGE_GUIDE.md) | [Hardware Setup](SETUP_GUIDE.md) | **[Debugging]** | [Live Portal ↗](https://junekim0712.github.io/CAN-Testbench/) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |

---

This guide provides exhaustive failure triage scenarios, script debugging steps, and diagnostic commands for the testbench toolchain.

---

## 1. Master Test Runner (`cal-test.sh`)

`cal-test.sh` coordinates build compilation, hardware mutex locking, binary flashing, and test ingestion.

### Common Failure Scenarios & Fixes:

* **Symptom 1: `[-] Error: idf.py not found and could not locate export.sh`**
  * *Root Cause:* The ESP-IDF toolchain is not sourced in the active shell.
  * *Resolution:* Run `. ~/esp/esp-idf/export.sh` or ensure ESP-IDF is installed in `/opt/esp-idf` or `~/esp/esp-idf`.

* **Symptom 2: `[-] ERROR: Board 'esp32_johnathan' is currently in use by another process!`**
  * *Root Cause:* A previous test run crashed or was killed with `kill -9`, leaving an orphaned lock in `/tmp/calsol_locks/`.
  * *Resolution:* Check lock ownership and clear stale locks:
    ```bash
    fuser /tmp/calsol_locks/esp32_johnathan.lock
    rm -f /tmp/calsol_locks/*.lock
    ```

* **Symptom 3: `[-] Flashing failed!`**
  * *Root Cause:* The target ESP32-S3 is stuck in deep sleep or crashed firmware has seized the USB JTAG/serial interface.
  * *Resolution:*
    1. Check `/github-action/.logs/flash.log` for exact esptool errors.
    2. Force ROM Download Mode: **Hold down the BOOT button**, tap the **RESET button**, then release **BOOT**.
    3. Re-run `./github-action/cal-test.sh pedals_fw/test`.

* **Symptom 4: `[-] Timed out (15s) waiting for Unity test output.`**
  * *Root Cause:* The firmware panicked before reaching `app_main`, or an unhandled infinite loop occurred before `UNITY_BEGIN()`.
  * *Resolution:* Inspect the raw UART stream generated in the log directory:
    ```bash
    cat github-action/.logs/pedals_fw_serial.log
    ```

---

## 2. Serial & CAN Stream Monitor (`unity_parser.py`)

`unity_parser.py` reads the DUT serial stream, parses Unity assertion lines, starts the CAN bus listening thread, and writes structured JSON test reports.

### Debugging Commands:

* **Verbose Stream Inspection:**
  Run the parser directly with the `--verbose` flag to see every raw line emitted by the microcontroller:
  ```bash
  python3 github-action/lib/unity_parser.py \
      --port /dev/esp32_johnathan \
      --subsystem pedals_fw \
      --timeout 15 \
      --verbose
  ```
* **Baud Rate Mismatch:**
  If the serial output appears as garbled junk, the board is logging at a non-standard baud rate. Verify that `sdkconfig.defaults` specifies `CONFIG_ESP_CONSOLE_UART_BAUDRATE=115200`.

---

## 3. High-Speed CAN Bridge Daemon (`can_bridge_daemon.py`)

The daemon connects to the dedicated debugger (`/dev/esp32_ahmed`), decodes COBS frame packets, writes to `can_trace.jsonl`, and broadcasts JSON events across Unix domain sockets (`/tmp/calsol_can.sock`) and TCP (`5555`).

### Troubleshooting:

* **Checking if the Daemon is Running:**
  ```bash
  ps aux | grep can_bridge_daemon
  ```
* **Diagnosing Stale Sockets:**
  If the daemon reports `Address already in use`, delete the orphaned Unix socket file:
  ```bash
  rm -f /tmp/calsol_can.sock
  ```
* **Sniffing Live Bus Traffic via CLI:**
  Verify that the physical bus is alive by streaming live frames in your terminal:
  ```bash
  python3 github-action/lib/calsol_snoop.py
  # Or filter for a specific CAN ID:
  python3 github-action/lib/calsol_snoop.py --id 0x011
  ```
* **Injecting a Frame to Test Physical Loopback:**
  ```bash
  python3 github-action/lib/calsol_inject.py --id 0x123 --data 0102030405
  ```

---

## 4. Guru Meditation Panic Decoder (`crash_decoder.py`)

When an ESP-IDF firmware panic occurs, the microcontroller dumps raw register states and program counter addresses (e.g. `Backtrace: 0x42001a2b:0x3fc9a100 0x420023c4:...`).

### Troubleshooting:

* **Running the Decoder Manually:**
  ```bash
  python3 github-action/lib/crash_decoder.py \
      --log-file github-action/.logs/pedals_fw_serial.log \
      --elf-file pedals_fw/test/build/pedals_fw_test.elf
  ```
* **`addr2line` Not Found:**
  Ensure the Xtensa toolchain is present in your PATH:
  ```bash
  which xtensa-esp32s3-elf-addr2line
  # If missing, source ESP-IDF:
  . ~/esp/esp-idf/export.sh
  ```
* **Direct Terminal Decoding:**
  If you have a raw backtrace address, decode it directly from the `.elf` file:
  ```bash
  xtensa-esp32s3-elf-addr2line -pfia -e pedals_fw/test/build/pedals_fw_test.elf 0x42001a2b
  ```

---

## 5. Cloud Quality Gate (`static_check.py`)

Runs `cppcheck` before silicon is flashed, catching memory leaks, uninitialized variables, and out-of-bounds pointer arithmetic.

* **Running Static Check Locally:**
  ```bash
  ./github-action/static-check.sh
  ```
* **Suppressing Known Hardware Register False-Positives:**
  If `cppcheck` flags a false positive on an intentional hardware address or macro, add an inline suppression comment:
  ```c
  // cppcheck-suppress arrayIndexOutOfBounds
  volatile uint32_t *reg = (volatile uint32_t *)0x60004000;
  ```

---

## 6. Subsystem Auto-Discovery (`auto_discover.py`)

Scans the repository for directories containing `testbench.json` and evaluates git changes against the base branch.

* **Testing Discovery Output Locally:**
  ```bash
  # Test auto-discovery with default git change evaluation:
  python3 github-action/lib/auto_discover.py --repo-root .

  # Force discovery of all configured subsystems:
  INPUT_TARGET="all" python3 github-action/lib/auto_discover.py --repo-root .
  ```
* **Why Was My Subsystem Skipped?**
  1. Verify that `testbench.json` exists in your subsystem folder (subsystems without `testbench.json` are intentionally excluded).
  2. If running on a PR branch, check `git diff --name-only origin/main...HEAD`. If no files in your subsystem folder were modified, CI skips testing to save hardware runner time.

---

## 7. Failure Triage & Troubleshooting Matrix

| Failure Symptom | Probable Cause | Immediate Diagnostic & Fix Command |
| :--- | :--- | :--- |
| **`Board is currently in use`** | Stale `/tmp/calsol_locks/*.lock` | `rm -f /tmp/calsol_locks/*.lock` |
| **`idf.py: command not found`** | ESP-IDF environment not loaded | `. ~/esp/esp-idf/export.sh` |
| **`Permission denied: /dev/ttyACM*`** | User missing `dialout` group permissions | `sudo usermod -a -G dialout $USER && newgrp dialout` |
| **`Flashing timed out / failed`** | Chip seized by crashed firmware | Hold **BOOT**, press **RESET**, release **BOOT**, re-run |
| **`Address already in use (sock)`** | Orphaned `/tmp/calsol_can.sock` | `rm -f /tmp/calsol_can.sock` |
| **`No CAN frames captured`** | Transceiver disconnected or unpowered | Check 12V DC bench power & verify $60\,\Omega$ termination |
| **`Unity Parser timed out`** | UART baud mismatch or early crash | Check `cat github-action/.logs/*_serial.log` |
| **`Subsystem skipped in CI`** | Missing `testbench.json` | Ensure `testbench.json` is committed in subsystem root |

---

[↑ Back to top](#calsol-hardware-testbench-script-debugging--triage-manual)
