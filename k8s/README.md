# Burdello Bum-Bum — k3s deployment

Production deployment of the KB-equipped stack on the homelab k3s cluster.

## Topology

| Pod | Containers | Purpose |
|---|---|---|
| `postgres` (StatefulSet) | `postgres` | pgvector — transcripts, KB tables |
| `qdrant` (Deployment) | `qdrant` | vector index over chunks + KB nodes |
| `redis` (Deployment) | `redis` | Celery broker + result backend |
| `backend` (Deployment) | `backend` + `frontend` + `ts-funnel` | FastAPI :8000, nginx :3000 (vite dist), public funnel |
| `celery-worker` (Deployment) | `worker` | default queue (extract, embed, KB incremental) |
| `celery-mining` (Deployment) | `worker` | mining queue (mine_task, knowledge_extract_task, kb_cluster_task) |
| `celery-beat` (Deployment) | `beat` | schedules weekly `kb_cluster_task` |

All volumes use the `nfs-studio` StorageClass → external drive
`100.116.31.6:/Users/Shared/cluster-nfs/pv` over tailnet. Keep data on
the external drive, not the k3s node's local disk.

## External image

- Registry: `forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum`
- Frontend image: `forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum-frontend`

Build & push from the repo root:

```bash
IMG=forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum
docker login forgejo.tail5d39b4.ts.net -u jakub
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --tag "$IMG:$(git rev-parse --short HEAD)" --tag "$IMG:latest" --push .

FE=forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum-frontend
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  -f frontend/Dockerfile.k8s --tag "$FE:latest" --push frontend/
```

## Pre-flight

1. Cluster must have the registry mirror configured (see
   `~/.claude/skills/homelab-k3s-deploy`).
2. Tailnet ACL must include:
   - `tagOwners: "tag:burdello": ["tag:jakub"]`
   - `nodeAttrs: {"target": ["tag:burdello"], "attr": ["funnel"]}`
3. Mint a Tailscale authkey tagged `tag:burdello` (reusable+ephemeral+preauth).
4. Create namespace + secrets:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n burdello create secret docker-registry forgejo-registry \
  --docker-server=forgejo.tail5d39b4.ts.net \
  --docker-username=jakub \
  --docker-password="$FORGEJO_PASSWORD"

kubectl -n burdello create secret generic ts-sidecar-auth \
  --from-literal=TS_AUTHKEY="$TS_AUTHKEY_BURDELLO"

kubectl -n burdello create secret generic burdello-secrets \
  --from-literal=POSTGRES_PASSWORD="$BB_DB_PW" \
  --from-literal=DATABASE_PASSWORD="$BB_DB_PW" \
  --from-literal=LITELLM_API_KEY="$LITELLM_KEY"
```

## Bring-up

```bash
kubectl apply -k k8s/
kubectl -n burdello rollout status deploy/postgres
kubectl -n burdello rollout status deploy/qdrant
kubectl -n burdello rollout status deploy/redis
kubectl -n burdello rollout status deploy/backend
kubectl -n burdello rollout status deploy/celery-worker
kubectl -n burdello rollout status deploy/celery-mining
kubectl -n burdello rollout status deploy/celery-beat

# Verify public funnel warmed (~30s after ts-funnel starts)
curl -sSf https://burdello.tail5d39b4.ts.net/health
```

## Update

```bash
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --tag forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum:latest --push .
kubectl -n burdello rollout restart deploy/backend deploy/celery-worker deploy/celery-mining
```

## Periodic KB rebuild

`celery-beat` triggers `kb_cluster_task` weekly. Manual kick:

```bash
kubectl -n burdello exec -it deploy/celery-mining -- \
  celery -A backend.pipeline.celery_app.celery_app call backend.knowledge.task.kb_cluster_task
```

## Data on external drive

`postgres-data`, `qdrant-data`, `redis-data` PVCs all bind to
`nfs-studio` → `/Users/Shared/cluster-nfs/pv` on Mac Studio (exported
over tailnet at `100.116.31.6`). Never use `local-path` for these —
data must survive node replacement.

## Local dev

Local `docker-compose.yml` stays as-is for offline development. The
k3s manifests are production-only.