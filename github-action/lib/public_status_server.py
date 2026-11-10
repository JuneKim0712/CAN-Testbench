"""Read-only public relay; no USB ownership and no bridge command forwarding."""
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from publish_snapshot import snapshot

cache = {"serial_connected": False, "mode": "hardware", "bridge_available": False, "frames": [], "updated_at": None}


def refresh():
    global cache
    while True:
        payload = snapshot()
        payload["feed_type"] = "live_read_only"
        payload["dut_connected"] = Path("/dev/esp32_johnathan").exists()
        payload["dut_status"] = ("unavailable" if not payload["dut_connected"] else
                                 "in_use" if payload["dut_usage"] == "in_use" else
                                 "idle" if payload["dut_usage"] == "idle" else "unknown")
        try:
            simulated = json.loads(Path("/var/lib/calsol-emulation/heartbeat.json").read_text())
            age = datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(simulated["updated_at"]).timestamp()
            if 0 <= age < 20:
                payload["frames"].extend(f for f in simulated.get("frames", [])[-100:] if f.get("source") == "emulated")
        except (OSError, ValueError, KeyError, TypeError):
            pass
        cache = payload
        time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/health", "/api/frames"):
            self.send_error(404)
            return
        body = dict(cache)
        if path == "/health":
            body.pop("frames", None)
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=refresh, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8767), Handler).serve_forever()
