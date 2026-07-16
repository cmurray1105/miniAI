#!/usr/bin/env bash
set -euo pipefail

# Image contents are intentionally generic: operating-system packages and
# safe defaults only. Private WireGuard keys, TLS certificates, DNS names, and
# nginx virtual hosts are configured after launch, never copied into an AMI.
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y \
  certbot \
  curl \
  dnsutils \
  nginx \
  python3-certbot-nginx \
  tar \
  unattended-upgrades \
  unzip \
  wireguard

# Ubuntu's ARM package repository does not publish awscli. Install AWS's
# official ARM64 v2 bundle so first-boot automation can retrieve SSM params.
curl --fail --location --retry 3 \
  --output /tmp/awscliv2.zip \
  https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip
unzip -q /tmp/awscliv2.zip -d /tmp
sudo /tmp/aws/install --update

sudo tee /etc/sysctl.d/99-miniai-edge.conf >/dev/null <<'EOF'
net.ipv4.ip_forward=1
EOF
sudo sysctl --system

sudo systemctl enable nginx
sudo systemctl enable unattended-upgrades

# Tempo is an edge-local trace store. Its data-plane configuration is fetched
# from SSM on first boot, so the AMI contains no environment-specific address
# or credential.
tempo_version="2.10.5"
tempo_archive="tempo_${tempo_version}_linux_arm64.tar.gz"
curl --fail --location --retry 3 \
  --output "/tmp/$tempo_archive" \
  "https://github.com/grafana/tempo/releases/download/v${tempo_version}/${tempo_archive}"
tar -xzf "/tmp/$tempo_archive" -C /tmp
sudo install -d -m 0755 /opt/tempo /etc/tempo /var/lib/tempo/blocks /var/lib/tempo/wal
sudo install -m 0755 /tmp/tempo /opt/tempo/tempo
sudo tee /etc/systemd/system/tempo.service >/dev/null <<'UNIT'
[Unit]
Description=Grafana Tempo
After=network-online.target wg-quick@wg0.service
Wants=network-online.target
Requires=wg-quick@wg0.service

[Service]
ExecStart=/opt/tempo/tempo -config.file=/etc/tempo/tempo.yaml
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
