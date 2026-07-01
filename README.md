# restic-backup

Automated weekly cloud backups using [Restic](https://restic.net/) and [rclone](https://rclone.org/), managed via macOS `launchd` and `pmset`.

Targets: **Google Drive**, **Dropbox**, **pCloud** (and optionally Mega).

---

## How it works

- `backup.conf` is the single source of truth for all configuration
- `install.sh` reads `backup.conf` and wires everything up (Keychain, rclone check, repo init, launchd, pmset)
- `backup.sh` is what launchd runs — it reads `backup.conf` at runtime, pulls the password from Keychain, and backs up to all configured repos
- The generated `.plist` (gitignored) is rendered from `com.amir.restic-backup.plist.template` by `install.sh`

---

## Prerequisites

```bash
brew install restic rclone
```

---

## First-time setup

### 1. Configure rclone remotes

Run `rclone config` and create remotes matching the names in `backup.conf`:

| Remote name | Provider     |
|-------------|--------------|
| `gdrive`    | Google Drive |
| `dropbox`   | Dropbox      |
| `pcloud`    | pCloud       |
| `mega`      | Mega (optional) |

Google Drive, Dropbox, and pCloud use OAuth (browser popup). Mega uses email/password.

> **Do not commit `~/.config/rclone/rclone.conf`** — it contains OAuth tokens.

### 2. Edit `backup.conf`

Adjust source directories, exclusions, retention policy, and schedule to taste. Everything is documented inline.

### 3. Run the installer

```bash
bash install.sh
```

The installer will:
- Check that `restic` and `rclone` are installed
- Prompt for your restic password and store it in macOS Keychain
- Verify all rclone remotes exist
- Initialise any uninitialised restic repos
- Render and install the launchd plist
- Load the launchd job
- Set a `pmset` wake schedule so the machine wakes before the backup runs

---

## Daily usage

### Run a backup manually

```bash
bash backup.sh
```

### Dry run (no changes)

```bash
bash backup.sh --dry-run
```

### Check snapshot status

```bash
bash status.sh              # latest snapshot per repo
bash status.sh --all        # all snapshots
bash status.sh --check      # integrity check (slow)
```

### Restore files

```bash
# Interactive restore from primary repo (latest snapshot, full restore)
bash restore.sh

# Restore a specific path from Dropbox to /tmp/restore
bash restore.sh --repo dropbox --include ~/Documents/invoice.pdf --target /tmp/restore

# Restore from a specific snapshot ID
bash restore.sh --snapshot abc12345 --target ~/Desktop/restored
```

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

```
~/.local/log/restic-backup/backup.log        # main backup log (auto-rotated at 5MB)
~/.local/log/restic-backup/launchd.log       # stdout from launchd
~/.local/log/restic-backup/launchd-err.log   # stderr from launchd
```

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
├── backup.sh                                # backup runner (called by launchd)
├── install.sh                               # one-time setup
├── uninstall.sh                             # teardown
├── status.sh                                # snapshot inspection
├── restore.sh                               # guided restore helper
├── com.amir.restic-backup.plist.template    # launchd plist template
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

**`rclone` or `restic` not found when launchd runs**
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
