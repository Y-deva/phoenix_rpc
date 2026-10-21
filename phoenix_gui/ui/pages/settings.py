"""Application settings page with live previews and connection checks."""

from __future__ import annotations

import json
import time
from typing import Any

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from ...core.errors import humanize_error
from ...core.sounds import SoundPlayer
from ...core.tasks import run_async
from ...rpc.client import RPCClient
from ...ui.widgets.card import Card, SectionHeader
from ...ui.widgets.fields import (
    PasswordField,
    PathField,
    SegmentedControl,
)
from ...ui.widgets.icons import brand_logo, icon
from ...ui.widgets.progress import Spinner
from ...ui.widgets.theme import (
    CUSTOM_TOKENS,
    THEMES,
    THEME_ORDER,
    Theme,
    contrast_ratio,
    customize_theme,
)
from .base import ScrollPage

VERBOSITY_HINTS = {
    0: "Только главное: суммы, статусы и основные действия.",
    1: "Баланс, комиссии, подтверждения и подсказки по умолчанию.",
    2: "Сырые данные RPC, задержки запросов и дополнительные детали.",
}


class SettingsPage(ScrollPage):
    """Configure appearance, background media, daemon and connection."""

    page_id = "settings"
    page_title = "Настройки"
    page_subtitle = "Внешний вид, безопасность и параметры подключения"
    auto_refresh = False

    connectionChanged = pyqtSignal()
    daemonRestartRequested = pyqtSignal()

    def __init__(self, context: Any, parent: QWidget | None = None) -> None:
        """Initialize the SettingsPage instance."""
        super().__init__(context, parent)
        self._syncing = False
        self._appearance_dirty = False
        self._draft_custom: dict[str, str] = {}
        self._draft_theme_key = self.settings.theme
        self._sound_player: SoundPlayer | None = None
        self._build()
        self._sync_from_settings()
        self.settings.changed.connect(self._on_setting_changed)

    def _build(self) -> None:
        """Create all preference sections."""
        self._build_appearance()
        self._build_behavior()
        self._build_media()
        self._build_sound()
        self._build_connection()
        self._build_daemon()
        self._build_about()
        self.add_stretch()

    def _section(self, title: str, subtitle: str = "") -> tuple[Card, QFormLayout]:
        """Create a titled settings card and return its form layout."""
        card = Card(padding=18)
        header = SectionHeader(title, subtitle, parent=card)
        card.add(header)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        card.add_layout(form)
        self.body.addWidget(card)
        return card, form

    def _build_appearance(self) -> None:
        """Theme, custom colors, typography and motion options."""
        card, form = self._section(
            "Внешний вид",
            "Настройте графику и нажмите Применить, чтобы увидеть результат",
        )
        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        self.theme_combo = QComboBox()
        for key in THEME_ORDER:
            self.theme_combo.addItem(THEMES[key].name, key)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.theme_combo.setToolTip("Выберите базовую цветовую схему интерфейса")
        self.theme_preview = QLabel()
        self.theme_preview.setObjectName("ThemePreview")
        self.theme_preview.setFixedSize(220, 58)
        self.theme_preview.setToolTip("Предпросмотр выбранной темы и цветов")
        theme_row.addWidget(self.theme_combo, 1)
        theme_row.addWidget(self.theme_preview)
        form.addRow("Тема", theme_row)

        colors = QGridLayout()
        colors.setHorizontalSpacing(8)
        colors.setVerticalSpacing(8)
        self._color_buttons: dict[str, QPushButton] = {}
        labels = {
            "bg": "Фон",
            "sidebar": "Панель",
            "surface": "Карточки",
            "accent": "Акцент",
            "text": "Текст",
        }
        for index, token in enumerate(CUSTOM_TOKENS):
            button = QPushButton(labels[token])
            button.setObjectName("ColorButton")
            button.setFixedHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Изменить цвет: {labels[token].lower()}")
            button.clicked.connect(
                lambda _checked=False, name=token: self._choose_color(name)
            )
            self._color_buttons[token] = button
            colors.addWidget(button, index // 3, index % 3)
        self.reset_colors_button = QPushButton("Сбросить цвета")
        self.reset_colors_button.setObjectName("GhostButton")
        self.reset_colors_button.setToolTip("Вернуть цвета выбранной базовой темы")
        self.reset_colors_button.clicked.connect(self._reset_custom_colors)
        colors.addWidget(self.reset_colors_button, 1, 2)
        colors.setColumnStretch(0, 1)
        colors.setColumnStretch(1, 1)
        colors.setColumnStretch(2, 1)
        form.addRow("Свои цвета", colors)

        self.color_warning = QLabel()
        self.color_warning.setObjectName("ErrorText")
        self.color_warning.setWordWrap(True)
        self.color_warning.hide()
        form.addRow("", self.color_warning)

        self.verbosity_control = SegmentedControl()
        self.verbosity_control.add_segment("0", "Минимум")
        self.verbosity_control.add_segment("1", "Стандарт")
        self.verbosity_control.add_segment("2", "Подробно")
        self.verbosity_control.valueChanged.connect(self._on_verbosity_changed)
        self.verbosity_control.setToolTip(
            "Сколько деталей показывать во всем приложении"
        )
        form.addRow("Информативность", self.verbosity_control)
        self.verbosity_hint = QLabel(VERBOSITY_HINTS[1])
        self.verbosity_hint.setObjectName("HintText")
        self.verbosity_hint.setWordWrap(True)
        form.addRow("", self.verbosity_hint)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(10)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(80, 140)
        self.scale_slider.setSingleStep(5)
        self.scale_slider.setPageStep(5)
        self.scale_slider.setToolTip("Размер шрифта интерфейса от 80 до 140 процентов")
        self.scale_value = QLabel("100 %")
        self.scale_value.setObjectName("Mono")
        self.scale_value.setFixedWidth(52)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_value)
        form.addRow("Масштаб", scale_row)

        self.animations_box = QCheckBox("Анимации интерфейса")
        self.animations_box.setToolTip(
            "Главный выключатель плавных появлений и переходов"
        )
        self.animations_box.toggled.connect(self._on_animation_toggled)
        form.addRow("Движение", self.animations_box)

        self.hover_box = QCheckBox("Подсветка кликабельных элементов при наведении")
        self.hover_box.setToolTip("Мягко подсвечивать кнопки и карточки под курсором")
        self.hover_box.toggled.connect(self._mark_appearance_dirty)
        form.addRow("", self.hover_box)

        self.transitions_box = QCheckBox("Переходы между страницами")
        self.transitions_box.setToolTip("Плавно проявлять страницу при переключении")
        self.transitions_box.toggled.connect(self._mark_appearance_dirty)
        form.addRow("", self.transitions_box)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(50, 200)
        self.speed_slider.setSingleStep(10)
        self.speed_slider.setPageStep(25)
        self.speed_slider.setToolTip("Скорость анимаций от 50 до 200 процентов")
        self.speed_value = QLabel("100 %")
        self.speed_value.setObjectName("Mono")
        self.speed_value.setFixedWidth(52)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_value)
        form.addRow("Скорость", speed_row)

        apply_row = QHBoxLayout()
        apply_row.setSpacing(10)
        self.appearance_status = QLabel("Сохранено")
        self.appearance_status.setObjectName("HintText")
        self.apply_button = QPushButton("Применить")
        self.apply_button.setObjectName("AccentButton")
        self.apply_button.setToolTip("Применить тему, цвета, шрифт и анимации")
        self.apply_button.clicked.connect(self._apply_appearance)
        self.apply_button.setEnabled(False)
        apply_row.addWidget(self.appearance_status, 1)
        apply_row.addWidget(self.apply_button)
        form.addRow("", apply_row)

    def _build_behavior(self) -> None:
        """Refresh cadence, charts and confirmation behavior."""
        card, form = self._section(
            "Поведение", "Как часто обновлять данные и спрашивать подтверждение"
        )
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(5, 600)
        self.refresh_spin.setSuffix(" с")
        self.refresh_spin.setToolTip("Интервал автоматического обновления страниц")
        self.refresh_spin.lineEdit().setToolTip(
            "Интервал автоматического обновления страниц"
        )
        self.refresh_spin.valueChanged.connect(
            lambda value: self.settings.set("behavior/refresh_seconds", value)
        )
        form.addRow("Обновление", self.refresh_spin)

        self.chart_days_spin = QSpinBox()
        self.chart_days_spin.setRange(7, 365)
        self.chart_days_spin.setSuffix(" дн.")
        self.chart_days_spin.setToolTip("Период графиков по умолчанию")
        self.chart_days_spin.lineEdit().setToolTip("Период графиков по умолчанию")
        self.chart_days_spin.valueChanged.connect(
            lambda value: self.settings.set("behavior/chart_days", value)
        )
        form.addRow("Период графиков", self.chart_days_spin)

        self.confirm_send_box = QCheckBox("Спрашивать подтверждение перед отправкой")
        self.confirm_send_box.setToolTip(
            "Показывать диалог с адресом, суммой и комиссией"
        )
        self.confirm_send_box.toggled.connect(
            lambda checked: self.settings.set("behavior/confirm_send", checked)
        )
        form.addRow("Безопасность", self.confirm_send_box)

    def _build_media(self) -> None:
        """Local image or video backdrop with dim and blur."""
        card, form = self._section(
            "Фон приложения",
            "Локальный файл не загружается в сеть и не нагружает сервер",
        )
        self.media_enabled_box = QCheckBox("Показывать медиафон")
        self.media_enabled_box.setToolTip(
            "Показывать локальное изображение или видео за интерфейсом"
        )
        self.media_enabled_box.toggled.connect(
            lambda checked: self.settings.set("media/enabled", checked)
        )
        form.addRow("Медиа", self.media_enabled_box)

        self.media_path = PathField(
            mode="file",
            caption="Выбрать",
            filter_text=(
                "Изображения (*.png *.jpg *.jpeg *.webp *.bmp);;"
                "Видео (*.mp4 *.webm *.mov *.mkv);;Все файлы (*)"
            ),
        )
        self.media_path.setToolTip(
            "Поддерживаются PNG, JPEG, WebP, BMP, MP4, WebM и MOV"
        )
        self.media_path.pathChanged.connect(self._on_media_path)
        form.addRow("Файл", self.media_path)

        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        self.media_clear = QPushButton("Убрать фон")
        self.media_clear.setObjectName("GhostButton")
        self.media_clear.setToolTip("Вернуть сгенерированный фон")
        self.media_clear.clicked.connect(self._clear_media)
        clear_row.addWidget(self.media_clear)
        form.addRow("", clear_row)

        self.dim_slider = QSlider(Qt.Orientation.Horizontal)
        self.dim_slider.setRange(0, 90)
        self.dim_slider.setToolTip(
            "Затемнение фона: 0 - без затемнения, 90 - почти черный"
        )
        self.dim_value = QLabel("58 %")
        self.dim_value.setObjectName("Mono")
        self.dim_value.setFixedWidth(52)
        self.dim_slider.valueChanged.connect(self._on_dim_changed)
        dim_row = QHBoxLayout()
        dim_row.addWidget(self.dim_slider, 1)
        dim_row.addWidget(self.dim_value)
        form.addRow("Затемнение", dim_row)

        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, 40)
        self.blur_slider.setToolTip("Размытие фона: 0 - четкое изображение")
        self.blur_value = QLabel("10")
        self.blur_value.setObjectName("Mono")
        self.blur_value.setFixedWidth(52)
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        blur_row = QHBoxLayout()
        blur_row.addWidget(self.blur_slider, 1)
        blur_row.addWidget(self.blur_value)
        form.addRow("Размытие", blur_row)

        self.pan_box = QCheckBox("Медленно перемещать фон")
        self.pan_box.setToolTip("Отключите для экономии ресурсов на слабых машинах")
        self.pan_box.toggled.connect(
            lambda checked: self.settings.set("media/pan", checked)
        )
        form.addRow("", self.pan_box)

        hint = QLabel("Файл можно перетащить прямо в окно приложения.")
        hint.setObjectName("HintText")
        form.addRow("", hint)

    def _build_sound(self) -> None:
        """Optional synthesized interface sounds."""
        card, form = self._section("Звуки", "Короткие сигналы без внешних файлов")
        self.sounds_box = QCheckBox("Звуковые уведомления")
        self.sounds_box.setToolTip("Короткие сигналы при успехе и ошибке")
        self.sounds_box.toggled.connect(
            lambda checked: self.settings.set("sounds/enabled", checked)
        )
        form.addRow("Звуки", self.sounds_box)
        volume_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setToolTip("Громкость звуковых уведомлений")
        self.volume_value = QLabel("35 %")
        self.volume_value.setObjectName("Mono")
        self.volume_value.setFixedWidth(52)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_row.addWidget(self.volume_slider, 1)
        volume_row.addWidget(self.volume_value)
        form.addRow("Громкость", volume_row)
        test_row = QHBoxLayout()
        test_row.addStretch(1)
        self.sound_test = QPushButton("Проверить звук")
        self.sound_test.setObjectName("GhostButton")
        self.sound_test.setToolTip("Проиграть короткий тестовый сигнал")
        self.sound_test.clicked.connect(self._test_sound)
        test_row.addWidget(self.sound_test)
        form.addRow("", test_row)

    def _build_connection(self) -> None:
        """Proxy endpoint, credentials and connection check."""
        card, form = self._section(
            "Подключение",
            "GUI общается только с локальным прокси, прокси - с novacoind",
        )
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:16666")
        self.proxy_edit.setToolTip("URL локального HTTP-прокси")
        self.proxy_edit.editingFinished.connect(self._save_connection)
        form.addRow("Адрес прокси", self.proxy_edit)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Имя пользователя прокси")
        self.user_edit.setToolTip("Логин Basic Auth для локального прокси")
        self.user_edit.editingFinished.connect(self._save_connection)
        form.addRow("Пользователь", self.user_edit)
        self.password_edit = PasswordField()
        self.password_edit.setPlaceholderText("Пароль прокси")
        self.password_edit.editingFinished.connect(self._save_connection)
        form.addRow("Пароль", self.password_edit)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(3, 120)
        self.timeout_spin.setSuffix(" с")
        self.timeout_spin.setToolTip("Таймаут одного RPC-запроса")
        self.timeout_spin.lineEdit().setToolTip("Таймаут одного RPC-запроса")
        self.timeout_spin.valueChanged.connect(
            lambda value: self.settings.set("connection/timeout_seconds", value)
        )
        form.addRow("Таймаут", self.timeout_spin)
        test_row = QHBoxLayout()
        self.connection_status = QLabel("Не проверено")
        self.connection_status.setObjectName("Muted")
        self.test_spinner = Spinner(size=16)
        self.test_button = QPushButton("Проверить соединение")
        self.test_button.setObjectName("GhostButton")
        self.test_button.setIcon(icon("link", self.tokens.get("muted", "#A7B1C2"), 15))
        self.test_button.setToolTip("Выполнить getinfo через указанный прокси")
        self.test_button.clicked.connect(self._test_connection)
        test_row.addWidget(self.connection_status, 1)
        test_row.addWidget(self.test_spinner)
        test_row.addWidget(self.test_button)
        form.addRow("Проверка", test_row)

    def _build_daemon(self) -> None:
        """Autostart, binary location and daemon arguments."""
        card, form = self._section(
            "Демон novacoind",
            "C++ демон запускается вместе с кошельком в фоновом режиме",
        )
        self.daemon_status = QLabel("Состояние неизвестно")
        self.daemon_status.setObjectName("Muted")
        form.addRow("Статус", self.daemon_status)
        self.autostart_box = QCheckBox("Запускать novacoind при старте GUI")
        self.autostart_box.setToolTip("Отключите, если демон уже запущен вручную")
        self.autostart_box.toggled.connect(
            lambda checked: self.settings.set("daemon/autostart", checked)
        )
        form.addRow("Автозапуск", self.autostart_box)
        self.binary_field = PathField(mode="file", caption="Обзор")
        self.binary_field.setToolTip("Путь к исполняемому файлу novacoind")
        self.binary_field.pathChanged.connect(
            lambda value: self.settings.set("daemon/binary", value)
        )
        form.addRow("Бинарник", self.binary_field)
        self.datadir_field = PathField(mode="dir", caption="Обзор")
        self.datadir_field.setToolTip("Каталог данных novacoind")
        self.datadir_field.pathChanged.connect(
            lambda value: self.settings.set("daemon/datadir", value)
        )
        form.addRow("Каталог данных", self.datadir_field)
        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("-maxconnections=16 -port=8344")
        self.args_edit.setToolTip("Дополнительные аргументы командной строки")
        self.args_edit.editingFinished.connect(
            lambda: self.settings.set(
                "daemon/extra_args", self.args_edit.text().strip()
            )
        )
        form.addRow("Аргументы", self.args_edit)
        self.start_timeout_spin = QSpinBox()
        self.start_timeout_spin.setRange(10, 180)
        self.start_timeout_spin.setSuffix(" с")
        self.start_timeout_spin.setToolTip("Сколько ждать готовности RPC после запуска")
        self.start_timeout_spin.lineEdit().setToolTip(
            "Сколько ждать готовности RPC после запуска"
        )
        self.start_timeout_spin.valueChanged.connect(
            lambda value: self.settings.set("daemon/start_timeout", value)
        )
        form.addRow("Ожидание", self.start_timeout_spin)
        daemon_row = QHBoxLayout()
        daemon_row.addStretch(1)
        self.restart_daemon_button = QPushButton("Перезапустить демон")
        self.restart_daemon_button.setObjectName("GhostButton")
        self.restart_daemon_button.setIcon(
            icon("refresh", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.restart_daemon_button.setToolTip("Остановить и снова запустить novacoind")
        self.restart_daemon_button.clicked.connect(self.daemonRestartRequested.emit)
        daemon_row.addWidget(self.restart_daemon_button)
        form.addRow("", daemon_row)
        hint = QLabel(
            "Прокси запускается отдельно: он запрашивает пароль хранилища ключей "
            "в терминале."
        )
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        form.addRow("", hint)

    def _build_about(self) -> None:
        """Project paths, about dialog and reset."""
        card, form = self._section("Обслуживание", "Пути проекта и сброс предпочтений")
        root_label = QLabel(str(self.config.root))
        root_label.setObjectName("Mono")
        root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root_label.setToolTip("Каталог проекта")
        form.addRow("Каталог", root_label)
        config_label = QLabel(str(self.config.config_path))
        config_label.setObjectName("Mono")
        config_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        config_label.setToolTip("Файл config.toml")
        form.addRow("Конфигурация", config_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        open_button = QPushButton("Открыть каталог")
        open_button.setObjectName("GhostButton")
        open_button.setIcon(icon("folder", self.tokens.get("muted", "#A7B1C2"), 15))
        open_button.setToolTip("Открыть каталог проекта в файловом менеджере")
        open_button.clicked.connect(self._open_project_folder)
        about_button = QPushButton("О программе")
        about_button.setObjectName("GhostButton")
        about_button.setIcon(icon("info", self.tokens.get("muted", "#A7B1C2"), 15))
        about_button.setToolTip("Версия и назначение приложения")
        about_button.clicked.connect(self._show_about)
        reset_button = QPushButton("Сбросить настройки")
        reset_button.setObjectName("DangerButton")
        reset_button.setToolTip("Вернуть все предпочтения к значениям по умолчанию")
        reset_button.clicked.connect(self._reset_settings)
        buttons.addWidget(open_button)
        buttons.addWidget(about_button)
        buttons.addWidget(reset_button)
        form.addRow("", buttons)

    def _sync_from_settings(self) -> None:
        """Push stored values into the controls without feedback loops."""
        self._syncing = True
        try:
            theme_index = self.theme_combo.findData(self.settings.theme)
            self.theme_combo.setCurrentIndex(max(0, theme_index))
            self._draft_theme_key = self.settings.theme
            self._draft_custom = dict(self.settings.custom_colors)
            self._refresh_color_buttons()
            self._update_theme_preview()
            self.verbosity_control.set_value(str(self.settings.verbosity))
            self.verbosity_hint.setText(VERBOSITY_HINTS[self.settings.verbosity])
            self.scale_slider.setValue(self.settings.font_scale)
            self.scale_value.setText(f"{self.settings.font_scale} %")
            self.animations_box.setChecked(self.settings.animations)
            self._on_animation_toggled(self.animations_box.isChecked())
            self.hover_box.setChecked(self.settings.hover_effects)
            self.transitions_box.setChecked(self.settings.page_transitions)
            self.speed_slider.setValue(self.settings.animation_speed)
            self.speed_value.setText(f"{self.settings.animation_speed} %")
            self._set_appearance_status("Сохранено", dirty=False)
            self.refresh_spin.setValue(self.settings.refresh_seconds)
            self.chart_days_spin.setValue(self.settings.chart_days)
            self.confirm_send_box.setChecked(self.settings.confirm_send)

            self.media_enabled_box.setChecked(self.settings.media_enabled)
            self.media_path.set_path(self.settings.media_path)
            self.dim_slider.setValue(self.settings.media_dim)
            self.dim_value.setText(f"{self.settings.media_dim} %")
            self.blur_slider.setValue(self.settings.media_blur)
            self.blur_value.setText(str(self.settings.media_blur))
            self.pan_box.setChecked(self.settings.media_pan)

            self.sounds_box.setChecked(self.settings.sounds_enabled)
            self.volume_slider.setValue(self.settings.sound_volume)
            self.volume_value.setText(f"{self.settings.sound_volume} %")

            self.proxy_edit.setText(str(self.settings.get("connection/proxy_url")))
            self.user_edit.setText(str(self.settings.get("connection/proxy_user")))
            self.password_edit.setText(
                str(self.settings.get("connection/proxy_password"))
            )
            self.timeout_spin.setValue(self.settings.timeout_seconds)

            self.autostart_box.setChecked(self.settings.daemon_autostart)
            self.binary_field.set_path(self.settings.daemon_binary)
            self.datadir_field.set_path(self.settings.daemon_datadir)
            self.args_edit.setText(self.settings.daemon_extra_args)
            self.start_timeout_spin.setValue(self.settings.daemon_start_timeout)
        finally:
            self._syncing = False

    def _on_setting_changed(self, key: str, value: object) -> None:
        """Reflect changes made by other components."""
        if self._syncing:
            return
        if key == "appearance/batch":
            self._sync_from_settings()
            return
        if key == "appearance/theme":
            index = self.theme_combo.findData(str(value))
            if index >= 0:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(index)
                self.theme_combo.blockSignals(False)
                self._draft_theme_key = str(value)
                self._draft_custom = {}
                self._refresh_color_buttons()
                self._update_theme_preview()
        elif key == "appearance/verbosity":
            self._syncing = True
            self.verbosity_control.set_value(str(value))
            self.verbosity_hint.setText(VERBOSITY_HINTS.get(int(value), ""))
            self._syncing = False
        elif key == "appearance/font_scale":
            self._syncing = True
            self.scale_slider.setValue(int(value))
            self.scale_value.setText(f"{int(value)} %")
            self._syncing = False
        elif key == "media/enabled":
            self.media_enabled_box.setChecked(bool(value))
        elif key == "media/path":
            self.media_path.set_path(str(value))
        elif key == "daemon/binary":
            self.binary_field.set_path(str(value))
        elif key == "daemon/datadir":
            self.datadir_field.set_path(str(value))

    def _on_theme_changed(self, index: int) -> None:
        """Stage a base theme choice and reset custom colors to its defaults."""
        if self._syncing or index < 0:
            return
        key = self.theme_combo.itemData(index)
        if not key:
            return
        self._draft_theme_key = str(key)
        self._draft_custom = {}
        self._refresh_color_buttons()
        self._update_theme_preview()
        self._mark_appearance_dirty()

    def _draft_theme(self) -> Theme:
        """Return the staged theme including unsaved custom colors."""
        base = THEMES.get(self._draft_theme_key, THEMES[THEME_ORDER[0]])
        return customize_theme(base, self._draft_custom)

    def _choose_color(self, token: str) -> None:
        """Open a color picker for one primary theme token."""
        current = QColor(self._draft_theme().color(token))
        title = "Цвет: " + self._token_label(token)
        chosen = QColorDialog.getColor(current, self, title)
        if not chosen.isValid():
            return
        self._draft_custom[token] = chosen.name()
        self._refresh_color_buttons()
        self._update_theme_preview()
        self._mark_appearance_dirty()

    def _reset_custom_colors(self) -> None:
        """Discard unsaved custom colors and restore the base palette."""
        if not self._draft_custom:
            return
        self._draft_custom = {}
        self._refresh_color_buttons()
        self._update_theme_preview()
        self._mark_appearance_dirty()

    def _token_label(self, token: str) -> str:
        """Return the Russian label for a primary color token."""
        return {
            "bg": "Фон",
            "sidebar": "Панель",
            "surface": "Карточки",
            "accent": "Акцент",
            "text": "Текст",
        }.get(token, token)

    def _refresh_color_buttons(self) -> None:
        """Paint color swatches with readable captions and warnings."""
        theme = self._draft_theme()
        for token, button in self._color_buttons.items():
            color = theme.color(token)
            caption = "#FFFFFF" if contrast_ratio(color, "#FFFFFF") > 2.2 else "#121212"
            button.setText(f"{self._token_label(token)}  {color.name()}")
            button.setStyleSheet(
                "QPushButton#ColorButton {"
                f" background: {color.name()}; color: {caption};"
                " border: 1px solid rgba(255, 255, 255, 40);"
                " border-radius: 7px; padding: 0 8px; font-weight: 600;"
                "}"
            )
            button.setToolTip(f"{self._token_label(token)}: {color.name()}")
        ratio = contrast_ratio(theme.color("text"), theme.color("bg"))
        if ratio < 4.5:
            self.color_warning.setText(
                f"Низкий контраст текста и фона ({ratio:.1f}:1). Проверьте читаемость."
            )
            self.color_warning.show()
        else:
            self.color_warning.hide()

    def _update_theme_preview(self) -> None:
        """Render a small color preview for the staged theme."""
        self.theme_preview.setPixmap(self._theme_pixmap(self._draft_theme()))

    def _theme_pixmap(self, theme: Theme) -> QPixmap:
        """Draw a compact theme preview card."""
        pixmap = QPixmap(220, 58)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor(theme.color("bg"))
        surface = QColor(theme.color("surface"))
        accent = QColor(theme.color("accent"))
        text = QColor(theme.color("text"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, 220, 58, 8, 8)
        painter.setBrush(surface)
        painter.drawRoundedRect(8, 8, 204, 42, 6, 6)
        painter.setBrush(accent)
        painter.drawRoundedRect(16, 16, 34, 26, 4, 4)
        painter.setBrush(text)
        painter.setOpacity(0.82)
        painter.drawRoundedRect(60, 18, 88, 4, 2, 2)
        painter.setOpacity(0.45)
        painter.drawRoundedRect(60, 28, 120, 3, 2, 2)
        painter.setOpacity(1.0)
        painter.setBrush(accent)
        painter.drawEllipse(178, 18, 10, 10)
        painter.end()
        return pixmap

    def _on_verbosity_changed(self, value: str) -> None:
        """Stage the information density level."""
        if self._syncing:
            return
        level = int(value)
        self.verbosity_hint.setText(VERBOSITY_HINTS.get(level, ""))
        self._mark_appearance_dirty()

    def _on_scale_changed(self, value: int) -> None:
        """Stage the interface scale."""
        self.scale_value.setText(f"{value} %")
        if not self._syncing:
            self._mark_appearance_dirty()

    def _on_speed_changed(self, value: int) -> None:
        """Stage the animation speed."""
        self.speed_value.setText(f"{value} %")
        if not self._syncing:
            self._mark_appearance_dirty()

    def _on_animation_toggled(self, checked: bool) -> None:
        """Enable dependent motion controls and stage the change."""
        self.hover_box.setEnabled(checked)
        self.transitions_box.setEnabled(checked)
        self.speed_slider.setEnabled(checked)
        if not self._syncing:
            self._mark_appearance_dirty()

    def _mark_appearance_dirty(self, *_args: object) -> None:
        """Enable Apply after the first unsaved appearance change."""
        if self._syncing:
            return
        self._appearance_dirty = True
        self._set_appearance_status("Есть непримененные изменения", dirty=True)

    def _set_appearance_status(self, text: str, dirty: bool) -> None:
        """Update the Apply row without changing the stored settings."""
        self.appearance_status.setText(text)
        self.appearance_status.setObjectName("WarningText" if dirty else "HintText")
        self.appearance_status.style().unpolish(self.appearance_status)
        self.appearance_status.style().polish(self.appearance_status)
        self.apply_button.setEnabled(dirty)

    def _apply_appearance(self) -> None:
        """Commit the whole appearance draft in one grouped update."""
        values = {
            "appearance/theme": self._draft_theme_key,
            "appearance/verbosity": int(self.verbosity_control.value()),
            "appearance/font_scale": self.scale_slider.value(),
            "appearance/animations": self.animations_box.isChecked(),
            "appearance/hover_effects": self.hover_box.isChecked(),
            "appearance/page_transitions": self.transitions_box.isChecked(),
            "appearance/animation_speed": self.speed_slider.value(),
            "appearance/custom_colors": json.dumps(self._draft_custom, sort_keys=True),
        }
        self.settings.set_many(values)
        self._appearance_dirty = False
        self._set_appearance_status("Применено", dirty=False)
        self.statusMessage.emit("Оформление применено", 2500)

    def _on_dim_changed(self, value: int) -> None:
        """Persist the media dim level."""
        self.dim_value.setText(f"{value} %")
        if not self._syncing:
            self.settings.media_dim = value

    def _on_blur_changed(self, value: int) -> None:
        """Persist the media blur radius."""
        self.blur_value.setText(str(value))
        if not self._syncing:
            self.settings.media_blur = value

    def _on_volume_changed(self, value: int) -> None:
        """Persist the sound volume."""
        self.volume_value.setText(f"{value} %")
        if not self._syncing:
            self.settings.sound_volume = value

    def _on_media_path(self, path: str) -> None:
        """Store a chosen background file and enable the backdrop."""
        if self._syncing:
            return
        self.settings.media_path = path
        if path:
            self.media_enabled_box.setChecked(True)
            self.settings.media_enabled = True

    def _clear_media(self) -> None:
        """Remove the custom background."""
        self.media_path.set_path("")
        self.settings.media_path = ""
        self.media_enabled_box.setChecked(False)
        self.settings.media_enabled = False
        self.statusMessage.emit("Медиафон отключен", 3000)

    def _save_connection(self) -> None:
        """Persist proxy credentials and notify the shell."""
        if self._syncing:
            return
        self.settings.set("connection/proxy_url", self.proxy_edit.text().strip())
        self.settings.set("connection/proxy_user", self.user_edit.text().strip())
        self.settings.set("connection/proxy_password", self.password_edit.text())
        self.connectionChanged.emit()

    def _test_connection(self) -> None:
        """Probe the configured proxy asynchronously."""
        url = self.proxy_edit.text().strip() or str(
            self.settings.get("connection/proxy_url")
        )
        if not url:
            self.connection_status.setText("Укажите адрес прокси")
            return
        user = self.user_edit.text().strip()
        password = self.password_edit.text()
        timeout = self.timeout_spin.value()
        self.test_button.setEnabled(False)
        self.test_spinner.start()
        self.connection_status.setText("Проверка...")
        run_async(
            lambda: self._probe(url, user, password, timeout),
            self._on_probe_ok,
            self._on_probe_failed,
            self._on_probe_done,
        )

    @staticmethod
    def _probe(url: str, user: str, password: str, timeout: int) -> tuple[dict, int]:
        """Run getinfo against a temporary client and measure latency."""
        started = time.monotonic()
        client = RPCClient(url, user, password, timeout=timeout)
        try:
            info = client.call("getinfo")
        finally:
            client.close()
        elapsed = int((time.monotonic() - started) * 1000)
        return dict(info or {}), elapsed

    def _on_probe_ok(self, payload: tuple[dict, int]) -> None:
        """Show block height and latency after a successful probe."""
        info, elapsed = payload
        blocks = info.get("blocks", "-")
        connections = info.get("connections", "-")
        self.connection_status.setText(
            f"Подключено: блок {blocks}, соединений {connections}, {elapsed} ms"
        )
        self.connection_status.setStyleSheet(
            f"color: {self.tokens.get('positive', '#4ED19E')};"
        )

    def _on_probe_failed(self, error: object) -> None:
        """Show a readable connection error."""
        self.connection_status.setText(humanize_error(error))
        self.connection_status.setStyleSheet(
            f"color: {self.tokens.get('negative', '#FF7070')};"
        )

    def _on_probe_done(self) -> None:
        """Restore the test button."""
        self.test_button.setEnabled(True)
        self.test_spinner.stop()

    def _test_sound(self) -> None:
        """Play a synthesized success sound."""
        if self._sound_player is None:
            self._sound_player = SoundPlayer(self.settings, self)
        self._sound_player.play("success")
        self.statusMessage.emit("Тестовый звук отправлен", 2000)

    def _open_project_folder(self) -> None:
        """Open the project root in the system file manager."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.root)))

    def _show_about(self) -> None:
        """Display a short about dialog."""
        from ... import __app_name__, __version__

        box = QMessageBox(self)
        box.setWindowTitle("О программе")
        box.setText(
            f"{__app_name__} {__version__}\n\n"
            "Графический интерфейс кошелька Phoenix на базе NovaCoin.\n"
            "Демон novacoind запускается под капотом, "
            "обмен идет через локальный прокси."
        )
        logo = brand_logo(72)
        if not logo.isNull():
            box.setIconPixmap(logo)
        box.exec()

    def _reset_settings(self) -> None:
        """Restore defaults after an explicit confirmation."""
        answer = QMessageBox.question(
            self,
            "Сброс настроек",
            "Вернуть все предпочтения к значениям по умолчанию?\n"
            "Данные кошелька и история операций не затрагиваются.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings.reset_defaults()
        self.settings.bootstrap(self.config, force=True)
        self._sync_from_settings()
        self.themes.apply(self.settings.theme)
        self.connectionChanged.emit()
        self.statusMessage.emit("Настройки сброшены", 4000)

    def set_daemon_status(self, text: str, color: str = "") -> None:
        """Update the daemon state label from the shell."""
        self.daemon_status.setText(text)
        if color:
            self.daemon_status.setStyleSheet(f"color: {color};")

    def apply_theme(self) -> None:
        """Recolor dynamic icons, previews and status labels."""
        muted = self.tokens.get("muted", "#A7B1C2")
        self.test_button.setIcon(icon("link", muted, 15))
        self.restart_daemon_button.setIcon(icon("refresh", muted, 15))
        self.connection_status.setStyleSheet("")
        self.daemon_status.setStyleSheet("")
        self._update_theme_preview()
