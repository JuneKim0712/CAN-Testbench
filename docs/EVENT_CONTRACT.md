# Capture and verification contract

Physical capture events use schema_version 1 and contain:

- session_id: bridge process UUID; sequence: strictly increasing capture number.
- event=frame, direction=rx, source=physical_bus.
- timestamp: host receipt time in Unix seconds; not a hardware wire timestamp.
- id_int, formatted id, dlc, data (compact hex), raw (spaced hex).
- extended=false and rtr=false: this paired debugger firmware rejects other
  formats before legacy serialization. Arbitrary legacy firmware cannot recover
  those flags; do not claim extended/RTR support without a protocol upgrade.

The pair (session_id, sequence) identifies an event. Identical payloads in
consecutive physical receptions are distinct events. Injection requests and
controller diagnostics are never physical reception evidence.

Each result stores run_id, subsystem, completed Unity counts, exact source
locations when emitted by Unity, duration, capture_error, verification_mode,
and physical_expectations_passed. The embedded can_traffic is the authoritative
report input; JSONL is the raw archive, not another set of packets to append.
Publish only results whose run_id matches the requested run.

## Configuration

Subsystem testbench.json is validated by the discovery engine and runner.
CLI target/port/timeout overrides take precedence over manifest values; manifest
values take precedence over defaults. A missing explicit device is an error.
Names contain letters, digits, dash or underscore; targets stay within the
repository. Timeouts are positive and at most 600 seconds.

expected_can contains standard identifiers and their exact ordered hex payloads.
For each configured ID, all captured payloads must match the sequence, including
count. These are expected test inputs, not fallback telemetry. No matching
physical reception means failure even if all Unity assertions pass.

The bridge defaults to loopback listeners, /dev/esp32_ahmed and
/tmp/calsol_can.sock. CLI options configure the device, socket, ports, and history
capacity. CALSOL_BIND changes network binding and should remain loopback for
SSH viewing. max_frames is 1..100000. Fanout queues cap at 4096 events, clients
at 64, raw input at 4096 bytes, HTTP headers at 8192 bytes. Trace logs rotate at
10 MiB with three backups; snapshots are atomic. Loss/disconnect counters appear
in health responses and snapshots. They must be considered in load acceptance.

The serial reader queues events; one background worker handles fanout, rotation,
and periodic snapshots. Slow clients are disconnected on partial/blocked writes.
Raw command responses mean serial acceptance, not confirmed CAN transmission.

## Reproduction

Run `python3 -m unittest discover -s github-action/lib -p 'test_*.py'`.
Run `./github-action/cal-test.sh lights_fw/test` in an exported ESP-IDF environment.
The runner locks the canonical device and shared bus, subscribes and checks
bridge readiness, fully flashes from generated metadata without reset, opens
the console, releases the download strap, then resets and captures execution.
Builds happen outside the hardware lock. Cancellation/failure writes an
infrastructure result; it never fabricates test assertions.

The API TX and RX mutexes are separate so a blocked receiver cannot starve TX.
Initialize from one startup owner before launching tasks. Shutdown refuses while
an API operation holds its mutex. Persistent TX storage survives timeout until
completion or driver deletion. Counters are cumulative until MCU reset.

Use the bench's tested ESP-IDF revision (currently v6.1 development toolchain;
exact revision appears in build logs). An SDK marked dirty is not a fully pinned
release. Record it rather than claiming reproducibility from a version label.
Production/test projects explicitly select esp32s3. Unit test self-test mode
is configured separately and never substitutes for physical expected_can checks.
