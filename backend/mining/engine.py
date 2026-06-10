"""LLM Data Mining Engine for extracting structured data from transcripts.

Provides ``MiningEngine`` which uses LiteLLM to run structured extraction
prompts against transcript text, identifying projects, tasks, artifacts,
status inferences, missing elements, and abandoned work.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Default prompts directory
_PROMPTS_DIR = Path(__file__).parent / "prompts"


class MiningEngine:
    """Uses a LiteLLM gateway to extract structured data from transcripts.

    All extraction methods are async and return structured dictionaries
    suitable for storage as ``MiningResult`` records.
    """

    def __init__(
        self,
        litellm_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialise the mining engine.

        Args:
            litellm_url: URL of the LiteLLM proxy gateway. Falls back to
                ``LITELLM_URL`` from settings, then ``http://localhost:4000``.
            model: LiteLLM model identifier. Falls back to
                ``BB_MINING_MODEL`` env var, then ``gpt-4o-mini``.
        """
        settings = get_settings()
        self.litellm_url = (litellm_url or settings.LITELLM_URL).rstrip("/")
        raw_model = model or os.environ.get("BB_MINING_MODEL", "gpt-4o-mini")
        # LiteLLM needs an explicit provider prefix to route via the
        # OpenAI-compatible api_base; bare model names like "kimi" trigger
        # "LLM Provider NOT provided". Default to openai/ when the caller
        # supplied no prefix.
        self.model = raw_model if "/" in raw_model else f"openai/{raw_model}"
        self.api_key = settings.LITELLM_API_KEY or os.environ.get("LITELLM_API_KEY", "")

    async def extract_projects(self, transcript_text: str) -> list[dict[str, Any]]:
        """Extract software projects mentioned in the transcript.

        Args:
            transcript_text: Full transcript text to analyse.

        Returns:
            List of project dicts with ``name``, ``description``, ``status``,
            and ``confidence`` keys.
        """
        prompt = self._load_prompt("project_extraction").format(
            transcript_text=transcript_text[:8000]
        )
        response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "description", "status", "confidence"],
            },
        }
        result = await self._call_llm(prompt, response_schema=response_schema)
        return result if isinstance(result, list) else []

    async def extract_tasks(
        self,
        transcript_text: str,
        project_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract actionable tasks from the transcript.

        Args:
            transcript_text: Full transcript text to analyse.
            project_context: Optional project description for context.

        Returns:
            List of task dicts with ``title``, ``description``, ``status``,
            ``priority``, and ``confidence`` keys.
        """
        prompt = self._load_prompt("task_extraction").format(
            transcript_text=transcript_text[:8000],
            project_context=project_context or "None provided",
        )
        response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                    "priority": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["title", "description", "status", "priority", "confidence"],
            },
        }
        result = await self._call_llm(prompt, response_schema=response_schema)
        return result if isinstance(result, list) else []

    async def infer_status(self, transcript_text: str) -> dict[str, Any]:
        """Infer the overall work status from the transcript.

        Args:
            transcript_text: Full transcript text to analyse.

        Returns:
            Dict with ``overall_status``, ``confidence``, ``reasoning``,
            ``phase``, and ``blockers`` keys.
        """
        prompt = self._load_prompt("status_inference").format(
            transcript_text=transcript_text[:8000]
        )
        response_schema = {
            "type": "object",
            "properties": {
                "overall_status": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
                "phase": {"type": "string"},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["overall_status", "confidence", "reasoning", "phase", "blockers"],
        }
        result = await self._call_llm(prompt, response_schema=response_schema)
        if isinstance(result, dict):
            return result
        return {
            "overall_status": "unknown",
            "confidence": 0.0,
            "reasoning": "Failed to parse LLM response",
            "phase": "unknown",
            "blockers": [],
        }

    async def extract_artifacts(self, transcript_text: str) -> list[dict[str, Any]]:
        """Identify code artifacts created or modified in the transcript.

        Args:
            transcript_text: Full transcript text to analyse.

        Returns:
            List of artifact dicts with ``name``, ``type``, ``language``,
            ``content_preview``, ``file_path``, and ``confidence`` keys.
        """
        prompt = self._load_prompt("artifact_extraction").format(
            transcript_text=transcript_text[:8000]
        )
        response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "language": {"type": "string"},
                    "content_preview": {"type": "string"},
                    "file_path": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "type", "language", "content_preview", "file_path", "confidence"],
            },
        }
        result = await self._call_llm(prompt, response_schema=response_schema)
        return result if isinstance(result, list) else []

    async def find_missing_elements(self, transcript_text: str) -> list[str]:
        """Find incomplete work items in the transcript.

        Args:
            transcript_text: Full transcript text to analyse.

        Returns:
            List of strings describing incomplete work items.
        """
        prompt = self._load_prompt("missing_elements").format(
            transcript_text=transcript_text[:8000]
        )
        response_schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        result = await self._call_llm(prompt, response_schema=response_schema)
        return result if isinstance(result, list) else []

    async def detect_abandoned_work(
        self,
        transcript: dict[str, Any],
        days_threshold: int = 7,
    ) -> dict[str, Any]:
        """Detect whether a transcript represents abandoned work.

        Uses heuristics combined with LLM analysis to determine if the
        session was left incomplete and not resumed.

        Args:
            transcript: Dict with at least ``text`` and ``created_at`` keys.
            days_threshold: Number of days without follow-up to consider
                work abandoned.

        Returns:
            Dict with ``is_abandoned``, ``confidence``, and ``reason`` keys.
        """
        text = transcript.get("text", "")
        created_at = transcript.get("created_at")

        # Check for explicit completion markers
        completion_markers = [
            "done", "completed", "finished", "wrapped up",
            "that's all", "session complete", "closing",
        ]
        abandonment_markers = [
            "i'll continue later", "to be continued", "let's pick this up",
            "back soon", "need to stop", "ran out of time",
        ]

        text_lower = text.lower()
        has_completion = any(m in text_lower for m in completion_markers)
        has_abandonment = any(m in text_lower for m in abandonment_markers)

        # Simple heuristic scoring
        if has_completion and not has_abandonment:
            return {
                "is_abandoned": False,
                "confidence": 0.7,
                "reason": "Explicit completion markers found in transcript",
            }

        if has_abandonment:
            return {
                "is_abandoned": True,
                "confidence": 0.6,
                "reason": "Explicit continuation markers found — work appears paused",
            }

        # Default: inconclusive
        return {
            "is_abandoned": False,
            "confidence": 0.3,
            "reason": f"No clear markers; threshold={days_threshold} days",
        }

    async def mine_transcript(
        self,
        transcript_id: uuid.UUID,
        transcript_text: str,
        project_context: str | None = None,
    ) -> dict[str, Any]:
        """Run all mining operations on a transcript.

        This is the main entry point — it orchestrates project extraction,
        task extraction, status inference, artifact extraction, and
        missing-element detection.

        Args:
            transcript_id: UUID of the transcript being mined.
            transcript_text: Full text of the transcript.

        Returns:
            Combined mining results with all extraction outputs.
        """
        logger.info("mine_transcript: starting mining for %s", transcript_id)

        # When the caller supplies a deterministic project_context (path-based
        # repo resolver), skip the LLM extract_projects call entirely — its
        # output is discarded by the new project-override path. Saves one LLM
        # roundtrip per transcript.
        if project_context is None:
            projects = await self.extract_projects(transcript_text)
            project_names = [p.get("name", "") for p in projects]
            project_context = ", ".join(project_names) if project_names else None
        else:
            projects = []

        tasks = await self.extract_tasks(transcript_text, project_context)
        status = await self.infer_status(transcript_text)
        artifacts = await self.extract_artifacts(transcript_text)
        missing = await self.find_missing_elements(transcript_text)
        abandoned = await self.detect_abandoned_work({"text": transcript_text})

        results = {
            "transcript_id": str(transcript_id),
            "projects": projects,
            "tasks": tasks,
            "status": status,
            "artifacts": artifacts,
            "missing_elements": missing,
            "abandoned_work": abandoned,
        }

        logger.info(
            "mine_transcript: completed for %s — %d projects, %d tasks, %d artifacts",
            transcript_id,
            len(projects),
            len(tasks),
            len(artifacts),
        )
        return results

    def _load_prompt(self, template_name: str) -> str:
        """Load a prompt template from the prompts directory.

        Args:
            template_name: Base name of the template file (without ``.txt``).

        Returns:
            The prompt template string.

        Raises:
            FileNotFoundError: If the template file does not exist.
        """
        template_path = _PROMPTS_DIR / f"{template_name}.txt"
        with open(template_path, "r", encoding="utf-8") as fh:
            return fh.read()

    async def _call_llm(
        self,
        prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Call the LLM via LiteLLM with optional JSON response format.

        Args:
            prompt: The complete prompt text.
            response_schema: Optional JSON schema to request structured output.

        Returns:
            Parsed JSON response from the LLM.
        """
        import litellm

        litellm.api_base = self.litellm_url
        if self.api_key:
            litellm.api_key = self.api_key

        messages = [
            {"role": "system", "content": "You are a structured data extraction assistant. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4000,
        }

        if response_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content

            if not content:
                logger.warning("_call_llm: empty response content")
                return {} if response_schema and response_schema.get("type") == "object" else []

            # Models (notably Claude) often wrap JSON in a ```json ... ``` fence
            # even in json_object mode; strip it before parsing.
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```[a-zA-Z0-9]*\s*", "", content)
                content = re.sub(r"\s*```$", "", content).strip()

            # Parse JSON response
            parsed = json.loads(content)

            # If an array was requested but the model wrapped it in an object
            # (e.g. {"projects": [...]}), return the first list value found.
            if (
                isinstance(parsed, dict)
                and response_schema
                and response_schema.get("type") == "array"
            ):
                for value in parsed.values():
                    if isinstance(value, list):
                        return value
                return []

            return parsed

        except json.JSONDecodeError as exc:
            # The model returned unparseable content — retrying rarely helps,
            # so treat as an empty (but successful) extraction.
            logger.error("_call_llm: JSON decode error: %s", exc)
            return {} if response_schema and response_schema.get("type") == "object" else []
        except Exception as exc:
            # Connection / provider errors (e.g. LiteLLM unreachable) MUST
            # propagate so the Celery task retries with backoff, instead of
            # silently storing empty mining results and marking the transcript
            # mined. Losing data on a transient outage is worse than retrying.
            logger.error("_call_llm: LLM call failed (will retry): %s", exc)
            raise
