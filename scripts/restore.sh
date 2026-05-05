#!/usr/bin/env bash
#
# Restore Vittring database from a backup file.
# Usage: ./scripts/restore.sh <vittring-YYYY-MM-DD.sql.gz.gpg>

set -euo pipefail

set -a; source /etc/vittring/.env; set +a

[[ $# -eq 1 ]] || { echo "usage: $0 <backup-file>"; exit 1; }
INFILE="$1"
[[ -f "${INFILE}" ]] || { echo "no such file: ${INFILE}"; exit 1; }
[[ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]] || { echo "missing BACKUP_ENCRYPTION_PASSPHRASE"; exit 1; }

DB_URL_PLAIN="$(echo "${DATABASE_URL}" | sed 's,^postgresql+asyncpg://,postgresql://,')"

read -r -p "About to DROP and recreate the database. Continue? [y/N] " ans
[[ "${ans,,}" == "y" ]] || { echo "aborted"; exit 1; }

DBNAME="$(echo "${DB_URL_PLAIN}" | sed -E 's,.*/([^?]+)$,\1,')"

echo "[restore] Dropping ${DBNAME}"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DBNAME};"
sudo -u postgres psql -c "CREATE DATABASE ${DBNAME} OWNER vittring;"
sudo -u postgres psql -d "${DBNAME}" -c "CREATE EXTENSION IF NOT EXISTS citext;"

echo "[restore] Decrypting and importing"
gpg --batch --yes --decrypt --passphrase "${BACKUP_ENCRYPTION_PASSPHRASE}" "${INFILE}" \
    | gunzip \
    | psql "${DB_URL_PLAIN}"

echo "[restore] Done."
