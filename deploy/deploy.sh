#!/usr/bin/env bash
# Publishes the API to the server:
#   1. checks data/ locally (the same checks the API runs before serving a file);
#   2. uploads the code, then images, then data/ last, so a client never gets a catalog whose
#      images aren't there yet;
#   3. rebuilds the image if the code changed and (re)starts the container; content-only
#      changes are picked up by the running API without a restart.
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

cd "$ROOT"
python3 -c 'from app.content import ContentStore; ContentStore()' # fails on unusable data

# World-readable: the container runs as an unprivileged user. (Set here rather than with
# rsync --chmod, which macOS's rsync lacks.)
chmod -R u=rwX,go=rX app scenarios data public/logos public/icons
chmod 644 Dockerfile requirements.txt compose.yaml .dockerignore

RSYNC=(rsync -rlpt --rsync-path="sudo rsync")
ssh "$HOST" "sudo mkdir -p $REMOTE/public $REMOTE/data"
"${RSYNC[@]}" --delete --exclude __pycache__ app scenarios "$HOST:$REMOTE/"
"${RSYNC[@]}" Dockerfile requirements.txt compose.yaml .dockerignore "$HOST:$REMOTE/"
"${RSYNC[@]}" public/logos public/icons "$HOST:$REMOTE/public/"
"${RSYNC[@]}" --delete data/ "$HOST:$REMOTE/data/"
# Only now drop images the new catalog no longer references (and anything not served).
"${RSYNC[@]}" --delete public/logos public/icons "$HOST:$REMOTE/public/"
ssh "$HOST" "cd $REMOTE && sudo find public -mindepth 1 -maxdepth 1 ! -name logos ! -name icons -exec rm -rf {} + \
  && sudo docker compose up -d --build --remove-orphans --wait --wait-timeout 90 \
  && curl -fsS http://127.0.0.1:8120/health >/dev/null"
echo "Deployed. Live: https://${DEPLOY_DOMAIN:-superapp.2z2.ir}/api/v1/config"
