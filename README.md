# turiya

Automated weekly cloud backups using [Restic](https://restic.net/) and [rclone](https://rclone.org/), managed via macOS `launchd` and `pmset`.

Targets: **Google Drive**, **Dropbox**, **pCloud** (and optionally Mega).

`turiya` is a library-first Python package: `backup`/`restore`/`status`/`query`/`setup`/`teardown` are all thin CLI wrappers around a typed, tested core (`turiya.config`, `turiya.operations.*`) that other tools can import directly.

---

## Quick Start

```bash
brew install restic rclone
uv sync                                          # or: uv tool install .
cp config.example.toml ~/.config/turiya/config.toml
$EDITOR ~/.config/turiya/config.toml             # adjust sources, excludes, retention, schedule
rclone config                                    # create remotes matching your config's [[repo]] entries
uv run turiya setup                              # Keychain password, repo init, launchd, pmset
uv run turiya backup --dry-run                   # sanity check
uv run turiya backup                             # first real backup
```

---

## How it works

- `~/.config/turiya/config.toml` is the single source of truth for all configuration (copy it from `config.example.toml`); override the path with the `TURIYA_CONFIG` environment variable
- `src/turiya/` is a layered Python package: `config.py`, `keychain.py`, `restic.py`, `rclone.py`, `logging.py`, and `scheduling.py` are the core; `operations/` contains the business logic (`backup`, `restore`, `status`, `query`, `setup`); `cli.py` is a thin [Typer](https://typer.tiangolo.com/) app mapping subcommands to operations
- `turiya setup` reads the config and wires everything up (Keychain, rclone check, repo init, launchd, pmset)
- `turiya backup` is what launchd runs — it loads the config, pulls the password from Keychain, and backs up to all configured repos
- The generated launchd `.plist` (gitignored) is rendered from `src/turiya/templates/launchd.plist.tmpl` by `turiya setup`

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
uv sync                  # creates .venv and installs turiya + dependencies
# or, to install turiya as a standalone CLI tool:
uv tool install .
```

With `uv sync`, run commands as `uv run turiya ...` (or `uv run python -m turiya ...`). With `uv tool install .`, the `turiya` command is available directly on `PATH`.

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

3. **Run setup**:
   ```bash
   uv run turiya setup
   ```
   It prompts for your restic password and stores it in macOS Keychain (or pass `--password`); verifies all configured rclone remotes exist; initializes any uninitialized restic repos; renders and installs the launchd plist(s); loads the launchd job(s); and sets a `pmset` wake schedule so the machine wakes before the earliest configured backup time.

4. **Verify with a dry run, then a real backup**:
   ```bash
   uv run turiya backup --dry-run
   uv run turiya backup
   ```

---

## CLI reference

Every subcommand has full `--help` via Typer, e.g. `uv run turiya backup --help`.

### `turiya backup`

```bash
uv run turiya backup                                  # back up all configured sources
uv run turiya backup --dry-run                        # dry run, no changes
uv run turiya backup --include ~/Documents/taxes      # back up only this path, this run
uv run turiya backup --pattern 'Documents/*/invoices' # back up paths matching this restic-style pattern
uv run turiya backup --glob '*.pdf'                   # back up only files matching this filename glob
uv run turiya backup --exclude '*.iso'                # add an extra exclude pattern, this run only
```

`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `sources` for that run (the scheduled weekly backup, run with no flags, always uses the full `sources` list). `--exclude` is repeatable and adds to the configured `excludes` for that run only.

### `turiya restore`

```bash
uv run turiya restore --target /tmp/restore                          # restore latest snapshot from the primary repo
uv run turiya restore --repo dropbox --target /tmp/restore           # use a specific remote
uv run turiya restore --snapshot abc12345 --target /tmp/restore      # restore a specific snapshot ID
uv run turiya restore --include ~/Documents/invoice.pdf --target /tmp/restore
uv run turiya restore --pattern 'Documents/*/invoices' --target /tmp/restore
uv run turiya restore --glob '*.pdf' --target /tmp/restore
uv run turiya restore --exclude '*.tmp' --target /tmp/restore
```

`--target` is required. `--include`/`--pattern`/`--glob` are repeatable and all map to restic's native include matcher (a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth). `--exclude` is repeatable.

### `turiya status`

```bash
uv run turiya status                          # latest snapshot per repo (--mode latest, the default)
uv run turiya status --mode all               # all snapshots
uv run turiya status --mode check             # integrity check (slow)
uv run turiya status --include ~/Documents    # only snapshots whose source paths include this exact path
uv run turiya status --pattern 'Doc*'         # only snapshots with a source path matching this pattern
uv run turiya status --glob 'Documents'       # only snapshots whose source path's basename matches
uv run turiya status --exclude Music          # drop snapshots matching this pattern
```

Targeting flags filter *which snapshots are listed*, by the top-level source paths recorded on each snapshot — they don't search file contents inside a snapshot. For that, use `turiya query`.

### `turiya query`

```bash
uv run turiya query --since 2026-01-01 --until 2026-06-01   # snapshots in a date range
uv run turiya query --find ~/Documents/taxes/2025.pdf       # which snapshot(s) contain this file
uv run turiya query --find '*.pdf'                          # which snapshot(s) contain files matching this glob
uv run turiya query --versions ~/Documents/notes.md         # every version of this file across snapshots, oldest first
uv run turiya query --repo dropbox --versions '*.pdf'       # restrict the search to one repo
uv run turiya query --find notes.md --json                  # raw JSON output instead of a formatted table
```

Exactly one of `--since`/`--until`, `--find`, or `--versions` is required per invocation. `--repo` defaults to searching all configured repos.

### `turiya setup` / `turiya teardown`

```bash
uv run turiya setup                     # Keychain prompt, rclone check, repo init, launchd + pmset install
uv run turiya setup --password '...'    # non-interactive Keychain password
uv run turiya teardown                  # unload launchd job(s), remove the pmset wake schedule
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
uv run turiya teardown
```

Removes the launchd job(s) and pmset schedule. **Does not touch your restic repos on the cloud providers.**

---

## Repository structure

```
turiya/
├── config.example.toml                      # ← copy to ~/.config/turiya/config.toml
├── pyproject.toml                           # package metadata + tool config (ruff/mypy/ty/pytest)
├── uv.lock
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
├── CLAUDE.md                                # project conventions for AI-assisted development
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
The `PATH` in the rendered plist includes `/usr/local/bin` (Homebrew Intel default). If you installed via a non-standard path (e.g. Apple Silicon's `/opt/homebrew/bin`), adjust `src/turiya/templates/launchd.plist.tmpl` and re-run `turiya setup`.

**Backup didn't run at the scheduled time**
Check that the machine was awake — `pmset` should handle this, but verify with:
```bash
pmset -g sched
```

**Keychain password prompt appears during backup**
macOS may prompt to allow `security` to access the keychain on first run. Click **Always Allow** to prevent future prompts.

**Repo initialisation fails**
Usually an rclone auth issue. Re-run `rclone config reconnect <remote>:` for the affected provider.

**A `--pattern` or `--glob` flag on `turiya backup` errors with "matched no files"**
The pattern didn't match anything under the configured `sources`. Check the pattern against `find <source> -path "*<pattern>*"` (for `--pattern`) or `find <source> -name "<glob>"` (for `--glob`) directly to debug.
