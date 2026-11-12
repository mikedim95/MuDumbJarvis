#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 init.py
docker compose build
docker compose up -d hermes jarvis
# Add one isolated service-network attachment; retain all existing networks.
if ! docker inspect -f '{{if index .NetworkSettings.Networks "jarvis-command-center_agent-private"}}attached{{end}}' ollama | grep -q attached; then
  docker network connect --alias ollama-models jarvis-command-center_agent-private ollama
fi
# Keep the original model intact; create the separate context-window alias once.
if ! docker exec ollama ollama show jarvis-hermes:3b >/dev/null 2>&1; then
  docker cp Modelfile.hermes ollama:/tmp/jarvis-hermes.Modelfile
  docker exec ollama ollama create jarvis-hermes:3b -f /tmp/jarvis-hermes.Modelfile
fi
docker compose up -d
if ! grep -q '^PAPERCLIP_AGENT_ID=.' .env; then
  docker run --rm --user 1000:1000 --network jarvis-command-center_default \
    -e PAPERCLIP_BOOTSTRAP_URL=http://paperclip:3100 \
    -v "$(cd .. && pwd):/workspace" --entrypoint /opt/venv/bin/python \
    jarvis-command-center:hud /workspace/deploy/bootstrap_paperclip.py
  docker compose up -d hermes jarvis
fi
