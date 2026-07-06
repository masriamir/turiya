# Auto-Include `config.toml` as an Implicit Backup Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `turiya backup` always include the resolved `config.toml` path
as an extra backup target — unconditionally, immune to excludes, and
surviving `--include`/`--pattern`/`--glob` overrides — closing issue #12 and
unblocking `turiya recover-config` (already implemented in a separate PR,
currently with nothing real-world to restore until this ships).

**Architecture:** One-line addition to `operations/backup.py::resolve_targets()`
appending `str(cfg.config_path)` to whichever target list was computed; a
`log_human` visibility line in `run()`; doc updates so
`README.md`/`config.example.toml`/`RECOVERY.md` no longer contradict the new
behavior.

**Tech Stack:** Python 3.14, existing restic/pydantic stack, no new
dependencies.

> **Amendment (PR #18 review).** Everywhere below that references
> `config.resolve_config_path(None)` describes the plan as originally
> written. The shipped code instead uses **`cfg.config_path`** — a new
> `Config` property (backed by a `PrivateAttr` set in `config.load()`)
> holding the exact path the `Config` was actually loaded from — because
> re-deriving the path from `TURIYA_CONFIG`/the default would back up the
> wrong file for a `Config` loaded via an explicit `load(path=...)`. A
> duplicate-target guard was also added (skip appending if the config path
> is already in the computed target list).

## Global Constraints

- No `[backup]` config table, no opt-out toggle (`backup.include_own_config`
  or similar) — always on, per the accepted spec's Decision.
- The implicit config target is appended **after** the existing
  early-`None`-return checks for a no-match `--include`/`--pattern`/`--glob`,
  so a matching-nothing override still fails the run exactly as today
  (`"ERROR: include/pattern/glob matched no files."`), not silently
  succeeding with only the config file backed up.
- Use `cfg.config_path` (the actual path this `Config` was loaded from) —
  don't re-derive `TURIYA_CONFIG`-or-default logic locally in `backup.py`,
  and don't call `config.resolve_config_path(None)` independently of `cfg`,
  since that can diverge from an explicit `load(path=...)` call.
- No client-side exclude-filtering guard code — the implicit target's
  immunity to `cfg.excludes`/`--exclude` comes from restic's own
  positional-argument semantics (verified empirically in the spec), not
  from anything this codebase implements.
- No change to `operations.backup.run`'s public signature or the JSONL
  logging schema.
- `backup.py` has no unit test file — its tests are integration-only against
  a real local restic repo, per this project's existing testing convention
  (matches `tests/integration/test_backup.py`'s current structure).
- All four gates (`pytest`, `ruff check`, `ruff format --check`, `mypy src
  tests`, `ty check`) clean before every commit.

---

### Task 1: `resolve_targets()` change + integration tests

**Files:**
- Modify: `src/turiya/operations/backup.py`
- Modify: `tests/integration/test_backup.py`

**Interfaces:**
- Consumes: `cfg.config_path -> Path` (a `Config` property added in
  `src/turiya/config.py`, backed by a `PrivateAttr` set in `config.load()`
  to the exact path loaded).
- Produces: no new public interface on `operations/backup.py` —
  `resolve_targets()`'s signature and `run()`'s signature are unchanged;
  only their internal behavior changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_backup.py`:

```python
def test_plain_backup_includes_own_config(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == str(harness_config) for p in paths)


def test_glob_override_still_includes_own_config(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p.endswith("todo.md") for p in paths)
    assert any(p == str(harness_config) for p in paths)


def test_glob_no_match_still_returns_false_despite_own_config(harness_config: Path) -> None:
    # Regression guard for the Global Constraint: a no-match override must
    # still fail the run, not silently succeed with only config.toml backed up.
    cfg = config.load()
    assert backup.run(cfg, glob=("*.nonexistent-xyz",)) is False


def test_exclude_matching_config_filename_does_not_exclude_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restic_repos: list[Path],
    source_tree: Path,
) -> None:
    # Regression test locking in the spec's empirically-verified restic
    # behavior: cfg.excludes matching the config filename must not exclude
    # the implicit config target, because restic never applies --exclude to
    # explicit positional targets (only to files found via directory
    # recursion). This uses its own config (not harness_config) because it
    # needs excludes = ["*.toml"], which harness_config hardcodes differently.
    own_config = tmp_path / "config.toml"
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    own_config.write_text(
        f'sources = ["{source_tree}"]\nexcludes = ["*.toml"]\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(own_config))
    monkeypatch.setenv("RESTIC_PASSWORD", "testpass123")

    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == str(own_config) for p in paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_backup.py -k "includes_own_config or override_still_includes or does_not_exclude" -v`
Expected: FAIL — the first three fail their `assert any(p == str(harness_config) ...)` / `str(own_config)` checks (the config path isn't in `paths` yet); `test_glob_no_match_still_returns_false_despite_own_config` should already PASS unmodified (it's a regression guard for existing behavior, included here for completeness alongside the new tests — verify it still passes both before and after Step 3).

- [ ] **Step 3: Implement the change in `backup.py`**

Modify `src/turiya/operations/backup.py`. Change the import line:

```python
from ..config import Config
```

to:

```python
from ..config import Config, resolve_config_path
```

Replace `resolve_targets()` entirely with:

```python
def resolve_targets(
    cfg: Config,
    *,
    include: Sequence[str],
    pattern: Sequence[str],
    glob: Sequence[str],
) -> list[str] | None:
    """Return target paths, or None if a pattern/glob/include matched nothing."""
    if not (include or pattern or glob):
        targets = [str(s) for s in cfg.sources]
    else:
        targets = []
        for path in include:
            from pathlib import Path

            if not Path(path).exists():
                return None
            targets.append(path)
        for pat in pattern:
            matches = [m for s in cfg.sources for m in _find(str(s), "-path", f"*{pat}*")]
            if not matches:
                return None
            targets.extend(matches)
        for g in glob:
            matches = [m for s in cfg.sources for m in _find(str(s), "-name", g)]
            if not matches:
                return None
            targets.extend(matches)
    targets.append(str(resolve_config_path(None)))
    return targets
```

In `run()`, immediately after the existing `if targets is None:` block (i.e.,
right before the `exclude_flags = [...]` line), add:

```python
    log.log_human(f"Including own config: {resolve_config_path(None)}")
```

So that section of `run()` reads:

```python
    targets = resolve_targets(cfg, include=include, pattern=pattern, glob=glob)
    if targets is None:
        log.log_human("ERROR: include/pattern/glob matched no files.")
        log.run_end(success=False)
        return False

    log.log_human(f"Including own config: {resolve_config_path(None)}")

    exclude_flags = [f"--exclude={p}" for p in (*cfg.excludes, *exclude)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_backup.py -v`
Expected: PASS (7 tests: 3 pre-existing + 4 new)

- [ ] **Step 5: Run the gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run ty check`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/operations/backup.py tests/integration/test_backup.py
git commit -m "feat(backup): always include config.toml as an implicit backup target"
```

---

### Task 2: Documentation — README, config.example.toml, RECOVERY.md

**Files:**
- Modify: `README.md`
- Modify: `config.example.toml`
- Modify: `RECOVERY.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `README.md`'s `turiya backup` CLI reference**

In `README.md`'s `### \`turiya backup\`` subsection, the current paragraph
immediately after the code block reads:

```markdown
`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `sources` for that run (the scheduled weekly backup, run with no flags, always uses the full `sources` list). `--exclude` is repeatable and adds to the configured `excludes` for that run only.
```

Append a new sentence to the end of that same paragraph:

```markdown
`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `sources` for that run (the scheduled weekly backup, run with no flags, always uses the full `sources` list). `--exclude` is repeatable and adds to the configured `excludes` for that run only. Every run also always includes turiya's own resolved config path as an implicit extra target — immune to `excludes`/`--exclude` — so `config.toml` itself is never the one thing a backup forgets; see `RECOVERY.md`.
```

- [ ] **Step 2: Update `config.example.toml`**

The current file starts:

```toml
# Example turiya configuration.
#
# Copy this file to ~/.config/turiya/config.toml (or point TURIYA_CONFIG at a
# copy elsewhere) and edit the values below to match your setup.
#
# Root-level keys (sources/excludes) must precede all [table]/[[array]]
# headers, otherwise TOML absorbs them into the preceding table.
sources = ["~/Documents", "~/Desktop", "~/Projects"]
excludes = [".DS_Store", "node_modules", "*.tmp"]
```

Insert one comment line right before `sources = [...]`:

```toml
# Example turiya configuration.
#
# Copy this file to ~/.config/turiya/config.toml (or point TURIYA_CONFIG at a
# copy elsewhere) and edit the values below to match your setup.
#
# Root-level keys (sources/excludes) must precede all [table]/[[array]]
# headers, otherwise TOML absorbs them into the preceding table.
#
# This file itself doesn't need to be listed in `sources` — turiya always
# backs up its own config as an implicit extra target, on every run.
sources = ["~/Documents", "~/Desktop", "~/Projects"]
excludes = [".DS_Store", "node_modules", "*.tmp"]
```

- [ ] **Step 3: Update `RECOVERY.md`'s prerequisites checklist item 2**

The current item 2 (after the merge with `main` already performed on this
branch) reads:

```markdown
- [ ] **A copy of `config.toml`.** This is **not currently backed up by
      `turiya` itself** — tracked in
      [issue #12](https://github.com/masriamir/turiya/issues/12). Until
      that lands, keep a copy of `~/.config/turiya/config.toml` alongside
      the password in whatever store holds it. If you don't have one,
      you'll reconstruct it from `config.example.toml` in step 3 below —
      you'll need to remember your `sources`, `excludes`, retention
      settings, and schedule.
```

Replace it with:

```markdown
- [ ] **A copy of `config.toml`** is no longer strictly required — since
      `turiya backup` always includes it as an implicit target (closing
      [issue #12](https://github.com/masriamir/turiya/issues/12)), `turiya
      recover-config --repo <your-repo-url>` (step 3 below) restores it
      directly from the repo's latest snapshot. Keeping a manual copy
      alongside the password is still a reasonable belt-and-suspenders
      backup, but no longer the only safety net.
```

- [ ] **Step 4: Verify placement**

Run: `grep -n "implicit\|no longer strictly required\|doesn't need to be listed" README.md config.example.toml RECOVERY.md`
Expected: one match in each of the three files.

- [ ] **Step 5: Commit**

```bash
git add README.md config.example.toml RECOVERY.md
git commit -m "docs: document config.toml's implicit backup inclusion"
```

---

### Task 3: Final gate check

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run ty check`
Expected: all clean.

- [ ] **Step 2: Confirm working tree is clean**

Run: `git status --short`
Expected: no output (all changes committed across Tasks 1–2).

## Self-Review Notes

- **Spec coverage:** mechanism (`resolve_targets()` appends the config path
  after existing early-returns) ✓ Task 1; no config toggle ✓ (not
  introduced anywhere in this plan); survives overrides ✓ Task 1's
  `test_glob_override_still_includes_own_config`; exclude immunity ✓ Task
  1's `test_exclude_matching_config_filename_does_not_exclude_it`
  (integration-level regression test, not just asserted in the spec doc);
  visibility log line ✓ Task 1 Step 3; docs (README, config.example.toml,
  RECOVERY.md) ✓ Task 2. No spec section lacks a task.
- **Placeholder scan:** no TBD/TODO; all code/doc blocks are complete,
  exact content.
- **Type consistency:** `resolve_targets(cfg: Config, *, include: Sequence[str], pattern: Sequence[str], glob: Sequence[str]) -> list[str] | None`
  and `run(cfg: Config, *, dry_run: bool = False, include: Sequence[str] = (), pattern: Sequence[str] = (), glob: Sequence[str] = (), exclude: Sequence[str] = ()) -> bool`
  are unchanged from the current codebase (verified against
  `src/turiya/operations/backup.py` before writing this plan) — no
  signature drift introduced.
