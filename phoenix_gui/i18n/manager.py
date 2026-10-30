"""Runtime translation catalogs loaded from a directory of JSON files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableView,
    QTextEdit,
    QWidget,
)

from ..settings import Settings

SOURCE_LANGUAGE = "ru"
BUNDLED_TRANSLATIONS = Path(__file__).resolve().parent / "translations"
PATTERN_TARGET = re.compile(r"\{(\d+)\}")


@dataclass(frozen=True, slots=True)
class Language:
    """Metadata for one available translation catalog."""

    code: str
    native_name: str
    english_name: str

    @property
    def display_name(self) -> str:
        """Return the label shown in the language picker."""
        if self.native_name.casefold() == self.english_name.casefold():
            return self.native_name
        return f"{self.native_name} ({self.english_name})"


@dataclass(slots=True)
class Catalog:
    """One parsed translation catalog."""

    language: Language
    strings: dict[str, str] = field(default_factory=dict)
    patterns: list[tuple[re.Pattern[str], str]] = field(default_factory=list)


class TranslationManager(QObject):
    """Load, switch and apply translation catalogs at runtime."""

    languageChanged = pyqtSignal(str)
    catalogsChanged = pyqtSignal()

    def __init__(
        self,
        settings: Settings,
        parent: QObject | None = None,
        directory: Path | str | None = None,
    ) -> None:
        """Create the manager and load the configured catalog directory."""
        super().__init__(parent)
        self._settings = settings
        self._fixed_directory = Path(directory) if directory else None
        self._catalogs: dict[str, Catalog] = {}
        self._errors: list[str] = []
        self._language = SOURCE_LANGUAGE
        self.reload()
        self._app = QApplication.instance()
        if self._app is not None:
            self._app.installEventFilter(self)
        requested = str(settings.get("appearance/language", SOURCE_LANGUAGE))
        if requested in self._catalogs:
            self._language = requested

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Translate dialogs after they become visible."""
        if (
            event.type() == QEvent.Type.Show
            and self._language != SOURCE_LANGUAGE
            and isinstance(watched, QDialog)
        ):
            QTimer.singleShot(0, lambda widget=watched: self._translate_later(widget))
        return False

    def _translate_later(self, widget: QWidget) -> None:
        """Translate a widget unless Qt already destroyed it."""
        try:
            self.translate_tree(widget)
        except RuntimeError:
            return

    # ------------------------------------------------------------------
    # Catalog discovery
    # ------------------------------------------------------------------
    @property
    def directory(self) -> Path:
        """Return the directory currently used for catalogs."""
        if self._fixed_directory is not None:
            return self._fixed_directory
        configured = str(self._settings.get("appearance/translations_dir", "")).strip()
        return Path(configured).expanduser() if configured else BUNDLED_TRANSLATIONS

    @property
    def errors(self) -> tuple[str, ...]:
        """Return non-fatal problems found while loading catalogs."""
        return tuple(self._errors)

    @property
    def language(self) -> str:
        """Return the active language code."""
        return self._language

    @property
    def active_language(self) -> Language:
        """Return metadata for the active language."""
        return self._catalogs[self._language].language

    def available_languages(self) -> list[Language]:
        """Return catalogs sorted by their native names."""
        entries = [catalog.language for catalog in self._catalogs.values()]
        return sorted(entries, key=lambda item: item.native_name.casefold())

    def has_language(self, code: str) -> bool:
        """Return whether a catalog with the given code is loaded."""
        return code in self._catalogs

    def reload(self) -> None:
        """Reload every JSON catalog from the active directory."""
        previous = self._language
        directory = self.directory
        catalogs: dict[str, Catalog] = {}
        errors: list[str] = []
        # Bundled catalogs always stay available, while an external directory
        # can add new languages or override individual files.
        search_paths = [BUNDLED_TRANSLATIONS]
        if directory != BUNDLED_TRANSLATIONS:
            search_paths.append(directory)
        for search_path in search_paths:
            if not search_path.is_dir():
                errors.append(f"Каталог переводов не найден: {search_path}")
                continue
            for path in sorted(search_path.glob("*.json")):
                try:
                    catalog = self._read_catalog(path)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    errors.append(f"{path.name}: {exc}")
                    continue
                catalogs[catalog.language.code] = catalog
        catalogs.setdefault(
            SOURCE_LANGUAGE,
            Catalog(Language(SOURCE_LANGUAGE, "Русский", "Russian")),
        )
        self._catalogs = catalogs
        self._errors = errors
        if self._language not in catalogs:
            self._language = SOURCE_LANGUAGE
        self.catalogsChanged.emit()
        if self._language != previous:
            self.languageChanged.emit(self._language)

    def _read_catalog(self, path: Path) -> Catalog:
        """Parse and validate one JSON catalog."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("корень файла должен быть объектом")
        code = str(raw.get("code") or path.stem).strip().lower()
        if not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{2,8})?", code):
            raise ValueError(f"некорректный код языка: {code}")
        native = str(raw.get("native_name") or raw.get("name") or code).strip()
        english = str(raw.get("name") or native).strip()
        strings = raw.get("strings", {})
        if not isinstance(strings, dict):
            raise ValueError("поле strings должно быть объектом")
        patterns = raw.get("patterns", {})
        if not isinstance(patterns, dict):
            raise ValueError("поле patterns должно быть объектом")
        compiled: list[tuple[re.Pattern[str], str]] = []
        for source, target in patterns.items():
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            try:
                compiled.append((re.compile(source), target))
            except re.error as exc:
                raise ValueError(f"regex {source!r}: {exc}") from exc
        clean_strings = {
            str(source): str(target)
            for source, target in strings.items()
            if isinstance(source, str) and isinstance(target, str) and target
        }
        return Catalog(
            Language(code=code, native_name=native, english_name=english),
            strings=clean_strings,
            patterns=compiled,
        )

    def set_directory(self, directory: Path | str | None) -> tuple[bool, str]:
        """Switch the catalog directory and reload it without a restart."""
        if self._fixed_directory is not None:
            return False, "Каталог переводов задан при запуске"
        value = str(directory).strip() if directory else ""
        if value:
            path = Path(value).expanduser()
            if not path.is_dir():
                return False, f"Каталог не найден: {path}"
            self._settings.set("appearance/translations_dir", str(path))
        else:
            self._settings.set("appearance/translations_dir", "")
        self.reload()
        if self._language == SOURCE_LANGUAGE:
            self.languageChanged.emit(self._language)
        return True, ""

    def set_language(self, code: str) -> bool:
        """Activate a catalog by code and persist the choice."""
        if code not in self._catalogs:
            return False
        changed = code != self._language
        self._language = code
        self._settings.set("appearance/language", code)
        if changed:
            self.languageChanged.emit(code)
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def tr(self, text: str) -> str:
        """Translate one source string, falling back to English then source."""
        if not text or self._language == SOURCE_LANGUAGE:
            return text
        catalog = self._catalogs.get(self._language)
        if catalog is not None:
            exact = catalog.strings.get(text)
            if exact is not None:
                return exact
            patterned = self._apply_patterns(text, catalog)
            if patterned is not None:
                return patterned
        english = self._catalogs.get("en")
        if english is not None and english is not catalog:
            exact = english.strings.get(text)
            if exact is not None:
                return exact
            patterned = self._apply_patterns(text, english)
            if patterned is not None:
                return patterned
        return text

    @staticmethod
    def _apply_patterns(text: str, catalog: Catalog) -> str | None:
        """Apply the first matching regex rule in a catalog."""
        for pattern, target in catalog.patterns:
            match = pattern.fullmatch(text)
            if match is None:
                continue
            groups = match.groups()

            def replace(found: re.Match[str]) -> str:
                index = int(found.group(1))
                return groups[index] if index < len(groups) else ""

            return PATTERN_TARGET.sub(replace, target)
        return None

    # ------------------------------------------------------------------
    # Widget tree application
    # ------------------------------------------------------------------
    def translate_tree(self, root: QWidget) -> None:
        """Translate labels, buttons, hints, tables and actions under root."""
        for widget in root.findChildren(QWidget):
            self._translate_widget(widget)
        for action in root.findChildren(QAction):
            self._translate_action(action)
        self._translate_widget(root)

    def _translate_widget(self, widget: QWidget) -> None:
        """Translate one widget's user-visible properties in place."""
        if isinstance(widget, QLabel):
            self._apply(widget, "text", widget.text, widget.setText)
        if isinstance(widget, QAbstractButton):
            self._apply(widget, "text", widget.text, widget.setText)
        if isinstance(widget, QGroupBox):
            self._apply(widget, "title", widget.title, widget.setTitle)
        if isinstance(widget, QLineEdit):
            self._apply(
                widget,
                "placeholder",
                widget.placeholderText,
                widget.setPlaceholderText,
            )
        elif isinstance(widget, QTextEdit):
            self._apply(
                widget,
                "placeholder",
                widget.placeholderText,
                widget.setPlaceholderText,
            )
        if isinstance(widget, QComboBox):
            self._translate_items(widget)
        if isinstance(widget, QTableView):
            self._translate_headers(widget)
        if isinstance(widget, QTabWidget):
            self._translate_tabs(widget)
        self._apply(widget, "tooltip", widget.toolTip, widget.setToolTip)
        title = widget.windowTitle()
        if title:
            self._apply(widget, "window_title", lambda: title, widget.setWindowTitle)

    def _apply(self, owner: QWidget, key: str, getter: Any, setter: Any) -> None:
        """Translate a scalar text property while preserving its source."""
        current = str(getter())
        state_name = "_phoenix_i18n_state"
        state: dict[str, tuple[str, str]] = getattr(owner, state_name, {})
        previous = state.get(key)
        if previous is not None and current == previous[1]:
            source = previous[0]
        else:
            source = current
        target = self.tr(source)
        if target != current:
            setter(target)
        state[key] = (source, target)
        setattr(owner, state_name, state)

    def _translate_items(self, combo: QComboBox) -> None:
        """Translate combo entries without firing selection callbacks."""
        current = [combo.itemText(index) for index in range(combo.count())]
        state: dict[str, Any] = getattr(combo, "_phoenix_i18n_state", {})
        previous = state.get("items")
        if previous is not None and current == previous[1]:
            sources = previous[0]
        else:
            sources = current
        targets = [self.tr(source) for source in sources]
        if targets != current:
            blocked = combo.blockSignals(True)
            try:
                for index, target in enumerate(targets):
                    combo.setItemText(index, target)
            finally:
                combo.blockSignals(blocked)
        state["items"] = (sources, targets)
        setattr(combo, "_phoenix_i18n_state", state)

    def _translate_tabs(self, tabs: QTabWidget) -> None:
        """Translate tab labels while preserving their source strings."""
        current = [tabs.tabText(index) for index in range(tabs.count())]
        state: dict[str, Any] = getattr(tabs, "_phoenix_i18n_state", {})
        previous = state.get("tabs")
        sources = (
            previous[0] if previous is not None and current == previous[1] else current
        )
        targets = [self.tr(source) for source in sources]
        if targets != current:
            blocked = tabs.blockSignals(True)
            try:
                for index, target in enumerate(targets):
                    tabs.setTabText(index, target)
            finally:
                tabs.blockSignals(blocked)
        state["tabs"] = (sources, targets)
        setattr(tabs, "_phoenix_i18n_state", state)

    def _translate_headers(self, table: QTableView) -> None:
        """Translate horizontal header labels of a table view."""
        model = table.model()
        if model is None:
            return
        current = [
            str(
                model.headerData(
                    index,
                    Qt.Orientation.Horizontal,
                    Qt.ItemDataRole.DisplayRole,
                )
                or ""
            )
            for index in range(model.columnCount())
        ]
        state: dict[str, Any] = getattr(table, "_phoenix_i18n_state", {})
        previous = state.get("headers")
        sources = (
            previous[0] if previous is not None and current == previous[1] else current
        )
        targets = [self.tr(source) for source in sources]
        if targets != current:
            blocked = model.blockSignals(True)
            try:
                for index, target in enumerate(targets):
                    model.setHeaderData(
                        index,
                        Qt.Orientation.Horizontal,
                        target,
                        Qt.ItemDataRole.DisplayRole,
                    )
            finally:
                model.blockSignals(blocked)
        state["headers"] = (sources, targets)
        setattr(table, "_phoenix_i18n_state", state)

    def _translate_action(self, action: QAction) -> None:
        """Translate a menu, tray or shortcut action label."""
        current = action.text()
        state: dict[str, Any] = getattr(action, "_phoenix_i18n_state", {})
        previous = state.get("text")
        source = (
            previous[0] if previous is not None and current == previous[1] else current
        )
        target = self.tr(source)
        if target != current:
            action.setText(target)
        state["text"] = (source, target)
        setattr(action, "_phoenix_i18n_state", state)
