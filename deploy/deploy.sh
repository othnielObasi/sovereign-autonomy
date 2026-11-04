#!/bin/sh
# Update the server to GitHub main and rebuild. Run on the server: /srv/sovereign/app/deploy/deploy.sh
set -eu
cd /srv/sovereign/app
git fetch --quiet origin main
git reset --quiet --hard origin/main
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build --remove-orphans
docker image prune -f >/dev/null
git log --oneline -1
