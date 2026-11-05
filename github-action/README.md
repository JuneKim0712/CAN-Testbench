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
│  - Job 1: detect-changes (Path filtering & matrix gen)      │
│  - Job 2: testbench (Matrix execution per changed subsystem)│
└──────────────────────────────┬──────────────────────────────┘
                               │ Dispatched via runner daemon
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Raspberry Pi 5 (`stolerpi` - ARM64 Linux)                   │
│  - Service: `github-runner.service` (systemd --user)        │
│  - Local checkout: `~/actions-runner/_work/...`              │
│                                                             │
│  1. `cal-test.sh`                                           │
│     ├── Environment setup: Source ESP-IDF (/opt/esp-idf)    │
│     ├── Port discovery: Auto-detect /dev/esp32_* /dev/ttyACM│
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
                               │ UART Flashing (921.6k baud)
                               │ UART Serial Logging (115.2k baud)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Target Silicon (ESP32-S3 Dual-Core Xtensa LX7)              │
│  - Runs FreeRTOS & Unity Test Framework                     │
│  - Executes subsystem logic, ADC math, and CAN frame checks │
└──────────────────────────────┬──────────────────────────────┘
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

## 4. Detailed Script Breakdown

### A. `cal-test.sh` — Hardware Test Orchestrator

This script is the primary entrypoint called by both GitHub Actions and engineers working locally on the Pi.

#### Sequence of Operations:

```text
cal-test.sh <target_directory_or_bin> [serial_port]
  │
  ├── 1. Resolve Target Path
  │      Checks if target is a relative directory, absolute path, or pre-built binary.
  │
  ├── 2. Source ESP-IDF Environment
  │      Verifies if `idf.py` is in $PATH. If not, automatically locates and sources
  │      `/opt/esp-idf/export.sh` or `~/esp/esp-idf/export.sh`.
  │
  ├── 3. Serial Port Auto-Discovery
  │      If port is not supplied, scans known udev symlinks in order of priority:
  │      - /dev/steering
  │      - /dev/esp32_johnathan
  │      - /dev/bms
  │      - /dev/esp32_ahmed
  │      - /dev/ttyACM0, /dev/ttyACM1
  │
  ├── 4. Hardware Mutex Acquisition (`flock`)
  │      Opens file descriptor 200 on `/tmp/calsol_locks/<board>.lock`.
  │      Waits up to 15 seconds (`flock -w 15 200`).
  │      Prevents concurrent flashing by GitHub Actions, local terminals, or the Slack Bot!
  │
  ├── 5. Build Firmware (`idf.py build`)
  │      Navigates to the test project directory.
  │      Configures ESP32-S3 target if no sdkconfig exists.
  │      Redirects all stdout/stderr to `.logs/build.log`.
  │      If compilation fails, prints the last 30 lines of error log and exits with code 1.
  │
  ├── 6. Flash Silicon (`idf.py flash` / `esptool.py`)
  │      Flashes firmware image at 921,600 baud.
  │      Redirects output to `.logs/flash.log`.
  │      If flashing fails, dumps error log and exits with code 1.
  │
  └── 7. Launch Unity Parser (`unity_parser.py`)
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
2. **Stream Analysis:** Continuously reads serial lines until `--timeout` (default 12s) expires or test completion is detected:
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

## 5. Workflow Step-by-Step Walkthrough

Here is the exact progression of steps executed when a workflow run triggers:

### Job 1: `detect-changes`
1. **Checkout Repository:** Fetches the repository shallowly to inspect changed files.
2. **Filter Changed Paths:** Executes `dorny/paths-filter@v3` against GitHub's Compare API to see which folders were touched.
3. **Determine Target Matrix:** Converts matched folders into a JSON matrix array (`targets`) and outputs a boolean (`has_changes`).
4. **Report Detection Summary:** Appends a quick Markdown notice to GitHub Actions summary stating which subsystems were scheduled.

### Job 2: `testbench`
1. **Conditional Check:** Evaluates `if: needs.detect-changes.outputs.has_changes == 'true'`. If false, the job is cleanly skipped.
2. **Matrix Expansion:** GitHub Actions schedules a parallel/queued job for each target subsystem in `subsystem: ${{ fromJson(needs.detect-changes.outputs.targets) }}`.
3. **Checkout Repository:** Checks out the code on the Raspberry Pi runner.
4. **Make Scripts Executable:** Runs `chmod +x github-action/*.sh github-action/lib/*.py`.
5. **Run Hardware Unit Tests:** Runs `./github-action/cal-test.sh "${{ matrix.subsystem }}"`.
6. **Dump Failure Logs:** Runs only `if: failure()`. If build or flash failed, reads `.logs/build.log` and `.logs/flash.log` and outputs them inside collapsible `<details>` blocks on GitHub for instant debugging without needing SSH access.

---

## 6. How to Add a New Firmware Subsystem & Test

To integrate a new vehicle subsystem (e.g., `steering_fw`):

### 1. Create Subsystem Directory & Test App
Structure the new folder alongside existing firmware:
```text
steering_fw/
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

### 2. Update Path Filter in [`.github/workflows/unit-test.yml`](../.github/workflows/unit-test.yml)
Add the subsystem under the `filters` block:
```yaml
steering_fw/test:
  - 'steering_fw/**'
  - 'components/**'
  - 'github-action/**'
  - '.github/**'
```

### 3. Add to Manual Trigger Options
Add `'steering_fw/test'` to `workflow_dispatch.inputs.target.options`.

Commit and push your changes. From that moment forward, any commit touching `steering_fw/` will automatically compile, flash, and test on target hardware!

---

## 7. Troubleshooting & FAQs

### Q: Why did the test fail with "Board is currently in use by another process"?
- **Cause:** Another test job, terminal session, or Slack bot command was holding the hardware mutex lock.
- **Resolution:** The runner automatically waits 15 seconds. If a stale lock remains, check running processes on the Pi (`ps aux | grep -E 'cal-test|idf.py'`) or remove the lock in `/tmp/calsol_locks/`.

### Q: Why was the hardware test skipped after my commit?
- **Cause:** The path filter determined that no firmware files were modified (e.g. only `README.md` or `.gitignore` changed).
- **Resolution:** This is intentional behavior to save testbed runtime. To force a run without changing firmware, trigger via the **Actions** tab using `workflow_dispatch`.

### Q: Where do I view test logs if a test fails?
- **In GitHub UI:** Open the failed Actions run. The step summary directly contains the Unity test assertion table and collapsible build/flash logs.
- **On the Pi:** Inspect `~/actions-runner/_work/CAN-Testbench/CAN-Testbench/github-action/.logs/`.
