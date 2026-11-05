# CalSol CAN Testbench & CI Monorepo

Continuous integration, remote hardware testbench flashing, Slack bot management, and on-target Unity unit testing for the UC Berkeley Solar Vehicle Team (**CalSol**).

Designed as the testing ground and prototype for [`CalSol/Gen11-FW`](https://github.com/CalSol/Gen11-FW).

---

## 1. Repository Structure

```text
CAN_TestBench/
├── .github/workflows/          # Central GitHub Actions CI/CD workflows for Raspberry Pi
│   └── unit-test.yml           # Multi-subsystem hardware test matrix & reusable workflow
│
├── components/                 # Shared vehicle components & libraries
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
├── server/                     # Raspberry Pi & CI Hardware Testbench Runner
│   ├── cal-test.sh             # Automated build, flash, and test orchestrator
│   ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
│   └── lib/
│       └── unity_parser.py     # Serial monitor & GitHub Actions summary table generator
│
└── Slack_Bot/                  # Bench Pi Slack Bot Daemon (@bot commands)
    ├── bot.py
    ├── esp_fleet_bot.service
    ├── requirements.txt
    └── Readme.md
```

---

## 2. Running Hardware Unit Tests Locally

On the Raspberry Pi testbed (`stolerpi`):

```bash
# Test the lights subsystem
./server/cal-test.sh lights_fw/test

# Test the pedals subsystem
./server/cal-test.sh pedals_fw/test
```

---

## 3. Automated Testing via GitHub Actions

Every push or Pull Request automatically runs the test matrix across all registered subsystems on real ESP32-S3 silicon connected to `stolerpi`. Results are posted directly to `$GITHUB_STEP_SUMMARY`.
