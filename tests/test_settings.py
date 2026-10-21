"""Settings defaults, clamping and persistence."""

from pathlib import Path

from phoenix_gui.settings import Settings


def test_defaults_are_available(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    assert store.theme == "phoenix"
    assert store.verbosity == 1
    assert store.refresh_seconds == 20
    assert store.confirm_send is True
    assert store.media_enabled is False


def test_set_get_and_typed_bool(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.set("appearance/animations", "false")
    assert store.animations is False
    store.set("appearance/animations", True)
    assert store.animations is True


def test_values_are_clamped(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.set("appearance/font_scale", 500)
    assert store.font_scale == 140
    store.set("appearance/font_scale", 1)
    assert store.font_scale == 80
    store.set("behavior/refresh_seconds", 1)
    assert store.refresh_seconds == 5
    store.set("behavior/refresh_seconds", 9999)
    assert store.refresh_seconds == 600


def test_changed_signal_only_for_real_changes(tmp_path: Path, qtbot):
    store = Settings(tmp_path / "settings.ini")
    events = []
    store.changed.connect(lambda key, value: events.append((key, value)))
    store.set("appearance/theme", "aurora")
    store.set("appearance/theme", "aurora")
    assert events == [("appearance/theme", "aurora")]


def test_bootstrap_preserves_explicit_values(tmp_path: Path, project):
    store = Settings(tmp_path / "settings.ini")
    store.set("connection/proxy_url", "http://127.0.0.1:9999")
    store.bootstrap(project)
    assert store.effective_proxy()[0] == "http://127.0.0.1:9999"
    store.bootstrap(project, force=True)
    assert store.effective_proxy()[0] == project.proxy_url


def test_recent_recipients_are_deduplicated(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.add_recent_recipient("2NOne")
    store.add_recent_recipient("2NTwo")
    store.add_recent_recipient("2NOne")
    assert store.recent_recipients() == ["2NOne", "2NTwo"]


def test_console_history_is_capped(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.set_console_history([str(index) for index in range(150)])
    assert len(store.console_history()) == 100
    assert store.console_history()[-1] == "149"


def test_console_history_survives_invalid_json(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.set("console/history", "not json")
    assert store.console_history() == []


def test_reset_restores_defaults(tmp_path: Path):
    store = Settings(tmp_path / "settings.ini")
    store.set("appearance/theme", "daylight")
    store.sync()
    store.reset()
    assert store.theme == "phoenix"
