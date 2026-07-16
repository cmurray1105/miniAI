#!/usr/bin/env bash
set -euo pipefail

# Install a repository-scoped GitHub Actions runner on the Mac mini.
#
# Required once beforehand:
#   gh auth login -h github.com
# The signed-in account needs repository administration permission because the
# script requests a short-lived Actions runner registration token. No GitHub
# token is written to disk by this script. Re-run with --replace to reconcile a
# stale local directory or GitHub registration without manual console cleanup.

REPOSITORY="${GITHUB_REPOSITORY:-cmurray1105/miniAI}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-miniai-mac-mini}"
RUNNER_LABELS="${RUNNER_LABELS:-miniai}"
REPLACE=false

case "${1:-}" in
  "") ;;
  --replace) REPLACE=true ;;
  *)
    echo "Usage: $0 [--replace]" >&2
    exit 2
    ;;
esac

require() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require gh
require curl
require tar

gh auth status -h github.com >/dev/null

# A runner can be registered at GitHub while its local service installation
# failed. --replace makes this normal reconciliation, rather than a manual UI
# and filesystem cleanup exercise. The delete is limited to this repo and the
# configured runner name.
runner_id="$(gh api "repos/$REPOSITORY/actions/runners?per_page=100" \
  --jq ".runners[] | select(.name == \"$RUNNER_NAME\") | .id" | head -n 1)"

if [[ -e "$RUNNER_DIR" || -n "$runner_id" ]]; then
  if [[ "$REPLACE" != true ]]; then
    echo "Runner state already exists (directory or GitHub registration)." >&2
    echo "Re-run with --replace to reconcile runner '$RUNNER_NAME' safely." >&2
    exit 1
  fi

  if [[ -x "$RUNNER_DIR/svc.sh" ]]; then
    "$RUNNER_DIR/svc.sh" stop >/dev/null 2>&1 || true
    "$RUNNER_DIR/svc.sh" uninstall >/dev/null 2>&1 || true
  fi
  if [[ -n "$runner_id" ]]; then
    gh api --method DELETE "repos/$REPOSITORY/actions/runners/$runner_id" >/dev/null
  fi
  rm -rf "$RUNNER_DIR"
fi

token="$(gh api --method POST "repos/$REPOSITORY/actions/runners/registration-token" --jq .token)"
release="$(gh api repos/actions/runner/releases/latest --jq .tag_name)"
version="${release#v}"
archive="actions-runner-osx-arm64-${version}.tar.gz"

mkdir -p "$RUNNER_DIR"
trap 'rm -f "$RUNNER_DIR/$archive"' EXIT
curl --fail --location --retry 3 \
  --output "$RUNNER_DIR/$archive" \
  "https://github.com/actions/runner/releases/download/${release}/${archive}"
tar -xzf "$RUNNER_DIR/$archive" -C "$RUNNER_DIR"

cd "$RUNNER_DIR"
./config.sh --unattended \
  --url "https://github.com/$REPOSITORY" \
  --token "$token" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --work "_work"

# GitHub's macOS service wrapper creates a per-user launchd service. It
# explicitly rejects sudo: the runner must run as the same unprivileged user
# that owns the checkout and Homebrew services.
./svc.sh install
./svc.sh start

echo "Runner installed. Confirm the labels in GitHub: Settings → Actions → Runners."
