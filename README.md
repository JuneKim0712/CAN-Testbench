# CalSol Gen11 Hardware Testbench & CI Testing Ground

Continuous hardware integration, automated on-target Unity unit testing, and GitHub Actions workflow testing ground for the UC Berkeley Solar Vehicle Team (**CalSol**).

Designed exclusively to model and validate continuous integration workflows for [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW).

---

## 1. Repository Structure

```text
CAN-Testbench/
├── .github/workflows/          # GitHub Actions CI/CD workflows for Raspberry Pi
│   └── unit-test.yml           # Dynamic change-detection hardware test matrix
│
├── components/                 # Shared vehicle components & libraries (from Gen11-FW)
│   └── can_driver/             # Universal CalSol CAN hardware driver (CAN.h, CAN_driver.c)
│
├── lights_fw/                  # Subsystem 1: Brakelights & Hazards
│   ├── CMakeLists.txt          # Production ESP-IDF CMake
│   ├── main/                   # Production firmware (I2C power, hazards, CAN loop)
│   │   ├── CMakeLists.txt
│   │   └── main.c
│   └── test/                   # On-Target Unity unit tests
│       ├── CMakeLists.txt
│       └── main/
│           ├── CMakeLists.txt
│           └── test_main.c     # Voltage conversion, state machine, and CAN assertions
│
├── pedals_fw/                  # Subsystem 2: Accelerator & Brake Plausibility
│   ├── CMakeLists.txt          # Production ESP-IDF CMake
│   ├── main/                   # Production firmware (Dual ADC pedals, CAN throttle)
│   │   ├── CMakeLists.txt
│   │   └── main.c
│   └── test/                   # On-Target Unity unit tests
│       ├── CMakeLists.txt
│       └── main/
│           ├── CMakeLists.txt
│           └── test_main.c     # Throttle deadzones, plausibility cutoff rules, and CAN
│
├── .clang-format               # Universal CalSol C/C++ code styling rules
└── github-action/              # Hardware Testbench & GitHub Actions CI Engine
    ├── cal-test.sh             # Fast build (ccache), mutex locking, app-flash, & test runner
    ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
    ├── static-check.sh         # Pre-hardware cloud static analysis & lint quality gate
    ├── action.yml              # Standalone composite action for custom workflows
    ├── README.md               # Comprehensive architecture, trigger, and step documentation
    └── lib/
        ├── auto_discover.py    # Subsystem discovery & git change resolver
        └── unity_parser.py     # Serial monitor & GitHub Actions summary table generator
```

---

## 2. Running Hardware Unit Tests Locally

On the Raspberry Pi testbed (`stolerpi`):

```bash
# Test the lights subsystem
./github-action/cal-test.sh lights_fw/test

# Test the pedals subsystem
./github-action/cal-test.sh pedals_fw/test
```

---

## 3. Automated Testing via GitHub Actions

Every push or Pull Request automatically runs the test matrix across all registered subsystems on real ESP32-S3 silicon connected to `stolerpi`. Results are posted directly to `$GITHUB_STEP_SUMMARY`.

---

## 4. Plug-and-Play Integration in Your Own Repository

To integrate automated on-target ESP32-S3 hardware testing into your repository (e.g. [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW) or a personal ECU repo), simply add `.github/workflows/testbench.yml`:

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

### What this does automatically:
- 🔍 **Strict `testbench.json` Discovery:** Scans your repo exclusively for folders containing `testbench.json`. Subsystems without `testbench.json` (even if they have `CMakeLists.txt`) are excluded from hardware testing.
- ⚡ **Smart Change-Detection:** Compiles and flashes **only the ECUs modified** in that push/PR.
- 🎯 **Per-ECU Microcontroller Routing:** Reads each folder's `testbench.json` to flash the correct board on `stolerpi` (e.g. `/dev/esp32_johnathan` vs `/dev/esp32_ahmed`).
- 📊 **Rich Step Summary:** Posts pass/fail tables with test assertions directly to GitHub.
- 🧩 **Zero-Maintenance Monorepo:** Adding a new ECU folder requires **no workflow edits**!

For standalone composite action usage and configuration details, see the [Full Documentation](github-action/README.md#6-plug-and-play-integration-guide).
