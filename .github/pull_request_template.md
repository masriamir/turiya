<!-- See CONTRIBUTING.md before opening. -->

## What & why

<!-- Summary of the change and the motivation. Link any related issue: Closes #123 -->

## Type of change

- [ ] `fix` — bug fix
- [ ] `feat` — new feature
- [ ] `feat!` / `fix!` — breaking change
- [ ] docs / chore / ci / refactor (no behavior change)

## Checklist

- [ ] Branched off `main`; commits follow Conventional Commits
- [ ] Gates pass locally: `pytest`, `ruff check`, `ruff format --check`, `mypy src tests`, `ty check`
- [ ] Tests added/updated (unit with subprocess mocked; integration if it touches restic)
- [ ] `uv.lock` in sync with `pyproject.toml` (if deps changed)
- [ ] No change to the documented public API or JSONL logging schema (or it's deliberate and coordinated — see `CLAUDE.md`)
- [ ] Docs updated (`README.md` / `CLAUDE.md` file map) if behavior or surface changed
