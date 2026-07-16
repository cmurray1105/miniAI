#!/usr/bin/env bash
set -euo pipefail
VERSION=2.10.5
ARCHIVE="tempo_${VERSION}_linux_arm64.tar.gz"
sudo install -d -m 0755 /opt/tempo /etc/tempo /var/lib/tempo/blocks /var/lib/tempo/wal
curl -fL -o "/tmp/$ARCHIVE" "https://github.com/grafana/tempo/releases/download/v${VERSION}/$ARCHIVE"
tar -xzf "/tmp/$ARCHIVE" -C /tmp
sudo install -m 0755 /tmp/tempo /opt/tempo/tempo
sudo install -m 0644 tempo.yaml /etc/tempo/tempo.yaml
sudo tee /etc/systemd/system/tempo.service >/dev/null <<'UNIT'
[Unit]
After=network-online.target wg-quick@wg0.service
[Service]
ExecStart=/opt/tempo/tempo -config.file=/etc/tempo/tempo.yaml
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now tempo
