"""Shared fixtures for the Phoenix Wallet test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from phoenix_gui.core.config import ProjectConfig, load_project_config  # noqa: E402
from phoenix_gui.demo import DemoService  # noqa: E402
from phoenix_gui.settings import Settings  # noqa: E402
from phoenix_gui.ui.main_window import MainWindow  # noqa: E402
from phoenix_gui.ui.widgets.theme import ThemeManager  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Isolated settings file for each test."""
    store = Settings(tmp_path / "settings.ini")
    store.set("appearance/animations", False)
    store.set("behavior/refresh_seconds", 3600)
    return store


@pytest.fixture()
def project() -> ProjectConfig:
    """Project defaults without requiring a real config.toml."""
    return load_project_config(Path.cwd())


@pytest.fixture()
def demo() -> DemoService:
    """Fresh deterministic demo backend."""
    return DemoService()


@pytest.fixture()
def window(qtbot, qapp, settings: Settings, project: ProjectConfig, demo: DemoService):
    """Main window wired to the demo service."""
    themes = ThemeManager(settings, qapp)
    themes.apply("phoenix")
    widget = MainWindow(project, settings, demo, themes, demo=True)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.wait(500)
    yield widget
    widget._save_geometry()
    widget.close()
