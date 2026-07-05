# turiya

Automated weekly cloud backups using [Restic](https://restic.net/) and [rclone](https://rclone.org/), managed via macOS `launchd` and `pmset`.

[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/masriamir/turiya/badge)](https://scorecard.dev/viewer/?uri=github.com/masriamir/turiya)

Targets: **Google Drive**, **Dropbox**, **pCloud** (and optionally Mega).

`turiya` is a library-first Python package: `backup`/`restore`/`status`/`query`/`setup`/`teardown` are all thin CLI wrappers around a typed, tested core (`turiya.config`, `turiya.operations.*`) that other tools can import directly.

---

## Quick Start

```bash
brew install restic rclone uv
make install                                     # uv tool install . — puts `turiya` on PATH
cp config.example.toml ~/.config/turiya/config.toml
$EDITOR ~/.config/turiya/config.toml             # adjust sources, excludes, retention, schedule
rclone config                                    # create remotes matching your config's [[repo]] entries
turiya setup                                     # Keychain password, repo init, launchd, pmset
turiya backup --dry-run                          # sanity check
turiya backup                                    # first real backup
```

---

## How it works

- `~/.config/turiya/config.toml` is the single source of truth for all configuration (copy it from `config.example.toml`); override the path with the `TURIYA_CONFIG` environment variable
- `src/turiya/` is a layered Python package: `config.py`, `keychain.py`, `restic.py`, `rclone.py`, `logging.py`, and `scheduling.py` are the core; `operations/` contains the business logic (`backup`, `restore`, `status`, `query`, `setup`); `cli.py` is a thin [Typer](https://typer.tiangolo.com/) app mapping subcommands to operations
- `turiya setup` reads the config and wires everything up (Keychain, rclone check, repo init, launchd, pmset)
- `turiya backup` is what launchd runs — it loads the config, pulls the password from Keychain, and backs up to all configured repos
- The generated launchd `.plist` (gitignored) is rendered from `src/turiya/templates/launchd.plist.tmpl` by `turiya setup`
- `turiya setup` pins the scheduled job to the `uv tool`-installed `turiya` binary (resolved via `uv tool dir --bin`), so run `make install` **before** `turiya setup` — see [Bootstrap](#bootstrap)

---

## Prerequisites

```bash
brew install restic rclone
```

You'll also need [uv](https://docs.astral.sh/uv/) to install and run the package — follow the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for your platform (Homebrew: `brew install uv`).

---

## Bootstrap

From the repository root:

```bash
make install              # uv tool install . --reinstall — pins `turiya` on PATH
uv tool update-shell      # one-time, if ~/.local/bin isn't already on PATH
```

This installs a **pinned snapshot** of the package into an isolated `uv`-managed
tool environment (not the project `.venv`) and drops a `turiya` shim into
`uv tool dir --bin` (typically `~/.local/bin`). It's a real copy, not a live
link to your working copy — the scheduled backup stays correct even if the
repo is moved or mid-edit. `turiya` then works from any directory. `turiya
setup` resolves and bakes this installed path into the launchd job, so
**install before you run `setup`**; re-run `make install` after pulling
changes or making local edits you want the installed command to pick up.

Contributing to the code itself uses a separate, unpinned flow — see
[`CONTRIBUTING.md`](CONTRIBUTING.md): `uv sync` creates `.venv`, and you run
commands as `uv run turiya ...` there so every edit is reflected immediately.

---

## First-run sequence

1. **Configure rclone remotes** — run `rclone config` and create remotes matching the `url`s in your config's `[[repo]]` entries:

   | Remote name | Provider     |
   |-------------|--------------|
   | `gdrive`    | Google Drive |
   | `dropbox`   | Dropbox      |
   | `pcloud`    | pCloud       |
   | `mega`      | Mega (optional) |

   Google Drive, Dropbox, and pCloud use OAuth (browser popup). Mega uses email/password.

   > **Do not commit `~/.config/rclone/rclone.conf`** — it contains OAuth tokens.

2. **Create your config** — copy `config.example.toml` to `~/.config/turiya/config.toml` and adjust source directories, exclusions, retention policy, and schedule to taste. Everything is documented inline.

3. **Run setup** (after `make install` — see [Bootstrap](#bootstrap)):
   ```bash
   turiya setup
   ```
   It prompts for your restic password and stores it in macOS Keychain with silent unattended-read access (or pass `--password`); verifies all configured rclone remotes exist; initializes any uninitialized restic repos; renders and installs the launchd plist(s), pinned to the installed `turiya` command; loads the launchd job(s); and sets a `pmset` wake schedule so the machine wakes before the earliest configured backup time. If `turiya` isn't installed on `PATH` yet, `setup` fails with a clear error rather than silently falling back to a fragile invocation — run `make install` first.

4. **Verify with a dry run, then a real backup**:
   ```bash
   turiya backup --dry-run
   turiya backup
   ```

---

## CLI reference

Every subcommand has full `--help` via Typer, e.g. `turiya backup --help`.
(Contributors running from a working copy without `make install`: prefix
every command below with `uv run`.)

### `turiya backup`

```bash
turiya backup                                  # back up all configured sources
turiya backup --dry-run                        # dry run, no changes
turiya backup --include ~/Documents/taxes      # back up only this path, this run
turiya backup --pattern 'Documents/*/invoices' # back up paths matching this restic-style pattern
turiya backup --glob '*.pdf'                   # back up only files matching this filename glob
turiya backup --exclude '*.iso'                # add an extra exclude pattern, this run only
```

`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `sources` for that run (the scheduled weekly backup, run with no flags, always uses the full `sources` list). `--exclude` is repeatable and adds to the configured `excludes` for that run only.

### `turiya restore`

```bash
turiya restore --target /tmp/restore                          # restore latest snapshot from the primary repo
turiya restore --repo dropbox --target /tmp/restore           # use a specific remote
turiya restore --snapshot abc12345 --target /tmp/restore      # restore a specific snapshot ID
turiya restore --include ~/Documents/invoice.pdf --target /tmp/restore
turiya restore --pattern 'Documents/*/invoices' --target /tmp/restore
turiya restore --glob '*.pdf' --target /tmp/restore
turiya restore --exclude '*.tmp' --target /tmp/restore
```

`--target` is required. `--include`/`--pattern`/`--glob` are repeatable and all map to restic's native include matcher (a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth). `--exclude` is repeatable.

### `turiya status`

```bash
turiya status                          # latest snapshot per repo (--mode latest, the default)
turiya status --mode all               # all snapshots
turiya status --mode check             # integrity check (slow)
turiya status --include ~/Documents    # only snapshots whose source paths include this exact path
turiya status --pattern 'Doc*'         # only snapshots with a source path matching this pattern
turiya status --glob 'Documents'       # only snapshots whose source path's basename matches
turiya status --exclude Music          # drop snapshots matching this pattern
```

Targeting flags filter *which snapshots are listed*, by the top-level source paths recorded on each snapshot — they don't search file contents inside a snapshot. For that, use `turiya query`.

### `turiya query`

```bash
turiya query --since 2026-01-01 --until 2026-06-01   # snapshots in a date range
turiya query --find ~/Documents/taxes/2025.pdf       # which snapshot(s) contain this file
turiya query --find '*.pdf'                          # which snapshot(s) contain files matching this glob
turiya query --versions ~/Documents/notes.md         # every version of this file across snapshots, oldest first
turiya query --repo dropbox --versions '*.pdf'       # restrict the search to one repo
turiya query --find notes.md --json                  # raw JSON output instead of a formatted table
```

Exactly one of `--since`/`--until`, `--find`, or `--versions` is required per invocation. `--repo` defaults to searching all configured repos.

### `turiya setup` / `turiya teardown`

```bash
turiya setup                     # Keychain prompt, rclone check, repo init, launchd + pmset install
turiya setup --password '...'    # non-interactive Keychain password
turiya teardown                  # unload launchd job(s), remove the pmset wake schedule
```

`setup` is idempotent — safe to re-run any time your config changes (e.g. a new schedule or repo). **`teardown` does not touch your restic repos on the cloud providers or remove logs.**

---

## Changing the schedule

Edit `~/.config/turiya/config.toml`:

```toml
[[schedule]]
weekday = 0      # 0=Sunday
hour = 10
minute = 0

[power]
wake_offset_minutes = 5
```

One or more `[[schedule]]` tables may be given; each renders its own launchd `StartCalendarInterval`. Then re-run `turiya setup` to apply.

---

## Logs

All logs live under `logging.dir` (default `~/.local/log/turiya`):

```
backup.jsonl    restore.jsonl    status.jsonl    query.jsonl       # structured JSON Lines, one per operation
ops.jsonl                                                          # combined structured JSON Lines, every operation interleaved
backup.log      restore.log                                       # human-readable, backup/restore only
launchd.log                                                        # stdout from launchd
launchd-err.log                                                    # stderr from launchd
```

Every operation (`backup`/`restore`/`status`/`query`) emits structured events to its own `<op>.jsonl` plus the combined `ops.jsonl`. `backup` and `restore` additionally write a human-readable `<op>.log` via the same logger (matching v1.0.0). `status` and `query` print their listings straight to stdout as a formatted table (or JSON with `--json`) — matching v1.0.0's console output — and do not produce a `status.log`/`query.log` file.

Each line of a `.jsonl` file is a standalone JSON object, so any JSON-aware tool can filter it — e.g. with Python: `python -c "import json,sys; [print(l) for l in sys.stdin if json.loads(l)['event']=='file']" < backup.jsonl`. Set `json_per_file = false` under `[logging]` in your config if per-file entries make the `.jsonl` files too large for your taste — you'll still get run/summary/error events. All log files (`.log` and `.jsonl`) rotate automatically at `max_bytes`.

---

## Uninstall

```bash
turiya teardown
```

Removes the launchd job(s) and pmset schedule. **Does not touch your restic repos on the cloud providers.**

---

## Disaster recovery

If the Mac running `turiya` is lost, dead, or wiped, see
[`RECOVERY.md`](RECOVERY.md) for the step-by-step procedure to restore your
backups onto a replacement machine.

---

## Repository structure

```
turiya/
├── config.example.toml                      # ← copy to ~/.config/turiya/config.toml
├── pyproject.toml                           # package metadata + tool config (ruff/mypy/ty/pytest)
├── uv.lock
├── Makefile                                 # install (uv tool install), dev (uv sync), gates (CI parity), release (tag + publish)
├── src/turiya/
│   ├── __init__.py
│   ├── __main__.py                          # `python -m turiya` entry point
│   ├── config.py                            # load + validate config.toml -> typed Config (pydantic)
│   ├── keychain.py                          # macOS `security` wrapper
│   ├── restic.py                            # subprocess wrapper: restic --json -> typed events
│   ├── rclone.py                            # remote verification
│   ├── logging.py                           # structured JSONL + human logging
│   ├── scheduling.py                        # launchd plist rendering + pmset
│   ├── errors.py                            # typed exception hierarchy (TuriyaError and subclasses)
│   ├── operations/
│   │   ├── backup.py
│   │   ├── restore.py
│   │   ├── status.py
│   │   ├── query.py
│   │   └── setup.py                         # setup + teardown
│   ├── cli.py                               # thin Typer app; console entry point `turiya`
│   └── templates/
│       └── launchd.plist.tmpl               # launchd plist template
├── tests/                                   # pytest: unit + integration suites
├── .claude/
│   └── CLAUDE.md                            # project conventions for AI-assisted development
├── .github/                                 # CI, CodeQL, Dependabot, issue/PR templates
│   └── copilot-instructions.md              # same conventions, for GitHub Copilot
├── .gitignore
└── README.md
```

---

## Security notes

- The restic password is stored in **macOS Keychain** — never in any file tracked by git
- All backups are **AES-256 encrypted by restic** before leaving your machine
- rclone OAuth tokens live in `~/.config/rclone/rclone.conf` — keep this out of version control
- The generated `.plist` is gitignored since it contains your absolute home path
- `~/.config/turiya/config.toml` is user-local and not tracked by git — only `config.example.toml` is committed
- `turiya setup` stores the Keychain item with silent (non-interactive) read access, so the scheduled backup never blocks on an unanswered access prompt. This is a deliberate trade-off: any process running as you can read the restic password without a prompt — the same as being able to invoke `security` yourself. The password never leaves Keychain for a file.
- The scheduled backup requires an **active login session** (an unlocked login keychain) to authenticate; a run that fires while logged out or at the login window will fail to read the password. `pmset` wakes the machine but doesn't log you in.

---

## Retention policy (default)

| Interval | Snapshots kept |
|----------|---------------|
| Daily    | 7             |
| Weekly   | 4             |
| Monthly  | 6             |
| Yearly   | 1             |

Configurable under `[retention]` in your config.

---

## Troubleshooting

**`rclone` or `restic` not found when launchd runs**
The rendered plist's `PATH` covers both Homebrew locations (`/opt/homebrew/bin` for Apple Silicon, `/usr/local/bin` for Intel). If you installed `restic`/`rclone` somewhere else entirely, adjust `src/turiya/templates/launchd.plist.tmpl` and re-run `turiya setup`.

**`turiya setup` fails with "turiya is not installed (no executable file at ...)"**
Run `make install` (`uv tool install .`) first, then re-run `turiya setup` — the scheduled job is pinned to the installed command, so it must exist (and be executable) before setup can resolve it.

**Backup didn't run at the scheduled time**
Check that the machine was awake — `pmset` should handle this, but verify with:
```bash
pmset -g sched
```
Also confirm you were **logged in** at the scheduled time: the backup reads the restic password from the login keychain, which is locked while logged out or at the login window.

**Keychain password prompt appears during backup**
As of 2.1.0, `turiya setup` stores the Keychain item with silent access (`-A`), so this shouldn't happen on a fresh setup. If you're seeing it on an install from before 2.1.0, re-run `turiya setup` (or `security add-generic-password ... -A` by hand) to update the item's ACL. If it still prompts, click **Always Allow** to unblock the current run.

**Repo initialisation fails**
Usually an rclone auth issue. Re-run `rclone config reconnect <remote>:` for the affected provider.

**A `--pattern` or `--glob` flag on `turiya backup` errors with "matched no files"**
The pattern didn't match anything under the configured `sources`. Check the pattern against `find <source> -path "*<pattern>*"` (for `--pattern`) or `find <source> -name "<glob>"` (for `--glob`) directly to debug.
