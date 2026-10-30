"""Tests for the GUI-side proxy process controller."""

from __future__ import annotations

from pathlib import Path

from phoenix_gui.core.config import ProjectConfig
from phoenix_gui.core.proxy import ProxyProcess, backend_python, proxy_arguments
from phoenix_gui.settings import Settings


def test_proxy_arguments_and_missing_backend(tmp_path: Path) -> None:
    """The proxy command stays local and reports a missing backend venv."""
    project = ProjectConfig(root=tmp_path)
    assert proxy_arguments(project) == ["main.py"]
    assert backend_python(project) is None


def test_effective_proxy_falls_back_to_project(tmp_path: Path) -> None:
    """Empty GUI fields use the project config credentials."""
    project = ProjectConfig(
        root=tmp_path,
        proxy_url="http://127.0.0.1:9",
        proxy_user="alice",
        proxy_password="secret",
    )
    settings = Settings(tmp_path / "settings.ini")
    settings.bootstrap(project)
    settings.set("connection/proxy_url", "")
    settings.set("connection/proxy_user", "")
    settings.set("connection/proxy_password", "")

    url, user, password = settings.effective_proxy()

    assert url == "http://127.0.0.1:9"
    assert (user, password) == ("alice", "secret")


def test_proxy_starts_in_stopped_state(tmp_path: Path, qapp) -> None:
    """A fresh controller owns no process and reports the stopped state."""
    project = ProjectConfig(root=tmp_path, proxy_url="http://127.0.0.1:9")
    settings = Settings(tmp_path / "settings.ini")
    settings.bootstrap(project)

    controller = ProxyProcess(settings, project, qapp)

    assert controller.state == "stopped"
    assert controller.owned is False
    assert controller.port_open() is False
    controller.stop()
