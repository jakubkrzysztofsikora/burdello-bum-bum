"""Seed taxonomy for the knowledge-base tree.

Ten root categories anchor the top level of the KB tree. Subtrees below
the roots are discovered automatically by clustering + linkage. Each seed
carries a short description used as the root node's curated summary.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategorySeed:
    """A root category in the KB tree."""

    slug: str
    title: str
    summary: str


CATEGORY_SEEDS: tuple[CategorySeed, ...] = (
    CategorySeed(
        slug="architecture",
        title="Architecture",
        summary=(
            "System and software architecture: patterns, decisions, "
            "boundaries, layering, modularity, and trade-offs."
        ),
    ),
    CategorySeed(
        slug="testing",
        title="Testing",
        summary=(
            "Testing strategies, tooling, fixtures, mocks, coverage, "
            "and patterns for trustworthy automated checks."
        ),
    ),
    CategorySeed(
        slug="debugging",
        title="Debugging",
        summary=(
            "Debugging techniques, instrumentation, log analysis, "
            "tracing, profiling, and root-cause workflows."
        ),
    ),
    CategorySeed(
        slug="devops",
        title="DevOps",
        summary=(
            "Build, deploy, CI/CD, release engineering, infrastructure "
            "as code, and runtime operations."
        ),
    ),
    CategorySeed(
        slug="performance",
        title="Performance",
        summary=(
            "Performance optimisation, profiling, caching, concurrency, "
            "and resource tuning."
        ),
    ),
    CategorySeed(
        slug="cybersecurity",
        title="Cybersecurity",
        summary=(
            "Cybersecurity patterns, threat modelling, authn/authz, "
            "secret handling, input validation, attack/defence techniques, "
            "and hardening."
        ),
    ),
    CategorySeed(
        slug="tooling",
        title="Tooling",
        summary=(
            "Developer tools, editors, CLIs, IDEs, language servers, "
            "and productivity aids."
        ),
    ),
    CategorySeed(
        slug="workflow",
        title="Workflow",
        summary=(
            "Process patterns: code review, branching, task management, "
            "planning, retrospectives, and collaboration."
        ),
    ),
    CategorySeed(
        slug="integrations",
        title="Integrations",
        summary=(
            "Third-party APIs, webhooks, SDKs, data formats, and "
            "cross-system glue."
        ),
    ),
    CategorySeed(
        slug="ai-engineering",
        title="AI Engineering",
        summary=(
            "Patterns for working with LLMs, embeddings, RAG, agent "
            "orchestration, prompt design, and evaluation."
        ),
    ),
)


_CATEGORY_HINT_TO_SLUG: dict[str, str] = {
    "architecture": "architecture",
    "testing": "testing",
    "debugging": "debugging",
    "devops": "devops",
    "performance": "performance",
    "security": "cybersecurity",
    "cybersecurity": "cybersecurity",
    "tooling": "tooling",
    "workflow": "workflow",
    "integrations": "integrations",
    "ai_engineering": "ai-engineering",
    "ai-engineering": "ai-engineering",
}


def resolve_seed_slug(category_hint: str | None) -> str:
    """Map an LLM-extracted category hint to a known seed slug.

    Unknown / empty hints fall back to ``ai-engineering`` (the most general
    bucket) so an atom never gets dropped on the floor.

    Args:
        category_hint: Lower-case hint emitted by the extraction prompt.

    Returns:
        Slug of the matching ``CategorySeed``, or ``"ai-engineering"`` when
        the hint is unknown.
    """
    if not category_hint:
        return "ai-engineering"
    return _CATEGORY_HINT_TO_SLUG.get(category_hint.strip().lower(), "ai-engineering")