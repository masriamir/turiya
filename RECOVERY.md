# Disaster Recovery

Use this when the Mac that ran `turiya` is lost, dead, or wiped, and you have
a **replacement** Mac that needs the backed-up files restored onto it.

## Prerequisites checklist

- [ ] **The restic repository password**, retrieved from wherever you keep a
      copy outside this Mac's Keychain (e.g. a password manager). The
      Keychain itself is gone along with the machine — you need an
      out-of-band copy.
- [ ] **A copy of `config.toml`.** This is **not currently backed up by
      `turiya` itself** — tracked in
      [issue #12](https://github.com/masriamir/turiya/issues/12). Until
      that lands, keep a copy of `~/.config/turiya/config.toml` alongside
      the password in whatever store holds it. If you don't have one,
      you'll reconstruct it from `config.example.toml` in step 3 below —
      you'll need to remember your `sources`, `excludes`, retention
      settings, and schedule.
- [ ] **The `[[repo]]` URLs** from that config (e.g.
      `rclone:gdrive:turiya-backups`) — needed even if you're reconstructing
      the config from memory, so you point at the right remotes.

## Procedure

1. **Install prerequisites:**
   ```bash
   brew install restic rclone uv
   ```

2. **Get the `turiya` source and install it.** There's no PyPI package —
   clone the repository, then from its root:
   ```bash
   make install
   ```
   This pins `turiya` on `PATH` (see `README.md`'s Bootstrap section).

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
- **Password not yet in Keychain:** fails with `Could not retrieve the
  restic password from the Keychain. Run \`turiya setup\`, or check
  keychain.account/keychain.service in the config.` (exit code 1). Complete
  step 5 above.

## Verify this actually works — don't just trust it

Rehearse this procedure periodically, rather than the first time you need it
for real: restore to a scratch directory on your *current* machine
(`turiya restore --target /tmp/restore-drill`) and confirm the files are
actually there and openable. A backup you've never restored is a hypothesis,
not a backup.
