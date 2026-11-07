# Implementation and bench verification progress

## Latest implementation checkpoint

- Software implementation is on `codex/reliable-can-testbench` in the user fork.
- Both production firmwares now build for ESP32-S3; both subsystem test projects
  and a fresh copied developer template also built on the Pi.
- Twenty-three software regressions pass on Linux, including actual Unix-socket
  command validation, slow-client disconnects, overload accounting, snapshots,
  stale-report rejection, manifest validation, and contradictory Unity results.
- The capture-first coordinator was tested on the DUT. Releasing DTR before
  native-USB hard reset is required to leave the bootloader; this is implemented.
- Canonical device alias locking, cancellation, lock release, and failure-artifact
  persistence were verified. No synthetic assertions were added to those artifacts.
- The copied template's three logic tests passed on silicon. Its optional
  physical injection test failed as expected with the unresolved CAN path.
- GitHub Actions run 42359195024 passed cloud static analysis and discovery;
  both hardware jobs failed because required physical frames were absent. The
  report job succeeded and uploaded telemetry artifacts. This is a genuine
  hardware acceptance failure, not a green CI run.
- Bridge and private viewer are deployed independently of the CI checkout under
  `/opt/calsol/releases/2594822c77c9eb1182aa2722aa15dc1db39d8ca3`.
  Persistent telemetry is under /var/lib/calsol and rotated logs /var/log/calsol.
- The loopback viewer was browser-verified through SSH. Tailscale Serve requires
  account access unavailable in this session, so PRIVATE_VIEWER.md provides
  encrypted SSH forwarding without publishing a network listener.
- Physical TX/RX and physical-load acceptance remain failed/blocked. USB inventory
  found no alternate CAN interface or lab instrument that could confirm or change
  transceiver power remotely. Older notes below describe intermediate states.

The whole plan is not verified until independent physical reception and the
remaining physical fault/load gates pass. Software fixture results cannot close
those gates.

## Final additional gates

- Changed partition layout: passed. The fresh template was fully flashed from
  generated metadata with factory app offset 0x20000 and all three logic tests
  executed successfully. This exercises the old fixed-offset failure scenario.
- Debugger USB recovery: passed. Only the identified debugger CDC interface was
  temporarily unbound/rebound under the shared-bus lock. Health reported the
  disconnect, recorded its counter, and recovered automatically. Capture count
  stayed zero throughout; no fallback frames were fabricated.
- Slow consumer and duplicate daemon: passed against the deployed code. A slow
  Unix-socket client is disconnected; a second daemon cannot unlink the live
  socket. A stale staging module was detected during test setup and excluded;
  results above are from the deployed release module.
- Counter synchronization: final ISR/task critical sections compiled on ESP32-S3.
- Truncated Unity summaries and suites containing only ignored tests cannot pass.
- Final debugger binary SHA-256:
  `6aab1716b144ebaaa47a149b39e8b24e3089736ad639ef47ca84f6c150db0ff3`.
  A startup delimiter prevents ROM boot text from contaminating the first COBS
  packet. The image was built/flashed under the shared-bus lock.
- CI now runs software regressions, including temporary Unix-socket transport
  tests, before allocating hardware. Workflow token scope permits read-only job
  inspection and failure logs use only the current run's directory.

Physical transceiver power/wiring, physical TX/RX delivery, real bus-load/soak,
and physical bus fault recovery cannot be marked passed while neither node
receives the other's traffic. They require bench-side correction/confirmation.

November 7, 2026. This is an intermediate checkpoint, not release approval.

## Observed bench

- SSH host: stolerpi-admin; Raspberry Pi 5 Model B Rev 1.1.
- Both ESP32 USB symlinks exist. Debugger chip identification succeeded.
- Existing service: can-bridge-daemon.service, running as jkim.
- Original runner checkout has pre-existing modifications and was preserved.
- Isolated source/build directory: /opt/calsol-verify-20261107.
- Service override: /etc/systemd/system/can-bridge-daemon.service.d/90-verification.conf.
  It runs the staged bridge. Prior unit text is saved under staging's rollback/.
- Password was supplied only as redirected stdin to sudo, never opened for inspection.

## Completed checks

- Ten local bridge/parser regression tests pass.
- Five bridge tests pass on the Pi.
- Lights test firmware with persistent TX storage built successfully on the Pi.
- DUT flashed and all four Unity tests passed on three physical acceptance attempts.
- Independent subscriber captured zero physical heartbeat frames on all attempts.
- The combined hardware acceptance command correctly exited nonzero. The latest
  report stores unity_passed=true, physical_rx_passed=false, passed=false.
- Debugger reset and service restart did not restore physical capture.

Evidence is retained remotely in verification-results/ and copied locally into
ignored staging/. No test fixture traffic was published as physical telemetry.

## Important constraints and pending work

- Physical CAN power/wiring and actual installed debugger firmware still require
  confirmation. The debugger source inspected under /home/jkim contains only a
  CAN-to-USB forwarding loop; no USB-to-CAN injection path was found there.
- Physical RX/spoofing is not verified. No successful end-to-end CAN claim is made.
- Latest Kconfig mode selection, template/pedals clean builds, concurrent TX and
  timeout stress checks remain pending. Do not treat the lights build as proof
  of those later additions.
- Runner capture startup handshake, complete bounded fanout/storage architecture,
  full report metadata/config unification, deployment/CI failure tests, remote
  secure live endpoint, UI browser validation, and load/soak gates remain pending.
- GitHub Actions and Pages changes are local and have not been pushed or deployed.
- Legacy binary capture cannot recover extended/RTR flags; a protocol/firmware
  upgrade is needed before claiming complete CAN 2.0B capture support.

## Resume and rollback

### Subsequent diagnosis

- Backed up the debugger's configured first 2 MiB at
  `/opt/calsol-verify-20261107/rollback/debugger-before.bin`.
- Installed app matched the older build/build_dev binaries, not build_debugger.
  This image difference alone was not established as the cause.
- Built and installed the repository's new `debugger_fw` with explicit native
  USB initialization, standard data-frame capture, injection, and a separate
  controller-status query. Original service is restored after exclusive checks.
- Found and fixed a further driver bug: `twai_node_transmit_wait_all_done()`
  establishes queue completion, not successful transmission. CAN_send now
  checks the TX-done event's `is_tx_success` flag.
- With self-test disabled, DUT test now correctly reports 3 passes and 1 CAN
  transmission failure; independent physical capture remains empty.
- Reverse-direction debugger transmission increased TX errors from 0 to 8 and
  bus errors from 0 to 1. Controller remained active; RX errors stayed 0.
- Both USB devices and the debugger command/response path work. This does not
  establish transceiver power, physical pin mapping, or differential connectivity.
  Physical-layer/configuration investigation remains necessary; no claim is
  made that the bus does not exist.

The DUT currently has ACK-required lights test firmware and debugger_fw is
installed on Node 1. The daemon is active. Restore the saved flash region if
reverting the debugger; do not confuse that backup with a complete 16 MiB dump.

1. Confirm transceiver power and CAN_H/CAN_L wiring; identify the flashed debugger
   image against saved binaries/source before replacing it.
2. Re-run github-action/verify_physical_tx.py on the Pi with the ESP-IDF environment.
3. Require independent tokens 1..10 before advancing to physical RX and load tests.
4. Finish the remaining gates in IMPLEMENTATION_AND_VERIFICATION_PLAN.md.

To revert the service staging, remove only the named 90-verification.conf override,
run systemctl daemon-reload, and restart can-bridge-daemon.service. The original
unit and original checkout were not overwritten. DUT currently runs the lights
test image; restore the chosen prior DUT image before returning it to other work.
