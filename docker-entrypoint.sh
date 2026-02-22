#!/usr/bin/env sh
set -eu

HOST="${OPENHYDRA_HOST:-0.0.0.0}"
PORT_VALUE="${PORT:-${OPENHYDRA_WEB_PORT:-7070}}"

# Default container mode is API service.
if [ "$#" -eq 0 ]; then
  exec openhydra serve --host "$HOST" --port "$PORT_VALUE"
fi

exec openhydra "$@"
