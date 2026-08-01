# DECISIONS.md

## 2026-07-10: HIGH-Fixes aus GitHub-Review implementiert

**Entscheidung:** Drei HIGH-Findings aus dem GitHub-Code-Review behoben:

- **T-013 (Heartbeat Race Condition — TOCTOU in mark_offline_nodes):**
  `mark_offline_nodes()` in `discovery.py` selektiert weiterhin Kandidaten via
  `SELECT ... WHERE status IN ('approved','online') AND last_seen < ?`, aber
  das UPDATE prueft die Bedingung erneut in der WHERE-Klausel
  (`UPDATE ... WHERE node_id = ? AND last_seen < ?`). Wenn ein Node zwischen
  SELECT und UPDATE einen Heartbeat sendet, matched das UPDATE 0 Zeilen und der
  Node wird nicht offline gesetzt. Nach dem UPDATE wird pro Node der Status
  gelesen, um die tatsaechlich offline gesetzten IDs zu ermitteln — Events
  werden nur fuer diese gefeuert. Race Condition ist geschlossen.

- **T-014 (Fehlendes Audit Logging):** Neue `audit_logs`-Tabelle in `db.py`
  mit Spalten `log_id`, `actor_id`, `actor_name`, `action`, `resource_type`,
  `resource_id`, `details`, `created_at`. Indexes auf `created_at` und
  `actor_id`. Migration in `_run_migrations()` legt die Tabelle in bestehenden
  DBs nach. Hilfsfunktion `log_audit_event()` schreibt Eintraege. Logging
  eingebaut in `admin_approve_node` (action=`node.approve`),
  `admin_issue_node_token` (action=`node.issue_token`),
  `admin_delete_node` (action=`node.delete`). Admin-Aktionen sind nun
  nachvollziehbar.

- **T-015 (EventBus Silent Drops):** Der `dropped`-Zaehler des `_Subscriber`
  wird jetzt im SSE-Stream als `X-Dropped: N`-Header exponiert (nur wenn > 0).
  Bei 100 Drops feuert der Subscriber ein `subscriber_lagging`-Warn-Event via
  `_publish_internal()` — einer neuen Methode, die Events ohne History-Schreiben
  verteilt, um Endlos-Rekursion zu vermeiden. Der Threshold-Check feuert nur
  einmal bei exakt `dropped == 100`. Subscriber und Dashboard koennen nun
  reagieren, wenn Events verloren gehen.

**Grund:** GitHub-Code-Review identifizierte drei HIGH-Findings, die alle die
Zuverlaessigkeit und Compliance des Servers gefaehrden: Race Condition beim
Heartbeat-Timeout (T-013), fehlendes Audit Trail bei Admin-Aktionen (T-014),
und unsichtbare Event-Verluste bei langsamen SSE-Subscribers (T-015).

**Betroffene Files:** `discovery.py`, `db.py`, `events.py`, `api/v2/admin.py`
**Betroffene Tasks:** T-013, T-014, T-015

---

## Abweichung vom Plan

Keine inhaltlichen Abweichungen. Siehe `STATUS.md` Abschnitt "Abweichung vom Plan"
bzgl. `RELAY_SESSION_SECRET`-Env-Variable fuer Test-Runs (vorgegebenes Test-Setup
aus dem vorigen CRITICAL-Fix T-012, nicht durch diese Aenderungen verursacht).