# Historical CAN reception investigation

Date: November 7, 2026. Outcome: no software regression identified that restores
cross-node reception; physical reception remains unverified/failed.

## Historical comparison

Compared roughly ten first-parent commits and the older restored firmware lab
sources at 961e788. Actual settings remain TX GPIO17, RX GPIO18, 500000 bit/s.
Some old comments say 1 Mbps, but the executable configuration says 500 kbps.

Inspected successful Actions runs 42318556434, 42325039593 and 42345219866.
Each pedal artifact reports seven passing tests and ten frames with no capture
source identifier; the lights artifacts report three passing tests and zero
frames. The historical parser also included DUT UART `[CAN_FRAME]` transmit
logs in the frame list. Those artifacts alone do not establish independent bus
reception; this does not prove that the bus never worked.

## Exact historical firmware trial

Reconstructed the flash layout from the pedals binary artifact in run
42318556434. Under the shared-bus lock, backed up both currently installed
firmware regions, installed the original debugger backup and the archived DUT
image, and checked them using the current independent-capture parser.

Result: all seven historical Unity tests passed; no independent physical CAN
frames were captured. Both current images were automatically restored afterward.
Rolling back this known successful-run binary did not restore reception today.

## Two-node electrical probe

Built temporary CAN-only firmware for both ESP32-S3s, using normal ACK-required
mode, TX17/RX18, and 500 kbps. Each node transmitted ten frames, then remained
listening. The opposite node was tested while that listener remained active.
GPIO edge interrupts measured actual pin activity. No UART diagnostic record
was published as physical CAN telemetry.

Observed on each node:

- All ten actual transmission attempts returned ESP_FAIL.
- Transmit error count rose from 0 to 80; ten bus errors were recorded.
- Own transmission produced approximately 179 TX-pin edges and 175 RX-pin edges.
  GPIO interrupts are diagnostic counters, not an exact wire waveform recorder.
- While the other node transmitted, the idle receiver's RX-edge count stayed
  unchanged. Neither node reported a CAN_receive result from its peer.

This establishes that both configured TX pins are active and local RX activity
exists, but the configured RX inputs do not observe the opposite transmitter.
Local RX activity could be transceiver feedback or a local loopback connection;
it does not by itself prove correct CAN_H/CAN_L interconnection or power wiring.
The observations point to inter-node wiring, polarity, reference, or hardware
mode/loopback rather than the dashboard decoder. Bench-side measurements are
required to distinguish those possibilities.

## Next physical checks

1. Trace CAN_H to CAN_H and CAN_L to CAN_L between the two transceiver boards.
2. Confirm a common ground/reference and the actual transceiver part/power pins.
3. Check for local TX-to-RX loopback jumpers or isolated bus segments.
4. With power removed, verify the intended termination (two 120-ohm end
   terminations give approximately 60 ohms across CAN_H/CAN_L).
5. Repeat the independent receive test after correcting/confirming the wiring.
   A green Unity transmit assertion is not the acceptance condition.

## Evidence and restoration

Raw trial results remain on stolerpi under /opt/calsol-verify-20261107:
historical-baseline-results.json, historical-baseline-trace.jsonl,
electrical-probe-results.json and electrical-probe.log. Current-image backups
are in rollback/historical-current-debugger.bin and historical-current-dut.bin.
The temporary probe project is .can-probe; its source is diagnostic-only.

Copies of result JSON are in the local ignored staging directory. Raw flash
backups remain on the Pi and were not published. Both normal firmware images
were restored and can-bridge-daemon.service was confirmed active, with its USB
connection healthy and zero physical receptions.
