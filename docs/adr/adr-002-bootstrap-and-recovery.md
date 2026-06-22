# ADR-002: Human admin bootstrap and recovery flow

## Status

Accepted

## Context

The AI Relay needs an initial administrator. The original design allowed the
master seed (adm_...) to act as a long-lived root login for the dashboard.
This created two problems:

1. Operational mismatch: The server is normally started by systemd. Creating
   the first admin through a CLI command that directly writes to the database
   bypasses the running service and requires shell access at the exact moment
   of setup.
2. Security drift: A single seed with permanent dashboard access is a
   long-lived high-value credential. If it leaks, an attacker can log in at any
   time, not only during setup.

At the same time there must be a recovery path when all human admin accounts
are lost or deactivated.

## Decision

1. The master seed is only usable for dashboard login in two situations:
   - No human admin account exists yet (initial bootstrap).
   - The server is started with an explicit recovery flag
     (--enable-master-seed or RELAY_ENABLE_MASTER_SEED_LOGIN=true) and all
     human admins have been deactivated via relay-recovery enable-recovery.

2. The first admin is created through a dedicated bootstrap page in the
   dashboard after master-seed login. The dashboard generates a temporary
   password that is displayed once.

3. The newly created admin account is flagged with force_password_change=True.
   The user is redirected to a password-change page and cannot use the
   dashboard until a new password is set.

4. Once a human admin exists, master-seed login is disabled automatically for
   normal operation.

5. Direct CLI creation of admin accounts (relay admin create-admin-user) is
   removed. Admin bootstrapping happens through the running web UI.

## Consequences

- Day-to-day administration uses regular human accounts with tracked sessions
  and mandatory password rotation on first use.
- The master seed becomes an emergency credential with a clear, explicit
  activation condition.
- Recovery requires two steps: deactivating admins with the local recovery CLI
  and restarting the server with recovery mode enabled. This prevents a single
  leaked master seed from silently regaining dashboard access.
- The systemd workflow is unaffected: the server keeps running while the first
  admin is created.

## Related files

- src/relay_server/api/v2/dashboard.py — bootstrap and password-change endpoints
- src/relay_server/main.py — recovery flag and middleware
- src/relay_server/static/bootstrap.html — bootstrap UI
- src/relay_server/static/change-password.html — forced password change UI
- docs/setup.md, docs/dashboard.md, docs/token-concept.md
- CHANGELOG.md
