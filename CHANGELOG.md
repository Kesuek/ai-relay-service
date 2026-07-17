# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Human users must change their password on first login. All new accounts and
  password resets set `force_password_change=True`. This also applies to the
  first admin created during bootstrap and to the bootstrap-generated temporary
  password.
- Master-seed dashboard login is now disabled automatically once a human admin
  exists. It can only be re-enabled explicitly via `RELAY_ENABLE_MASTER_SEED_LOGIN=true`
  or `--enable-master-seed` (recovery mode).
- Added recovery flow: `relay-recovery --db-path ~/.relay/server.db enable-recovery --all` deactivates all
  human admins; combined with recovery mode, the master seed can log in and
  bootstrap a replacement admin.
- Removed direct CLI creation of admin accounts (`relay admin create-admin-user`).
  Admin bootstrapping now goes through the running web dashboard, which is the
  normal path when the server is managed by systemd.
- bcrypt is now used for master seed hashing instead of plain SHA-256.
- Registration secrets (`rs_...`) are rotated when `/relay/v2/auth/refresh` is
  called with a registration secret, preventing replay of the old secret.
- File upload size is capped at 100 MiB via `max_upload_bytes` in `config.py`.
- `slowapi` rate limiting is applied to `auth`, `dashboard`, and general API
  routes.
- Session cookies are now `HttpOnly`, `Secure`, and `SameSite=Lax`; a session
  secret of at least 32 characters is enforced.
- CSRF protection via Double-Submit Cookie pattern is implemented for dashboard
  mutations.
- Security headers added: `Content-Security-Policy`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`.
- Password policy enforced: minimum length 12 characters and check against a
  common-password list.
- Storage-node path traversal hardened with a `_safe_path()` helper that keeps
  resolved paths inside the configured storage root.

### Added

- Bootstrap page at `/relay/v2/dashboard/bootstrap` for creating the first human
  admin after master-seed login.
- `POST /relay/v2/dashboard/api/bootstrap` endpoint (master-seed session only).
- `POST /relay/v2/dashboard/api/me/password` endpoint for self-service password
  changes.
- Recovery-mode server flag:
  - CLI: `relay-server server --enable-master-seed`
  - Environment: `RELAY_ENABLE_MASTER_SEED_LOGIN=true`
- Middleware that blocks all dashboard access except password-change endpoints
  while `force_password_change=True`.

### Changed

- First-time setup flow in documentation: create master seed (`relay admin
  init-master`), start server, open dashboard, log in with master seed, create
  first human admin via bootstrap, change generated password.
- Dashboard approval and normal administration now require a human admin
  account, not the master seed.

### Fixed

- Documentation updated to reflect the new bootstrap, forced password change,
  and recovery-mode behavior.
- `validate_token` now accepts nodes in `online` status as well as `approved`.
- `/relay/v2/auth/status` supports unauthenticated pending polling with a
  `registration_secret`.

### Documentation

- `token-concept.md` and `node-readme.md` updated to describe the
  `approved → online` lifecycle, the read-only nature of `/auth/status`,
  and registration-secret rotation during recovery.
- `nodes-design.md` and `node-readme.md` updated with recommended core
  capability names, execution-mode suffixes (`.native`, `.ai`, `.relay`),
  and the rule that capabilities can be changed at runtime via heartbeat.
- `AGENT_README.md` rewritten to match the current v2 auth flow and
  capability naming guidelines.