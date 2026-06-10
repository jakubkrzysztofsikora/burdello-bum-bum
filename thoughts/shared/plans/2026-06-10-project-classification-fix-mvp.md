---
date: 2026-06-10
commit: f9cf3b233e3b63aedca6b1ba3f20b30fa8e8759f
branch: main
status: revised-mvp
supersedes: prior 5-phase plan (workstream classifier + migration script deferred)
---
# Plan: Project Classification Granularity Fix (MVP)

## Summary

Replace LLM-based project extraction with a **deterministic path-based repo resolver**,
**drop empty projects at write time**, add **resolver observability**, then
**TRUNCATE + re-mine** existing data. Workstream subdivision and the migration
script are deferred until per-repo task counts show a single repo needs further
hierarchy.

Three adversarial reviews of the prior plan converged on this MVP.

## Target Outcome

| Today (1,134 projects) | Target (≈30–80) |
|---|---|
| `circit-app-evals-a-t1…b-t9` (19 variants) | `Circit App Evals` (one) |
| `circit-app-pr-10851`, `circit-app-waf-33115`, `circit-app-bugfix-…` | `Circit App` |
| `apim-circit-non-prod`, `appi-circit-prod`, `kv-circitron-mcp` | dropped (infra resource) |
| `cypress`, `fastapi`, `huggingface-hub`, `transformers` | dropped (library blocklist) |
| `reasoning-core` | `Reasoning Core` |
| Bare `~`-launched Claude sessions | `Claude Shell Sessions` |
| `.kimi`, `.codex`, `.gemini` transcripts | `Unsorted (Kimi)`, `Unsorted (Codex)`, `Unsorted (Gemini)` |

Workstream subdivision is out of scope here.

---

## Phase 1 — Deterministic repo resolver + counters

### File: `backend/pipeline/repo_resolver.py` (new)

Pure-Python module mapping a transcript source path to a canonical `RepoIdentity`.
Handles Claude (root + subagents), Claude-shell-sessions (no `Repos` segment),
Gemini antigravity, Kimi sessions, Codex rollouts. Allow-list collapse rules,
blocklist for libraries and Azure resources, humanization overrides for acronyms,
counters for observability.

### File: `backend/pipeline/tasks.py`

- `extract_task`: call `resolve_from_path(source_path)`, attach
  `repo_slug` / `repo_humanized` / `repo_provider` to the result dict.
- `normalize_task`, `chunk_task`, `embed_task`, `chunk_embed_task`: pass through.
- `mine_task`: after `engine.mine_transcript`, OVERRIDE `results["projects"]`
  with `[{name: repo_humanized, status: "active", confidence: 1.0}]`. The LLM
  keeps producing tasks/artifacts/status (valuable); only its project guesses
  are discarded.

### File: `backend/api/routers/stats.py`

Add `GET /api/v1/stats/resolver` returning `counters()` + `unmatched_slugs(50)`
for curation signal.

### File: `backend/tests/test_repo_resolver.py` (new)

- Claude root + subagents/agent-*.jsonl → same canonical slug
- Claude-shell (`-Users-jakubsikora` only) → `claude-shell-sessions`
- All `circit-app-evals-{a,b}-{p0,t1..t9,e1}` variants → `circit-app-evals` (1)
- `circit-app-pr-NNNN`, `-waf-NNNN`, `-bugfix-*` → `circit-app`
- `apim-*`, `appi-*`, `kv-*` → `None` (infra ignore)
- `cypress`, `fastapi` → `None` (library blocklist)
- `.gemini/`, `.kimi/`, `.codex/` paths → `unsorted-*` identities
- Unknown path → `None`, `resolver_miss` counter increments

### Success Criteria
- `pytest backend/tests/test_repo_resolver.py` green
- Smoke command resolves the canonical subagent path correctly
- Ingest after restart writes no library/infra projects

---

## Phase 2 — Drop empty projects at write time (concurrency-safe)

### File: `backend/pipeline/storage.py`

Track `newly_created_project_ids` set within `store_mining_results`. At end of
method, before commit:

```python
if newly_created_project_ids:
    await self.db.execute(
        delete(Project).where(
            Project.id.in_(newly_created_project_ids),
            ~exists().where(Task.project_id == Project.id),
            ~exists().where(Artifact.project_id == Project.id),
        )
    )
```

Guard means only projects this transcript just created get dropped, and only
when no tasks AND no artifacts reference them anywhere — concurrency-safe
against parallel `mine_task` workers.

### Success Criteria
- `pytest backend/tests/pipeline/test_storage.py -k empty` green
- Post-re-mine: zero empty projects in DB

---

## Phase 3 — TRUNCATE + re-mine

1. `pg_dump` `projects`, `tasks`, `artifacts`, `mining_results` to `backups/<ts>.sql`.
2. `TRUNCATE TABLE projects, tasks, artifacts, mining_results CASCADE`.
3. Restart workers.
4. `POST /api/v1/ingest/` to trigger discovery.
5. Monitor until queues = 0.

### Success Criteria
- `count(projects)` ∈ [20, 150]
- 0 empty projects
- `/api/v1/stats/resolver` shows `resolver_hit > 0`, `resolver_miss == 0`
- Spot-check: project names match the Target Outcome table

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Collapse rule over-merges a legitimate distinct repo | Med | Low | Allow-list (not heuristic); `unmatched_slugs()` surfaces curation candidates |
| Subagent path regex misses an edge case | Low | Med | Test covers root + subagents + nested; unmatched logged at WARN |
| Non-Claude transcripts bucket into `Unsorted (X)` with thousands of tasks | High | Low | Acceptable for MVP — defer per-provider subdivision |
| Re-mining hits LiteLLM rate limits | High | Low | Retry-100 already in place; user accepts multi-hour runtime |
| TRUNCATE wipes work in progress | Low | High | `pg_dump` backup first |

## Rollback Strategy

- Code: `git revert` Phase 1 + 2 commits.
- Data: `psql < backups/<ts>.sql`.
- No feature flag — git IS the flag.

## Deferred (explicit)

- Workstream classifier — revisit only if a single repo lands with >300 tasks.
- Migration script — re-mine instead.
- Feature flag.
- Multi-repo session splitting.
- Calibration / golden set (no classifier to calibrate).

## Files

| File | Phase | Change |
|---|---|---|
| `backend/pipeline/repo_resolver.py` | 1 | Create |
| `backend/tests/test_repo_resolver.py` | 1 | Create |
| `backend/pipeline/tasks.py` | 1 | Modify |
| `backend/api/routers/stats.py` | 1 | Modify |
| `backend/pipeline/storage.py` | 2 | Modify |
| `backend/tests/pipeline/test_storage.py` | 2 | Modify or create |
| (operational) | 3 | TRUNCATE + ingest + monitor |
