# Contributing to turiya

Thanks for your interest. turiya is a library-first Python 3.14 package; the
architecture and conventions are documented in
[`CLAUDE.md`](.claude/CLAUDE.md) — read it before making changes.

## Development setup

turiya uses [uv](https://docs.astral.sh/uv/). Run everything through it:

```bash
uv sync --all-extras --dev   # install deps into the managed venv
uv run turiya --help         # run the CLI
```

Do not activate the venv manually. Add runtime deps with `uv add`, dev deps
with `uv add --dev`; `uv.lock` is committed and must stay in sync with
`pyproject.toml`.

This is the contributor/dev workflow and stays canonical for the gates and
test loop, even though end users run `turiya ...` directly (see the
`Makefile`/README "Install" section). If you want the on-PATH `turiya`
command to reflect your local changes, run `make install` to refresh the
pinned install — `uv run turiya ...` always reflects source edits immediately
and needs no extra step.

## Required gates

All four must be clean before a PR can merge (CI enforces them as the `gates`
check on every pull request):

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run ty check
```

`uv run ruff format .` fixes formatting in place.

## Releasing (maintainers)

After bumping `version` in `pyproject.toml` and adding the matching entry to
`CHANGELOG.md`, run `make release` from `main`. It reads the version from
`pyproject.toml`, slices the corresponding `CHANGELOG.md` section for the
release notes, then tags, pushes, and publishes a GitHub release — all in
one step. `refs/tags/v*` are protected (no deletion, no force-push), so
double-check the version and CHANGELOG entry before running it.

## Pull requests

- Branch off `main`; direct pushes to `main` are blocked.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
  (e.g. `feat:`, `fix:`, `fix(cli):`, `feat!:` for breaking changes).
- Keep the CLI thin: business logic lives in `operations/*` and the layers
  below it, never in `cli.py` (see the layering rule in `CLAUDE.md`).
- Don't change the documented public API, the JSONL logging schema, or
  hardcode paths/repos/credentials — these are called out under
  "What not to touch" in `CLAUDE.md`.
- Add tests: unit tests with subprocess mocked; an integration test against a
  real temp restic repo if the change touches restic.

## Reporting issues

Use the issue templates. For bugs, include your macOS version, restic/rclone
versions, and the relevant lines from the JSONL logs under `logging.dir`
(redact any paths or remote names you'd rather not share).
