# CalSol CAN Testbench

Automated continuous integration, remote hardware testbench flashing, Slack bot management, and Unity unit testing for the UC Berkeley Solar Vehicle Team (**CalSol**).

---

## 1. Repository Structure

```text
CAN_TestBench/
├── .github/workflows/          # GitHub Actions CI/CD workflows for Raspberry Pi
├── Slack_Bot/                  # Bench Pi Slack Bot Daemon (@bot commands)
│   ├── bot.py                  # Slack Socket Mode bot (scan, flash, verify, who)
│   ├── esp_fleet_bot.service   # Systemd service unit template
│   ├── requirements.txt        # Python dependencies (slack-bolt, pyserial)
│   └── Readme.md               # Slack bot documentation and token setup
│
├── server/                     # Raspberry Pi & CI Hardware Testbench Runner
│   ├── cal-test.sh             # Automated build, flash, and test orchestrator
│   ├── cal-flash.sh            # Hardware mutex flashing runner
│   └── lib/
│       └── unity_parser.py     # Serial monitor & GitHub Actions summary formatter
│
├── examples/
│   └── unit_test_app/          # Reference ESP32-S3 Unity unit testing project
│       ├── CMakeLists.txt
│       └── main/
│           ├── CMakeLists.txt
│           └── test_main.c
│
└── unit-testing/
    └── fw-lab-examples/        # Vehicle node firmware (brakelights, pedals, can_driver)
```

---

## 2. Automated Testing via GitHub Actions

When you push code or open a Pull Request, the GitHub Action automatically runs on the Raspberry Pi testbed (`stolerpi`):
1. Checks out the code.
2. Compiles your firmware targeting `esp32s3`.
3. Flashes the connected ESP32-S3 over USB CDC at 921,600 baud.
4. Executes Unity assertions on real silicon and reports test results directly in the GitHub PR summary.

---

## 3. Slack Bot Integration (`Slack_Bot/`)

A Slack-driven ESP board discovery and verification daemon that runs on the bench Raspberry Pi:

| Slack Command | Action |
|---|---|
| `@bot boards` | List every ESP board plugged into the Pi (chip + MAC + port) |
| `@bot flash <port>` | Build + flash + verify firmware on target port |
| `@bot flash all` | Flash and verify on every connected board |
| `@bot confirm <code>` | Approve a gated flash if another member is active on the Pi |
| `@bot who` | Shows who is currently logged into the Pi |
| `@bot status` | IDF version, git commit SHA, uptime, cached builds |

See [Slack_Bot/Readme.md](Slack_Bot/Readme.md) for full setup instructions.
