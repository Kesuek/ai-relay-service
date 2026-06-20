"""Example external node that advertises the 'board' capability.

This node is a standalone process. It does NOT import relay_server internals.
It registers itself in pending state, waits for an admin to approve it and
supply a runtime token, then heartbeats, claims board stages, and completes them.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay_client import RelayClient, TokenSource, wait_for_approval

logger = logging.getLogger("board_node")

CAPABILITY = "board"
DEFAULT_BASE_URL = "http://127.0.0.1:8788"
DEFAULT_NODE_ID = "board-node"
DEFAULT_NODE_NAME = "Board Node"


def _default_token_file(node_id: str) -> str:
    relay_dir = Path.home() / ".relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    return str(relay_dir / f"{node_id}.token")


def _capability_record(version: str = "1.0.0") -> Dict[str, Any]:
    return {
        "name": CAPABILITY,
        "version": version,
    }


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Board capability node for AI-Relay-Service v2")
    parser.add_argument("--base-url", default=os.environ.get("RELAY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--node-id", default=os.environ.get("RELAY_NODE_ID", DEFAULT_NODE_ID))
    parser.add_argument("--node-name", default=os.environ.get("RELAY_NODE_NAME", DEFAULT_NODE_NAME))
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


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _register_or_use_token(client: RelayClient, args: argparse.Namespace) -> None:
    if args.runtime_token:
        logger.info("Using provided runtime token.")
        client.set_token(args.runtime_token)
        return

    token_file = args.token_file or _default_token_file(args.node_id)
    logger.info("Registering node %s as pending (token file: %s)", args.node_id, token_file)
    result = client.register(
        node_id=args.node_id,
        node_name=args.node_name,
        capabilities=[_capability_record()],
        endpoint=args.endpoint,
        role="service",
    )
    logger.info(
        "Registered. status=%s token_type=%s temporary_token=%s...",
        result.get("status"),
        result.get("token_type"),
        result.get("token", "")[:12],
    )
    logger.info("Waiting for admin approval; write runtime token to %s", token_file)

    token_source = TokenSource(env_var="RELAY_RUNTIME_TOKEN", token_file=token_file)
    wait_for_approval(client, args.node_id, poll_interval=2.0, token_source=token_source)


def _do_board_work(stage: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal simulated board work."""
    payload = stage.get("payload") or {}
    logger.info("Doing board work for stage %s", stage.get("stage_id"))
    time.sleep(0.3)
    return {
        "capability": CAPABILITY,
        "stage_id": stage.get("stage_id"),
        "posts_created": payload.get("posts", 1),
        "status": "published",
    }


def _claim_and_complete_loop(
    base_url: str,
    token: str,
    node_id: str,
    shutdown: threading.Event,
    claim_interval: float,
) -> None:
    client = RelayClient(base_url=base_url, token=token)
    try:
        while not shutdown.is_set():
            try:
                response = client.claim(capability=CAPABILITY)
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
                result = _do_board_work(stage)
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


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)

    shutdown = threading.Event()

    def _on_signal(signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    client = RelayClient(base_url=args.base_url)
    try:
        _register_or_use_token(client, args)
        runtime_token = client.token
        if not runtime_token:
            logger.error("No runtime token available; exiting.")
            return 1

        logger.info("Starting board node %s work loops", args.node_id)

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(args.base_url, runtime_token, args.node_id, shutdown, args.heartbeat_interval),
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
            shutdown=shutdown,
            claim_interval=args.claim_interval,
        )
    finally:
        shutdown.set()
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
