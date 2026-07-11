#!/usr/bin/env bash
# miniAI deploy: pull → test → restart → health-gate.
# This *is* the CD pipeline — single host, no orchestrator, no apologies.
# Run on the mini:  ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
UID_N=$(id -u)

echo "==> pulling latest main"
git pull --ff-only origin main

echo "==> installing deps"
pip install -q -r requirements.txt

echo "==> running tests (deploy gate)"
python3 -m pytest -q

echo "==> restarting services"
launchctl kickstart -k "gui/${UID_N}/com.miniai.mlx-server"
launchctl kickstart -k "gui/${UID_N}/com.miniai.gateway"

echo "==> health gate: waiting for /readyz (model load can take ~60s)"
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/readyz > /dev/null; then
    echo "==> deploy OK — gateway ready, model server up"
    exit 0
  fi
  sleep 5
done

echo "!! deploy FAILED health gate — check logs/gateway.log and logs/mlx-server.log"
echo "!! rollback: git checkout <previous-sha> && ./deploy/deploy.sh"
exit 1
