"""Lifecycle management for the local Phoenix HTTP proxy.

The proxy is a normal Python process, but users should never have to open a
terminal for it.  This controller starts ``main.py`` hidden, feeds the
wallet password through the environment, waits until the HTTP endpoint
answers, and stops the process again when the wallet closes.
"""

from __future__ import annotations

import base64
import http.client
import os
import re
import threading
import socket
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from .config import ProjectConfig
from ..settings import Settings

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_STOPPING = "stopping"
STATE_MISSING = "missing"
STATE_FAILED = "failed"

PASSWORD_ENV = "PHOENIX_WALLET_PASSWORD"


def backend_python(project: ProjectConfig) -> Path | None:
    """Return the interpreter of the backend virtual environment."""
    candidates = [
        project.root / ".venv-backend" / "bin" / "python",
        project.root / ".venv-backend" / "Scripts" / "python.exe",
        project.root / ".venv-backend" / "Scripts" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def proxy_arguments(project: ProjectConfig) -> list[str]:
    """Return arguments for launching the proxy entry point."""
    return ["main.py"]


class ProxyProcess(QObject):
    """Start, probe and stop the local Flask proxy."""

    stateChanged = pyqtSignal(str)
    ready = pyqtSignal(bool)
    failed = pyqtSignal(str)
    stopped = pyqtSignal(int)
    output = pyqtSignal(str)
    probe_result = pyqtSignal(bool, str, str)

    def __init__(
        self, settings: Settings, project: ProjectConfig, parent: QObject | None = None
    ) -> None:
        """Initialize the ProxyProcess instance."""
        super().__init__(parent)
        self._settings = settings
        self._project = project
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.errorOccurred.connect(self._on_process_error)
        self._process.finished.connect(self._on_finished)
        self._state = STATE_STOPPED
        self._owned = False
        self._stopping = False
        self._buffer = ""
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._on_timeout)
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(700)
        self._probe_timer.timeout.connect(self._probe)
        self._probe_thread: threading.Thread | None = None
        self.probe_result.connect(self._on_probe_result)

    @property
    def state(self) -> str:
        """Return the current lifecycle state."""
        return self._state

    @property
    def owned(self) -> bool:
        """Return whether this window owns the proxy process."""
        return self._owned

    @property
    def recent_output(self) -> str:
        """Return the tail of the proxy console output for diagnostics."""
        return self._buffer[-8000:]

    @property
    def state_label(self) -> str:
        """Return a human-readable state label."""
        return {
            STATE_STOPPED: "Прокси остановлен",
            STATE_STARTING: "Запуск прокси",
            STATE_RUNNING: "Прокси работает",
            STATE_STOPPING: "Остановка прокси",
            STATE_MISSING: "Прокси не найден",
            STATE_FAILED: "Ошибка прокси",
        }.get(self._state, self._state)

    def _set_state(self, state: str) -> None:
        """Update and broadcast the lifecycle state."""
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _endpoint(self) -> tuple[str, str, str]:
        """Return proxy URL, user and password from GUI settings."""
        return self._settings.effective_proxy()

    def port_open(self) -> bool:
        """Return whether something already serves the proxy port."""
        url = self._endpoint()[0]
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 16666
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except OSError:
            return False

    def start(self, password: str = "") -> None:
        """Start the proxy, or attach to an already running one."""
        if self._state in {STATE_STARTING, STATE_RUNNING, STATE_STOPPING}:
            return
        if self.port_open():
            # A listening socket does not prove that the proxy is healthy.
            # Probe the HTTP endpoint before attaching to a stale process.
            self._owned = False
            self._buffer = ""
            self._set_state(STATE_STARTING)
            self._deadline.start(6000)
            self._probe_timer.start()
            QTimer.singleShot(80, self._probe)
            return
        python = backend_python(self._project)
        script = self._project.root / "main.py"
        if python is None:
            self._set_state(STATE_MISSING)
            self.failed.emit(
                "Не найден интерпретатор прокси .venv-backend. "
                "Установите зависимости прокси и повторите запуск."
            )
            return
        if not script.is_file():
            self._set_state(STATE_MISSING)
            self.failed.emit("Не найден main.py прокси.")
            return
        self._owned = True
        self._stopping = False
        self._buffer = ""
        self._set_state(STATE_STARTING)
        environment = self._process.processEnvironment()
        environment.insert(PASSWORD_ENV, password)
        self._process.setProcessEnvironment(environment)
        self._process.setWorkingDirectory(str(self._project.root))
        self._process.start(str(python), proxy_arguments(self._project))
        if not self._process.waitForStarted(4000):
            self._set_state(STATE_FAILED)
            self.failed.emit(
                f"Не удалось запустить прокси: {self._process.errorString()}"
            )
            return
        self._deadline.start(30000)
        self._probe_timer.start()
        QTimer.singleShot(250, self._probe)

    def stop(self) -> None:
        """Stop the proxy if this window owns it; external proxies stay up."""
        self._probe_timer.stop()
        self._deadline.stop()
        if not self._owned or self._process.state() == QProcess.ProcessState.NotRunning:
            self._set_state(STATE_STOPPED)
            return
        self._stopping = True
        self._set_state(STATE_STOPPING)
        self._process.terminate()
        if not self._process.waitForFinished(2500):
            self._process.kill()
            self._process.waitForFinished(1200)

    def restart(self, password: str = "") -> None:
        """Stop and start the proxy again."""
        self.stop()
        QTimer.singleShot(350, lambda: self.start(password))

    def _probe(self) -> None:
        """Ask the proxy for getinfo until it answers or the deadline expires."""
        if self._state != STATE_STARTING or self._probe_thread is not None:
            return
        url, user, password = self._endpoint()
        self._probe_thread = threading.Thread(
            target=self._probe_worker,
            args=(url, user, password),
            daemon=True,
            name="phoenix-proxy-probe",
        )
        self._probe_thread.start()

    def _probe_worker(self, url: str, user: str, password: str) -> None:
        """Perform one short HTTP probe without blocking the GUI thread."""
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 16666
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "Connection": "close",
        }
        # The health route never touches the daemon, so a busy node cannot
        # make a healthy proxy look broken.
        connection = http.client.HTTPConnection(host, port, timeout=1.6)
        try:
            connection.request("GET", "/health", headers=headers)
            response = connection.getresponse()
            response.read(256)
            self._emit_probe(True, str(response.status))
        except (OSError, http.client.HTTPException) as exc:
            self._emit_probe(False, "", type(exc).__name__)
        finally:
            connection.close()

    def _emit_probe(self, alive: bool, status: str, detail: str = "") -> None:
        """Emit a probe result, tolerating a window closed mid-probe."""
        try:
            self.probe_result.emit(alive, status, detail)
        except RuntimeError:
            pass

    def _on_probe_result(self, alive: bool, status: str, detail: str) -> None:
        """Handle one finished proxy readiness probe on the GUI thread."""
        self._probe_thread = None
        if self._state != STATE_STARTING:
            return
        if alive and status == "401":
            self._probe_timer.stop()
            self._deadline.stop()
            self._set_state(STATE_FAILED)
            self.failed.emit(
                "Прокси отклонил логин или пароль. Проверьте данные "
                "подключения в настройках."
            )
        elif alive:
            # Any HTTP response means the proxy is alive. A 5xx caused by
            # the daemon is reported by the normal connection check.
            self._probe_timer.stop()
            self._deadline.stop()
            self._set_state(STATE_RUNNING)
            self.ready.emit(not self._owned)
        # Connection refused/timeouts are retried until the deadline.

    def _on_timeout(self) -> None:
        """Report a proxy that did not start in time."""
        self._probe_timer.stop()
        if self._state == STATE_STARTING:
            self._set_state(STATE_FAILED)
            tail = self._buffer.strip().splitlines()[-4:]
            detail = " | ".join(tail)
            if self._owned:
                message = (
                    "Прокси не ответил вовремя. Проверьте config.toml и пароль "
                    f"хранилища ключей. {detail}"
                )
            else:
                message = (
                    "Порт прокси занят, но HTTP-прокси не отвечает. "
                    "Закройте старый процесс прокси или перезапустите его. "
                    f"{detail}"
                )
            self.failed.emit(message.strip())

    def _read_output(self) -> None:
        """Collect process output for diagnostics."""
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        if not chunk:
            return
        chunk = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", chunk)
        self._buffer = (self._buffer + chunk)[-16000:]
        self.output.emit(chunk)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        """React to a proxy process that cannot start."""
        if self._stopping:
            return
        if error in {
            QProcess.ProcessError.FailedToStart,
            QProcess.ProcessError.Crashed,
        }:
            self._probe_timer.stop()
            self._deadline.stop()
            self._set_state(STATE_FAILED)
            self.failed.emit(f"Ошибка процесса прокси: {self._process.errorString()}")

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        """Report an unexpected proxy exit with a useful tail."""
        self._probe_timer.stop()
        self._deadline.stop()
        was_stopping = self._stopping
        self._stopping = False
        self._owned = False
        self._set_state(STATE_STOPPED)
        self.stopped.emit(code)
        if was_stopping:
            return
        tail = self._buffer.strip().splitlines()[-5:]
        detail = " | ".join(tail)
        if any(
            marker in detail
            for marker in (
                "Invalid password",
                "MAC check failed",
                "Wrong password",
                "Wrong password or corrupted file",
            )
        ):
            detail = "Неверный пароль хранилища ключей."
        self.failed.emit(f"Прокси завершился с кодом {code}: {detail}")
