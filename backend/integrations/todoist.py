"""Todoist REST API client.

Provides ``TodoistClient`` which wraps the Todoist REST API v2 for
project and task management operations.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TodoistClient:
    """Async client for the Todoist REST API v2.

    Manages projects, tasks, subtasks, comments, and completions.
    Uses ``httpx.AsyncClient`` for all HTTP operations.
    """

    BASE_URL = "https://api.todoist.com/rest/v2"

    def __init__(self, access_token: str) -> None:
        """Initialise the Todoist client.

        Args:
            access_token: Todoist API personal token.
        """
        self.token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            headers=self.headers,
            base_url=self.BASE_URL,
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> TodoistClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def get_projects(self) -> list[dict[str, Any]]:
        """List all projects in the Todoist account.

        Returns:
            List of project dicts with ``id``, ``name``, etc.

        Raises:
            httpx.HTTPError: If the API request fails.
        """
        response = await self.client.get("/projects")
        response.raise_for_status()
        projects: list[dict[str, Any]] = response.json()
        logger.debug("Retrieved %d Todoist projects", len(projects))
        return projects

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Get a single project by ID.

        Args:
            project_id: Todoist project ID.

        Returns:
            Project dict.
        """
        response = await self.client.get(f"/projects/{project_id}")
        response.raise_for_status()
        return dict(response.json())

    async def create_project(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        """Create a new Todoist project.

        Args:
            name: Project name.
            parent_id: Optional parent project ID.

        Returns:
            Created project dict.
        """
        payload: dict[str, Any] = {"name": name}
        if parent_id:
            payload["parent_id"] = parent_id

        response = await self.client.post("/projects", json=payload)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        logger.info("Created Todoist project %r (id=%s)", name, result.get("id"))
        return result

    async def delete_project(self, project_id: str) -> None:
        """Delete a Todoist project.

        Args:
            project_id: Project ID to delete.
        """
        response = await self.client.delete(f"/projects/{project_id}")
        response.raise_for_status()
        logger.info("Deleted Todoist project %s", project_id)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def get_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """List tasks, optionally filtered by project.

        Args:
            project_id: Optional project ID filter.

        Returns:
            List of task dicts.
        """
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id

        response = await self.client.get("/tasks", params=params)
        response.raise_for_status()
        tasks: list[dict[str, Any]] = response.json()
        return tasks

    async def create_task(
        self,
        project_id: str,
        content: str,
        description: str = "",
        due_date: str | None = None,
        priority: int = 1,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new task in Todoist.

        Args:
            project_id: Project ID to add the task to.
            content: Task title/content.
            description: Optional longer description.
            due_date: Optional due date (YYYY-MM-DD format).
            priority: Priority from 1 (normal) to 4 (urgent).
            labels: Optional list of label names.

        Returns:
            Created task dict.
        """
        payload: dict[str, Any] = {
            "content": content,
            "description": description,
            "priority": priority,
        }
        if project_id:
            payload["project_id"] = project_id
        if due_date:
            payload["due_date"] = due_date
        if labels:
            payload["labels"] = labels

        response = await self.client.post("/tasks", json=payload)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        logger.info("Created Todoist task %r (id=%s)", content, result.get("id"))
        return result

    async def create_subtask(
        self,
        parent_id: str,
        content: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a subtask under an existing task.

        Args:
            parent_id: Parent task ID.
            content: Subtask content.
            description: Optional description.

        Returns:
            Created subtask dict.
        """
        payload: dict[str, Any] = {
            "content": content,
            "description": description,
            "parent_id": parent_id,
        }

        response = await self.client.post("/tasks", json=payload)
        response.raise_for_status()
        return dict(response.json())

    async def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update an existing task.

        Args:
            task_id: Task ID to update.
            **kwargs: Fields to update (content, description, priority, etc.).

        Returns:
            Updated task dict.
        """
        response = await self.client.post(f"/tasks/{task_id}", json=kwargs)
        response.raise_for_status()
        return dict(response.json())

    async def complete_task(self, task_id: str) -> dict[str, Any]:
        """Mark a task as completed.

        Args:
            task_id: Task ID to complete.

        Returns:
            Completion response.
        """
        response = await self.client.post(f"/tasks/{task_id}/close")
        response.raise_for_status()
        logger.info("Completed Todoist task %s", task_id)
        return {"id": task_id, "status": "completed"}

    async def delete_task(self, task_id: str) -> None:
        """Delete a task.

        Args:
            task_id: Task ID to delete.
        """
        response = await self.client.delete(f"/tasks/{task_id}")
        response.raise_for_status()
        logger.info("Deleted Todoist task %s", task_id)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    async def add_comment(
        self,
        task_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Add a comment to a task.

        Args:
            task_id: Task ID to comment on.
            content: Comment text (supports Markdown).

        Returns:
            Created comment dict.
        """
        payload = {
            "task_id": task_id,
            "content": content,
        }

        response = await self.client.post("/comments", json=payload)
        response.raise_for_status()
        return dict(response.json())

    async def get_comments(self, task_id: str) -> list[dict[str, Any]]:
        """Get all comments on a task.

        Args:
            task_id: Task ID.

        Returns:
            List of comment dicts.
        """
        response = await self.client.get("/comments", params={"task_id": task_id})
        response.raise_for_status()
        comments: list[dict[str, Any]] = response.json()
        return comments
