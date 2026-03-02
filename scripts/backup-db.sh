#!/usr/bin/env bash
#
# PostgreSQL backup script for Spark Device Library
#
# Usage:
#   ./scripts/backup-db.sh                  # from project root
#   BACKUP_DIR=/mnt/backups ./scripts/backup-db.sh   # custom backup location
#
# Install as daily cron (run from project root):
#   crontab -e
#   0 3 * * * cd /opt/spark-device-library && ./scripts/backup-db.sh >> /var/log/spark-device-library-backup.log 2>&1
#

set -euo pipefail

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
DB_SERVICE="db"
DB_USER="spark_device_library"
DB_NAME="spark_device_library"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/spark_device_library_${TIMESTAMP}.sql.gz"

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting database backup..."

# Dump and compress
docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-acl \
    | gzip > "${BACKUP_FILE}"

# Verify backup is not empty
SIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null)
if [ "${SIZE}" -lt 100 ]; then
    echo "[$(date)] ERROR: Backup file is suspiciously small (${SIZE} bytes)"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

echo "[$(date)] Backup saved: ${BACKUP_FILE} ($(numfmt --to=iec "${SIZE}" 2>/dev/null || echo "${SIZE} bytes"))"

# Rotate old backups
DELETED=$(find "${BACKUP_DIR}" -name "spark_device_library_*.sql.gz" -mtime +"${KEEP_DAYS}" -print -delete | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    echo "[$(date)] Rotated ${DELETED} backup(s) older than ${KEEP_DAYS} days"
fi

echo "[$(date)] Backup complete"
