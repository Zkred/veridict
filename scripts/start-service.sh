#!/bin/sh
# Write key material from env vars to temp files before starting the server.
# Cloud Run is stateless; secrets land in env vars and we write them to /tmp.

# Shared keys — written before service dispatch so both backend and issuer get them.
if [ -n "$GITHUB_APP_KEY_B64" ]; then
  echo "$GITHUB_APP_KEY_B64" | base64 -d > /tmp/app-private-key.pem
  export GITHUB_APP_PRIVATE_KEY_PATH=/tmp/app-private-key.pem
fi

if [ "$SERVICE" = "backend" ]; then
  export DB_PATH="${DB_PATH:-/tmp/backend.db}"
  cd /app/backend && exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8001}"
fi

# issuer-only keys
if [ -n "$ISSUER_KEY_B64" ]; then
  echo "$ISSUER_KEY_B64" | base64 -d > /tmp/issuer_key.pem
  export ISSUER_KEY_PATH=/tmp/issuer_key.pem
fi

if [ -n "$PSEUDONYM_KEY_B64" ]; then
  mkdir -p /tmp/.secrets
  echo "$PSEUDONYM_KEY_B64" | base64 -d > /tmp/.secrets/pseudonym-key.bin
  export PSEUDONYM_KEY_PATH=/tmp/.secrets/pseudonym-key.bin
fi

export ISSUER_DB_PATH="${ISSUER_DB_PATH:-/tmp/issuer.db}"

cd /app/issuer && exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}"
