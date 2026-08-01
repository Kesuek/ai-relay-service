# TASKS.md — T-001 + T-003: Artifact Upload + YAML Schema Validation

| ID    | Status | Notiz |
|-------|--------|-------|
| T-001 | ✅ done | `node-cli artifact upload <file>` + `RelayClient.upload_artifact()` (multipart upload an `/relay/v2/storage/upload`, 401/403-Token-Refresh-Retry) |
| T-003 | ✅ done | JSON Schema (Draft 2020-12) fuer capabilities.yaml: `CAPABILITY_SCHEMA` + `validate_with_schema()`, in `validate_profile()` vor der programmatischen Validierung |