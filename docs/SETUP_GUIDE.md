# CalSol Hardware Testbench: Complete Host & Hardware Setup Guide

| [Overview](../README.md) | [Tutorial](TUTORIAL.md) | [Contributing](../CONTRIBUTING.md) | [Architecture](CODE_DOCUMENTATION.md) | [Bench Manual](CAN_TESTBENCH_STAGE_GUIDE.md) | **[Hardware Setup]** | [Debugging](DEBUGGING_GUIDE.md) | [Live Portal ↗](https://junekim0712.github.io/CAN-Testbench/) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |

---

Follow this guide to commission a new engineering laptop or Raspberry Pi lab runner from scratch.

---

## 1. Hardware Requirements & Wiring

### 1.1 Microcontrollers & Transceivers
- 2x ESP32-S3 DevKits (ESP32-S3-WROOM-1).
- 2x TI TCAN332 (or ISO 11898-2 compatible 3.3V CAN transceivers).

### 1.2 Pin Assignments (Both Nodes)
- `GPIO 17` $\rightarrow$ Transceiver **TXD**
- `GPIO 18` $\rightarrow$ Transceiver **RXD**
- `3.3V` & `GND` $\rightarrow$ Transceiver Power

### 1.3 Differential Bus Wiring
1. Connect Node 1 **CAN_H** to Node 2 **CAN_H**.
2. Connect Node 1 **CAN_L** to Node 2 **CAN_L**.
3. Install a $120\,\Omega$, 1/4W resistor across CAN_H and CAN_L at both physical ends of the twisted pair.

> [!CAUTION]
> Always verify bus resistance with power disconnected before connecting microcontrollers. Measure resistance between CAN_H and CAN_L with a multimeter. The reading must be $60\,\Omega \pm 3\,\Omega$. Missing or incorrect termination can cause unreliable communication. These are two end terminators, not split termination.

---

## 2. Host System Configuration (Linux / Raspberry Pi)

To ensure persistent device names regardless of USB plug order, configure custom `udev` rules:

### 2.1 Create the udev rule file:
```bash
sudo nano /etc/udev/rules.d/99-calsol-hil.rules
```

### 2.2 Add the persistent symlinks:
```udev
# Node 1: CAN Bus Debugger (/dev/esp32_ahmed)
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="AHMED_*", SYMLINK+="esp32_ahmed", MODE="0666"

# Node 2: Device Under Test (/dev/esp32_johnathan)
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="1001", ATTRS{serial}=="JOHNATHAN_*", SYMLINK+="esp32_johnathan", MODE="0666"
```

### 2.3 Reload rules and configure group permissions:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -a -G dialout,plugdev $USER
```
*(Log out and log back in for group permissions to take effect)*.

### 2.4 Verify device detection:
```bash
ls -la /dev/esp32_*
# Expected output:
# lrwxrwxrwx 1 root root /dev/esp32_ahmed -> ttyACM0
# lrwxrwxrwx 1 root root /dev/esp32_johnathan -> ttyACM1
```

---

## 3. Software Toolchain & Environment

### 3.1 Clone the repository:
```bash
git clone https://github.com/CalSol/CAN_TestBench.git
cd CAN_TestBench
```

### 3.2 Install system utilities:
```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-pip python3-venv ccache cppcheck
```

### 3.3 Install Python host dependencies:
```bash
pip3 install --user pyserial
```

### 3.4 Install and Source ESP-IDF (v5.1+ or v5.3+ recommended):
```bash
# If ESP-IDF is not yet installed:
mkdir -p ~/esp && cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git -b v5.3.1
cd esp-idf && ./install.sh esp32s3

# Export environment to current shell:
. ~/esp/esp-idf/export.sh
```
Verify installation:
```bash
idf.py --version
```

---

## 4. Setting Up the GitHub Actions Self-Hosted Runner

To configure `stolerpi` to execute automated CI jobs:

```bash
# 1. Download and extract actions runner package
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-arm64.tar.gz -L https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-arm64-2.321.0.tar.gz
tar xzf ./actions-runner-linux-arm64.tar.gz

# 2. Configure runner with stolerpi labels
./config.sh --url https://github.com/JuneKim0712/CAN-Testbench --token <RUNNER_REGISTRATION_TOKEN> --labels self-hosted,linux,ARM64,stolerpi

# 3. Enable systemd lingering service for 24/7 background availability
sudo loginctl enable-linger $USER
./svc.sh install
./svc.sh start
```

---

## 5. Setting Up the Permanent 24/7 CAN Bus Sniffer Service (`/dev/esp32_ahmed`)

To maintain an uninterrupted, authentic stream of all physical CAN bus traffic transmitted across the bench:

```bash
# 1. Copy the systemd unit file
sudo cp systemd/calsol-can-sniffer.service /etc/systemd/system/

# 2. Reload daemon and enable the service across system reboots
sudo systemctl daemon-reload
sudo systemctl enable --now calsol-can-sniffer.service

# 3. Verify real-time sniffer health
sudo systemctl status calsol-can-sniffer.service
```

The daemon connects directly to `/dev/esp32_ahmed` at 500 kbps, automatically reconnects if the silicon is reset, broadcasts live frames over WebSocket (port `8765`), Unix socket (`/tmp/calsol_can.sock`), and TCP (`5555`), and atomically writes real packet captures to `web/data/live_stream.json`.

---

[↑ Back to top](#calsol-hardware-testbench-complete-host--hardware-setup-guide)
