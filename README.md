# Burdello Bum-Bum

AI Session Transcript Processing System

Turn your AI coding assistant session transcripts into structured, searchable, actionable knowledge.

## Overview

Burdello Bum-Bum ("BB") is a **local-first** web application that:

- **Ingests** session transcripts from Claude Code, Kimi CLI, Vibe CLI, Codex CLI, Agy, Aider, and generic formats
- **Processes** transcripts into vectorized, searchable data via semantic chunking + embeddings
- **Mines** projects, tasks, threads, artifacts, and statuses using LLM-powered extraction
- **Searches** across everything with hybrid search (full-text + vector + metadata filters)
- **Displays** data hierarchically (Project > Task > Thread) with multiple detail levels
- **Exports** to Todoist for project/task synchronization

## Architecture

```
+-----------+     +-------------+     +---------------+
| React SPA | --> | FastAPI     | --> | PostgreSQL    |
| (Port     |     | (Port 8000) |     | + pgvector    |
|  3000)    |     +-------------+     +---------------+
+-----------+           |                     |
                        v                     v
                  +-------------+     +---------------+
                  | Qdrant      |     | LiteLLM       |
                  | (Vectors)   |     | Gateway       |
                  | (Port 6333) |     | (Port 4000)   |
                  +-------------+     +---------------+
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + TypeScript + Tailwind CSS + shadcn/ui |
| API | FastAPI (async) |
| Database | PostgreSQL 16 + pgvector |
| Vector Store | Qdrant |
| Embeddings | sentence-transformers (nomic-embed-text-v2) |
| LLM Gateway | LiteLLM proxy |
| Task Queue | Celery + Redis |
| Deployment | Docker Compose |

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Mac Studio or equivalent (Apple Silicon optimized)
- Tailscale (for network sharing)
- LiteLLM proxy running locally (default: `http://localhost:4000`)

### 1. Clone and Start

```bash
git clone https://github.com/jakubkrzysztofsikora/burdello-bum-bum.git
cd burdello-bum-bum

# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/health
```

### 2. Configure AI Data Directories

Mount your AI tool directories into the container. By default, the app looks for:

| Tool | Default Path | Override Env Var |
|------|-------------|-----------------|
| Claude Code | `~/.claude` | `BB_CLAUDE_DIR` |
| Kimi CLI | `~/.kimi` | `BB_KIMI_DIR` |
| Vibe CLI | `~/.vibe` | `BB_VIBE_DIR` |
| Codex CLI | `~/.codex` | `BB_CODEX_DIR` |
| Agy | `~/.gemini` | `BB_AGY_DIR` |
| Aider | `.aider.chat.history.md` in each project | N/A |

Edit `docker-compose.yml` to add volume mounts:

```yaml
volumes:
  - ~/.claude:/data/.claude:ro
  - ~/.codex:/data/.codex:ro
  - ~/.kimi:/data/.kimi:ro
  - ~/.vibe:/data/.vibe:ro
```

### 3. Configure LiteLLM

Set the LiteLLM gateway URL in `.env`:

```bash
LITELLM_URL=http://host.docker.internal:4000
LITELLM_API_KEY=your-key-if-needed
```

Or pass directly:

```bash
LITELLM_URL=http://litellm:4000 docker compose up -d
```

### 4. Ingest Transcripts

Click "Ingest" in the web UI or trigger via API:

```bash
curl -X POST http://localhost:8000/api/v1/ingest
```

The system will:
1. Scan all configured directories
2. Detect new/changed files
3. Extract transcripts using provider-specific skills
4. Chunk, embed, and store in vector DB
5. Mine for projects, tasks, and artifacts via LLM

## Features

### Provider Skills

| Skill | Provider | Format | Detection Pattern |
|-------|----------|--------|-------------------|
| ClaudeCodeSkill | Claude Code | JSONL | `~/.claude/projects/*/*.jsonl` |
| CodexSkill | OpenAI Codex | JSONL | `~/.codex/sessions/*/*/*/*.jsonl` |
| KimiSkill | Kimi CLI | JSONL | `~/.kimi/sessions/*/wire.jsonl` |
| VibeSkill | Vibe CLI | JSON | `~/.vibe/logs/session/*.json` |
| AgySkill | Agy | Mixed | `~/.gemini/antigravity-cli/` |
| AiderSkill | Aider | Markdown | `.aider.chat.history.md` |
| GenericSkill | Any fallback | Various | Any `.jsonl`, `.md`, `.txt` |

### Search

- **Hybrid Search**: Combines vector similarity + metadata filtering via Qdrant
- **Full-Text Search**: PostgreSQL tsvector for exact phrase matching
- **Similarity Matching**: Find semantically similar transcripts
- **Autocomplete**: Suggestions for projects, tasks, and content

### Data Mining (via LiteLLM)

- **Project Extraction**: Automatically identifies projects being worked on
- **Task Extraction**: Extracts actionable tasks within projects
- **Status Inference**: Determines if work is active, completed, or abandoned
- **Artifact Detection**: Identifies files, configs, and code generated
- **Missing Elements**: Finds TODOs, incomplete work, and forgotten threads
- **Abandoned Work Detection**: Flags old transcripts with no recent follow-up

### Display Levels

- **Dashboard**: Overview stats, recent activity, status breakdowns
- **Projects**: Browse all projects with status, task progress, last activity
- **Project Detail**: Tasks (Kanban), transcripts, artifacts, missing elements
- **Tasks**: Kanban board (Todo / In Progress / Completed / Abandoned)
- **Transcripts**: Full conversation viewer with tool call highlighting
- **Search**: Advanced search with filters and similarity matching

### Todoist Export

- Export projects as Todoist projects
- Export tasks with priorities, due dates, and descriptions
- Sync status tracking
- Bulk export with filtering

## API Reference

### Endpoints

```
GET    /health                    Health check
GET    /api/v1/stats              System statistics

GET    /api/v1/sources            List transcript sources
GET    /api/v1/sources/{id}       Get source details
DELETE /api/v1/sources/{id}       Delete source

GET    /api/v1/transcripts        List transcripts (filter: project, status, provider)
GET    /api/v1/transcripts/{id}   Get transcript with messages
DELETE /api/v1/transcripts/{id}   Delete transcript

GET    /api/v1/projects           List projects (filter: status, search)
GET    /api/v1/projects/{id}      Get project detail with tasks/transcripts
PUT    /api/v1/projects/{id}/status  Update project status

GET    /api/v1/tasks              List tasks (filter: project, status, priority)
GET    /api/v1/tasks/kanban       Get Kanban board data
PUT    /api/v1/tasks/{id}/status  Update task status

GET    /api/v1/artifacts          List artifacts

POST   /api/v1/search             Hybrid search
GET    /api/v1/search/similar/{id} Find similar transcripts
GET    /api/v1/search/suggest     Autocomplete
GET    /api/v1/search/facets      Facet counts

GET    /api/v1/skills             List available skills
POST   /api/v1/skills/test/{name} Test a skill against a file

POST   /api/v1/ingest             Trigger ingestion
POST   /api/v1/ingest/upload      Upload transcript file
GET    /api/v1/ingest/status      Get ingestion status

POST   /api/v1/mining/transcript/{id}  Trigger mining
GET    /api/v1/mining/transcript/{id}  Get mining results
GET    /api/v1/mining/abandoned   Find abandoned work

GET    /api/v1/todoist/projects         List Todoist projects
POST   /api/v1/todoist/export/project/{id}  Export project
POST   /api/v1/todoist/export/task/{id}     Export task
GET    /api/v1/todoist/sync-status    Sync status
```

## Development

### Project Structure

```
burdello-bum-bum/
├── backend/                  # Python FastAPI backend
│   ├── api/routers/          # REST API endpoints
│   ├── core/                 # Models, schemas, config, database
│   ├── skills/               # Skill system + provider skills
│   │   ├── base.py           # ABC + data classes
│   │   ├── registry.py       # Skill discovery + routing
│   │   ├── mixins.py         # Shared parsing utilities
│   │   └── providers/        # 7 built-in skills
│   ├── pipeline/             # Processing pipeline
│   │   ├── chunking.py       # Semantic + hierarchical chunking
│   │   ├── embedding.py      # Embedding generation
│   │   ├── normalization.py  # Transcript normalization
│   │   ├── storage.py        # DB + vector store storage
│   │   ├── discovery.py      # Source file discovery
│   │   └── tasks.py          # Celery task definitions
│   ├── mining/               # LLM data mining
│   │   ├── engine.py         # MiningEngine
│   │   └── prompts/          # LLM prompt templates
│   ├── search/               # Search engine
│   │   ├── engine.py         # HybridSearchEngine (Qdrant)
│   │   ├── vector.py         # Embedding utilities
│   │   └── fulltext.py       # PostgreSQL full-text search
│   ├── integrations/         # External integrations
│   │   ├── todoist.py        # Todoist REST API client
│   │   └── litellm.py        # LiteLLM gateway client
│   └── tests/                # Comprehensive test suite
├── frontend/                 # React SPA
│   ├── src/components/       # Reusable UI components
│   ├── src/pages/            # Page components
│   ├── src/hooks/            # React Query hooks
│   └── src/stores/           # Zustand state management
├── docker-compose.yml        # Full stack deployment
├── Dockerfile                # Backend container
└── pyproject.toml            # Python dependencies
```

### Running Tests

```bash
# Backend tests
cd backend
pytest -xvs --cov=. --cov-report=term-missing

# Specific test modules
pytest tests/unit/test_skills/ -xvs
pytest tests/unit/test_pipeline/ -xvs
pytest tests/unit/test_api/ -xvs

# Frontend tests
cd frontend
npm test
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://bbuser:bbpass@localhost:5432/burdello` | PostgreSQL connection |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant vector store |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery |
| `LITELLM_URL` | `http://localhost:4000` | LiteLLM gateway |
| `LITELLM_API_KEY` | `` | API key for LiteLLM |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `BB_EMBEDDING_MODEL` | `nomic-embed-text-v2` | Embedding model |
| `BB_CHUNK_SIZE` | `512` | Max chunk size (tokens) |
| `BB_CHUNK_OVERLAP` | `50` | Chunk overlap |
| `TODOIST_API_TOKEN` | `` | Todoist API token |

## Maintenance

### Project classification — re-bind to canonical names

The mining pipeline previously generated 1,000+ noisy projects (libraries,
Azure resources, PR branches). It now derives the canonical project from
the source file path via `backend/pipeline/repo_resolver.py`.

To re-apply the resolver against existing data (after editing collapse rules,
the blocklist, or the humanizer overrides):

```bash
# Backup (lives inside the postgres container on a persistent volume)
docker exec bb-postgres pg_dump -U bbuser -d burdello \
    -t projects -t tasks -t artifacts -f /tmp/pre-canonicalize.sql

# Preview (no writes)
docker exec bb-backend python -m backend.scripts.canonicalize_projects --dry-run

# Apply atomically
docker exec bb-backend python -m backend.scripts.canonicalize_projects --apply
```

Expected order-of-magnitude result: ~3,700 source rows collapse to **~20–30
canonical projects** (e.g. *Reasoning Core*, *Circit App*, *Jakub Health Hub*).
Non-Claude transcripts (Gemini / Kimi / Codex) bucket into
`Unsorted (<Provider>)` until per-provider resolvers are added.

Tweak the rule set at:

- `backend/pipeline/repo_resolver.py` — `_COLLAPSE_RULES`,
  `_IGNORE_PREFIXES`, `_LIBRARY_BLOCKLIST`, `_HUMANIZED_OVERRIDES`,
  `_KNOWN_ORGS`.
- Curation hint: run `--dry-run` and read the *Top unmatched slugs* list at
  the end of the log to find candidates for new rules / overrides.

## Tailscale Deployment

Share your local instance over Tailscale:

```bash
# Serve the web UI
tailscale serve --https 443 --set-path / http://localhost:3000

# Serve the API
tailscale serve --https 443 --set-path /api http://localhost:8000
```

Now your instance is available at `https://your-machine.your-tailnet.ts.net`.

## License

MIT
