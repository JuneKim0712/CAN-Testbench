# CalSol Gen 11 Hardware-in-the-Loop (HIL) Testbench & CI Platform

Continuous hardware integration, automated on-target silicon testing, and CAN bus telemetry validation for the UC Berkeley Solar Vehicle Team (**CalSol**).

This platform validates embedded vehicle firmware on physical microcontrollers and differential bus hardware before deployment to the Gen 11 solar car, serving both as the automated Hardware-in-the-Loop (HIL) test harness and as the reusable CI workflow engine for [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW).

---

### Quick Links & Interactive Dashboards
* **Interactive Web Telemetry Portal:** [https://junekim0712.github.io/CAN-Testbench/](https://junekim0712.github.io/CAN-Testbench/)
* **Pedals / Brake Nominal Run (7/7 Passed):** [View `pedals_fw` Run](https://junekim0712.github.io/CAN-Testbench/?subsystem=pedals_fw&run=42325039593-pedals)
* **Lights Nominal Run (3/3 Passed):** [View `lights_fw` Run](https://junekim0712.github.io/CAN-Testbench/?subsystem=lights_fw&run=42325039593-lights)
* **GitHub Actions CI Dashboard:** [https://github.com/JuneKim0712/CAN-Testbench/actions](https://github.com/JuneKim0712/CAN-Testbench/actions)
* **Technical Architecture Manual:** [`docs/CODE_DOCUMENTATION.md`](docs/CODE_DOCUMENTATION.md)
* **Bench Operational Manual:** [`docs/CAN_TESTBENCH_STAGE_GUIDE.md`](docs/CAN_TESTBENCH_STAGE_GUIDE.md)

---

## Table of Contents
1. [System Overview & Architecture Topology](#1-system-overview--architecture-topology)
2. [Complete Setup Guide](#2-complete-setup-guide)
   - [2.1 Hardware Requirements & Wiring](#21-hardware-requirements--wiring)
   - [2.2 Host System Configuration (Linux / Raspberry Pi)](#22-host-system-configuration-linux--raspberry-pi)
   - [2.3 Software Toolchain & Environment](#23-software-toolchain--environment)
3. [Unit Testing Guide](#3-unit-testing-guide)
   - [3.1 On-Target Execution Architecture](#31-on-target-execution-architecture)
   - [3.2 Running Subsystem Tests Locally](#32-running-subsystem-tests-locally)
   - [3.3 Writing a New Unit Test Suite](#33-writing-a-new-unit-test-suite)
   - [3.4 Viewing & Interpreting Test Outcomes](#34-viewing--interpreting-test-outcomes)
4. [Script Debugging Guide](#4-comprehensive-script-debugging-guide)
   - [4.1 Master Test Runner (`cal-test.sh`)](#41-master-test-runner-cal-testsh)
   - [4.2 Serial & CAN Stream Monitor (`unity_parser.py`)](#42-serial--can-stream-monitor-unity_parserpy)
   - [4.3 High-Speed CAN Bridge Daemon (`can_bridge_daemon.py`)](#43-high-speed-can-bridge-daemon-can_bridge_daemonpy)
   - [4.4 Guru Meditation Panic Decoder (`crash_decoder.py`)](#44-guru-meditation-panic-decoder-crash_decoderpy)
   - [4.5 Cloud Quality Gate (`static_check.py`)](#45-cloud-quality-gate-static_checkpy)
   - [4.6 Subsystem Auto-Discovery (`auto_discover.py`)](#46-subsystem-auto-discovery-auto_discoverpy)
   - [4.7 Telemetry Ingestion Engine (`pages_compiler.py`)](#47-telemetry-ingestion-engine-pages_compilerpy)
   - [4.8 Failure Triage & Troubleshooting Matrix](#48-failure-triage--troubleshooting-matrix)
5. [Repository Layout](#5-repository-layout)
6. [Continuous Integration Workflow](#6-continuous-integration-workflow)
7. [Trackside Flashing & Safety Protocols](#7-trackside-flashing--safety-protocols)

---

## 1. System Overview & Architecture Topology

The testbench operates on a dedicated physical host (`stolerpi` (Raspberry Pi 5)) directly wired to dual ESP32-S3 microcontroller nodes sharing a physical, differential 500 kbps CAN 2.0B bus:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      Raspberry Pi 5 Host (stolerpi)                    │
 │                                                                        │
 │   ┌───────────────────────┐              ┌─────────────────────────┐   │
 │   │  HIL Test Runner      │              │  CAN Bridge Daemon      │   │
 │   │  (cal-test.sh)        │              │  (can_bridge_daemon.py) │   │
 │   └──────────┬────────────┘              └────────────┬────────────┘   │
 └──────────────┼────────────────────────────────────────┼────────────────┘
                │ USB CDC-ACM                            │ USB CDC-ACM
                ▼ (/dev/esp32_johnathan)                 ▼ (/dev/esp32_ahmed)
 ┌─────────────────────────────────┐        ┌─────────────────────────────┐
 │  Node 2: Device Under Test     │        │  Node 1: CAN Bus Debugger   │
 │  ESP32-S3 Microcontroller       │        │  ESP32-S3 Microcontroller   │
 │  TI TCAN332 CAN Transceiver     │        │  TI TCAN332 CAN Transceiver │
 └────────────────┬────────────────┘        └──────────────┬──────────────┘
                  │                                        │
                  ▼                                        ▼
 ══════════════════════════════════════════════════════════════════════════
               Physical CAN 2.0B Bus (500 kbps, 120Ω Terminated)
 ══════════════════════════════════════════════════════════════════════════
```

| Node | Physical Port Symlink | Role | Details |
| :--- | :--- | :--- | :--- |
| **Node 1** | `/dev/esp32_ahmed` | **CAN Bus Debugger** | Dedicated passive listener. Samples differential traffic at 500 kbps, decodes COBS frames, and broadcasts events to `/tmp/calsol_can.sock`. |
| **Node 2** | `/dev/esp32_johnathan` | **Device Under Test (DUT)** | Target node. Flashed on-the-fly with subsystem unit test firmware (`pedals_fw`, `lights_fw`). Evaluated for Unity assertions. |
| **Bus Backbone** | Differential Twisted Pair | **CAN 2.0B Vehicle Bus** | High-speed vehicle bus (500 kbps, 20 Time Quanta, 80% sample point) terminated with dual $120\,\Omega$ split termination resistors ($60\,\Omega$ equivalent). |

---

## 2. Complete Setup Guide

Follow this guide to commission a new engineering laptop or Raspberry Pi lab runner from scratch.

### 2.1 Hardware Requirements & Wiring

1. **Microcontrollers & Transceivers:**
   - 2x ESP32-S3 DevKits (ESP32-S3-WROOM-1).
   - 2x TI TCAN332 (or ISO 11898-2 compatible 3.3V CAN transceivers).
2. **Pin Assignments (Both Nodes):**
   - `GPIO 17` $\rightarrow$ Transceiver **TXD**
   - `GPIO 18` $\rightarrow$ Transceiver **RXD**
   - `3.3V` & `GND` $\rightarrow$ Transceiver Power
3. **Differential Bus Wiring:**
   - Connect Node 1 **CAN_H** to Node 2 **CAN_H**.
   - Connect Node 1 **CAN_L** to Node 2 **CAN_L**.
   - Install a $120\,\Omega$, 1/4W resistor across CAN_H and CAN_L at both physical ends of the twisted pair.
   - **Verification:** Measure resistance between CAN_H and CAN_L with power disconnected. The multimeter must read $60\,\Omega \pm 3\,\Omega$.

---

### 2.2 Host System Configuration (Linux / Raspberry Pi)

To ensure persistent device names regardless of USB plug order, configure custom `udev` rules:

1. **Create the udev rule file:**
   ```bash
   sudo nano /etc/udev/rules.d/99-calsol-hil.rules
   ```

2. **Add the persistent symlinks (matched by USB vendor/product IDs or serials):**
   ```udev
   # Node 1: CAN Bus Debugger (/dev/esp32_ahmed)
   SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="AHMED_*", SYMLINK+="esp32_ahmed", MODE="0666"

   # Node 2: Device Under Test (/dev/esp32_johnathan)
   SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="JOHNATHAN_*", SYMLINK+="esp32_johnathan", MODE="0666"
   ```

3. **Reload rules and add your user to the serial groups:**
   ```bash
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   sudo usermod -a -G dialout,plugdev $USER
   ```
   *(Log out and log back in for group permissions to take effect)*.

4. **Verify device detection:**
   ```bash
   ls -la /dev/esp32_*
   # Expected output:
   # lrwxrwxrwx 1 root root /dev/esp32_ahmed -> ttyACM0
   # lrwxrwxrwx 1 root root /dev/esp32_johnathan -> ttyACM1
   ```

---

### 2.3 Software Toolchain & Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/CalSol/CAN_TestBench.git
   cd CAN_TestBench
   ```

2. **Install system utilities:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y git python3 python3-pip python3-venv ccache cppcheck
   ```

3. **Install Python host dependencies:**
   ```bash
   pip3 install --user pyserial
   ```

4. **Install and Source ESP-IDF (v5.1+ or v5.3+ recommended):**
   ```bash
   # If ESP-IDF is not yet installed:
   mkdir -p ~/esp && cd ~/esp
   git clone --recursive https://github.com/espressif/esp-idf.git -b v5.3.1
   cd esp-idf && ./install.sh esp32s3

   # Export environment to current shell:
   . ~/esp/esp-idf/export.sh
   ```
   *(Verify installation by typing `idf.py --version`)*.

---

## 3. Unit Testing Guide

### 3.1 On-Target Execution Architecture

Unlike host-simulated unit tests, CalSol executes tests **directly on the physical microcontroller core**:
1. ESP-IDF compiles the test runner, production subsystem logic, and the Unity test harness into a trackside `.elf` and `.bin`.
2. `cal-test.sh` acquires a hardware mutex (`/tmp/calsol_locks/esp32_johnathan.lock`), ensuring zero device collisions.
3. High-speed flashing writes the image to flash at 921,600 baud in $< 3.5\,\text{s}$.
4. The DUT boots, initializes the on-chip TWAI peripheral, and prints test assertions to UART serial using the format:
   ```text
   main/test_main.c:196:test_throttle_calculation_and_deadzone:PASS
   main/test_main.c:197:test_brake_plausibility_safety_interlock:PASS
   ```
5. Any CAN frames transmitted during test assertions (`CAN_send`) broadcast across physical copper and are sampled by Node 1.

---

### 3.2 Running Subsystem Tests Locally

Execute unit tests directly from the repository root:

```bash
# 1. Execute pedals_fw unit tests (Accelerator, Deadzones, Plausibility interlock)
./github-action/cal-test.sh pedals_fw/test

# 2. Execute lights_fw unit tests (LTC4151 ADC voltage conversion, state machine)
./github-action/cal-test.sh lights_fw/test

# 3. Execute with explicit port override and custom 20-second timeout:
./github-action/cal-test.sh pedals_fw/test /dev/esp32_johnathan 20
```

#### What `pedals_fw` Tests Validate:
* `test_throttle_calculation_and_deadzone`: Validates ADC mapping below deadzone ($ADC \le 500 \rightarrow 0\%$), nominal curve, and saturation ($ADC \ge 3500 \rightarrow 100\%$).
* `test_brake_plausibility_safety_interlock`: Enforces FSAE and CalSol EV safety rules: if mechanical brake is pressed, throttle demand $> 25\%$ immediately cuts motor demand to $0\%$.
* `test_can_packet_builder_clamping_and_zeroing`: Validates DLC clamping to 8 bytes and zero-padding of unwritten payload bytes.
* `test_can_driver_lifecycle`: Verifies driver initialization, duplicate initialization protection (`ESP_ERR_INVALID_STATE`), and deinitialization.
* `test_can_receive_timeout`: Verifies that `CAN_receive()` accurately times out when no bus traffic is present without blocking the RTOS task.
* `test_pedal_can_transmission`: Performs a physical transmission sweep ($10\% \rightarrow 100\%$) broadcasting frames `0x011` onto the bus.

#### What `lights_fw` Tests Validate:
* `test_voltage_conversion`: Verifies LTC4151 current/voltage ADC scalar calculations.
* `test_state_toggle`: Verifies braking/hazard state machine transitions.
* `test_can_message_format`: Validates lighting system CAN frame payloads (`0x021`).

---

### 3.3 Writing a New Unit Test Suite

To add a new test suite to an existing subsystem or create a new ECU subsystem:

1. **Create the test directory structure:**
   ```bash
   mkdir -p bms_fw/test/main
   ```

2. **Add the manifest (`bms_fw/testbench.json`):**
   ```json
   {
     "name": "bms_fw",
     "target": "bms_fw/test",
     "port": "/dev/esp32_johnathan",
     "baud": 921600,
     "timeout": 15,
     "description": "Battery Management System Voltage & Thermal Interlock Assertions"
   }
   ```

3. **Configure the test build files:**
   * In `bms_fw/test/CMakeLists.txt`:
     ```cmake
     cmake_minimum_required(VERSION 3.16)
     include($ENV{IDF_PATH}/tools/cmake/project.cmake)
     project(bms_fw_test)
     ```
   * In `bms_fw/test/main/CMakeLists.txt`:
     ```cmake
     idf_component_register(SRCS "test_main.c"
                            INCLUDE_DIRS "."
                            REQUIRES unity can_driver)
     ```
   * In `bms_fw/test/sdkconfig.defaults`:
     ```ini
     CONFIG_IDF_TARGET="esp32s3"
     ```

4. **Write the Unity test cases (`bms_fw/test/main/test_main.c`):**
   ```c
   #include <stdio.h>
   #include "unity.h"
   #include "freertos/FreeRTOS.h"
   #include "freertos/task.h"
   #include "CAN.h"

   static void test_cell_voltage_undervoltage_cutoff(void) {
       uint16_t sample_mv = 2750; // 2.75V (below 2.8V cutoff threshold)
       bool trip = (sample_mv < 2800);
       TEST_ASSERT_TRUE(trip);
   }

   void app_main(void) {
       vTaskDelay(pdMS_TO_TICKS(1500)); // Allow serial & PLL to stabilize
       UNITY_BEGIN();
       RUN_TEST(test_cell_voltage_undervoltage_cutoff);
       UNITY_END();
   }
   ```

5. **Test locally before pushing:**
   ```bash
   ./github-action/cal-test.sh bms_fw/test
   ```

---

### 3.4 Viewing & Interpreting Test Outcomes

1. **Terminal Console Output:**
   Passes appear in green; failed assertions immediately display the exact C source file and line number:
   ```text
   [+] Tests: 7 Failures: 0 Ignored: 0 (ALL PASSED)
   [+] Captured 10 physical CAN frames on bus during test run.
   ```
2. **GitHub Actions Step Summary:**
   Every CI run features a **dedicated Unit Test Assertions Breakdown table** showing status, subsystem, function name, file location, and diagnostic diffs.
3. **Interactive Web Portal:**
   Visit [`https://junekim0712.github.io/CAN-Testbench/`](https://junekim0712.github.io/CAN-Testbench/) to filter runs by ECU (`[ALL RUNS]`, `[PEDALS_FW]`, `[LIGHTS_FW]`), inspect CAN timing waveforms, and review historic assertion trends.

---

## 4. Script Debugging Guide

### 4.1 Master Test Runner (`cal-test.sh`)

`cal-test.sh` is the central orchestrator that coordinates build compilation, hardware locks, binary flashing, and test ingestion.

#### Common Failure Scenarios & Fixes:

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

### 4.2 Serial & CAN Stream Monitor (`unity_parser.py`)

`unity_parser.py` reads the DUT serial stream, parses Unity assertion lines, starts the CAN bus listening thread, and writes structured JSON test reports.

#### Debugging Commands:

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
  If the serial output appears as garbled junk (``), the board is logging at a non-standard baud rate. Verify that `sdkconfig.defaults` specifies `CONFIG_ESP_CONSOLE_UART_BAUDRATE=115200`.

---

### 4.3 High-Speed CAN Bridge Daemon (`can_bridge_daemon.py`)

The daemon connects to the dedicated debugger (`/dev/esp32_ahmed`), decodes COBS frame packets, writes to `can_trace.jsonl`, and broadcasts JSON events across Unix domain sockets (`/tmp/calsol_can.sock`) and TCP (`5555`).

#### Troubleshooting:

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

### 4.4 Guru Meditation Panic Decoder (`crash_decoder.py`)

When an ESP-IDF firmware panic occurs, the microcontroller dumps raw register states and program counter addresses (e.g. `Backtrace: 0x42001a2b:0x3fc9a100 0x420023c4:...`).

#### Troubleshooting:

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

### 4.5 Cloud Quality Gate (`static_check.py`)

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

### 4.6 Subsystem Auto-Discovery (`auto_discover.py`)

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

### 4.7 Telemetry Ingestion Engine (`pages_compiler.py`)

Compiles test results (`*test_results*.json`) and CAN traffic traces (`*can_trace*.jsonl`) into `web/data/history.json` for the web dashboard.

* **Testing Ingestion Locally:**
  ```bash
  python3 github-action/lib/pages_compiler.py
  ```
* **Verifying History JSON Format:**
  ```bash
  python3 -c "import json; d=json.load(open('web/data/history.json')); print('Total Runs:', len(d['runs']))"
  ```

---

### 4.8 Failure Triage & Troubleshooting Matrix

| Symptom | Probable Cause | Instant Diagnostic & Fix Command |
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

## 5. Repository Layout

```text
CAN_TestBench/
├── .github/
│   └── workflows/
│       ├── unit-test.yml           # Monorepo CI workflow (push, PR, dispatch)
│       ├── deploy-pages.yml        # Continuous deployment to GitHub Pages
│       └── testbench.yml           # Reusable workflow for external ECU repositories
│
├── components/                     # Shared firmware components (synchronized with Gen11-FW)
│   └── can_driver/                 # Universal TWAI/CAN driver (CAN.h, CAN_driver.c)
│
├── pedals_fw/                      # Subsystem: Accelerator & Brake Plausibility
│   ├── testbench.json              # HIL hardware testbench specification
│   ├── main/                       # Operational subsystem firmware
│   └── test/                       # Unity on-target test suite
│
├── lights_fw/                      # Subsystem: Brakelights & Hazards
│   ├── testbench.json              # HIL hardware testbench specification
│   ├── main/                       # Operational subsystem firmware
│   └── test/                       # Unity on-target test suite
│
├── sim/                            # Simulation & Software Board Emulation
│   └── virtual_ecus/               # Software-defined mock ECUs (BMS, Motor Controller, Steering)
│
├── docs/                           # Hardware testbench architectural & stage guides
│   ├── CODE_DOCUMENTATION.md       # Complete code & architectural reference manual
│   └── CAN_TESTBENCH_STAGE_GUIDE.md # Stage-by-stage operational & engineering manual
│
├── web/                            # Interactive Telemetry & Testbench Web Portal (GitHub Pages)
│   ├── index.html                  # Minimalist, right-angled telemetry dashboard
│   └── data/
│       └── history.json            # Cumulative testbench run records & bus traces
│
└── github-action/                  # Testbench runner scripts & ingestion libraries
    ├── action.yml                  # Standalone GitHub Composite Action definition
    ├── cal-test.sh                 # Master test execution runner (build, flash, parse, report)
    ├── cal-flash.sh                # Standalone safe firmware flashing tool
    ├── static-check.sh             # Cloud static analysis & quality gate runner
    └── lib/
        ├── auto_discover.py        # Subsystem discovery & git change resolver
        ├── unity_parser.py         # Serial parser, test evaluator, and step summary writer
        ├── can_bridge_daemon.py    # Host CAN ingestion daemon & socket server
        ├── crash_decoder.py        # ESP32 panic register & stack backtrace decoder
        ├── pages_compiler.py       # Ingests telemetry & compiles web/data/history.json
        ├── pr_reporter.py          # Consolidated test dashboard & PR comment reporter
        ├── calsol_snoop.py         # CLI live CAN bus snooper tool
        └── calsol_inject.py        # CLI CAN frame injector tool
```

---

## 6. Continuous Integration Workflow

On every pull request and push to `main`, GitHub Actions executes:

1. **Pre-Hardware Quality Gate (`static-analysis`):** Cppcheck scans all C/C++ sources for critical defects.
2. **Matrix Discovery (`discover`):** Inspects Git change deltas. Only subsystems with modified files are scheduled.
3. **Hardware Execution (`testbench`):** Dispatches matrix jobs in parallel to physical silicon on `stolerpi`. Each job:
   - Compiles firmware using `ccache` acceleration.
   - Acquires the hardware mutex lock.
   - Flashes the target microcontroller.
   - Streams serial output and decodes live CAN bus traffic via `/dev/esp32_ahmed`.
   - Captures any Guru Meditation crash dumps and resolves stack addresses to line numbers.
4. **Consolidated Dashboard (`report`):** Aggregates unit test tables and failure diagnostics into the GitHub Actions Step Summary.
5. **Interactive Telemetry Portal Deployment (`deploy-pages`):** Recompiles historical runs into `web/data/history.json` and deploys to GitHub Pages.

---

## 7. Trackside Flashing & Safety Protocols

Precompiled firmware binaries (`.bin`, `.elf`, `bootloader.bin`) are automatically archived in GitHub Run Artifacts on every build.

### Trackside Single-Command Flashing:
```bash
python3 -m esptool --chip esp32s3 -p /dev/esp32_johnathan -b 921600 write_flash 0x10000 pedals_fw.bin
```

### High-Voltage DC & Bus Safety Protocols:
1. **DC Voltage Check:** Ensure the high-voltage traction pack is isolated and interlocks are disengaged before touching ECU transceivers.
2. **Split Termination Verification:** Never operate the vehicle bus without both $120\,\Omega$ termination resistors installed (equivalent resistance must be $60\,\Omega$).
3. **Signal Ground:** Always ensure a common ground reference between the host testbench and the ECU ground plane to prevent ground loop damage to transceiver chips.
