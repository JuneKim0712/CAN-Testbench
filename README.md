# CalSol CAN Testbench

Testing infrastructure, remote flashing, Slack bot automation, and continuous validation for the UC Berkeley Solar Vehicle Team (**CalSol**).

---

## 1. Repository Architecture

The repository contains three primary components:

```text
CAN-Testbench/
├── Slack_Bot/                  # Bench Pi Slack Bot Daemon (@bot commands)
│   ├── bot.py                  # Slack Socket Mode bot (scan, flash, verify, who)
│   ├── esp_fleet_bot.service   # Systemd service unit template
│   ├── requirements.txt        # Python dependencies (slack-bolt, pyserial)
│   └── Readme.md               # Slack bot documentation and token setup
│
├── client/                     # Developer Workstation Side (Laptop / PC)
│   ├── calsol.py               # Cross-platform CLI (Windows, macOS, Linux)
│   ├── calsol.sh               # Bash wrapper for UNIX environments
│   ├── config.json             # Remote host connection configuration
│   └── vscode/tasks.json       # VS Code keyboard shortcuts & tasks
│
├── server/                     # Raspberry Pi Testbench Side (Host Server)
│   ├── cal-flash.sh            # Hardware mutex flashing runner (flock)
│   ├── cal-test.sh             # Automated Unity test runner & serial parser
│   ├── cal-status.sh           # Active hardware availability and lock inspector
│   ├── cal-powercycle.sh       # USB hub power cycling via uhubctl
│   └── udev/                   # Static device rules for connected boards
│
└── examples/
    └── unit_test_app/          # Starter Unity unit test firmware for ESP32-S3
```

---

## 2. Slack Bot Overview (`Slack_Bot/`)

A Slack-driven ESP board discovery and verification daemon that runs continuously on the bench Raspberry Pi:

| Slack Command | Action |
|---|---|
| `@bot boards` | List every ESP board plugged into the Pi (chip + MAC + port) |
| `@bot flash <port>` | Build + flash + verify firmware on target port |
| `@bot flash all` | Flash and verify on every connected board |
| `@bot confirm <code>` | Approve a gated flash if another member is SSH'd into the Pi |
| `@bot who` | Shows who is currently logged into the Pi |
| `@bot status` | IDF version, git commit SHA, uptime, cached builds |

See [Slack_Bot/Readme.md](Slack_Bot/Readme.md) for full configuration, Slack API scopes, and systemd service setup.

---

## 3. Quickstart: Developer (Client Side)

1. **Clone this repository on your laptop:**
   ```bash
   git clone https://github.com/CalSol/CAN_TestBench.git
   cd CAN_TestBench
   ```

2. **Configure your connection in `client/config.json`:**
   ```json
   {
     "host": "stolerpi",
     "remote_user": "<your_pi_username>",
     "default_board": "steering"
   }
   ```

3. **Check testbench status:**
   ```bash
   python client/calsol.py status
   ```

4. **Flash firmware remotely from your workstation:**
   ```bash
   python client/calsol.py flash <board_name> --binary path/to/firmware.bin
   ```

5. **Run automated on-target Unity unit tests:**
   ```bash
   python client/calsol.py test <board_name> --binary path/to/unit_tests.bin
   ```

6. **Monitor live serial console output:**
   ```bash
   python client/calsol.py monitor <board_name>
   ```

---

## 4. Quickstart: Raspberry Pi Host (Server Side)

1. **Clone / Sync on the Raspberry Pi (`stolerpi`):**
   ```bash
   git clone https://github.com/CalSol/CAN_TestBench.git ~/CAN_TestBench
   ```

2. **Make scripts executable and link them:**
   ```bash
   chmod +x ~/CAN-Testbench/server/*.sh
   sudo ln -sf ~/CAN-Testbench/server/cal-flash.sh /usr/local/bin/cal-flash
   sudo ln -sf ~/CAN-Testbench/server/cal-test.sh /usr/local/bin/cal-test
   sudo ln -sf ~/CAN-Testbench/server/cal-status.sh /usr/local/bin/cal-status
   sudo ln -sf ~/CAN-Testbench/server/cal-powercycle.sh /usr/local/bin/cal-powercycle
   ```

3. **Install persistent `udev` device mappings:**
   ```bash
   sudo ~/CAN-Testbench/server/udev/setup-udev.sh
   ```

---

## 5. Hardware Safety & Multi-User Arbitration

* **Hardware Mutex (`flock`):** The server-side flashing engine locks each target board's serial port with `flock`. If another developer is currently testing or flashing a board, concurrent attempts are held safely in a queue or cleanly rejected rather than corrupting flash memory.
* **USB Power-Cycling:** Hung or frozen boards can be hard-reset without physical access using `python client/calsol.py powercycle`.
