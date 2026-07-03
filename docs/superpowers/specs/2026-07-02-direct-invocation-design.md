# Direct `turiya` Invocation (`uv tool install`) — Design & ADR

Date: 2026-07-02
Status: Accepted
Sub-project: post-v2.0.0 roadmap — developer/operator ergonomics

This document is both the design spec and the architecture decision record for
making `turiya` directly callable on `PATH` (e.g. `turiya backup`) instead of
always going through `uv run turiya ...`.

> **Accepted (2026-07-02).** All design choices below are confirmed: pinned
> `uv tool install .` (§1); the launchd path resolved from `uv tool dir --bin`,
> with a **loud failure** if the installed command is missing rather than a
> silent fragile fallback (§2); auto-resolve keeping the existing `program`
> kwarg (§3); a `Makefile` (§4); `set_password` uses `-A` with an accepted
> logged-in-only boundary, and the plist PATH prepends `/opt/homebrew/bin`
> (Runtime environment & operational risks); and versioning as `2.1.0`. The
> design is accepted but **not yet implemented** — the code/template/docs
> changes land in the `2.1.0` implementation.

## Purpose

Let the operator (and the scheduled job) invoke `turiya` as a first-class
command on `PATH`, rather than only through `uv run turiya` from inside the
project directory. This is an **install/distribution** change, not a CLI code
change — the entry point already exists.

## Context

- The package **already declares a console entry point**:
  `pyproject.toml` → `[project.scripts] turiya = "turiya.cli:app"`, and
  `src/turiya/__main__.py` exists (so `python -m turiya` also works). `uv sync`
  already builds a `turiya` executable at `.venv/bin/turiya`; `uv run turiya`
  merely runs that through uv's managed environment. Nothing new needs to be
  authored in `cli.py`.
- `uv run turiya` has two ergonomic costs: it only works **from within the
  project directory**, and it adds uv's resolution overhead per invocation.
- **launchd does not use `uv run` today.** `operations/setup.py`'s
  `default_program()` returns `[sys.executable, "-m", "turiya", "backup"]` — the
  absolute path to whatever Python ran `turiya setup`. Under `uv run` that is
  `…/turiya/.venv/bin/python`: a **fragile pin** that breaks if the venv is
  recreated, the repo moves, or Python is bumped. The rendered plist's `PATH` is
  `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` — notably **not** including
  `~/.local/bin`.

### What `uv tool install` actually produces (verified 2026-07-02, uv 0.11.26)

A sandboxed install revealed the real layout:

```
<uv tool dir --bin>/turiya            # e.g. ~/.local/bin/turiya — symlink to…
  <uv tool dir>/turiya/bin/turiya     # /bin/sh trampoline that execs…
    <uv tool dir>/turiya/bin/python   # uv-managed CPython 3.14
```

- `uv tool dir` → `~/.local/share/uv/tools`; `uv tool dir --bin` → `~/.local/bin`.
  Both are supported commands and are the **public contract** for where uv puts
  tool environments and their executables.
- With `--editable`, the tool env's site-packages gains
  `_editable_impl_turiya.pth` pointing back at the repo `src/` — so every run
  imports the **live working copy**.

## Scope

**In scope**

- Install `turiya` on `PATH` via a **pinned** `uv tool install .` (§1).
- Unify the launchd invocation onto the installed command, resolved
  deterministically from `uv tool dir --bin` (§2) — fixes the `.venv` pin.
- A `Makefile` capturing install + dev + gates (§4).
- `keychain.set_password` gains `-A` so the unattended job's password read never
  prompts (see Runtime environment & operational risks).
- The launchd plist PATH prepends `/opt/homebrew/bin` so the job resolves
  `restic`/`rclone` on both Intel and Apple Silicon.
- Docs: make `turiya …` the primary user-facing invocation; keep `uv run …`
  as the contributor/dev workflow; document the `-A` trade-off and the
  logged-in-only boundary in the README security notes.
- A `2.1.0` release (CHANGELOG + tag).

**Out of scope**

- Publishing to PyPI / installability by others (explicitly personal,
  this-Mac-only).
- A standalone frozen binary (PyInstaller/shiv/pex).
- Any change to the documented public API (`config.load`, `operations.*.run`)
  or the JSONL logging schema.

## Design

### 1. Install mechanism — pinned `uv tool install .`

uv's tool installer (its `pipx` equivalent) installs the package into an
isolated, uv-managed environment and drops a `turiya` shim into
`uv tool dir --bin` (`~/.local/bin`):

```bash
uv tool install .            # snapshot copy of the code in the tool env
uv tool update-shell         # one-time: ensure ~/.local/bin is on PATH
turiya backup                # now works from anywhere
```

**Pinned (a real copy), not `--editable`.** The reconsidered rationale:

- The **scheduled backup must not depend on repo state.** With `--editable`, the
  tool env imports live from `~/workspace/turiya`; a moved repo, a mid-rebase
  tree, or a branch with a syntax error at fire time would break the backup
  **silently** — the worst failure mode for a tool you only lean on during a
  restore.
- The dev loop already runs through **`uv run`** (a confirmed decision), so
  editable's one advantage — reflecting source edits in the installed command —
  is **redundant**. Pinning costs nothing here and makes both the interactive
  command and the scheduled job immune to repo state.
- Refresh after a release with `uv tool install . --reinstall` (or
  `uv tool upgrade turiya`); this is a deliberate, explicit step rather than an
  implicit live link.

The tool env's interpreter is independent of the project `.venv`, so
`uv sync --reinstall` never affects the installed command.

### 2. launchd resolution — `uv tool dir --bin`, absolute

`operations/setup.py::default_program()` resolves the installed shim to an
**absolute path**, deterministically, from uv's public executable directory —
**not** from the ambient `PATH` (which `shutil.which` would depend on, making
the baked path vary by *how* setup was invoked):

```python
def _uv_tool_bin() -> Path | None:
    try:
        out = subprocess.run(
            ["uv", "tool", "dir", "--bin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out) if out else None


def default_program() -> list[str]:
    bin_dir = _uv_tool_bin() or Path("~/.local/bin").expanduser()
    shim = bin_dir / "turiya"
    if not shim.exists():
        raise SchedulingError(
            f"turiya is not installed on PATH (no executable at {shim}). "
            "Run `make install` (`uv tool install .`) before `turiya setup`, so "
            "the scheduled job is pinned to the installed command. "
            "To bake a specific path instead, pass program= to setup.run()."
        )
    return [str(shim), "backup"]
```

**Missing shim ⇒ loud failure, not silent fallback.** If the installed command
can't be resolved (e.g. `turiya setup` was run before `uv tool install`),
`default_program()` **raises `SchedulingError`** telling the operator to
`make install` first — rather than silently baking a `.venv`-pinned
`sys.executable -m turiya`, which would quietly reintroduce the exact fragility
this design removes. The only escape hatch is the explicit `program=` override
(used by tests and unusual layouts), which bypasses `default_program()` entirely.

Why this is the stable/well-defined choice:

- **Deterministic:** the path comes from uv's own reported bin dir, not from
  whatever `PATH` was active at setup time.
- **Public contract:** `~/.local/bin/turiya` is the executable uv officially
  installs and maintains; a baked absolute path to it survives
  `uv tool upgrade`/reinstall (the path is stable) and uv version changes.
- **PATH-immune:** an absolute path needs nothing added to the plist's minimal
  `PATH`.
- **uv only needed at setup time**, to compute the path once; launchd itself
  never invokes uv.

Rejected alternative — pointing `-m turiya` at
`<uv tool dir>/turiya/bin/python`: fewer indirections and closest to today's
code, but it hard-codes uv's **internal** env layout (a larger
implementation-detail bet than the public installed-executable location).

### 3. Configurability — auto-resolve, keep the existing kwarg

No new config surface. `default_program()` auto-resolves; the already-present
`setup.run(cfg, *, program=None)` kwarg remains the single override point (used
by tests and unusual layouts). Stays within the "don't hardcode a path — resolve
or configure it" convention without adding a `[scheduling] program` TOML key.

### 4. Bootstrap — a `Makefile`

```makefile
install:            ## Install `turiya` on PATH (pinned snapshot)
	uv tool install . --reinstall

dev:                ## Sync the dev environment
	uv sync --all-extras --dev

gates:              ## Run all required gates
	uv run pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests
	uv run ty check
```

`make install` is the per-machine (and post-release) step; `make gates` mirrors
the CI `gates` job.

### 5. Documentation changes

- **README** — user examples become `turiya backup`, etc., with a short
  "Install" section (`make install` / `uv tool install .` + `uv tool
  update-shell`) and the **install-before-setup** ordering note.
- **CONTRIBUTING** — canonical dev flow unchanged: `uv sync` + `uv run` for
  gates and tests. Note the two audiences (operator vs. contributor), and that
  after changing code you `make install` to refresh the on-PATH command.
- **CLAUDE.md** — add the `Makefile` to the file map; note the installed
  `turiya` and `uv run turiya` are the same entry point via two environments.

## Runtime environment & operational risks (launchd)

These risks are **largely pre-existing** — the current `.venv`-pinned plist
faces them too — but this ADR touches the launchd invocation and asserts a
working *unattended* backup, so they must be validated, not assumed. Making the
*invocation* robust does nothing for whether the invoked process can
*authenticate* and *find its tools* when launchd fires it non-interactively.

### Keychain access is the most likely silent failure

The scheduled backup runs with **no `RESTIC_PASSWORD` in its environment** (that
env var is only set transiently during setup's repo-init step). So every run
does a live `security find-generic-password -w` against the **login keychain**,
non-interactively, from a LaunchAgent (`keychain.get_password`). If the item's
ACL doesn't permit non-interactive reads, macOS raises an access prompt no one
answers → the backup hangs or fails.

**The framing that settles this:** unattended ⇒ no prompt ⇒ the item must be
silently readable ⇒ broad access. You cannot have both "no local process reads
it without approval" and "runs at 2am unattended." Scoping to `/usr/bin/security`
buys ~nothing against the only threat it could address (a same-user process,
which can just invoke `security` itself, Apple-signed and in the `apple-tool:`
partition), while adding fragility and a login-password chicken-and-egg (the
partition-list command needs `-k`). Stronger options (Touch ID / per-access
approval) are fundamentally incompatible with unattended operation.

**Decision — `set_password` uses `-A` (allow silent access).** (macOS 26.5.1 /
Tahoe; `/usr/bin/security`.)

```python
# keychain.set_password — add -A so headless reads never prompt
["security", "add-generic-password", "-a", account, "-s", service, "-w", pw, "-A"]
```

- Deterministic: no prompt in any session, independent of how the OS treats a
  default ACL from a non-interactive context.
- **Preserves the stated security model** — the password stays *in Keychain,
  never in a file or in git* (README's promise). `-A` only broadens
  *local-process* access, which is documented as an accepted trade-off.
- Rejected the `-T`/partition-list route: marginal real gain, OS-update
  fragility, and it would force a login-password prompt into `turiya setup`.

**Decision — locked keychain = accepted "logged-in only" boundary.** If the job
fires while logged out or at the login window (a state `pmset` wake can produce),
the login keychain is **locked** and `security` fails *regardless of ACL*. This
is documented as a known limitation: the scheduled backup requires an active
login session (an unlocked login keychain). No dedicated-keychain machinery — it
would only relocate the secret-storage problem.

Both are **implemented in this change**: `set_password` gains `-A`, and the
limitation is documented in the README security notes.

### Tool resolution in the plist's minimal PATH

The rendered plist sets a `PATH` in `EnvironmentVariables` that must resolve
`restic`, `rclone`, and `/usr/bin/security`. Today's value
(`/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`) works on this **Intel** Mac
(Homebrew lives in `/usr/local/bin`) but would **silently break on Apple
Silicon**, where Homebrew is `/opt/homebrew/bin`.

**Decision — prepend `/opt/homebrew/bin` to the plist PATH** so the same
template works on both architectures:

```
PATH = /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

A missing `/opt/homebrew/bin` on an Intel machine is simply skipped by `PATH`
resolution, so the combined value is safe everywhere — no per-arch branching
needed. (Resolving `restic`/`rclone` to absolute paths at setup time, the way we
now resolve `turiya`, remains a possible future hardening but is not needed for
this change.)

### Config discovery

The unattended run loads `~/.config/turiya/config.toml`. LaunchAgents inherit a
populated `HOME`, so path expansion works; no `TURIYA_CONFIG` override is needed.
Worth confirming during verification below rather than assuming.

### Verification — force-run, don't wait for the schedule

Success is not "the plist installed." After `turiya setup`, force the job and
inspect the logs:

```bash
launchctl kickstart -k gui/$(id -u)/<label>    # run the scheduled job now
# then confirm authentication + a real summary event:
tail -f <logging.dir>/launchd-err.log <logging.dir>/ops.jsonl
```

A run that reaches a `summary` event in `ops.jsonl` proves Keychain auth, config
discovery, tool resolution, and the pinned program path all work end-to-end.

## Testing

- **Unit** (`tests/`): `default_program()` with `_uv_tool_bin`/subprocess and
  `Path.exists` mocked to cover (a) resolved bin dir + shim present →
  `["<bin>/turiya", "backup"]`, (b) `uv` missing but the default `~/.local/bin`
  shim present → resolves there, and (c) **shim absent → raises
  `SchedulingError`** (asserts the loud-failure contract, no silent
  `sys.executable` fallback). Assert the rendered plist's `ProgramArguments`
  contains the resolved absolute path (extends existing `scheduling` plist
  tests).
- **Unit:** `set_password` assembles the `security add-generic-password …`
  argv with `-A` present (subprocess mocked, extends existing `keychain` tests).
- The `uv tool install` step is a system action — documented and manually
  verified, not run in CI (CI keeps using `uv run`). Optional follow-up: a smoke
  job that `uv tool install .` into a throwaway `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR`
  and asserts `turiya --help` exits 0 (this is exactly how the layout above was
  verified).

## Versioning & cutover

- Release **`2.1.0`** — additive install path plus a plist-robustness fix, no
  public API or schema change → minor bump. New `CHANGELOG.md` entry and
  `v2.1.0` tag.
- **Migration for an existing install:** run `make install` (or `uv tool
  install .`) and re-run `turiya setup` so the plist is re-rendered with the
  resolved absolute path, replacing the old `.venv`-pinned `ProgramArguments`.
- **Bootstrap ordering:** `uv tool install .` **before** `turiya setup`, and run
  the installed `turiya setup` so the shim exists when `default_program()`
  resolves it — **enforced**: setup raises `SchedulingError` if the shim is
  absent. Documented in README.

## Decisions & alternatives considered (ADR)

- **Install: `uv tool install .`** (vs. a shell alias, vs. a PATH wrapper
  script, vs. publish-to-PyPI). uv-native, single command, isolated env. A shell
  alias (`alias turiya='uv run turiya'`) was rejected — shell-specific,
  project-dir-bound, useless to launchd. A hand-rolled wrapper was rejected as
  fragility we'd own. PyPI was rejected as out of scope for a personal tool.
- **Pinned vs. editable** — **pinned chosen** for robustness. Editable makes the
  *scheduled backup* import live from the repo, so a repo move / broken branch /
  mid-edit breaks it silently; and editable's only benefit (source tracking) is
  redundant because the dev loop is `uv run`. Editable remains a one-flag change
  for anyone who wants it, but is not the default. **[revised from the initial
  editable pick.]**
- **launchd path: resolve `uv tool dir --bin`, absolute** (vs. `shutil.which`
  at setup, vs. adding `~/.local/bin` to the plist `PATH`, vs. `-m` against the
  tool env python). Chosen: deterministic (independent of ambient PATH at setup
  time), uses uv's public installed-executable location, PATH-immune, and
  removes the `.venv` interpreter pin. `shutil.which` was rejected as
  PATH-dependent/"loosely defined"; the internal-python `-m` form was rejected
  as an implementation-detail bet. **[revised from the initial `which` pick.]**
- **Missing shim: fail loud, not silent** — setup raises `SchedulingError`
  rather than falling back to `sys.executable -m turiya`. A silent fallback would
  quietly re-pin the plist to the `.venv`, recreating the very bug this ADR
  removes, with no signal to the operator.
- **Keychain: `set_password` uses `-A`** (vs. `-T`/partition-list scoping, vs.
  leaving the default ACL). Chosen because unattended operation *requires* a
  prompt-free read, `-A` makes that deterministic, and scoping adds fragility +
  a login-password chicken-and-egg for ~no real gain against a same-user threat.
  The password stays in Keychain (not a file/git); the accepted cost is silent
  same-user local access. **The locked-keychain case is an accepted limitation:
  the scheduled backup needs an active login session.**
- **Configurability: auto-resolve + existing `program` kwarg** (vs. a new
  `[scheduling] program` config key / `--program` flag). Auto-resolution avoids
  a new config surface for a derived value.
- **Bootstrap: `Makefile`** (vs. `justfile`, vs. README-only). No new
  dependency, ubiquitous on macOS, encodes install + gates as commands.

## Consequences & trade-offs

- ➕ `turiya` works from any directory; scheduled job is pinned to a stable
  installed path, immune to repo moves/edits and `.venv` recreation.
- ➕ No CLI code churn — pure packaging + a small, testable `default_program()`.
- ➖ After changing code, `make install` is required to refresh the on-PATH
  command (the dev loop via `uv run` still reflects edits immediately).
- ➖ New per-machine bootstrap (`make install` + `uv tool update-shell`) and a
  documented install-before-setup ordering.
- ➖ `~/.local/bin` must be on the interactive `PATH` (`uv tool update-shell`).
- ➖ `-A` on the Keychain item means any process running as you can read the
  restic password without a prompt (documented, accepted).
- ➖ The scheduled backup requires an active login session (unlocked login
  keychain); a run fired at the login window won't authenticate (documented).

## Success criteria

- `turiya backup|restore|status|query|setup|teardown` run from an arbitrary
  directory after `make install`.
- `turiya setup` renders a plist whose `ProgramArguments` is the absolute
  `uv tool dir --bin`/turiya path (verified in a unit test), and raises
  `SchedulingError` if the command isn't installed; the pinned job keeps working
  after the repo directory is moved.
- A **force-run** via `launchctl kickstart -k gui/$(id -u)/<label>` reaches a
  `summary` event in `ops.jsonl` — proving Keychain auth, config discovery, and
  tool resolution all work unattended (not just that the plist installed).
- `uv run` remains the documented contributor workflow; all four gates stay
  green.
- No change to the public API or the JSONL log schema.
- Tagged `v2.1.0` with a CHANGELOG entry.
