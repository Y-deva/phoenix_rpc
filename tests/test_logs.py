"""Application log helpers."""

from phoenix_gui.core.logs import clean_output


def test_clean_output_strips_ansi_sequences() -> None:
    """Terminal color codes must never leak into the log viewer."""
    assert clean_output("\x1b[31merror\x1b[0m") == ["error"]
    assert clean_output("plain\n") == ["plain"]


def test_logs_page_filters_and_renders(window, qtbot, monkeypatch) -> None:
    """The viewer should show the log tail and respect the level filter."""
    import phoenix_gui.ui.pages.logs as logs_page

    text = (
        "2026-10-31 10:00:00 INFO phoenix: started\n"
        "2026-10-31 10:00:01 ERROR phoenix: failed\n"
    )
    monkeypatch.setattr(logs_page, "read_log", lambda: text)
    window.navigate("logs")
    qtbot.waitUntil(lambda: "logs" in window._pages, timeout=2000)
    page = window._pages["logs"]
    page.refresh()
    assert "ERROR" in page.view.toPlainText()
    page.level.setCurrentIndex(1)
    assert "ERROR" in page.view.toPlainText()
    assert "started" not in page.view.toPlainText()


def test_clear_and_export_log(tmp_path, monkeypatch) -> None:
    """Clearing removes contents and exporting combines rotated files."""
    from phoenix_gui.core import logs

    monkeypatch.setattr(logs, "log_directory", lambda: tmp_path)
    (tmp_path / "phoenix-wallet.log").write_text("latest\n", encoding="utf-8")
    (tmp_path / "phoenix-wallet.log.1").write_text("older\n", encoding="utf-8")
    destination = logs.export_log(tmp_path / "bundle")
    assert destination.suffix == ".log"
    assert "latest" in destination.read_text(encoding="utf-8")
    logs.clear_log()
    assert (tmp_path / "phoenix-wallet.log").read_text(encoding="utf-8") == ""
    assert (tmp_path / "phoenix-wallet.log.1").read_text(encoding="utf-8") == ""
