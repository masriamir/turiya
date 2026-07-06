# Disaster Recovery

Use this when the Mac that ran `turiya` is lost, dead, or wiped, and you have
a **replacement** Mac that needs the backed-up files restored onto it.

## Prerequisites checklist

- [ ] **The restic repository password**, retrieved from wherever you keep a
      copy outside this Mac's Keychain (e.g. a password manager). The
      Keychain itself is gone along with the machine — you need an
      out-of-band copy.
- [ ] **A copy of `config.toml`** is no longer strictly required — since
      `turiya backup` always includes it as an implicit target (closing
      [issue #12](https://github.com/masriamir/turiya/issues/12)), `turiya
      recover-config --repo <your-repo-url>` (step 3 below) restores it
      directly from the repo's latest snapshot. Keeping a manual copy
      alongside the password is still a reasonable belt-and-suspenders
      backup, but no longer the only safety net.
- [ ] **The `[[repo]]` URLs** from that config (e.g.
      `rclone:gdrive:turiya-backups`) — needed even if you're reconstructing
      the config from memory, so you point at the right remotes.

## Procedure

1. **Install prerequisites:**
   ```bash
   brew install restic rclone uv
   ```
   You'll also need `git` to clone the source in the next step — it ships
   with the Xcode Command Line Tools (`xcode-select --install` if missing).

2. **Get the `turiya` source and install it.** There's no PyPI package —
   clone the repository, then from its root:
   ```bash
   make install              # pins `turiya` on PATH
   uv tool update-shell      # one-time, if ~/.local/bin isn't already on PATH
   ```
   On a fresh machine `~/.local/bin` (the `uv` tool bin directory) usually
   isn't on `PATH` yet — without `uv tool update-shell` the later steps fail
   with `turiya: command not found` even though install succeeded. See
   `README.md`'s Bootstrap section.

3. **Recreate `~/.config/turiya/config.toml`** — copy back your saved copy
   (recommended), or copy `config.example.toml` and fill in your
   sources/excludes/retention/schedule/repo URLs from memory.

4. **Re-authenticate rclone remotes:**
   ```bash
   rclone config
   ```
   Every OAuth-based remote (Google Drive, Dropbox, pCloud) needs a fresh
   browser login on the new machine; Mega needs email/password again. This
   is identical to the First-run sequence in `README.md` — it's not
   DR-specific, it's just also required after a machine change.

5. **Get the password into Keychain.** Either:
   - let `turiya setup` prompt for it (this also reinstalls the launchd
     schedule immediately — fine if you want that now), or
   - if you'd rather restore first and set up the schedule later:
     ```bash
     security add-generic-password -a restic -s turiya -w '<your-recovered-password>' -A -U
     ```
     (`-a`/`-s` must match `keychain.account`/`keychain.service` in your
     config — `restic`/`turiya` are the defaults in `config.example.toml`.)

6. **Restore:**
   ```bash
   turiya restore --target ~/restored
   ```
   Add `--repo <name>`, `--snapshot <id>`, or `--include`/`--pattern`/
   `--glob`/`--exclude` as needed — see the CLI reference in `README.md`.

   **Note:** restic restores files under their **original absolute path**
   nested inside `--target` (e.g. `~/restored/Users/you/Documents/...`), not
   flattened directly into `~/restored`. This is restic's own behavior, not
   something turiya changes.

## If something's missing

- **No `config.toml` at all:** every `turiya` command fails immediately with
  `Config file not found at <path>` (exit code 1) — no partial state to
  clean up.
- **Password not yet in Keychain:** fails with ``Could not retrieve the
  restic password from the Keychain. Run `turiya setup`, or check
  keychain.account/keychain.service in the config. (security exit <n>)``
  (exit code 1). Complete step 5 above.

## Verify this actually works — don't just trust it

Rehearse this procedure periodically, rather than the first time you need it
for real: restore to a scratch directory on your *current* machine
(`turiya restore --target /tmp/restore-drill`) and confirm the files are
actually there and openable. A backup you've never restored is a hypothesis,
not a backup.
