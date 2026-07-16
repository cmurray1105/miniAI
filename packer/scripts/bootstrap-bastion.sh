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
  nginx \
  python3-certbot-nginx \
  unattended-upgrades \
  wireguard

sudo tee /etc/sysctl.d/99-miniai-edge.conf >/dev/null <<'EOF'
net.ipv4.ip_forward=1
EOF
sudo sysctl --system

sudo systemctl enable nginx
sudo systemctl enable unattended-upgrades
