# Auto-Include `config.toml` as an Implicit Backup Source — Design & ADR

Date: 2026-07-05
Status: Proposed
Sub-project: closes [issue #12](https://github.com/masriamir/turiya/issues/12);
unblocks the already-designed, currently-blocked
`docs/superpowers/specs/2026-07-05-recover-config-bootstrap-design.md`
(`turiya recover-config`).

## Purpose

`~/.config/turiya/config.toml` (or whatever `TURIYA_CONFIG` resolves to) is
currently a single point of failure: it's not in any repo's backed-up
`sources`, and lives nowhere but the machine running `turiya`. `RECOVERY.md`'s
disaster-recovery procedure currently asks the operator to reconstruct it
from memory plus `config.example.toml` if they don't have an out-of-band
copy — easy to get retention/schedule/excludes subtly wrong at exactly the
moment they're least able to double-check anything.

This design makes `turiya backup` always include the resolved config path as
an extra backup target, unconditionally, so the file that makes every other
`turiya` command work is never the one thing an operator forgets to back up.

## Context

- Raised while designing `RECOVERY.md` (companion PR); tracked as its own
  issue since it's a code change, not a docs one.
- `docs/superpowers/specs/2026-07-05-recover-config-bootstrap-design.md`
  designs `turiya recover-config`, a command that restores `config.toml`
  directly from a snapshot on a bare machine. That design is **blocked on
  this issue shipping** — it has nothing to restore until some snapshot
  actually contains `config.toml`. This design doesn't implement
  `recover-config`; it's the prerequisite that makes it viable.
- `config.resolve_config_path(explicit: Path | None = None) -> Path`
  (`src/turiya/config.py:80`) already exists and is exactly the logic
  `config.load()` uses internally (`TURIYA_CONFIG` env var, else
  `~/.config/turiya/config.toml`). Reusing it here means the implicit
  backup target can never drift out of sync with what `turiya` actually
  treats as "the config path" — and it's the same function
  `recover-config`'s design already commits to for its own default target,
  so both sides of this feature agree on "the config path" by construction.
- `operations/backup.py::resolve_targets()` already assembles the effective
  per-run target list (default `cfg.sources`, or the override matches from
  `--include`/`--pattern`/`--glob`) — the natural, single place to fold this
  in, as the issue itself anticipated.
- **Verified restic behavior (empirical, not assumed):** whether an
  `--exclude` pattern can silently swallow the implicit config target was an
  open question raised in review. Tested against a real scratch repo
  (`restic 0.19.0`) before finalizing this design:

  ```bash
  export RESTIC_PASSWORD=testpass
  restic init -r ./repo --quiet
  # Test 1: config.toml passed as an explicit positional target, alongside
  # a bare pattern exclude that matches its filename.
  restic backup -r ./repo ./source/Documents.txt \
    ./source/.config/turiya/config.toml --exclude='*.toml' --quiet
  # → config.toml IS present in the resulting snapshot's tree.

  # Test 2: same exclude, but config.toml is only reachable via directory
  # recursion (the parent dir is the target, not the file itself).
  restic backup -r ./repo ./source/.config --exclude='*.toml' --quiet
  # → config.toml is NOT present — the exclude took effect.

  # Test 3: same exclude, BOTH the parent dir (a traversal path that would
  # exclude it) AND the file itself (an explicit target) passed together.
  restic backup -r ./repo ./source/.config \
    ./source/.config/turiya/config.toml --exclude='*.toml' --quiet
  # → config.toml IS present — the explicit target wins even when the same
  #   path is simultaneously reachable via an excluded traversal path.
  ```

  **Conclusion:** restic's `--exclude` patterns apply only to files
  discovered via directory recursion, never to files passed as explicit
  positional targets — and this holds even when the same file is also
  reachable through an excluded traversal path. Since `resolve_targets()`
  appends the config path as its own explicit target (never folded into a
  directory scan), it is structurally immune to `cfg.excludes` / `--exclude`
  by restic's own native behavior. No client-side pattern-matching or
  exclude-filtering guard is needed — and building one would have been
  actively wrong, since a naive guard would need to strip the offending
  exclude pattern *globally* (e.g. dropping `*.toml` entirely would also
  stop excluding the user's own `*.toml` files elsewhere in their real
  `sources`), which is a much bigger, unwanted side effect than the problem
  it would solve.

## Scope

**In scope**

- `resolve_targets()` in `src/turiya/operations/backup.py` always appends
  `str(config.resolve_config_path(None))` to the computed target list.
- One `log.log_human(...)` line announcing the inclusion.
- `README.md`, `config.example.toml`, and `RECOVERY.md` updates so the docs
  don't contradict the new behavior.
- Integration tests proving: plain-run inclusion, survival under a
  `--glob`/`--pattern`/`--include` override, and survival under a
  `cfg.excludes` pattern that matches the config filename.

**Out of scope**

- `turiya recover-config` itself — separate, already-designed, blocked on
  this shipping (see Context above).
- Any config toggle to disable this (e.g. `backup.include_own_config`) — see
  Decisions below.
- Any change to the documented public API in `CLAUDE.md`'s "what not to
  touch" (`operations.backup.run`'s signature is unchanged; only its
  internal `resolve_targets()` helper gains a line).

## Design

### 1. Mechanism

In `resolve_targets()`:

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
        # ... existing include/pattern/glob resolution, unchanged ...
        # (returns None early if any of them matched nothing)
    targets.append(str(config.resolve_config_path(None)))
    return targets
```

The config path is appended **after** the existing early-return-`None`
checks for a no-match override, so an override that matches nothing still
fails the run exactly as it does today (`"ERROR: include/pattern/glob
matched no files."`) rather than silently succeeding with only the config
file backed up.

### 2. No config toggle — always on

No `[backup]` table, no `include_own_config` flag. The issue raised this as
an open question; decided against it: the entire motivation is "this file
must never be the one thing you forget," which a silent-by-default toggle
would undermine, and it's one more config surface for a codebase that
already tries to keep config minimal (`CLAUDE.md`: "don't hardcode a path...
it belongs in config.toml" — the inverse principle here is not every
runtime behavior needs to become configurable either). If a real need to
exclude it ever surfaces, that's a new, deliberate design, not a default
this ships with.

### 3. Survives `--include`/`--pattern`/`--glob` overrides

Today, these flags fully *replace* the default `cfg.sources` list for that
run. Decided that the implicit config target should be appended
unconditionally, regardless of which branch computed `targets` — a scoped,
one-off backup run (e.g. "just back up this one folder right now") should
not have to also remember `--include ~/.config/turiya/config.toml` to keep
the guarantee intact. The cost of always including one small file is
negligible next to the cost of a silent gap in the one run where a user
happened to use an override flag.

### 4. Exclude immunity — verified, not assumed

See Context above. `cfg.excludes` / `--exclude` are passed to restic
unchanged; the implicit config target is immune to them by restic's own
positional-argument semantics, not by any special-case code in this
codebase. This is the single most important property of this design and is
locked in by a regression test (see Testing).

### 5. Visibility

One line before the per-repo backup loop:

```python
log.log_human(f"Including own config: {config_path}")
```

Matches the existing `log_human` pattern (e.g. the `--- Repository: {url}
---` line) — a human reading `backup.log` can see this happened without
grepping JSONL. No new JSONL event type; the config path shows up in the
normal `file`/`summary` events like any other backed-up path.

### 6. Docs updated in the same change

- `README.md`: backup section notes that turiya's own config is always
  included as an implicit source.
- `config.example.toml`: a comment near `sources` noting `config.toml`
  itself doesn't need to be listed there — it's always included.
- `RECOVERY.md`: prerequisites checklist item 2 currently states
  `config.toml` "is **not currently backed up by `turiya` itself**" —
  corrected to reflect that it now is, once this ships, with the manual
  keep-a-copy advice demoted to a belt-and-suspenders recommendation rather
  than the only safety net.

## Decisions & alternatives considered (ADR)

- **Append in `resolve_targets()`, not in `run()` after calling it.**
  Chosen because `resolve_targets()` is already the "assemble the effective
  source list for this run" function (the issue itself anticipated this),
  keeping all target-list logic in one place rather than splitting it
  across two functions.
- **No exclude-filtering guard logic** (vs. detecting and stripping exclude
  patterns that would match the config filename before invoking restic).
  Rejected after empirical verification showed it's unnecessary — restic
  already never applies excludes to explicit positional targets. Building a
  guard anyway would require either (a) globally stripping a matching
  exclude pattern, which would also stop excluding the user's own files
  matching that pattern elsewhere in their `sources` (a bigger, unwanted
  side effect), or (b) reimplementing restic's own glob-matching semantics
  in Python for no behavioral gain. Neither is worth the complexity for a
  property restic already guarantees.
- **Always on, no config toggle** (vs. `backup.include_own_config = true`
  suggested in the issue). Rejected the toggle: it adds a config surface and
  a silent way to defeat the feature's entire purpose, for a scenario (a
  user who deliberately wants their own config excluded from backup) with
  no concrete motivating use case.
- **Survives target-list overrides** (vs. only applying to unscoped/default
  runs). Chosen so the guarantee is unconditional — see Design §3.
- **Reuse `config.resolve_config_path(None)`** (vs. deriving the
  `TURIYA_CONFIG`-or-default path locally in `backup.py`). Chosen because
  the function already exists, is exactly what `config.load()` uses, and is
  the same function `recover-config`'s design already commits to — keeping
  both features' notion of "the config path" identical by construction
  rather than by convention.

## Consequences & trade-offs

- ➕ Closes the weakest link identified while writing `RECOVERY.md`: once
  this ships, `config.toml` is backed up like any other file, in every
  repo, every run, immune to exclude misconfiguration.
- ➕ Unblocks `turiya recover-config`'s design
  (`2026-07-05-recover-config-bootstrap-design.md`), which currently has
  nothing to restore.
- ➕ The exclude-immunity property is restic's own behavior, verified
  empirically — no new code paths to maintain or get subtly wrong later.
- ➖ `RECOVERY.md` needs a follow-up edit in this same change (see Design
  §6) or it will actively contradict the new behavior.
- ➖ A user who — for some reason — genuinely wants `config.toml` excluded
  from backup has no supported way to do that. Considered acceptable per
  the "always on" decision above; revisit only if a real use case surfaces.

## Testing

Extend `tests/integration/test_backup.py` (the existing pattern — no unit
test file exists for `backup.py`; its tests are integration-only against a
real local restic repo per `CLAUDE.md`'s testing convention):

1. **Plain run:** `backup.run(cfg)` → the resulting snapshot's paths include
   the harness's resolved config path.
2. **Override survival:** `backup.run(cfg, glob=("todo.md",))` → the
   snapshot still includes the resolved config path alongside the glob
   match.
3. **Exclude immunity (regression test locking in the verified restic
   behavior):** harness config with `excludes = ["*.toml"]` (or an
   equivalent bare pattern matching the config's filename) → `backup.run(cfg)`
   still includes the config path in the snapshot.

## Success criteria

- Every `turiya backup` run — default, or with any `--include`/`--pattern`/
  `--glob` override — includes the resolved `config.toml` path as a target,
  in every configured repo.
- No `[backup]` config table, no opt-out toggle.
- The exclude-immunity property is covered by an integration test, not just
  asserted in this doc.
- `README.md`, `config.example.toml`, and `RECOVERY.md` no longer contradict
  the new behavior.
- No change to `operations.backup.run`'s public signature or the JSONL
  logging schema.
- All four gates (`pytest`, `ruff check`, `mypy`, `ty check`) clean.
