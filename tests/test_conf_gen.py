"""Tests for first-run configuration generation."""

from __future__ import annotations

import tomllib
from pathlib import Path

import conf_gen


def test_generated_config_contains_matching_proxy_credentials(tmp_path: Path) -> None:
    """A generated config must authenticate the GUI without extra edits."""
    target = tmp_path / "config.toml"
    conf_gen._write_config_toml("alice", "secret", 8344, False, str(target))
    config = tomllib.loads(target.read_text(encoding="utf-8"))
    assert config["daemon"]["user"] == "alice"
    assert config["proxy"]["user"] == "alice"
    assert config["proxy"]["password"] == "secret"
    assert config["proxy"]["port"] == 16666
