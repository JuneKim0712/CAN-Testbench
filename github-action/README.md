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

## 6. Guide: Implementing Hardware CI in Your Own Repository

Whether you are developing in [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW), a subsystem-specific repository, or your own testing fork, you can integrate this automated hardware testbench into your repo with minimal setup.

There are two primary integration patterns depending on your repository structure:
- **Pattern A (Reusable Workflow):** Best for single-ECU repositories or simple setups. Calls `CalSol/CAN_TestBench`'s centralized runner without needing to copy build scripts.
- **Pattern B (Monorepo Dynamic Matrix):** Best for multi-ECU repositories (like `Gen11-FW`). Evaluates commit diffs, runs only changed folders, and maps each ECU to its designated ESP32 board.

---

### Pattern A: Reusable Workflow Integration (Recommended for Single Subsystems)

If your repository focuses on one ECU or already has a unified test target, you can invoke CalSol's centralized testbench workflow directly via GitHub's `workflow_call`.

#### Step 1: Add `testbench.json` to Your Test Project
Place `testbench.json` inside your test directory (e.g. `test/testbench.json` or project root):

```json
{
  "name": "steering_fw",
  "target": "test",
  "port": "/dev/esp32_johnathan",
  "baud": 921600,
  "timeout": 12,
  "description": "Steering wheel ECU hardware test configuration"
}
```

*Note: If `port` is omitted or left as `""`, the runner automatically detects any available ESP32 connected to the bench.*

#### Step 2: Create the Workflow File in Your Repo
Create `.github/workflows/hardware-test.yml` in your repository:

```yaml
name: Hardware Testbench

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  run-hardware-tests:
    name: Run On-Target ESP32 Test
    uses: CalSol/CAN_TestBench/.github/workflows/unit-test.yml@main
    with:
      target: 'test'                    # Path to the ESP-IDF test project in your repo
      # port: '/dev/esp32_johnathan'    # Optional override (defaults to testbench.json or auto)
```

That's it! When you push or open a PR, GitHub Actions automatically dispatches the job to `stolerpi`, checks out your code, pulls the testbench engine, compiles, flashes, and reports results.

---

### Pattern B: Monorepo Dynamic Matrix Integration (Recommended for Multi-ECU Repos)

If your repository contains multiple vehicle subsystems (e.g. `lights_fw`, `pedals_fw`, `steering_fw`, `bms_fw`), you only want to compile and flash the ECUs that were modified in a commit.

#### Step 1: Structure Subsystems & Configurations
Give each subsystem its own folder with a `testbench.json` specifying its assigned ESP32 board on `stolerpi`:

```text
your-firmware-repo/
├── lights_fw/
│   ├── testbench.json          # "port": "/dev/esp32_johnathan"
│   ├── main/
│   └── test/
│       └── main/test_main.c
├── pedals_fw/
│   ├── testbench.json          # "port": "/dev/esp32_ahmed"
│   ├── main/
│   └── test/
│       └── main/test_main.c
└── steering_fw/
    ├── testbench.json          # "port": "/dev/steering"
    ├── main/
    └── test/
        └── main/test_main.c
```

#### Step 2: Create the Dynamic Matrix Workflow
Create `.github/workflows/hardware-ci.yml` in your repository:

```yaml
name: CalSol Hardware CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:
    inputs:
      target:
        description: 'Target subsystem to test'
        required: true
        default: 'all'
        type: choice
        options:
          - 'all'
          - 'lights_fw/test'
          - 'pedals_fw/test'
          - 'steering_fw/test'

jobs:
  detect-changes:
    name: Detect Changed Subsystems & Configs
    runs-on: [ self-hosted, linux, ARM64 ]
    outputs:
      matrix: ${{ steps.set-targets.outputs.matrix }}
      has_changes: ${{ steps.set-targets.outputs.has_changes }}
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Filter Changed Paths
        if: github.event_name == 'push' || github.event_name == 'pull_request'
        uses: dorny/paths-filter@v3
        id: filter
        with:
          token: ${{ github.token }}
          filters: |
            lights_fw/test:
              - 'lights_fw/**'
              - 'components/**'
            pedals_fw/test:
              - 'pedals_fw/**'
              - 'components/**'
            steering_fw/test:
              - 'steering_fw/**'
              - 'components/**'

      - name: Determine Target Matrix & Settings
        id: set-targets
        env:
          EVENT_NAME: ${{ github.event_name }}
          INPUT_TARGET: ${{ inputs.target }}
          FILTER_CHANGES: ${{ steps.filter.outputs.changes }}
        run: |
          python3 - << 'EOF'
          import json, os, glob

          event_name = os.environ.get("EVENT_NAME", "")
          input_target = os.environ.get("INPUT_TARGET", "")
          filter_changes_raw = os.environ.get("FILTER_CHANGES", "[]")

          try:
              changes = json.loads(filter_changes_raw)
          except:
              changes = []

          if event_name == "workflow_dispatch" and input_target and input_target != "all":
              subsystems = [input_target]
          elif event_name == "workflow_dispatch" and (input_target == "all" or not input_target):
              subsystems = sorted(glob.glob("*/test"))
          else:
              subsystems = changes

          matrix_items = []
          for sub in subsystems:
              folder = sub.split("/")[0]
              cfg_path = f"{folder}/testbench.json"
              if not os.path.exists(cfg_path):
                  cfg_path = f"{sub}/testbench.json"

              cfg = {}
              if os.path.exists(cfg_path):
                  try:
                      with open(cfg_path, "r", encoding="utf-8") as f:
                          cfg = json.load(f)
                  except Exception as e:
                      print(f"Warning: Failed to parse {cfg_path}: {e}")

              target = cfg.get("target", f"{folder}/test" if not sub.endswith("/test") else sub)
              name = cfg.get("name", folder)
              port = cfg.get("port", "")
              timeout = cfg.get("timeout", 12)

              matrix_items.append({
                  "name": name,
                  "folder": folder,
                  "target": target,
                  "port": port,
                  "timeout": timeout
              })

          has_changes = "true" if len(matrix_items) > 0 else "false"
          matrix_json = json.dumps(matrix_items)

          gh_output = os.environ.get("GITHUB_OUTPUT")
          if gh_output:
              with open(gh_output, "a", encoding="utf-8") as f:
                  f.write(f"matrix={matrix_json}
")
                  f.write(f"has_changes={has_changes}
")
          EOF

  testbench:
    name: Test ${{ matrix.cfg.name }} (${{ matrix.cfg.port || 'auto' }})
    needs: detect-changes
    if: needs.detect-changes.outputs.has_changes == 'true'
    runs-on: [ self-hosted, linux, ARM64 ]
    strategy:
      fail-fast: false
      matrix:
        cfg: ${{ fromJson(needs.detect-changes.outputs.matrix) }}
    timeout-minutes: 8

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Checkout CalSol Testbench Engine
        uses: actions/checkout@v4
        with:
          repository: CalSol/CAN_TestBench
          path: .calsol_testbench

      - name: Make Scripts Executable
        run: chmod +x .calsol_testbench/github-action/*.sh .calsol_testbench/github-action/lib/*.py

      - name: Execute On-Target Hardware Test
        run: |
          .calsol_testbench/github-action/cal-test.sh \
            "${{ matrix.cfg.target }}" \
            "${{ matrix.cfg.port }}" \
            "${{ matrix.cfg.timeout }}"

      - name: Dump Failure Logs
        if: failure()
        run: |
          echo "### ⚠️ Build / Flash Debug Logs for ${{ matrix.cfg.name }}" >> $GITHUB_STEP_SUMMARY
          echo "<details><summary>Click to view failure logs</summary>" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo '```text' >> $GITHUB_STEP_SUMMARY
          [ -f ".calsol_testbench/github-action/.logs/build.log" ] && tail -n 40 .calsol_testbench/github-action/.logs/build.log
          [ -f ".calsol_testbench/github-action/.logs/flash.log" ] && tail -n 40 .calsol_testbench/github-action/.logs/flash.log
          echo '```' >> $GITHUB_STEP_SUMMARY
          echo "</details>" >> $GITHUB_STEP_SUMMARY
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
