# CalSol Hardware CAN Testbench: Stage-by-Stage Operational & Engineering Manual

This manual is the definitive, beginner-accessible guide to the **CalSol Hardware-in-the-Loop (HIL) CAN Testbench**. It explains how the entire system works—from physical silicon and wiring to cloud continuous integration—broken down into clear, progressive stages. 

Whether you are a new firmware developer writing your first driver or a test engineer evaluating vehicle safety, this guide provides the concepts, architectural diagrams, and step-by-step commands needed to operate the bench without prior knowledge of the codebase.

---

## Table of Contents
1. [System Overview & Philosophy](#1-system-overview--philosophy)
2. [Stage 1: Physical Hardware & Bench Architecture](#stage-1-physical-hardware--bench-architecture)
3. [Stage 2: Remote Flashing & Interactive Serial Monitoring](#stage-2-remote-flashing--interactive-serial-monitoring)
4. [Stage 3: Remote CAN Packet Snooping & Injection](#stage-3-remote-can-packet-snooping--injection)
5. [Stage 4: Software Board Emulation (Virtual ECUs)](#stage-4-software-board-emulation-virtual-ecus)
6. [Stage 5: Automated HIL Road Testing Suite (100 Scenarios)](#stage-5-automated-hil-road-testing-suite-100-scenarios)
7. [Stage 6: GitHub Actions CI Pipeline & PR Status Dashboard](#stage-6-github-actions-ci-pipeline--pr-status-dashboard)
8. [Stage 7: Developer & Operator Quick Reference Cheat Sheet](#stage-7-developer--operator-quick-reference-cheat-sheet)

---

## 1. System Overview & Philosophy

### The Engineering Challenge
Developing solar vehicle firmware is notoriously difficult because engineers cannot carry a physical car into their dorm rooms or lab desks. In traditional workflows:
- Firmware is written on personal laptops without physical verification.
- Code breaks when flashed to real microcontrollers because silicon timing and register behavior differ from laptop CPUs.
- Missing vehicle subsystems (such as the Battery Management System or Motor Controller) prevent standalone testing of individual nodes like the pedal or lights board.

### The Solution: The CalSol Testbench
The **CalSol CAN Testbench** bridges this gap. Hosted on a dedicated Raspberry Pi 5 (`stolerpi`), it creates an automotive proving ground combining:
1. **Real Hardware:** Physical ESP32-S3 microcontrollers connected to real differential CAN transceivers.
2. **Remote Access:** Seamless firmware flashing and terminal monitoring over the secure Tailscale mesh network.
3. **Dedicated Bus Debugger:** Real-time hardware snooping and injection running [ESP32_CAN_BUS_Debugger](https://github.com/CalSol/ESP32_CAN_BUS_Debugger).
4. **Software Vehicle Simulation:** Realistic virtual vehicle models (Virtual BMS, Virtual Motor, Virtual Steering) that fill in for missing car hardware.
5. **Continuous Verification:** 100 automated driving cycles, fault injections, and electrical stress tests executed on every GitHub Pull Request.

---

## Stage 1: Physical Hardware & Bench Architecture

The testbench is structured into three distinct hardware tiers: the **Master Controller**, the **Physical CAN Backbone**, and the **Microcontroller Nodes**.

```mermaid
graph TD
    subgraph MasterController ["Master Controller: Raspberry Pi 5 (stolerpi)"]
        Daemon["can_bridge_daemon.py<br/>(COBS & Sockets)"]
        HIL["hil_road_tester.py<br/>(100 Road Scenarios)"]
        Runner["GitHub Actions Runner"]
    end

    subgraph CANBus ["Physical CAN 2.0B Bus (500 kbps)"]
        WireH["CAN_H (Differential High)"]
        WireL["CAN_L (Differential Low)"]
        Term1["120Ω Terminator"] --- WireH
        Term1 --- WireL
        Term2["120Ω Terminator"] --- WireH
        Term2 --- WireL
        Power["12V Bench DC Power Supply"] -.-> WireH
    end

    subgraph Node1 ["Node 1: Device Under Test (DUT)"]
        DUT_ESP["ESP32-S3 Silicon (/dev/esp32_ahmed)<br/>Running: pedals_fw / lights_fw"]
        DUT_XCVR["TI TCAN332 Transceiver<br/>TX: GPIO 17 | RX: GPIO 18"]
    end

    subgraph Node2 ["Node 2: Dedicated CAN Debugger"]
        DBG_ESP["ESP32-S3 Silicon (/dev/esp32_johnathan)<br/>Running: ESP32_CAN_BUS_Debugger"]
        DBG_XCVR["TI TCAN332 Transceiver<br/>TX: GPIO 17 | RX: GPIO 18"]
    end

    %% Connections
    MasterController <===>|USB CDC Serial| DUT_ESP
    MasterController <===>|High-Speed USB CDC| DBG_ESP

    DUT_ESP <--->|TTL UART| DUT_XCVR
    DBG_ESP <--->|TTL UART| DBG_XCVR

    DUT_XCVR <===>|Differential Signal| WireH
    DUT_XCVR <===>|Differential Signal| WireL
    DBG_XCVR <===>|Differential Signal| WireH
    DBG_XCVR <===>|Differential Signal| WireL
```

### Hardware Inventory & Device Mapping
- **Raspberry Pi 5 (`stolerpi` @ `100.120.92.102`):** Quad-core ARM Cortex-A76 host running Linux. Manages all compilation, flashing, bridge daemon, and network sockets.
- **Node 1 (DUT):** Permanent symlink `/dev/esp32_ahmed` (MAC `E0:72:A1:FD:24:38`). Test target flashed on-demand with firmware under review.
- **Node 2 (CAN Debugger):** Permanent symlink `/dev/esp32_johnathan` (MAC `E0:72:A1:FC:DC:94`). Dedicated sniffer/injector running `ESP32_CAN_BUS_Debugger`.
- **Transceivers (TI TCAN332):** Convert 3.3V logic to high-speed differential CAN voltages ($CAN\_H \approx 3.5V$, $CAN\_L \approx 1.5V$). Silicon pinout is **TX = GPIO 17**, **RX = GPIO 18**.
- **Bus Termination:** Two 120Ω resistors at each bus end to prevent signal reflection.

---

## Stage 2: Remote Flashing & Interactive Serial Monitoring

Firmware engineers do not need to sit next to the bench or touch cables. Flashing and monitoring are fully automated via the host scripts.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Firmware Engineer
    participant Host as Raspberry Pi 5 (stolerpi)
    participant Lock as Lockfile (/tmp/calsol_locks/)
    participant ESP as ESP32-S3 Hardware Silicon

    Dev->>Host: ssh stolerpi-jkim "bash github-action/cal-test.sh pedals_fw/test /dev/esp32_ahmed 12"
    Host->>Lock: flock -w 15 /tmp/calsol_locks/esp32_ahmed.lock
    Note over Lock: Prevents simultaneous writes by other devs/CI
    Host->>ESP: idf.py build && esptool flash (921,600 baud)
    Host->>ESP: Trigger RTS/DTR Hard Reset
    ESP-->>Host: Stream Unity test output over USB-Serial-JTAG
    Host->>Host: unity_parser.py parses [PASS] / [FAIL]
    Host->>Lock: Release lock
    Host-->>Dev: Return test results JSON
```

### Concurrency Protection (Mutex Locks)
To prevent two engineers or a GitHub Actions runner from flashing the same microcontroller at the same moment, the testbench enforces Linux kernel advisory locks (`flock`):
- Locks live in `/tmp/calsol_locks/<device>.lock`.
- If a port is in use, incoming requests wait up to 15 seconds before safely failing with an informative diagnostic message rather than corrupting flash memory.

### How to Flash & Test a Board
From your workstation terminal:
```bash
# 1. Connect and run automated Unity unit tests on Node 1 (DUT)
ssh stolerpi-jkim "bash ~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/cal-test.sh pedals_fw/test /dev/esp32_ahmed 15"

# 2. Flash standalone firmware binary without running Unity tests
ssh stolerpi-jkim "bash ~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/cal-flash.sh pedals_fw/test /dev/esp32_ahmed"
```

---

## Stage 3: Remote CAN Packet Snooping & Injection

The bench operates a high-speed software bridge daemon ([`can_bridge_daemon.py`](file:///C:/JuneKim0712/CAN_TestBench/github-action/lib/can_bridge_daemon.py)) that interfaces with the dedicated CAN Debugger on Node 2.

```mermaid
flowchart LR
    subgraph Silicon ["CAN Bus Wire"]
        Wire["Physical Differential Bus (500 kbps)"]
    end

    subgraph Node2 ["ESP32 CAN Debugger"]
        FW["ESP32_CAN_BUS_Debugger<br/>COBS Wire Protocol"]
    end

    subgraph DaemonTier ["Daemon Layer (stolerpi)"]
        Daemon["can_bridge_daemon.py"]
        Trace[("/tmp/can_trace.jsonl")]
        Sock[("/tmp/calsol_can.sock<br/>or TCP: 5555")]
    end

    subgraph Clients ["Remote Clients"]
        Snoop["calsol_snoop.py<br/>(Live Waterfall)"]
        Inject["calsol_inject.py<br/>(Packet Injector)"]
        VirtualCar["car_runner.py<br/>(Vehicle Simulation)"]
    end

    Wire <===>|Differential| FW
    FW <===>|USB CDC Stream (COBS)| Daemon
    Daemon --> Trace
    Daemon <===> Sock
    Sock <===> Snoop
    Sock <===> Inject
    Sock <===> VirtualCar
```

### The COBS Wire Protocol
Because CAN frames can contain arbitrary binary zeros (`0x00`), standard null-terminated serial streams would break. The debugger uses **Consistent Overhead Byte Stuffing (COBS)**:
- Encodes arbitrary payloads so that `0x00` never appears within a frame body.
- Appends `0x00` strictly as a frame boundary delimiter.
- Computes an 8-bit checksum: `sum(frame) % 256 == 0` for integrity.

### How to Snoop (Listen to) Live Bus Traffic
Run [`calsol_snoop.py`](file:///C:/JuneKim0712/CAN_TestBench/github-action/lib/calsol_snoop.py) to watch the live bus in real-time:
```bash
# Snoop on the Raspberry Pi
python3 github-action/lib/calsol_snoop.py

# Snoop remotely from your laptop over Tailscale
python3 github-action/lib/calsol_snoop.py --tcp 100.120.92.102:5555

# Filter for a specific CAN ID (e.g. 0x501 Drive Command)
python3 github-action/lib/calsol_snoop.py --id 0x501
```
**Example Live Terminal Output:**
```text
Timestamp      Dir  CAN ID  DLC  Payload Data
-------------------------------------------------------
[03:12:45.102]  RX   0x301    8    02 01 00 58 00 00 00 00
[03:12:45.150]  RX   0x502    8    05 DC 01 C2 00 24 01 5E
[03:12:45.201]  TX   0x200    8    01 00 02 00 00 00 00 00
```

### How to Inject (Transmit) Packets Remotely
Run [`calsol_inject.py`](file:///C:/JuneKim0712/CAN_TestBench/github-action/lib/calsol_inject.py) to transmit custom CAN frames:
```bash
# One-shot injection of Drive Command 0x501
python3 github-action/lib/calsol_inject.py --id 0x501 --data 000000003F000000

# Continuous injection at 20 Hz (e.g. simulating accelerator pedal)
python3 github-action/lib/calsol_inject.py --id 0x11 --data 80 --rate 20
```

---

## Stage 4: Software Board Emulation (Virtual ECUs)

When developing a single subsystem (like the pedals board), the other physical car ECUs (BMS, Motor Controller, Steering) are usually missing. The testbench provides lightweight, deterministic software-defined mock ECUs in [`sim/virtual_ecus/`](file:///C:/JuneKim0712/CAN_TestBench/sim/virtual_ecus/).

### The Emulated Models
1. **Virtual BMS ([`virtual_bms.py`](file:///C:/JuneKim0712/CAN_TestBench/sim/virtual_ecus/virtual_bms.py)):**
   - Simulates a 96-cell series lithium-ion pack (nominal 379.2V, 28.5°C, 88% SoC).
   - Broadcasts Heartbeat `0x301` @ 10 Hz, Cell Voltages `0x302` @ 2 Hz, Temperatures `0x303` @ 1 Hz.
   - Responds to fault conditions by tripping contactors from `CLOSED` to `OPEN`.
2. **Virtual Motor Controller ([`virtual_motor.py`](file:///C:/JuneKim0712/CAN_TestBench/sim/virtual_ecus/virtual_motor.py)):**
   - Simulates a Tritium WaveSculptor 22 motor controller and Gen11 vehicle physics ($320\text{ kg}$, $C_d A = 0.12$, $C_{rr} = 0.0028$, $80\text{ Nm}$ peak torque).
   - Listens for Drive Command `0x501` or Pedal Position `0x11`.
   - Broadcasts Motor Status `0x502` @ 20 Hz (RPM, velocity, phase current) and Bus Measurements `0x503` @ 10 Hz.
3. **Virtual Steering ([`virtual_steering.py`](file:///C:/JuneKim0712/CAN_TestBench/sim/virtual_ecus/virtual_steering.py)):**
   - Simulates driver mode switch (`NEUTRAL`, `DRIVE`, `REVERSE`), cruise control, and hazard lights.
   - Broadcasts Controls `0x200` @ 10 Hz.

### Running the Virtual Vehicle
To bring up the entire simulated vehicle in the background:
```bash
# Start all virtual ECUs on the Pi
python3 sim/virtual_ecus/car_runner.py

# Run for a fixed duration (e.g. 30 seconds for test automation)
python3 sim/virtual_ecus/car_runner.py --duration 30
```

---

## Stage 5: Automated HIL Road Testing Suite (100 Scenarios)

The testbench transforms isolated unit tests into a full automotive proving ground via [`hil_road_tester.py`](file:///C:/JuneKim0712/CAN_TestBench/github-action/lib/hil_road_tester.py). It executes **100 standardized road scenarios** across 3 categories:

```mermaid
pie title 100 Automated Road Scenarios Distribution
    "Category 1: Drive Cycles (Highway Speeds & Grades)" : 30
    "Category 2: Safety Interlocks & Fault Injections" : 40
    "Category 3: Electrical & CAN Bus Stress" : 30
```

### Scenario Categories
1. **Category 1: Standard Drive Cycles (30 Scenarios):**
   - Tests speeds from $40\text{ km/h}$ to $90\text{ km/h}$ across road grades from $-4\%$ (downhill) to $+4\%$ (hill climb).
   - Verifies that vehicle physics, RPM calculations, and motor commands maintain stable bus timing.
2. **Category 2: Safety Interlocks & Fault Injections (40 Scenarios):**
   - Injects real vehicle emergency events: Overvoltage, Undervoltage, Thermal Runaway ($>60^\circ\text{C}$), Accelerator/Brake Implausibility (pressing brake and gas simultaneously), Loss of Motor Heartbeat, and Precharge Failures.
   - Evaluates that failsafes trigger, contactors open, and motor commands zero out.
3. **Category 3: Electrical & CAN Bus Stress (30 Scenarios):**
   - Injects arbitration storms, corrupted CRC bursts, extended frame glitches, and bit-stuffing stress at bus utilizations ranging from $20\%$ to $95\%$.
   - Asserts that high-priority safety frames (e.g., BMS contactor cutoff) successfully arbitrate over non-critical traffic.

### How to Run the Road Test Suite
```bash
# Run 100 scenarios against the virtual environment (standalone / cloud)
python3 github-action/lib/hil_road_tester.py --virtual --scenarios 100 --report-json hil_report.json

# Run against physical bench silicon
python3 github-action/lib/hil_road_tester.py --socket /tmp/calsol_can.sock --report-json hil_report.json
```

**Output:** Generates a structured certification report in `hil_report.json` containing total scenarios, pass rate, simulated road kilometers, and frames verified.

---

## Stage 6: GitHub Actions CI Pipeline & PR Status Dashboard

On every Pull Request or push to `main`, GitHub Actions automatically orchestrates the entire verification process via [`.github/workflows/unit-test.yml`](file:///C:/JuneKim0712/CAN_TestBench/.github/workflows/unit-test.yml).

```mermaid
flowchart TD
    A["Push / PR Event"] --> B["Cloud Quality Gate<br/>(cppcheck Static Analysis)"]
    B -->|Fast-Fail if defects exist| C["Auto-Discovery Job<br/>(Detects Changed Subsystems)"]
    B --> D["HIL Road Testing Suite<br/>(100 Scenarios in Cloud)"]
    C -->|Matrix Generated| E["Physical Bench Testbench<br/>(Flashes DUT on stolerpi)"]
    D --> F["Upload hil_report.json"]
    E --> G["Upload test_results.json"]
    F --> H["Consolidated PR Status Dashboard<br/>(pr_reporter.py)"]
    G --> H
    H --> I["Post Sticky PR Comment & Step Summary"]
```

### The 4 Pipeline Gates:
1. **Cloud Lint & Static Analysis Gate (`static-analysis`):** Runs on Ubuntu Cloud in 13 seconds. Fast-fails if syntax errors, null pointers, or memory leaks are detected before touching physical hardware.
2. **Subsystem Auto-Discovery (`discover`):** Runs on `stolerpi`. Analyzes git diff against `main`. If only `pedals_fw` was modified, it dispatches only `pedals_fw` tests, skipping unaffected boards.
3. **Hardware Execution Matrix (`testbench`):** Compiles firmware using ESP-IDF v6.1 and Ninja, acquires the device mutex lock, flashes the microcontroller at 921,600 baud, and monitors Unity assertions.
4. **HIL Road Testing Suite (`hil-road-tests`):** Executes all 100 simulated road scenarios, verifying automotive safety interlocks.
5. **Consolidated Dashboard Bot (`report`):** Downloads test reports and road test certificates, compiling a clean Markdown summary into GitHub Actions `$GITHUB_STEP_SUMMARY` and posting an interactive sticky comment on the PR.

---

## Stage 7: Developer & Operator Quick Reference Cheat Sheet

### Common Operator Commands

| Task | Command |
| :--- | :--- |
| **Snoop Bus Traffic** | `python3 github-action/lib/calsol_snoop.py` |
| **Snoop Remotely (from laptop)** | `python3 github-action/lib/calsol_snoop.py --tcp 100.120.92.102:5555` |
| **Inject Single Packet** | `python3 github-action/lib/calsol_inject.py --id 0x501 --data DEADBEEF` |
| **Inject Periodic Packet (20 Hz)** | `python3 github-action/lib/calsol_inject.py --id 0x11 --data 80 --rate 20` |
| **Start Virtual Vehicle** | `python3 sim/virtual_ecus/car_runner.py` |
| **Run 100 HIL Road Tests** | `python3 github-action/lib/hil_road_tester.py --virtual --scenarios 100` |
| **Run Unit Tests on DUT** | `ssh stolerpi-jkim "bash ~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/cal-test.sh pedals_fw/test /dev/esp32_ahmed 15"` |
| **Flash DUT Standalone** | `ssh stolerpi-jkim "bash ~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/cal-flash.sh pedals_fw/test /dev/esp32_ahmed"` |
| **Restore Debugger to Node 2** | `ssh stolerpi-jkim "python3 -m esptool --chip esp32s3 -p /dev/esp32_johnathan -b 921600 write-flash 0x0 /home/jkim/ESP32_CAN_BUS_Debugger/build_dev/bootloader/bootloader.bin 0x8000 /home/jkim/ESP32_CAN_BUS_Debugger/build_dev/partition_table/partition-table.bin 0x10000 /home/jkim/ESP32_CAN_BUS_Debugger/build_dev/CAN_driver_API.bin"` |

---

### Troubleshooting Checklist
- **Serial port permission denied:** Ensure user is in `dialout` group (`sudo usermod -aG dialout <user>`).
- **Device locked error:** Check `/tmp/calsol_locks/` on `stolerpi`. If an orphaned process crashed, remove the stale `.lock` file.
- **Bus off / Transmit error count rising:** Verify that the 12V bench DC power supply is active and connected to transceiver $V_{CC}$ / differential bias pins.
- **No CAN frames appearing in snooper:** Check that `can_bridge_daemon.py` is running (`pgrep -f can_bridge_daemon.py`). If not, launch it with `python3 github-action/lib/can_bridge_daemon.py &`.
