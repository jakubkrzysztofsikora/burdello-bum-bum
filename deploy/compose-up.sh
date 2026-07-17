#!/usr/bin/env bash
set -euo pipefail
REPO="/Users/jakubsikora/Repos/personal/burdello-bum-bum"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

for _ in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 5
done

cd "$REPO"
exec docker compose up -d
