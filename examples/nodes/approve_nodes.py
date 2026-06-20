"""Helper to approve pending example nodes and write their runtime tokens.

This utility is meant for the manual end-to-end demo. It registers a temporary
admin node with the master bootstrap secret, lists pending nodes, approves those
that match the requested capabilities, and writes the resulting runtime tokens
to the node token files so the nodes can continue.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay_client import RelayClient, RelayError

logger = logging.getLogger("approve_nodes")

DEFAULT_BASE_URL = "http://127.0.0.1:8788"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Approve pending relay nodes and persist runtime tokens"
    )
    parser.add_argument("--base-url", default=os.environ.get("RELAY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--master-secret",
        default=os.environ.get("RELAY_MASTER_SECRET"),
        help="Master admin bootstrap secret (required).",
    )
    parser.add_argument(
        "--capabilities",
        default=os.environ.get("RELAY_APPROVE_CAPABILITIES", "vault,board"),
        help="Comma-separated capability names to approve.",
    )
    parser.add_argument(
        "--token-dir",
        default=os.environ.get("RELAY_TOKEN_DIR", str(Path.home() / ".relay")),
        help="Directory where runtime token files are written.",
    )
    parser.add_argument(
        "--admin-node-name",
        default=os.environ.get("RELAY_ADMIN_NODE_NAME", "Approve Helper"),
        help="Name for the temporary admin helper node.",
    )
    parser.add_argument("--log-level", default=os.environ.get("RELAY_LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _register_admin(client: RelayClient, master_secret: str) -> tuple[str, str]:
    response = client.register(
        node_name="Approve Helper",
        capabilities=[{"name": "admin", "version": "1.0.0"}],
        bootstrap_secret=master_secret,
        role="admin",
    )
    return response["node_id"], response["token"]


def _approve_node(client: RelayClient, node_id: str, capabilities: List[Dict[str, Any]]) -> str:
    data = client.approve_node(
        node_id=node_id,
        role="service",
        capabilities=capabilities,
    )
    return data["token"]


def _capability_record(name: str) -> Dict[str, Any]:
    return {"name": name, "version": "1.0.0"}


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)

    if not args.master_secret:
        logger.error(
            "Master secret is required. Set RELAY_MASTER_SECRET or use --master-secret. "
            "Create one with: python -m relay_server.main admin init-master"
        )
        return 1

    token_dir = Path(args.token_dir)
    token_dir.mkdir(parents=True, exist_ok=True)

    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    cap_records = [_capability_record(c) for c in capabilities]

    client = RelayClient(base_url=args.base_url)
    try:
        logger.info("Registering admin helper %s ...", args.admin_node_name)
        admin_id, admin_token = _register_admin(client, args.master_secret)
        client.set_token(admin_token)
        logger.info("Admin helper registered as %s.", admin_id)

        logger.info("Listing pending nodes ...")
        data = client.get_nodes(status="pending")
        pending = data.get("nodes", [])
        if not pending:
            logger.info("No pending nodes found.")
            return 0

        approved_any = False
        for node in pending:
            node_caps = node.get("capabilities") or []
            node_cap_names = {c.get("name") for c in node_caps}
            matched = [c for c in capabilities if c in node_cap_names]
            if not matched:
                logger.info(
                    "Skipping node %s (capabilities: %s)",
                    node["node_id"],
                    sorted(node_cap_names),
                )
                continue

            logger.info("Approving node %s for %s ...", node["node_id"], matched)
            try:
                runtime_token = _approve_node(client, node["node_id"], cap_records)
            except RelayError as e:
                logger.error("Could not approve %s: %s", node["node_id"], e)
                continue

            token_file = token_dir / f"{node['node_id']}.token"
            token_file.write_text(runtime_token, encoding="utf-8")
            logger.info(
                "Approved %s; runtime token written to %s (%s...)",
                node["node_id"],
                token_file,
                runtime_token[:12],
            )
            approved_any = True

        if not approved_any:
            logger.warning("No pending nodes matched requested capabilities: %s", capabilities)
            return 0
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
