# CAN unit test starter

Copy this starter to a top-level ECU folder. Direct injection tests run by default
on the ESP32 through Unity and require no CAN peer. Physical injection is opt-in.
The example IDs 0x600/0x601 and demand range 0..100 are a test protocol, not the
vehicle's existing pedal protocol.

## Start a subsystem

From the repository root on the Linux bench runner:

```bash
cp -r templates/can-unit-test example_fw
cp example_fw/testbench.json.example example_fw/testbench.json
./github-action/cal-test.sh example_fw/test
```

For a different folder name, update `name` and `target` in `testbench.json`.
The checked-in starter intentionally has no active `testbench.json`, so discovery
will not allocate hardware for the template itself. Keep the copied project at
the repository's top level so its shared-component path resolves.

## Inject directly in C

`test/main/test_main.c` constructs a `CAN_message_t` and calls
`handle_command(&state, &message)`. This is the fastest way to test a spoofed ID,
payload, invalid DLC, RTR, extended frames, and application state changes.
It does not transmit a physical frame or exercise TWAI/ISR reception.

Replace `main/message_handler.c` with your production decoder/state logic and
link that same module into your firmware. Do not copy its implementation into
the test. The starter links the example handler into the test project; it does
not include a complete production firmware project.

Each test begins with fresh state. `tearDown()` releases CAN after physical-test
assertion failures. Add tests using `RUN_TEST(your_test)` in `app_main()`.
Use explicit `.dlc = 0` for an empty frame: the current shared packet builder
treats zero as a request for eight bytes. Source buffers must contain at least
the number of bytes the builder will copy.

## Spoof a peer over the physical bus

Use the existing bridge daemon and debugger ESP32 with the DUT on the same
500 kbps bench bus. The debugger must support serial-to-CAN injection. Select
unused IDs if your bench has other nodes transmitting these example IDs.

Enable the optional test once:

```bash
cd example_fw/test
idf.py menuconfig
# CAN message test options -> Run physical CAN request/reply test
cd ../..
```

For a fresh CI build, add `CONFIG_CAN_TEST_PHYSICAL_RX=y` to the copied project's
`test/sdkconfig.defaults`. Existing `sdkconfig` files can override defaults; use
menuconfig to change an already-configured local build.

Start the responder before the hardware test. Wait for its connection rather
than sleeping for a guessed build/flash duration:

```bash
set -e
python3 example_fw/respond.py --duration 600 > /tmp/example-responder.log 2>&1 &
responder=$!
trap 'kill "$responder" 2>/dev/null || true; wait "$responder" 2>/dev/null || true' EXIT
ready=0
for attempt in $(seq 1 50); do
    if grep -q 'Responder ready' /tmp/example-responder.log; then
        ready=1
        break
    fi
    if ! kill -0 "$responder" 2>/dev/null; then
        cat /tmp/example-responder.log
        exit 1
    fi
    sleep 0.1
done
if [ "$ready" != 1 ]; then
    cat /tmp/example-responder.log
    exit 1
fi
./github-action/cal-test.sh example_fw/test
```

The bridge must be running before this block (for example via the supplied
systemd service). The DUT initializes CAN, sends `0x601 [A5]`, and waits up to
two seconds. The responder observes that physical request and injects
`0x600 [32]`. The DUT validates reception and the resulting demand of 50.
Unrelated frames are ignored within the fixed deadline.

The responder also accepts `--tcp HOST PORT`. It supports the bridge's current
`id_int`/`raw` fields and `id`/`data` events. Bridge acknowledgments confirm a
request was handled; the DUT assertion establishes successful physical reception.
This example tests one exchange; it does not measure loss or throughput.

For manual injection while a receiver is already running:

```bash
python3 github-action/lib/calsol_inject.py --id 0x600 --data 32
python3 github-action/lib/calsol_inject.py --id 0x600 --data 32 --rate 10 --count 20
```

## GitHub Actions

The existing workflow discovers the copied `testbench.json` on PRs and pushes
to main; no new workflow is needed for direct injection tests.

For the optional physical test, place the responder block above in the hardware
job in place of its `Run Hardware Test Action` step, using the same matrix target
and port arguments if testing several subsystems. Start responders only for the
matching physical-test subsystem. Keep the existing artifact-upload steps.
Run one request/reply exchange at a time on a shared bus and keep the bench's
normal hardware lock in use through `cal-test.sh`.

Validate a valid command, each boundary, wrong ID, incorrect DLC, invalid value,
RTR/extended flags, and unchanged state after rejection before enabling HIL.
