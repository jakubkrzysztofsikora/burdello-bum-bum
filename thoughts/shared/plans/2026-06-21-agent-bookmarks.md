---
date: 2026-06-21
commit: 5fd27656a3a5bafe7019159c670023d9e26b8d55
branch: main
ticket: none
status: approved
revision: 2
---
# Plan: Agent Session Bookmarks

> **v2** — revised after adversarial review by three expert reviewers (senior fullstack, agent-harness designer, solutions architect). Every blocker below was verified against the live codebase/environment. The v1 design is superseded where noted. **User approved all reversals (R1/R2/R3) on 2026-06-21 — status: approved, ready to implement.**

## Summary
Let an agent drop a **bookmark** — a durable note marking something worth returning to (an unresolved bug, a deferred refactor, a design question, a "come back and verify X") — on the project it is working in, linked to the exact session/transcript. The bookmark is created via the burdello MCP (`create_bookmark`). The **stdio server resolves the session and project itself** from `CLAUDE_CODE_SESSION_ID` + `cwd` (the agent passes only `note_text`). Transcript linking is keyed on **`session_id`** (already persisted), not on path strings. Linking is **event-driven** off the ingest pipeline tail, not done on read. Bookmarks are listed per project via MCP (`list_bookmarks`) and in the web frontend (a Bookmarks section on Project Detail).

## Research References
- Four parallel codebase explorations (MCP layer, ingest pipeline, data models, API+frontend), 2026-06-21.
- Three adversarial reviews, 2026-06-21 (findings folded in below). Reviewer agent IDs retained for follow-up: fullstack `a4b805785fb77811f`, harness `a47768fb3ae1bf52d`, architect `afb08b0e67fb61352`.

---

## Reversed decisions (USER-APPROVED 2026-06-21)

The review produced verified evidence that overturns two choices made in v1. The user reviewed R1/R2/R3 below and **approved all three** — proceed as written.

### R1. Agent does NOT pass `project_name`/`session_path`. The stdio server derives both. ⬅ reverses v1 Decision 2
- **Why v1 was wrong**: Agents genuinely do not know their own transcript path, so "optional session_path" → agents omit it 100% of the time → the focused-ingest + transcript-link half of the feature is dead on arrival. And `project_name` as a freeform string fails on the slug-vs-humanized gap: the canonical row is `"Burdello Bum Bum"` (repo_resolver `_humanize`), but an agent passes `"burdello-bum-bum"` → `create_bookmark` errors "project not found" for a session that is trivially resolvable from its path.
- **Verified facts** (this environment): `CLAUDE_CODE_SESSION_ID=3ef8f1e0-…` is present in the env (`env | grep CLAUDE` confirms). The transcript is at a deterministic path: `~/.claude/projects/-<cwd-with-/-as->/<session_id>.jsonl` — confirmed the live file `…/-Users-jakubsikora-Repos-personal-burdello-bum-bum/3ef8f1e0-….jsonl` exists. The stdio server is a child of the Claude Code process and inherits the env + `cwd`.
- **New design**: `create_bookmark`'s agent-facing signature is **`create_bookmark(note_text, tags?)`**. The stdio server injects `session_id` (from env), `session_path` (computed), and `cwd` into the `_call` payload. The backend resolves the **project from the path** via `resolve_from_path(session_path)` — the exact function mining uses — so the bookmark's project is provably the same one mining will assign the session. Freeform `project_name` remains an accepted *override/fallback* for non-Claude-Code callers but is never required.

### R2. Transcript link keys on `session_id`, NOT `session_path` string-equality. ⬅ reverses v1 Decision 1's join key
- **Why v1 was wrong**: `Source.url` is `file://{path.resolve()}` (discovery resolves symlinks; storage.py:73). A bookmark's agent-supplied path is raw (`~`, relative, or a different mount inside Docker). Server-side `.resolve()` of a *foreign* path is meaningless. The strings essentially never match → linker silently links nothing. Also two Sources can share one `url` after re-ingest → `scalar_one_or_none()` raises `MultipleResultsFound`.
- **Verified facts**: the Claude provider extracts `session_id` (claude_code.py:158-189), `mine_task`/extract puts it at `metadata["session_id"]` (tasks.py:184), and normalization merges `**extracted.metadata` into the transcript (normalization.py:44-47). So **`Transcript.metadata_["session_id"]` already holds the session UUID today**, no schema change required. The filename IS `<session_id>.jsonl`.
- **New design**: promote `session_id` to an indexed column on `Transcript` (`store_transcript` already has it in `metadata`), and link `Bookmark.session_id == Transcript.session_id`. UUID equality — filesystem- and Docker-independent. Resolves the multi-transcript-per-session ambiguity too (pick newest transcript *for that session_id*).

### R3. Linking is event-driven (pipeline tail), not backfill-on-read. ⬅ reverses v1's "lazy on every list" mechanism
- **Why v1 was wrong**: `link_pending_bookmarks` on every `list_bookmarks`/`GET` mutates rows inside a read path (get_db auto-commits), N+1 scans all NULL bookmarks for the project on every call, and a permanently-unlinkable bookmark gets re-scanned forever. Read latency grows monotonically.
- **New design**: append a tiny `link_task` to the Celery chain after `mine_task` (or call the linker at the end of `mine_task`) that links bookmarks **for the just-ingested session_id only** — O(1) at the moment a transcript appears. `create_bookmark` still does one immediate best-effort link (handles already-ingested sessions). Reads become pure reads. A bounded lazy fallback (only bookmarks created in the last hour) is optional, not primary.

### Net effect on the user's three original answers
- "Store raw ids, link later" → **kept**, but the link key is `session_id` and the linker is event-driven.
- "Agent passes project_name only" → **reversed** to "server derives project+session; agent passes note_text." This is strictly safer and the only version where focused ingest actually fires. If you insist on project_name-only, the feature degrades to project-scoped notes with no transcript link (acceptable fallback, but not the headline feature).
- "New /ingest/session endpoint" → **kept**.

---

## Core flow (v2)
```
agent (Claude Code):  create_bookmark(note_text, tags?)
        │
stdio_server.py: inject session_id = $CLAUDE_CODE_SESSION_ID
                 inject session_path = ~/.claude/projects/-<cwd→->/<session_id>.jsonl  (if file exists)
                 inject cwd = os.getcwd()
        ▼  POST /api/v1/mcp/create_bookmark {note_text, session_id, session_path, cwd}
backend create_bookmark(db, ...):
        ├─ identity = resolve_from_path(session_path or cwd)        # SAME resolver mining uses
        ├─ project  = get-or-create Project(identity.humanized)     # derived, not asserted
        ├─ INSERT bookmark(project_id, session_id, session_path, transcript_id=NULL, note_text)
        ├─ immediate link: Transcript WHERE session_id == bm.session_id (newest) → set transcript_id
        └─ if still NULL and session_path is a real file:
               POST internal /ingest/session  → process_source.delay(session_path)   # focused ingest
                 (guarded: broker errors swallowed; bookmark already committed)
        ▼
pipeline finishes for that source → link_task(session_id):
        UPDATE bookmarks SET transcript_id = (newest transcript for session_id)
        WHERE project bookmarks with transcript_id IS NULL AND session_id = <this>
        ▼
list_bookmarks / GET /bookmarks  →  pure read (no mutation)

Worker (Claude.ai HTTP):  list_bookmarks only (read).  create_bookmark NOT exposed
   (no shared env/fs → cannot resolve session; would only ever make orphan project notes
    and fire doomed ingest jobs against paths that don't exist on the ingest box).
```

---

## Phase 0 (NEW): Persist `session_id` on Transcript + resolve the schema source-of-truth

This phase did not exist in v1. It is a prerequisite for R2 and fixes the migration/`create_all` split-brain (Blocker B2/architect-B2).

### Schema source of truth — decision
`main.py:92` lifespan calls `init_db()` → `Base.metadata.create_all` on **every startup** (database.py:83-92). The lone Alembic migration (`3a0318e8a482`, `down_revision=None`) is vestigial; `create_all` does the real work. Therefore:
- **`create_all` is authoritative for this plan.** New columns/tables materialize from the models at startup.
- The Alembic migration is **parity/documentation** and MUST be idempotent so `alembic upgrade head` does not crash on a box where the app already booted (where `create_all` already made the table). Use guards: `op.execute("CREATE TABLE IF NOT EXISTS …")` / `inspect(conn).has_table(...)`, not bare `op.create_table`.
- Plan does **not** claim `alembic upgrade head && alembic downgrade -1` as a green gate (it isn't, post-boot). Stated honestly as a known limitation.
- *(Out of scope, named for later: making Alembic authoritative by removing `create_all` from startup is a deployment-model change, not part of bookmarks.)*

### Changes

#### File: `backend/core/models.py`
- **What**: Add `session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)` to `Transcript`.
- **Rationale**: Promote the already-present `metadata_["session_id"]` into a queryable, indexed column — the correlation key for bookmarks (R2).

#### File: `backend/pipeline/storage.py`
- **What**: In `store_transcript`, also set `session_id=transcript_create.metadata.get("session_id")` on the `Transcript(...)` (storage.py:106-112).
- **Where**: storage.py ~line 106.
- **Note**: `metadata` already carries it (normalization.py:46). Pure copy-up; no extraction change.

#### File: `backend/core/schemas.py`
- **What**: Add `session_id: str | None = None` to `TranscriptCreate` and the transcript response/summary schemas so it round-trips.

#### File: `backend/scripts/backfill_session_id.py` (Create, optional)
- **What**: One-shot `UPDATE transcripts SET session_id = metadata->>'session_id' WHERE session_id IS NULL`.
- **Rationale**: Existing transcripts already have it in JSONB; this lifts them so old sessions are linkable. Mirrors `canonicalize_projects.py` style.

### Success Criteria
#### Automated
- [ ] `python -c "from backend.core.models import Transcript; Transcript.session_id"` resolves
- [ ] `pytest backend/tests/unit -q` — **establish baseline first** (see Risk: baseline may already be red, fullstack-M2)
- [ ] After a single-session ingest, `SELECT session_id FROM transcripts` is non-NULL for that row
#### Manual
- [ ] `transcripts.session_id` indexed (`\d transcripts`)
- [ ] Backfill script populates historical rows from JSONB

### Dependencies: none. Blocks: all later phases.

---

## Phase 1: Bookmark data model + idempotent migration

#### File: `backend/core/models.py`
- **What**: Add `Bookmark`; add `bookmarks` relationship to `Project`.
- **Code sketch**:
  ```python
  class Bookmark(Base, TimestampMixin):
      """An agent-authored mark on a session — something to revisit later."""
      __tablename__ = "bookmarks"

      id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
      project_id: Mapped[uuid.UUID | None] = mapped_column(
          ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
      transcript_id: Mapped[uuid.UUID | None] = mapped_column(
          ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True)
      session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)   # link key (R2)
      session_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)             # display + ingest hint only
      note_text: Mapped[str] = mapped_column(Text, nullable=False)
      author: Mapped[str | None] = mapped_column(String(100), nullable=True)
      ingest_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")  # none|pending|linked|failed
      ingest_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)             # celery result id (observability, architect-M5)
      tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
      pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
      metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=dict)

      project: Mapped["Project"] = relationship(back_populates="bookmarks")
      transcript: Mapped["Transcript"] = relationship()

  __table_args__ = (
      Index("ix_bookmarks_list", "project_id", "pinned", "created_at"),     # composite for list order (architect-M8)
      Index("ix_bookmarks_unlinked", "session_id",
            postgresql_where=text("transcript_id IS NULL")),                # partial, for the linker
  )
  ```
- **Cascade consistency (architect-M9)**: DB FK is `SET NULL`; therefore do **not** put `cascade="all, delete-orphan"` on `Project.bookmarks` (that contradicts SET NULL). Use plain `relationship(back_populates="project")`. Orphan-on-project-delete is intentional; add a "show orphaned bookmarks" filter later if needed.

#### File: `backend/migrations/versions/{rev}_add_bookmarks_and_session_id.py` (Create)
- `down_revision = "3a0318e8a482"`. **Idempotent** body (guards per Phase 0 decision):
  ```python
  def upgrade():
      conn = op.get_bind(); insp = sa.inspect(conn)
      cols = [c["name"] for c in insp.get_columns("transcripts")]
      if "session_id" not in cols:
          op.add_column("transcripts", sa.Column("session_id", sa.String(255), nullable=True))
          op.create_index("ix_transcripts_session_id", "transcripts", ["session_id"])
      if not insp.has_table("bookmarks"):
          op.create_table("bookmarks", ... )   # full def
          op.create_index("ix_bookmarks_list", "bookmarks", ["project_id", "pinned", "created_at"])
          op.execute("CREATE INDEX IF NOT EXISTS ix_bookmarks_unlinked ON bookmarks (session_id) WHERE transcript_id IS NULL")
  ```

#### File: `backend/core/schemas.py`
- Add `BookmarkCreate`, `BookmarkResponse`, `BookmarkListResponse` (artifact-style `{total, items}` envelope; `ConfigDict(from_attributes=True)`; `metadata` via `AliasChoices("metadata_","metadata")`). Include `session_id`, `transcript_id`, `ingest_status`.

### Success Criteria
#### Automated
- [ ] Models + schemas import
- [ ] `pytest backend/tests/unit -q` (vs Phase 0 baseline)
- [ ] Migration applies idempotently on a DB where `create_all` already made the table (run app once, then `alembic upgrade head` → no error)
#### Manual
- [ ] `\d bookmarks` shows composite + partial indexes, both FKs `ON DELETE SET NULL`

### Dependencies: Phase 0. Blocks: 2,3,4.

---

## Phase 2: Linker (session_id-keyed) + event-driven hook + focused-ingest endpoint

#### File: `backend/pipeline/bookmark_linker.py` (Create)
- **What**: `async def link_bookmarks_for_session(db, session_id) -> int` — set `transcript_id` + `ingest_status="linked"` for that session's unlinked bookmarks, using the **newest** transcript with that `session_id`.
- **Code sketch**:
  ```python
  async def link_bookmarks_for_session(db, session_id: str) -> int:
      if not session_id:
          return 0
      t = (await db.execute(
          select(Transcript).where(Transcript.session_id == session_id)
          .order_by(desc(Transcript.created_at)).limit(1)
      )).scalar_one_or_none()
      if t is None:
          return 0
      res = await db.execute(
          update(Bookmark)
          .where(Bookmark.session_id == session_id, Bookmark.transcript_id.is_(None))
          .values(transcript_id=t.id, ingest_status="linked")
      )
      return res.rowcount or 0
  ```
  Single set-based UPDATE — no N+1, no per-row Python loop, idempotent.

#### File: `backend/pipeline/tasks.py`
- **What**: At the end of `mine_task` (after results stored), call the linker for the session_id of the just-ingested source. Either inline (open a session) or append a `link_task` to the chain. Inline is simpler given the existing `asyncio.run`-per-task pattern.
- **Where**: tasks.py end of `mine_task` (~line 580). The task already resolved `identity`/has the source; pull `session_id` from the stored transcript metadata or extract result.

#### File: `backend/api/routers/ingest.py`
- **What**: `POST /ingest/session` accepting `path` (preferred) or `session_id`.
- **Code sketch**:
  ```python
  @router.post("/session")
  async def ingest_session(path: str | None = Query(None), session_id: str | None = Query(None)):
      if not path and not session_id:
          raise HTTPException(422, "path or session_id required")
      target = path or _find_session_file(session_id)   # glob provider dirs for <session_id>.jsonl
      if not target or not Path(target).is_file():
          raise HTTPException(404, f"session file not found")
      try:
          result = process_source.delay(target)
      except OperationalError as exc:                   # broker down (fullstack-B2)
          raise HTTPException(503, f"ingest queue unavailable: {exc}")
      return {"job_id": result.id, "session_path": target, "status": "queued"}
  ```
- **`_find_session_file(session_id)`** is now first-class (architect-M10): glob `~/.claude/projects/**/<session_id>.jsonl` (+ other providers). ~5 lines; session_id is the filename.

#### File: `backend/tests/unit/test_bookmark_linker.py` (Create)
- session_id match links newest transcript; no-match → 0; multiple transcripts same session → picks newest. Patch `process_source.delay`.

### Success Criteria
#### Automated
- [ ] `pytest backend/tests/unit/test_bookmark_linker.py -q`
- [ ] `POST /ingest/session?path=/nope` → 404; broker-down → 503 (mock)
- [ ] linker test: 2 transcripts same session_id → bookmark links to newest
#### Manual
- [ ] With worker up: focused ingest of a real `.jsonl` links its bookmark on pipeline completion (event-driven, not on read)

### Dependencies: Phase 1. Blocks: 3.

---

## Phase 3: MCP tools — server-resolved session + project (stdio create + cross-transport split)

#### File: `backend/mcp_tools/__init__.py`
- **What**: Add **real helpers** `_resolve_project(db, *, project_id, project_name)` and `_bookmark_summary(bm)` (v1 referenced these as if they existed — they do not; fullstack-B1). Add `create_bookmark` and `list_bookmarks`.
- **`create_bookmark`** resolves project from path (R1), links by session_id (R2), records ingest job id, guards broker:
  ```python
  async def create_bookmark(db, *, note_text, session_id=None, session_path=None, cwd=None,
                            project_name=None, project_id=None, author="claude-code", tags=None):
      # project DERIVED from path, not asserted
      identity = resolve_from_path(session_path or cwd or "") if (session_path or cwd) else None
      if identity is not None:
          project = await _get_or_create_project(db, identity.humanized)
      else:
          project = await _resolve_project(db, project_id=project_id, project_name=project_name)
      if project is None:
          return {"error": "could not resolve project (no path and unknown project_name)"}

      bm = Bookmark(project_id=project.id, session_id=session_id, session_path=session_path,
                    note_text=note_text, author=author, tags=tags, ingest_status="none")
      db.add(bm); await db.flush()

      linked = await link_bookmarks_for_session(db, session_id) if session_id else 0
      triggered = False
      if not linked and session_path and Path(session_path).is_file():
          try:
              job = process_source.delay(session_path)
              bm.ingest_job_id, bm.ingest_status, triggered = job.id, "pending", True
          except OperationalError:
              bm.ingest_status = "failed"      # broker down; bookmark still saved (fullstack-B2)
      await db.refresh(bm)
      return {"bookmark": _bookmark_summary(bm), "ingest_triggered": triggered}
  ```
  `list_bookmarks` is a **pure read** (no linker call): order `pinned DESC, created_at DESC`, limit.

#### File: `backend/api/routers/mcp_api.py`
- Add `POST /mcp/create_bookmark`, `POST /mcp/list_bookmarks`, bearer-guarded. `create` validates `note_text` (max_length 4000, fullstack/harness-m1), passes through `session_id/session_path/cwd`.

#### File: `backend/mcp/stdio_server.py`  ← the R1 mechanism lives here
- **What**: `create_bookmark(note_text, tags=None)` — agent-facing signature is **two params**. Server injects session/project context:
  ```python
  @mcp.tool()
  async def create_bookmark(note_text: str, tags: list[str] | None = None) -> dict:
      """Persist a bookmark — a durable note on this project, visible in future
      sessions and on the burdello web board — for something worth returning to:
      an unresolved bug, a deferred refactor, a design question you couldn't
      settle, a 'come back and verify X'. Use when you'd otherwise lose the
      thread between sessions. One bookmark per distinct thread; don't
      re-bookmark something you already noted this session. Not for routine
      status — only things a future you would want surfaced."""
      sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
      cwd = os.getcwd()
      spath = None
      if sid:
          enc = "-" + cwd.replace("/", "-")
          p = Path.home() / ".claude" / "projects" / enc / f"{sid}.jsonl"
          spath = str(p) if p.is_file() else None
      return await _call("/create_bookmark", {
          "note_text": note_text, "tags": tags,
          "session_id": sid, "session_path": spath, "cwd": cwd})

  @mcp.tool()
  async def list_bookmarks(project_name: str | None = None, limit: int = 50) -> dict:
      """List bookmarks for a project (pinned + newest first). Call at session
      start to see what past sessions flagged. Defaults to the current repo."""
      return await _call("/list_bookmarks",
          {"project_name": project_name, "cwd": os.getcwd(), "limit": limit})
  ```
  (`list_bookmarks` passes `cwd` so the backend can default the project via resolver.)

#### File: `worker/src/index.ts`  ← cross-transport split (harness-B2)
- **What**: Add **`list_bookmarks` only** to the Worker `TOOLS`. **Do NOT expose `create_bookmark` over the Worker** — Claude.ai has no shared env/fs, so it can't resolve a real session; it would only create orphan project-notes and fire doomed ingest jobs against nonexistent paths. Document this in a code comment.
- *(If a Claude.ai-side create is ever wanted, it's a separate project-only `create_project_note` tool with no session_path — out of scope.)*

### Success Criteria
#### Automated
- [ ] `_resolve_project`, `_get_or_create_project`, `_bookmark_summary` exist and have unit tests
- [ ] `create_bookmark` (called as a function with a fake `cwd` under a repo) derives the canonical project (resolver), not the raw dir name
- [ ] `create_bookmark` with broker mocked-down → bookmark saved, `ingest_status="failed"`, no exception
- [ ] tests call **tool functions directly** with `db_session` (not the bearer router, which 503s when `MCP_BRIDGE_TOKEN` unset — fullstack-M3); `process_source.delay` patched
- [ ] Worker still builds (`cd worker && npm run types` — note: there is **no** `build`/test script; `dev`,`deploy`,`types` only — fullstack-M1); `tools/list` includes `list_bookmarks`, excludes `create_bookmark`
#### Manual
- [ ] From a real Claude Code session in this repo: `create_bookmark("revisit auth retry logic")` → returns a bookmark whose project is the canonical name and whose session_id matches `$CLAUDE_CODE_SESSION_ID`; ingest fires; after pipeline, `transcript_id` populates via the event hook (not via a list call)

### Dependencies: Phases 1,2. Blocks: 4 (frontend independent).

---

## Phase 4: REST API + per-project bookmarks view (frontend)

#### File: `backend/api/routers/bookmarks.py` (Create) + register in `main.py`
- `GET /bookmarks/?project_id=&skip=&limit=` (**pure read**, no linker), `POST /bookmarks/`, `DELETE /bookmarks/{id}`, `PATCH /bookmarks/{id}` (pin/edit). `{total, items}` envelope, `Depends(get_db)`, `HTTPException(404)` — mirrors `projects.py`/`tasks.py`. Unauthenticated like the other public routers (note: only `/mcp/*` is bearer-guarded; flag if undesired).

#### File: `frontend/src/api/types.ts` / `client.ts` / `hooks/useApi.ts`
- Add `Bookmark` type (incl. `session_id`, `transcript_id`, `ingest_status`), `listBookmarks(params)`, `useBookmarks(params)` (TanStack Query, `staleTime: 30_000`). `FilterParams.project_id` already exists.

#### File: `frontend/src/pages/ProjectDetail.tsx`
- **What**: Add a Bookmarks section using the **existing Tailwind `bb-*` design system** (NOT the v1 `className="bookmark-row"`/`"muted"` which don't exist — fullstack-m1). Match the existing section shell `rounded-lg border border-bb-border bg-bb-card p-4`, `text-bb-muted`, lucide icon in an `<h3 className="text-sm font-semibold">`, like the Task/Transcripts sections (ProjectDetail.tsx:67-118).
- Each row: `{b.note_text}` (React auto-escapes — never `dangerouslySetInnerHTML`; harness-m2), author + relative time, and:
  - `b.transcript_id` → `<Link to={`/transcripts/${b.transcript_id}`}>` (route confirmed App.tsx:26),
  - else `ingest_status === "failed"` → "ingest failed" + retry affordance,
  - else → muted "session ingesting…".

### Success Criteria
#### Automated
- [ ] `GET /api/v1/bookmarks/?project_id=<id>` → `{total, items}`; no row mutated by the GET
- [ ] Frontend typecheck/build: `cd frontend && npm run build` (script is `tsc -b && vite build`; there is **no** `type-check` script — fullstack-M1)
- [ ] `cd frontend && npm run lint`; `cd frontend && npm test`
#### Manual
- [ ] `/projects/{id}` renders Bookmarks in `bb-*` styling; linked → transcript; failed → retry; pending → spinner that flips after ingest

### Dependencies: Phase 1 (+2 for status). Frontend independent of MCP.

---

## Risk Assessment (v2)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Test baseline already red (`test_ingest.py` asserts keys current code doesn't return — fullstack-M2) | High | Med | Establish/record baseline in Phase 0 before treating "tests pass" as signal; fix or xfail the stale test. |
| Celery broker down when `create_bookmark`/`ingest_session` enqueues (fullstack-B2) | Med | Med | try/except `OperationalError`; bookmark committed first; `ingest_status="failed"`; endpoint 503. |
| `create_all` vs Alembic split-brain (architect-B2) | High | Med | Phase 0 decision: `create_all` authoritative; migration idempotent; don't gate on `alembic upgrade`. |
| Partial-then-full transcript (bookmark mid-session captures truncated JSONL; harness-M4) | Med | Med | Linker always points to **newest** transcript for the session_id; event hook re-links when the fuller batch ingest lands. Accept that the bookmarked transcript grows. |
| Agent on non-Claude-Code/Worker has no session → project-only note | Med | Low | Documented degradation; `create_bookmark` not on Worker; fallback `project_name`. |
| Dup bookmarks (no natural key; harness-M3) | Med | Low | Optional soft-dedup: pre-insert check on `(project_id, session_id, lower(note_text))`, return existing with `deduped:true`. Deferred unless spam observed. |
| `_find_session_file` globbing slow on huge `.claude/projects` | Low | Low | session_id is the filename; targeted glob `**/<sid>.jsonl`, first hit wins. |

## Rollback
- DB: drop `bookmarks` table; `transcripts.session_id` is additive/nullable (leave or drop). FKs are SET NULL — no other table altered.
- Code: additive files + appended functions/routes/tools. Revert = remove router include, the two `@mcp.tool()`s, the Worker `list_bookmarks` ToolDef, the ProjectDetail section, and the `link` call in `mine_task`. `session_id` column is harmless if left.

## File Ownership Summary
| File | Phase | Type |
|------|-------|------|
| backend/core/models.py | 0,1 | Modify (Transcript.session_id; Bookmark) |
| backend/pipeline/storage.py | 0 | Modify (copy session_id up) |
| backend/core/schemas.py | 0,1 | Modify |
| backend/scripts/backfill_session_id.py | 0 | Create (optional) |
| backend/migrations/versions/{rev}_add_bookmarks_and_session_id.py | 1 | Create (idempotent) |
| backend/pipeline/bookmark_linker.py | 2 | Create (session_id-keyed, set-based) |
| backend/pipeline/tasks.py | 2 | Modify (link at mine_task tail) |
| backend/api/routers/ingest.py | 2 | Modify (/session, broker guard, _find_session_file) |
| backend/tests/unit/test_bookmark_linker.py | 2 | Create |
| backend/mcp_tools/__init__.py | 3 | Modify (_resolve_project, _get_or_create_project, _bookmark_summary, create/list) |
| backend/api/routers/mcp_api.py | 3 | Modify |
| backend/mcp/stdio_server.py | 3 | Modify (env/path/cwd injection) |
| worker/src/index.ts | 3 | Modify (list_bookmarks ONLY) |
| backend/tests/unit/test_bookmark_tools.py | 3 | Create |
| backend/api/routers/bookmarks.py | 4 | Create |
| backend/main.py | 4 | Modify (register router) |
| frontend/src/api/types.ts, client.ts, hooks/useApi.ts | 4 | Modify |
| frontend/src/pages/ProjectDetail.tsx | 4 | Modify (bb-* styling) |

## Open Questions / Flags
- **Deferred vs eager focused ingest (harness-M4)**: v2 fires at bookmark time (captures the session so-far) and re-links to the fuller transcript when batch ingest lands. A SessionEnd/Stop hook firing `/ingest/session` once the JSONL is complete (same pattern as `burdello-kanban-summary.py`) is the cleaner long-term trigger and would make the bookmarked transcript whole on first link. Recommend adding it as a follow-up; not required for MVP.
- **Re-ingest creates a 2nd transcript for a grown file** (file_hash dedup keys on content). Confirmed acceptable: linker takes newest-by-session_id. If you'd rather dedup transcripts by session_id (one logical session = one transcript, updated in place), that's a larger pipeline change — flag if wanted.
- **REST `/bookmarks` unauthenticated** — consistent with existing projects/tasks routers. Flag if the board will ever be shared (then add auth + sanitize note rendering everywhere, not just ProjectDetail).
- **Soft-dedup** left as deferred; enable if agents spam.
- **`pending` can be terminal if the pipeline dies before `embed_task`** (architect Phase-2 #1). Linking now runs at the `completed` transition (in `embed_task`/`chunk_embed_task`), decoupled from the failure-prone LLM mining stage, plus an idempotent safety-net re-link at mine-tail — so a mining failure no longer blocks linking. Residual hole: if extract/normalize/chunk/embed exhaust retries, the transcript never reaches `completed`, the linker never runs, and a bookmark's `ingest_status` stays `pending` forever. Follow-up: a periodic Celery-beat sweep that calls `link_bookmarks_for_session` for `pending` bookmarks older than N minutes (closes the dead-letter hole). Not built in MVP — Phase 3 sets `pending`/`failed`; the sweep is a small additive task.

## Implementation deviations (applied during build)
- **Phase 0 BLOCKER fixed**: real Claude Code JSONL uses camelCase `sessionId`, but the provider read snake_case `session_id` — the correlation key would have been NULL on every real ingest. Fixed `backend/skills/providers/claude_code.py` to read `record.get("session_id") or record.get("sessionId")` (+ excluded `sessionId` from metadata passthrough) and corrected the test fixture to the real wire format. Verified against a live transcript (1146 `sessionId`, 0 `session_id`).
- **Phase 2 linker**: changed the re-link predicate from `transcript_id IS NULL` to `transcript_id IS DISTINCT FROM <newest>` so re-ingest re-points bookmarks to the fuller transcript (honors R3 / partial-then-full), while staying idempotent. Linking moved from mine-tail to the `completed` transition with a SAVEPOINT (`db.begin_nested()`) so a linker error can't poison the chunks/status commit. `_find_session_file` UUID-validates before globbing and picks newest-by-mtime deterministically; the 503 no longer leaks the broker exception string.
