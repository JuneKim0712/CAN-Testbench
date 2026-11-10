"""Publish a bounded read-only bench snapshot using an Actions job token."""
import json
import os
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def read_url(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def dut_usage(lock_dir="/tmp/calsol_locks"):
    """Observe runner ownership without changing lock files or taking ownership."""
    try:
        import fcntl
        directory = Path(lock_dir)
        if not directory.is_dir():
            return "unknown"
        files = list(directory.glob("hw*.lock")) + [directory / "bus.lock", directory / "esp32_johnathan.lock"]
        for path in files:
            try:
                with path.open("r") as handle:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return "in_use"
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except FileNotFoundError:
                continue
        return "idle"
    except (OSError, ImportError):
        return "unknown"


def snapshot():
    now = datetime.now(timezone.utc).isoformat()
    try:
        health = read_url("http://127.0.0.1:8765/health")
        data = read_url("http://127.0.0.1:8765/api/frames")
        frames = [{k: f[k] for k in ("event", "session_id", "sequence", "timestamp", "time", "id", "id_int", "id_hex", "dlc", "raw", "data", "source", "direction") if k in f}
                  for f in data.get("frames", [])[-100:]
                  if f.get("source") == "physical_bus" and f.get("direction") == "rx"]
        return {"updated_at": now, "feed_type": "public_snapshot", "dut_usage": dut_usage(), "bridge_available": True,
                "serial_connected": bool(health.get("serial_connected")), "mode": health.get("mode"),
                "last_rx_at": health.get("last_rx_at"), "total_rx": health.get("total_rx", 0), "frames": frames}
    except (OSError, ValueError):
        return {"updated_at": now, "feed_type": "public_snapshot", "dut_usage": dut_usage(), "bridge_available": False,
                "serial_connected": False, "frames": []}


def publish(payload):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    branch = "telemetry-feed"
    root = "https://api.github.com/repos/" + repo
    def api(path, data=None):
        request = urllib.request.Request(root + path, data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "CalSol-snapshot"},
            method="PUT" if path.startswith("/contents/") and data is not None else None)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    try:
        api("/git/ref/heads/" + branch)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        head = api("/git/ref/heads/main")["object"]["sha"]
        api("/git/refs", {"ref": "refs/heads/" + branch, "sha": head})
    path = "/contents/public-telemetry.json"
    body = {"message": "Update public bench snapshot", "branch": branch,
            "content": base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()}
    try:
        body["sha"] = api(path + "?ref=" + branch)["sha"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    api(path, body)
    print("Published snapshot; physical frames:", sum(f.get("source") == "physical_bus" for f in payload["frames"]), "emulated:", sum(f.get("source") == "emulated" for f in payload["frames"]))


if __name__ == "__main__":
    payload = snapshot()
    try:
        emulated = json.loads(Path("/var/lib/calsol-emulation/heartbeat.json").read_text())
        if abs(datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(emulated["updated_at"]).timestamp()) < 20:
            payload["frames"].extend(f for f in emulated.get("frames", [])[-100:]
                                     if f.get("source") == "emulated" and f.get("event") == "emulated_frame")
            payload["emulated_interval_seconds"] = 5
    except (OSError, ValueError, KeyError, TypeError):
        pass
    publish(payload)
