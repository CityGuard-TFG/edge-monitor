#!/usr/bin/env bash
# Runs as ExecStartPre before the dashboard starts, as the unprivileged
# `cityguard` user. Deliberately never fails the unit: any problem here
# (offline, rate-limited, no git checkout) just means the service starts
# with whatever code is already on disk.
#
# Scope boundary: this updates the application code (server/, web/) but
# cannot touch /etc/systemd/system or run `systemctl daemon-reload` --
# both need root, which this unprivileged service intentionally doesn't
# have. A release that changes systemd/cityguard-edge-monitor.service or
# scripts/install.sh itself needs a manual `sudo bash scripts/install.sh`
# re-run; only server/web code updates apply automatically on restart.
set -uo pipefail

APP_DIR="${CITYGUARD_APP_DIR:-/opt/cityguard-edge-monitor}"
REPO="CityGuard-TFG/edge-monitor"

log() { echo "[check-update] $*"; }

if [[ ! -d "${APP_DIR}/.git" ]]; then
  log "${APP_DIR} is not a git checkout -- skipping update check."
  exit 0
fi

latest_tag="$(curl -fsS --max-time 5 "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
  | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/')"

if [[ -z "${latest_tag}" ]]; then
  log "Could not reach the GitHub releases API -- starting with the currently deployed code."
  exit 0
fi

current_tag="$(git -C "${APP_DIR}" describe --tags --exact-match 2>/dev/null || true)"

if [[ "${current_tag}" == "${latest_tag}" ]]; then
  log "Already on latest release (${latest_tag})."
  exit 0
fi

log "Newer release available: '${current_tag:-unknown}' -> '${latest_tag}'. Updating..."

if ! git -C "${APP_DIR}" fetch --tags --quiet; then
  log "git fetch failed -- starting with the currently deployed code."
  exit 0
fi

if ! git -C "${APP_DIR}" checkout --quiet "${latest_tag}"; then
  log "git checkout ${latest_tag} failed -- starting with the currently deployed code."
  exit 0
fi

log "Reinstalling backend dependencies..."
"${APP_DIR}/venv/bin/pip" install --quiet -r "${APP_DIR}/server/requirements.txt" \
  || log "pip install reported errors -- continuing with what succeeded."

log "Rebuilding frontend..."
( cd "${APP_DIR}/web" && npm ci --silent && npm run build --silent ) \
  || log "Frontend rebuild failed -- continuing with the previous build if one exists."

log "Updated to ${latest_tag}."
exit 0
