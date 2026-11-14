#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R app:app /app/data
    exec setpriv --reuid=app --regid=app --clear-groups "$@"
fi

exec "$@"
