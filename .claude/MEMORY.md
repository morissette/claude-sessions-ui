# Claude Memory Index

Memory files for the `claude-sessions-ui` project. These capture decisions, patterns, and references extracted from session history that are not in `CLAUDE.md`.

- [decisions.md](memory/decisions.md) — Architectural and design decisions: single-file backend, SQLite cache semantics, time range routing, Docker peer dep fix, FTS5 search, Memory Explorer path traversal pattern, frontend conventions
- [feedback.md](memory/feedback.md) — User feedback patterns and preferred approaches: parallel agents via worktrees, sequential merges after rebase, Copilot comment workflow, cherry-pick over rebase -i for contaminated branches, launchd port ownership
- [references.md](memory/references.md) — PR history (all 17 PRs), feature plan docs in `docs/plans/`, infrastructure (launchd, Prometheus, Grafana)
