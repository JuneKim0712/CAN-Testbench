# CalSol Hardware Testbench: 5-Minute Quickstart Tutorial

| [Overview](../README.md) | **[Tutorial]** | [Contributing](../CONTRIBUTING.md) | [Architecture](CODE_DOCUMENTATION.md) | [Bench Manual](CAN_TESTBENCH_STAGE_GUIDE.md) | [Hardware Setup](SETUP_GUIDE.md) | [Debugging](DEBUGGING_GUIDE.md) | [Live Portal ↗](https://junekim0712.github.io/CAN-Testbench/) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |

---

This tutorial walks you through creating, compiling, and validating a new firmware unit test on physical ESP32-S3 silicon connected to the differential CAN bus.

---

## Prerequisites
- A clone of [`CalSol/CAN_TestBench`](https://github.com/CalSol/CAN_TestBench) or your team fork.
- Basic familiarity with C and Git.

---

## Step 1: Create the Subsystem Test Folder

In your repository, create the standard directory structure for your ECU test suite:

```bash
mkdir -p bms_fw/test/main
```

---

## Step 2: Define the CI Hardware Manifest (`testbench.json`)

Create `bms_fw/testbench.json`. This tells the auto-discovery engine where to find the test project, what baud rate to use, and how long to wait before timing out:

```json
{
  "name": "bms_fw",
  "target": "bms_fw/test",
  "port": "/dev/esp32_johnathan",
  "baud": 921600,
  "timeout": 15,
  "description": "Battery Management System Voltage & Thermal Interlock Assertions"
}
```

> [!TIP]
> Setting `"port": ""` enables automatic port detection, which finds any connected ESP32 board on the runner.

---

## Step 3: Configure ESP-IDF Build Files

### 1. `bms_fw/test/CMakeLists.txt`
```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(bms_fw_test)
```

### 2. `bms_fw/test/main/CMakeLists.txt`
```cmake
idf_component_register(SRCS "test_main.c"
                       INCLUDE_DIRS "."
                       REQUIRES unity can_driver)
```

### 3. `bms_fw/test/sdkconfig.defaults`
```ini
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESP_CONSOLE_UART_BAUDRATE=115200
```

---

## Step 4: Write Unity Test Assertions

Create `bms_fw/test/main/test_main.c`:

```c
#include <stdio.h>
#include "unity.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "CAN.h"

// Logic under test: Undervoltage safety cutoff threshold (2.80V)
static bool check_undervoltage_trip(uint16_t cell_mv) {
    return (cell_mv < 2800);
}

static void test_cell_undervoltage_protection(void) {
    // 2.75V should trigger immediate trip
    TEST_ASSERT_TRUE(check_undervoltage_trip(2750));

    // 3.30V nominal should not trip
    TEST_ASSERT_FALSE(check_undervoltage_trip(3300));
}

static void test_can_telemetry_broadcast(void) {
    TEST_ASSERT_EQUAL(ESP_OK, CAN_init());

    uint8_t payload[2] = {0x0A, 0xF0}; // 2800 mV in hex
    CAN_message_t msg = build_packet_no_ext(0x301, payload, 2);

    TEST_ASSERT_EQUAL(ESP_OK, CAN_send(&msg, 50));

    CAN_deinit();
}

void app_main(void) {
    // Allow UART serial and clock PLL to stabilize
    vTaskDelay(pdMS_TO_TICKS(1500));

    UNITY_BEGIN();
    RUN_TEST(test_cell_undervoltage_protection);
    RUN_TEST(test_can_telemetry_broadcast);
    UNITY_END();
}
```

---

## Step 5: Test Locally on the Bench Runner

If you have SSH access to `stolerpi` (Raspberry Pi 5):

```bash
# Execute your new test suite directly:
./github-action/cal-test.sh bms_fw/test
```

Expected terminal output:
```text
==================================================
CalSol Hardware Testbench: bms_fw
DUT Port:     /dev/esp32_johnathan (esp32_johnathan)
Target Path:  bms_fw/test
Flashing:     921600 baud
Test Timeout: 15s
==================================================
Building Firmware (bms_fw)
[+] Build completed successfully.
Flashing Silicon (esp32_johnathan @ 921600 baud)
[+] Fast differential app-flash succeeded.
On-Target Silicon Execution & Live CAN Stream (bms_fw)
[*] Monitoring DUT UART output & physical CAN bus traffic...
    [CAN LIVE] 0x301 (BMS_VOLTAGE) DLC:2 [0A F0] -> Cell Voltage Broadcast
[+] Tests: 2 Failures: 0 Ignored: 0 (ALL PASSED)
```

---

## Step 6: Push & Validate via GitHub Actions

1. Commit and push your changes to your feature branch:
   ```bash
   git add bms_fw/
   git commit -m "feat(bms): add undervoltage protection unit test"
   git push origin feature/bms-test
   ```
2. Open a Pull Request on GitHub.
3. The CI engine automatically detects `bms_fw/testbench.json`, runs cloud static analysis, dispatches the job to physical silicon on `stolerpi`, and posts the results table to `$GITHUB_STEP_SUMMARY`.
4. Download your precompiled `bms_fw.bin` from the workflow run artifacts for trackside deployment.

---

[↑ Back to top](#calsol-hardware-testbench-5-minute-quickstart-tutorial)
