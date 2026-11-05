#!/bin/sh
set -eu
# Render mounts the dedicated persistent disk here. Do not write entitlements
# to the disposable container filesystem. Never run the API as root.
mkdir -p /var/data
chown nija:nija /var/data
exec gosu nija /bin/sh -c 'exec /opt/venv/bin/gunicorn "game_sandbox.staging_entrypoint:application" --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 2 --error-logfile -'
