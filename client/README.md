# CalSol CAN Testbench - Client (Developer Workstation)

The `client/` folder contains tools for developers working from their personal laptops (Windows, macOS, Linux, WSL). It abstracts remote operations so developers can build locally, push binaries, flash remote ESP32s, and inspect test output with simple commands.

---

## 1. Prerequisites

1. **SSH Key Access:**
   Ensure your SSH key is authorized on the Raspberry Pi host (e.g. `stolerpi` in `~/.ssh/config`):
   ```text
   Host stolerpi
       HostName stolerpi
       User jkim
       IdentityFile ~/.ssh/id_ed25519
   ```
2. **Python 3:**
   Ensure Python 3 is installed on your workstation.

---

## 2. Configuration (`client/config.json`)

Edit `client/config.json` to customize target settings:
```json
{
  "host": "stolerpi",
  "remote_user": "jkim",
  "staging_dir": "~/calsol/staging",
  "default_board": "esp32_johnathan",
  "baud_rate": 921600
}
```

---

## 3. Usage

### Using Python CLI (Windows PowerShell, macOS, Linux)
```bash
# Check testbench board availability and active locks
python client/calsol.py status

# Flash firmware binary
python client/calsol.py flash esp32_johnathan --binary build/steering.bin

# Run automated Unity unit tests on physical hardware
python client/calsol.py test esp32_johnathan --binary build/unit_tests.bin

# Open interactive serial console
python client/calsol.py monitor esp32_johnathan

# Powercycle hung USB hubs if a board stops responding
python client/calsol.py powercycle
```

### Using Bash CLI (macOS / Linux / WSL)
```bash
chmod +x client/calsol.sh
./client/calsol.sh flash esp32_johnathan build/steering.bin
./client/calsol.sh test esp32_johnathan build/unit_tests.bin
./client/calsol.sh monitor esp32_johnathan
```

---

## 4. VS Code Integration

Copy `client/vscode/tasks.json` into your local `.vscode/tasks.json` inside your firmware project repository to trigger remote flashing and testing via **Ctrl+Shift+B** or the VS Code Task Runner.
