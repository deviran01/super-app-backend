#!/usr/bin/env bash
# Deploys the API and the admin dashboard to the server:
#   1. uploads the code and adds the repository's images (uploaded ones are never deleted);
#   2. seeds data/ on the very first deploy only — afterwards the admin dashboard owns it
#      (publish there; deploy/pull.sh copies the live data back into this repository);
#   3. builds the image here (linux/amd64) and loads it on the server — PyPI is slow or
#      unreachable from servers in Iran — then (re)starts the container. DEPLOY_BUILD=server
#      builds on the server instead.
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
# What goes live is what git records: uncommitted edits to deployed files are refused.
if [ -n "$(git status --porcelain -- app scenarios Dockerfile requirements.txt compose.yaml .dockerignore)" ] && [ "${DEPLOY_DIRTY:-}" != 1 ]; then
  echo "Uncommitted changes in deployed files: commit them first (or DEPLOY_DIRTY=1)." >&2
  exit 1
fi
python3 -c 'from app.content import ContentStore; ContentStore()' # fails on an unusable seed

# World-readable: the container runs as an unprivileged user. (Set here rather than with
# rsync --chmod, which macOS's rsync lacks.)
# data/admin/ (local accounts and signing key) is never uploaded and stays private.
chmod -R u=rwX,go=rX app scenarios public/logos public/icons
chmod 644 Dockerfile requirements.txt compose.yaml .dockerignore data/catalog.json data/release.json

RSYNC=(rsync -rlpt --rsync-path="sudo rsync")
ssh "$HOST" "sudo mkdir -p $REMOTE/public $REMOTE/data"
"${RSYNC[@]}" --delete --exclude __pycache__ app scenarios "$HOST:$REMOTE/"
"${RSYNC[@]}" Dockerfile requirements.txt compose.yaml .dockerignore "$HOST:$REMOTE/"
"${RSYNC[@]}" public/logos public/icons "$HOST:$REMOTE/public/"
# Seeds data/ on the first deploy only. --ignore-existing (decided by the receiving side) never
# replaces what the dashboard published, even if a connection hiccup made a remote check fail.
"${RSYNC[@]}" --ignore-existing data/catalog.json data/release.json "$HOST:$REMOTE/data/"
if [ "${DEPLOY_BUILD:-local}" = "server" ]; then
  UP="sudo docker compose up -d --build --remove-orphans --wait --wait-timeout 90"
else
  docker build --platform linux/amd64 -t superapp-api:latest .
  # The running image stays as :previous — one command away from a rollback:
  #   sudo docker tag superapp-api:previous superapp-api:latest && sudo docker compose up -d --no-build
  # The image it replaces as :previous is removed (only ours, and only when nothing uses it).
  ssh "$HOST" "old=\$(sudo docker images -q superapp-api:previous); sudo docker tag superapp-api:latest superapp-api:previous 2>/dev/null || true; \
    if [ -n \"\$old\" ] && [ \"\$old\" != \"\$(sudo docker images -q superapp-api:previous)\" ]; then sudo docker rmi \"\$old\" >/dev/null 2>&1 || true; fi"
  docker save superapp-api:latest | gzip -1 | ssh "$HOST" "gunzip | sudo docker load"
  UP="sudo docker compose up -d --no-build --remove-orphans --wait --wait-timeout 90"
fi
# The container (uid 10001) writes drafts, history, accounts and uploaded images.
ssh "$HOST" "cd $REMOTE && sudo find public -mindepth 1 -maxdepth 1 ! -name logos ! -name icons -exec rm -rf {} + \
  && sudo chown -R 10001:10001 data public \
  && $UP \
  && curl -fsS http://127.0.0.1:8120/health >/dev/null"
echo "Deployed. API: https://${DEPLOY_DOMAIN:-superapp.2z2.ir}/api/v1/config · Admin: https://${DEPLOY_DOMAIN:-superapp.2z2.ir}/admin/"
