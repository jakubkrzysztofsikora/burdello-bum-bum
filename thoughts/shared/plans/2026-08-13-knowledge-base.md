# Knowledge Base — hierarchical curated KB from transcripts

Status: approved (build), Phase 1 in progress
Date: 2026-08-13

## Goal

Add a Knowledge Base section to the BB website: hierarchical tree of curated
pages (architecture → patterns → hexagonal → detail) plus a full
keyword/tool/pattern index. Each page links to the projects and transcripts
where it was observed.

## Decisions (user-approved)

- Publish gate: draft by default; >=2 corroborating transcripts auto-publish.
- Root taxonomy: 10 seed roots (architecture, testing, debugging, devops,
  performance, security, tooling, workflow, integrations, ai-engineering);
  discovery builds subtrees below.
- Entity index: all types — tool, library, framework, pattern, technique,
  concept.
- Backfill: last 90 days first, then full history.

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

1. Schema + migration (this phase)
2. Extraction prompt + task
3. Clustering + hierarchy + draft generation
4. Frontend
5. QA + incremental + recluster cron
6. MCP tools

## Risks

- Prompt injection via transcripts → delimited framing + gate + secret scrub
- LLM cost on large corpus → mine completed transcripts, batch by project
- Cluster drift → mechanical keys + calibrated bands + global recluster
- Noise KB → confidence floors (atom >=0.6, bands >=0.8) + curation UI

## First backfill scope

Last 90 days. Then full history batch by project.