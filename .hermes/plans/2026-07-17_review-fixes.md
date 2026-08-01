# GitHub Review Findings — 11 Dokumentations-Fehler beheben

> **For OpenCode:** `opencode run --agent primary "Abarbeiten von .hermes/plans/2026-07-17_review-fixes.md" --thinking`

**Goal:** Alle 11 Findings aus dem GitHub-Review (`review-260717`) beheben. Veraltete URLs korrigieren, fehlende Dokumentation ergänzen, unvollständige Einträge vervollständigen.

**Architecture:** Reine Markdown/Config-Änderungen. Kein Code. Die Findings betreffen README.md, docs/, CHANGELOG.md, STATUS.md, pyproject.toml.

---

## Task 1: Fix #1 — Git Clone URL korrigieren

**Objective:** `README.md` Zeile 18 zeigt `github.com/felix/` statt `github.com/Kesuek/`.

**Files:**
- Modify: `README.md`

**Änderung:**
```bash
# ALT:
git clone https://github.com/felix/ai-relay-service.git
# NEU:
git clone https://github.com/Kesuek/ai-relay-service.git
```

---

## Task 2: Fix #2 — relay-recovery Syntax korrigieren

**Objective:** `README.md` Quick Start und `CHANGELOG.md` zeigen `relay-recovery enable-recovery --all` ohne `--db-path`. Tatsächliche CLI: `relay-recovery --db-path ~/.relay/server.db enable-recovery [--all]`.

**Files:**
- Modify: `README.md` (Quick Start + Recovery section)
- Modify: `CHANGELOG.md` (Zeile 44)

**README.md Änderungen:**
- Quick Start (Zeile 22): `relay-server admin init-master` ist korrekt (das ist der init-master Befehl, der braucht kein --db-path). Aber der Recovery-Befehl weiter unten muss korrigiert werden.
- Recovery section: `relay-recovery enable-recovery --all` → `relay-recovery --db-path ~/.relay/server.db enable-recovery --all`

**CHANGELOG.md Änderungen:**
- Zeile 44: `relay-recovery enable-recovery --all` → `relay-recovery --db-path ~/.relay/server.db enable-recovery --all`

---

## Task 3: Fix #3 — Token-Cleanup-Watchdog dokumentieren

**Objective:** `src/relay_server/main.py` Zeilen 119-139 hat einen `_token_cleanup_watchdog()` der stündlich abgelaufene Tokens löscht. Das ist nirgendwo dokumentiert.

**Files:**
- Modify: `docs/node/token-lifecycle.md`
- Modify: `docs/concepts.md`
- Modify: `STATUS.md`

**token-lifecycle.md:**
Neuen Abschnitt "Automatic token cleanup" einfügen (nach dem "Common mistakes"-Abschnitt):
```markdown
## Automatic token cleanup

The relay runs a background watchdog every hour that deletes expired tokens
from the database (`DELETE FROM node_tokens WHERE expires_at < ?`). This
prevents the token table from growing indefinitely. The cleanup is
transparent to nodes — a token that was already expired would be rejected
by the auth middleware regardless.
```

**concepts.md:**
Kurzen Satz im Security-Abschnitt ergänzen: "Expired tokens are purged hourly by a background watchdog."

**STATUS.md:**
In Phase 6: `[x] Token-Cleanup-Watchdog (T-027)` ergänzen (ist bereits als done markiert, aber nicht in der Liste).

---

## Task 4: Fix #4 — Fehlende Token-Typen in token-lifecycle.md ergänzen

**Objective:** `docs/node/token-lifecycle.md` listet nur 3 Credential-Typen (tp_, rt_, rs_). Es fehlen `adm_` (Master admin seed) und `bs_` (Bootstrap seed).

**Files:**
- Modify: `docs/node/token-lifecycle.md`

**Änderung in der Token-Typen-Tabelle (Zeile 6-12):**

| Credential | Prefix | Default TTL | Purpose |
|---|---|---|---|
| Master admin seed | `adm_` | Permanent (until rotated) | Bootstrap & recovery — login when no human admin exists |
| Bootstrap seed | `bs_` | 24 h | One-time bootstrap session after master-seed login |
| Temporary token | `tp_` | 24 h | Issued on registration, replaced after approval |
| Runtime token | `rt_` | 7 days | Day-to-day auth for heartbeat, claim, complete |
| Registration secret | `rs_` | 12 h | Recovery only — rotate the runtime token |

---

## Task 5: Fix #5 — README Doc-Tabelle abschneiden fixen

**Objective:** README.md Zeile 46 zeigt `[...]` weil die Beschreibung zu lang ist. Die Tabelle ist unvollständig.

**Files:**
- Modify: `README.md`

**Änderung:** Die `reference-api` und `reference-design-board` Beschreibungen kürzen, damit sie nicht abgeschnitten werden. Oder die Tabelle auf 2 Zeilen aufteilen.

---

## Task 6: Fix #6 — CHANGELOG relay-recovery Syntax korrigieren

**Objective:** Selber Fix wie #2, aber in CHANGELOG.md. `--db-path` fehlt.

**Files:**
- Modify: `CHANGELOG.md`

**Änderung:** `relay-recovery enable-recovery --all` → `relay-recovery --db-path ~/.relay/server.db enable-recovery --all`

---

## Task 7: Fix #7 — Token-Cleanup in STATUS.md Phase 6 ergänzen

**Objective:** T-027 (validate_token synchroner DELETE → Background Cleaner) ist in TASKS.md als done markiert, aber in STATUS.md Phase 6 fehlt der Eintrag.

**Files:**
- Modify: `STATUS.md`

**Änderung:** In Phase 6 `[x] Token-Cleanup-Watchdog (T-027)` ergänzen.

---

## Task 8: Fix #8 — Worker-Heartbeat API dokumentieren

**Objective:** `docs/reference/api.md` listet `POST /relay/v2/discovery/worker-heartbeat` aber ohne Payload/Response-Beschreibung.

**Files:**
- Modify: `docs/reference/api.md`

**Änderung:** In der API-Tabelle für `worker-heartbeat` eine Beschreibung ergänzen:
```
| Discovery | `POST /relay/v2/discovery/worker-heartbeat` | Worker heartbeat with load/capabilities (alternative to the node heartbeat for worker-specific metrics) |
```

Oder einen eigenen Abschnitt für den Endpoint, wenn er sich vom normalen Heartbeat unterscheidet.

---

## Task 9: Fix #9 — Python Version in README Quick Start ergänzen

**Objective:** `pyproject.toml` sagt `requires-python = ">=3.11"`, aber README Quick Start hat keine Systemanforderungen.

**Files:**
- Modify: `README.md`

**Änderung:** Nach dem Quick-Start-Block einen Hinweis ergänzen:
```
> **Requirements:** Python 3.11+
```

---

## Task 10: Fix #10 — Linting & Build Tools dokumentieren

**Objective:** Ruff- und Pytest-Konfiguration existiert in `pyproject.toml` aber wird nirgendwo erwähnt.

**Files:**
- Modify: `README.md`

**Änderung:** Im Tests-Abschnitt ergänzen:
```
### Linting

```bash
ruff check .
```

### Formatting

```bash
ruff format .
```
```

---

## Task 11: Fix #11 — Legacy Doc Name Mapping dokumentieren

**Objective:** README sagt "Legacy short names still resolve" aber nicht wohin.

**Files:**
- Modify: `README.md`

**Änderung:** Die Legacy-Liste durch eine Tabelle ersetzen:

| Legacy Name | Resolves to |
|---|---|
| `setup` | `server-setup` |
| `admin-setup` | `server-admin` |
| `dashboard` | `server-dashboard` |
| `node-readme` | `node-setup` |
| `nodes-design` | `concepts` |
| `token-concept` | `concepts` |
| `token-lifecycle` | `node-token-lifecycle` |
| `capabilities` | `node-capabilities` |
| `design-board` | `reference-design-board` |
| `proxmox-worker-setup` | `node-setup` |

---

## Task 12: Tests laufen lassen

**Objective:** Sicherstellen, dass keine Änderungen die Tests brechen.

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/ -q
```

Expected: ALL PASSED

---

## Abschliessende Antwort für das Project Board

**TASKS.md:**
- T-032 — "GitHub Review Findings beheben (11 Dokumentations-Fehler)" — Prio HIGH, Status done

**DECISIONS.md:**
- Eintrag: "2026-07-17: GitHub Review Findings aus review-260717 behoben — 11 Findings (2 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW) alle gefixt"

**IDEAS.md:**
- Umgesetzte Idee ergänzen

---

## OpenCode-Output

```
.hermes/opencode-output/2026-07-17_review-fixes/
├── STATUS.md
├── TASKS.md
├── DECISIONS.md
├── VERIFICATION.md
└── LOG.md
```
