"""First-run preparation for users who have never opened a terminal.

The wallet can create the daemon configuration and the project TOML from
the GUI.  Only missing files are created; existing wallets and credentials
are never overwritten.
"""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
from .config import ProjectConfig
from .proxy import backend_python

DAEMON_CONF = """server=1
rpcuser=phoenix
rpcpassword={password}
rpcport={port}
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
"""


def _hidden_flags() -> int:
    """Return the platform flag that suppresses a console window."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def ensure_daemon_conf(project: ProjectConfig) -> str:
    """Create a private daemon configuration when it is missing."""
    datadir = project.default_datadir
    conf = datadir / "novacoin.conf"
    if conf.is_file():
        return ""
    try:
        datadir.mkdir(parents=True, exist_ok=True)
        os.chmod(datadir, stat.S_IRWXU)
        conf.write_text(
            DAEMON_CONF.format(
                password=secrets.token_urlsafe(30), port=project.daemon_port
            ),
            encoding="utf-8",
        )
        os.chmod(conf, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        return f"Не удалось создать novacoin.conf: {exc}"
    return ""


def ensure_project_config(project: ProjectConfig) -> str:
    """Generate ``config.toml`` through the backend helper when absent."""
    if project.config_path.is_file():
        return ""
    python = backend_python(project)
    if python is None:
        return (
            "Не найден .venv-backend. Установите зависимости серверной части "
            "или создайте config.toml вручную."
        )
    try:
        result = subprocess.run(
            [str(python), "-c", "import conf_gen; conf_gen.generate_config()"],
            cwd=str(project.root),
            capture_output=True,
            timeout=30,
            creationflags=_hidden_flags(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Не удалось создать config.toml: {exc}"
    if result.returncode != 0 or not project.config_path.is_file():
        detail = (result.stderr or result.stdout).decode("utf-8", "replace")
        return f"config.toml не создан. {detail.strip()[:300]}"
    try:
        os.chmod(project.config_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return ""


def ensure_runtime_config(project: ProjectConfig) -> str:
    """Prepare missing daemon and proxy configuration files."""
    error = ensure_daemon_conf(project)
    if error:
        return error
    return ensure_project_config(project)
