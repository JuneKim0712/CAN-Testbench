# CalSol CAN Testbench - Server (Raspberry Pi Host)

The `server/` directory contains the scripts and configurations deployed directly onto the central Raspberry Pi testbench host (`stolerpi`). It arbitrates physical access to multiple ESP32 boards, locks hardware devices during active flashing, runs automated Unity assertions, and controls USB power.

---

## 1. Directory Structure

```text
server/
├── cal-flash.sh         # Hardware mutex flashing runner
├── cal-test.sh          # Automated Unity test runner & serial parser
├── cal-status.sh        # Live status of connected boards and locks
├── cal-powercycle.sh    # USB hub power-cycling using uhubctl
├── udev/
│   ├── 99-calsol.rules  # Static USB device symlinks (/dev/esp32_*)
│   └── setup-udev.sh    # Installs and reloads udev rules
└── README.md
```

---

## 2. Server Installation

### A. Install Server Utilities to PATH
To make `cal-flash`, `cal-test`, and `cal-status` executable by all users:

```bash
# Add server directory to PATH or symlink to /usr/local/bin:
sudo ln -sf $(pwd)/server/cal-flash.sh /usr/local/bin/cal-flash
sudo ln -sf $(pwd)/server/cal-test.sh /usr/local/bin/cal-test
sudo ln -sf $(pwd)/server/cal-status.sh /usr/local/bin/cal-status
sudo ln -sf $(pwd)/server/cal-powercycle.sh /usr/local/bin/cal-powercycle
```

### B. Setup Persistent Device Names (`udev`)
```bash
sudo ./server/udev/setup-udev.sh
```

---

## 3. Server Scripts Overview

### `cal-flash <board> <binary> [offset]`
- Acquires an exclusive file lock (`flock`) on the target board before starting.
- Automatically selects the appropriate `esptool` executable.
- Flashes at 921,600 baud and resets the board.

### `cal-test <board> <test_binary>`
- Flashes the target board with a Unity unit test binary.
- Monitors UART serial traffic until the test summary is emitted.
- Exits with `0` if all tests pass, or `1` if any assertion fails or times out.

### `cal-status`
- Prints an ASCII table showing all registered boards, their device symlinks, and whether another developer is currently holding a lock.
