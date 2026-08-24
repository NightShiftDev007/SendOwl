#!/bin/sh
set -eu

if [ ! -f /workspace/pyproject.toml ]; then
  cp -R /opt/matraix/. /workspace/
fi

exec uvicorn playground.remote_runner.server:create_app --factory --host 0.0.0.0 --port 9100
