# Contributing

## Changelog

Every change that affects users, operators, or developers **must** be documented
in [CHANGELOG.md](CHANGELOG.md) under the `[Unreleased]` section before merging.
This includes:

- New features
- API changes (new endpoints, changed payloads, removed fields)
- Config changes (new/removed/renamed keys)
- Breaking changes
- Bug fixes
- Documentation restructuring
- Dependency changes

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Use the `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Deprecated`
sections as appropriate.

## Documentation

- All public Markdown docs live in `docs/` and are served live by the relay
  at `/relay/v2/docs/{name}`.
- New features must include or update the relevant documentation.
- The doc index in `README.md` must be kept in sync with `docs/`.
- `AGENT_README.md` is the quick-start for autonomous agents — keep it
  concise and up to date.

## Code style

- Python: follow the existing style (ruff check + ruff format).
- Tests: run `pytest` before pushing. New features should include tests.
- No `__pycache__/`, `.pyc`, `dist/`, or generated images in commits.
