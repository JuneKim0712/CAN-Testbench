# Reproducible USB CAN debugger

ESP32-S3, shared CAN driver, 500 kbps. GPIO defaults come from CAN.h (TX17/RX18).
Normal ACK-checking mode is the default. Build with ESP-IDF:

```bash
idf.py -C debugger_fw build
idf.py -C debugger_fw -p /dev/esp32_ahmed flash
```

Stop the bridge service before flashing or opening the debugger serial device;
restart it afterward. Preserve the installed firmware before replacing it.

The stream uses the existing COBS/checksum protocol for standard data frames
only. Extended and RTR frames are excluded because legacy framing cannot
represent them faithfully. Incoming validated packets request actual bus TX;
they do not echo into the physical capture stream. USB request acceptance is
not a CAN success acknowledgment.

For controlled diagnostics with the daemon stopped, send bytes `02 F1 00` over
USB. Decode the COBS response. Its bytes are: `F1 F0`, version 1, controller
state, TX error count low byte, RX error count low byte, RX pin level, TX pin
level, cumulative bus-error count low byte. This is diagnostic data, not a CAN
frame; the impossible legacy DLC 15 makes normal capture parsers reject it.
Counters can wrap; use this query for short before/after checks only.

USB output has a bounded wait; this firmware does not promise lossless capture
at arbitrary bus load. Load testing and drop instrumentation remain required.
