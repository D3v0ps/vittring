#!/usr/bin/env bash
#
# Nightly Postgres dump, gpg-encrypted, with retention pruning.
# Honors BACKUP_TARGET=local|storagebox per CLAUDE.md §18.

set -euo pipefail

set -a; source /etc/vittring/.env; set +a

readonly TARGET="${BACKUP_TARGET:-local}"
readonly LOCAL_PATH="${BACKUP_LOCAL_PATH:-/var/backups/vittring}"
readonly STAMP="$(date +%Y-%m-%d)"
readonly OUTFILE="vittring-${STAMP}.sql.gz.gpg"
readonly TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

[[ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]] || { echo "BACKUP_ENCRYPTION_PASSPHRASE missing"; exit 1; }

DB_URL_PLAIN="$(echo "${DATABASE_URL}" | sed 's,^postgresql+asyncpg://,postgresql://,')"

echo "[backup] Dumping ${DB_URL_PLAIN%@*}@..."
pg_dump --format=plain --no-owner --no-privileges "${DB_URL_PLAIN}" \
    | gzip -9 \
    | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase "${BACKUP_ENCRYPTION_PASSPHRASE}" \
        --output "${TMPDIR}/${OUTFILE}"

echo "[backup] Wrote ${TMPDIR}/${OUTFILE} ($(du -h "${TMPDIR}/${OUTFILE}" | cut -f1))"

if [[ "${TARGET}" == "storagebox" ]]; then
    : "${BACKUP_HOST:?}" "${BACKUP_USER:?}" "${BACKUP_REMOTE_PATH:?}" "${BACKUP_SSH_KEY_PATH:?}"
    echo "[backup] Uploading via rsync to ${BACKUP_USER}@${BACKUP_HOST}:${BACKUP_REMOTE_PATH}"
    rsync -e "ssh -i ${BACKUP_SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new" \
        "${TMPDIR}/${OUTFILE}" \
        "${BACKUP_USER}@${BACKUP_HOST}:${BACKUP_REMOTE_PATH}/"
    # Retention pruning over SSH
    ssh -i "${BACKUP_SSH_KEY_PATH}" "${BACKUP_USER}@${BACKUP_HOST}" \
        "cd ${BACKUP_REMOTE_PATH} && ls -1t vittring-*.sql.gz.gpg | tail -n +31 | xargs -r rm --"
else
    install -d -m 750 "${LOCAL_PATH}"
    mv "${TMPDIR}/${OUTFILE}" "${LOCAL_PATH}/${OUTFILE}"
    echo "[backup] Stored locally at ${LOCAL_PATH}/${OUTFILE}"
    # Keep last 30 dailies
    ls -1t "${LOCAL_PATH}"/vittring-*.sql.gz.gpg | tail -n +31 | xargs -r rm --
fi

echo "[backup] Done."
