# CalSol CAN Testbench - Server (Raspberry Pi & CI Runner)

The `server/` directory contains the core test execution scripts used by the GitHub Actions self-hosted runner and local developers on the Raspberry Pi (`stolerpi`).

---

## Directory Structure

```text
server/
├── cal-test.sh         # Top-level automated build, flash, and Unity test runner
├── cal-flash.sh        # Fast esptool flashing runner with hardware mutex
└── lib/
    └── unity_parser.py # UART serial stream parser (outputs to terminal and GitHub Actions)
```

---

## Usage

### Run Unit Tests
Builds the firmware, flashes the target ESP32-S3 at 921,600 baud, and monitors Unity assertions:
```bash
./server/cal-test.sh [project_dir_or_bin] [serial_port]
```
- **Default project**: `examples/unit_test_app`
- **Default port**: Auto-detects active `/dev/ttyACM*` or `/dev/steering`

### Output Integration
When executed within a GitHub Actions workflow, `unity_parser.py` automatically detects `$GITHUB_STEP_SUMMARY` and posts a clean Markdown table summarizing test results directly onto the GitHub commit / PR dashboard.
