# Security Policy

The AI Relay Service is a distributed coordination layer that connects,
authenticates, and dispatches work across self-healing worker nodes. Because it
handles authentication, task routing, and node identity, we take security
reports seriously.

## Reporting a vulnerability

**Do not open a public issue for security problems.** Please report
vulnerabilities privately by email to the repository maintainer, or use the
GitHub **Security → Report a vulnerability** flow (private disclosure).

Please include:

- The affected version / commit.
- A description of the vulnerability and its impact.
- Steps to reproduce (redact any real personal data, credentials, or private
  configuration).
- Whether it is already publicly known.

We aim to acknowledge reports within **3 business days** and will keep you
informed of progress toward a fix. Please do not disclose the issue publicly
until we have published a fix or agreed otherwise.

## Supported versions

| Version | Supported          |
|---------|--------------------|
| `main`  | ✅ actively developed |

This is a fast-moving personal project — we recommend tracking `main` rather
than pinning a release.

## Security-relevant areas

These are the parts of the codebase most likely to attract an attack, and the
ones we pay closest attention to:

- **Authentication / token handling** — node auth, token refresh, and the
  credential lifecycle. Tokens must never be committed or logged.
- **Task routing / dispatch** — capability-based routing across nodes; a node
  must only receive work it is authorized and capable of handling.
- **SSE event bus** — live event delivery to nodes; events must not leak
  credentials or private configuration.
- **Storage / persistence** — server DB and artifacts; persisted files must
  not contain secrets.

## Good security practice (for contributors)

- Never commit secrets, tokens, private config, or real personal data — use
  placeholders (e.g. `alice@example.com`).
- Never loosen the auth boundary between nodes and the server.
- If a persisted file shape changes, migrate old data instead of breaking it.

## Thanks

We appreciate researchers who report issues responsibly and give us time to
fix them before disclosure.
