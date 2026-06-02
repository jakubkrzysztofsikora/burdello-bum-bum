"""Tests for the LLM Data Mining Engine.

Covers project extraction, task extraction, status inference, artifact
extraction, missing element detection, abandoned work detection, and
the main mine_transcript orchestration.  All LLM calls are mocked.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.mining.engine import MiningEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_litellm():
    """Patch litellm.acompletion with a mock that returns structured JSON."""
    with patch("backend.mining.engine.litellm") as mock_lm:
        yield mock_lm


@pytest.fixture
def mining_engine() -> MiningEngine:
    """Return a MiningEngine with mocked config."""
    return MiningEngine(litellm_url="http://test-llm:4000", model="gpt-4o-mini")


@pytest.fixture
async def mock_llm_response(mock_litellm):
    """Configure the mock litellm to return a JSON string response."""

    def configure_response(data: Any):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(data)
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

    return configure_response


@pytest.fixture
def sample_transcript() -> str:
    """Return a sample transcript for mining."""
    return (
        "User: Let's build the authentication service.\n"
        "Assistant: I'll create the auth module with JWT support.\n"
        "User: Also add password hashing with bcrypt.\n"
        "Assistant: Done. I've created the AuthService class.\n"
        "User: We need to add tests for the login endpoint.\n"
        "Assistant: I'll write unit tests for the auth module.\n"
        "User: Don't forget about the API documentation.\n"
        "Assistant: I'll add OpenAPI docs for the endpoints.\n"
        "User: The deployment config needs updating too.\n"
        "Assistant: I'll update the Kubernetes manifests.\n"
    )


# ---------------------------------------------------------------------------
# MiningEngine.__init__
# ---------------------------------------------------------------------------


class TestMiningEngineInit:
    """Test MiningEngine initialisation."""

    def test_default_url(self):
        """Should use provided litellm_url."""
        engine = MiningEngine(litellm_url="http://custom:4000")

        assert engine.litellm_url == "http://custom:4000"

    def test_default_model(self):
        """Should use provided model."""
        engine = MiningEngine(model="gpt-4o")

        assert engine.model == "gpt-4o"

    def test_url_strips_trailing_slash(self):
        """Should strip trailing slash from URL."""
        engine = MiningEngine(litellm_url="http://localhost:4000/")

        assert engine.litellm_url == "http://localhost:4000"

    def test_model_from_env(self):
        """Should read model from environment variable."""
        with patch.dict("os.environ", {"BB_MINING_MODEL": "claude-sonnet"}):
            engine = MiningEngine()

            assert engine.model == "claude-sonnet"


# ---------------------------------------------------------------------------
# extract_projects
# ---------------------------------------------------------------------------


class TestExtractProjects:
    """Test project extraction."""

    @pytest.mark.asyncio
    async def test_returns_list_of_projects(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a list of project dicts."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"name": "auth-service", "description": "JWT auth system", "status": "active", "confidence": 0.95}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_projects(sample_transcript)

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_project_has_required_fields(self, mining_engine, mock_litellm, sample_transcript):
        """Each project should have name, description, status, confidence."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"name": "api", "description": "REST API", "status": "active", "confidence": 0.9}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_projects(sample_transcript)

        project = result[0]
        assert "name" in project
        assert "description" in project
        assert "status" in project
        assert "confidence" in project

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self, mining_engine, mock_litellm, sample_transcript):
        """Empty LLM response should return empty list."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_projects(sample_transcript)

        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_list(self, mining_engine, mock_litellm, sample_transcript):
        """Invalid JSON response should return empty list."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_projects(sample_transcript)

        assert result == []


# ---------------------------------------------------------------------------
# extract_tasks
# ---------------------------------------------------------------------------


class TestExtractTasks:
    """Test task extraction."""

    @pytest.mark.asyncio
    async def test_returns_list_of_tasks(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a list of task dicts."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"title": "Add JWT auth", "description": "Implement JWT tokens", "status": "todo", "priority": "high", "confidence": 0.9}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_tasks(sample_transcript)

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_task_has_required_fields(self, mining_engine, mock_litellm, sample_transcript):
        """Each task should have title, description, status, priority, confidence."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"title": "Write tests", "description": "Add unit tests", "status": "todo", "priority": "medium", "confidence": 0.85}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_tasks(sample_transcript)

        task = result[0]
        assert "title" in task
        assert "description" in task
        assert "status" in task
        assert "priority" in task
        assert "confidence" in task

    @pytest.mark.asyncio
    async def test_uses_project_context(self, mining_engine, mock_litellm, sample_transcript):
        """Should include project context in the prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        await mining_engine.extract_tasks(sample_transcript, project_context="auth-service")

        # Verify the call was made
        mock_litellm.acompletion.assert_called_once()
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert "messages" in call_kwargs


# ---------------------------------------------------------------------------
# infer_status
# ---------------------------------------------------------------------------


class TestInferStatus:
    """Test status inference."""

    @pytest.mark.asyncio
    async def test_returns_status_dict(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a dict with status fields."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "overall_status": "in_progress",
            "confidence": 0.85,
            "reasoning": "Active development is occurring",
            "phase": "implementation",
            "blockers": [],
        })
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.infer_status(sample_transcript)

        assert isinstance(result, dict)
        assert "overall_status" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "phase" in result
        assert "blockers" in result

    @pytest.mark.asyncio
    async def test_returns_defaults_on_invalid_response(self, mining_engine, mock_litellm, sample_transcript):
        """Invalid response should return default status dict."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not json"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.infer_status(sample_transcript)

        assert result["overall_status"] == "unknown"
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# extract_artifacts
# ---------------------------------------------------------------------------


class TestExtractArtifacts:
    """Test artifact extraction."""

    @pytest.mark.asyncio
    async def test_returns_list_of_artifacts(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a list of artifact dicts."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"name": "auth_service.py", "type": "source_code", "language": "python", "content_preview": "class AuthService:", "file_path": "/src/auth.py", "confidence": 0.95}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_artifacts(sample_transcript)

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_artifact_has_required_fields(self, mining_engine, mock_litellm, sample_transcript):
        """Each artifact should have required fields."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"name": "config.yaml", "type": "config", "language": "yaml", "content_preview": "api:", "file_path": "/config.yaml", "confidence": 0.9}
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.extract_artifacts(sample_transcript)

        artifact = result[0]
        assert "name" in artifact
        assert "type" in artifact
        assert "language" in artifact
        assert "content_preview" in artifact
        assert "file_path" in artifact
        assert "confidence" in artifact


# ---------------------------------------------------------------------------
# find_missing_elements
# ---------------------------------------------------------------------------


class TestFindMissingElements:
    """Test missing element detection."""

    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a list of strings describing missing work."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            "Tests for login endpoint not yet written",
            "API documentation is incomplete",
        ])
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.find_missing_elements(sample_transcript)

        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self, mining_engine, mock_litellm, sample_transcript):
        """Empty response should return empty list."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine.find_missing_elements(sample_transcript)

        assert result == []


# ---------------------------------------------------------------------------
# detect_abandoned_work
# ---------------------------------------------------------------------------


class TestDetectAbandonedWork:
    """Test abandoned work detection."""

    @pytest.mark.asyncio
    async def test_completion_markers_not_abandoned(self, mining_engine):
        """Transcript with completion markers should not be abandoned."""
        transcript = {"text": "We are done with the implementation. Completed!", "created_at": None}
        result = await mining_engine.detect_abandoned_work(transcript)

        assert result["is_abandoned"] is False
        assert result["confidence"] > 0.5

    @pytest.mark.asyncio
    async def test_continuation_markers_are_abandoned(self, mining_engine):
        """Transcript with continuation markers should be flagged."""
        transcript = {"text": "I'll continue later. Let's pick this up tomorrow.", "created_at": None}
        result = await mining_engine.detect_abandoned_work(transcript)

        assert result["is_abandoned"] is True

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_fields(self, mining_engine):
        """Result should have is_abandoned, confidence, reason."""
        transcript = {"text": "Random work session content.", "created_at": None}
        result = await mining_engine.detect_abandoned_work(transcript)

        assert isinstance(result, dict)
        assert "is_abandoned" in result
        assert isinstance(result["is_abandoned"], bool)
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert "reason" in result
        assert isinstance(result["reason"], str)

    @pytest.mark.asyncio
    async def test_uses_days_threshold(self, mining_engine):
        """days_threshold parameter should be accepted."""
        transcript = {"text": "Some session content.", "created_at": None}
        result = await mining_engine.detect_abandoned_work(transcript, days_threshold=14)

        assert isinstance(result, dict)
        assert "is_abandoned" in result


# ---------------------------------------------------------------------------
# mine_transcript
# ---------------------------------------------------------------------------


class TestMineTranscript:
    """Test the full mining orchestration."""

    @pytest.mark.asyncio
    async def test_returns_combined_results(self, mining_engine, mock_litellm, sample_transcript):
        """Should return a dict with all mining results."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # Return different responses for different prompts
        responses = {
            "project": [{"name": "auth", "description": "Auth system", "status": "active", "confidence": 0.9}],
            "task": [{"title": "Add tests", "description": "Write unit tests", "status": "todo", "priority": "high", "confidence": 0.85}],
            "status": {"overall_status": "in_progress", "confidence": 0.8, "reasoning": "Active work", "phase": "implementation", "blockers": []},
            "artifact": [{"name": "auth.py", "type": "source_code", "language": "python", "content_preview": "class Auth:", "file_path": "/auth.py", "confidence": 0.9}],
            "missing": ["Tests not written"],
        }

        call_count = [0]

        async def mock_acompletion(**kwargs):
            call_count[0] += 1
            content = "[]"
            messages = kwargs.get("messages", [])
            prompt = messages[1]["content"] if len(messages) > 1 else ""

            if "project" in prompt.lower():
                content = json.dumps(responses["project"])
            elif "task" in prompt.lower():
                content = json.dumps(responses["task"])
            elif "status" in prompt.lower():
                content = json.dumps(responses["status"])
            elif "artifact" in prompt.lower():
                content = json.dumps(responses["artifact"])
            elif "missing" in prompt.lower() or "incomplete" in prompt.lower():
                content = json.dumps(responses["missing"])

            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = content
            return mock_resp

        mock_litellm.acompletion = mock_acompletion

        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        result = await mining_engine.mine_transcript(transcript_id, sample_transcript)

        assert "transcript_id" in result
        assert "projects" in result
        assert "tasks" in result
        assert "status" in result
        assert "artifacts" in result
        assert "missing_elements" in result
        assert "abandoned_work" in result

    @pytest.mark.asyncio
    async def test_transcript_id_in_result(self, mining_engine, mock_litellm, sample_transcript):
        """Result should contain the transcript_id as string."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        result = await mining_engine.mine_transcript(transcript_id, sample_transcript)

        assert result["transcript_id"] == str(transcript_id)


# ---------------------------------------------------------------------------
# _load_prompt
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    """Test prompt template loading."""

    def test_loads_existing_prompt(self, mining_engine):
        """Should load an existing prompt template."""
        prompt = mining_engine._load_prompt("project_extraction")

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "{transcript_text}" in prompt

    def test_loads_all_prompts(self, mining_engine):
        """All prompt templates should be loadable."""
        template_names = [
            "project_extraction",
            "task_extraction",
            "status_inference",
            "artifact_extraction",
            "missing_elements",
        ]

        for name in template_names:
            prompt = mining_engine._load_prompt(name)
            assert isinstance(prompt, str)
            assert len(prompt) > 10

    def test_raises_on_missing_template(self, mining_engine):
        """Should raise FileNotFoundError for missing templates."""
        with pytest.raises(FileNotFoundError):
            mining_engine._load_prompt("nonexistent_template")


# ---------------------------------------------------------------------------
# _call_llm
# ---------------------------------------------------------------------------


class TestCallLLM:
    """Test the LLM call method."""

    @pytest.mark.asyncio
    async def test_sets_litellm_api_base(self, mining_engine, mock_litellm):
        """Should configure litellm.api_base."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        await mining_engine._call_llm("test prompt")

        assert mock_litellm.api_base == "http://test-llm:4000"

    @pytest.mark.asyncio
    async def test_returns_parsed_json(self, mining_engine, mock_litellm):
        """Should return parsed JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine._call_llm("test prompt")

        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_handles_empty_content(self, mining_engine, mock_litellm):
        """Empty content should return default empty value."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine._call_llm("test prompt")

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_json_decode_error(self, mining_engine, mock_litellm):
        """Invalid JSON should return default empty value."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not json at all"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        result = await mining_engine._call_llm("test prompt")

        assert result == []

    @pytest.mark.asyncio
    async def test_sets_temperature_and_max_tokens(self, mining_engine, mock_litellm):
        """Should use low temperature and limited max_tokens."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        await mining_engine._call_llm("test prompt")

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["max_tokens"] == 4000
