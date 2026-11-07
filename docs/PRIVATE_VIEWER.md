# Private telemetry viewing over SSH

The Pi viewer listens on 127.0.0.1:8080; the read-only bridge web stream listens
on 127.0.0.1:8765. SSH encrypts the network hop. No Tailscale account change,
public listener, or certificate is required.

Keep this command running on your computer:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18880:127.0.0.1:8080 -L 127.0.0.1:18765:127.0.0.1:8765 stolerpi-admin
```

Open [the private viewer](http://127.0.0.1:18880/?bridge=ws%3A%2F%2F127.0.0.1%3A18765%2Fws).
Closing SSH closes access. A connected viewer does not establish successful
CAN reception. GitHub Pages remains a separate deployed historical snapshot.

Install systemd/calsol-telemetry-viewer.service and set `CALSOL_WEB_ROOT` in
/etc/calsol/viewer.env to the deployed web directory. `CALSOL_WEB_PORT` defaults
to 8080. Enable it with `systemctl enable --now calsol-telemetry-viewer.service`.
The viewer has no write access.

Tailscale Serve can be configured later, but its one-time tailnet enablement
requires an account administrator; local sudo cannot grant it.
