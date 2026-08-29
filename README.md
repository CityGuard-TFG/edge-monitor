# CityGuard Edge Monitor

A local status dashboard for a single CityGuard Pi edge node: system health
(CPU, RAM, disk, temperature, throttling), a live camera preview, Hailo-8L
NPU detection, and GPS fix quality with live coordinates. It runs at boot as
a systemd service and is reachable from any device on the same network as
the Pi, at `http://<pi-ip>`.

## What this is not

This tool is deliberately **not** part of the CityGuard capture, privacy, or
upload pipeline described in the `edge` repository. It exists purely to make
hardware bring-up and field debugging observable — "is the camera focused,
is the GPS getting a fix, is the Hailo NPU actually responding" — without
SSHing in and running scripts by hand every time.

Two consequences follow directly from that scope, and both are load-bearing:

- **It carries no authentication.** Anyone who can reach the Pi's IP on port 80
  can view its status, including the raw camera feed. This is
  acceptable for a trusted development LAN or a workbench network, but the
  dashboard must never be exposed on an untrusted or public network.
- **The camera preview serves unblurred, raw frames.** `/api/camera/snapshot.jpg`
  exists specifically so a person can check focus and mounting angle by eye —
  running it through the anonymization pipeline first would defeat that
  purpose. This is the opposite of the fail-closed privacy guarantee the rest
  of the project enforces (see `privacy` and `05-privacy-compliance.md` in the
  knowledge base), and it must stay that way only because this service is not
  running while the bus operates around the public. **Stop the
  `cityguard-edge-monitor` service (`sudo systemctl stop cityguard-edge-monitor`)
  or firewall off port 80 before the node captures real evidence on a route.**

## API surface

All endpoints are `GET`, unauthenticated, and CORS-open.

| Endpoint | Returns |
|---|---|
| `/api/health` | `{"ok": true}` liveness check |
| `/api/status` | Hostname, uptime, CPU/RAM/disk usage, CPU temperature, estimated board power draw, under-voltage/throttling flags, IP addresses |
| `/api/hailo` | Whether the Hailo-8L NPU responds to `hailortcli fw-control identify`, plus board/architecture/firmware/chip temperature |
| `/api/gps` | Fix quality (none/2D/3D), latitude/longitude/altitude/speed, satellites used/visible, HDOP — read from a background gpsd client |
| `/api/camera/snapshot.jpg` | An on-demand JPEG frame from the camera, throttled to at most one real capture every 2 seconds |
| `/api/camera/status` | Whether the last capture succeeded and how old the cached frame is, without triggering a new capture |

`power_w` is an estimate from `vcgencmd pmic_read_adc`, summed over every
PMIC rail that reports both current and voltage. It covers the Pi 5's own
internal regulators, not the full board — power drawn by the Hailo HAT+,
camera, and GPS over the 5V rail isn't separately metered by the PMIC, so
this number is a lower bound on total system draw, not the whole picture.
The Hailo-8L itself doesn't expose a "utilization" figure until a real
inference workload is running on it (Phase 2); until then the dashboard
shows it as idle, which is accurate rather than a missing feature.

## Local development

```bash
# Terminal 1 -- backend
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000

# Terminal 2 -- frontend
cd web
npm install
npm run dev   # http://localhost:5173, proxies /api to :8000
```

Off the Pi, `/api/hailo`, `/api/gps`, and `/api/camera/*` will simply report
"not detected" / "unavailable" — every hardware read degrades gracefully
rather than raising, by design.

## Releases and CI

The repository is public and has two GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`) — on every push/PR to `dev` or `main`,
  byte-compiles the backend and runs a real `npm run build` of the frontend.
  This is a build check, not a hardware test — it can't exercise `/api/hailo`,
  `/api/gps`, or the camera, which only mean anything on the real device.
- **Release** (`.github/workflows/release.yml`) — pushing a tag matching
  `v*.*.*` (e.g. `v0.2.0`) automatically publishes a GitHub Release at that
  tag with auto-generated notes. This is what the Pi checks against — see
  below.

## Deployment (on the Pi)

1. Clone the repository to `/opt/cityguard-edge-monitor` on the device (a
   real `git clone`, not a tarball or `git archive` dump — the startup update
   check needs an actual `.git` directory to `fetch`/`checkout` against):

   ```bash
   sudo git clone https://github.com/CityGuard-TFG/edge-monitor.git /opt/cityguard-edge-monitor
   ```

2. Run the installer as root:

   ```bash
   cd /opt/cityguard-edge-monitor
   sudo bash scripts/install.sh
   ```

   This installs Python/Node/git/curl system packages, creates a virtualenv,
   builds the frontend (`web/dist`), hands the whole tree to the `cityguard`
   account, installs `systemd/cityguard-edge-monitor.service`, and enables
   it to start on boot. That account needs to already exist on the device
   with `video`, `i2c`, `gpio`, and `dialout` group membership — on the
   reference node this is the primary account set up in Raspberry Pi
   Imager, not a separate service user created by any script here.
3. Browse to `http://<pi-ip>` from any device on the same network.

The installer is idempotent — re-run it after a `git pull` to redeploy.

### Automatic updates on startup

Every time the service starts (boot, or a manual restart),
`scripts/check-update.sh` runs first as `ExecStartPre`, as the unprivileged
`cityguard` user: it asks the GitHub Releases API for the latest published
release, and if the Pi isn't already on that tag, `git fetch`es, checks it
out, reinstalls backend dependencies, and rebuilds the frontend — all before
`uvicorn` actually starts. It is deliberately fail-open: no network, a
GitHub API hiccup, or a checkout that isn't a git clone all just mean "start
with whatever's already on disk," logged but never fatal to the unit. There
is no background polling while the service is running — cutting a new
release only takes effect on the next restart of
`cityguard-edge-monitor.service` (or the next reboot).

This only updates application code (`server/`, `web/`). Because the update
check itself runs unprivileged, it cannot touch `/etc/systemd/system` or run
`systemctl daemon-reload` — a release that changes
`systemd/cityguard-edge-monitor.service` or `scripts/install.sh` still needs
a manual `sudo bash scripts/install.sh` re-run on the device.

To ship an update: merge to `main`, then `git tag vX.Y.Z && git push --tags`.
The Release workflow publishes it, and every deployed node picks it up the
next time its service restarts.
