"""Small QRunnable helpers for off-main-thread wallet calls."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class TaskSignals(QObject):
    """Signals emitted by a background task."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(object)
    done = pyqtSignal()


class Task(QRunnable):
    """Run one callable in the global thread pool."""

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Initialize the Task instance."""
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        """Execute the callable and translate exceptions into signals."""
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - background boundary
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


_ACTIVE: set[Task] = set()


def run_async(
    function: Callable[..., Any],
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    on_done: Callable[[], None] | None = None,
    *args: Any,
    **kwargs: Any,
) -> Task:
    """Start a callable in the global pool and keep it alive until done."""
    task = Task(function, *args, **kwargs)
    if on_success is not None:
        task.signals.finished.connect(on_success)
    if on_error is not None:
        task.signals.failed.connect(on_error)
    if on_done is not None:
        task.signals.done.connect(on_done)
    _ACTIVE.add(task)
    task.signals.done.connect(lambda: _ACTIVE.discard(task))
    QThreadPool.globalInstance().start(task)
    return task
