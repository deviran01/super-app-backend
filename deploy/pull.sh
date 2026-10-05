#!/usr/bin/env bash
# Copies what is live on the server back into this repository — the published catalog and
# release rules, and the images uploaded from the admin dashboard — so git keeps a history
# and a fresh server can be seeded from it. Never pulls data/admin/ (accounts, drafts) or
# data/stats/ (usage statistics).
#
#   deploy/pull.sh && git diff --stat
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$HERE/.env" ] && . "$HERE/.env"
HOST="${DEPLOY_HOST:?Set DEPLOY_HOST=user@host (environment or deploy/.env)}"
REMOTE="${DEPLOY_DIR:-/srv/superapp}"

RSYNC=(rsync -rlt --rsync-path="sudo rsync")
"${RSYNC[@]}" "$HOST:$REMOTE/data/catalog.json" "$HOST:$REMOTE/data/release.json" "$ROOT/data/"
"${RSYNC[@]}" "$HOST:$REMOTE/public/logos/" "$ROOT/public/logos/"
"${RSYNC[@]}" "$HOST:$REMOTE/public/icons/" "$ROOT/public/icons/"
echo "Pulled the live catalog, release rules and images."
