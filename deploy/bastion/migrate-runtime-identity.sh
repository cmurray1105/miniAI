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

command -v aws >/dev/null
command -v ssh >/dev/null

ssh_options=(-o BatchMode=yes)
if [ -n "$SSH_IDENTITY_FILE" ]; then
  ssh_options+=(-i "$SSH_IDENTITY_FILE" -o IdentitiesOnly=yes)
fi

ssh "${ssh_options[@]}" "$BASTION_SSH" 'sudo cat /etc/wireguard/server.key' >"$tmpdir/wireguard-private-key"
mini_public_key="$(ssh "${ssh_options[@]}" "$BASTION_SSH" "sudo awk '/^PublicKey[[:space:]]*=/{print \\$3; exit}' /etc/wireguard/wg0.conf")"
acme_email="$(ssh "${ssh_options[@]}" "$BASTION_SSH" "sudo awk -F' = ' '/^email =/{print \\$2; exit}' /etc/letsencrypt/renewal/*.conf")"

test -s "$tmpdir/wireguard-private-key"
test -n "$mini_public_key"
test -n "$acme_email"

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
