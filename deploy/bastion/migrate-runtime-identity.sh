#!/usr/bin/env bash
set -euo pipefail

# One-time migration from the live bastion into SSM. It preserves the existing
# WireGuard server identity, so the Mini keeps its current peer configuration
# when Terraform replaces the instance. Private material is never printed.

BASTION_SSH="${BASTION_SSH:-ubuntu@34.205.40.23}"
AWS_REGION="${AWS_REGION:-us-east-1}"
SSH_IDENTITY_FILE="${SSH_IDENTITY_FILE:-}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
umask 077

require() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require aws
require ssh

ssh_options=(-o BatchMode=yes)
if [ -n "$SSH_IDENTITY_FILE" ]; then
  ssh_options+=(-i "$SSH_IDENTITY_FILE" -o IdentitiesOnly=yes)
fi

echo "Reading existing WireGuard identity from the bastion..."
ssh "${ssh_options[@]}" "$BASTION_SSH" 'sudo cat /etc/wireguard/server.key' >"$tmpdir/wireguard-private-key"
test -s "$tmpdir/wireguard-private-key" || {
  echo "Bastion returned an empty WireGuard private key." >&2
  exit 1
}

echo "Reading the Mini peer public key..."
mini_public_key="$(ssh "${ssh_options[@]}" "$BASTION_SSH" "sudo sed -n 's/^[[:space:]]*PublicKey[[:space:]]*=[[:space:]]*//p' /etc/wireguard/wg0.conf | head -n 1")"
test -n "$mini_public_key" || {
  echo "Could not find a PublicKey entry in /etc/wireguard/wg0.conf." >&2
  exit 1
}

echo "Reading the existing Certbot contact..."
acme_email="$(ssh "${ssh_options[@]}" "$BASTION_SSH" "sudo sed -n 's/^email = //p' /etc/letsencrypt/renewal/*.conf | head -n 1")"
test -n "$acme_email" || {
  echo "Could not find an email entry in /etc/letsencrypt/renewal/*.conf." >&2
  exit 1
}

aws ssm put-parameter --region "$AWS_REGION" --overwrite --type SecureString \
  --name /miniai/bastion/wireguard-private-key \
  --value "file://$tmpdir/wireguard-private-key" >/dev/null
aws ssm put-parameter --region "$AWS_REGION" --overwrite --type String \
  --name /miniai/bastion/mini-wg-public-key \
  --value "$mini_public_key" >/dev/null
aws ssm put-parameter --region "$AWS_REGION" --overwrite --type String \
  --name /miniai/bastion/acme-email \
  --value "$acme_email" >/dev/null

echo "Bastion runtime identity migrated to SSM."
