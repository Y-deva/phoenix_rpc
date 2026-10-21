"""Thread-friendly JSON-RPC client for the Phoenix proxy.

The proxy speaks HTTP and expects basic authentication. Requests are
short-lived and the client keeps one ``requests.Session`` per thread so
connection pooling works with the UI's worker threads.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Sequence

import requests
from requests.auth import HTTPBasicAuth

Transport = Callable[[str, Sequence[Any]], Any]


class RPCError(Exception):
    """Base class for errors returned by the wallet backend."""

    def __init__(self, message: str, code: int | None = None, data: Any = None) -> None:
        """Store the RPC error details."""
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data

    def __str__(self) -> str:
        """Return the error with its numeric RPC code."""
        if self.code is None:
            return self.message
        return f"{self.message} (code {self.code})"


class RPCConnectionError(RPCError):
    """Raised when the proxy or daemon cannot be reached."""


class RPCAuthError(RPCError):
    """Raised when the proxy rejects the configured credentials."""


class RPCProtocolError(RPCError):
    """Raised when the proxy returns a malformed response."""


class RPCClient:
    """Minimal JSON-RPC 1.0 client with per-thread HTTP sessions."""

    def __init__(
        self,
        url: str,
        user: str = "",
        password: str = "",
        timeout: float = 12.0,
        transport: Transport | None = None,
    ) -> None:
        """Initialize the RPCClient instance."""
        self.url = (url or "").rstrip("/")
        self.user = user or ""
        self.password = password or ""
        self.timeout = max(1.0, float(timeout))
        self._transport = transport
        self._local = threading.local()
        self._id_lock = threading.Lock()
        self._request_id = 0

    def _next_id(self) -> int:
        """Return a monotonically increasing request id."""
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def _session(self) -> requests.Session:
        """Return the session owned by the current thread."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            if self.user or self.password:
                session.auth = HTTPBasicAuth(self.user, self.password)
            session.headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "PhoenixWallet/1.0",
                }
            )
            self._local.session = session
        return session

    def close(self) -> None:
        """Close the current thread's HTTP session."""
        session = getattr(self._local, "session", None)
        if session is not None:
            session.close()
            self._local.session = None

    def call(self, method: str, params: Sequence[Any] | None = None) -> Any:
        """Execute one JSON-RPC method and return its result.

        ``transport`` is primarily used by tests and by the demo service;
        when present it bypasses HTTP entirely.
        """
        payload_params = list(params or [])
        if self._transport is not None:
            return self._transport(method, payload_params)

        payload = {
            "jsonrpc": "1.0",
            "id": self._next_id(),
            "method": method,
            "params": payload_params,
        }
        try:
            response = self._session().post(
                self.url,
                data=json.dumps(payload).encode("utf-8"),
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise RPCConnectionError(
                f"Backend did not respond in {self.timeout:.0f} seconds"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RPCConnectionError("Cannot reach the wallet backend") from exc
        except requests.exceptions.RequestException as exc:
            raise RPCConnectionError(f"Backend request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise RPCAuthError(
                "Backend rejected the credentials", code=response.status_code
            )
        if response.status_code >= 400:
            message = self._extract_error(response)
            raise RPCProtocolError(message, code=response.status_code)

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            snippet = (response.text or "").strip()[:160]
            raise RPCProtocolError(f"Backend returned invalid JSON: {snippet}") from exc
        if not isinstance(data, dict):
            raise RPCProtocolError("Backend returned an unexpected response")
        error = data.get("error")
        if error:
            if isinstance(error, dict):
                raise RPCError(
                    str(error.get("message") or "Backend error"),
                    code=error.get("code"),
                    data=error.get("data"),
                )
            raise RPCError(str(error))
        if "result" not in data:
            raise RPCProtocolError("Backend response does not contain a result")
        return data["result"]

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        """Read a useful message from an HTTP error response."""
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str):
                return error
            if data.get("message"):
                return str(data["message"])
        reason = response.reason or "HTTP error"
        return f"Backend returned {response.status_code} {reason}"

    def getinfo(self) -> dict[str, Any]:
        """Fetch general daemon information."""
        return self.call("getinfo") or {}

    def getblockchaininfo(self) -> dict[str, Any]:
        """Fetch chain synchronization details."""
        return self.call("getblockchaininfo") or {}

    def ping(self) -> bool:
        """Check connectivity without changing any state."""
        try:
            self.getinfo()
        except RPCError:
            return False
        return True


def friendly_error(error: BaseException) -> str:
    """Convert an exception into a short message suitable for the UI."""
    if isinstance(error, RPCError):
        return str(error)
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "The operation timed out"
    return str(error) or error.__class__.__name__
