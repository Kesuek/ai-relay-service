# TASKS.md — T-016 + T-017: SQLite Lock Contention + Task Timeout Enforcement

| ID    | Status | Notiz |
|-------|--------|-------|
| T-016 | ✅ done | `retry_on_locked`-Decorator in `db.py` (angewandt auf `log_audit_event`) + `_retry_db_write`-Wrapper in `scheduler.py` (angewandt auf `create_task`, `claim_stage`, `complete_stage`, `release_expired_claims`); exponentieller Backoff 50ms→800ms, 5 Versuche; 3 Tests in `test_scheduler.py` |
| T-017 | ✅ done | `Scheduler.enforce_timeouts()` markiert ueberfaellige `claimed` Stages (`claimed_at + timeout_seconds < now`) als `timed_out`; Tasks, deren saemtliche Stages fertig/timed_out sind, werden ebenfalls `timed_out`; `POST /relay/v2/scheduler/enforce-timeouts`-Endpoint; Events `stage_timed_out`/`task_timed_out`; 3 Tests in `test_scheduler.py` |