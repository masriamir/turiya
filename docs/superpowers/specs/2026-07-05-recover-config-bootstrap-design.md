# `turiya recover-config` — Bootstrap Config Recovery — Design & ADR

Date: 2026-07-05
Status: Proposed (blocked on issue #12)
Sub-project: automates one step of the manual `RECOVERY.md` disaster-recovery
runbook.

## Purpose

`RECOVERY.md` (see the companion PR) documents restoring turiya's backups
onto a replacement Mac. Its step 3 — recreating `~/.config/turiya/config.toml`
— is the weakest link in that procedure: without a backed-up copy, the
operator reconstructs it from memory plus `config.example.toml`, risking
silently wrong retention/schedule/exclude settings at the exact moment
they're least able to double-check anything.

This ADR designs `turiya recover-config`: given only a bare repo URL and the
restic password (both of which the operator already needs per
`RECOVERY.md`'s prerequisites), it restores `config.toml` directly from the
latest snapshot — no existing `config.toml` required to run it. This turns
step 3 from "reconstruct from memory" into "run one command," provided the
config is actually in the snapshot to begin with.

## Context

- The design for `RECOVERY.md` explicitly deferred this: *"Automating any
  part of the recovery procedure ... If the manual procedure proves painful
  enough to warrant this, that's a future design, not this one."* This is
  that future design.
- [Issue #12](https://github.com/masriamir/turiya/issues/12) tracks making
  `turiya backup` implicitly include `config.toml` as a backup source. That
  issue is a **hard prerequisite** for this one: `recover-config` has
  nothing to restore until some snapshot actually contains `config.toml`.
  This ADR's design can be reviewed and accepted now, but implementation is
  blocked until #12 ships.
- Every other operation's `run()` takes `cfg: Config` as its first parameter
  and uses `StructuredLogger` (see `CLAUDE.md`'s "How to add a new
  operation"). This operation is the one place in the codebase where that
  doesn't apply — see Design §3.
- Mechanism verified against a real scratch restic repo before writing this
  design (not assumed):
  ```bash
  export RESTIC_PASSWORD="dry-run-password"
  restic init -r /tmp/repo
  restic backup -r /tmp/repo /tmp/home/.config/turiya/config.toml
  restic ls -r /tmp/repo latest --recursive --json   # → node with name="config.toml", type="file", exact path
  restic dump -r /tmp/repo latest "<that exact path>" > /tmp/dest/config.toml
  ```
  → the dumped file's content matched the original byte-for-byte. Error
  paths were also verified: `restic ls` on a snapshot-less repo yields a
  JSON `exit_error` (`"no snapshot found"`); `restic dump` on a bad path
  fails with plain-text `Fatal: cannot dump file: path "..." not found in
  snapshot` on stderr (not JSON — unlike the rest of `restic.py`'s parsed
  event stream).

## Scope

**In scope**

- `restic.find_path()` / `restic.dump_file()` — two new thin wrappers in
  `src/turiya/restic.py`.
- `operations/recover_config.py::run()` — the new operation.
- `turiya recover-config` CLI command.
- Unit tests (subprocess mocked) + one integration test against a real
  local restic repo + a CLI test.
- README/CLAUDE.md doc updates (new command in the CLI reference and file
  map) and a `RECOVERY.md` update once this ships, replacing step 3's
  "reconstruct from memory" framing with "run `turiya recover-config`
  first."

**Out of scope**

- Issue #12 itself (config.toml auto-included as a backup source) — a
  separate, already-filed piece of work this depends on.
- Automating any other `RECOVERY.md` step (prerequisite install, `git
  clone`, `rclone config` OAuth, Keychain population, the final
  `turiya restore`). Those either can't be automated (OAuth needs a human
  in a browser) or don't have the same "impossible without this tool"
  quality that step 3 does. A broader `turiya recover` wizard remains a
  possible future design — deliberately not this one, hence the narrower
  `recover-config` name.
- Any change to the documented public API listed in `CLAUDE.md`'s "what not
  to touch" (`config.load`, `operations.*.run` for the five existing
  operations) — this adds a sixth operation, it doesn't touch the existing
  five.

## Design

### 1. Command shape

```bash
turiya recover-config --repo rclone:gdrive:turiya-backups
turiya recover-config --repo rclone:gdrive:turiya-backups --target /tmp/inspect-first.toml
turiya recover-config --repo rclone:gdrive:turiya-backups --force
```

- `--repo` (required): a bare repo URL, e.g. `rclone:gdrive:turiya-backups`
  or a local path — not a config-resolved repo name, since there's no config
  yet to resolve it from.
- `--target` (optional): defaults to `config.resolve_config_path(None)` —
  reusing the exact function `config.load()` already calls internally
  (`TURIYA_CONFIG` env var, else `~/.config/turiya/config.toml`), so the
  default is guaranteed to match the real path with no new resolution logic.
- `--force` (optional flag): required to overwrite an existing file at the
  target; refuses otherwise with a `ConfigError` before any restic call is
  made.
- Password: `RESTIC_PASSWORD` env var if set, else an interactive hidden
  prompt (`typer.prompt(..., hide_input=True)`) in `cli.py`. No `--password`
  flag — this command is used exactly once, under stress, on a machine that
  doesn't have your shell history yet; there's no scripting use case to
  justify the plaintext-in-history risk.

### 2. Restic primitives (new, in `src/turiya/restic.py`)

```python
def find_path(repo: str, snapshot: str, *, password: str, name: str) -> str:
    """Return the exact snapshot path of the single file node named `name`."""
    ...

def dump_file(repo: str, snapshot: str, path: str, *, password: str) -> bytes:
    """Return the raw bytes of a single file from a snapshot."""
    ...
```

- `find_path` runs `restic ls <snapshot> --recursive --json`, parses each
  JSONL line, filters for `message_type == "node"`, `type == "file"`,
  `name == name`. Raises `ResticError` if zero matches ("no `config.toml`
  found in this repo's latest snapshot — is issue #12 in place, and does
  this repo have a snapshot taken after it shipped?") or more than one match
  (ambiguous — refuses rather than guessing which one).
- `dump_file` runs `restic dump <snapshot> <path>`, returns stdout bytes
  as-is, and raises `ResticError` with restic's raw stderr text on non-zero
  exit — `dump`'s errors are plain text, not the JSON `exit_error` shape the
  rest of `restic.py` parses, so this path does not reuse `parse_event`.

Both commands were exercised for real against a scratch repo (Context
above) before this design was written.

### 3. Operation layering — a deliberate, narrow exception

```python
def run(*, repo: str, password: str, target: Path, force: bool = False) -> bool:
```

This does **not** take `cfg: Config`, and does **not** construct a
`StructuredLogger`. Every other operation does both (`CLAUDE.md`'s "How to
add a new operation" convention). This operation's entire reason to exist is
to run *before* a `Config` can be loaded — there is nothing to build a
`Config` or a `StructuredLogger.config.logging` from. It prints a single
plain confirmation line to stdout on success:
`Recovered {target} from {repo} (latest snapshot).` — the same
"print directly, no JSONL" precedent `status`/`query` already established
for output that isn't part of the backup/restore logging schema. This is
the one deliberate exception in the codebase to the `cfg: Config`-first
convention, and it's recorded here rather than left to look like an
oversight in code review.

### 4. Error handling

- `target.exists() and not force` → `ConfigError`, raised before any restic
  subprocess runs at all.
- Zero snapshots, zero/multiple `config.toml` matches, or a `dump` failure
  → `ResticError`, message never swallowed (project convention).
- `cli.py`'s `recover-config` command catches `TuriyaError` exactly like
  every other command: clean stderr message, `typer.Exit(code=1)`.

### 5. Testing

- **Unit** (`tests/test_restic.py`): `find_path`/`dump_file` with
  `subprocess.run` mocked — zero-match, multi-match, and happy-path JSONL
  parsing; `dump_file`'s plain-text (non-JSON) error path.
- **Unit** (`tests/test_recover_config.py`, new): `run()` with `restic.*`
  mocked — happy path, existing-target-without-force refusal,
  existing-target-with-force overwrite.
- **Integration** (`tests/integration/`, new): a real local restic repo,
  backing up a fake `config.toml`, then calling `run()` for real and
  asserting the recovered file's content and location — matching the
  existing integration-test pattern (`restic init` a temp repo,
  `RESTIC_PASSWORD` env).
- **CLI** (`tests/test_cli.py`): the new subcommand, using `RESTIC_PASSWORD`
  env to skip the interactive prompt (matching how other CLI tests already
  avoid Keychain/prompts).

## Decisions & alternatives considered (ADR)

- **Mechanism: `restic ls --json` + `restic dump`** (vs. `restic restore`
  into a scratch dir then locating-and-copying the file out). Chosen:
  restic's `restore` preserves the file's *original absolute path* nested
  under `--target` (confirmed during `RECOVERY.md`'s own verification) — on
  a replacement Mac, the original username/path is unknown, so a restore-
  based approach would still need to walk the scratch tree to find the
  file, plus manage a temp-directory lifecycle. `ls` + `dump` finds the
  exact snapshot path and streams the content directly to the real
  destination in two commands, no temp directory, no cleanup path to get
  wrong. Verified working end-to-end against a scratch repo before this
  decision was finalized, not chosen on paper alone.
- **Command name: `recover-config`, not `recover`** (vs. a generic
  `turiya recover` that might later grow to wrap more of `RECOVERY.md`).
  Chosen to keep this command's contract narrow and honest about what it
  does — restores exactly one file. A broader wizard-style command, if ever
  built, gets its own name and its own design rather than silently
  expanding this one's scope.
- **Password: prompt + `RESTIC_PASSWORD` env, no `--password` flag** (vs.
  matching `turiya setup --password` for consistency). Rejected matching
  `setup`: this command is run once, under stress, on a fresh machine with
  no shell history hygiene established yet — there's no repeat-invocation
  scripting use case here to justify a plaintext-argv password, unlike
  `setup` (which is also re-run routinely for config changes).
- **Overwrite: refuse by default, `--force` to proceed** (vs. always
  overwriting silently). Chosen for the same reason the project generally
  treats overwrites/destructive actions as opt-in: an operator accidentally
  re-running this on a machine that already has a real `config.toml` should
  not have it silently clobbered by an old snapshot's version.
- **Target default: reuse `config.resolve_config_path(None)`** (vs.
  re-deriving the `TURIYA_CONFIG`-env-or-default logic locally). Chosen
  because the function already exists and is exactly the logic
  `config.load()` uses — reusing it means the default can never drift out
  of sync with what `turiya` actually treats as "the config path."
- **Layering: `cfg: Config`-less operation, no `StructuredLogger`** (vs.
  forcing this into the existing operation shape, e.g. by accepting a
  partially-populated or dummy `Config`). Rejected fabricating a `Config`:
  it would be a fiction (there's no real `[keychain]`/`[logging]`/`[[repo]]`
  data to put in it at this point in the recovery flow), and would obscure
  the actual reason this operation is different — it deliberately runs
  before configuration exists.

## Consequences & trade-offs

- ➕ Closes the weakest link in `RECOVERY.md` — once #12 ships, "recreate
  `config.toml`" becomes a single verified command instead of a
  memory-reconstruction exercise.
- ➕ New restic primitives (`find_path`/`dump_file`) are generically useful
  (any future "pull one known file out of a snapshot" need reuses them),
  not single-purpose plumbing.
- ➖ This is the one operation in the codebase that doesn't follow the
  `cfg: Config`-first / `StructuredLogger` convention — future maintainers
  need this ADR (or the code comment pointing at it) to understand why,
  rather than assuming it's an inconsistency to "fix."
- ➖ Cannot ship or be meaningfully tested end-to-end until issue #12 lands
  (the integration test can prove the mechanism works against a repo that
  *does* contain `config.toml`, but can't prove real-world snapshots contain
  it until #12's implementation is what puts it there).
- ➖ `RECOVERY.md` will need a follow-up edit once this ships, to point step
  3 at `turiya recover-config` instead of "reconstruct from memory" — not
  done in this ADR, since the command doesn't exist yet.

## Success criteria

- `turiya recover-config --repo <url>` restores `config.toml` from the
  latest snapshot to the resolved default target, refusing to overwrite an
  existing file without `--force`.
- `restic.find_path`/`dump_file` unit tests cover zero-match, multi-match,
  and the plain-text `dump` error path.
- An integration test proves the mechanism against a real local restic
  repo, not just mocks.
- No change to any of the five existing operations' signatures or the
  JSONL logging schema.
- All four gates (`pytest`, `ruff check`, `mypy`, `ty check`) clean.
- Explicitly blocked on, and documented as depending on, issue #12.
