# Disaster Recovery Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `RECOVERY.md` runbook documenting how to restore turiya's
backups onto a replacement Mac after the original is lost/dead/wiped, proven
accurate by an executed dry run rather than assumed.

**Architecture:** Pure documentation — one new root-level file plus two small
cross-reference edits. No code, no tests in the pytest sense; "testing" here
is the dry-run verification already performed against a local restic repo
standing in for a cloud remote (rclone re-auth is identical to the existing
First-run sequence and isn't re-verified here).

**Tech Stack:** Markdown. Verification uses the existing `turiya` CLI via
`uv run turiya` and a local `restic` repo (no rclone/cloud credentials
needed for the parts that are turiya-specific).

## Global Constraints

- No code changes. No `CHANGELOG.md` entry or version bump (spec: pure docs).
- Must explicitly flag `config.toml` as not currently backed up, linking to
  issue #12 (https://github.com/masriamir/turiya/issues/12) rather than
  working around it silently.
- `RECOVERY.md` lives at the repo root (sibling to `SECURITY.md`), not under
  `docs/`.
- Cross-linked from `README.md` and listed in `.claude/CLAUDE.md`'s file map.
- Every command shown in the doc must be one that was actually run during
  this plan's verification steps, with output matching what's documented.

---

### Task 1: Write `RECOVERY.md`

**Files:**
- Create: `RECOVERY.md`

**Verification evidence (already gathered, reproduced below so the content
of Step 1 is provably accurate, not assumed):**

A local restic repo was used as a stand-in for a cloud remote to simulate a
fresh-machine restore:

```bash
export RESTIC_PASSWORD="dry-run-password"
restic init -r /tmp/dr-dryrun/repo
restic backup -r /tmp/dr-dryrun/repo /tmp/dr-dryrun/source/Documents
```
→ repo initialized, one snapshot created successfully.

A fresh `config.toml` (simulating "recreated on a new machine") pointed
`[[repo]] url` at that local repo path instead of an `rclone:` URL, with
`TURIYA_CONFIG` pointed at it:

```bash
export TURIYA_CONFIG=/tmp/dr-dryrun/config/config.toml
export RESTIC_PASSWORD="dry-run-password"
uv run turiya restore --target /tmp/dr-dryrun/restore-target
```
→ Output (log lines from `StructuredLogger`):
```
[...] restored /tmp/dr-dryrun/source/Documents/taxes.pdf
[...] restored /tmp/dr-dryrun/source/Documents
...
```
→ **Confirmed:** restic restores under the file's **original absolute path**
nested inside `--target` (e.g. `<target>/tmp/dr-dryrun/source/Documents/taxes.pdf`)
— it does **not** flatten into `<target>` directly. This is restic's own
native behavior (not turiya-specific) and is worth calling out explicitly
since it surprises people expecting a flattened restore.

Error paths, confirmed with the same fresh config:

```bash
TURIYA_CONFIG=/nonexistent/config.toml uv run turiya restore --target /tmp/x
```
→ `Config file not found at /nonexistent/config.toml`, exit code 1.

```bash
# valid config, but no RESTIC_PASSWORD env and no matching Keychain item
uv run turiya restore --target /tmp/x
```
→ ``Could not retrieve the restic password from the Keychain. Run `turiya setup`, or check keychain.account/keychain.service in the config. (security exit 44)``, exit code 1.

(The Keychain *write* path — `security add-generic-password ... -A -U` — was
not re-executed against the real login keychain to avoid writing a test
entry under the same `account`/`service` defaults (`restic`/`turiya`) a real
future `turiya setup` on this machine would use. Its exact argv is read
directly from `src/turiya/keychain.py::set_password` and is already covered
by `tests/test_keychain.py`, so this is documented from source, not
re-verified live.)

- [ ] **Step 1: Write the file**

Create `RECOVERY.md` with this exact content:

````markdown
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
  keychain.account/keychain.service in the config.`` (exit code 1). Complete
  step 5 above.

## Verify this actually works — don't just trust it

Rehearse this procedure periodically, rather than the first time you need it
for real: restore to a scratch directory on your *current* machine
(`turiya restore --target /tmp/restore-drill`) and confirm the files are
actually there and openable. A backup you've never restored is a hypothesis,
not a backup.
````

- [ ] **Step 2: Confirm the file renders sensibly**

Run: `git diff --stat RECOVERY.md` (should show a new ~65-line file) and
visually scan the rendered markdown (e.g. `glow RECOVERY.md` if installed,
or just re-read the file) for any broken code fences or list nesting.

- [ ] **Step 3: Commit**

```bash
git add RECOVERY.md
git commit -m "docs: add disaster-recovery runbook for restoring onto a replacement Mac"
```

---

### Task 2: Cross-link from `README.md`

**Files:**
- Modify: `README.md` (add a new section after "Uninstall", before
  "Repository structure" — i.e. immediately after the line
  `Removes the launchd job(s) and pmset schedule. **Does not touch your restic repos on the cloud providers.**`
  and its following `---`)

**Interfaces:**
- Consumes: nothing code-level — just needs `RECOVERY.md` to exist (Task 1).

- [ ] **Step 1: Add the section**

Insert this new section into `README.md` immediately after the existing
"Uninstall" section's closing `---` (i.e. right before `## Repository
structure`):

```markdown
## Disaster recovery

If the Mac running `turiya` is lost, dead, or wiped, see
[`RECOVERY.md`](RECOVERY.md) for the step-by-step procedure to restore your
backups onto a replacement machine.

---

```

- [ ] **Step 2: Verify placement**

Run: `grep -n "^## " README.md` and confirm the output shows `## Disaster
recovery` between `## Uninstall` and `## Repository structure`, in that
order.

Expected (excerpt):
```
212:## Uninstall
...:## Disaster recovery
222:## Repository structure
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: link README to the new disaster-recovery runbook"
```

---

### Task 3: Add file-map entry to `.claude/CLAUDE.md`

**Files:**
- Modify: `.claude/CLAUDE.md`

**Interfaces:**
- Consumes: nothing code-level.

- [ ] **Step 1: Add the row**

In the "File map" table in `.claude/CLAUDE.md`, add a new row immediately
after the existing `README.md` row:

```markdown
| `RECOVERY.md` | Disaster-recovery runbook: restoring turiya's backups onto a replacement Mac after the original is lost/dead/wiped. |
```

- [ ] **Step 2: Verify**

Run: `grep -n "RECOVERY.md" .claude/CLAUDE.md`

Expected: one match, the row just added.

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: add RECOVERY.md to CLAUDE.md's file map"
```

---

### Task 4: Final gate check

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run ty check`

Expected: all clean (no `.py` files were touched by this plan, so this
mainly guards against an accidental unrelated change slipping in).

- [ ] **Step 2: Confirm branch is clean and ready**

Run: `git status --short` — expected: no output (working tree clean, Tasks
1–3 already committed).

## Self-Review Notes

- **Spec coverage:** "When to use this" ✓ (Procedure intro line), prerequisites
  checklist ✓, step-by-step procedure ✓ (all 6 steps from the spec design),
  "verify, don't just trust it" closing note ✓, config.toml gap + issue #12
  link ✓, cross-link from README ✓ (Task 2), CLAUDE.md file map entry ✓
  (Task 3). No spec section lacks a task.
- **Placeholder scan:** no TBD/TODO; the one bracketed value
  (`<your-recovered-password>`) is an intentional user-supplied placeholder
  in an example command, not a plan placeholder.
- **Type/name consistency:** n/a (no code).
