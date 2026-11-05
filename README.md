# CalSol CAN Testbench

Unified hardware-in-the-loop (HIL) testing, remote flashing, and continuous validation infrastructure for the UC Berkeley Solar Vehicle Team (**CalSol**).

---

## 1. Architecture Overview

The repository is structured into two main components:

```
CAN-Testbench/
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

## 2. Quickstart: Developer (Client Side)

1. Clone this repository to your laptop:
   ```bash
   git clone https://github.com/JuneKim0712/CAN-Testbench.git
   cd CAN-Testbench
   ```

2. Configure your SSH target in `client/config.json`:
   ```json
   {
     "host": "stolerpi",
     "remote_user": "jkim",
     "default_board": "esp32_johnathan"
   }
   ```

3. Flash a firmware binary from your laptop to the remote testbench:
   ```bash
   python client/calsol.py flash esp32_johnathan --binary path/to/firmware.bin
   ```

4. Run automated on-target Unity unit tests:
   ```bash
   python client/calsol.py test esp32_johnathan --binary path/to/unit_tests.bin
   ```

5. Monitor serial output live:
   ```bash
   python client/calsol.py monitor esp32_johnathan
   ```

---

## 3. Quickstart: Raspberry Pi Host (Server Side)

1. Clone or sync this repository onto the Raspberry Pi (`stolerpi`):
   ```bash
   git clone https://github.com/JuneKim0712/CAN-Testbench.git ~/calsol/server
   ```

2. Make scripts executable and link them to `/usr/local/bin` (or user `~/bin`):
   ```bash
   chmod +x ~/calsol/server/*.sh
   sudo ln -sf ~/calsol/server/cal-flash.sh /usr/local/bin/cal-flash
   sudo ln -sf ~/calsol/server/cal-test.sh /usr/local/bin/cal-test
   sudo ln -sf ~/calsol/server/cal-status.sh /usr/local/bin/cal-status
   sudo ln -sf ~/calsol/server/cal-powercycle.sh /usr/local/bin/cal-powercycle
   ```

3. Install persistent `udev` device mappings:
   ```bash
   sudo ~/calsol/server/udev/setup-udev.sh
   ```

---

## 4. Hardware Safety & Multi-User Arbitration

* **Hardware Mutex (`flock`):** The server-side flashing engine locks each target board's serial port with `flock`. If another developer is currently testing or flashing a board, concurrent attempts are held safely in a queue or cleanly rejected rather than corrupting flash memory.
* **USB Power-Cycling:** Hung or frozen boards can be hard-reset without physical access using `calsol.py powercycle`.
