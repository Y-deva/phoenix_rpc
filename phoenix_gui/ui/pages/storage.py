"""PStore page: upload, download and cancel public file transactions."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from ...core.formatting import format_bytes
from ...core.tasks import run_async
from ..widgets.card import Card
from ..widgets.fields import CopyLineEdit, PathField, SegmentedControl
from ..widgets.icons import icon
from ..widgets.progress import TaskProgress
from .base import ScrollPage

FILE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
EXTENSION_PATTERN = re.compile(r"^[A-Za-z0-9]{1,16}$")


class StoragePage(ScrollPage):
    """Public file storage backed by pstore, pload and pcancel."""

    page_id = "storage"
    page_title = "Хранилище"
    page_subtitle = "Публичные файлы в блокчейне через pstore"
    auto_refresh = False

    def __init__(self, context, parent: QWidget | None = None) -> None:
        """Initialize the StoragePage instance."""
        super().__init__(context, parent)
        self._busy_upload = False
        self._busy_download = False
        self._busy_cancel = False
        self._last_path = ""
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        """Build upload, download and cancellation panels."""
        intro = Card(padding=16, spacing=8, object_name="SoftCard")
        title = QLabel("Публичное хранилище")
        title.setObjectName("CardTitle")
        intro.add(title)
        text = QLabel(
            "Файл записывается в публичную цепочку Novacoin серией транзакций. "
            "Для получения понадобится id графа. Отмена возможна только до "
            "подтверждения ожидающих транзакций."
        )
        text.setObjectName("Muted")
        text.setWordWrap(True)
        intro.add(text)
        self.body.addWidget(intro)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_upload_card(), 1)
        columns.addWidget(self._build_download_card(), 1)
        self.body.addLayout(columns)
        self.body.addWidget(self._build_cancel_card())
        self.add_stretch()

    def _build_upload_card(self) -> Card:
        """Create the file-or-link upload form."""
        card = Card(padding=18, spacing=10)
        title = QLabel("Загрузить файл")
        title.setObjectName("CardTitle")
        card.add(title)

        self.source_control = SegmentedControl()
        self.source_control.add_segment(
            "file", "Файл", "Выбрать файл на этом компьютере"
        )
        self.source_control.add_segment("url", "Ссылка", "Загрузить файл по HTTP(S)")
        self.source_control.valueChanged.connect(self._on_source_mode)
        card.add(self.source_control)

        self.file_field = PathField("file", "Выбрать файл")
        self.url_field = QLineEdit()
        self.url_field.setPlaceholderText("https://example.com/file.zip")
        self.url_field.setToolTip("Прямая ссылка на файл по HTTP или HTTPS")
        self.url_field.setClearButtonEnabled(True)
        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self.file_field)
        self.source_stack.addWidget(self.url_field)
        card.add(self.source_stack)

        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Комментарий к файлу, необязательно")
        self.comment_input.setMaxLength(120)
        self.comment_input.setToolTip("Короткое описание, сохраняется в базе прокси")
        card.add(self.comment_input)

        self.upload_progress = TaskProgress()
        self.upload_progress.setVisible(False)
        card.add(self.upload_progress)

        self.upload_button = QPushButton("Загрузить в pstore")
        self.upload_button.setObjectName("AccentButton")
        self.upload_button.setMinimumHeight(40)
        self.upload_button.setToolTip("Создать цепочку pstore для выбранного источника")
        self.upload_button.clicked.connect(self._start_upload)
        card.add(self.upload_button)

        self.upload_status = QLabel("")
        self.upload_status.setObjectName("HintText")
        self.upload_status.setWordWrap(True)
        card.add(self.upload_status)

        self.file_id_output = CopyLineEdit()
        self.file_id_output.setPlaceholderText("id графа появится после загрузки")
        self.file_id_output.setVisible(False)
        self.file_id_output.copied.connect(
            lambda _text: self.notify("id графа скопирован", 2500)
        )
        card.add(self.file_id_output)

        self.upload_details = QLabel("")
        self.upload_details.setObjectName("Faint")
        self.upload_details.setWordWrap(True)
        card.add(self.upload_details)
        return card

    def _build_download_card(self) -> Card:
        """Create the id-and-extension download form."""
        card = Card(padding=18, spacing=10)
        title = QLabel("Получить файл")
        title.setObjectName("CardTitle")
        card.add(title)

        self.file_id_input = QLineEdit()
        self.file_id_input.setPlaceholderText("id графа, 64 шестнадцатеричных символа")
        self.file_id_input.setClearButtonEnabled(True)
        self.file_id_input.setToolTip("Идентификатор, который вернул pstore")
        card.add(self.file_id_input)

        extension_row = QHBoxLayout()
        extension_caption = QLabel("Расширение")
        extension_caption.setObjectName("Muted")
        self.extension_input = QLineEdit("bin")
        self.extension_input.setMaxLength(16)
        self.extension_input.setFixedWidth(100)
        self.extension_input.setToolTip("Расширение без точки, например zip или pdf")
        extension_row.addWidget(extension_caption)
        extension_row.addWidget(self.extension_input)
        extension_row.addStretch(1)
        card.add_layout(extension_row)

        self.download_progress = TaskProgress()
        self.download_progress.setVisible(False)
        card.add(self.download_progress)

        self.download_button = QPushButton("Скачать из pstore")
        self.download_button.setObjectName("AccentButton")
        self.download_button.setMinimumHeight(40)
        self.download_button.setToolTip(
            "Собрать файл из цепочки и сохранить в загрузки"
        )
        self.download_button.clicked.connect(self._start_download)
        card.add(self.download_button)

        self.download_status = QLabel("")
        self.download_status.setObjectName("HintText")
        self.download_status.setWordWrap(True)
        card.add(self.download_status)

        self.download_result = CopyLineEdit()
        self.download_result.setPlaceholderText("Путь к сохраненному файлу")
        self.download_result.setVisible(False)
        card.add(self.download_result)

        self.open_folder_button = QPushButton("Открыть папку")
        self.open_folder_button.setObjectName("GhostButton")
        self.open_folder_button.setIcon(
            icon("folder", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.open_folder_button.setToolTip("Открыть папку с загруженным файлом")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_folder)
        card.add(self.open_folder_button, 0)
        return card

    def _build_cancel_card(self) -> Card:
        """Create the pending pstore cancellation panel."""
        card = Card(padding=16, spacing=8, object_name="SoftCard")
        title = QLabel("Ожидающие транзакции")
        title.setObjectName("CardTitle")
        card.add(title)
        hint = QLabel(
            "pcancel удаляет только неподтвержденные pstore-транзакции из "
            "приоритетной очереди и заново закрепляет якорь цепочки."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        card.add(hint)
        self.cancel_button = QPushButton("Отменить ожидающие")
        self.cancel_button.setObjectName("GhostButton")
        self.cancel_button.setIcon(
            icon("trash", self.tokens.get("negative", "#FF7070"), 16)
        )
        self.cancel_button.setToolTip("Удалить неподтвержденные pstore-транзакции")
        self.cancel_button.clicked.connect(self._cancel_pending)
        card.add(self.cancel_button, 0)
        return card

    def apply_theme(self) -> None:
        """Refresh icon tints after a theme change."""
        if not hasattr(self, "upload_button"):
            return
        self.upload_button.setIcon(
            icon("upload", self.tokens.get("accent_text", "#1A1208"), 16)
        )
        self.download_button.setIcon(
            icon("download", self.tokens.get("accent_text", "#1A1208"), 16)
        )
        self.open_folder_button.setIcon(
            icon("folder", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.cancel_button.setIcon(
            icon("trash", self.tokens.get("negative", "#FF7070"), 16)
        )
        self.file_field.browse.setIcon(
            icon("folder", self.tokens.get("muted", "#A7B1C2"), 17)
        )
        self.file_id_output.set_icon_color(self.tokens.get("muted", "#A7B1C2"))
        self.download_result.set_icon_color(self.tokens.get("muted", "#A7B1C2"))

    def _on_source_mode(self, mode: str) -> None:
        """Switch between a local file and a remote URL."""
        self.source_stack.setCurrentIndex(0 if mode == "file" else 1)

    def _source(self) -> str:
        """Return and validate the selected source."""
        mode = self.source_control.value()
        if mode == "file":
            source = self.file_field.path()
            if not source:
                raise ValueError("Выберите файл для загрузки")
            if not Path(source).expanduser().is_file():
                raise ValueError("Файл не найден")
            return source
        source = self.url_field.text().strip()
        if not source:
            raise ValueError("Введите ссылку на файл")
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ссылка должна начинаться с http:// или https://")
        return source

    def _set_upload_busy(self, busy: bool) -> None:
        """Toggle upload controls and the progress panel."""
        self._busy_upload = busy
        self.upload_button.setEnabled(not busy)
        self.upload_progress.setVisible(busy)
        if busy:
            self.upload_progress.set_busy("Загрузка файла в pstore")
            self.busyChanged.emit(True)

    def _start_upload(self) -> None:
        """Validate the form and start a pstore request."""
        if self._busy_upload:
            return
        try:
            source = self._source()
        except ValueError as exc:
            self.upload_status.setText(str(exc))
            self.upload_status.setProperty("error", True)
            self._refresh_style(self.upload_status)
            return
        self.upload_status.setProperty("error", False)
        self._refresh_style(self.upload_status)
        self.upload_status.setText("Подготовка к загрузке...")
        self._set_upload_busy(True)
        run_async(
            self.service.pstore,
            self._upload_done,
            self._upload_failed,
            self._upload_finished,
            source,
            self.comment_input.text().strip(),
        )

    def _upload_done(self, result: object) -> None:
        """Show the returned graph id and transaction metadata."""
        data = result if isinstance(result, dict) else {}
        file_id = str(data.get("file_id", ""))
        if not file_id:
            self._upload_failed(ValueError("Прокси не вернул id графа"))
            return
        self.file_id_output.setText(file_id)
        self.file_id_output.setVisible(True)
        self.file_id_input.setText(file_id)
        size = int(data.get("size", 0) or 0)
        tx_count = int(data.get("tx_count", 0) or 0)
        self.upload_details.setText(
            f"Транзакций: {tx_count}. Размер: {format_bytes(size)}. "
            f"Якорь: {data.get('anchor') or '-'}"
        )
        self.upload_status.setText("Файл поставлен в очередь pstore.")
        self.upload_progress.finish("Готово")
        self.notify("Файл загружен в pstore", 4000)

    def _upload_failed(self, error: object) -> None:
        """Report an upload error without hiding the form."""
        self.upload_status.setText(f"Ошибка: {error}")
        self.upload_status.setProperty("error", True)
        self._refresh_style(self.upload_status)
        self.upload_progress.finish("Ошибка")
        self.errorRaised.emit(str(error))

    def _upload_finished(self) -> None:
        """Release upload controls."""
        self._busy_upload = False
        self.upload_button.setEnabled(True)
        self.busyChanged.emit(False)

    def _start_download(self) -> None:
        """Validate the id and start a pload request."""
        if self._busy_download:
            return
        file_id = self.file_id_input.text().strip()
        if not FILE_ID_PATTERN.fullmatch(file_id):
            self.download_status.setText(
                "id должен состоять из 64 шестнадцатеричных символов"
            )
            self.download_status.setProperty("error", True)
            self._refresh_style(self.download_status)
            return
        extension = self.extension_input.text().strip().lstrip(".")
        if not EXTENSION_PATTERN.fullmatch(extension):
            self.download_status.setText(
                "Расширение: буквы и цифры, не длиннее 16 символов"
            )
            self.download_status.setProperty("error", True)
            self._refresh_style(self.download_status)
            return
        self.download_status.setProperty("error", False)
        self._refresh_style(self.download_status)
        self.download_status.setText("Сборка файла из цепочки...")
        self._busy_download = True
        self.download_button.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_progress.set_busy("Скачивание из pstore")
        self.busyChanged.emit(True)
        run_async(
            self.service.pload,
            self._download_done,
            self._download_failed,
            self._download_finished,
            file_id.lower(),
            extension,
        )

    def _download_done(self, result: object) -> None:
        """Show the path returned by pload."""
        data = result if isinstance(result, dict) else {}
        path = str(data.get("path", ""))
        if not path:
            self._download_failed(ValueError("Прокси не вернул путь к файлу"))
            return
        self._last_path = path
        self.download_result.setText(path)
        self.download_result.setVisible(True)
        self.open_folder_button.setVisible(True)
        self.download_status.setText(
            f"Файл сохранен: {format_bytes(int(data.get('size', 0) or 0))}"
        )
        self.download_progress.finish("Готово")
        self.notify("Файл получен из pstore", 4000)

    def _download_failed(self, error: object) -> None:
        """Report a download error."""
        self.download_status.setText(f"Ошибка: {error}")
        self.download_status.setProperty("error", True)
        self._refresh_style(self.download_status)
        self.download_progress.finish("Ошибка")
        self.errorRaised.emit(str(error))

    def _download_finished(self) -> None:
        """Release download controls."""
        self._busy_download = False
        self.download_button.setEnabled(True)
        self.busyChanged.emit(False)

    def _open_folder(self) -> None:
        """Open the directory containing the downloaded file."""
        if not self._last_path:
            return
        folder = Path(self._last_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _cancel_pending(self) -> None:
        """Confirm and call pcancel."""
        if self._busy_cancel:
            return
        answer = QMessageBox.question(
            self,
            "Отменить pstore",
            "Удалить все неподтвержденные pstore-транзакции из очереди? "
            "Уже подтвержденные транзакции останутся в блокчейне.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy_cancel = True
        self.cancel_button.setEnabled(False)
        self.busyChanged.emit(True)
        run_async(
            self.service.pcancel,
            self._cancel_done,
            self._cancel_failed,
            self._cancel_finished,
        )

    def _cancel_done(self, result: object) -> None:
        """Report how many queued transactions were removed."""
        data = result if isinstance(result, dict) else {}
        count = int(data.get("cancelled", 0) or 0)
        self.notify(f"Отменено транзакций: {count}", 4000)

    def _cancel_failed(self, error: object) -> None:
        """Report a cancellation error."""
        self.errorRaised.emit(str(error))

    def _cancel_finished(self) -> None:
        """Release the cancel button."""
        self._busy_cancel = False
        self.cancel_button.setEnabled(True)
        self.busyChanged.emit(False)

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        """Repolish a widget after an error property change."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
