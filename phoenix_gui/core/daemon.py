"""Lifecycle management for the bundled NovaCoin daemon.

The GUI owns ``novacoind`` when it starts it: the process runs in the
foreground, its output is captured, and it is stopped when the wallet
closes. If a daemon is already listening on the RPC port, the GUI leaves
it alone and simply connects to it.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import socket
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QProcess, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .config import ENV_NOVACOIND, ProjectConfig
from ..settings import Settings

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_STOPPING = "stopping"
STATE_MISSING = "missing"
STATE_FAILED = "failed"


def daemon_executable_name() -> str:
    """Return the platform-specific daemon file name."""
    return "novacoind.exe" if os.name == "nt" else "novacoind"


def discover_daemon(
    project: ProjectConfig,
    configured: str = "",
    environment: dict[str, str] | None = None,
) -> Path | None:
    """Find the daemon binary in the configured and conventional places."""
    env = environment if environment is not None else os.environ
    candidates: list[Path] = []
    if configured.strip():
        candidates.append(Path(configured).expanduser())
    env_value = env.get(ENV_NOVACOIND, "").strip()
    if env_value:
        candidates.append(Path(env_value).expanduser())
    name = daemon_executable_name()
    candidates.extend(
        [
            project.root / "bin" / name,
            project.root / name,
            project.root / "novacoin-master" / "src" / name,
            project.root / "novacoin-master" / "src" / "qt" / name,
        ]
    )
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def daemon_arguments(settings: Settings, project: ProjectConfig) -> list[str]:
    """Build safe command line arguments for a foreground daemon."""
    args: list[str] = []
    datadir = settings.daemon_datadir.strip()
    if datadir:
        args.append(f"-datadir={Path(datadir).expanduser()}")
    args.append(f"-rpcport={project.daemon_port}")
    args.append("-server=1")
    if project.testnet:
        args.append("-testnet")
    extra = settings.daemon_extra_args.strip()
    if extra:
        try:
            args.extend(shlex.split(extra, posix=os.name != "nt"))
        except ValueError:
            args.extend(extra.split())
    return args


def _cookie_paths(project: ProjectConfig, datadir: str) -> Iterable[Path]:
    """Yield candidate cookie files used for daemon authentication."""
    base = Path(datadir).expanduser() if datadir else project.default_datadir
    yield base / ".cookie"
    yield base / "testnet2" / ".cookie"
    yield base / "testnet3" / ".cookie"


class DaemonProcess(QObject):
    """Start, probe and stop one foreground ``novacoind`` process."""

    stateChanged = pyqtSignal(str)
    ready = pyqtSignal(bool)
    failed = pyqtSignal(str)
    output = pyqtSignal(str)
    stopped = pyqtSignal(int)

    def __init__(
        self, settings: Settings, project: ProjectConfig, parent: QObject | None = None
    ) -> None:
        """Initialize the DaemonProcess instance."""
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
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(1500)
        self._probe_timer.timeout.connect(self._probe)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._on_probe_timeout)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._binary: Path | None = None

    @property
    def state(self) -> str:
        """Return the current lifecycle state."""
        return self._state

    @property
    def state_label(self) -> str:
        """Return a human-readable state label."""
        return {
            STATE_STOPPED: "Демон остановлен",
            STATE_STARTING: "Запуск демона",
            STATE_RUNNING: "Демон работает",
            STATE_STOPPING: "Остановка демона",
            STATE_MISSING: "Демон не найден",
            STATE_FAILED: "Ошибка демона",
        }.get(self._state, self._state)

    @property
    def binary(self) -> Path | None:
        """Return the executable used for this launch."""
        return self._binary

    @property
    def owned(self) -> bool:
        """Return whether this wallet started the daemon itself."""
        return self._owned

    @property
    def recent_output(self) -> str:
        """Return the tail of the daemon console output."""
        return self._buffer[-8000:]

    def _set_state(self, state: str) -> None:
        """Update and broadcast the lifecycle state."""
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def start(self) -> None:
        """Start the daemon unless something already serves its RPC port."""
        if self._state in {STATE_STARTING, STATE_RUNNING, STATE_STOPPING}:
            return
        host = urlparse(self._project.daemon_url).hostname or "127.0.0.1"
        if self._port_open(host, self._project.daemon_port):
            self._owned = False
            self._set_state(STATE_RUNNING)
            self.ready.emit(True)
            return
        binary = discover_daemon(self._project, self._settings.daemon_binary)
        if binary is None:
            self._set_state(STATE_MISSING)
            self.failed.emit(
                "novacoind не найден. Укажите путь в настройках "
                "или запустите прокси вручную."
            )
            return
        self._binary = binary
        self._owned = True
        self._stopping = False
        self._buffer = ""
        self._set_state(STATE_STARTING)
        args = daemon_arguments(self._settings, self._project)
        self._process.setWorkingDirectory(str(self._project.root))
        self._process.start(str(binary), args)
        if not self._process.waitForStarted(4000):
            self._set_state(STATE_FAILED)
            self.failed.emit(
                f"Не удалось запустить {binary.name}: {self._process.errorString()}"
            )
            return
        self._deadline.start(max(10, self._settings.daemon_start_timeout) * 1000)
        self._probe_timer.start()
        QTimer.singleShot(300, self._probe)

    @staticmethod
    def _port_open(host: str, port: int, timeout: float = 0.6) -> bool:
        """Check whether something is already listening on a TCP port."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _auth_header(self) -> bytes:
        """Build a basic auth header from config or the daemon cookie."""
        user = self._project.daemon_user
        password = self._project.daemon_password
        if not user and not password:
            for path in _cookie_paths(self._project, self._settings.daemon_datadir):
                try:
                    content = path.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if ":" in content:
                    user, password = content.split(":", 1)
                    break
        token = base64.b64encode(f"{user}:{password}".encode("utf-8"))
        return b"Basic " + token

    def _probe(self) -> None:
        """Ask the daemon for ``getinfo`` without blocking the UI."""
        if self._state != STATE_STARTING:
            return
        if self._reply is not None:
            return
        payload = json.dumps(
            {"jsonrpc": "1.0", "id": 1, "method": "getinfo", "params": []}
        ).encode("utf-8")
        request = QNetworkRequest(QUrl(self._project.daemon_url))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
        )
        request.setRawHeader(b"Authorization", self._auth_header())
        reply = self._network.post(request, payload)
        self._reply = reply
        reply.finished.connect(lambda: self._on_probe_reply(reply))

    def _on_probe_reply(self, reply: QNetworkReply) -> None:
        """Handle a daemon readiness probe response."""
        self._reply = None
        try:
            raw = bytes(reply.readAll())
            error = reply.error()
            if error == QNetworkReply.NetworkError.NoError:
                data = json.loads(raw.decode("utf-8", "replace"))
                if (
                    isinstance(data, dict)
                    and data.get("result")
                    and not data.get("error")
                ):
                    self._probe_timer.stop()
                    self._deadline.stop()
                    self._set_state(STATE_RUNNING)
                    self.ready.emit(False)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        finally:
            reply.deleteLater()

    def _on_probe_timeout(self) -> None:
        """Report a daemon that never became ready."""
        self._probe_timer.stop()
        if self._state == STATE_STARTING:
            self._set_state(STATE_FAILED)
            self.failed.emit(
                "Демон не ответил на RPC-порту вовремя. "
                "Проверьте каталог данных и журнал."
            )

    def _read_output(self) -> None:
        """Collect daemon output for diagnostics."""
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        if not chunk:
            return
        self._buffer = (self._buffer + chunk)[-16000:]
        self.output.emit(chunk)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        """React to QProcess startup failures."""
        if self._stopping:
            return
        if error in {
            QProcess.ProcessError.FailedToStart,
            QProcess.ProcessError.Crashed,
        }:
            self._probe_timer.stop()
            self._deadline.stop()
            self._set_state(STATE_FAILED)
            self.failed.emit(f"Ошибка процесса демона: {self._process.errorString()}")

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        """React to the daemon exiting, whether expected or not."""
        self._probe_timer.stop()
        self._deadline.stop()
        was_stopping = self._stopping
        self._stopping = False
        self._owned = False
        self._set_state(STATE_STOPPED)
        self.stopped.emit(code)
        if not was_stopping:
            tail = self._buffer.strip().splitlines()[-3:]
            detail = " | ".join(tail) if tail else "нет вывода"
            self.failed.emit(f"Демон завершился с кодом {code}: {detail}")

    def stop(self) -> None:
        """Stop a daemon owned by this GUI; external daemons are untouched."""
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

    def restart(self) -> None:
        """Stop and start the daemon again."""
        self.stop()
        QTimer.singleShot(400, self.start)
