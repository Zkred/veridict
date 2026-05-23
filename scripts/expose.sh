#!/usr/bin/env bash
# Expose the local backend on a public URL so GitHub Actions can reach it.
# Prefers ngrok (already installed). Falls back to cloudflared if present.
#
# Keep this terminal open — the URL stays alive as long as the tunnel runs.

set -euo pipefail
PORT="${PORT:-8001}"

# Verify backend is up before exposing it.
if ! curl -fsS "http://localhost:${PORT}/pr/test/test/1/abc/approvals" >/dev/null 2>&1; then
  echo "Backend not responding on http://localhost:${PORT}"
  echo "Start it with:  .venv/bin/python backend/main.py"
  exit 1
fi

if command -v ngrok >/dev/null; then
  echo "Tunneling http://localhost:${PORT} via ngrok …"
  echo "Look for the 'Forwarding' line — copy the https://*.ngrok-free.app URL."
  echo "Then run:"
  echo "    gh secret set REVIEW_BACKEND_URL --body \"https://...\"  -R <owner>/<repo>"
  echo
  exec ngrok http "$PORT"
elif command -v cloudflared >/dev/null; then
  echo "Tunneling http://localhost:${PORT} via cloudflared …"
  exec cloudflared tunnel --url "http://localhost:${PORT}"
else
  echo "No tunnel tool installed. Install one:"
  echo "    brew install ngrok        (recommended; you already have it)"
  echo "    brew install cloudflared  (alternative; no account required)"
  exit 1
fi
