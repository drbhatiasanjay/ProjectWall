from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from project_wall.config import Project, WallConfig, load_config


def test_load_config_roundtrip(dummy_config: Path, dummy_port: int) -> None:
    cfg = load_config(dummy_config)
    assert isinstance(cfg, WallConfig)
    assert cfg.version == 1
    assert cfg.defaults.health_timeout_s == 5
    assert len(cfg.projects) == 1
    p = cfg.projects[0]
    assert p.id == "dummy"
    assert p.port == dummy_port


def test_port_substitution_in_command(loaded_config: WallConfig, dummy_port: int) -> None:
    p = loaded_config.projects[0]
    rendered = p.rendered_command()
    assert str(dummy_port) in rendered
    assert "{port}" not in " ".join(rendered)


def test_port_substitution_in_health(loaded_config: WallConfig, dummy_port: int) -> None:
    p = loaded_config.projects[0]
    assert p.rendered_health() == f"http://127.0.0.1:{dummy_port}/"


def test_get_by_id(loaded_config: WallConfig) -> None:
    assert loaded_config.get("dummy") is not None
    assert loaded_config.get("does-not-exist") is None


def test_project_without_port_skips_substitution() -> None:
    p = Project(
        id="x",
        name="X",
        path=".",
        stack="bash",
        command=["echo", "hello"],
        health="http://example.com/health",
    )
    assert p.rendered_command() == ["echo", "hello"]
    assert p.rendered_health() == "http://example.com/health"


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yml")


def test_load_config_invalid_schema(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.safe_dump({"version": 1, "projects": "not-a-list"}))
    with pytest.raises(Exception):
        load_config(bad)
