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
├── server/                     # Raspberry Pi Testbench Engine
│   ├── cal-test.sh             # Automated build, flash, and test orchestrator
│   ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
│   ├── lib/
│   │   └── unity_parser.py     # Serial monitor & GitHub Actions summary generator
│   └── README.md
│
└── unit-testing/
    └── fw-lab-examples/        # Firmware lab code & examples (Kyle Liang)
        ├── components/can_driver/ # Shared TWAI/CAN bus driver
        ├── brakelights/        # Brakelights ECU firmware & build files
        └── pedals/             # Pedals ECU firmware & build files
```

---

## 2. Using the Reusable GitHub Action Workflow

To use this hardware testbench in another repository (e.g., [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW) or firmware testing grounds):

Add `.github/workflows/testbench.yml` to your repository:

```yaml
name: Hardware Testbench

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  run-testbench:
    uses: CalSol/CAN_TestBench/.github/workflows/unit-test.yml@main
    with:
      target: 'path/to/your/test_project'  # Path to the ESP-IDF project containing test_main.c
```

---

## 3. Running Testbench Scripts Locally on the Pi

On `stolerpi`:

```bash
# Build, flash, and run Unity tests on target
./server/cal-test.sh path/to/project_dir [port]
```
