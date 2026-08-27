<!-- See CONTRIBUTING.md before opening. -->

## What & why

<!-- Summary of the change and the motivation. Link any related issue: Closes #123 -->

## Type of change

- [ ] `fix` — bug fix
- [ ] `feat` — new feature
- [ ] `feat!` / `fix!` — breaking change
- [ ] docs / chore / ci / refactor (no behavior change)

## Checklist

- [ ] Branched off `main`; the **PR title** is a Conventional Commit (it becomes the squash commit, the changelog entry, and the version bump)
- [ ] Gates pass locally: `make gates`
- [ ] `make meta-check` clean (no drift from the pinned canonical sources)
- [ ] Tests added/updated (unit with subprocess mocked; integration if it touches restic)
- [ ] `uv.lock` in sync with `pyproject.toml` (if deps changed)
- [ ] No change to the documented public API or JSONL logging schema (or it's deliberate and coordinated — see `AGENTS.md`)
- [ ] Docs updated (`README.md` / `AGENTS.md` file map) if behavior or surface changed
