"""Render documentation screenshots from the demo wallet.

Usage:
    QT_QPA_PLATFORM=offscreen python tools/screenshot_gui.py --output docs/screenshots

The script never touches the user's real settings or wallet database.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from phoenix_gui.core.config import load_project_config  # noqa: E402
from phoenix_gui.demo import DemoService  # noqa: E402
from phoenix_gui.settings import Settings  # noqa: E402
from phoenix_gui.ui.main_window import MainWindow  # noqa: E402
from phoenix_gui.ui.widgets.theme import THEME_ORDER, ThemeManager  # noqa: E402

PAGES = (
    "overview",
    "send",
    "receive",
    "transactions",
    "coins",
    "storage",
    "analytics",
    "console",
    "settings",
)


def build_parser() -> argparse.ArgumentParser:
    """Create the command line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=880)
    parser.add_argument("--wait", type=int, default=650, help="milliseconds per page")
    parser.add_argument(
        "--theme",
        choices=THEME_ORDER,
        default="phoenix",
        help="theme used for this capture",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="file name suffix, for example -light",
    )
    parser.add_argument(
        "--language",
        default="ru",
        help="interface language code for the capture",
    )
    parser.add_argument(
        "--pages",
        default=",".join(PAGES),
        help="comma separated page ids to capture",
    )
    return parser


def run() -> int:
    """Build the window and save one screenshot per page."""
    args = build_parser().parse_args()
    requested = [item.strip() for item in args.pages.split(",") if item.strip()]
    unknown = [item for item in requested if item not in PAGES]
    if unknown:
        print(f"unknown pages: {', '.join(unknown)}", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    project = load_project_config(Path.cwd())

    with tempfile.TemporaryDirectory(prefix="phoenix-shot-") as temporary:
        settings = Settings(Path(temporary) / "settings.ini")
        settings.set("behavior/refresh_seconds", 600)
        settings.set("appearance/language", args.language)
        themes = ThemeManager(settings, app)
        themes.apply(args.theme)
        window = MainWindow(project, settings, DemoService(), themes, demo=True)
        window.resize(args.width, args.height)
        window.show()
        QTest.qWait(1400)
        for page_id in requested:
            window.navigate(page_id)
            page = window.current_page
            for _ in range(40):
                if page is not None and not getattr(page, "_refreshing", False):
                    break
                QTest.qWait(100)
            QTest.qWait(args.wait)
            target = args.output / f"{page_id}{args.suffix}.png"
            window.grab().save(str(target))
            print(f"saved {target}")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
