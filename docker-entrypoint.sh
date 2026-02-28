#!/bin/sh
set -e

# Cooldown on failure: if anything below fails (set -e), sleep 30s
# before exiting so Docker's restart policy doesn't spin a tight loop.
# The trap does NOT fire on success because exec replaces this shell.
trap 'echo "Entrypoint failed, cooling down 30s before exit..."; sleep 30' EXIT

# Wait for the database to be reachable before running migrations.
echo "Waiting for database..."
retries=30
while [ "$retries" -gt 0 ]; do
    if python -c "
import django; django.setup()
from django.db import connections
connections['default'].ensure_connection()
" 2>/dev/null; then
        break
    fi
    retries=$((retries - 1))
    echo "Database not ready, retrying in 2s... ($retries attempts left)"
    sleep 2
done

if [ "$retries" -le 0 ]; then
    echo "ERROR: Database not available after 60s, exiting"
    exit 1
fi

# Run database migrations before starting the application
echo "Running database migrations..."
python manage.py migrate --noinput

exec "$@"
