"""Application entry point for the Phoenix wallet."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import __app_name__, __version__
from .core.config import load_project_config
from .demo import DemoService
from .rpc.client import RPCClient
from .rpc.service import WalletService
from .settings import Settings
from .ui.main_window import MainWindow
from .ui.widgets.icons import app_icon
from .ui.widgets.theme import THEME_ORDER, ThemeManager

LOGGER = logging.getLogger("phoenix")


def build_parser() -> argparse.ArgumentParser:
    """Create the command line parser."""
    parser = argparse.ArgumentParser(
        prog="phoenix-wallet",
        description="Phoenix Wallet - графический клиент кошелька Phoenix",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="запустить с локальными демонстрационными данными без прокси и демона",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="каталог проекта Phoenix (по умолчанию определяется автоматически)",
    )
    parser.add_argument(
        "--theme",
        choices=THEME_ORDER,
        default=None,
        help="принудительно выбрать тему оформления",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="URL локального прокси, например http://127.0.0.1:16666",
    )
    parser.add_argument(
        "--reset-settings",
        action="store_true",
        help="сбросить сохраненные настройки интерфейса",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="уровень журналирования",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} {__version__}",
    )
    return parser


def setup_logging(level: str) -> Path | None:
    """Configure a rotating log next to the user's application data."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    log_path: Path | None = None
    data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if data_dir:
        folder = Path(data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / "phoenix-wallet.log"
        handler = RotatingFileHandler(
            log_path, maxBytes=1_500_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return log_path


def install_exception_hook() -> None:
    """Log unexpected exceptions and show them without hiding the window."""

    def handle(exc_type, exc_value, exc_traceback) -> None:
        """Handle one uncaught exception."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        LOGGER.critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Непредвиденная ошибка")
        box.setText("Приложение столкнулось с ошибкой, подробности записаны в журнал.")
        box.setInformativeText(str(exc_value)[:500])
        box.exec()

    sys.excepthook = handle


def main(argv: list[str] | None = None) -> int:
    """Create the application, connect it to the proxy and run the event loop."""
    args = build_parser().parse_args(argv)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(__app_name__)
    app.setOrganizationName("Phoenix")
    app.setApplicationVersion(__version__)
    QApplication.setDesktopFileName("phoenix-wallet")

    log_path = setup_logging(args.log_level)
    if log_path is not None:
        LOGGER.info("Log file: %s", log_path)
    install_exception_hook()

    project = load_project_config(args.project)
    settings = Settings()
    if args.reset_settings:
        settings.reset()
    settings.bootstrap(project)
    if args.proxy:
        settings.set("connection/proxy_url", args.proxy)
    if args.theme:
        settings.set("appearance/theme", args.theme)

    themes = ThemeManager(settings, app)
    themes.apply(settings.theme)
    app.setWindowIcon(app_icon(themes.theme))

    if args.demo:
        service: WalletService | DemoService = DemoService()
        LOGGER.info("Starting in demo mode")
    else:
        url, user, password = settings.effective_proxy()
        client = RPCClient(url, user, password, timeout=settings.timeout_seconds)
        service = WalletService(client)
        LOGGER.info("Proxy endpoint: %s", url)

    window = MainWindow(
        project,
        settings,
        service,
        themes,
        demo=args.demo,
    )
    window.show()
    app.aboutToQuit.connect(settings.sync)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
