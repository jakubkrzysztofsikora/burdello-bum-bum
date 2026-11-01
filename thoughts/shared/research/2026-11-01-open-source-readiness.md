---
date: 2026-11-01
commit: da9b14f4a46e105edb9d29161fbaa932be76a32f
branch: main
tags: [open-source, readme, setup, portability, infrastructure]
status: complete
---
# Research: Open-Source Readiness — Repo Portability, README, and Local-Infra Independence

## Summary

The repo is **not yet open-source-ready**. Three blockers prevent a new user from bootstrapping: (1) the Qdrant service in `docker-compose.yml` is a socat forwarder to the author's private tailnet IP (`100.127.6.70`), not a local Qdrant instance; (2) the `Dockerfile` hard-`COPY`s a `.hf-cache/` directory that is gitignored and absent from a fresh clone, breaking `docker compose up --build`; (3) no `LICENSE` file exists despite the README claiming MIT. Beyond blockers, `deploy/`, `k8s/`, `worker/`, and `scripts/` are tightly coupled to the author's machine (Mac-Studio-Jakub, Mikrus, tailnet, Forgejo registry, Cloudflare domain). The core app (Postgres, Redis, backend, Celery, frontend) is self-hostable and portable once Qdrant and the Dockerfile are fixed.

## Files Involved

### Blockers (must fix before open-sourcing)

| File | Layer | Issue |
|------|-------|-------|
| `docker-compose.yml:31-55` | Infra | Qdrant service = socat forwarder to `100.127.6.70:6333` (author's Mikrus VPS over tailnet). New user has no route to this IP. |
| `Dockerfile:70` | Build | `COPY .hf-cache /opt/hf-cache` — `.hf-cache/` is gitignored (`.gitignore:69`), absent from fresh clone. `docker build` fails. |
| `LICENSE` (missing) | Legal | README:184 claims "MIT" but no LICENSE file exists. |

### Author-specific (works for author, breaks for new user)

| File | Layer | Issue |
|------|-------|-------|
| `deploy/burdello-lifecycle.sh:12,17-23` | Deploy | Hard-codes `REPO="$HOME/Repos/personal/burdello-bum-bum"`, hostname gate `Mac-Studio-Jakub`, SSH alias `macstudio`. |
| `deploy/launchd/com.burdello.host-api.plist:9` | Deploy | Absolute `/Users/jakubsikora/...` paths. Same in all 5 launchd plists. |
| `deploy/compose-up.sh:14-16` | Deploy | Refuses to start if `docker-compose.override.yml` missing — new user has no override. |
| `deploy/compose.qdrant-mikrus.yaml:7` | Deploy | Author tailnet bind + `/opt/burdello-qdrant` path. |
| `deploy/burdello-qdrant.service:10` | Deploy | Systemd unit requires Tailscale interface + `/opt/burdello-qdrant`. |
| `deploy/QDRANT-MIKRUS-OPERATIONS.md` | Docs | Author-specific: remote paths, tailnet, SSH, NFS. |
| `k8s/configmap.yaml:7` | K8s | Hard-coded author LiteLLM tailnet hostname. |
| `k8s/backend.yaml:20` | K8s | Images from private author Forgejo registry. |
| `k8s/mikrus/configmap.yaml:8` | K8s | Author Qdrant tailnet IP. |
| `k8s/mikrus/README.md:1` | K8s | Targets `k3s-mikrus-1`, Studio, NexGate. |
| `worker/wrangler.jsonc:8` | Worker | Custom domain `burdello-mcp.jakub.team`, API URL `mac-studio-jakub.tail5d39b4.ts.net`. |
| `scripts/run-burdello-host.sh:11-31` | Scripts | Hard-codes `/Volumes/models/hf`, `.venv`, localhost URLs. macOS-only. |
| `scripts/refresh-agent-exports.sh` | Scripts | macOS `~/Library/Logs` path, assumes `.venv`. |
| `scripts/export_goose_sessions.py:2-23` | Scripts | Hard-coded `~/.local/share/goose/` paths, not configurable. |
| `scripts/export_opencode_sessions.py:2-31` | Scripts | Hard-coded `~/.local/share/opencode/` paths, not configurable. |
| `deploy/host_service.py:42` | Deploy | Overrides local URLs/ports, Homebrew PATH, reads `.hf-token`. |

### Already portable (works for new user)

| File | Layer | Status |
|------|-------|--------|
| `docker-compose.yml:5-25` | Postgres | `ankane/pgvector:latest`, named volume, `bbuser:bbpass` defaults. Works. |
| `docker-compose.yml:57-90` | Redis | Redis 7, named volume. Works. |
| `docker-compose.yml:95-151` | Backend | Builds from Dockerfile, env vars, healthcheck. Works (once Dockerfile fixed). |
| `docker-compose.yml:156-262` | Celery | Workers + beat, resource limits. Works. |
| `docker-compose.yml:300-326` | Frontend | Vite dev server, npm install on start. Works. |
| `backend/core/config.py:19-45` | Config | Env-var-driven defaults, `localhost` fallbacks. Portable. |
| `backend/pipeline/embedding.py` | Embedding | sentence-transformers, local inference. Portable (needs model download). |
| `backend/pipeline/model_cache.py:21-64` | Model | Downloads from HuggingFace if not cached. Portable. |
| `backend/migrations/` | DB | Alembic + `create_all` on first start. Portable. |
| `frontend/vite.config.ts:4-39` | Frontend | Proxies to `VITE_API_PROXY` (default `localhost:8000`). Portable. |
| `.env.example:1-14` | Config | Documents optional integrations. Good. |
| `.gitignore` | Config | Excludes `.env`, `.hf-cache`, override, secrets. Good. |

## Data Flow (new user bootstrap path)

```
git clone → cp .env.example .env → docker compose up -d --build
                                                         │
                                                         ├─ postgres (pgvector) ✓
                                                         ├─ redis ✓
                                                         ├─ qdrant ✗ (socat → 100.127.6.70, unreachable)
                                                         ├─ backend build ✗ (COPY .hf-cache fails, dir absent)
                                                         ├─ celery-worker ✗ (depends on backend image)
                                                         ├─ celery-beat ✗ (depends on backend image)
                                                         └─ frontend ✓ (node:20-alpine, npm install)
```

**Two failure points** in the default path. Both are fixable with tracked-file changes.

## Existing Patterns

### What works well (templates for the fix)

1. **Env-var-driven config** (`backend/core/config.py:19-45`): every service URL is an env var with a `localhost` default. This is the right pattern. Qdrant just needs the same treatment in compose.

2. **Postgres/Redis in compose** (`docker-compose.yml:5-25,57-90`): self-contained services with named volumes and healthchecks. Qdrant should follow this pattern — replace the socat forwarder with `qdrant/qdrant:latest` and a named volume.

3. **`.env.example`** (`:1-14`): documents optional integrations (LiteLLM, Todoist, MCP, Cloudflare). The Qdrant URL should be added here as `QDRANT_URL` with default `http://qdrant:6333` (compose-internal).

4. **Model download fallback** (`backend/pipeline/model_cache.py:21-64`): already downloads the embedding model from HuggingFace if not cached locally. The Dockerfile's `HF_HUB_OFFLINE=1` + `COPY .hf-cache` is a workaround for the author's corporate TLS proxy, not a fundamental requirement. A portable Dockerfile would let the model download at first run instead of baking it in.

### Author's local flow (what must keep working)

The author's `docker-compose.override.yml` (gitignored) overrides:
- Postgres → remote tailnet DB
- Redis → remote tailnet Redis
- Qdrant → already forwarded to Mikrus
- Frontend hosts → author-specific
- Transcript mounts → MacBook session dir

**Key insight**: the author's local flow uses the override file, which is gitignored. Any changes to the base `docker-compose.yml` must not break the override merge. Using env vars with defaults (rather than hard-coded values) keeps both paths working.

## Architecture Notes

### Layer boundaries

- **Core app** (backend, Celery, frontend, Postgres, Redis): self-contained, env-var-driven, portable. Ready for open source.
- **Qdrant**: the only core dependency that is NOT self-contained in compose. This is the primary blocker.
- **Dockerfile**: couples to author's TLS proxy workaround (`.hf-cache` bake). Needs a portable build path.
- **deploy/**: author's personal lifecycle scripts (launchd, ssh relay, hostname gate). Not for new users.
- **k8s/**: author's private cluster manifests (Forgejo, tailnet, Mikrus). Not for new users.
- **worker/**: author's Cloudflare Worker (private domain, tailnet API URL). Optional, not needed locally.
- **scripts/**: author's export utilities (hard-coded paths, macOS-only). Useful as reference but not portable.

### What "local-infra independence" means here

The goal: a new user clones, `cp .env.example .env`, `docker compose up -d --build`, and everything works with zero knowledge of the author's infrastructure. The author's local flow (override file, tailnet, Mikrus) must continue to work via gitignored overrides, not tracked hard-coding.

### System requirements (current evidence)

| Source | Requirement |
|--------|-------------|
| `README.md:22-24` | Docker Compose v2, ~8 GB RAM, optional LiteLLM endpoint |
| `docker-compose.yml` mem limits | Postgres 1g, Qdrant 128m, Redis 4g, backend 2g, worker 8g, beat 1500m, frontend 256m, cloudflared 1g |
| `Dockerfile:8` | Python 3.12-slim |
| `frontend/Dockerfile.k8s` | Node 20 |
| Embedding model | `sentence-transformers/all-mpnet-base-v2`, ~420 MB download |

**Problem**: README says "~8 GB RAM for the stack" but per-service limits sum to ~18 GB. The 8 GB figure is likely the author's practical minimum (services don't all peak simultaneously), but it's not documented how that number was derived. A new user with 8 GB may hit OOM on the worker (8g limit) if mining runs. The README should clarify: 8 GB minimum for ingest+search, 16+ GB recommended if mining with local LLM.

**Missing from README**:
- CPU requirements (no CPU limits in compose, no guidance)
- Disk requirements (Postgres volume, Qdrant volume, model cache ~420 MB, Docker images)
- OS requirements (Docker Desktop on macOS/Linux, Docker Engine on Linux; no Windows guidance)
- Network requirements (HuggingFace access for model download, optional LiteLLM endpoint)

## External Dependencies

| Service | Required? | New user needs | Author's setup |
|---------|-----------|----------------|----------------|
| PostgreSQL + pgvector | Yes | Compose provisions it | Override → remote tailnet DB |
| Qdrant | Yes | **Must run locally** (currently broken) | Forwarder → Mikrus VPS |
| Redis | Yes | Compose provisions it | Override → remote tailnet Redis |
| HuggingFace | For embeddings | Model download (~420 MB) on first run | Pre-baked in `.hf-cache` |
| LiteLLM endpoint | For mining only | Any OpenAI-compatible gateway | Author's NexGate (tailnet) |
| Cloudflare | Optional | Account for Worker/Tunnel | Author's domain + tunnel |
| Todoist | Optional | API token | Author's token |
| Tailscale | Not for new user | Not needed | Author's tailnet to Mikrus |
| MCP bridge | Optional | `MCP_BRIDGE_TOKEN` | Author's OMP extension |

## Open Questions

1. **Qdrant fix approach**: Replace the socat forwarder in `docker-compose.yml` with `qdrant/qdrant:latest` + named volume (standard approach), or make the forwarder target configurable via env var (preserves author's Mikrus setup without override)? The env-var approach is more flexible but adds complexity. **Recommendation**: use `qdrant/qdrant:latest` in base compose; author overrides via gitignored `docker-compose.override.yml` to restore the forwarder.

2. **Dockerfile `.hf-cache` fix**: Remove the `COPY .hf-cache` and let the model download at first container start (simpler, portable, but needs network access and ~420 MB download on first run), or make it a conditional build arg (preserves author's bake, adds build complexity)? **Recommendation**: remove the bake; set `HF_HUB_OFFLINE=0` by default; author can override via build arg or override Dockerfile.

3. **deploy/ and k8s/ directories**: Move to a separate `infra-personal/` repo, or keep in-repo with a clear "author-specific, not for new users" disclaimer in README? **Recommendation**: keep in-repo (they're useful reference), add README section "Author-specific infrastructure" explaining these are not needed for local use.

4. **scripts/ portability**: Make export scripts configurable via env vars (portable), or document them as author-specific? **Recommendation**: add env var overrides with sensible defaults; minimal effort, maximum portability.

5. **System requirements**: Should the README state a higher minimum (16 GB) to cover mining, or keep 8 GB with a "mining needs more" note? **Recommendation**: 8 GB minimum for ingest+search, 16 GB recommended for mining, 4 GB disk for volumes + images + model.

6. **LICENSE file**: Add MIT LICENSE file (matches README claim), or choose a different license? **Recommendation**: add MIT LICENSE file — it's already claimed in README.
