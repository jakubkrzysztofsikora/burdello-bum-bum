"""LiteLLM client wrapper.

Provides ``LiteLLMClient`` which wraps ``litellm.acompletion`` with
error handling, JSON-mode extraction, and health checking.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Attempt to import litellm — if not available, the client degrades gracefully
try:
    import litellm

    _LITELLM_AVAILABLE = True
except ImportError:
    _LITELLM_AVAILABLE = False
    litellm = None  # type: ignore[assignment]


class LiteLLMClient:
    """Async client for LiteLLM proxy / OpenAI-compatible APIs.

    Wraps ``litellm.acompletion`` with consistent error handling,
    JSON-mode support, and health checking.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4000",
        api_key: str = "",
        default_model: str = "gpt-4o-mini",
    ) -> None:
        """Initialise the LiteLLM client.

        Args:
            base_url: LiteLLM proxy base URL.
            api_key: API key for authentication.
            default_model: Default model identifier.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

        if _LITELLM_AVAILABLE and litellm is not None:
            litellm.api_base = self.base_url
            if api_key:
                litellm.api_key = api_key
            # Reduce litellm verbosity
            litellm.suppress_debug_info = True
            litellm.set_verbose = False

        # HTTP client for health checks
        self.http_client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10.0,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.http_client.aclose()

    async def __aenter__(self) -> LiteLLMClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            model: Model identifier (defaults to ``default_model``).
            response_format: Optional response format dict for JSON mode.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional arguments passed to ``litellm.acompletion``.

        Returns:
            Completion response dict with ``choices``, ``usage``, etc.

        Raises:
            RuntimeError: If litellm is not installed.
            Exception: If the API call fails.
        """
        if not _LITELLM_AVAILABLE:
            raise RuntimeError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        model_id = model or self.default_model

        request_args: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        if response_format:
            request_args["response_format"] = response_format

        try:
            response = await litellm.acompletion(**request_args)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("LiteLLM completion error: %s", exc)
            raise

        # Convert ModelResponse to dict
        result: dict[str, Any]
        if hasattr(response, "model_dump"):
            result = response.model_dump()
        elif hasattr(response, "dict"):
            result = response.dict()
        else:
            result = dict(response)

        logger.debug(
            "LiteLLM completion: model=%s prompt_tokens=%s completion_tokens=%s",
            model_id,
            result.get("usage", {}).get("prompt_tokens", "?"),
            result.get("usage", {}).get("completion_tokens", "?"),
        )

        return result

    async def extract_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        system_prompt: str = "You are a helpful assistant. Respond with valid JSON only.",
    ) -> dict[str, Any]:
        """Extract structured JSON from a prompt.

        Uses the ``response_format={"type": "json_object"}`` mode to
        enforce JSON output.

        Args:
            prompt: User prompt to send.
            schema: Optional JSON schema dict (used in system prompt).
            model: Model identifier override.
            system_prompt: System prompt for the extraction.

        Returns:
            Parsed JSON dict.

        Raises:
            RuntimeError: If litellm is not installed.
            ValueError: If the response is not valid JSON.
        """
        if not _LITELLM_AVAILABLE:
            raise RuntimeError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        if schema:
            schema_text = json.dumps(schema, indent=2)
            messages[0]["content"] += (
                f"\n\nRespond with JSON matching this schema:\n{schema_text}"
            )

        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.completion(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except Exception as exc:
            logger.error("JSON extraction error: %s", exc)
            raise

        # Extract content from response
        try:
            content = response["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return json.loads(content)
            return dict(content)
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to parse JSON from response: {exc}")

    async def health_check(self) -> bool:
        """Check if the LiteLLM proxy is reachable.

        Returns:
            ``True`` if the proxy responds, ``False`` otherwise.
        """
        try:
            response = await self.http_client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception as exc:
            logger.debug("LiteLLM health check failed: %s", exc)
            return False

    async def list_models(self) -> list[str]:
        """List available models from the LiteLLM proxy.

        Returns:
            List of model ID strings.

        Raises:
            RuntimeError: If litellm is not installed.
        """
        if not _LITELLM_AVAILABLE:
            raise RuntimeError("litellm is not installed.")

        try:
            response = await litellm.get_model_list()  # type: ignore[union-attr]
            if hasattr(response, "data"):
                return [m.id for m in response.data if hasattr(m, "id")]
            if isinstance(response, list):
                return [m.get("id", "") for m in response if isinstance(m, dict)]
            return []
        except Exception as exc:
            logger.error("Failed to list models: %s", exc)
            return []

    async def embedding(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Get embeddings for a list of texts.

        Args:
            texts: List of strings to embed.
            model: Embedding model identifier.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If litellm is not installed.
        """
        if not _LITELLM_AVAILABLE:
            raise RuntimeError("litellm is not installed.")

        try:
            response = await litellm.aembedding(  # type: ignore[union-attr]
                model=model or "text-embedding-3-small",
                input=texts,
            )
            embeddings: list[list[float]] = []
            for item in response.data:
                if hasattr(item, "embedding"):
                    embeddings.append(item.embedding)
                elif isinstance(item, dict):
                    embeddings.append(item["embedding"])
            return embeddings
        except Exception as exc:
            logger.error("Embedding error: %s", exc)
            raise
