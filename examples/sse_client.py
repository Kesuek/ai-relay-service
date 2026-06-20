#!/usr/bin/env python3
"""Example SSE client for the relay event stream.

Usage:
    export RELAY_TOKEN="rt_..."
    python examples/sse_client.py --node my-node [--types task_created,stage_claimed]
"""

import argparse
import json
import os
import sys

import httpx


def parse_sse(lines: list[str]) -> dict | None:
    """Parse a single SSE message split into lines."""
    event: dict[str, str] = {}
    for line in lines:
        if line.startswith("event: "):
            event["event"] = line[7:]
        elif line.startswith("data: "):
            event["data"] = line[6:]
    if "data" not in event:
        return None
    try:
        return {
            "event": event.get("event", "message"),
            "data": json.loads(event["data"]),
        }
    except json.JSONDecodeError:
        return {"event": event.get("event", "message"), "data": event["data"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Relay SSE client")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--node", required=True, help="Node ID to subscribe as")
    parser.add_argument(
        "--types",
        help="Comma-separated event types to filter (e.g. task_created,stage_claimed)",
    )
    parser.add_argument("--token", default=os.environ.get("RELAY_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        print("Error: --token or RELAY_TOKEN environment variable required", file=sys.stderr)
        sys.exit(1)

    params = {"node": args.node}
    if args.types:
        params["types"] = args.types

    url = f"{args.base_url}/relay/v2/events/stream"
    headers = {"Authorization": f"Bearer {args.token}"}

    print(f"Connecting to {url} as {args.node} ...")
    with httpx.stream("GET", url, params=params, headers=headers, timeout=None) as response:
        response.raise_for_status()
        print("Connected. Waiting for events...")
        buffer: list[str] = []
        for line in response.iter_lines():
            if line == "":
                message = parse_sse(buffer)
                buffer = []
                if message:
                    print(json.dumps(message, indent=2, sort_keys=True))
            else:
                buffer.append(line)


if __name__ == "__main__":
    main()
