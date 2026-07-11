#!/usr/bin/env python3
"""
esp-fleet-bot — Slack-driven ESP board discovery + hello_world flash check.

Commands (mention the bot in a channel it's been invited to):
    boards              list every ESP board plugged into this machine
    flash <port>|all    build + flash + verify hello_world
    prebuild <target>   warm the build cache, e.g. `prebuild esp32s3`
    status              IDF version, cached targets, uptime

Env:
    SLACK_BOT_TOKEN=xoxb-...   scopes: app_mentions:read, chat:write
    SLACK_APP_TOKEN=xapp-...   app-level token, scope: connections:write
    IDF_PATH=/home/pi/esp/esp-idf
    FLEET_WORKSPACE=~/.cache/esp-fleet-bot   (optional; build cache location)

Local check (no Slack):  python bot.py boards
"""

import functools
import getpass
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

KNOWN_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}   # CP210x, CH340, FTDI, Espressif native USB

# Deliberately OUTSIDE the git checkout. A `git clean -xdf` after a bad pull
# would otherwise delete a build that took six minutes on a Pi.
WORKSPACE = Path(
    os.environ.get("FLEET_WORKSPACE", "~/.cache/esp-fleet-bot")
).expanduser().resolve()

BUILD_LOCK = threading.Lock()                    # ESP-IDF builds clobber each other
BUILD_TIMEOUT = 2400                             # a Pi is slow; be generous
STARTED = time.time()

SERVICE_USER = getpass.getuser()     # who the bot itself runs as
CONFIRM_TTL = 120                    # seconds a confirmation code stays valid
PENDING: dict[str, dict] = {}        # code -> pending flash job
PENDING_LOCK = threading.Lock()

CHIP_RE = re.compile(r"Chip (?:is|type):\s*(ESP32[\w\-]*)", re.I)
MAC_RE = re.compile(r"MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", re.I)


# ---------- ESP-IDF environment ----------

@functools.lru_cache(maxsize=1)
def idf_env() -> dict:
    """Source export.sh ONCE and capture the resulting environment.

    systemd gives the service a bare PATH and does not read your shell profile,
    so idf.py and esptool.py are not findable by default. Re-sourcing export.sh
    per subprocess would also cost seconds every call. Do it once, reuse the env.
    """
    idf_path = os.environ.get("IDF_PATH")
    if not idf_path:
        sys.exit("IDF_PATH is not set.")
    export = Path(idf_path) / "export.sh"
    if not export.exists():
        sys.exit(f"No export.sh at {export}")

    r = subprocess.run(
        ["bash", "-c", f'source "{export}" >/dev/null 2>&1 && env -0'],
        capture_output=True, timeout=180,
    )
    if r.returncode:
        sys.exit(f"export.sh failed:\n{r.stderr.decode()[-500:]}")

    env = {}
    for entry in r.stdout.split(b"\0"):
        if b"=" in entry:
            k, v = entry.split(b"=", 1)
            env[k.decode()] = v.decode(errors="replace")
    env["IDF_CCACHE_ENABLE"] = "1"   # makes rebuilds of a target much faster
    return env


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 300):
    return subprocess.run(cmd, cwd=cwd, env=idf_env(), capture_output=True,
                          text=True, timeout=timeout)


# ---------- hardware ----------

def scan() -> list[dict]:
    """Every ESP-looking port, identified by chip + MAC."""
    boards = []
    for p in list_ports.comports():
        if p.vid not in KNOWN_VIDS:
            continue
        b = {"port": p.device, "desc": p.description, "chip": None, "mac": None, "error": None}
        try:
            r = run(["esptool.py", "--port", p.device, "--chip", "auto",
                     "--connect-attempts", "2", "read_mac"], timeout=30)
            out = r.stdout + r.stderr
            chip, mac = CHIP_RE.search(out), MAC_RE.search(out)
            if mac:
                b["chip"] = chip.group(1).upper() if chip else "ESP32"
                b["mac"] = mac.group(1).lower()
            else:
                b["error"] = (out.strip().splitlines() or ["no response"])[-1][:120]
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            b["error"] = str(e)[:120]
        boards.append(b)
    return boards


def target_of(board: dict) -> str:
    return board["chip"].lower().replace("-", "")     # ESP32-S3 -> esp32s3


def cached_targets() -> list[str]:
    if not WORKSPACE.exists():
        return []
    return sorted(
        d.name.removeprefix("hello_world_")
        for d in WORKSPACE.iterdir()
        if (d / "build" / "hello_world.bin").exists()
    )


def ensure_built(target: str, report) -> tuple[bool, str]:
    """Build hello_world for `target`, reusing the cache if present."""
    proj = WORKSPACE / f"hello_world_{target}"
    if (proj / "build" / "hello_world.bin").exists():
        return True, f"using cached `{target}` build"

    with BUILD_LOCK:
        if (proj / "build" / "hello_world.bin").exists():   # won the race while waiting
            return True, f"using cached `{target}` build"

        report(f":hammer: Building hello_world for `{target}`. "
               f"First build on a Pi takes several minutes.")

        src = Path(os.environ["IDF_PATH"]) / "examples/get-started/hello_world"
        if not src.exists():
            return False, f"hello_world example not found at `{src}`"

        shutil.rmtree(proj, ignore_errors=True)
        proj.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, proj)   # own copy per target: sdkconfigs never collide

        for args, t in ((["set-target", target], 300), (["build"], BUILD_TIMEOUT)):
            r = run(["idf.py", *args], cwd=proj, timeout=t)
            if r.returncode:
                shutil.rmtree(proj, ignore_errors=True)   # never cache a broken tree
                tail = (r.stdout + r.stderr)[-700:]
                return False, f"`idf.py {' '.join(args)}` failed:\n```{tail}```"

    return True, f"built hello_world for `{target}`"


def verify(port: str, expect="Hello world!", timeout=20) -> tuple[bool, str]:
    """Reset the board and watch the console for hello_world's greeting."""
    try:
        with serial.Serial(port, 115200, timeout=1) as ser:
            ser.setDTR(False)      # IO0 high -> boot the app, not the bootloader
            ser.setRTS(True)       # EN low  -> hold in reset
            time.sleep(0.1)
            ser.setRTS(False)      # release
            ser.reset_input_buffer()

            buf, deadline = "", time.time() + timeout
            while time.time() < deadline:
                buf += ser.read(256).decode("utf-8", "replace")
                if expect in buf:
                    return True, f"flashed, saw {expect!r}"
            return False, f"flashed, but never saw {expect!r}:\n```{buf[-400:] or '(silence)'}```"
    except serial.SerialException as e:
        return False, f"serial error: {e}"


def flash_hello_world(board: dict, report) -> tuple[bool, str]:
    ok, msg = ensure_built(target_of(board), report)
    if not ok:
        return False, msg
    report(f":zap: Flashing `{board['port']}`…")

    r = run(["idf.py", "-p", board["port"], "-b", "460800", "flash"],
            cwd=WORKSPACE / f"hello_world_{target_of(board)}", timeout=600)
    if r.returncode:
        return False, f"flash failed:\n```{(r.stdout + r.stderr)[-700:]}```"

    return verify(board["port"])


# ---------- who is on the box ----------

def logged_in_users() -> dict[str, list[str]]:
    """Current SSH/console sessions, grouped by user. Reads /run/utmp via `who`.

    Won't see detached tmux sessions or anything running as a service — it only
    knows about login sessions.
    """
    try:
        r = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}

    sessions: dict[str, list[str]] = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        user, tty = parts[0], parts[1]
        host = parts[-1].strip("()") if parts[-1].startswith("(") else "console"
        sessions.setdefault(user, []).append(f"{tty} from {host}")
    return sessions


def others_online() -> set[str]:
    """Logged-in humans other than the account the bot runs as."""
    return {u for u in logged_in_users() if u != SERVICE_USER}


# ---------- slack ----------

def run_bot():
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    @app.event("app_mention")
    def on_mention(event, say):
        words = re.sub(r"<@[A-Z0-9]+>", "", event["text"]).strip().split()
        cmd = words[0].lower() if words else "help"
        arg = words[1] if len(words) > 1 else None
        ts = event.get("thread_ts") or event["ts"]
        user = event.get("user", "?")
        report = lambda text: say(text=text, thread_ts=ts)

        # Every command runs off-thread: a scan can take 30s/board and a cold
        # build takes minutes. Blocking here would stall the Socket Mode listener.
        def work():
            try:
                handle(cmd, arg, report, user)
            except Exception as e:
                report(f":x: {type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    def do_flash(boards, report):
        for b in boards:
            ok, msg = flash_hello_world(b, report)
            report(f"{':white_check_mark:' if ok else ':x:'} `{b['port']}` — {msg}")

    def handle(cmd, arg, report, user):
        if cmd in ("boards", "list"):
            boards = scan()
            if not boards:
                report(":warning: No ESP boards found on any USB port.")
                return
            report("\n".join(
                f":white_check_mark: `{b['port']}`  *{b['chip']}*  `{b['mac']}`" if b["mac"]
                else f":x: `{b['port']}`  {b['desc']} — {b['error']}"
                for b in boards
            ))

        elif cmd == "flash":
            if not arg:
                report("Usage: `flash <port>` or `flash all`")
                return

            # Report who's on the box BEFORE doing anything destructive.
            others = others_online()
            if others:
                report(":warning: Logged into the Pi right now: " +
                       ", ".join(f"`{u}`" for u in sorted(others)))
            else:
                report(":zzz: Nobody else is logged into the Pi.")

            boards = [b for b in scan() if b["mac"] and (arg == "all" or b["port"] == arg)]
            if not boards:
                report(f":x: No responding board matches `{arg}`.")
                return

            if not others:
                do_flash(boards, report)
                return

            # Someone else is on the box: park the job behind a confirmation code.
            code = secrets.token_hex(2).upper()
            with PENDING_LOCK:
                for k, v in list(PENDING.items()):          # prune stale codes
                    if time.time() > v["expires"]:
                        del PENDING[k]
                PENDING[code] = {"boards": boards, "user": user,
                                 "expires": time.time() + CONFIRM_TTL}

            names = ", ".join(f"`{b['port']}`" for b in boards)
            report(f"This will flash and reset {names}.\n"
                   f"Reply `confirm {code}` within {CONFIRM_TTL}s to go ahead.")

        elif cmd == "confirm":
            if not arg:
                report("Usage: `confirm <code>`")
                return
            code = arg.upper()
            with PENDING_LOCK:
                job = PENDING.pop(code, None)
                if job and job["user"] != user:
                    PENDING[code] = job                     # not yours; put it back
                    job = None
                    report(":x: Only whoever asked for the flash can confirm it.")
                    return
            if not job:
                report(f":x: No pending job `{code}`. Expired, already used, or mistyped.")
                return
            if time.time() > job["expires"]:
                report(f":hourglass: `{code}` expired. Run the flash command again.")
                return
            do_flash(job["boards"], report)

        elif cmd == "prebuild":
            if not arg:
                report("Usage: `prebuild esp32s3`")
                return
            ok, msg = ensure_built(arg, report)
            report(f"{':white_check_mark:' if ok else ':x:'} {msg}")

        elif cmd == "status":
            idf = idf_env().get("IDF_VERSION") or "unknown"
            rev = git_rev()
            up = int(time.time() - STARTED)
            cached = ", ".join(f"`{t}`" for t in cached_targets()) or "_none_"
            report(f"IDF `{idf}` · code `{rev}` · up {up // 3600}h{up % 3600 // 60}m "
                   f"· cached builds: {cached}")

        elif cmd == "who":
            sessions = logged_in_users()
            if not sessions:
                report(":zzz: Nobody is logged into the Pi.")
                return
            report("\n".join(
                f":bust_in_silhouette: *{u}* — {', '.join(ttys)}"
                for u, ttys in sorted(sessions.items())
            ))

        else:
            report("`boards` · `flash <port>|all` · `confirm <code>` · "
                   "`prebuild <target>` · `who` · `status`")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    idf_env()   # fail loudly at startup, not on the first Slack command
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


def git_rev() -> str:
    """Short SHA of the checkout this file lives in. Tells you what the Pi is running."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=Path(__file__).parent, capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "boards":
        for b in scan():
            print(f"{b['port']:<18} {b['chip'] or 'ERROR':<10} {b['mac'] or b['error']}")
    else:
        run_bot()