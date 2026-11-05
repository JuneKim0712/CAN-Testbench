# CalSol CAN Testbench

Testing infrastructure, Slack bot automation, continuous integration, and automated on-target Unity unit testing for the UC Berkeley Solar Vehicle Team (**CalSol**).

---

## 1. Repository Structure

```text
CAN_TestBench/
├── .github/workflows/          # GitHub Actions CI/CD workflows for Raspberry Pi
│   └── unit-test.yml           # Automated hardware testbench workflow
│
├── Slack_Bot/                  # Bench Pi Slack Bot Daemon (@bot commands)
│   ├── bot.py                  # Slack Socket Mode bot (scan, flash, verify, who)
│   ├── esp_fleet_bot.service   # Systemd service unit template
│   ├── requirements.txt        # Python dependencies (slack-bolt, pyserial)
│   └── Readme.md               # Slack bot documentation and token setup
│
├── server/                     # Raspberry Pi & CI Hardware Testbench Engine
│   ├── cal-test.sh             # Automated build, flash, and test orchestrator
│   ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
│   └── lib/
│       └── unity_parser.py     # Serial monitor & GitHub Actions summary generator
│
└── unit-testing/
    └── fw-lab-examples/        # Firmware lab code & test suites
        ├── components/can_driver/ # Shared TWAI/CAN bus driver
        ├── brakelights/        # Brakelights ECU firmware & test suite
        │   ├── main/main.c     # Production brakelights firmware
        │   └── test/           # Hardware unit test suite
        └── pedals/             # Pedals ECU firmware & test suite
            ├── main/main.c     # Production throttle firmware
            └── test/           # Hardware unit test suite
```

---

## 2. Running Hardware Unit Tests Locally

On the Raspberry Pi testbed (`stolerpi`):

```bash
# Test the brakelights subsystem
./server/cal-test.sh unit-testing/fw-lab-examples/brakelights/test

# Test the pedals subsystem
./server/cal-test.sh unit-testing/fw-lab-examples/pedals/test
```

---

## 3. Automated Testing via GitHub Actions

Every push or Pull Request automatically runs the test matrix across all registered subsystems on real ESP32-S3 silicon connected to `stolerpi`. Results are posted directly to `$GITHUB_STEP_SUMMARY`.
