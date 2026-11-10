"""Software-only CAN-shaped heartbeat. Never opens a CAN or serial device."""
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def frame(session, sequence):
    now = datetime.now(timezone.utc)
    payload = sequence.to_bytes(4, "big").hex().upper()
    return {"event": "emulated_frame", "source": "emulated", "direction": "simulated",
            "session_id": session, "sequence": sequence, "timestamp": now.timestamp(),
            "time": now.strftime("%H:%M:%S"), "id": "0x700", "dlc": 4,
            "data": payload, "raw": " ".join(payload[i:i+2] for i in range(0, 8, 2))}


def main():
    path = Path(os.environ.get("HEARTBEAT_OUTPUT", "/var/lib/calsol-heartbeat/heartbeat.json"))
    session = "emulated-" + uuid.uuid4().hex
    frames = deque(maxlen=100)
    sequence = 0
    deadline = time.monotonic()
    while True:
        sequence = (sequence + 1) % (2**32)
        frames.append(frame(session, sequence))
        content = {"updated_at": datetime.now(timezone.utc).isoformat(), "interval_seconds": 5, "frames": list(frames)}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(content), encoding="utf-8")
        temporary.replace(path)
        deadline += 5
        time.sleep(max(0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
