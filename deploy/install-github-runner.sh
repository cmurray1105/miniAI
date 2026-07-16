#!/usr/bin/env bash
set -euo pipefail

# Install a repository-scoped GitHub Actions runner on the Mac mini.
#
# Required once beforehand:
#   gh auth login -h github.com
# The signed-in account needs repository administration permission because the
# script requests a short-lived Actions runner registration token. No GitHub
# token is written to disk by this script.

REPOSITORY="${GITHUB_REPOSITORY:-cmurray1105/miniAI}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-$(scutil --get ComputerName 2>/dev/null || hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-miniai}"

require() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require gh
require curl
require tar

if [[ -e "$RUNNER_DIR" ]]; then
  echo "$RUNNER_DIR already exists; refusing to overwrite an existing runner." >&2
  echo "To replace it, remove the runner in GitHub first and choose a new RUNNER_DIR." >&2
  exit 1
fi

gh auth status -h github.com >/dev/null
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

# GitHub's service wrapper creates a per-user launchd service on macOS.
sudo ./svc.sh install "$(id -un)"
sudo ./svc.sh start

echo "Runner installed. Confirm the labels in GitHub: Settings → Actions → Runners."
