# Disaster Recovery Runbook — Design

Date: 2026-07-05
Status: Proposed
Sub-project: post-v2.1.0 documentation — closes the "restore onto a
replacement Mac" gap identified during a security/gap-analysis review.

## Purpose

Document, and prove by dry run, how to recover onto a **replacement** Mac if
the original machine that ran `turiya` is lost, stolen, or dies. Today
`README.md` documents `turiya restore` assuming `turiya` is already
installed and configured on the machine you're restoring *to* — it does not
address the actual disaster scenario a backup tool exists for: the original
machine is gone.

## Context

- The restic repository password lives only in this Mac's Keychain
  (`src/turiya/keychain.py`); the user separately confirmed a copy already
  exists outside this machine (a password manager), so the password itself
  is not at risk.
- `~/.config/turiya/config.toml` (sources, excludes, retention, schedule) is
  **not** backed up anywhere and is not part of what `turiya backup` backs
  up. Confirmed with the user: only this Mac has it. Reconstructing it from
  memory + `config.example.toml` risks silently wrong retention/exclude
  settings.
- A companion GitHub issue (#12) tracks the code-level fix (auto-include
  `config.toml` as an implicit backup source). That is explicitly **out of
  scope here** — this design is docs-only, and recommends a manual stopgap
  (keep a copy of `config.toml` next to the password) until #12 lands.
- Existing convention: `SECURITY.md` is a standalone, root-level operational
  doc, distinct from `README.md`'s day-to-day usage docs and cross-linked
  from it. This design follows that pattern rather than growing `README.md`
  further (currently 285+ lines).

## Scope

**In scope**

- A new `RECOVERY.md` at the repo root.
- A cross-link from `README.md` (near "Uninstall" / "Security notes") and an
  entry in `CLAUDE.md`'s file map.
- A real, executed dry run of the documented procedure against a live
  configured repo, to confirm the steps are accurate — not just plausible.

**Out of scope**

- Any code change (including issue #12's auto-include-config-as-source
  idea — tracked separately).
- Automating any part of the recovery procedure (e.g. a `turiya recover`
  command). If the manual procedure proves painful enough to warrant this,
  that's a future design, not this one.

## Design

### `RECOVERY.md` structure

1. **When to use this** — one-liner scoping the doc to "original Mac lost/
   dead/wiped, replacement Mac in hand, need the files back."
2. **Prerequisites checklist**
   - The restic repository password, retrieved from wherever it's kept
     outside Keychain.
   - A copy of `config.toml` — call out plainly that this is **not**
     currently backed up by `turiya` itself (link to issue #12), and
     recommend storing a copy alongside the password today as a stopgap.
   - The `[[repo]]` URLs from that config (needed to run `restic`/`turiya`
     against the right remotes even before `config.toml` is restored, if the
     user only has the password and must reconstruct the config from
     memory).
3. **Step-by-step procedure**
   1. Install prerequisites: `brew install restic rclone uv`.
   2. Clone/obtain the `turiya` source and `make install` (pins `turiya` on
      `PATH`) — or, if the source isn't handy, note this requires the repo;
      there's no PyPI package (confirmed out of scope elsewhere).
   3. Recreate `~/.config/turiya/config.toml`, either from the backed-up
      copy (recommended path) or from `config.example.toml` + memory.
   4. `rclone config` — re-authenticate each remote referenced by the
      restored config's `[[repo]]` entries (OAuth remotes need a fresh
      browser auth on the new machine).
   5. Put the recovered password into Keychain — either let `turiya setup`
      prompt for it, or `security add-generic-password` directly if
      restoring before running full `setup` (e.g. to avoid also installing
      the launchd schedule immediately).
   6. `turiya restore --target <somewhere>` (optionally scoped with
      `--repo`/`--include`/`--pattern`/`--glob` per the existing CLI
      reference).
4. **Verify, don't just read** — a short closing note recommending this
   procedure actually be *rehearsed* periodically (e.g. restore to a scratch
   directory on the current machine), not just trusted to work when needed —
   the general "you don't have a backup until you've tested a restore"
   principle.

### Verification of the doc itself

Before considering this done, run through the documented procedure for
real, simulating "fresh machine, nothing installed" conditions on the
current machine via `TURIYA_CONFIG` pointed at a scratch config and
`RESTIC_PASSWORD` set directly (bypassing Keychain, which is unaffected by
the simulation) against one of the real configured repos, restoring into a
scratch target directory. This is **read-only** against the repo — no data
is modified. Confirm each documented step matches actual behavior, including
what error appears if a step is skipped (e.g. missing `config.toml`, missing
remote auth), and correct the doc if reality differs from the draft above.

## Testing

- No automated tests — this is a documentation deliverable. "Testing" here
  is the manual verification pass described above, and its outcome (what
  actually happened at each step) is what the final `RECOVERY.md` text
  reflects.

## Success criteria

- `RECOVERY.md` exists at the repo root, cross-linked from `README.md` and
  listed in `CLAUDE.md`'s file map.
- Every command in the documented procedure has actually been run once
  during verification and produces the stated result (or the doc is
  corrected to match reality).
- The doc explicitly flags the `config.toml` single-point-of-failure and
  links to issue #12 rather than silently working around it.
- No code changes, no CHANGELOG/version bump (pure docs; if the team wants
  doc-only releases tracked, that's a separate, existing convention
  decision, not introduced here).
