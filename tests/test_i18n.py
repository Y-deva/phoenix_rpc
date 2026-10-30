"""Translation catalog and language switching tests."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt

from phoenix_gui.i18n import BUNDLED_TRANSLATIONS, SOURCE_LANGUAGE, TranslationManager
from phoenix_gui.settings import Settings


def test_bundled_catalogs_cover_required_languages(qapp, tmp_path: Path) -> None:
    manager = TranslationManager(Settings(tmp_path / "s.ini"), qapp)
    codes = {language.code for language in manager.available_languages()}
    assert {"ru", "en", "de", "fr", "it", "uk"} <= codes
    assert not manager.errors
    assert manager.language == SOURCE_LANGUAGE


def test_catalog_lookup_and_english_fallback(qapp, tmp_path: Path) -> None:
    manager = TranslationManager(Settings(tmp_path / "s.ini"), qapp)
    assert manager.set_language("de")
    assert manager.tr("Поведение") == "Verhalten"
    assert manager.tr("Показано 3 из 5 операций.") == "3 von 5 Transaktionen angezeigt."
    # A key absent from German still resolves through the English catalog.
    assert manager.tr("Очистить") == "Clear"
    assert manager.tr("Неизвестная строка") == "Неизвестная строка"


def test_custom_directory_and_invalid_catalog(qapp, tmp_path: Path) -> None:
    directory = tmp_path / "locales"
    directory.mkdir()
    (directory / "es.json").write_text(
        json.dumps(
            {
                "code": "es",
                "name": "Spanish",
                "native_name": "Español",
                "strings": {"Настройки": "Ajustes"},
                "patterns": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    manager = TranslationManager(
        Settings(tmp_path / "s.ini"), qapp, directory=directory
    )
    assert manager.errors
    assert manager.set_language("es")
    assert manager.tr("Настройки") == "Ajustes"
    assert manager.tr("Сумма") == "Amount"
    assert any(language.code == "es" for language in manager.available_languages())


def test_switch_persists_and_changes_window(window, qtbot) -> None:
    window.translations.set_language("en")
    qtbot.wait(100)
    assert window.translations.language == "en"
    assert window.settings.get("appearance/language") == "en"
    assert window.windowTitle() == "Novacoin - Demo network"
    window.navigate("transactions")
    Q = Qt.Orientation.Horizontal
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    assert window.title_label.text() == "History"
    headers = [
        page.table.model().headerData(index, Q, Qt.ItemDataRole.DisplayRole)
        for index in range(3)
    ]
    assert headers[:2] == ["Date", "Type"]
    assert page.table.item(0, 1).text() in {"Received", "Sent", "Block reward"}

    window.translations.set_language("ru")
    qtbot.wait(100)
    window.navigate("overview")
    assert window.windowTitle() == "Novacoin - Демо-сеть"
    assert window.title_label.text() == "Обзор"


def test_settings_language_row_lists_catalogs(window) -> None:
    page = window._pages["settings"]
    assert page.language_combo.count() >= 6
    assert page.language_combo.findData("de") >= 0
    assert page.translations_path.path().endswith("translations")
    assert page.translations_status.text()


def test_settings_custom_directory_reload(window, tmp_path: Path) -> None:
    page = window._pages["settings"]
    custom = tmp_path / "custom-locales"
    custom.mkdir()
    (custom / "es.json").write_text(
        json.dumps(
            {
                "code": "es",
                "name": "Spanish",
                "native_name": "Español",
                "strings": {"Обзор": "Resumen"},
                "patterns": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    page.translations_path.set_path(str(custom))
    page._apply_translations_directory()
    assert window.translations.directory == custom
    assert page.language_combo.findData("es") >= 0
    assert "7" in page.translations_status.text()
    page.translations_path.set_path(str(BUNDLED_TRANSLATIONS))
    page._apply_translations_directory()
