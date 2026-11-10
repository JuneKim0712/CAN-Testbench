# CAN testbench implementation and verification plan

Date: November 7, 2026

Status: software implemented and under end-to-end verification. Physical CAN
acceptance is failing and must not be represented as complete. See
VERIFICATION_PROGRESS.md for measured results and remaining gates.

## Objective

Make every reported hardware pass and displayed physical CAN frame traceable to
real execution and reception. Keep the existing ESP32, Python, shell, Unity, and
static frontend architecture. Implement the stages below as separate reviewable
changes; complete each stage's checks before progressing.

Production telemetry must never contain fabricated captures. Deterministic
fixtures and spoofed inputs are permitted in isolated software tests, clearly
separated from physical reception evidence.

## Stage 1: Configuration and event contract

Files: bridge, Unity parser, reporter, Pages compiler, configuration documentation.

- Define a versioned event contract: session ID, sequence number, timestamp,
  interface, numeric CAN ID, extended/RTR flags, DLC, payload, and event origin.
- Separate physical RX, injection request, TX completion, and diagnostics.
- Preserve repeated identical frames; deduplicate only by session and sequence.
- Validate bench configuration and document precedence of CLI, manifest, defaults.
- Verify Pi model, USB interfaces, debugger firmware location/version, and wiring.
- Document legacy wire limitations: it carries only 12 ID bits and no frame flags.
  Initially reject unsupported formats. If extended/RTR support is required,
  implement a versioned firmware/host protocol together, with explicit negotiation
  and rollback; never silently reinterpret legacy packets.

Acceptance: a physical event retains identity and contents across capture,
artifacts, and rendering. Unsupported formats fail explicitly.

## Stage 2: CAN driver reliability

Files: components/can_driver; subsystem driver tests.

- Fix asynchronous TX ownership on completion timeout. Retain both frame and
  payload in owned storage until confirmed completion or cancellation; never
  release storage merely because the caller's wait expired.
- Define concurrency and shutdown rules for send, receive, init, and deinit.
- Make self-test/ACK behavior explicit configuration for each test mode.
- Validate arguments, ID bounds, DLC, and frame flags consistently.
- Document overflow/error counter lifetime and synchronization.
- Introduce explicit zero-length packet construction without silently changing
  the legacy builder's zero-means-eight behavior.
- Avoid new task frameworks or asynchronous APIs unless ownership requires them.

Acceptance: concurrent TX, timeout, and shutdown checks show no corrupted frames,
use-after-return, deadlocks, or unreported overflow.

## Stage 3: Bridge ownership and bounded operation

Files: can_bridge_daemon.py, injection CLI, systemd service, cal-test.sh.

- Make systemd the only permanent bridge owner. Remove process/port killing from CI.
- Fail injection when disconnected; reject invalid IDs and oversized payloads.
- Distinguish serial request acceptance from confirmed CAN transmission/reception.
- Bound serial input, client commands, outgoing queues, and client count.
- Keep slow clients and disk snapshot writes off the serial capture path.
- Rotate logs; expose connection state, malformed packets, dropped events, and gaps.
- Use monotonic clocks for elapsed deadlines and wall time for display.
- Restrict injection access using Unix socket permissions and local binding;
  expose remote viewing through a configured secure endpoint.

Acceptance: disconnected injection fails; slow viewers cannot silently stall
capture; buffers and disk usage remain bounded; reconnects create visible gaps.

## Stage 4: Deterministic runner and flashing

Files: cal-test.sh, cal-flash.sh, Unity parser, GitHub workflows.

- Retain canonical-device locking; add shared-bus ownership for physical tests.
- Build outside hardware locks, with isolated logs and artifacts per run.
- Sequence execution: lock, verify bridge/device readiness, subscribe and confirm
  capture readiness, flash/hold or handshake DUT, run suite, finalize capture,
  persist artifacts, release locks.
- Associate the capture and suite with one run identifier; reject stale results.
- Use app-only flashing only with verified compatible partition/bootloader state.
  Use build metadata for offsets; full-flash when compatibility is unknown.
- Fail if a specified board is missing instead of silently selecting another DUT.
- Guarantee cleanup and diagnostic artifacts after failure or cancellation.
- Correct push change detection to cover the event's full commit range.

Acceptance: startup traffic is captured, aliases cannot bypass locking, concurrent
bus tests cannot interfere, and partition changes use the correct flash procedure.

## Stage 5: Tests and authoritative reports

Files: subsystem tests, templates/can-unit-test, Unity parser, Pages compiler,
static checker and reporting workflows.

- Link tests to production handlers; retain direct-in-C injection examples.
- Keep software handler tests distinct from physical TX, RX, and request/reply tests.
- Use bounded deadlines, startup handshakes, and cleanup after failed assertions.
- Require a valid completed Unity summary and consistent test counts for success.
- Store exact file/line data, durations, suite status, and infrastructure status.
- Distinguish build failure, timeout, crash, assertion failure, and capture failure.
- Use one authoritative trace artifact; avoid ingesting embedded and JSONL copies.
- Associate traces using run metadata, never subsystem-name guesses.
- Preserve event provenance and gaps through report generation.
- Treat missing static-analysis execution as unknown/error, not passed.
- Require current-run artifacts for publication; fail visibly on missing downloads.

Acceptance: partial success followed by timeout stays failed; no duplicate or
cross-subsystem frames; missing evidence cannot produce a hardware pass.

## Stage 6: Accurate and efficient telemetry UI

Files: web/index.html, deployment documentation and workflow.

- Label live, stale, historical snapshot, and disconnected states accurately.
- Use a secure live Pi endpoint for remote streaming. GitHub Pages hosts deployed
  snapshots; polling Pages does not fetch continuously changing files on the Pi.
- Batch rendering; ingest incrementally by event identity instead of scanning
  the complete history for every frame.
- Bound rendered rows; use pagination or actual windowed rendering if required.
- Preserve chronology and repeated frames; show capture gaps and last-update age.
- Decode only against a verified protocol/DBC; preserve unknown raw messages.
- Avoid adding frontend dependencies unless measured behavior justifies them.

Acceptance: stale snapshots never appear live, repeated frames are retained, and
the UI stays responsive at the agreed measured bench rate.

## Verification gates

1. Software regression: exercise codec boundary IDs/DLCs, embedded zeros,
   truncation, checksum errors, invalid flags, oversized input, both legacy and
   versioned behavior if implemented. Test summaries with 0/1/10/100 failures,
   missing summaries, crash, mismatched counts, and partial output. Test duplicate
   artifacts, run isolation, disconnected injection, and slow clients.
   Pass: invalid inputs fail explicitly; no false passes or duplicated events.
2. Build/runner integration: clean builds with pinned ESP-IDF; copy and build the
   developer template; contend for one device through aliases; cancel during
   build, flashing, and test execution; change partition layout.
   Pass: correct exit status, diagnostics, lock release, and flashing selection.
3. Physical TX: DUT sends ten sequence-tagged frames on an isolated bench.
   Independently compare Node 1 captures for ID, DLC, payload, count, and order.
   Pass: all ten appear exactly once as physical RX events, not TX logs.
4. Physical RX: peer waits for DUT readiness, injects a valid command, and DUT
   asserts production state change. Repeat with wrong ID/DLC/value/flags.
   Pass: valid command changes state; rejected commands leave state unchanged.
5. Fault/recovery: disconnect debugger USB, restart bridge, remove CAN peer or
   transceiver power, interrupt viewing network, and exhaust TX wait deadline.
   Pass: failures and gaps are explicit, no fabricated frames appear, recovery is
   observable, and retained TX storage remains safe.
6. Load/soak: first record an agreed operating rate and soak duration. Measure
   sequence gaps, queue overflows, memory, disk growth, and latency with multiple
   viewers and a slow client. Instrument source-side drops where possible.
   Pass: zero unexplained loss at the agreed rate; overload is counted and shown;
   memory and rotated storage remain within configured bounds.
7. End-to-end CI: run a successful HIL job, an intentional assertion failure, and
   a timeout. Compare raw capture, JSONL, test report, and dashboard by event ID.
   Pass: statuses and physical events agree across all outputs; historical data
   is labeled correctly; build/capture/infrastructure failures cannot appear green.

For physical delivery evidence, use an independent receiving controller where
possible. A software request acknowledgment or DUT TX return code alone is not
proof of bus reception. Declare listen-only versus ACK-capable peer modes in the
test setup; a listen-only sniffer cannot ACK a lone normal-mode transmitter.

## Completion evidence and rollout

- Save firmware/host commit IDs, pinned tools, bench configuration, hardware
  inventory, commands, raw logs, traces, counters, test results, and browser checks.
- Mark each verification gate passed, failed, or not run, with its evidence path.
- Keep the full raw trace even when the UI displays a bounded subset.
- Run stages on the bench before deployment; preserve the previous known-good
  service and firmware artifacts for rollback.
- Call the implementation verified only when all required gates pass. Report
  unavailable hardware checks as pending rather than inferring success.

## References

- Espressif TWAI modes and asynchronous buffer ownership:
  https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/twai.html
- GitHub Pages static hosting:
  https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- TI TCAN332 electrical specifications (use actual board/datasheet values rather
  than generic 5 V CAN bias assumptions): https://www.ti.com/lit/ds/symlink/tcan332.pdf
