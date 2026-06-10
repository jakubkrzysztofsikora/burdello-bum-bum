"""Tests for backend.pipeline.repo_resolver."""

from __future__ import annotations

import pytest

from backend.pipeline import repo_resolver as rr
from backend.pipeline.repo_resolver import RepoIdentity, resolve_from_path


@pytest.fixture(autouse=True)
def _reset_counters():
    rr.reset_counters()
    yield
    rr.reset_counters()


# ---------------------------------------------------------------------------
# Claude Code — root transcripts
# ---------------------------------------------------------------------------

class TestClaudeRoot:
    def test_personal_repo(self):
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-reasoning-core/7235c58e.jsonl"
        identity = resolve_from_path(p)
        assert identity == RepoIdentity(
            slug="reasoning-core",
            humanized="Reasoning Core",
            owner="personal",
            provider="claude",
            collapsed_from=None,
        )
        assert rr.counters()["resolver_hit"] == 1

    def test_circit_repo(self):
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-circit-app/abc.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-app"
        assert identity.humanized == "Circit App"
        assert identity.owner == "circit"


# ---------------------------------------------------------------------------
# Claude Code — subagent transcripts (BLOCKER-1 from review)
# ---------------------------------------------------------------------------

class TestClaudeSubagents:
    def test_subagent_path_resolves_to_same_repo(self):
        root = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-reasoning-core/32cc534e.jsonl"
        sub = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-reasoning-core/32cc534e/subagents/agent-a499c0f65849f37df.jsonl"
        assert resolve_from_path(root).slug == resolve_from_path(sub).slug == "reasoning-core"

    def test_nested_workflow_subagent(self):
        # …/subagents/workflows/wf_<id>/agent-*.jsonl
        p = (
            "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-reasoning-core/"
            "32cc534e/subagents/workflows/wf_fea883d3-4eb/agent-aabbcc.jsonl"
        )
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "reasoning-core"


# ---------------------------------------------------------------------------
# Claude-shell (~-launched, no Repos segment) — BLOCKER-2 from review
# ---------------------------------------------------------------------------

class TestClaudeShell:
    def test_bare_home_launch(self):
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora/071bf936-474d-497e-9cbd-e3a302c47cc9.jsonl"
        identity = resolve_from_path(p)
        assert identity == RepoIdentity(
            slug="claude-shell-sessions",
            humanized="Claude Shell Sessions",
            owner=None,
            provider="claude-shell",
            collapsed_from=None,
        )

    def test_bare_home_subagent(self):
        p = (
            "/home/bbuser/.claude/projects/-Users-jakubsikora/"
            "0ccc9d6f-ba7f-4665-bb41-8fdff1c78c80/subagents/agent-a69b2f1c2772c5079.jsonl"
        )
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "claude-shell-sessions"


# ---------------------------------------------------------------------------
# Collapse rules
# ---------------------------------------------------------------------------

class TestCircitAppEvalsCollapse:
    @pytest.mark.parametrize(
        "variant",
        [
            "circit-app-evals-a-t1", "circit-app-evals-a-t2", "circit-app-evals-a-t5",
            "circit-app-evals-a-t6", "circit-app-evals-a-t7", "circit-app-evals-a-t8",
            "circit-app-evals-a-t9", "circit-app-evals-a-p0", "circit-app-evals-a-e1",
            "circit-app-evals-b-t1", "circit-app-evals-b-t2", "circit-app-evals-b-t5",
            "circit-app-evals-b-t6", "circit-app-evals-b-t7", "circit-app-evals-b-t8",
            "circit-app-evals-b-t9", "circit-app-evals-b-p0", "circit-app-evals-b-e1",
        ],
    )
    def test_all_eval_variants_collapse(self, variant: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-{variant}/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-app-evals"
        assert identity.collapsed_from is not None


class TestCircitAppPrCollapse:
    @pytest.mark.parametrize(
        "variant",
        [
            "circit-app-pr-10851",
            "circit-app-waf-33115",
            "circit-app-bugfix-qa-db-restore-name-mismatch",
            "circit-app-telemetry",
            "circit-app-ephemeral-pr-envs",
            "circit-app-scaleway-dr",
            "circit-app-support-copilot",
            "circit-app-pr-envs-quotas",
            "circit-app-pipeline-silent-failures",
            "circit-app-test-reasoningcore-p0",
            "circit-app-test-regular-claude-p0",
            "circit-app-windows-psr",
            "circit-app-4eyes",
        ],
    )
    def test_pr_branch_variants_collapse(self, variant: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-{variant}/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-app"

    def test_legit_subproject_not_collapsed(self):
        # Real distinct repo that just happens to share the prefix.
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-circit-app-casl-poc/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-app-casl-poc"
        assert identity.collapsed_from is None


class TestEnvStageCollapse:
    @pytest.mark.parametrize(
        "variant",
        [
            "circit-prod", "circit-production", "circit-prod-failover",
            "circit-stage", "circit-qa", "circit-nonprod",
            "circit-pr-infrastructure", "circit-pr-preview-infra",
            "circit-production-apim",
        ],
    )
    def test_env_variants_collapse_to_infrastructure(self, variant: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-{variant}/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-infrastructure"
        assert identity.humanized == "Circit Infrastructure"

    def test_global_infrastructure_not_collapsed(self):
        # Distinct project, should stay.
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-circit-global-infrastructure/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circit-global-infrastructure"


class TestCircitronCollapse:
    @pytest.mark.parametrize(
        "variant",
        ["circitron-mcp", "circitron-mcp-app", "circitron-mcp-preflight",
         "circitron-police", "circitron-slack-bot",
         "circitron-deploy-spike", "circitron-infrastructure",
         "circitron-app"],
    )
    def test_circitron_variants_collapse(self, variant: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-{variant}/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "circitron"


# ---------------------------------------------------------------------------
# Drop-lists
# ---------------------------------------------------------------------------

class TestInfraIgnore:
    @pytest.mark.parametrize(
        "name",
        ["apim-circit-non-prod", "appi-circit-prod", "kv-circitron-mcp",
         "rg-circit-ado-asana-sync", "dev-mssql-circitprod", "afdp-circit-prod",
         "stcircitdata", "synw-circit-data", "cdr-circit-sandbox"],
    )
    def test_infra_resource_returns_none(self, name: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-circit-{name}/x.jsonl"
        assert resolve_from_path(p) is None
        assert rr.counters()["ignored_infra"] >= 1


class TestLibraryBlocklist:
    @pytest.mark.parametrize(
        "lib",
        ["cypress", "fastapi", "huggingface-hub", "transformers", "tailscale",
         "arize", "braintrust", "langsmith", "openai-evals"],
    )
    def test_library_returns_none(self, lib: str):
        p = f"/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-{lib}/x.jsonl"
        assert resolve_from_path(p) is None
        assert rr.counters()["blocklisted"] >= 1


# ---------------------------------------------------------------------------
# Non-Claude providers (BLOCKER-5 from review)
# ---------------------------------------------------------------------------

class TestNonClaudeProviders:
    def test_gemini_antigravity(self):
        p = (
            "/home/bbuser/.gemini/antigravity-cli/brain/"
            "02dfdf6e-58ab-4e92-9ef3-2b639c21f0c6/.system_generated/logs/transcript_full.jsonl"
        )
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "unsorted-gemini"
        assert identity.humanized == "Unsorted (Gemini)"
        assert identity.provider == "gemini"

    def test_kimi_session(self):
        p = "/home/bbuser/.kimi/sessions/f2d393c3842564d7cda46b57a0b98606/9d5e3151/wire.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "unsorted-kimi"
        assert identity.provider == "kimi"

    def test_kimi_subagent(self):
        p = (
            "/home/bbuser/.kimi/sessions/00260a46afd26e30e6f732c10ac2fe6f/"
            "107c9a50-ecdf/subagents/a1f6e9825/wire.jsonl"
        )
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "unsorted-kimi"

    def test_codex_rollout(self):
        p = "/home/bbuser/.codex/sessions/2026/03/03/rollout-2026-03-03T13-49-37-019cb3bf.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "unsorted-codex"
        assert identity.provider == "codex"


# ---------------------------------------------------------------------------
# Unknown / miss
# ---------------------------------------------------------------------------

class TestMiss:
    def test_unknown_path_returns_none_and_increments_miss(self):
        p = "/some/unknown/path/transcript.jsonl"
        assert resolve_from_path(p) is None
        assert rr.counters()["resolver_miss"] == 1


# ---------------------------------------------------------------------------
# Humanisation (acronyms / overrides)
# ---------------------------------------------------------------------------

class TestHumanize:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [
            ("reasoning-core", "Reasoning Core"),
            ("circit-app-evals", "Circit App Evals"),
            ("circitron-mcp", "Circitron MCP"),       # acronym
            ("slack-mcp-internal", "Slack MCP Internal"),  # mixed
            ("ai-orchestrator", "AI Orchestrator"),
            ("burdello-bum-bum", "Burdello Bum Bum"),
        ],
    )
    def test_humanization(self, slug: str, expected: str):
        from backend.pipeline.repo_resolver import _humanize

        assert _humanize(slug) == expected


# ---------------------------------------------------------------------------
# Counters / unmatched
# ---------------------------------------------------------------------------

class TestCounters:
    def test_unmatched_slug_tracked(self):
        p = "/home/bbuser/.claude/projects/-Users-jakubsikora-Repos-personal-some-brand-new-thing/x.jsonl"
        identity = resolve_from_path(p)
        assert identity is not None
        assert identity.slug == "some-brand-new-thing"
        unmatched = dict(rr.unmatched_slugs(10))
        assert unmatched.get("some-brand-new-thing") == 1
