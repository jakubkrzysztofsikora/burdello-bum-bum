"""Deterministic transcript-path → canonical project identity resolver.

Replaces the LLM-based project extractor (which produced 1,134 noisy projects,
88% empty). The repo identity for every Claude-Code / Gemini / Kimi / Codex
transcript is fully derivable from the source file path. This module is pure
Python with no external deps so the same code can run in workers, tests, and
ad-hoc scripts.

Counters are process-local for cheap observability; the `/api/v1/stats/resolver`
endpoint exposes them but reports only the API process's own counters under
prefork — use `SELECT count(*) FROM projects GROUP BY name` for ground truth.

Workstream subdivision (e.g. ``Reasoning Core — Evaluation``) is intentionally
deferred; see thoughts/shared/plans/2026-06-10-project-classification-fix-mvp.md.
Revisit only after observing >300 tasks attached to a single repo.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider path matchers
# ---------------------------------------------------------------------------

# Claude Code stores transcripts under:
#   …/.claude/projects/-<encoded>/<uuid>.jsonl
#   …/.claude/projects/-<encoded>/<uuid>/subagents/agent-*.jsonl
#   …/.claude/projects/-<encoded>/<uuid>/subagents/workflows/wf_*/agent-*.jsonl
# The <encoded> segment is the absolute project directory with "/" → "-".
# We must NOT anchor on a single trailing /<file>.jsonl because subagents nest.
_CLAUDE_RE = re.compile(r"/\.claude/projects/-(?P<encoded>[^/]+)(?:/|$)")

_GEMINI_RE = re.compile(r"/\.gemini/antigravity-cli/")
_KIMI_RE = re.compile(r"/\.kimi/sessions/")
_CODEX_RE = re.compile(r"/\.codex/sessions/")


# ---------------------------------------------------------------------------
# Slug normalisation rules — allow-list, ordered.
# Each rule collapses a known variant family back to its canonical base slug.
# ---------------------------------------------------------------------------

_COLLAPSE_RULES: list[tuple[re.Pattern[str], str]] = [
    # circit-app-evals-{a,b}-{p0|t1..t9|e1} → circit-app-evals
    (re.compile(r"^(?P<base>circit-app-evals)-[ab](-[a-z]\d+)?$"), r"\g<base>"),
    # circit-app feature/PR/bugfix/perf variants → circit-app
    (
        re.compile(
            r"^(?P<base>circit-app)-("
            r"pr-\d+|waf-\d+|bugfix-.+|telemetry|ephemeral-pr-envs"
            r"|scaleway-dr|support-copilot|pr-envs-quotas|pipeline-silent-failures"
            r"|test-.+|windows-psr|4eyes|develop"
            r")$"
        ),
        r"\g<base>",
    ),
    # Worktree paths leak into the slug as a leading hidden dir:
    #   /Repos/circit/circit-app/.claude-worktrees/pr-11139-split-research
    # → circit-app--claude-worktrees-pr-11139-split-research
    # Collapse everything after the double-dash back to the parent repo.
    (re.compile(r"^(?P<base>[a-z0-9][a-z0-9-]*?)--claude-worktrees-.*$"), r"\g<base>"),
    # circit-{prod,production,stage,qa,nonprod}(-*)? → circit-infrastructure
    (
        re.compile(
            r"^circit-("
            r"prod|production|stage|qa|nonprod|prod-failover"
            r"|pr-infrastructure|pr-preview-infra|production-apim"
            r")(-.*)?$"
        ),
        "circit-infrastructure",
    ),
    # circitron-{mcp*, police, slack-bot, deploy-spike, infrastructure, app} → circitron
    (
        re.compile(
            r"^circitron-(mcp.*|police|slack-bot|deploy-spike|infrastructure|app)$"
        ),
        "circitron",
    ),
]


# ---------------------------------------------------------------------------
# Drop-lists
# ---------------------------------------------------------------------------

# Azure / infra resource naming — these are never user-facing projects.
_IGNORE_PREFIXES: tuple[str, ...] = (
    "apim-",
    "appi-",
    "kv-",
    "rg-",
    "dev-mssql-",
    "afdp-",
    "afd-",
    "dns-",
    "stcircit",
    "synw-",
    "cdr-",
)

# Library / tool names the previous LLM extractor kept calling "projects".
_LIBRARY_BLOCKLIST: frozenset[str] = frozenset({
    "cypress",
    "fastapi",
    "huggingface-hub",
    "transformers",
    "tailscale",
    "arize",
    "braintrust",
    "langsmith",
    "openai-evals",
    "asana-ado-sync",
    "api-documentation",
    "maximhq-bifrost",
    "ecosystem-routes",
    "ecosystem-dashboard",
    "operationplanner-nginx-waf",
    "openai",
    "anthropic",
    "litellm",
    "pytorch",
    "scikit-learn",
    "numpy",
    "pandas",
    # Generic transient directory names that are NOT project repos.
    "poc",
    "tmp",
    "scratch",
    "sandbox",
    "workspace",
    "personal",
    "claude-theme",
})


# ---------------------------------------------------------------------------
# Humanisation
# ---------------------------------------------------------------------------

# Explicit overrides for names that .capitalize() would mangle.
_HUMANIZED_OVERRIDES: dict[str, str] = {
    "circit-app": "Circit App",
    "circit-app-evals": "Circit App Evals",
    "circit-app-casl-poc": "Circit App CASL POC",
    "circit-infrastructure": "Circit Infrastructure",
    "circit-global-infrastructure": "Circit Global Infrastructure",
    "circitron": "Circitron",
    "circitron-mcp": "Circitron MCP",
    "reasoning-core": "Reasoning Core",
    "burdello-bum-bum": "Burdello Bum Bum",
    "jakub-health-hub": "Jakub Health Hub",
    "sikoras-chat": "Sikoras Chat",
    "ai-orchestrator": "AI Orchestrator",
    "ai-orchestrator-frontend": "AI Orchestrator Frontend",
    "circit-mcp-prod": "Circit MCP Prod",
    "slack-mcp-internal": "Slack MCP Internal",
    "claude-shell-sessions": "Claude Shell Sessions",
    "unsorted-gemini": "Unsorted (Gemini)",
    "unsorted-kimi": "Unsorted (Kimi)",
    "unsorted-codex": "Unsorted (Codex)",
    "sovereign-agent-setup": "Sovereign Agent Setup",
    "cyberlegion": "Cyberlegion",
    "choyce-engine": "Choyce Engine",
    "ai-control-room": "AI Control Room",
    "poc-slack-agent": "POC Slack Agent",
    "poc-slack-agent-slack-azure-ai-bot": "POC Slack Agent — Slack Azure AI Bot",
    "ai-gateway-poc-tmp": "AI Gateway POC (Tmp)",
    "circit-poc-slack-agent": "Circit POC Slack Agent",
    "status-service": "Status Service",
    "odysseus": "Odysseus",
    "circit-hive-mind": "Circit Hive Mind",
    "circit-app-develop": "Circit App",  # develop branch worktree
    "data-factory-circit-data": "Circit Data Factory",
}

_ACRONYMS: frozenset[str] = frozenset({
    "mcp", "api", "ai", "cli", "sdk", "ado", "qa", "ci", "cd",
    "url", "uri", "ui", "ux", "io", "rls", "etl", "waf", "kpi",
    "kv", "tcp", "http", "https", "sql", "jwt", "okr", "swe",
    "llm", "csv", "json", "yaml", "xml", "pdf", "aws", "gcp", "iam",
    "poc", "ob", "e2e", "dr", "wopi", "rnd", "psr",
})

# GitHub orgs / shared parent dirs that appear under `Repos/`. Encoded
# Claude paths cannot distinguish `/Repos/<org>/<repo>` from
# `/Repos/<org-repo>` (both encode to `-Repos-<org>-<repo>`). Treat
# `parts[idx+1]` as the owner only when it matches one of these known dirs;
# otherwise assume the entire tail is the single-segment repo slug.
_KNOWN_ORGS: frozenset[str] = frozenset({
    "personal",
    "circit",
    "kaw",
})


# ---------------------------------------------------------------------------
# Counters (process-local; surfaced via the stats endpoint)
# ---------------------------------------------------------------------------

_COUNTERS: Counter[str] = Counter()
_UNMATCHED_SLUGS: Counter[str] = Counter()


@dataclass(frozen=True)
class RepoIdentity:
    """Canonical project identity derived from a transcript source path."""

    slug: str
    humanized: str
    owner: str | None
    provider: str  # "claude" | "claude-shell" | "gemini" | "kimi" | "codex"
    collapsed_from: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_from_path(file_path: str) -> RepoIdentity | None:
    """Resolve a canonical repo identity from a transcript source path.

    Returns None only when the path matches a known provider but maps to a
    blocked / ignored slug, or when the path matches no provider at all.
    Non-Claude providers collapse into single `unsorted-*` buckets so their
    transcripts remain visible without polluting the project list.

    Args:
        file_path: Absolute path to the transcript file (POSIX form).

    Returns:
        A :class:`RepoIdentity`, or None if the path should not produce a
        project row.
    """
    if "/.claude/projects/" in file_path:
        return _claude_identity(file_path)
    if _GEMINI_RE.search(file_path):
        return _synthetic("unsorted-gemini", "gemini")
    if _KIMI_RE.search(file_path):
        return _synthetic("unsorted-kimi", "kimi")
    if _CODEX_RE.search(file_path):
        return _synthetic("unsorted-codex", "codex")

    _COUNTERS["resolver_miss"] += 1
    log.warning("repo_resolver: no provider match for %s", file_path)
    return None


def counters() -> dict[str, int]:
    """Return a snapshot of process-local counters."""
    return dict(_COUNTERS)


def unmatched_slugs(top_n: int = 50) -> list[tuple[str, int]]:
    """Return the most-seen slugs that did not match any collapse rule.

    Useful for curating ``_COLLAPSE_RULES`` over time without instrumenting
    a dashboard.
    """
    return _UNMATCHED_SLUGS.most_common(top_n)


def reset_counters() -> None:
    """Reset counters and unmatched-slug tracking.

    Intended for tests; production callers should not invoke this.
    """
    _COUNTERS.clear()
    _UNMATCHED_SLUGS.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _synthetic(slug: str, provider: str) -> RepoIdentity:
    _COUNTERS[f"synthetic_{provider}"] += 1
    return RepoIdentity(
        slug=slug,
        humanized=_humanize(slug),
        owner=None,
        provider=provider,
    )


def _claude_identity(file_path: str) -> RepoIdentity | None:
    m = _CLAUDE_RE.search(file_path)
    if not m:
        _COUNTERS["resolver_miss"] += 1
        log.warning("repo_resolver: claude path did not parse: %s", file_path)
        return None

    parts = m.group("encoded").split("-")

    # Bare `~`-launched Claude session: `-Users-jakubsikora` with no
    # `Repos` segment. These are real transcripts; bucket them so they remain
    # browseable without polluting the project list.
    if "Repos" not in parts:
        _COUNTERS["synthetic_claude_shell"] += 1
        return RepoIdentity(
            slug="claude-shell-sessions",
            humanized=_humanize("claude-shell-sessions"),
            owner=None,
            provider="claude-shell",
        )

    idx = parts.index("Repos")
    tail = parts[idx + 1:]
    if not tail:
        _COUNTERS["resolver_miss"] += 1
        return None
    # `-Repos-<org>-<repo…>` is ambiguous with `-Repos-<org>-<repo…>` where the
    # whole tail is one dashed repo name. Resolve via the _KNOWN_ORGS allow-list.
    if tail[0] in _KNOWN_ORGS and len(tail) > 1:
        owner = tail[0]
        repo_segments = tail[1:]
    else:
        owner = None
        repo_segments = tail

    # Claude preserves directory case in the encoding ("circit-app-evals-B-t1");
    # collapse rules and the blocklist are defined lower-case.
    slug_lc = "-".join(repo_segments).lower()

    if slug_lc in _LIBRARY_BLOCKLIST:
        _COUNTERS["blocklisted"] += 1
        return None
    if any(slug_lc.startswith(p) for p in _IGNORE_PREFIXES):
        _COUNTERS["ignored_infra"] += 1
        return None

    canonical, collapsed_from = _apply_collapse(slug_lc)
    if collapsed_from:
        _COUNTERS["collapsed"] += 1
    else:
        _UNMATCHED_SLUGS[canonical] += 1

    _COUNTERS["resolver_hit"] += 1
    return RepoIdentity(
        slug=canonical,
        humanized=_humanize(canonical),
        owner=owner,
        provider="claude",
        collapsed_from=collapsed_from,
    )


def _apply_collapse(slug: str) -> tuple[str, str | None]:
    for pattern, replacement in _COLLAPSE_RULES:
        if pattern.match(slug):
            new = pattern.sub(replacement, slug)
            if new != slug:
                return new, slug
    return slug, None


def _humanize(slug: str) -> str:
    if slug in _HUMANIZED_OVERRIDES:
        return _HUMANIZED_OVERRIDES[slug]
    return " ".join(
        (w.upper() if w in _ACRONYMS else w.capitalize())
        for w in slug.split("-")
    )
