"""Todoist sync planning and execution service.

This service turns a chosen Burdello project into a Todoist sync run:

1. Load the Burdello project tasks.
2. Group tasks into epics.
3. Match each epic to an existing Todoist project.
4. Create or update Todoist tasks.
5. Persist run history and stable task links.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import get_settings
from backend.core.models import Project, Task, TodoistSyncRun, TodoistTaskLink
from backend.integrations.litellm import LiteLLMClient
from backend.integrations.todoist import TodoistClient

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "mining" / "prompts"


@dataclass(frozen=True)
class EpicPlan:
    key: str
    name: str
    summary: str | None
    task_ids: list[uuid.UUID]
    match: dict[str, Any]


class TodoistSyncService:
    """Build and execute Todoist sync runs for a Burdello project."""

    def __init__(
        self,
        db: AsyncSession,
        todoist_client: TodoistClient | None = None,
        llm_client: LiteLLMClient | None = None,
    ) -> None:
        self.db = db
        self._owns_todoist_client = todoist_client is None
        self._owns_llm_client = llm_client is None
        self.todoist_client = todoist_client or self._make_todoist_client()
        self.llm_client = llm_client or self._make_llm_client()

    async def close(self) -> None:
        """Close owned HTTP clients."""
        if self._owns_todoist_client:
            await self.todoist_client.close()
        if self._owns_llm_client:
            await self.llm_client.close()

    async def build_plan(
        self,
        project_id: uuid.UUID,
        include_done: bool = False,
    ) -> dict[str, Any]:
        """Build a preview plan for syncing a Burdello project to Todoist."""
        project = await self._load_project(project_id)
        tasks = self._selected_tasks(project, include_done=include_done)
        todoist_projects_error: str | None = None
        try:
            todoist_projects = await self._load_todoist_projects()
        except Exception as exc:
            logger.warning(
                "Todoist project listing failed during preview for %s: %s",
                project_id,
                exc,
            )
            todoist_projects_error = str(exc)
            todoist_projects = []
        inbox_project = self._find_inbox_project(todoist_projects)
        persisted_targets = await self._load_persisted_epic_targets(project.id)

        epic_groups = await self._group_tasks_into_epics(project, tasks)

        planned_epics = []
        for epic in epic_groups:
            match = self._match_epic_to_project(
                epic_key=epic["key"],
                epic_name=epic["name"],
                epic_summary=epic.get("summary"),
                todoist_projects=todoist_projects,
                inbox_project=inbox_project,
                persisted_targets=persisted_targets,
            )
            planned_epics.append(
                {
                    "epic_key": epic["key"],
                    "epic_name": epic["name"],
                    "summary": epic.get("summary"),
                    "task_count": len(epic["task_ids"]),
                    "task_ids": [str(task_id) for task_id in epic["task_ids"]],
                    "match": match,
                }
            )

        skipped_done = sum(1 for task in project.tasks or [] if task.status == "done")
        eligible_tasks = len(tasks)

        return {
            "project_id": str(project.id),
            "project_name": project.name,
            "include_done": include_done,
            "todoist_inbox_project_id": inbox_project["id"] if inbox_project else None,
            "todoist_projects_error": todoist_projects_error,
            "todoist_projects": [
                {"id": proj["id"], "name": proj["name"]}
                for proj in todoist_projects
            ],
            "epics": planned_epics,
            "skipped_done": skipped_done,
            "total_tasks": len(project.tasks or []),
            "eligible_tasks": eligible_tasks,
        }

    async def run_sync(
        self,
        project_id: uuid.UUID,
        include_done: bool = False,
    ) -> dict[str, Any]:
        """Execute a Todoist sync run and persist the result."""
        project = await self._load_project(project_id)
        plan = await self.build_plan(project_id, include_done=include_done)

        run = TodoistSyncRun(
            project_id=project.id,
            project_name=project.name,
            status="running",
            mode="auto",
            include_done=include_done,
            todoist_inbox_project_id=plan.get("todoist_inbox_project_id"),
            plan_data=plan,
            result_data={},
            metadata_={},
        )
        self.db.add(run)
        await self.db.flush()

        todoist_projects = {
            project["id"]: project for project in plan.get("todoist_projects", [])
        }
        inbox_project_id = plan.get("todoist_inbox_project_id")
        persisted_targets = await self._load_persisted_epic_targets(project.id)

        task_by_id = {task.id: task for task in project.tasks or []}
        result_epics: list[dict[str, Any]] = []
        counts = Counter[str]()
        errors: list[str] = []

        for epic in plan.get("epics", []):
            epic_key = epic["epic_key"]
            task_ids = [uuid.UUID(task_id) for task_id in epic.get("task_ids", [])]
            target = self._match_epic_to_project(
                epic_key=epic_key,
                epic_name=epic["epic_name"],
                epic_summary=epic.get("summary"),
                todoist_projects=list(todoist_projects.values()),
                inbox_project=todoist_projects.get(inbox_project_id),
                persisted_targets=persisted_targets,
            )

            epic_item = {
                "epic_key": epic_key,
                "epic_name": epic["epic_name"],
                "summary": epic.get("summary"),
                "match": target,
                "tasks": [],
            }

            for task_id in task_ids:
                task = task_by_id.get(task_id)
                if task is None:
                    continue
                action_result = await self._sync_task(
                    run=run,
                    project=project,
                    task=task,
                    epic_key=epic_key,
                    epic_name=epic["epic_name"],
                    target=target,
                    include_done=include_done,
                )
                epic_item["tasks"].append(action_result)
                counts[action_result["action"]] += 1
                if action_result["status"] == "failed":
                    errors.append(action_result["error"])

            result_epics.append(epic_item)

        status = "completed"
        if errors and counts["created"] + counts["updated"] == 0:
            status = "failed"
        elif errors:
            status = "partial"

        result_data = {
            "epics": result_epics,
            "counts": dict(counts),
            "errors": errors,
        }

        run.status = status
        run.result_data = result_data
        run.error_text = "; ".join(errors) if errors else None
        run.metadata_ = {
            "source": "todoist_sync_service",
            "task_total": len(task_by_id),
        }
        await self.db.flush()
        await self.db.commit()

        return self._serialize_run(run)

    async def list_runs(self, project_id: uuid.UUID) -> dict[str, Any]:
        """List historical sync runs for a Burdello project."""
        result = await self.db.execute(
            select(TodoistSyncRun)
            .where(TodoistSyncRun.project_id == project_id)
            .order_by(TodoistSyncRun.created_at.desc())
        )
        runs = list(result.scalars().all())
        return {
            "total": len(runs),
            "items": [self._serialize_run_summary(run) for run in runs],
        }

    async def get_run(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a single run by ID."""
        result = await self.db.execute(
            select(TodoistSyncRun).where(TodoistSyncRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            return None
        return self._serialize_run(run)

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def _group_tasks_into_epics(
        self,
        project: Project,
        tasks: list[Task],
    ) -> list[dict[str, Any]]:
        task_records = [self._serialize_task(project, task) for task in tasks]
        if not task_records:
            return []

        prompt = self._load_prompt("todoist_epic_classification").format(
            project_name=project.name,
            project_description=project.description or "None",
            tasks_json=json.dumps(task_records, indent=2, ensure_ascii=False),
        )

        schema = {
            "type": "object",
            "properties": {
                "epics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "name": {"type": "string"},
                            "summary": {"type": "string"},
                            "task_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["key", "name", "summary", "task_ids"],
                    },
                }
            },
            "required": ["epics"],
        }

        try:
            response = await self.llm_client.extract_json(
                prompt=prompt,
                schema=schema,
                system_prompt=(
                    "You group Burdello tasks into Todoist epics. "
                    "Return valid JSON only."
                ),
            )
            epics = response.get("epics", []) if isinstance(response, dict) else []
            normalized = self._normalize_epic_response(task_records, epics)
            if normalized:
                return normalized
        except Exception as exc:
            logger.warning("Todoist epic grouping failed, using fallback: %s", exc)

        return self._fallback_group_tasks(task_records)

    def _normalize_epic_response(
        self,
        task_records: list[dict[str, Any]],
        epics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        task_ids = {item["task_id"] for item in task_records}
        used: set[str] = set()
        normalized: list[dict[str, Any]] = []

        for epic in epics:
            epic_task_ids = [
                uuid.UUID(task_id)
                for task_id in epic.get("task_ids", [])
                if task_id in task_ids
            ]
            if not epic_task_ids:
                continue
            key = self._slugify(epic.get("key") or epic.get("name") or "epic")
            name = str(epic.get("name") or key.replace("-", " ").title()).strip()
            summary = str(epic.get("summary") or "").strip() or None
            normalized.append(
                {
                    "key": key,
                    "name": name,
                    "summary": summary,
                    "task_ids": epic_task_ids,
                }
            )
            used.update(str(task_id) for task_id in epic_task_ids)

        missing = [item for item in task_records if item["task_id"] not in used]
        if missing:
            normalized.extend(self._fallback_group_tasks(missing))

        return normalized

    def _fallback_group_tasks(
        self,
        task_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for task in task_records:
            bucket = self._infer_bucket(task)
            buckets[bucket["key"]].append(task)

        epics: list[dict[str, Any]] = []
        for bucket_key, records in buckets.items():
            epics.append(
                {
                    "key": bucket_key,
                    "name": self._humanize(bucket_key),
                    "summary": self._summarize_tasks(records),
                    "task_ids": [uuid.UUID(item["task_id"]) for item in records],
                }
            )
        return epics

    def _infer_bucket(self, task: dict[str, Any]) -> dict[str, str]:
        text = " ".join(
            [
                task.get("title", ""),
                task.get("description", ""),
                " ".join(task.get("tags", []) or []),
                task.get("notes", ""),
            ]
        ).lower()

        categories = [
            ("auth-security", ["auth", "login", "token", "password", "oauth", "jwt", "session"]),
            ("api-backend", ["api", "endpoint", "router", "backend", "service", "graphql", "rest"]),
            ("frontend-ui", ["ui", "frontend", "react", "component", "layout", "page", "tailwind"]),
            ("tests", ["test", "pytest", "coverage", "spec", "e2e"]),
            ("docs", ["doc", "docs", "documentation", "readme", "guide"]),
            ("infra-deploy", ["deploy", "docker", "kubernetes", "terraform", "ci", "cd", "pipeline", "infra"]),
            ("bugfix", ["bug", "fix", "regression", "broken", "error", "crash"]),
            ("refactor", ["refactor", "cleanup", "simplify", "restructure"]),
            ("data-search", ["data", "search", "qdrant", "embedding", "vector", "index"]),
            ("research", ["research", "investigate", "explore", "analysis"]),
        ]

        best_key = "general"
        best_score = 0
        for key, keywords in categories:
            score = sum(1 for keyword in keywords if keyword in text)
            if score > best_score:
                best_key = key
                best_score = score
        return {"key": best_key}

    def _summarize_tasks(self, tasks: list[dict[str, Any]]) -> str | None:
        titles = [str(task.get("title", "")).strip() for task in tasks if task.get("title")]
        if not titles:
            return None
        if len(titles) == 1:
            return titles[0]
        return ", ".join(titles[:3]) + ("..." if len(titles) > 3 else "")

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _match_epic_to_project(
        self,
        epic_key: str,
        epic_name: str,
        epic_summary: str | None,
        todoist_projects: list[dict[str, Any]],
        inbox_project: dict[str, Any] | None,
        persisted_targets: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        persisted = persisted_targets.get(epic_key)
        if persisted is not None:
            project = self._project_by_id(todoist_projects, persisted["todoist_project_id"])
            if project is not None:
                return {
                    "todoist_project_id": project["id"],
                    "todoist_project_name": project["name"],
                    "score": 1.0,
                    "reason": "reused persisted mapping",
                    "source": "persisted",
                }

        best_project: dict[str, Any] | None = None
        best_score = 0.0
        for project in todoist_projects:
            score = self._project_match_score(epic_name, epic_summary, project["name"])
            if score > best_score:
                best_score = score
                best_project = project

        if best_project is not None and best_score >= 0.55:
            return {
                "todoist_project_id": best_project["id"],
                "todoist_project_name": best_project["name"],
                "score": round(best_score, 3),
                "reason": "fuzzy name match",
                "source": "fuzzy",
            }

        if inbox_project is not None:
            return {
                "todoist_project_id": inbox_project["id"],
                "todoist_project_name": inbox_project["name"],
                "score": best_score or 0.0,
                "reason": "fallback to Inbox",
                "source": "inbox",
            }

        return {
            "todoist_project_id": None,
            "todoist_project_name": None,
            "score": best_score or 0.0,
            "reason": "no Inbox project found",
            "source": "unmatched",
        }

    def _project_match_score(
        self,
        epic_name: str,
        epic_summary: str | None,
        project_name: str,
    ) -> float:
        lhs = self._normalize_match_text(epic_name)
        rhs = self._normalize_match_text(project_name)
        score = SequenceMatcher(None, lhs, rhs).ratio()
        if epic_summary:
            summary_score = SequenceMatcher(
                None,
                self._normalize_match_text(epic_summary),
                rhs,
            ).ratio()
            score = max(score, summary_score * 0.9)
        if lhs == rhs:
            score = 1.0
        return score

    def _project_by_id(
        self,
        todoist_projects: list[dict[str, Any]],
        project_id: str,
    ) -> dict[str, Any] | None:
        for project in todoist_projects:
            if project["id"] == project_id:
                return project
        return None

    def _normalize_match_text(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _find_inbox_project(
        self,
        todoist_projects: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for project in todoist_projects:
            if project.get("name", "").strip().lower() == "inbox":
                return project
        return None

    async def _load_persisted_epic_targets(
        self,
        project_id: uuid.UUID,
    ) -> dict[str, dict[str, Any]]:
        result = await self.db.execute(
            select(TodoistTaskLink)
            .where(TodoistTaskLink.project_id == project_id)
            .order_by(TodoistTaskLink.last_synced_at.desc().nullslast())
        )
        links = list(result.scalars().all())
        targets: dict[str, dict[str, Any]] = {}
        for link in links:
            targets.setdefault(
                link.epic_key,
                {
                    "todoist_project_id": link.todoist_project_id,
                    "todoist_project_name": link.todoist_project_name,
                },
            )
        return targets

    # ------------------------------------------------------------------
    # Sync execution
    # ------------------------------------------------------------------

    async def _sync_task(
        self,
        run: TodoistSyncRun,
        project: Project,
        task: Task,
        epic_key: str,
        epic_name: str,
        target: dict[str, Any],
        include_done: bool,
    ) -> dict[str, Any]:
        if task.status == "done" and not include_done:
            return {
                "task_id": str(task.id),
                "action": "skipped",
                "status": "skipped",
                "todoist_task_id": None,
                "todoist_project_id": target.get("todoist_project_id"),
                "todoist_project_name": target.get("todoist_project_name"),
                "error": None,
            }

        payload = self._build_task_payload(project, task, epic_name)
        todoist_project_id = target.get("todoist_project_id")
        link = await self._get_task_link(task.id)

        todoist_task: dict[str, Any] | None = None
        action = "created"
        error_text: str | None = None

        try:
            if link is not None:
                update_payload = {
                    "content": payload["content"],
                    "description": payload["description"],
                    "priority": payload["priority"],
                }
                if todoist_project_id:
                    update_payload["project_id"] = todoist_project_id
                if payload.get("due_date"):
                    update_payload["due_date"] = payload["due_date"]
                if payload.get("labels"):
                    update_payload["labels"] = payload["labels"]
                todoist_task = await self.todoist_client.update_task(
                    link.todoist_task_id,
                    **update_payload,
                )
                action = "updated"
            else:
                create_payload = {
                    "project_id": todoist_project_id or "",
                    "content": payload["content"],
                    "description": payload["description"],
                    "priority": payload["priority"],
                }
                if payload.get("due_date"):
                    create_payload["due_date"] = payload["due_date"]
                if payload.get("labels"):
                    create_payload["labels"] = payload["labels"]
                todoist_task = await self.todoist_client.create_task(**create_payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and link is not None:
                todoist_task = await self.todoist_client.create_task(
                    project_id=todoist_project_id or "",
                    content=payload["content"],
                    description=payload["description"],
                    priority=payload["priority"],
                    due_date=payload.get("due_date"),
                    labels=payload.get("labels"),
                )
                action = "recreated"
            else:
                error_text = str(exc)
        except Exception as exc:
            error_text = str(exc)

        if todoist_task is not None:
            await self._upsert_task_link(
                task=task,
                run=run,
                epic_key=epic_key,
                epic_name=epic_name,
                target=target,
                payload=payload,
                todoist_task=todoist_task,
            )
            return {
                "task_id": str(task.id),
                "action": action,
                "status": "ok",
                "todoist_task_id": todoist_task.get("id"),
                "todoist_project_id": todoist_project_id,
                "todoist_project_name": target.get("todoist_project_name"),
                "error": None,
            }

        await self._mark_link_error(task.id, run.id, error_text, payload, target, epic_key, epic_name)
        return {
            "task_id": str(task.id),
            "action": "failed",
            "status": "failed",
            "todoist_task_id": link.todoist_task_id if link else None,
            "todoist_project_id": todoist_project_id,
            "todoist_project_name": target.get("todoist_project_name"),
            "error": error_text or "Todoist sync failed",
        }

    async def _get_task_link(self, task_id: uuid.UUID) -> TodoistTaskLink | None:
        result = await self.db.execute(
            select(TodoistTaskLink).where(TodoistTaskLink.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def _upsert_task_link(
        self,
        task: Task,
        run: TodoistSyncRun,
        epic_key: str,
        epic_name: str,
        target: dict[str, Any],
        payload: dict[str, Any],
        todoist_task: dict[str, Any],
    ) -> None:
        link = await self._get_task_link(task.id)
        if link is None:
            link = TodoistTaskLink(
                task_id=task.id,
                project_id=task.project_id or run.project_id,
                epic_key=epic_key,
                epic_name=epic_name,
                todoist_project_id=target.get("todoist_project_id") or "",
                todoist_project_name=target.get("todoist_project_name") or "",
                todoist_task_id=str(todoist_task.get("id") or ""),
                sync_run_id=run.id,
                last_synced_at=datetime.now(timezone.utc),
                last_payload=payload,
                last_result=todoist_task,
                metadata_={},
            )
            self.db.add(link)
        else:
            link.project_id = task.project_id or run.project_id
            link.epic_key = epic_key
            link.epic_name = epic_name
            link.todoist_project_id = target.get("todoist_project_id") or link.todoist_project_id
            link.todoist_project_name = target.get("todoist_project_name") or link.todoist_project_name
            link.todoist_task_id = str(todoist_task.get("id") or link.todoist_task_id)
            link.sync_run_id = run.id
            link.last_synced_at = datetime.now(timezone.utc)
            link.last_payload = payload
            link.last_result = todoist_task
        await self.db.flush()

    async def _mark_link_error(
        self,
        task_id: uuid.UUID,
        run_id: uuid.UUID,
        error_text: str | None,
        payload: dict[str, Any],
        target: dict[str, Any],
        epic_key: str,
        epic_name: str,
    ) -> None:
        link = await self._get_task_link(task_id)
        if link is None:
            return
        link.sync_run_id = run_id
        link.last_synced_at = datetime.now(timezone.utc)
        link.last_payload = payload
        link.last_result = {
            "error": error_text,
            "todoist_project_id": target.get("todoist_project_id"),
            "todoist_project_name": target.get("todoist_project_name"),
            "epic_key": epic_key,
            "epic_name": epic_name,
        }
        await self.db.flush()

    def _build_task_payload(
        self,
        project: Project,
        task: Task,
        epic_name: str,
    ) -> dict[str, Any]:
        description_parts = [
            f"Burdello project: {project.name}",
            f"Epic: {epic_name}",
            f"Burdello task id: {task.id}",
            f"Status: {task.status}",
            f"Priority: {task.priority or 'medium'}",
        ]
        if task.due_date:
            description_parts.append(f"Due date: {task.due_date.date().isoformat()}")
        if task.tags:
            description_parts.append(f"Tags: {', '.join(task.tags)}")
        if task.notes:
            description_parts.append("")
            description_parts.append("Notes:")
            description_parts.append(task.notes)
        if task.description:
            description_parts.append("")
            description_parts.append("Details:")
            description_parts.append(task.description)
        if task.source_transcript_id:
            description_parts.append("")
            description_parts.append(f"Source transcript: {task.source_transcript_id}")
        description = "\n".join(description_parts).strip()
        if len(description) > 4000:
            description = description[:3997] + "..."

        labels = [str(tag).strip() for tag in (task.tags or []) if str(tag).strip()]

        return {
            "content": task.title.strip(),
            "description": description,
            "priority": self._priority_to_todoist(task.priority),
            "due_date": task.due_date.date().isoformat() if task.due_date else None,
            "labels": labels,
        }

    # ------------------------------------------------------------------
    # Persistence / serialization
    # ------------------------------------------------------------------

    async def _load_project(self, project_id: uuid.UUID) -> Project:
        result = await self.db.execute(
            select(Project)
            .options(selectinload(Project.tasks))
            .where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise LookupError(f"Project {project_id} not found")
        return project

    def _selected_tasks(
        self,
        project: Project,
        include_done: bool,
    ) -> list[Task]:
        tasks = list(project.tasks or [])
        if include_done:
            return tasks
        return [task for task in tasks if task.status != "done"]

    async def _load_todoist_projects(self) -> list[dict[str, Any]]:
        projects = await self.todoist_client.get_projects()
        return sorted(projects, key=lambda item: item.get("name", "").lower())

    def _serialize_task(
        self,
        project: Project,
        task: Task,
    ) -> dict[str, Any]:
        return {
            "task_id": str(task.id),
            "title": task.title,
            "description": task.description or "",
            "notes": task.notes or "",
            "tags": task.tags or [],
            "status": task.status,
            "priority": task.priority or "medium",
            "due_date": task.due_date.date().isoformat() if task.due_date else None,
            "project_name": project.name,
        }

    def _serialize_run_summary(self, run: TodoistSyncRun) -> dict[str, Any]:
        metrics = {}
        if isinstance(run.result_data, dict):
            metrics = run.result_data.get("counts", {}) or {}
        return {
            "id": run.id,
            "project_id": run.project_id,
            "project_name": run.project_name,
            "status": run.status,
            "include_done": run.include_done,
            "todoist_inbox_project_id": run.todoist_inbox_project_id,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "error_text": run.error_text,
            "metrics": metrics,
        }

    def _serialize_run(self, run: TodoistSyncRun) -> dict[str, Any]:
        payload = self._serialize_run_summary(run)
        payload["plan_data"] = run.plan_data or {}
        payload["result_data"] = run.result_data or {}
        return payload

    def _make_todoist_client(self) -> TodoistClient:
        settings = get_settings()
        token = getattr(settings, "TODOIST_API_TOKEN", "") or "dummy-token"
        return TodoistClient(access_token=token)

    def _make_llm_client(self) -> LiteLLMClient:
        settings = get_settings()
        return LiteLLMClient(
            base_url=settings.LITELLM_URL,
            api_key=settings.LITELLM_API_KEY,
        )

    def _load_prompt(self, template_name: str) -> str:
        template_path = _PROMPTS_DIR / f"{template_name}.txt"
        with open(template_path, "r", encoding="utf-8") as fh:
            return fh.read()

    def _priority_to_todoist(self, priority: str | None) -> int:
        mapping = {"low": 1, "medium": 2, "high": 4}
        return mapping.get(priority or "medium", 2)

    def _slugify(self, value: str) -> str:
        value = value.lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = re.sub(r"-+", "-", value).strip("-")
        return value or "epic"

    def _humanize(self, slug: str) -> str:
        parts = [part for part in slug.replace("_", "-").split("-") if part]
        if not parts:
            return "General"
        return " ".join(part.capitalize() for part in parts)


__all__ = ["TodoistSyncService"]
