# restic-backup

Automated weekly cloud backups using [Restic](https://restic.net/) and [rclone](https://rclone.org/), managed via macOS `launchd` and `pmset`.

Targets: **Google Drive**, **Dropbox**, **pCloud** (and optionally Mega).

---

## Quick Start

```bash
brew install restic rclone jq
rclone config                    # create remotes matching backup.conf's REPOS
$EDITOR backup.conf              # adjust sources, excludes, retention, schedule
bash install.sh                  # Keychain password, repo init, launchd, pmset
bash backup.sh --dry-run         # sanity check
bash backup.sh                   # first real backup
```

---

## How it works

- `backup.conf` is the single source of truth for all configuration
- `lib/common.sh` / `lib/logging.sh` are shared helpers sourced by every script (config loading, Keychain access, dependency checks, structured logging)
- `install.sh` reads `backup.conf` and wires everything up (Keychain, rclone check, repo init, launchd, pmset)
- `backup.sh` is what launchd runs — it reads `backup.conf` at runtime, pulls the password from Keychain, and backs up to all configured repos
- The generated `.plist` (gitignored) is rendered from `com.amir.restic-backup.plist.template` by `install.sh`

---

## Prerequisites

```bash
brew install restic rclone jq
```

---

## First-run sequence

1. **Configure rclone remotes** — run `rclone config` and create remotes matching the names in `backup.conf`:

   | Remote name | Provider     |
   |-------------|--------------|
   | `gdrive`    | Google Drive |
   | `dropbox`   | Dropbox      |
   | `pcloud`    | pCloud       |
   | `mega`      | Mega (optional) |

   Google Drive, Dropbox, and pCloud use OAuth (browser popup). Mega uses email/password.

   > **Do not commit `~/.config/rclone/rclone.conf`** — it contains OAuth tokens.

2. **Edit `backup.conf`** — adjust source directories, exclusions, retention policy, and schedule to taste. Everything is documented inline.

3. **Run the installer**:
   ```bash
   bash install.sh
   ```
   It checks that `restic`, `rclone`, and `jq` are installed; prompts for your restic password and stores it in macOS Keychain; verifies all rclone remotes exist; initializes any uninitialized restic repos; renders and installs the launchd plist; loads the launchd job; and sets a `pmset` wake schedule so the machine wakes before the backup runs.

4. **Verify with a dry run, then a real backup**:
   ```bash
   bash backup.sh --dry-run
   bash backup.sh
   ```

---

## Daily usage

### backup.sh

```bash
bash backup.sh                                  # back up all configured SOURCES
bash backup.sh --dry-run                        # dry run, no changes
bash backup.sh --include ~/Documents/taxes      # back up only this path, this run
bash backup.sh --pattern 'Documents/*/invoices' # back up paths matching this restic-style pattern
bash backup.sh --glob '*.pdf'                   # back up only files matching this filename glob
bash backup.sh --exclude '*.iso'                # add an extra exclude pattern, this run only
```

`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `SOURCES` for that run (the scheduled weekly backup, run with no flags, always uses the full `SOURCES` list). `--exclude` is repeatable and adds to `backup.conf`'s `EXCLUDES` for that run only.

### restore.sh

```bash
bash restore.sh                                     # interactive guided restore (latest snapshot, primary repo)
bash restore.sh --repo dropbox                       # use a specific remote
bash restore.sh --snapshot abc12345                  # restore a specific snapshot ID
bash restore.sh --include ~/Documents/invoice.pdf    # restore a specific path
bash restore.sh --pattern 'Documents/*/invoices'     # restore paths matching this pattern
bash restore.sh --glob '*.pdf'                       # restore files matching this filename glob
bash restore.sh --exclude '*.tmp'                    # skip files matching this pattern
bash restore.sh --target /tmp/restore                # restore to a custom location
```

`--include`/`--pattern`/`--glob` are repeatable and all map to restic's native include matcher (a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth). `--exclude` is repeatable.

### status.sh

```bash
bash status.sh                        # latest snapshot per repo
bash status.sh --all                  # all snapshots
bash status.sh --check                # integrity check (slow)
bash status.sh --include ~/Documents  # only snapshots whose source paths include this exact path
bash status.sh --pattern 'Doc*'       # only snapshots with a source path matching this pattern
bash status.sh --glob 'Documents'     # only snapshots whose source path's basename matches
bash status.sh --exclude Music        # drop snapshots matching this pattern
```

Targeting flags filter *which snapshots are listed*, by the top-level source paths recorded on each snapshot — they don't search file contents inside a snapshot. For that, use `query.sh`.

### query.sh

```bash
bash query.sh --since 2026-01-01 --until 2026-06-01   # snapshots in a date range
bash query.sh --find ~/Documents/taxes/2025.pdf       # which snapshot(s) contain this file
bash query.sh --find '*.pdf'                          # which snapshot(s) contain files matching this glob
bash query.sh --versions ~/Documents/notes.md         # every version of this file across snapshots, oldest first
bash query.sh --repo dropbox --versions '*.pdf'       # restrict the search to one repo
bash query.sh --find notes.md --json                  # raw JSON output instead of a formatted table
```

Exactly one of `--since`/`--until`, `--find`, or `--versions` is required per invocation. `--repo` defaults to searching all configured repos.

---

## Changing the schedule

Edit `backup.conf`:

```bash
BACKUP_WEEKDAY=0      # 0=Sunday
BACKUP_HOUR=10
BACKUP_MINUTE=0
PMSET_WAKE_OFFSET_MINUTES=5
```

Then re-run `install.sh` to apply. It's idempotent — safe to re-run at any time.

---

## Logs

All logs live under `LOG_DIR` (default `~/.local/log/restic-backup`), one pair of files per operation plus a combined structured log:

```
backup.log      restore.log      status.log      query.log        # human-readable, one per operation
backup.jsonl    restore.jsonl    status.jsonl    query.jsonl       # structured JSON Lines, one per operation
ops.jsonl                                                          # combined structured JSON Lines, every operation interleaved
launchd.log                                                        # stdout from launchd
launchd-err.log                                                    # stderr from launchd
```

Each line of a `.jsonl` file is a standalone JSON object — e.g. `jq -c 'select(.event == "file")' backup.jsonl` shows every file restic touched on the last few runs, or `jq -c 'select(.level == "error")' ops.jsonl` surfaces every error across every operation. Set `LOG_JSON_PER_FILE=false` in `backup.conf` if per-file entries make the `.jsonl` files too large for your taste — you'll still get run/summary/error events. All log files (`.log` and `.jsonl`) rotate automatically at `LOG_MAX_BYTES`.

---

## Uninstall

```bash
bash uninstall.sh
```

Removes the launchd job and pmset schedule. Optionally removes the Keychain entry and logs. **Does not touch your restic repos on the cloud providers.**

---

## Repository structure

```
restic-backup/
├── backup.conf                              # ← all config lives here
├── lib/
│   ├── common.sh                            # config loading, Keychain, dependency checks
│   └── logging.sh                           # structured JSONL + human-readable logging
├── backup.sh                                # backup runner (called by launchd)
├── install.sh                               # one-time setup
├── uninstall.sh                             # teardown
├── status.sh                                # snapshot inspection
├── restore.sh                               # guided restore helper
├── query.sh                                 # snapshot search (date range, file, version history)
├── com.amir.restic-backup.plist.template    # launchd plist template
├── CLAUDE.md                                # project conventions for AI-assisted development
├── .copilot-instructions.md                 # same, for GitHub Copilot
├── .gitignore
└── README.md
```

---

## Security notes

- The restic password is stored in **macOS Keychain** — never in any file tracked by git
- All backups are **AES-256 encrypted by restic** before leaving your machine
- rclone OAuth tokens live in `~/.config/rclone/rclone.conf` — keep this out of version control
- The generated `.plist` is gitignored since it contains your absolute home path

---

## Retention policy (default)

| Interval | Snapshots kept |
|----------|---------------|
| Daily    | 7             |
| Weekly   | 4             |
| Monthly  | 6             |
| Yearly   | 1             |

Configurable in `backup.conf`.

---

## Troubleshooting

**`rclone`, `restic`, or `jq` not found when launchd runs**
The `PATH` in the plist template includes `/usr/local/bin` (Homebrew Intel default). If you installed via a non-standard path, update `EnvironmentVariables > PATH` in the template and re-run `install.sh`.

**Backup didn't run at the scheduled time**
Check that the machine was awake — `pmset` should handle this, but verify with:
```bash
pmset -g sched
```

**Keychain password prompt appears during backup**
macOS may prompt to allow `security` to access the keychain on first run. Click **Always Allow** to prevent future prompts.

**Repo initialisation fails**
Usually a rclone auth issue. Re-run `rclone config reconnect <remote>:` for the affected provider.

**A `--pattern` or `--glob` flag on `backup.sh` errors with "matched no files"**
The pattern didn't match anything under the configured `SOURCES`. Check the pattern against `find <source> -path "*<pattern>*"` (for `--pattern`) or `find <source> -name "<glob>"` (for `--glob`) directly to debug.
