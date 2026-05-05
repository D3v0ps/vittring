#!/usr/bin/env bash
#
# Zero-downtime deploy. Runs as the 'vittring' user on the server.
#
# Usage:
#   ./scripts/deploy.sh <ref>      # ref = git tag, branch, or commit
#
# Strategy: each release lands in /opt/vittring/releases/<ts>/, the venv is
# built from uv.lock, migrations run, then /opt/vittring/current is atomically
# repointed and systemd units are reloaded.

set -euo pipefail

readonly APP_HOME="/opt/vittring"
readonly REPO_URL="${REPO_URL:-https://github.com/D3v0ps/vittring.git}"

REF="${1:-main}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RELEASE_DIR="${APP_HOME}/releases/${TIMESTAMP}-${REF}"

log() { printf "\n\033[1;36m[deploy]\033[0m %s\n" "$*"; }
fail() { printf "\n\033[1;31m[deploy]\033[0m %s\n" "$*" >&2; exit 1; }

[[ "$(whoami)" == "vittring" ]] || fail "must run as vittring user"
command -v uv >/dev/null || fail "uv not on PATH; rerun bootstrap"

log "Cloning ${REPO_URL} @ ${REF} into ${RELEASE_DIR}"
git clone --depth 1 --branch "${REF}" "${REPO_URL}" "${RELEASE_DIR}" 2>/dev/null \
    || git clone "${REPO_URL}" "${RELEASE_DIR}" && (cd "${RELEASE_DIR}" && git checkout "${REF}")

cd "${RELEASE_DIR}"

log "Installing dependencies via uv"
uv sync --frozen --no-dev

log "Running database migrations"
set -a; source /etc/vittring/.env; set +a
uv run alembic upgrade head

log "Atomically repointing /opt/vittring/current"
ln -sfn "${RELEASE_DIR}" "${APP_HOME}/current"

log "Reloading systemd units"
sudo /bin/systemctl reload-or-restart vittring-api.service || true
sudo /bin/systemctl restart vittring-scheduler.service || true

log "Verifying /health"
for i in 1 2 3 4 5; do
    if curl -fsS http://localhost:8000/health | grep -q '"status":"ok"'; then
        log "Healthy."
        break
    fi
    sleep 2
    if [[ $i -eq 5 ]]; then
        fail "Health check failed after 5 attempts"
    fi
done

log "Pruning old releases (keeping last 5)"
ls -1dt "${APP_HOME}/releases"/*/ | tail -n +6 | xargs -r rm -rf

log "Deploy complete: ${REF}"
