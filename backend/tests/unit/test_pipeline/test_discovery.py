"""Tests for source file discovery.

Covers file discovery from provider directories, hash computation,
provider pattern matching, and directory resolution.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.discovery import DEFAULT_PROVIDER_PATTERNS, SourceDiscovery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_provider_dir(tmp_path: Path):
    """Create a temporary directory structure mimicking provider files."""
    # Create structure: .claude/projects/proj1/transcript.jsonl
    claude_dir = tmp_path / ".claude" / "projects" / "proj1"
    claude_dir.mkdir(parents=True)
    (claude_dir / "transcript.jsonl").write_text(
        '{"role": "user", "content": "Hello"}\n'
        '{"role": "assistant", "content": "Hi!"}\n'
    )

    # Create structure: .aider.chat.history.md
    aider_file = tmp_path / ".aider.chat.history.md"
    aider_file.write_text("# Aider Chat History\n\n## User\nFix the bug\n")

    # Create structure: .codex/sessions/2024-01/sess.jsonl
    codex_dir = tmp_path / ".codex" / "sessions" / "2024-01"
    codex_dir.mkdir(parents=True)
    (codex_dir / "sess.jsonl").write_text(
        '{"speaker": "user", "text": "Hello"}\n'
    )

    return tmp_path


# ---------------------------------------------------------------------------
# SourceDiscovery.__init__
# ---------------------------------------------------------------------------


class TestDiscoveryInit:
    """Test SourceDiscovery initialisation."""

    def test_default_initialization(self):
        """Should initialise with default patterns and no overrides."""
        discovery = SourceDiscovery()

        assert discovery.base_dirs == {}
        assert discovery.patterns == DEFAULT_PROVIDER_PATTERNS

    def test_with_base_dirs_override(self):
        """Should accept base directory overrides."""
        overrides = {"claude_code": "/custom/claude/path"}
        discovery = SourceDiscovery(base_dirs=overrides)

        assert discovery.base_dirs == overrides


# ---------------------------------------------------------------------------
# SourceDiscovery.discover
# ---------------------------------------------------------------------------


class TestDiscover:
    """Test file discovery."""

    def test_discovers_claude_files(self, temp_provider_dir: Path):
        """Should discover Claude Code transcript files."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        claude_results = [r for r in results if r["provider"] == "claude_code"]
        assert len(claude_results) == 1
        assert claude_results[0]["path"].endswith("transcript.jsonl")

    def test_discovers_aider_files(self, temp_provider_dir: Path):
        """Should discover Aider chat history files."""
        discovery = SourceDiscovery(
            base_dirs={"aider": str(temp_provider_dir)}
        )
        results = discovery.discover()

        aider_results = [r for r in results if r["provider"] == "aider"]
        assert len(aider_results) == 1
        assert aider_results[0]["path"].endswith(".aider.chat.history.md")

    def test_discovers_codex_files(self, temp_provider_dir: Path):
        """Should discover Codex session files."""
        discovery = SourceDiscovery(
            base_dirs={"codex": str(temp_provider_dir)}
        )
        results = discovery.discover()

        codex_results = [r for r in results if r["provider"] == "codex"]
        assert len(codex_results) == 1
        assert codex_results[0]["path"].endswith("sess.jsonl")

    def test_result_has_required_fields(self, temp_provider_dir: Path):
        """Each result should have path, provider, size, hash fields."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        for result in results:
            assert "path" in result
            assert "provider" in result
            assert "size" in result
            assert "hash" in result
            assert isinstance(result["path"], str)
            assert isinstance(result["provider"], str)
            assert isinstance(result["size"], int)
            assert isinstance(result["hash"], str)

    def test_path_is_absolute(self, temp_provider_dir: Path):
        """Discovered paths should be absolute."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        for result in results:
            assert os.path.isabs(result["path"])

    def test_size_is_nonnegative(self, temp_provider_dir: Path):
        """Discovered file sizes should be non-negative."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        for result in results:
            assert result["size"] >= 0

    def test_hash_is_lowercase_hex(self, temp_provider_dir: Path):
        """File hashes should be lowercase hex strings."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        for result in results:
            assert len(result["hash"]) == 64  # SHA-256 hex length
            assert result["hash"] == result["hash"].lower()
            int(result["hash"], 16)  # Valid hex

    def test_empty_directory_returns_empty(self, tmp_path: Path):
        """Empty directory should produce no results."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(tmp_path)}
        )
        results = discovery.discover()

        claude_results = [r for r in results if r["provider"] == "claude_code"]
        assert claude_results == []

    def test_missing_base_dir_skips_provider(self, tmp_path: Path):
        """Non-existent base directory should skip that provider."""
        nonexistent = str(tmp_path / "does_not_exist")
        discovery = SourceDiscovery(
            base_dirs={"claude_code": nonexistent}
        )
        results = discovery.discover()

        claude_results = [r for r in results if r["provider"] == "claude_code"]
        assert claude_results == []

    def test_returns_list(self, temp_provider_dir: Path):
        """discover() should always return a list."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        assert isinstance(results, list)

    def test_discover_all_providers(self, temp_provider_dir: Path):
        """Should discover files from all configured providers."""
        # Use the same temp dir for all providers
        base_dirs = {
            provider: str(temp_provider_dir)
            for provider in ["claude_code", "aider", "codex"]
        }
        discovery = SourceDiscovery(base_dirs=base_dirs)
        results = discovery.discover()

        providers_found = {r["provider"] for r in results}
        assert "claude_code" in providers_found
        assert "aider" in providers_found
        assert "codex" in providers_found

    def test_does_not_discover_directories(self, temp_provider_dir: Path):
        """Should not return directories as results."""
        discovery = SourceDiscovery(
            base_dirs={"claude_code": str(temp_provider_dir)}
        )
        results = discovery.discover()

        for result in results:
            assert Path(result["path"]).is_file()


# ---------------------------------------------------------------------------
# SourceDiscovery.compute_hash
# ---------------------------------------------------------------------------


class TestComputeHash:
    """Test hash computation."""

    def test_hash_is_sha256(self, tmp_path: Path):
        """Hash should be SHA-256 of file contents."""
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        discovery = SourceDiscovery()
        hash_result = discovery.compute_hash(test_file)

        expected = hashlib.sha256(content).hexdigest().lower()
        assert hash_result == expected

    def test_hash_changes_with_content(self, tmp_path: Path):
        """Different content should produce different hashes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content A")
        file2.write_text("Content B")

        discovery = SourceDiscovery()
        hash1 = discovery.compute_hash(file1)
        hash2 = discovery.compute_hash(file2)

        assert hash1 != hash2

    def test_hash_same_for_same_content(self, tmp_path: Path):
        """Same content should produce identical hashes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Same content")
        file2.write_text("Same content")

        discovery = SourceDiscovery()
        hash1 = discovery.compute_hash(file1)
        hash2 = discovery.compute_hash(file2)

        assert hash1 == hash2

    def test_empty_file_hash(self, tmp_path: Path):
        """Empty file should have known SHA-256 hash."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        discovery = SourceDiscovery()
        hash_result = discovery.compute_hash(empty_file)

        expected = hashlib.sha256(b"").hexdigest().lower()
        assert hash_result == expected

    def test_large_file_hash(self, tmp_path: Path):
        """Should correctly hash files larger than chunk size."""
        large_file = tmp_path / "large.txt"
        content = b"x" * 100_000  # 100KB
        large_file.write_bytes(content)

        discovery = SourceDiscovery()
        hash_result = discovery.compute_hash(large_file)

        expected = hashlib.sha256(content).hexdigest().lower()
        assert hash_result == expected

    def test_hash_is_lowercase(self, tmp_path: Path):
        """Hash should be lowercase hex."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        discovery = SourceDiscovery()
        hash_result = discovery.compute_hash(test_file)

        assert hash_result == hash_result.lower()


# ---------------------------------------------------------------------------
# SourceDiscovery._resolve_base_dir
# ---------------------------------------------------------------------------


class TestResolveBaseDir:
    """Test base directory resolution."""

    def test_uses_override_when_provided(self):
        """Should use base_dirs override when available."""
        discovery = SourceDiscovery(base_dirs={"claude_code": "/custom/path"})
        result = discovery._resolve_base_dir("claude_code")

        assert result == "/custom/path"

    def test_falls_back_to_home(self):
        """Should fall back to HOME environment variable."""
        discovery = SourceDiscovery()

        with patch.dict(os.environ, {"HOME": "/home/testuser"}):
            result = discovery._resolve_base_dir("claude_code")

        assert result == "/home/testuser"

    def test_falls_back_to_userprofile(self):
        """Should fall back to USERPROFILE on Windows."""
        discovery = SourceDiscovery()

        env = {"HOME": "", "USERPROFILE": "C:\\Users\\TestUser"}
        with patch.dict(os.environ, env, clear=True):
            result = discovery._resolve_base_dir("claude_code")

        assert result == "C:\\Users\\TestUser"

    def test_returns_none_when_no_home(self):
        """Should return None when no home directory is found."""
        discovery = SourceDiscovery()

        with patch.dict(os.environ, {}, clear=True):
            result = discovery._resolve_base_dir("claude_code")

        assert result is None
