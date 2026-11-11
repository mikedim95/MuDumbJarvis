#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 init.py
docker compose up -d
# Add one isolated service-network attachment; retain all existing networks.
if ! docker inspect -f '{{if index .NetworkSettings.Networks "jarvis-command-center_agent-private"}}attached{{end}}' ollama | grep -q attached; then
  docker network connect --alias ollama-models jarvis-command-center_agent-private ollama
fi
