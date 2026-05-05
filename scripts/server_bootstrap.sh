#!/usr/bin/env bash
#
# Vittring server bootstrap. Idempotent — safe to re-run.
#
# Usage (as root on the target server):
#   DEPLOY_PUBLIC_KEY="ssh-ed25519 AAAA... vittring-deploy" \
#   bash server_bootstrap.sh
#
# What it does (CLAUDE.md §16):
#   - System update + base packages
#   - PostgreSQL 16 with vittring db/user
#   - vittring user, /opt/vittring tree, /etc/vittring/.env (640 root:vittring)
#   - Caddy 2 with managed TLS via Let's Encrypt
#   - systemd units for API + scheduler (not started yet)
#   - UFW + fail2ban + unattended-upgrades + logrotate
#   - Disable root SSH login and password auth
#
# Required env vars (set inline or via /etc/vittring/.env on re-runs):
#   DEPLOY_PUBLIC_KEY  — public key for the github-actions deploy user
#

set -euo pipefail

readonly APP_USER="vittring"
readonly APP_HOME="/opt/vittring"
readonly ENV_DIR="/etc/vittring"
readonly LOG_DIR="/var/log/vittring"
readonly REPO_URL="${REPO_URL:-https://github.com/D3v0ps/vittring.git}"
readonly DOMAIN="${DOMAIN:-vittring.karimkhalil.se}"

log() { printf "\n\033[1;36m[bootstrap]\033[0m %s\n" "$*"; }
fail() { printf "\n\033[1;31m[bootstrap]\033[0m %s\n" "$*" >&2; exit 1; }
require_root() { [[ $EUID -eq 0 ]] || fail "must run as root"; }

require_root

# ---------------------------------------------------------------------------
# Phase 0 — sanity
# ---------------------------------------------------------------------------
log "Phase 0: sanity checks"
if [[ -z "${DEPLOY_PUBLIC_KEY:-}" && ! -f "${ENV_DIR}/.deploy_pub" ]]; then
    fail "DEPLOY_PUBLIC_KEY env var required on first run"
fi

# ---------------------------------------------------------------------------
# Phase 1 — system hardening + base packages
# ---------------------------------------------------------------------------
log "Phase 1: hostname, timezone, base packages"
hostnamectl set-hostname vittring-prod-01
timedatectl set-timezone Europe/Stockholm

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

apt-get install -y -qq \
    postgresql-16 postgresql-contrib \
    python3.12 python3.12-venv python3.12-dev \
    build-essential libpq-dev pkg-config \
    git curl ca-certificates gnupg \
    ufw fail2ban unattended-upgrades \
    logrotate chrony rsync

# Caddy from official repo
if ! command -v caddy >/dev/null; then
    log "Installing Caddy 2"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
fi

# uv (modern Python package manager)
if ! command -v /usr/local/bin/uv >/dev/null; then
    log "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

# ---------------------------------------------------------------------------
# Phase 2 — application user, directories
# ---------------------------------------------------------------------------
log "Phase 2: user + directories"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --shell /bin/bash --groups sudo "${APP_USER}"
fi

install -d -m 750 -o "${APP_USER}" -g "${APP_USER}" "${APP_HOME}" "${APP_HOME}/var" "${APP_HOME}/releases"
install -d -m 755 -o "${APP_USER}" -g "${APP_USER}" "${LOG_DIR}"
install -d -m 750 -o root -g "${APP_USER}" "${ENV_DIR}"

# Authorized keys: copy root's keys into vittring + add deploy key
mkdir -p "/home/${APP_USER}/.ssh"
chmod 700 "/home/${APP_USER}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
    cat /root/.ssh/authorized_keys > "/home/${APP_USER}/.ssh/authorized_keys"
fi
if [[ -n "${DEPLOY_PUBLIC_KEY:-}" ]]; then
    grep -qxF "${DEPLOY_PUBLIC_KEY}" "/home/${APP_USER}/.ssh/authorized_keys" 2>/dev/null \
        || echo "${DEPLOY_PUBLIC_KEY}" >> "/home/${APP_USER}/.ssh/authorized_keys"
    echo "${DEPLOY_PUBLIC_KEY}" > "${ENV_DIR}/.deploy_pub"
fi
chmod 600 "/home/${APP_USER}/.ssh/authorized_keys"
chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.ssh"

# ---------------------------------------------------------------------------
# Phase 3 — PostgreSQL
# ---------------------------------------------------------------------------
log "Phase 3: PostgreSQL"
PG_HBA="$(sudo -u postgres psql -tAc 'SHOW hba_file;' | tr -d '[:space:]')"
PG_CONF="$(sudo -u postgres psql -tAc 'SHOW config_file;' | tr -d '[:space:]')"

if ! grep -q "^listen_addresses = 'localhost'" "${PG_CONF}"; then
    sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost'/" "${PG_CONF}"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='vittring'" | grep -q 1; then
    PG_PASSWORD="$(openssl rand -hex 24)"
    sudo -u postgres psql -c "CREATE ROLE vittring LOGIN PASSWORD '${PG_PASSWORD}';"
    sudo -u postgres psql -c "CREATE DATABASE vittring OWNER vittring;"
    sudo -u postgres psql -d vittring -c "CREATE EXTENSION IF NOT EXISTS citext;"
    log "Saving DATABASE_URL to ${ENV_DIR}/.env"
    DB_URL="postgresql+asyncpg://vittring:${PG_PASSWORD}@localhost:5432/vittring"
else
    log "Postgres role 'vittring' already exists; reusing"
    DB_URL="$(grep -E '^DATABASE_URL=' "${ENV_DIR}/.env" 2>/dev/null | cut -d= -f2- || true)"
fi

systemctl enable --now postgresql

# ---------------------------------------------------------------------------
# Phase 4 — /etc/vittring/.env
# ---------------------------------------------------------------------------
log "Phase 4: /etc/vittring/.env"
ENV_FILE="${ENV_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    SECRET="$(openssl rand -hex 32)"
    cat > "${ENV_FILE}" <<EOF
APP_ENV=production
APP_SECRET_KEY=${SECRET}
APP_BASE_URL=https://${DOMAIN}
TZ=Europe/Stockholm

DATABASE_URL=${DB_URL}

# Email — fill in before starting services
RESEND_API_KEY=
EMAIL_FROM_ADDRESS=info@karimkhalil.se
EMAIL_FROM_NAME=Vittring
EMAIL_REPLY_TO=info@karimkhalil.se
EMAIL_SENDING_DOMAIN=karimkhalil.se

# Sentry
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1

# Backups
BACKUP_TARGET=local
BACKUP_LOCAL_PATH=/var/backups/vittring
BACKUP_ENCRYPTION_PASSPHRASE=
EOF
fi
chown root:"${APP_USER}" "${ENV_FILE}"
chmod 640 "${ENV_FILE}"

# ---------------------------------------------------------------------------
# Phase 5 — Caddy
# ---------------------------------------------------------------------------
log "Phase 5: Caddy"
if [[ -d "${APP_HOME}/current" ]]; then
    install -m 644 "${APP_HOME}/current/deploy/Caddyfile" /etc/caddy/Caddyfile
else
    # Will be installed by deploy.sh on first deploy; for now write a minimal
    # placeholder so caddy starts and provisions TLS for the domain.
    cat > /etc/caddy/Caddyfile <<EOF
{
    email info@karimkhalil.se
}

${DOMAIN} {
    respond "Vittring — bootstrapping"
}
EOF
fi
install -d -m 755 /var/log/caddy
systemctl enable --now caddy
systemctl reload caddy || true

# ---------------------------------------------------------------------------
# Phase 6 — systemd units
# ---------------------------------------------------------------------------
log "Phase 6: systemd units"
if [[ -d "${APP_HOME}/current" ]]; then
    install -m 644 "${APP_HOME}/current/deploy/systemd/vittring-api.service" \
        /etc/systemd/system/vittring-api.service
    install -m 644 "${APP_HOME}/current/deploy/systemd/vittring-scheduler.service" \
        /etc/systemd/system/vittring-scheduler.service
    systemctl daemon-reload
fi

# ---------------------------------------------------------------------------
# Phase 7 — UFW + fail2ban + unattended-upgrades + logrotate
# ---------------------------------------------------------------------------
log "Phase 7: firewall, fail2ban, unattended-upgrades, logrotate"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable

cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 3
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl reload fail2ban

if [[ -d "${APP_HOME}/current/deploy/unattended-upgrades" ]]; then
    install -m 644 "${APP_HOME}/current/deploy/unattended-upgrades/50unattended-upgrades" \
        /etc/apt/apt.conf.d/50unattended-upgrades
fi

if [[ -d "${APP_HOME}/current/deploy/logrotate" ]]; then
    install -m 644 "${APP_HOME}/current/deploy/logrotate/vittring" \
        /etc/logrotate.d/vittring
fi

# ---------------------------------------------------------------------------
# Phase 8 — SSH hardening
# ---------------------------------------------------------------------------
log "Phase 8: SSH hardening"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
# Ubuntu 24.04 socket-activates ssh, so the .service is inactive between
# connections — `reload` fails. Restart the .socket if present, otherwise
# the .service. Existing sessions stay alive in either case.
if systemctl list-unit-files --type=socket | grep -q '^ssh\.socket'; then
    systemctl restart ssh.socket
elif systemctl list-unit-files --type=service | grep -q '^ssh\.service'; then
    systemctl restart ssh.service
elif systemctl list-unit-files --type=service | grep -q '^sshd\.service'; then
    systemctl restart sshd.service
fi

# ---------------------------------------------------------------------------
# Phase 9 — backup directory + cron
# ---------------------------------------------------------------------------
log "Phase 9: backup directory + cron"
install -d -m 750 -o "${APP_USER}" -g "${APP_USER}" /var/backups/vittring

if [[ -f "${APP_HOME}/current/scripts/backup.sh" ]]; then
    cat > /etc/cron.d/vittring-backup <<EOF
# Nightly Postgres dump at 02:00 Europe/Stockholm
0 2 * * * ${APP_USER} ${APP_HOME}/current/scripts/backup.sh >> ${LOG_DIR}/backup.log 2>&1
EOF
fi

# ---------------------------------------------------------------------------
log ""
log "Bootstrap complete."
log "Next steps:"
log "  1. Edit ${ENV_FILE} and fill in RESEND_API_KEY, SENTRY_DSN."
log "  2. As ${APP_USER}, clone the repo and run scripts/deploy.sh main."
log "  3. systemctl enable --now vittring-api vittring-scheduler"
log ""
