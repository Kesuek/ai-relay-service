"""Minimal HTTP client for external AI-Relay-Service v2 nodes.

This module is intentionally standalone: it does NOT import any relay_server
internals. It talks to the core over the public REST + SSE endpoints.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

logger = logging.getLogger("relay_client")

DEFAULT_TIMEOUT = 30.0


class RelayError(Exception):
    """Raised when the relay server returns an error response."""

    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class RelayClient:
    """Thin wrapper around the relay v2 API for example nodes."""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def set_token(self, token: str) -> None:
        self.token = token

    def close(self) -> None:
        self.client.close()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _check(self, response: httpx.Response) -> Dict[str, Any]:
        if response.status_code >= 400:
            body: Any = None
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise RelayError(
                f"Relay API error: {response.status_code} {response.url}",
                status_code=response.status_code,
                body=body,
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def register(
        self,
        node_id: str,
        node_name: str,
        capabilities: List[Dict[str, Any]],
        endpoint: Optional[str] = None,
        role: str = "service",
        bootstrap_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register a new node. Returns pending temporary token unless bootstrap secret is used."""
        payload: Dict[str, Any] = {
            "node_id": node_id,
            "node_name": node_name,
            "capabilities": capabilities,
            "role": role,
        }
        if endpoint:
            payload["endpoint"] = endpoint
        if bootstrap_secret:
            payload["bootstrap_secret"] = bootstrap_secret
        response = self.client.post(
            self._url("/relay/v2/auth/register"),
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        data = self._check(response)
        self.token = data.get("token")
        return data

    def get_nodes(self, status: Optional[str] = None) -> Dict[str, Any]:
        params = {"status": status} if status else {}
        response = self.client.get(
            self._url("/relay/v2/discovery/nodes"),
            params=params,
            headers=self._headers(),
        )
        return self._check(response)

    def heartbeat(
        self,
        load: Optional[float] = None,
        queue_depth: Optional[int] = None,
        available: Optional[bool] = None,
        endpoint: Optional[str] = None,
        capabilities: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if load is not None:
            payload["load"] = load
        if queue_depth is not None:
            payload["queue_depth"] = queue_depth
        if available is not None:
            payload["available"] = available
        if endpoint is not None:
            payload["endpoint"] = endpoint
        if capabilities is not None:
            payload["capabilities"] = capabilities
        response = self.client.post(
            self._url("/relay/v2/discovery/heartbeat"),
            json=payload,
            headers=self._headers(),
        )
        return self._check(response)

    def claim(self, capability: Optional[str] = None) -> Dict[str, Any]:
        payload = {"capability": capability} if capability else {}
        response = self.client.post(
            self._url("/relay/v2/scheduler/claim"),
            json=payload,
            headers=self._headers(),
        )
        return self._check(response)

    def complete(self, stage_id: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"result": result} if result is not None else {}
        response = self.client.post(
            self._url(f"/relay/v2/scheduler/stages/{stage_id}/complete"),
            json=payload,
            headers=self._headers(),
        )
        return self._check(response)

    def subscribe_events(self, node_id: str) -> Generator[Dict[str, Any], None, None]:
        """Open an SSE stream and yield parsed events."""
        if not self.token:
            raise RelayError("Cannot subscribe to events without a token")
        url = self._url(f"/relay/v2/events/stream?node={node_id}")
        headers = {"Accept": "text/event-stream", "Authorization": f"Bearer {self.token}"}
        with self.client.stream("GET", url, headers=headers, timeout=None) as response:
            if response.status_code >= 400:
                self._check(response)
            for line in response.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Ignoring malformed SSE payload: %s", raw)

    def __enter__(self) -> "RelayClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def wait_for_approval(
    client: RelayClient,
    node_id: str,
    poll_interval: float = 2.0,
    token_source: Optional["TokenSource"] = None,
) -> str:
    """Wait until a runtime token for *node_id* becomes available.

    The core deletes the temporary token when an admin approves the node, so an
    external actor must supply the runtime token (e.g. via a token file or
    environment variable). This helper keeps heartbeating with the temporary
    token while pending and returns as soon as a runtime token is supplied.
    """
    logger.info("Waiting for admin approval of %s ...", node_id)
    while True:
        try:
            client.heartbeat(available=True)
        except RelayError as e:
            if e.status_code == 401:
                logger.debug("Temporary token expired / invalidated for %s", node_id)
            else:
                logger.warning("Heartbeat failed: %s", e)

        if token_source:
            runtime_token = token_source()
            if runtime_token:
                client.set_token(runtime_token)
                # Verify the runtime token works by fetching our node record.
                try:
                    data = client.get_nodes()
                    for node in data.get("nodes", []):
                        if node["node_id"] == node_id and node["status"] == "approved":
                            logger.info("Node %s approved; runtime token active.", node_id)
                            return runtime_token
                except RelayError as e:
                    logger.debug("Runtime token not valid yet: %s", e)

        time.sleep(poll_interval)


class TokenSource:
    """Callable that returns a runtime token or None."""

    def __init__(
        self,
        env_var: Optional[str] = None,
        token_file: Optional[str] = None,
    ):
        self.env_var = env_var
        self.token_file = token_file

    def __call__(self) -> Optional[str]:
        if self.env_var:
            token = _read_env(self.env_var)
            if token:
                return token
        if self.token_file:
            return _read_file_if_exists(self.token_file)
        return None


def _read_env(name: str) -> Optional[str]:
    import os

    return os.environ.get(name)


def _read_file_if_exists(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
