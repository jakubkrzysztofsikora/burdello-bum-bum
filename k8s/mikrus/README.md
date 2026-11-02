# Burdello on k3s-mikrus-1

Overlay that runs Postgres, Redis and one default plus one mining Celery worker on
`k3s-mikrus-1` (namespace `burdello`). The backend, frontend, beat and the Qdrant forwarder stay
on the Mac Studio (Qdrant itself is already on Mikrus). This is not the stock `k8s/` stack: it
matches the Studio's runtime settings (`all-mpnet-base-v2`, chunk 512/50, the existing Qdrant, the
NexGate LiteLLM, per-queue `BB_MINING_MODEL`) and uses `local-path` storage because
`k3s-mikrus-1` has no NFS client.

Status: applied and live since 2026-10-14. Data was restored from a verified dump (22 of 22 table
row counts identical) and the Studio backend and beat were switched to it.

## Endpoints

| Service | In cluster | From the Studio (tailnet) |
|---|---|---|
| Postgres | `postgres.burdello:5432` | `100.127.6.70:30543` |
| Redis | `redis.burdello:6379` | `100.127.6.70:30379` (password required) |
| Qdrant | host `100.127.6.70:6333` | `100.127.6.70:6333` |

## Image

Built natively on Mikrus (amd64) from the Burdello working tree (`Dockerfile`, `pyproject.toml`,
`backend/`, `.hf-cache/` baked with `all-mpnet-base-v2`, `HF_HUB_OFFLINE=1`) and imported into k3s
containerd; it is not pushed to Forgejo:

```bash
docker build --target production -t burdello-bum-bum:mikrus .
docker save burdello-bum-bum:mikrus | k3s ctr -n k8s.io images import -
docker rmi burdello-bum-bum:mikrus && docker builder prune -af
```

The pods use `docker.io/library/burdello-bum-bum:mikrus` with `imagePullPolicy: Never`, so the
image only exists on that node. Rebuild it there after backend code changes, then
`kubectl -n burdello rollout restart deploy/celery-worker deploy/celery-mining`.

## Secret (create out of band, never commit)

`burdello-secrets` keys: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `DATABASE_URL`
(`postgresql+asyncpg://bbuser:<pw>@postgres.burdello.svc.cluster.local:5432/burdello`), `REDIS_URL`
(`redis://:<pw>@redis.burdello.svc.cluster.local:6379/0`), `CELERY_BROKER_URL` (same host, `/1`),
`LITELLM_API_KEY`. The generated passwords are kept in `~/.config/burdello-k8s/secrets.env`
(mode 600) for the Studio side.

## How the Studio is wired

The repo `.env` (mode 600) holds `BB_DATABASE_URL`, `BB_REDIS_URL` and `BB_CELERY_BROKER_URL`
pointing at the NodePorts above. The untracked `docker-compose.override.yml` feeds them to
`backend` and `celery-beat`, and puts `postgres`, `redis`, `celery-worker` and `celery-mining`
under the compose profile `legacy` so `docker compose up` never starts a local database. The
`com.burdello.host-*` LaunchAgents are unloaded and disabled.

## Redeploy / verify

```bash
kubectl apply -k k8s/mikrus
kubectl -n burdello get pods -o wide
kubectl -n burdello logs deploy/celery-worker --tail=30
```

## Rollback

The pre-cutover Postgres data directory and a verified dump are in `~/burdello-pg-backup/`. To
roll back: scale `celery-worker` and `celery-mining` to 0, dump the cluster database back if any
data was written after cutover, restore the pre-cutover override (`/tmp/bb-override.pre-cutover.yml`
if still present), drop the `legacy` profiles, and run `docker compose --profile legacy up -d`.

## Known gaps

- Postgres uses a single `local-path` PVC on the node's disk (no replication); keep regular dumps.
- The NodePorts listen on the node's LAN and tailnet addresses (password protected); there is no
  host firewall rule limiting them to the tailnet.
- Embeddings run on CPU (2 vCPU); expect slower ingestion than the Studio's MPS path.
- The image lives only in that node's containerd store.
