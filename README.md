# CalSol Gen 11 Hardware-in-the-Loop (HIL) Testbench & CI Platform

Continuous hardware integration, automated on-target silicon testing, and CAN bus telemetry validation for the UC Berkeley Solar Vehicle Team (**CalSol**).

This platform validates embedded vehicle firmware on physical microcontrollers and differential bus hardware before deployment to the Gen 11 solar car, serving both as the automated Hardware-in-the-Loop (HIL) test harness and as the reusable CI workflow engine for [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW).

> **Documentation Quick Links:**
> - [📘 Code & Architecture Reference Manual](docs/CODE_DOCUMENTATION.md): Complete technical reference for all C drivers, Python daemons, FreeRTOS tasks, and CI scripts.
> - [🛠️ Stage-by-Stage Operational Manual](docs/CAN_TESTBENCH_STAGE_GUIDE.md): Beginner-friendly hardware and bench walkthrough.

---

## 1. System Overview & Capabilities

The CalSol Hardware Testbench bridges cloud CI workflows with physical lab testbed hardware:

- **Automated On-Target Unit Testing:** Compiles firmware with ESP-IDF and executes Unity unit tests directly on physical ESP32-S3 silicon at 921,600 baud.
- **Physical CAN Bus Telemetry & Capture:** Passive, non-intrusive monitoring of the physical 500 kbps differential CAN bus via a dedicated hardware CAN Debugger, capturing and decoding packets in real time.
- **Subsystem Auto-Discovery:** Monorepo change-detection scans for `testbench.json` definitions and triggers tests exclusively for modified ECU subsystems.
- **Hardware Concurrency Protection:** OS-level mutex locking (`flock`) prevents serial collisions and race conditions across concurrent jobs and developers.
- **Pre-Hardware Quality Gate:** Cloud-based static analysis (`cppcheck`) identifies memory safety flaws, null-pointer dereferences, and bounds violations before flashing silicon.
- **Crash Backtrace Decoding:** Automatically decodes ESP-IDF Guru Meditation panic dumps and registers into source file line numbers using target ELF symbols.

---

## 2. Hardware Testbed Topology

The testbench operates on a dedicated bench testbed connected via the team network:

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

| Hardware Node | Persistent Dev Symlink | Role | Details |
| :--- | :--- | :--- | :--- |
| **Node 1** | `/dev/esp32_ahmed` | **CAN Bus Debugger** | Permanently reserved hardware listener. Captures raw frames, packages COBS streams over native USB, and bridges to `/tmp/calsol_can.sock`. |
| **Node 2** | `/dev/esp32_johnathan` | **Device Under Test (DUT)** | Dynamic test node. Flashed with subsystem test firmware (`pedals_fw`, `lights_fw`, etc.) and monitored for Unity test assertions. |
| **Bus Backbone** | Physical Differential Pair | **CAN 2.0B** | High-speed differential bus operating at 500 kbps with dual $120\,\Omega$ split termination resistors. |

---

## 3. Repository Layout

```text
CAN_TestBench/
├── .github/
│   └── workflows/
│       ├── unit-test.yml           # Monorepo CI workflow (push, PR, dispatch)
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
    ├── cal-snoop.sh                # Terminal-based live CAN bus monitor
    ├── static-check.sh             # Cloud static analysis & quality gate runner
    └── lib/
        ├── auto_discover.py        # Subsystem discovery & git change resolver
        ├── unity_parser.py         # Serial parser, test evaluator, and step summary writer
        ├── can_bridge_daemon.py    # Host CAN ingestion daemon & socket server
        ├── crash_decoder.py        # ESP32 panic register & stack backtrace decoder
        └── pr_reporter.py          # Consolidated test dashboard & PR comment reporter
```

---

## 4. Onboarding a New Subsystem (`testbench.json`)

To register a new ECU subsystem for automated hardware testing, add a `testbench.json` file inside the subsystem directory:

```json
{
  "name": "bms_fw",
  "target": "bms_fw/test",
  "port": "/dev/esp32_johnathan",
  "baud": 921600,
  "timeout": 15,
  "description": "Battery Management System Voltage & Temperature Assertions"
}
```

### Parameter Reference

| Key | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `name` | `string` | *(Folder name)* | Identifier used in CI matrix logs, summaries, and test reports. |
| `target` | `string` | `<folder>/test` | Path containing the Unity test project (`CMakeLists.txt` and `main/`). |
| `port` | `string` | `""` | Serial device symlink on the runner. If omitted, the runner auto-detects an available board. |
| `baud` | `integer` | `921600` | USB flashing speed. `921600` completes flashes in under 4 seconds. |
| `timeout` | `integer` | `15` | Maximum seconds to wait for Unity test completion before timing out. |
| `description` | `string` | `""` | Optional human-readable description for documentation. |

---

## 5. Local Bench Operations

Firmware engineers working on the lab Raspberry Pi (`stolerpi`) can run tests, flash silicon, and inspect bus traffic directly from the command line:

### Connect to the Bench Host
```bash
ssh <user>@stolerpi
cd /path/to/CAN_TestBench
```

### Run an Automated Test Suite
```bash
# Execute unit tests and live CAN capture for pedals_fw
./github-action/cal-test.sh pedals_fw/test

# Execute unit tests for lights_fw with custom timeout (20s)
./github-action/cal-test.sh lights_fw/test /dev/esp32_johnathan 20
```

### Safe Flashing via Mutex Lock
```bash
# Safely flash without triggering test runners
./github-action/cal-flash.sh pedals_fw/test /dev/esp32_johnathan
```

### Passive Live CAN Snooping
```bash
# Monitor decoded CAN traffic in real time
./github-action/cal-snoop.sh
```

---

## 6. Continuous Integration Workflow

On every Pull Request and push to `main`, GitHub Actions executes the following pipeline:

1. **Pre-Hardware Quality Gate (`static-analysis`):** Cppcheck scans all C/C++ sources for critical defects. If errors are found, CI halts immediately to prevent flashing unstable code.
2. **Matrix Discovery (`discover`):** Inspects Git change deltas against target branches. Only subsystems with modified files are added to the test matrix. Pure documentation changes skip hardware testing automatically.
3. **Hardware Execution (`testbench`):** Dispatches matrix jobs in parallel to physical silicon on `stolerpi`. Each job:
   - Compiles firmware using `ccache` acceleration.
   - Acquires the hardware mutex lock.
   - Flashes the target microcontroller.
   - Streams serial output and decodes live CAN bus traffic via `/dev/esp32_ahmed`.
   - Captures any Guru Meditation crash dumps and resolves stack addresses to line numbers.
4. **Consolidated Dashboard (`report`):** Aggregates static analysis results, unit test tables, live CAN telemetry, and failure diagnostics into the GitHub Actions Step Summary and posts a sticky comment on the Pull Request.

---

## 7. Inspecting CAN Traffic in GitHub Actions

Captured CAN frames are surfaced in four accessible locations during CI runs:

1. **Workflow Run Summary:** Located under **"CalSol Hardware-in-the-Loop Testbench Report"** $\rightarrow$ **"CAN Bus Telemetry & Traffic"**.
2. **Job Step Summary:** Expandable within the specific test job summary under `<details>` **"CAN Bus Telemetry"**.
3. **Live Job Logs:** Real-time stream inside step **"On-Target Silicon Execution & Live CAN Stream"** (e.g. `[CAN LIVE] 0x011 (THROTTLE_COMMAND)...`).
4. **Run Artifacts:** Complete raw traces are downloadable as `can_trace.jsonl` under the run's **Artifacts** section for offline analysis.
5. **Interactive Web Portal (GitHub Pages):** Deployed to `https://<org>.github.io/<repo>/`, displaying historical testbench runs, real-time CAN bus oscilloscope waveforms, filterable packet streams, and Unity assertion breakdowns.

---

## 8. Trackside & Deployment Flashing

Precompiled binaries (`.bin`, `.elf`, `bootloader.bin`) are automatically archived in GitHub Run Artifacts. To flash a tested binary directly to an ECU board at the track or lab bench:

```bash
# Trackside single-command flash via esptool
python3 -m esptool --chip esp32s3 -p /dev/esp32_johnathan -b 921600 write_flash 0x10000 <subsystem>.bin
```

---

## 9. Reusable Workflow for Other CalSol Repositories

To enable automated HIL hardware testing in [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW) or any other subsystem repository, add `.github/workflows/testbench.yml`:

```yaml
name: CalSol Hardware Testbench

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  hardware-ci:
    uses: CalSol/CAN_TestBench/.github/workflows/testbench.yml@main
```

---

## 10. Development & Code Standards

- **Code Formatting:** All C and C++ source code must adhere to the project's [`.clang-format`](.clang-format) configuration. Run `clang-format -i main/*.c main/*.h` before committing.
- **Repository Separation:**
  - Core testbench infrastructure, runner scripts, and reusable workflows are maintained in [`CalSol/CAN_TestBench`](https://github.com/CalSol/CAN_TestBench).
  - Test suites and CI testing ground iterations are validated on developer forks before merging.
- **Transceiver Safety:** Always verify external 12V bench DC power and differential bus termination ($120\,\Omega$) before conducting high-throughput CAN transmission tests.
