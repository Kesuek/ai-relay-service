#!/usr/bin/env python3
"""Container healthcheck for the relay server.

Tries the /health endpoint over http, then https, so it works whether or not
TLS is enabled. Exits 0 on success, 1 on failure.
"""
import sys
import urllib.request

for scheme in ("http", "https"):
    try:
        urllib.request.urlopen(
            f"{scheme}://localhost:8788/health", timeout=5
        )
        sys.exit(0)
    except Exception:
        continue

sys.exit(1)
