# Knowledge Base — hierarchical curated KB from transcripts

Status: build, Phases 1–4 done, Phase 5 in progress
Date: 2026-08-13

## Goal

Add a Knowledge Base section to the BB website: hierarchical tree of curated
pages (architecture → patterns → hexagonal → detail) plus a full
keyword/tool/pattern index. Each page links to the projects and transcripts
where it was observed.

## Decisions (user-approved)

- Publish gate: draft by default; >=2 corroborating transcripts auto-publish.
- Root taxonomy: 10 seed roots (architecture, testing, debugging, devops,
  performance, **cybersecurity**, tooling, workflow, integrations,
  ai-engineering); discovery builds subtrees below.
- Entity index: all types — tool, library, framework, pattern, technique,
  concept.
- Backfill: last 90 days first, then full history.

## Deployment target (revised mid-build)

**k3s homelab cluster** (single node `k3s-cp-1`, VM on Mac-mini host).
NOT the Mac Studio. The Mac Studio stays the NFS server for the
external drive (exported over tailnet at `100.116.31.6:/Users/Shared/
cluster-nfs/pv`).

| Thing | Value |
|---|---|
| Cluster | `k3s-cp-1` (Mac-mini host VM) |
| kubeconfig | `~/cluster-migration/kube/kubeconfig.yaml` |
| Registry | `forgejo.tail5d39b4.ts.net/jakub/burdello-bum-bum` |
| StorageClass (data) | **`nfs-studio`** — keeps Postgres / Qdrant / Redis volumes on the external drive over tailnet |
| Public exposure | Tailscale Funnel sidecar; hostname `burdello` → `https://burdello.tail5d39b4.ts.net` |
| Namespace | `burdello` |
| Local docker-compose | Stays for offline dev only; live traffic goes through k3s |

## Data model (new tables)

### kb_nodes — tree
- `id` uuid PK
- `parent_id` uuid FK self nullable (root = null)
- `slug` unique
- `title`
- `node_type` enum category|topic|subcategory
- `summary` markdown (curated)
- `embedding` Vector(768)
- `status` enum draft|published|archived (draft default)
- `mechanical_key` unique nullable — lustro dedup key `topic:term1:term2`
- `top_terms` JSONB
- `confidence` float
- `metadata_` JSONB
- `created_at`/`updated_at` (TimestampMixin)
- `source_evidence_count` int — corroborating transcript count for auto-publish

### kb_node_sources — evidence links
- `id`
- `node_id` FK kb_nodes CASCADE
- `transcript_id` FK nullable
- `chunk_id` FK nullable
- `project_id` FK nullable
- `excerpt` text
- `evidence_type` enum worked_example|solved_problem|decision|pitfall|pattern
- `outcome` enum worked|failed|mixed nullable
- `confidence` float
- unique(node_id, chunk_id) — no duplicate evidence

### kb_entities — keyword/tool index
- `id`
- `canonical_name` unique
- `aliases` JSONB list
- `entity_type` enum tool|library|framework|pattern|technique|concept
- `description` text
- `how_used` text
- `why_used` text
- `embedding` Vector(768)

### kb_entity_mentions — entity occurrences
- `id`
- `entity_id` FK kb_entities CASCADE
- `node_id` FK kb_nodes nullable
- `transcript_id` FK nullable
- `project_id` FK nullable
- `context_excerpt` text
- `outcome` enum worked|failed|mixed nullable
- `first_seen` / `last_seen` timestamp
- unique(entity_id, chunk_id)

## Pipeline

1. Extract knowledge atoms (new Celery task after mine). Injection-safe prompt
   (QA router pattern, `<source_data>` delimiters). Output:
   `{name, kind, summary, excerpt, outcome, confidence}`. Scrub secrets.
2. Entity index: deterministic (code blocks, tool calls, CLI paths) + LLM pass.
   Alias merge >=0.87 cosine, keep most frequent canonical.
3. Clustering job (periodic, offline). Agglomerative + cosine. c-TF-IDF terms.
   LLM display labels (soft-fail). Silhouette scoring.
4. RAPTOR hierarchy under 10 seed roots. scipy linkage over cluster reps.
5. Incremental: new atoms matched by cosine — >=0.87 attach, 0.80–0.87 review,
   <0.80 new candidate. Weekly recluster preserves confirmed mechanical_keys.
6. Gate: draft default. >=2 corroborating transcripts auto-publish.

## Search integration

- Qdrant collection `bb_knowledge`; payload indexes node_id, project_id,
  entity_type.
- QA `/api/v1/search/qa` two-stage: KB pages first, chunks second.
- MCP tools: `kb_tree`, `kb_page_read`, `kb_entity_lookup`.

## Frontend

- `/knowledge` tree explorer
- `/knowledge/:slug` page: summary, subpages, evidence cards → transcript/project links
- `/knowledge/index` entity index (filter by type/project)
- `/knowledge/entity/:slug` detail: how/when/why, mentions timeline, linked pages
- Draft/published badge + admin confirm/merge/reparent

## Phases

1. ✅ Schema + migration — `f4a6ba0`
2. ✅ Extraction prompt + Celery task — `ce19ce3`
3. ✅ Clustering + RAPTOR hierarchy + draft generation — `5e8a7d0`
4. ✅ Frontend tree + node pages + entity index — `d6ca48e`
5. 🔄 QA two-stage retrieval + incremental assignment + k3s manifests
6. ⏳ MCP tools (kb_tree, kb_page_read, kb_entity_lookup)

## Phase 5 detail (current)

- **QA two-stage**: `/api/v1/search/qa` first retrieves top KB pages by
  embedding cosine, then falls through to chunk search. KB pages are
  surfaced as a separate citation kind so the LLM can ground on curated
  knowledge rather than raw transcript chunks when available.
- **Incremental atom assignment**: per-new-transcript. After
  `knowledge_extract_task` extracts atoms, each is matched against
  existing `KbNode` rows by cosine — ≥0.87 attach to existing node,
  0.80–0.87 queue for review, <0.80 spawn new candidate. Reuses the
  calibrated lustro-style bands.
- **Periodic recluster**: `kb_cluster_task` already exists. Wire into a
  Celery beat schedule (weekly). mechanical_key + deterministic slug
  dedup means re-runs update in place rather than duplicating.
- **k3s deployment**: `k8s/` directory — namespace, secrets stubs,
  PVCs on `nfs-studio`, deployments for postgres / qdrant / redis /
  backend / celery-worker / celery-mining / celery-beat / frontend,
  ts-funnel sidecar for public exposure. Build/push script for
  forgejo registry (amd64).

## Risks

- Prompt injection via transcripts → delimited framing + gate + secret scrub
- LLM cost on large corpus → mine completed transcripts, batch by project
- Cluster drift → mechanical keys + calibrated bands + global recluster
- Noise KB → confidence floors (atom >=0.6, bands >=0.8) + curation UI

## First backfill scope

Last 90 days. Then full history batch by project.