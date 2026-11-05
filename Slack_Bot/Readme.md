# Slack_Bot

Slack-driven ESP board discovery + `hello_world` flash check, running on the bench Pi.

## Commands

| Slack | Does |
|---|---|
| `@bot boards` | List every ESP board plugged into the Pi (chip + MAC) |
| `@bot flash <port>` | Build + flash + verify `hello_world` |
| `@bot flash all` | Same, on every board |
| `@bot confirm <code>` | Approve a flash that was gated because someone else is on the Pi |
| `@bot who` | Who's logged into the Pi |
| `@bot prebuild esp32s3` | Warm the build cache |
| `@bot status` | IDF version, git SHA, uptime, cached builds |

If anyone else is SSH'd in, `flash` reports it and waits for a `confirm <code>` (120s expiry, requester only).

## Service control

```bash
sudo systemctl restart esp-fleet-bot     # pick up code changes
sudo systemctl stop esp-fleet-bot        # turn off
sudo systemctl start esp-fleet-bot       # turn on
sudo systemctl status esp-fleet-bot      # alive?
sudo journalctl -u esp-fleet-bot -f      # live logs
```

Edited the `.service` file? `sudo systemctl daemon-reload` first.

## Files

| File | What |
|---|---|
| `bot.py` | Everything. Scan, build, flash, verify, Slack handlers. |
| `esp-fleet-bot.service` | systemd unit **template**. The live copy is `/etc/systemd/system/`. |
| `requirements.txt` | `slack-bolt`, `pyserial`. |

Not in the repo, on purpose: tokens (`/etc/esp-fleet-bot.env`), build cache (`~/.cache/esp-fleet-bot`), venv (`.venv/`).

## Update the Pi

```bash
cd ~/CAN_TestBench && git pull
sudo systemctl restart esp-fleet-bot
```

Check with `@bot status` — it prints the git SHA it's running.

## Brand new setup

**1. Slack app** (`api.slack.com/apps` → From scratch)
- *Socket Mode* → on → generate app token, scope `connections:write` → `xapp-...`
- *OAuth & Permissions* → bot scopes `app_mentions:read`, `chat:write`
- *Event Subscriptions* → on → subscribe to bot event `app_mention`
- *Install to Workspace* → copy Bot User OAuth Token → `xoxb-...`
- In Slack: `/invite @your-bot`

**2. Pi**

```bash
git clone git@github.com:<you>/CAN_TestBench.git ~/CAN_TestBench
cd ~/CAN_TestBench/Slack_Bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout,adm,systemd-journal $USER    # then LOG OUT + BACK IN
```

**3. Tokens**

```bash
sudo tee /etc/esp-fleet-bot.env >/dev/null <<'X'
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
X
sudo chmod 600 /etc/esp-fleet-bot.env
```

**4. Service** — copy `esp-fleet-bot.service` to `/etc/systemd/system/`, fixing `User=`, `WorkingDirectory=`, `IDF_PATH=`, `IDF_TOOLS_PATH=` for your machine. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now esp-fleet-bot
```

**5. Verify, in order** — each step isolates a different failure.

```bash
source $IDF_PATH/export.sh && idf.py --version   # IDF works
.venv/bin/python bot.py boards                   # serial works (empty = dialout)
sudo systemctl status esp-fleet-bot              # service works
```
Then `@bot status` in Slack.