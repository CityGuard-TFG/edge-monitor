# CityGuard Edge Monitor

A local status dashboard for a single CityGuard Pi edge node: system health
(CPU, RAM, disk, temperature, throttling), a live camera preview, Hailo-8L
NPU detection, and GPS fix quality with live coordinates. It runs at boot as
a systemd service and is reachable from any device on the same network as
the Pi, at `http://<pi-ip>:8090`.

## What this is not

This tool is deliberately **not** part of the CityGuard capture, privacy, or
upload pipeline described in the `edge` repository. It exists purely to make
hardware bring-up and field debugging observable — "is the camera focused,
is the GPS getting a fix, is the Hailo NPU actually responding" — without
SSHing in and running scripts by hand every time.

Two consequences follow directly from that scope, and both are load-bearing:

- **It carries no authentication.** Anyone who can reach the Pi's IP on port
  8090 can view its status, including the raw camera feed. This is
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
  or firewall off port 8090 before the node captures real evidence on a route.**

## API surface

All endpoints are `GET`, unauthenticated, and CORS-open.

| Endpoint | Returns |
|---|---|
| `/api/health` | `{"ok": true}` liveness check |
| `/api/status` | Hostname, uptime, CPU/RAM/disk usage, CPU temperature, under-voltage/throttling flags, IP addresses |
| `/api/hailo` | Whether the Hailo-8L NPU responds to `hailortcli fw-control identify`, plus board/architecture/firmware |
| `/api/gps` | Fix quality (none/2D/3D), latitude/longitude/altitude/speed, satellites used/visible, HDOP — read from a background gpsd client |
| `/api/camera/snapshot.jpg` | An on-demand JPEG frame from the camera, throttled to at most one real capture every 2 seconds |
| `/api/camera/status` | Whether the last capture succeeded and how old the cached frame is, without triggering a new capture |

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

## Deployment (on the Pi)

1. Copy a reviewed checkout of this repository to `/opt/cityguard-edge-monitor`
   on the device.
2. Run the installer as root:

   ```bash
   sudo bash scripts/install.sh
   ```

   This installs Python/Node system packages, creates a virtualenv, builds
   the frontend (`web/dist`), installs
   `systemd/cityguard-edge-monitor.service`, and enables it to start on boot.
   It runs as the existing `cityguard` service account (created by
   `edge/scripts/install-pi-runtime.sh`), which already has `video`, `i2c`,
   `gpio`, and `dialout` group membership.
3. Browse to `http://<pi-ip>:8090` from any device on the same network.

The installer is idempotent — re-run it after a `git pull` to redeploy.
