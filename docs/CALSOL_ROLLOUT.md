# Deploy CalSol CAN TestBench

## 1. Merge and deploy the website

Review and merge the codex/calsol-rollout branch into CalSol/CAN_TestBench main.
This rollout preserves the upstream Slack_Bot and unit-testing training projects.
Repository administrators must configure these GitHub settings:

1. Settings > Pages > Build and deployment > Source: GitHub Actions.
2. Settings > Environments > github-pages: permit deployment from main.
3. Settings > Actions > General: allow the workflow actions and self-hosted runner.
4. Merge into main. Pushes touching web/ trigger Deploy Testbench Telemetry to
   GitHub Pages. Alternatively Actions > that workflow > Run workflow > main.
5. Expected URL: https://calsol.github.io/CAN_TestBench/ (subject to organization
   Pages settings). Verify the deployment job, not just a successful build.

The workflow now permits CalSol deployments. Test artifacts update only web/data,
so an older report bundle cannot roll back the current frontend.

Live status automatically uses web/bridge-config.js. It currently points to the
existing approved read-only Pi relay. Visitors need no configuration or SSH.
The current Cloudflare Quick Tunnel URL changes if cloudflared restarts; an admin
must update that file and redeploy. For stable production operation, configure a
named Cloudflare tunnel and permanent HTTPS hostname, then replace this URL.
The public relay exposes GET /health and /api/frames only, never CAN injection.
See LIVE_PUBLIC_STATUS.md for service paths and refresh intervals.

## 2. Connect the physical bench

Use TWO ESP32-S3 boards: one debugger and one DUT (device under test). Each needs
a compatible CAN transceiver. On both boards, the current driver defaults are:

- GPIO17 -> transceiver TXD; GPIO18 <- transceiver RXD.
- Correct supply for the actual transceiver module; logic must suit ESP32 3.3V.
- CAN_H -> CAN_H; CAN_L -> CAN_L; common ground/reference between nodes.
- One 120 ohm end terminator at each end of the bus. With power disconnected,
  two parallel 120 ohm resistors should measure about 60 ohms across CAN_H/CAN_L.
- Both firmwares use 500000 bit/s. Check enable/standby pins for your actual module.
- Connect BOTH ESP32 USB cables to the Pi. The debugger alone is insufficient
  for peer reception testing. A software heartbeat is not physical CAN traffic.

On the Pi:

```bash
ls -l /dev/serial/by-id/ /dev/esp32_*
```

The expected aliases are /dev/esp32_ahmed (debugger) and /dev/esp32_johnathan (DUT).
Use actual serial numbers from udevadm for persistent udev rules; AHMED_* and
JOHNATHAN_* in older examples are placeholders, not board serial numbers.
Give the runner user dialout access, log in again, and verify distinct canonical
paths with readlink -f. The DUT is currently missing from the deployed Pi.

## 3. Prepare the Pi and debugger

The existing stolerpi already has ESP-IDF, bridge and live relay installed. Do not
install a second daemon or open the debugger serial port while its owner runs.
For a new bench, install ESP-IDF and pyserial, register a repository/organization
Actions runner with self-hosted, linux, ARM64 labels, and use the same Linux user
and device/bus locks for local and CI tests. Runner registration is done through
Settings > Actions > Runners > New self-hosted runner; use GitHub's generated
commands and keep its registration token out of commits and logs.

Initialize and build the debugger from this checkout:

```bash
source /opt/esp-idf/export.sh
idf.py -C debugger_fw set-target esp32s3
idf.py -C debugger_fw build
# Preserve existing firmware before replacing it. Coordinate with any active job.
sudo systemctl stop can-bridge-daemon.service
idf.py -C debugger_fw -p /dev/esp32_ahmed flash
sudo systemctl start can-bridge-daemon.service
curl --fail http://127.0.0.1:8765/health
```

The existing service name is can-bridge-daemon.service. The generic repository
unit is systemd/calsol-can-sniffer.service; on a NEW bench edit its User and
WorkingDirectory to match your deployment, install it, and run only one bridge.
The bridge owns USB; consumers use /tmp/calsol_can.sock or its read-only web feed.
Its ports should remain loopback-bound. Do not expose raw command port 5555.

## 4. Run the existing unit tests

After merging, on GitHub choose Actions > CalSol Hardware Unit Tests > Run
workflow > main. Set target to pedals_fw or lights_fw, or all. The manifest points
to the test directory and DUT alias. The hardware job runs on the registered Pi.
Expect cloud regression/static checks, firmware build/flash, complete Unity
results, physical frame verification, artifact upload and the report job.

To run locally from the repository root:

```bash
source /opt/esp-idf/export.sh
./github-action/cal-test.sh pedals_fw/test /dev/esp32_johnathan 12
./github-action/cal-test.sh lights_fw/test /dev/esp32_johnathan 12
```

Run one hardware test at a time. The scripts acquire canonical-device and bus
locks; don't independently flash or read the reserved debugger serial device.
The runner flashes TEST firmware, which replaces normal application firmware.
Restore your application afterward if the bench needs normal operation.

## 5. Add a developer unit-test project

```bash
cp -r templates/can-unit-test my_ecu_fw
cp my_ecu_fw/testbench.json.example my_ecu_fw/testbench.json
```

Edit the manifest name to my_ecu_fw and target to my_ecu_fw/test. Keep the copied
folder top-level so shared component paths resolve. Use the same production
message handler module in firmware and tests; never duplicate its implementation.
Construct CAN_message_t values in test/main/test_main.c, call the handler, assert
state/output, and register tests with RUN_TEST. Cover valid messages, wrong IDs,
wrong DLC, out-of-range payloads, and fresh state between cases.

```bash
./github-action/cal-test.sh my_ecu_fw/test /dev/esp32_johnathan 15
```

These direct C injection tests do not require real CAN traffic. On-device Unity
still needs the DUT connected. The .example manifest is intentionally inactive
until copied and renamed. The template README documents the optional physical
request/reply test using IDs 0x601 and 0x600, CONFIG_CAN_TEST_PHYSICAL_RX=y and
respond.py. Follow its responder-ready and cleanup procedure; do not merely
start an unsynchronized injector during flashing.

## 6. Acceptance checks

1. Both USB aliases exist and resolve to different devices.
2. Bridge health says serial_connected=true and mode=hardware.
3. A complete Unity suite passes, with no crash, timeout or incomplete summary.
4. Pedals physical test: independent debugger receives ID 0x11, DLC1, payloads
   0A,14,1E,28,32,3C,46,50,5A,64 in order.
5. Lights physical test: independent debugger receives ID 0x02, DLC1, payloads
   01 through 0A in order. UART TX logs and injection requests are not proof.
6. Optional physical request/reply test verifies DUT reception and application
   state, not just bridge request acceptance.
7. Public website loads automatically, status refreshes, unavailable USB is shown
   honestly, and simulated ID 0x700 messages remain labeled SIMULATED (Pi).
8. Inspect current-run JSON and physical trace artifacts. A green logic suite
   alone does not prove the electrical bus works.

Current limitation: physical cross-node reception has NOT passed. Earlier
rollback and GPIO-edge tests point to the inter-node electrical path. See
HISTORICAL_CAN_RECEPTION_INVESTIGATION.md. Do not change the test to accept
simulated messages as physical evidence.
