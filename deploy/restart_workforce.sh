#!/bin/sh
# Reconcile the existing deployment without rebuilding Paperclip or touching
# employee sandboxes, Ollama, AIGoat or PentAGI. Native runtime lifecycle remains
# with staffing.py. Existing unchanged services are left running.
set -eu
cd "$(dirname "$0")/.."
for jarvis_env in deploy/.env deploy/codex-demo.env deploy/codex-workforce.env; do
  if [ ! -f "$jarvis_env" ]; then
    echo "Missing server-side configuration: $jarvis_env" >&2
    exit 1
  fi
done
exec docker compose \
  --env-file deploy/.env \
  --env-file deploy/codex-demo.env \
  --env-file deploy/codex-workforce.env \
  -f deploy/compose.yaml \
  -f deploy/compose.codex-demo.yaml \
  -f deploy/compose.codex-chat.yaml \
  -f deploy/compose.codex-workforce.yaml \
  up -d --no-deps --wait --wait-timeout 120 jarvis hermes hermes-ceo
