"""Persistent, typed application settings.

Settings are stored in an INI file via QSettings. The class deliberately
exposes named properties instead of scattering string keys through the
UI, which keeps defaults and validation in one place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QByteArray, QObject, QSettings, QStandardPaths, pyqtSignal

from .core.config import ProjectConfig

APP_ORGANIZATION = "Phoenix"
APP_NAME = "Phoenix Wallet"

VERBOSITY_MINIMAL = 0
VERBOSITY_STANDARD = 1
VERBOSITY_DETAILED = 2

DEFAULTS: dict[str, Any] = {
    "appearance/theme": "phoenix",
    "appearance/verbosity": VERBOSITY_STANDARD,
    "appearance/animations": True,
    "appearance/hover_effects": True,
    "appearance/page_transitions": True,
    "appearance/animation_speed": 100,
    "appearance/custom_colors": "{}",
    "appearance/language": "ru",
    "appearance/translations_dir": "",
    "appearance/density": "comfortable",
    "appearance/font_scale": 100,
    "privacy/hidden": False,
    "behavior/refresh_seconds": 20,
    "behavior/chart_days": 30,
    "behavior/confirm_send": True,
    "behavior/last_page": "overview",
    "connection/proxy_url": "",
    "connection/proxy_user": "",
    "connection/proxy_password": "",
    "connection/timeout_seconds": 12,
    "daemon/autostart": True,
    "daemon/binary": "",
    "daemon/datadir": "",
    "daemon/extra_args": "",
    "daemon/start_timeout": 40,
    "media/enabled": False,
    "media/path": "",
    "media/dim": 58,
    "media/blur": 10,
    "media/pan": True,
    "sounds/enabled": False,
    "sounds/volume": 35,
    "console/history": "[]",
    "wallet/last_receive_address": "",
    "wallet/recent_recipients": "[]",
    "window/geometry": b"",
    "window/state": b"",
}


def default_settings_path() -> Path:
    """Return the per-user settings file used outside tests."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        base = str(Path.home() / ".config" / "phoenix-wallet")
    return Path(base) / "settings.ini"


class Settings(QObject):
    """Typed access to persistent application preferences."""

    changed = pyqtSignal(str, object)
    projectChanged = pyqtSignal()

    def __init__(
        self, path: str | Path | None = None, parent: QObject | None = None
    ) -> None:
        """Initialize the Settings instance."""
        super().__init__(parent)
        self._path = Path(path) if path else default_settings_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._store = QSettings(str(self._path), QSettings.Format.IniFormat)
        self._project: ProjectConfig | None = None
        self._loading = False

    @property
    def path(self) -> Path:
        """Return the settings file location."""
        return self._path

    def sync(self) -> None:
        """Flush pending changes to disk."""
        self._store.sync()

    def reset(self) -> None:
        """Remove every stored preference and restore built-in defaults."""
        self._store.clear()
        self._store.sync()

    def contains(self, key: str) -> bool:
        """Return whether a key has been stored explicitly."""
        return self._store.contains(key)

    def raw_value(self, key: str, default: Any = None) -> Any:
        """Read a value without applying a typed default."""
        return self._store.value(key, default)

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value, falling back to the built-in defaults."""
        fallback = DEFAULTS.get(key, default)
        value = self._store.value(key, fallback)
        if isinstance(fallback, bool):
            return self._to_bool(value, fallback)
        if isinstance(fallback, int) and not isinstance(fallback, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback
        return value

    def set_many(
        self,
        values: dict[str, Any],
        emit: bool = True,
        signal_key: str = "appearance/batch",
    ) -> None:
        """Store several values and emit one grouped notification.

        This keeps the Apply button in appearance settings from rebuilding
        the stylesheet once for every changed control.
        """
        changed = False
        for key, value in values.items():
            before = self.get(key)
            self.set(key, value, emit=False)
            if before != self.get(key):
                changed = True
        if changed:
            self._store.sync()
        if changed and emit and not self._loading:
            self.changed.emit(signal_key, dict(values))

    def set(self, key: str, value: Any, emit: bool = True) -> None:
        """Store a value and notify listeners when it actually changed."""
        previous = self.get(key)
        if isinstance(previous, bool):
            value = self._to_bool(value, previous)
        elif isinstance(previous, int) and not isinstance(previous, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = previous
        if previous == value and self._store.contains(key):
            return
        self._store.setValue(key, value)
        if emit and not self._loading:
            self.changed.emit(key, value)

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        """Normalize QSettings' many boolean representations."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    def reset_defaults(self, keep_window: bool = True) -> None:
        """Restore every preference to its shipped default.

        Window geometry and the last page are kept by default so a reset
        does not move the window to an unexpected position.
        """
        protected = {"window/geometry", "window/state", "behavior/last_page"}
        for key, value in DEFAULTS.items():
            if keep_window and key in protected:
                continue
            self.set(key, value)
        self.sync()

    def bootstrap(self, project: ProjectConfig, force: bool = False) -> None:
        """Seed connection defaults from ``config.toml`` once.

        Values explicitly stored by the user are preserved unless
        ``force`` is requested from the settings page.
        """
        self._project = project
        self._loading = True
        try:
            mapping = {
                "connection/proxy_url": project.proxy_url,
                "connection/proxy_user": project.proxy_user,
                "connection/proxy_password": project.proxy_password,
                "daemon/datadir": str(project.default_datadir),
            }
            for key, value in mapping.items():
                if force or not self._store.contains(key) or not self._store.value(key):
                    self._store.setValue(key, value)
            self._store.sync()
        finally:
            self._loading = False
        self.projectChanged.emit()

    @property
    def project(self) -> ProjectConfig | None:
        """Return the project configuration used for bootstrapping."""
        return self._project

    def effective_proxy(self) -> tuple[str, str, str]:
        """Return URL, user and password, falling back to config.toml."""
        url = str(self.get("connection/proxy_url") or "")
        user = str(self.get("connection/proxy_user") or "")
        password = str(self.get("connection/proxy_password") or "")
        if self._project is not None:
            url = url or self._project.proxy_url
            user = user or self._project.proxy_user
            password = password or self._project.proxy_password
        return url or "http://127.0.0.1:16666", user, password

    # Appearance -----------------------------------------------------
    @property
    def hover_effects(self) -> bool:
        """Return whether pointer-hover motion is enabled."""
        return bool(self.get("appearance/hover_effects"))

    @hover_effects.setter
    def hover_effects(self, value: bool) -> None:
        """Set pointer-hover motion."""
        self.set("appearance/hover_effects", bool(value))

    @property
    def page_transitions(self) -> bool:
        """Return whether page transitions are enabled."""
        return bool(self.get("appearance/page_transitions"))

    @page_transitions.setter
    def page_transitions(self, value: bool) -> None:
        """Set page transitions."""
        self.set("appearance/page_transitions", bool(value))

    @property
    def animation_speed(self) -> int:
        """Return animation speed in percent of the nominal duration."""
        try:
            value = int(self.get("appearance/animation_speed"))
        except (TypeError, ValueError):
            value = 100
        return max(50, min(200, value))

    @animation_speed.setter
    def animation_speed(self, value: int) -> None:
        """Set animation speed, clamped to 50..200 percent."""
        self.set("appearance/animation_speed", max(50, min(200, int(value))))

    @property
    def custom_colors(self) -> dict[str, str]:
        """Return user theme overrides as a token-to-color mapping."""
        raw = self.get("appearance/custom_colors")
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
        try:
            parsed = json.loads(str(raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items()}

    def set_custom_colors(self, colors: dict[str, str]) -> None:
        """Persist theme token overrides as JSON."""
        self.set("appearance/custom_colors", json.dumps(colors, sort_keys=True))

    @property
    def theme(self) -> str:
        """Return the selected theme key."""
        return str(self.get("appearance/theme"))

    @theme.setter
    def theme(self, value: str) -> None:
        """Set the theme value."""
        self.set("appearance/theme", value)

    @property
    def verbosity(self) -> int:
        """Return the informativeness level (0, 1 or 2)."""
        return max(
            VERBOSITY_MINIMAL,
            min(VERBOSITY_DETAILED, int(self.get("appearance/verbosity"))),
        )

    @verbosity.setter
    def verbosity(self, value: int) -> None:
        """Set the verbosity value."""
        self.set(
            "appearance/verbosity",
            max(VERBOSITY_MINIMAL, min(VERBOSITY_DETAILED, int(value))),
        )

    @property
    def detailed(self) -> bool:
        """Return whether the most detailed mode is active."""
        return self.verbosity >= VERBOSITY_DETAILED

    @property
    def minimal(self) -> bool:
        """Return whether the compact mode is active."""
        return self.verbosity <= VERBOSITY_MINIMAL

    @property
    def animations(self) -> bool:
        """Return whether non-essential animations are enabled."""
        return bool(self.get("appearance/animations"))

    @animations.setter
    def animations(self, value: bool) -> None:
        """Set the animations value."""
        self.set("appearance/animations", value)

    @property
    def density(self) -> str:
        """Return the table density preset."""
        value = str(self.get("appearance/density"))
        return value if value in {"comfortable", "compact"} else "comfortable"

    @density.setter
    def density(self, value: str) -> None:
        """Set the density value."""
        self.set(
            "appearance/density",
            value if value in {"comfortable", "compact"} else "comfortable",
        )

    @property
    def font_scale(self) -> int:
        """Return the UI font scale in percent."""
        return max(80, min(140, int(self.get("appearance/font_scale"))))

    @font_scale.setter
    def font_scale(self, value: int) -> None:
        """Set the font_scale value."""
        self.set("appearance/font_scale", max(80, min(140, int(value))))

    # Behavior -------------------------------------------------------
    @property
    def refresh_seconds(self) -> int:
        """Return the automatic refresh period in seconds."""
        return max(5, min(600, int(self.get("behavior/refresh_seconds"))))

    @refresh_seconds.setter
    def refresh_seconds(self, value: int) -> None:
        """Set the refresh_seconds value."""
        self.set("behavior/refresh_seconds", max(5, min(600, int(value))))

    @property
    def chart_days(self) -> int:
        """Return the default analytics window in days."""
        return max(7, min(365, int(self.get("behavior/chart_days"))))

    @chart_days.setter
    def chart_days(self, value: int) -> None:
        """Set the chart_days value."""
        self.set("behavior/chart_days", max(7, min(365, int(value))))

    @property
    def confirm_send(self) -> bool:
        """Return whether sending requires an explicit confirmation."""
        return bool(self.get("behavior/confirm_send"))

    @confirm_send.setter
    def confirm_send(self, value: bool) -> None:
        """Set the confirm_send value."""
        self.set("behavior/confirm_send", value)

    @property
    def last_page(self) -> str:
        """Return the page that was open during the previous session."""
        return str(self.get("behavior/last_page"))

    @last_page.setter
    def last_page(self, value: str) -> None:
        """Set the last_page value."""
        self.set("behavior/last_page", value)

    # Connection -----------------------------------------------------
    @property
    def timeout_seconds(self) -> int:
        """Return the HTTP timeout in seconds."""
        return max(3, min(120, int(self.get("connection/timeout_seconds"))))

    @timeout_seconds.setter
    def timeout_seconds(self, value: int) -> None:
        """Set the timeout_seconds value."""
        self.set("connection/timeout_seconds", max(3, min(120, int(value))))

    # Daemon ---------------------------------------------------------
    @property
    def daemon_autostart(self) -> bool:
        """Return whether the bundled daemon should be started."""
        return bool(self.get("daemon/autostart"))

    @daemon_autostart.setter
    def daemon_autostart(self, value: bool) -> None:
        """Set the daemon_autostart value."""
        self.set("daemon/autostart", value)

    @property
    def daemon_binary(self) -> str:
        """Return an explicitly configured daemon executable path."""
        return str(self.get("daemon/binary") or "")

    @daemon_binary.setter
    def daemon_binary(self, value: str) -> None:
        """Set the daemon_binary value."""
        self.set("daemon/binary", value)

    @property
    def daemon_datadir(self) -> str:
        """Return the NovaCoin data directory used by the daemon."""
        return str(self.get("daemon/datadir") or "")

    @daemon_datadir.setter
    def daemon_datadir(self, value: str) -> None:
        """Set the daemon_datadir value."""
        self.set("daemon/datadir", value)

    @property
    def daemon_extra_args(self) -> str:
        """Return extra command line arguments for the daemon."""
        return str(self.get("daemon/extra_args") or "")

    @daemon_extra_args.setter
    def daemon_extra_args(self, value: str) -> None:
        """Set the daemon_extra_args value."""
        self.set("daemon/extra_args", value)

    @property
    def daemon_start_timeout(self) -> int:
        """Return how long to wait for the daemon RPC to come up."""
        return max(10, min(180, int(self.get("daemon/start_timeout"))))

    @daemon_start_timeout.setter
    def daemon_start_timeout(self, value: int) -> None:
        """Set the daemon_start_timeout value."""
        self.set("daemon/start_timeout", max(10, min(180, int(value))))

    # Media ----------------------------------------------------------
    @property
    def media_enabled(self) -> bool:
        """Return whether a custom local backdrop is enabled."""
        return bool(self.get("media/enabled"))

    @media_enabled.setter
    def media_enabled(self, value: bool) -> None:
        """Set the media_enabled value."""
        self.set("media/enabled", value)

    @property
    def media_path(self) -> str:
        """Return the local image or video used as a backdrop."""
        return str(self.get("media/path") or "")

    @media_path.setter
    def media_path(self, value: str) -> None:
        """Set the media_path value."""
        self.set("media/path", value)

    @property
    def media_dim(self) -> int:
        """Return the backdrop dimming strength in percent."""
        return max(0, min(90, int(self.get("media/dim"))))

    @media_dim.setter
    def media_dim(self, value: int) -> None:
        """Set the media_dim value."""
        self.set("media/dim", max(0, min(90, int(value))))

    @property
    def media_blur(self) -> int:
        """Return the backdrop blur radius."""
        return max(0, min(40, int(self.get("media/blur"))))

    @media_blur.setter
    def media_blur(self, value: int) -> None:
        """Set the media_blur value."""
        self.set("media/blur", max(0, min(40, int(value))))

    @property
    def media_pan(self) -> bool:
        """Return whether a subtle Ken Burns pan is enabled."""
        return bool(self.get("media/pan"))

    @media_pan.setter
    def media_pan(self, value: bool) -> None:
        """Set the media_pan value."""
        self.set("media/pan", value)

    # Sounds ---------------------------------------------------------
    @property
    def sounds_enabled(self) -> bool:
        """Return whether interface sounds are enabled."""
        return bool(self.get("sounds/enabled"))

    @sounds_enabled.setter
    def sounds_enabled(self, value: bool) -> None:
        """Set the sounds_enabled value."""
        self.set("sounds/enabled", value)

    @property
    def sound_volume(self) -> int:
        """Return the interface sound volume in percent."""
        return max(0, min(100, int(self.get("sounds/volume"))))

    @sound_volume.setter
    def sound_volume(self, value: int) -> None:
        """Set the sound_volume value."""
        self.set("sounds/volume", max(0, min(100, int(value))))

    # Wallet helpers -------------------------------------------------
    def recent_recipients(self) -> list[str]:
        """Return the most recently used recipient addresses."""
        try:
            value = json.loads(str(self.get("wallet/recent_recipients") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()][:12]

    def add_recent_recipient(self, address: str) -> None:
        """Remember a recipient address, most recent first."""
        text = (address or "").strip()
        if not text:
            return
        recipients = [item for item in self.recent_recipients() if item != text]
        recipients.insert(0, text)
        self.set("wallet/recent_recipients", json.dumps(recipients[:12]))

    @property
    def last_receive_address(self) -> str:
        """Return the address shown on the receive page last time."""
        return str(self.get("wallet/last_receive_address") or "")

    @last_receive_address.setter
    def last_receive_address(self, value: str) -> None:
        """Set the last_receive_address value."""
        self.set("wallet/last_receive_address", value)

    def console_history(self) -> list[str]:
        """Return previously executed console commands."""
        try:
            value = json.loads(str(self.get("console/history") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(item) for item in value if isinstance(item, (str, int, float))][
            -100:
        ]

    def set_console_history(self, commands: list[str]) -> None:
        """Persist up to one hundred console commands."""
        self.set("console/history", json.dumps(commands[-100:]))

    # Window state ---------------------------------------------------
    @property
    def window_geometry(self) -> QByteArray:
        """Return the stored main window geometry."""
        value = self._store.value("window/geometry", QByteArray())
        return value if isinstance(value, QByteArray) else QByteArray()

    @window_geometry.setter
    def window_geometry(self, value: QByteArray) -> None:
        """Set the window_geometry value."""
        self.set("window/geometry", value)

    @property
    def window_state(self) -> QByteArray:
        """Return the stored main window state."""
        value = self._store.value("window/state", QByteArray())
        return value if isinstance(value, QByteArray) else QByteArray()

    @window_state.setter
    def window_state(self, value: QByteArray) -> None:
        """Set the window_state value."""
        self.set("window/state", value)
