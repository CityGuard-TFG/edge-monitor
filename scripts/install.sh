#!/usr/bin/env bash
set -euo pipefail

# Installs the CityGuard Edge Monitor dashboard from a reviewed checkout
# already placed at /opt/cityguard-edge-monitor (a `git clone`, not a tarball
# -- scripts/check-update.sh needs a real .git directory to pull releases).
APP_DIR=/opt/cityguard-edge-monitor
SERVICE_USER=cityguard

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install.sh" >&2
  exit 2
fi

[[ -d "${APP_DIR}/server" ]] || { echo "Expected a reviewed release at ${APP_DIR}" >&2; exit 2; }
[[ -d "${APP_DIR}/.git" ]] || echo "Warning: ${APP_DIR} is not a git checkout -- the startup update check will be skipped." >&2

id -u "${SERVICE_USER}" >/dev/null 2>&1 || {
  echo "Expected the ${SERVICE_USER} service account to already exist (created by edge/scripts/install-pi-runtime.sh)." >&2
  exit 2
}

apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip python3-gps nodejs npm git curl

# --system-site-packages: /api/gps depends on `import gps`, provided by the
# apt package python3-gps, not a PyPI package -- an isolated venv can't see it.
python3 -m venv --system-site-packages "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/server/requirements.txt"

if [[ -d "${APP_DIR}/web/dist" && "${SKIP_FRONTEND_BUILD:-}" == "1" ]]; then
  echo "web/dist already exists and SKIP_FRONTEND_BUILD=1 -- skipping frontend build."
else
  ( cd "${APP_DIR}/web" && npm ci && npm run build )
fi

# check-update.sh runs as User=cityguard at every startup and needs to git
# checkout / pip install / npm build in place -- hand it the whole tree.
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
chmod +x "${APP_DIR}/scripts/check-update.sh"

install -m 0644 "${APP_DIR}/systemd/cityguard-edge-monitor.service" /etc/systemd/system/cityguard-edge-monitor.service
systemctl daemon-reload
systemctl enable cityguard-edge-monitor.service
# `enable --now` is a no-op restart-wise if the service is already running,
# which would leave a re-run after `git pull` silently serving stale code.
systemctl restart cityguard-edge-monitor.service

ip_addr="$(hostname -I | awk '{print $1}')"
echo "CityGuard Edge Monitor installed and running."
echo "Dashboard reachable at: http://${ip_addr}:8090"
