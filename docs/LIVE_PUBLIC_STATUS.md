# Public live status

The public website defaults to the HTTPS read-only relay in web/bridge-config.js.
The Pi caches live status every 2 seconds. Browsers fetch health every 3 seconds
and messages every 1.5 seconds. After 10 seconds without valid health, the UI
marks status unavailable. The relay never opens the debugger serial port.

Target states: unavailable when its USB device is missing; in use while runner
locks are held; idle when present and unreserved; unknown when ownership cannot
be checked. Idle does not prove firmware or physical CAN operation.

Only GET /health and GET /api/frames are exposed. Injection, command forwarding,
files, WebSocket upgrades and other paths are not supported. Simulated messages
are labeled and excluded from physical RX counters and test evidence.

Services: calsol-public-status.service and calsol-public-tunnel.service.
Cloudflared version 2026.10.7 was installed from the official GitHub release,
verified against its published asset SHA256 digest.

The account-free Cloudflare Quick Tunnel has no uptime guarantee and its hostname
changes if the cloudflared process restarts. Update web/bridge-config.js and
redeploy when that occurs. A named tunnel and stable hostname are required to
remove this administrative limitation. Visitors never configure an endpoint.
The existing GitHub snapshot feed remains available for historical fallback;
it is not claimed to be a live status source.
