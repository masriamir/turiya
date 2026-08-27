# GitHub Copilot Instructions — turiya

Reviewer-focused notes. The full project guidance — purpose, file map, conventions,
logging schema, and the shared blocks (language, commits, branching, review loop) — lives
in [`AGENTS.md`](../AGENTS.md), which Copilot code review reads directly. Do not duplicate
it here.

## What to weight when reviewing

- **Layering is strict.** `operations/*` hold the logic and may import
  `config`/`keychain`/`restic`/`rclone`/`logging`/`scheduling`/`errors`. `cli.py` is thin —
  argument wiring and error-to-exit-code translation only. Nothing under `operations/` or
  the core modules may import `cli`.
- **Public API and JSONL schema are frozen.** `config.load` and `operations.*.run`
  signatures, and the JSONL log envelope, must stay byte-compatible with v1.0.0. Flag any
  change to either as breaking.
- **No hardcoded paths, repo names, retention values, or credentials** — they belong in
  `config.toml` and its pydantic model.
- **Errors** are `TuriyaError` subclasses raised from `operations/*`; only `cli.py` maps
  them to exit codes. Never `sys.exit` from an operation.
- **All JSON via `json.dumps`**; all logging via `StructuredLogger`. No parallel logging
  mechanism, no hand-built JSON strings.
- **Gates:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy src tests`, `uv run ty check` — all clean, zero warnings.
