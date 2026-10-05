#!/usr/bin/env bash
# Publishes the config backend to the server:
#   1. exports public/ as an upload-ready folder (checks it first);
#   2. uploads it to /srv/superapp/public — images first, config.json last, so a client never
#      sees a document whose images aren't there yet;
#   3. starts or updates the container (no restart when only content changed).
#
#   deploy/deploy.sh
#
# The target comes from DEPLOY_HOST (user@host with sudo), read from the environment or from
# deploy/.env, which is git-ignored: this repository is public, the server address isn't.
# One-time host setup (nginx site + certificate) is described in README.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$HERE/.env" ] && . "$HERE/.env"
HOST="${DEPLOY_HOST:?Set DEPLOY_HOST=user@host (environment or deploy/.env)}"
REMOTE="${DEPLOY_DIR:-/srv/superapp}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

python3 "$ROOT/tools/export_static.py" --out "$STAGE/public"
# World-readable: the container's nginx runs as an unprivileged user. (Set here rather than
# with rsync --chmod, which macOS's rsync lacks.)
chmod -R u=rwX,go=rX "$STAGE/public"
chmod 644 "$HERE/compose.yaml" "$HERE/nginx.conf"

RSYNC=(rsync -rlpt --rsync-path="sudo rsync")
ssh "$HOST" "sudo mkdir -p $REMOTE/public"
"${RSYNC[@]}" "$HERE/compose.yaml" "$HERE/nginx.conf" "$HOST:$REMOTE/"
"${RSYNC[@]}" --exclude /config.json "$STAGE/public/" "$HOST:$REMOTE/public/"
"${RSYNC[@]}" "$STAGE/public/config.json" "$HOST:$REMOTE/public/config.json"
# Only now drop images the new document no longer references.
"${RSYNC[@]}" --delete "$STAGE/public/" "$HOST:$REMOTE/public/"

ssh "$HOST" "cd $REMOTE && sudo docker compose up -d --wait --wait-timeout 60 && curl -fsS http://127.0.0.1:8120/health >/dev/null"
echo "Deployed. Live: https://${DEPLOY_DOMAIN:-superapp.2z2.ir}/config.json"
