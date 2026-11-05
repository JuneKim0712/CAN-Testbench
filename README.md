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

## 2. Guide: Implementing Hardware CI in Your Own Repository

To integrate automated Hardware-in-the-Loop (HIL) testing on physical ESP32-S3 silicon into your own repository (such as [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW) or a subsystem testing repo):

### Option 1: Reusable Workflow (Quickest Setup)

Add `.github/workflows/hardware-test.yml` to your repository:

```yaml
name: Hardware Testbench

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  run-testbench:
    name: Run On-Target ESP32 Test
    uses: CalSol/CAN_TestBench/.github/workflows/unit-test.yml@main
    with:
      target: 'path/to/your/test_project'  # Path to the ESP-IDF project containing test_main.c
      # port: '/dev/esp32_johnathan'       # Optional port override; defaults to testbench.json or auto-detection
```

### Option 2: Monorepo Dynamic Matrix (Path-Filtered)

For repositories containing multiple vehicle ECUs (like `Gen11-FW`), use path filtering so that only modified subsystems are compiled and tested on their designated microcontrollers:

1. **Add `testbench.json` to each subsystem folder:**
   ```json
   {
     "name": "steering_fw",
     "target": "steering_fw/test",
     "port": "/dev/steering",
     "timeout": 12
   }
   ```
2. **Configure dynamic matrix dispatch:** Refer to the comprehensive [Step-by-Step Integration Guide](github-action/README.md#6-guide-implementing-hardware-ci-in-your-own-repository) for the full workflow template, configuration schema, runner setup, and local Pi debugging instructions.

---

## 3. Running Testbench Scripts Locally on the Pi

On `stolerpi`:

```bash
# Build, flash, and run Unity tests on target
./github-action/cal-test.sh path/to/project_dir [port] [timeout]
```
