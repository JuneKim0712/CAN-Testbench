# CalSol Hardware Testbench & GitHub Actions CI Engine

This directory contains the continuous integration (CI) hardware runner engine for the UC Berkeley Solar Vehicle Team (**CalSol**). It bridges cloud GitHub Actions workflows to physical ESP32-S3 microcontrollers on the bench Raspberry Pi (`stolerpi`).

---

## 1. Executive Architecture Overview

Unlike traditional software CI pipelines that run inside abstract Docker containers or emulators, the CalSol CAN Testbench runs **Hardware-in-the-Loop (HIL)** unit tests on real automotive silicon. Code is compiled against Espressif ESP-IDF, flashed over high-speed UART, and executed on physical microcontrollers connected to real hardware peripherals and CAN bus transceivers.

```
 GitHub Event (push / PR / manual)
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions Cloud Orchestrator                           │
│  - Job 1: detect-changes (Inspects testbench.json per folder)│
│  - Job 2: testbench (Matrix execution per changed subsystem)│
└──────────────────────────────┬──────────────────────────────┘
                               │ Dispatched via runner daemon
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Raspberry Pi 5 (`stolerpi` - ARM64 Linux)                   │
│  - Service: `github-runner.service` (systemd --user)        │
│                                                             │
│  1. `cal-test.sh`                                           │
│     ├── Per-Folder Config: Read `<subsystem>/testbench.json`│
│     ├── Port mapping: /dev/esp32_johnathan vs /dev/esp32_ahmed
│     ├── Hardware Mutex: Acquire flock (/tmp/calsol_locks/)  │
│     ├── Build: `idf.py build` -> .logs/build.log            │
│     ├── Flash: `idf.py flash` (921.6k baud) -> flash.log    │
│     └── Monitor & Parse: Launch `unity_parser.py`           │
│                                                             │
│  2. `unity_parser.py`                                       │
│     ├── Read serial output line-by-line (115,200 baud)      │
│     ├── Extract Unity assertion tokens (:PASS / :FAIL)      │
│     ├── Post Markdown summary table to $GITHUB_STEP_SUMMARY │
│     └── Exit with code 0 (Pass) or code 1 (Fail/Timeout)    │
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               │ UART (921.6k)                 │ UART (921.6k)
               ▼                               ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│ ESP32-S3 Board A             ││ ESP32-S3 Board B             │
│ /dev/esp32_johnathan (ttyACM1)││ /dev/esp32_ahmed (ttyACM0)   │
│ Lights & Hazards ECU         ││ Pedals & Throttle ECU        │
└──────────────────────────────┘└──────────────────────────────┘
```

---

## 2. Directory Structure

```text
github-action/
├── cal-test.sh         # Master test orchestrator (Build, Mutex, Flash, Parse)
├── cal-flash.sh        # Standalone mutex flashing utility for pre-built binaries
├── README.md           # Comprehensive architecture and operation guide
└── lib/
    ├── __init__.py     # Python package marker
    └── unity_parser.py # UART serial stream parser & GitHub Step Summary generator
```

---

## 3. GitHub Actions CI Triggers & Filtering

The workflow file is located at [`.github/workflows/unit-test.yml`](../.github/workflows/unit-test.yml).

### Supported Triggers

| Trigger Event | Purpose | Behavior |
| :--- | :--- | :--- |
| `push: branches: [main]` | Continuous testing on merge | Runs path filtering across commits in push |
| `pull_request: branches: [main]` | Pre-merge verification | Runs path filtering between PR branch and `main` |
| `workflow_dispatch` | Manual on-demand testing | Interactive drop-down to select `all` or specific subsystem |
| `workflow_call` | Reusable workflow execution | Allows caller repos (e.g. `CalSol/Gen11-FW`) to pass target paths |

### Dynamic Path Filtering (`dorny/paths-filter@v3`)

To prevent wearing out ESP32 flash memory and avoid wasting bench test time, the workflow uses an intelligent path detector:

```yaml
filters: |
  lights_fw/test:
    - 'lights_fw/**'
    - 'components/**'
    - 'github-action/**'
    - '.github/**'
  pedals_fw/test:
    - 'pedals_fw/**'
    - 'components/**'
    - 'github-action/**'
    - '.github/**'
```

#### Filtering Rules:
1. **Isolated Subsystems:** Modifying only files inside `lights_fw/` triggers **only** `lights_fw/test`. The `pedals_fw/test` suite is completely omitted from the matrix.
2. **Shared Dependencies:** Modifying shared drivers (`components/can_driver/**`), runner scripts (`github-action/**`), or the workflow itself (`.github/**`) causes **all** test suites to run, preventing cross-subsystem regressions.
3. **Documentation & Unrelated Commits:** Modifying only documentation (e.g., `README.md`, `.gitignore`, `docs/`) evaluates to an empty change list (`targets: []`), setting `has_changes=false`. The entire hardware test job is safely skipped with a clean green checkmark.

---

## 4. Per-Subsystem Hardware Configuration (`testbench.json`)

In a monorepo containing multiple vehicle subsystems, each subsystem can be mapped to its own designated microcontroller on the bench. Each subsystem directory can contain a `testbench.json` configuration file:

### Example: `lights_fw/testbench.json`
```json
{
  "name": "lights_fw",
  "target": "lights_fw/test",
  "port": "/dev/esp32_johnathan",
  "baud": 921600,
  "timeout": 12,
  "description": "Brakelights & Hazards ECU testbench configuration"
}
```

### Example: `pedals_fw/testbench.json`
```json
{
  "name": "pedals_fw",
  "target": "pedals_fw/test",
  "port": "/dev/esp32_ahmed",
  "baud": 921600,
  "timeout": 12,
  "description": "Accelerator & Brake Plausibility ECU testbench configuration"
}
```

### Supported Configuration Fields

| Field | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `name` | string | Subsystem folder name | Name displayed in GitHub Actions job title and reports |
| `target` | string | `<folder>/test` | Relative path to the ESP-IDF test project directory |
| `port` | string | `""` (auto-detect) | Udev device path on Raspberry Pi (e.g. `/dev/esp32_johnathan`) |
| `baud` | integer | `921600` | Baud rate for flashing firmware onto silicon |
| `timeout` | integer | `12` | Max seconds to monitor serial port for Unity results |
| `description`| string | `""` | Human-readable documentation string |

### Precedence Hierarchy
1. **CLI Flag Override:** Passing a port directly (`cal-test.sh <target> [port] [timeout]`) overrides all files.
2. **Folder `testbench.json`:** If no CLI argument is given, settings are loaded from `<folder>/testbench.json`.
3. **Automatic Discovery Fallback:** If the configured port is disconnected or empty, the runner automatically scans active udev devices (`/dev/steering`, `/dev/esp32_*`, `/dev/ttyACM*`).

---

## 5. Detailed Script Breakdown

### A. `cal-test.sh` — Hardware Test Orchestrator

This script is the primary entrypoint called by both GitHub Actions and engineers working locally on the Pi.

#### Sequence of Operations:

```text
cal-test.sh <target_directory_or_bin> [port] [timeout]
  │
  ├── 1. Resolve Target Path
  │      Checks if target is a relative directory, absolute path, or pre-built binary.
  │
  ├── 2. Load Folder `testbench.json`
  │      Inspects $TARGET/testbench.json or $(dirname $TARGET)/testbench.json.
  │      Extracts port, baud, timeout, and name.
  │
  ├── 3. Source ESP-IDF Environment
  │      Verifies if `idf.py` is in $PATH. If not, automatically locates and sources
  │      `/opt/esp-idf/export.sh` or `~/esp/esp-idf/export.sh`.
  │
  ├── 4. Port Validation & Auto-Discovery
  │      Validates configured port. If not connected, scans known udev symlinks.
  │
  ├── 5. Hardware Mutex Acquisition (`flock`)
  │      Opens file descriptor 200 on `/tmp/calsol_locks/<board>.lock`.
  │      Waits up to 15 seconds (`flock -w 15 200`).
  │      Prevents concurrent flashing by GitHub Actions, local terminals, or the Slack Bot!
  │
  ├── 6. Build Firmware (`idf.py build`)
  │      Navigates to the test project directory.
  │      Configures ESP32-S3 target if no sdkconfig exists.
  │      Redirects all stdout/stderr to `.logs/build.log`.
  │      If compilation fails, prints the last 30 lines of error log and exits with code 1.
  │
  ├── 7. Flash Silicon (`idf.py flash` / `esptool.py`)
  │      Flashes firmware image at configured baud rate (default 921,600 baud).
  │      Redirects output to `.logs/flash.log`.
  │      If flashing fails, dumps error log and exits with code 1.
  │
  └── 8. Launch Unity Parser (`unity_parser.py`)
         Executes serial monitor to parse test assertions and report results.
```

---

### B. `cal-flash.sh` — Fast Hardware Mutex Flashing Runner

A lightweight flashing utility intended for pre-compiled binaries or quick manual updates without requiring a full CMake build tree.

- **Usage:** `./github-action/cal-flash.sh <board_name> <binary_path> [offset]`
- **Features:**
  - Fast resolution of board udev devices (`/dev/<board>`, `/dev/esp32_<board>`).
  - Strict 15-second mutex acquisition before touching serial hardware.
  - Invokes `esptool.py` with `--before default_reset --after hard_reset write_flash 0x10000 <binary>`.

---

### C. `lib/unity_parser.py` — Serial Monitor & GitHub Summary Generator

This Python utility is responsible for reading the microcontroller's UART output, detecting pass/fail assertions, and posting formatted status back to GitHub.

#### How It Works:
1. **Serial Connection:** Opens the specified serial device (`--port`) at 115,200 baud with a 0.5-second read timeout.
2. **Stream Analysis:** Continuously reads serial lines until `--timeout` expires or test completion is detected:
   - Matches line containing `:PASS` -> Records passed assertion: `results.append(("PASS", test_name, line))`.
   - Matches line containing `:FAIL` -> Records failure: `results.append(("FAIL", test_name, line))`.
   - Matches Unity summary line containing `Tests` and `Failures`:
     - If `0 Failures` is present, marks run as `passed = True` and terminates loop immediately.
3. **GitHub Step Summary Integration:**
   - Detects the `$GITHUB_STEP_SUMMARY` environment variable provided by the GitHub Actions runner.
   - Generates a Markdown table containing test status icons, function names, and raw line output:

| Status | Test Function | Details |
| :---: | :--- | :--- |
| ✅ | `test_voltage_conversion` | `../main/test_main.c:28:test_voltage_conversion:PASS` |
| ✅ | `test_state_toggle` | `../main/test_main.c:37:test_state_toggle:PASS` |
| ✅ | `test_can_message_format` | `../main/test_main.c:47:test_can_message_format:PASS` |

4. **Exit Codes:**
   - Exits with **Code 0** if and only if all tests passed.
   - Exits with **Code 1** if any test failed, or if no summary line was detected before timeout.

---

## 6. How to Add a New Firmware Subsystem & Test

To integrate a new vehicle subsystem (e.g., `steering_fw`):

### 1. Create Subsystem Directory & Test App
Structure the new folder alongside existing firmware:
```text
steering_fw/
├── testbench.json              # Custom ECU port and timeout settings
├── CMakeLists.txt
├── main/
│   ├── CMakeLists.txt
│   └── main.c
└── test/
    ├── CMakeLists.txt
    └── main/
        ├── CMakeLists.txt
        └── test_main.c
```

### 2. Configure `testbench.json`
```json
{
  "name": "steering_fw",
  "target": "steering_fw/test",
  "port": "/dev/steering",
  "baud": 921600,
  "timeout": 15
}
```

### 3. Update Path Filter in [`.github/workflows/unit-test.yml`](../.github/workflows/unit-test.yml)
Add the subsystem under the `filters` block:
```yaml
steering_fw/test:
  - 'steering_fw/**'
  - 'components/**'
  - 'github-action/**'
  - '.github/**'
```

### 4. Add to Manual Trigger Options
Add `'steering_fw/test'` to `workflow_dispatch.inputs.target.options`.

Commit and push your changes. From that moment forward, any commit touching `steering_fw/` will automatically compile, flash to its designated microcontroller, and test on target hardware!

---

## 7. Troubleshooting & FAQs

### Q: Why did the test fail with "Board is currently in use by another process"?
- **Cause:** Another test job, terminal session, or Slack bot command was holding the hardware mutex lock.
- **Resolution:** The runner automatically waits 15 seconds. If a stale lock remains, check running processes on the Pi (`ps aux | grep -E 'cal-test|idf.py'`) or remove the lock in `/tmp/calsol_locks/`.

### Q: What if a configured port in `testbench.json` is unplugged?
- **Behavior:** `cal-test.sh` prints a warning and automatically falls back to discovering available ESP32 serial devices in `/dev/`.

### Q: Where do I view test logs if a test fails?
- **In GitHub UI:** Open the failed Actions run. The step summary directly contains the Unity test assertion table and collapsible build/flash logs.
- **On the Pi:** Inspect `~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/.logs/`.
