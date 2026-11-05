# CalSol CAN Testbench Infrastructure

Testbench runner scripts, Raspberry Pi Slack bot daemon, firmware lab examples, and reusable GitHub Actions CI logic for the UC Berkeley Solar Vehicle Team (**CalSol**).

---

## 1. Repository Structure

This repository contains the infrastructure and server-side automation deployed on the bench Raspberry Pi (`stolerpi`):

```text
CAN_TestBench/
├── .github/workflows/          # Reusable GitHub Actions CI/CD workflows
│   └── unit-test.yml           # Reusable workflow logic for calling repos (e.g. Gen11-FW)
│
├── Slack_Bot/                  # Bench Pi Slack Bot Daemon (@bot commands - Jonathan Ji)
│   ├── bot.py                  # Slack Socket Mode bot (scan, flash, verify, who)
│   ├── esp_fleet_bot.service   # Systemd service unit template
│   ├── requirements.txt        # Python dependencies (slack-bolt, pyserial)
│   └── Readme.md               # Slack bot documentation and token setup
│
├── github-action/              # Hardware Testbench & GitHub Actions CI Engine
│   ├── cal-test.sh             # Automated build, flash, and test orchestrator
│   ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
│   ├── lib/
│   │   └── unity_parser.py     # Serial monitor & GitHub Actions summary generator
│   └── README.md               # Comprehensive GitHub Action & runner documentation
│
└── unit-testing/
    └── fw-lab-examples/        # Firmware lab code & examples (Kyle Liang)
        ├── components/can_driver/ # Shared TWAI/CAN bus driver
        ├── brakelights/        # Brakelights ECU firmware & build files
        └── pedals/             # Pedals ECU firmware & build files
```

---

## 2. Plug-and-Play Integration in Your Own Repository

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
- 🔍 **Auto-Discovers Subsystems:** Scans your repo for any folders containing `testbench.json` or `*/test/CMakeLists.txt`.
- ⚡ **Smart Change-Detection:** Compiles and flashes **only the ECUs modified** in that push/PR.
- 🎯 **Per-ECU Microcontroller Routing:** Reads each folder's `testbench.json` to flash the correct board on `stolerpi` (e.g. `/dev/esp32_johnathan` vs `/dev/esp32_ahmed`).
- 📊 **Rich Step Summary:** Posts pass/fail tables with test assertions directly to GitHub.
- 🧩 **Zero-Maintenance Monorepo:** Adding a new ECU folder requires **no workflow edits**!

For standalone composite action usage and configuration details, see the [Full Documentation](github-action/README.md#6-plug-and-play-integration-guide).

---

## 3. Running Testbench Scripts Locally on the Pi

On `stolerpi`:

```bash
# Build, flash, and run Unity tests on target
./github-action/cal-test.sh path/to/project_dir [port] [timeout]
```
