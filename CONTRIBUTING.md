# Contributing to CalSol CAN TestBench

This document outlines development workflows, code standards, and verification requirements for contributing to the CalSol Hardware-in-the-Loop (HIL) Testbench platform and associated vehicle firmware.

---

## 1. Development & Branching Workflow

1. **Fork the Repository:** Create your developer fork on GitHub.
2. **Branch Naming:** Create feature branches using standard prefixes:
   - `feature/<subsystem>-<description>` (e.g. `feature/bms-interlock-assertions`)
   - `fix/<subsystem>-<description>` (e.g. `fix/pedals-deadzone-saturation`)
   - `ci/<description>` (e.g. `ci/ccache-optimization`)
   - `docs/<description>` (e.g. `docs/stage-guide-clarification`)
3. **Upstream Safety:** Never push unverified branches directly to `origin/main` (`CalSol/CAN_TestBench`). Validate all changes on your developer fork first.

---

## 2. Pre-Commit Verification Checklist

Before pushing commits or opening a Pull Request, verify the following:

### A. Pre-Hardware Quality Gate (Static Analysis)
Run cppcheck locally using the testbench static analyzer:
```bash
./github-action/static-check.sh
```
All errors and high-severity defects must be resolved before hardware allocation.

### B. C/C++ Code Styling
Format all C and header files using the repository's `.clang-format` configuration:
```bash
clang-format -i main/*.c main/*.h test/main/*.c test/main/*.h
```

### C. Zero-Hardcode Standards
1. **Transceiver GPIOs:** Never hardcode transceiver TX/RX pins in shared components without `#ifndef` and Kconfig overrides. Use `CONFIG_CAN_TX_GPIO` and `CONFIG_CAN_RX_GPIO`.
2. **Deterministic Timeouts:** Always drain FreeRTOS queues (`while (CAN_receive(&rx_msg, 5) == ESP_OK) {}`) before asserting `ESP_ERR_TIMEOUT`.
3. **No Synthetic Telemetry:** Never fabricate mock packets in telemetry ingesters or fallback datasets. If a subsystem emits zero frames, report an empty list (`[]`).
4. **No Decorative Emojis:** Do not commit emojis or decorative glyphs into code, scripts, or markdown.

---

## 3. Adding a New ECU Subsystem to CI

To add a new ECU folder to the automated test matrix:
1. Create a `testbench.json` manifest in the subsystem root folder:
   ```json
   {
     "name": "bms_fw",
     "target": "bms_fw/test",
     "port": "/dev/esp32_johnathan",
     "baud": 921600,
     "timeout": 15,
     "description": "Battery Management System Voltage & Thermal Assertions"
   }
   ```
2. Include the standard ESP-IDF CMake files (`CMakeLists.txt`, `main/CMakeLists.txt`, `sdkconfig.defaults`).
3. Ensure the test entrypoint initializes serial and calls `UNITY_BEGIN()` and `UNITY_END()`.
4. The auto-discovery engine will detect the folder on the next push or Pull Request.

---

## 4. Hardware Safety Protocols

1. **High-Voltage Pack Isolation:** Verify that traction high-voltage contactors are open before connecting testbench nodes.
2. **Split Termination Check:** Multimeter resistance across CAN_H and CAN_L must read $60\,\Omega \pm 3\,\Omega$ with power disconnected.
3. **Common Ground:** Maintain a common ground reference between the host runner and DUT to prevent transceiver damage.
