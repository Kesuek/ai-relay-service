# IOWAP — ai-relay-service (deprecated)

**This repository has been split into 4 repositories under `iowap-org`.**

---

## → **[github.com/iowap-org/iowap](https://github.com/iowap-org/iowap)** (meta + architecture)

The project formerly known as `ai-relay-service` now lives as **IOWAP** (Infrastructure · Offloading · Workload Assignment Platform):

| Old | New |
|-----|-----|
| `src/relay_server/` | [iowap-server](https://github.com/iowap-org/iowap-server) — API, scheduler, auth, DB, dashboard |
| `nodes/common/` | [iowap-node](https://github.com/iowap-org/iowap-node) — node framework, CLI, daemon |
| `docker/nodes/storage/` | [iowap-storage](https://github.com/iowap-org/iowap-storage) — storage node reference |
| `README` + docs | [iowap (meta)](https://github.com/iowap-org/iowap) — story, architecture, links |

**Why?** The monorepo grew beyond a single component. Separate repos allow independent releases, cleaner CI, and better onboarding for specific audiences (node operators vs server admins).

**What happened to existing deployments?** Nothing. Code is identical, just in new repos. Nodes and servers continue working as before.

**Last original commit:** `fc7af12` (T-045)
**Split date:** 2026-08-24