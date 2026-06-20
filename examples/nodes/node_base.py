"""Shared base node implementation for external AI-Relay-Service v2 nodes.

This module is intentionally standalone: it does NOT import any relay_server
internals. Concrete nodes provide a capability name and a work function; this
base handles registration, approval waiting, heartbeats, SSE listening, and the
claim/complete loop.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from relay_client import RelayClient, TokenSource, wait_for_approval

logger = logging.getLogger("base_node")

DEFAULT_BASE_URL = "http://127.0.0.1:8788"
WorkFn = Callable[[str, str, Dict[str, Any]], Dict[str, Any]]


def _default_token_file(node_id: str) -> str:
    relay_dir = Path.home() / ".relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    return str(relay_dir / f"{node_id}.token")


def _capability_record(name: str, version: str = "1.0.0") -> Dict[str, Any]:
    return {"name": name, "version": version}


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _register_or_use_token(
    client: RelayClient,
    node_id: str,
    node_name: str,
    capability: str,
    endpoint: Optional[str],
    runtime_token: Optional[str],
    token_file: Optional[str],
) -> None:
    if runtime_token:
        logger.info("Using provided runtime token.")
        client.set_token(runtime_token)
        return

    token_path = token_file or _default_token_file(node_id)
    logger.info("Registering node %s as pending (token file: %s)", node_id, token_path)
    result = client.register(
        node_id=node_id,
        node_name=node_name,
        capabilities=[_capability_record(capability)],
        endpoint=endpoint,
        role="service",
    )
    logger.info(
        "Registered. status=%s token_type=%s temporary_token=%s...",
        result.get("status"),
        result.get("token_type"),
        result.get("token", "")[:12],
    )
    logger.info("Waiting for admin approval; write runtime token to %s", token_path)

    token_source = TokenSource(env_var="RELAY_RUNTIME_TOKEN", token_file=token_path)
    wait_for_approval(client, node_id, poll_interval=2.0, token_source=token_source)


def _heartbeat_loop(
    base_url: str,
    token: str,
    node_id: str,
    shutdown: threading.Event,
    interval: float,
) -> None:
    client = RelayClient(base_url=base_url, token=token)
    try:
        while not shutdown.is_set():
            try:
                client.heartbeat(available=True, load=0.0, queue_depth=0)
                logger.debug("Heartbeat OK")
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)
            shutdown.wait(interval)
    finally:
        client.close()


def _sse_listener(
    base_url: str,
    token: str,
    node_id: str,
    shutdown: threading.Event,
) -> None:
    client = RelayClient(base_url=base_url, token=token)
    try:
        for event in client.subscribe_events(node_id):
            if shutdown.is_set():
                break
            logger.info("SSE: %s %s", event.get("type"), event.get("payload"))
    except Exception as e:
        logger.warning("SSE listener ended: %s", e)
    finally:
        client.close()


def _claim_and_complete_loop(
    base_url: str,
    token: str,
    node_id: str,
    capability: str,
    work_fn: WorkFn,
    shutdown: threading.Event,
    claim_interval: float,
) -> None:
    client = RelayClient(base_url=base_url, token=token)
    try:
        while not shutdown.is_set():
            try:
                response = client.claim(capability=capability)
                if not response.get("claimed"):
                    time.sleep(claim_interval)
                    continue
                stage = response["stage"]
                logger.info(
                    "Claimed stage %s (%s) of task %s",
                    stage["stage_id"],
                    stage["stage_name"],
                    stage["task_id"],
                )
                result = work_fn(capability, node_id, stage)
                client.complete(stage["stage_id"], result=result)
                logger.info(
                    "Completed stage %s of task %s",
                    stage["stage_id"],
                    stage["task_id"],
                )
            except Exception as e:
                logger.exception("Claim/complete loop error: %s", e)
                time.sleep(claim_interval)
    finally:
        client.close()


class BaseNode:
    """Reusable external node runner.

    Subclass or instantiate directly with a capability name and work function.
    The work function receives ``(capability, node_id, stage)`` and must return
    a result dictionary for ``/scheduler/stages/{stage_id}/complete``.
    """

    def __init__(
        self,
        capability: str,
        work_fn: WorkFn,
        *,
        default_node_id: str,
        default_node_name: str,
        default_base_url: str = DEFAULT_BASE_URL,
    ):
        self.capability = capability
        self.work_fn = work_fn
        self.default_node_id = default_node_id
        self.default_node_name = default_node_name
        self.default_base_url = default_base_url

    def _parse_args(self, argv: Optional[List[str]]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description=f"{self.capability.title()} capability node for AI-Relay-Service v2"
        )
        parser.add_argument(
            "--base-url",
            default=os.environ.get("RELAY_BASE_URL", self.default_base_url),
        )
        parser.add_argument(
            "--node-id",
            default=os.environ.get("RELAY_NODE_ID", self.default_node_id),
        )
        parser.add_argument(
            "--node-name",
            default=os.environ.get("RELAY_NODE_NAME", self.default_node_name),
        )
        parser.add_argument("--endpoint", default=os.environ.get("RELAY_ENDPOINT"))
        parser.add_argument(
            "--runtime-token",
            default=os.environ.get("RELAY_RUNTIME_TOKEN"),
            help="Skip pending registration and use this approved runtime token directly.",
        )
        parser.add_argument(
            "--token-file",
            default=os.environ.get("RELAY_TOKEN_FILE"),
            help="Path to a file that will receive the runtime token after admin approval.",
        )
        parser.add_argument(
            "--heartbeat-interval",
            type=float,
            default=float(os.environ.get("RELAY_HEARTBEAT_INTERVAL", "10")),
        )
        parser.add_argument(
            "--claim-interval",
            type=float,
            default=float(os.environ.get("RELAY_CLAIM_INTERVAL", "2")),
        )
        parser.add_argument("--log-level", default=os.environ.get("RELAY_LOG_LEVEL", "INFO"))
        return parser.parse_args(argv)

    def run(self, argv: Optional[List[str]] = None) -> int:
        args = self._parse_args(argv)
        _setup_logging(args.log_level)

        shutdown = threading.Event()

        def _on_signal(signum: int, frame: Any) -> None:
            logger.info("Received signal %s, shutting down...", signum)
            shutdown.set()

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

        client = RelayClient(base_url=args.base_url)
        try:
            _register_or_use_token(
                client,
                args.node_id,
                args.node_name,
                self.capability,
                args.endpoint,
                args.runtime_token,
                args.token_file,
            )
            runtime_token = client.token
            if not runtime_token:
                logger.error("No runtime token available; exiting.")
                return 1

            logger.info("Starting %s node %s work loops", self.capability, args.node_id)

            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                args=(
                    args.base_url,
                    runtime_token,
                    args.node_id,
                    shutdown,
                    args.heartbeat_interval,
                ),
                name="heartbeat",
                daemon=True,
            )
            sse_thread = threading.Thread(
                target=_sse_listener,
                args=(args.base_url, runtime_token, args.node_id, shutdown),
                name="sse-listener",
                daemon=True,
            )
            heartbeat_thread.start()
            sse_thread.start()

            _claim_and_complete_loop(
                base_url=args.base_url,
                token=runtime_token,
                node_id=args.node_id,
                capability=self.capability,
                work_fn=self.work_fn,
                shutdown=shutdown,
                claim_interval=args.claim_interval,
            )
        finally:
            shutdown.set()
            client.close()

        return 0


def run_node(
    capability: str,
    work_fn: WorkFn,
    *,
    default_node_id: str,
    default_node_name: str,
    default_base_url: str = DEFAULT_BASE_URL,
    argv: Optional[List[str]] = None,
) -> int:
    """Convenience entry point for thin node shells."""
    return BaseNode(
        capability=capability,
        work_fn=work_fn,
        default_node_id=default_node_id,
        default_node_name=default_node_name,
        default_base_url=default_base_url,
    ).run(argv)
