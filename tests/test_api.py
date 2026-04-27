from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from project_wall.app import create_app
from tests.conftest import wait_for_port, wait_for_port_free


@pytest.fixture
def client(
    dummy_config: Path, log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("WALL_CONFIG", str(dummy_config))
    monkeypatch.setenv("WALL_LOGS", str(log_dir))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_list_projects(client: TestClient) -> None:
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    ids = [p["id"] for p in data["projects"]]
    assert "dummy" in ids
    entry = next(p for p in data["projects"] if p["id"] == "dummy")
    assert entry["state"]["running"] is False
    assert entry["local_url"].startswith("http://127.0.0.1:")


def test_get_project(client: TestClient) -> None:
    resp = client.get("/api/projects/dummy")
    assert resp.status_code == 200
    assert resp.json()["id"] == "dummy"


def test_get_unknown_project_returns_404(client: TestClient) -> None:
    resp = client.get("/api/projects/ghost")
    assert resp.status_code == 404


def test_start_stop_lifecycle(client: TestClient, dummy_port: int) -> None:
    start = client.post("/api/projects/dummy/start")
    assert start.status_code == 200, start.text
    state = start.json()
    assert state["running"] is True
    assert state["pid"] is not None

    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)

    status = client.get("/api/projects/dummy").json()
    assert status["state"]["running"] is True

    stop = client.post("/api/projects/dummy/stop")
    assert stop.status_code == 200
    stopped = stop.json()
    assert stopped["running"] is False
    assert stopped["exit_code"] is not None

    assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=8.0)


def test_start_unknown_project_404(client: TestClient) -> None:
    assert client.post("/api/projects/ghost/start").status_code == 404
    assert client.post("/api/projects/ghost/stop").status_code == 404


def test_logs_endpoint(client: TestClient) -> None:
    client.post("/api/projects/dummy/start")
    time.sleep(0.4)
    client.post("/api/projects/dummy/stop")
    resp = client.get("/api/projects/dummy/logs?n=50")
    assert resp.status_code == 200
    lines = resp.json()["lines"]
    assert any("[wall]" in line for line in lines)


def test_logs_unknown_project_404(client: TestClient) -> None:
    assert client.get("/api/projects/ghost/logs").status_code == 404


def test_health_probe_over_http(client: TestClient, dummy_port: int) -> None:
    client.post("/api/projects/dummy/start")
    try:
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert "dummy" in results
        assert results["dummy"]["ok"] is True
        assert results["dummy"]["status"] == 200
    finally:
        client.post("/api/projects/dummy/stop")


def test_index_renders(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ProjectWall" in resp.text
    assert "Dummy Server" in resp.text
