#!/bin/sh
set -eu
# The image and application run as the same unprivileged identity. Provision
# the dedicated disk before enabling the sandbox; never chown it at startup.
exec /opt/venv/bin/python -m game_sandbox.staging_bootstrap
