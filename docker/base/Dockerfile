# syntax=docker/dockerfile:1
# AI-Relay-Service — Node base image.
#
# A reusable base image that carries the *installed* node stack (node-cli,
# node-daemon, relay_client, node_config, handler_runner). A concrete
# service image (e.g. docker/storage/) builds ``FROM ai-relay-node-base``
# and only adds its ``node.yaml`` + ``handlers/`` directory — no Python
# install, no wheel build.
#
# The node stack is installed from the same wheel as the server so both
# sides run identical code. The entrypoint translates environment
# variables (RELAY_URL, NODE_NAME, NODE_PROFILE) into ``relay_config.json``
# + ``node.yaml`` and registers the node on first start; then execs
# ``node-daemon`` (SSE, event-driven).
#
# Two-stage: a builder that assembles the wheel, and a slim runtime that
# only carries the wheel + a non-root user (PUID/PGID-overridable).

# ---- build stage ---------------------------------------------------------
FROM python:3.11-slim AS builder
WORKDIR /build

# Build backend + core build deps in one layer.
RUN pip install --no-cache-dir build

# Copy only what hatchling needs to resolve the project.
COPY pyproject.toml README.md ./
COPY src ./src
COPY nodes ./nodes

# Build an sdist+wheel so the runtime stage installs from the wheel only.
RUN python -m build --wheel --outdir /build/dist

# ---- runtime stage -------------------------------------------------------
FROM python:3.11-slim AS runtime

# tini as PID 1 so signals (SIGTERM/SIGINT) reach node-daemon cleanly on stop.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the node stack wheel. ``psycopg`` is not needed on the node side
# (the node never opens the server DB), so we skip the ``postgres`` extra
# and keep the image lean.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

# --- appuser ---------------------------------------------------------------
# Non-root runtime user. PUID/PGID are overridable so a NAS operator can map
# the container's file ownership to their host user for bind-mounted volumes.
ARG PUID=1000
ARG PGID=1000
RUN groupadd -g ${PGID} appuser \
    && useradd -m -u ${PUID} -g appuser appuser \
    && install -d -o appuser -g appuser /app /home/appuser/.relay

# The node resolves ~/.relay via Path.home(); ensure HOME is the appuser's.
ENV HOME=/home/appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

USER appuser

# Entrypoint translates env → relay_config.json + node.yaml, registers the
# node on first start, then execs node-daemon.
COPY --chown=appuser:appuser docker/base/docker-entrypoint.sh /app/docker-entrypoint.sh
# Healthcheck script (reads the daemon status file).
COPY --chown=appuser:appuser docker/base/healthcheck.py /app/healthcheck.py
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]

# No EXPOSE — the node does not listen on any port (it only connects to the
# relay via SSE + HTTP; any bridge-route upstream is served by the service
# image itself, not the base image).
CMD ["node-daemon"]