#!/usr/bin/env bash
set -euo pipefail

# On-demand lifecycle for the Studio burdello compose stack.
# up       health-check, start if down (delegates to burdello-recall/ensure_ready.sh)
# down     stop all non-legacy services (backend, frontend, celery-beat, celery-worker, qdrant)
# autodown stop only if a previous `up` on this machine started the stack (marker-gated; hook use)
# status   container states + API health
# Run from a non-studio host (e.g. MacBook): transparently re-executes over ssh on macstudio.

MARKER=/tmp/burdello.auto-up
REPO="$HOME/Repos/personal/burdello-bum-bum"
READY="${BURDELLO_READY:-$HOME/.claude/skills/burdello-recall/ensure_ready.sh}"

PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ "$(hostname -s)" != "Mac-Studio-Jakub" ]]; then
  # ssh session + wrong host = renamed studio; relaying again would loop
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    echo "burdello: hostname is $(hostname -s), not Mac-Studio-Jakub; refusing to relay from inside ssh" >&2
    exit 1
  fi
  exec ssh macstudio "$HOME/bin/burdello $*"
fi

case "${1:-status}" in
  up)
    # touch first: a killed or failed up can still leave containers running; autodown needs the marker
    touch "$MARKER"
    out=$(bash "$READY")
    printf '%s\n' "$out"
    ;;
  down)
    (cd "$REPO" && docker compose stop backend frontend celery-beat celery-worker qdrant)
    rm -f "$MARKER"
    ;;
  autodown)
    if [ -f "$MARKER" ]; then
      exec "$0" down
    fi
    ;;
  status)
    docker ps --filter name=bb- --format '{{.Names}}\t{{.Status}}' || true
    if curl -fsS -m3 http://127.0.0.1:8001/health; then
      echo
    else
      echo 'api down'
    fi
    ;;
  *)
    echo "usage: burdello {up|down|autodown|status}" >&2
    exit 2
    ;;
esac
