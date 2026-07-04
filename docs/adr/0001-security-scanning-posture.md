# ADR-0001: Security Scanning Posture

- **Status:** Accepted
- **Date:** 2026-07-03
- **Deciders:** @masriamir
- **Supersedes:** —
- **Superseded by:** —

## Context and Problem Statement

turiya automates encrypted, versioned backups of a Mac's important directories
to cloud remotes via `restic` + `rclone`. The repository is **public**, which
makes the full suite of GitHub Advanced Security features available at no cost.
Several are already enabled (CodeQL, secret scanning, push protection,
Dependabot). We want a **thorough, deliberately-scoped security scanning
posture** — and, just as importantly, a written record of what we *don't* do,
so the setup does not accrete redundant, overlapping tools over time.

The guiding question this ADR answers: **what is the complete set of automated
security controls for this repository, why each one earns its place, and what
have we consciously rejected or deferred?**

### Threat model (why this ADR is weighted the way it is)

turiya's own Python is small, pure, and processes no untrusted network input.
A general-purpose SAST tool will find little in it. The genuine attack surface
is narrower and more specific:

1. **The CI supply chain.** GitHub Actions workflows run with a token that can
   read the repo and write security events. A compromised or retagged
   third-party action executes in that context. This is the single largest
   realistic risk for a project of this size.
2. **Subprocess construction.** The core wraps `restic` and `rclone` via
   `subprocess`. Argument assembly is the one place in our own code where a
   command-injection-shaped bug could plausibly live.
3. **Secret handling.** The restic repository password lives in the macOS
   Keychain and is passed to subprocesses via the environment. Leaking it into
   logs or committing it would be the highest-impact code defect.

The posture below therefore **weights supply-chain hardening and subprocess
SAST above generic dependency scanning**, and rejects tools that merely
duplicate controls already in force.

## Decision Drivers

- **No duplication.** Every control must cover something no other enabled
  control already covers. Overlap is the primary failure mode we are guarding
  against.
- **Real teeth where it counts.** The maintainer has opted for **maximum**
  enforcement: security-relevant checks block merges rather than merely
  reporting.
- **Solo-maintainer sustainability.** Controls that can never pass for a
  single-maintainer repo (e.g. mandatory second-reviewer checks) must not hard-
  gate CI, or they turn the pipeline permanently red for unfixable reasons.
- **Low future friction.** Controls that only become relevant at first
  publish (provenance, signing) should be *designed now and wired up later*, so
  there is no design work left at release time.
- **Everything as code, except what genuinely cannot be.** Repository settings
  that have no file representation are captured here as an explicit operational
  checklist so they are auditable and reproducible.

## Considered Options

1. **Minimal** — `SECURITY.md` plus a maxed-out `codeql.yml`, nothing else.
   Rejected: leaves the two highest-value gaps (Actions supply chain,
   subprocess SAST) unaddressed, and does nothing about the duplication risk.
2. **Everything-on** — add `pip-audit`, standalone Bandit, gitleaks/trufflehog,
   SLSA, SBOM publishing, artifact signing, and an enforced Scorecard gate on
   top of what already exists. Rejected: most of it duplicates enabled controls
   and several pieces cannot pass or add no value pre-publish.
3. **Threat-model-weighted posture (chosen).** Document the whole posture,
   affirm what already exists, add only controls that close a real gap, gate
   the ones with teeth, defer publish-only controls behind a named trigger, and
   record the rejections. See "Decision Outcome".

## Decision Outcome

Chosen option: **the threat-model-weighted posture**, at **maximum enforcement**
with two deliberate exceptions (OpenSSF Scorecard runs advisory; publish-only
controls are deferred). The full posture is the union of sections A–F below.

### A. Controls already in place (affirmed, not re-litigated)

These are current, deliberate decisions. This ADR records them so a future
contributor does not re-add an equivalent tool believing it is missing.

| Control | Mechanism | Why it is sufficient as-is |
|---|---|---|
| **CodeQL SAST** | `.github/workflows/codeql.yml` (`python`, `security-and-quality`) | GitHub-native SAST with the most extensive first-party query suite; hardened further in §C. |
| **Secret scanning** | Repo setting (enabled) | Native detection of committed credentials across history. |
| **Push protection** | Repo setting (enabled) | Blocks secrets *before* they land, not just after. |
| **Dependabot version updates** | `.github/dependabot.yml` (`uv` + `github-actions`) | Keeps dependencies and pinned actions current. |
| **Dependabot security updates** | Repo setting (enabled) | Opens fix PRs for known-vulnerable dependencies automatically. |

### B. `SECURITY.md` and coordinated disclosure

Add a root `SECURITY.md` that specifies:

- **Supported versions** — the current `2.x` line receives security fixes.
- **Reporting channel** — GitHub **private vulnerability reporting** (Security →
  Advisories) as the sole primary channel; no personal email is published.
- **Response expectations** — acknowledge within 3 business days; triage and
  target-fix window stated as a good-faith goal, not a contractual SLA.
- **Scope** — in scope: turiya's own handling of the restic password, Keychain
  access, subprocess construction, and log redaction. Out of scope:
  vulnerabilities in `restic`, `rclone`, or the user's cloud remotes
  themselves (report those upstream).
- **Safe harbor** — a short good-faith-research statement.

This requires enabling **private vulnerability reporting** (a repository
setting — see §D).

### C. New and hardened automated controls

| Control | File / location | Enforcement |
|---|---|---|
| **Ruff `S` (flake8-bandit)** added to `select`, tuned per Consequences | `pyproject.toml` | **Blocks** — runs inside the existing `ruff check` CI gate. Keeps the shell-injection rules (`S602`/`S604`/`S605`/`S609`) active as a guardrail on subprocess construction (threat #2). Subsumes standalone Bandit. |
| **`dependency-review-action`** on `pull_request` | new `.github/workflows/dependency-review.yml` | **Blocks** — fails a PR that *introduces* a vulnerable dependency or a disallowed license, at review time (Dependabot only reacts post-merge). |
| **zizmor** (GitHub Actions static analysis) in **pedantic** mode, SARIF uploaded | new `.github/workflows/zizmor.yml` | **Blocks** — catches template-injection, over-broad `permissions`, unpinned actions, and other workflow-level defects (threat #1). |
| **CodeQL hardening** — explicit `build-mode: none`, minimal top-level `permissions`, SHA-pinned actions | `.github/workflows/codeql.yml` | Code-scanning results made a **required** check via branch protection (§D). |
| **SHA-pin all third-party *and* first-party actions** (`actions/*`, `github/codeql-action/*`, etc.) to full commit SHAs, with a trailing `# vX.Y.Z` comment; Dependabot bumps them | every workflow file | n/a (hardening). Removes the retag-attack vector (threat #1). |
| **OpenSSF Scorecard** — scheduled + on push to `main`, SARIF to Security tab, README trend badge | new `.github/workflows/scorecard.yml` | **Advisory** (see rationale in "Consequences"). |

### D. Repository settings this ADR mandates (operational checklist)

These have no file representation and must be set in the GitHub UI/API. They are
listed here so the posture is fully auditable:

- [ ] Enable **private vulnerability reporting** (required by §B).
- [ ] Enable secret scanning **non-provider patterns** (currently off).
- [ ] Enable secret scanning **validity checks** (currently off).
- [ ] Create a **branch-protection ruleset** on `main` requiring, as **required
      status checks**: the CI `gates` job, CodeQL code-scanning results, the
      `zizmor` job, and the `dependency-review` job.
- [ ] Require branches to be **up to date** before merging.
- [ ] Require a pull request before merging (no direct pushes to `main`).

### E. Rejected — with rationale (the anti-duplication core)

| Rejected control | Why (what already covers it) |
|---|---|
| **`pip-audit` / `uv audit` CVE scan in CI** | Redundant with Dependabot security updates (post-merge) + `dependency-review-action` (pre-merge). Adds a third scanner of the same dependency set with no new coverage. |
| **Standalone Bandit** | Subsumed by Ruff's `S` (flake8-bandit) rules, which run in a gate we already have. Two Bandit engines, one signal. |
| **gitleaks / trufflehog** | Redundant with native GitHub secret scanning + push protection, which additionally block *before* commit and understand provider-specific patterns. |
| **CodeQL "quality" queries vs. ruff/mypy** | Overlap acknowledged, but the `security-and-quality` suite is **kept** for its security half; the quality overlap is harmless and not worth splitting the query pack over. |

### F. Deferred behind a named trigger — publish-readiness

turiya is currently installed from source (`uv tool install .`); it publishes
no artifact, so provenance and signing would attest and sign things that do not
exist. These controls are **designed now and deferred**, with an explicit
trigger so there is no design work left when the time comes.

**Trigger:** the first PyPI publish *or* the first GitHub Release that attaches
a built binary/wheel.

**Pre-decided approach (to be wired up at the trigger, not before):**

- **PyPI Trusted Publishing** (OIDC) via `pypa/gh-action-pypi-publish` — no
  long-lived PyPI token stored in the repo.
- **Build provenance attestations** emitted by that same publish action
  (`attestations: true`), giving SLSA-style provenance for wheels/sdists.
- **Sigstore/cosign signing** for any standalone release binaries attached to a
  GitHub Release.
- **SBOM** — rely on GitHub's auto-generated dependency-graph SBOM (exportable
  today); revisit publishing a CycloneDX/SPDX SBOM as a release asset only if a
  downstream consumer asks for one.

Until the trigger fires, none of the above is implemented; this section is the
standing decision that removes the future design step.

## Consequences

**Positive**

- A single canonical reference for the entire security posture, including the
  reasoning for both inclusions and exclusions.
- The two real threats — CI supply chain and subprocess construction — are
  gated at merge time, not merely reported.
- Publish-time security is a solved design problem the day publishing begins.

**Negative / trade-offs (accepted deliberately)**

- **More required checks = more PR friction**, plus recurring Dependabot churn
  from SHA-pin bumps. Accepted as the cost of "maximum".
- **Ruff `S` is tuned, not suppressed per-site.** Enabling the full `S`
  family surfaces 23 findings in `src/` and 121 in `tests/`, dominated by rules
  that carry no signal here: `S603` fires on *every* `subprocess.run`
  regardless of safety (it detects nothing on its own), `S607` fires because we
  deliberately resolve system tools (`restic`/`rclone`/`launchctl`/`sudo`) via
  `PATH`, and `S101` fires on every pytest `assert`. The value of enabling `S`
  is the *latent* injection guardrail — `S602` (`shell=True`), `S604`, `S605`,
  `S609` — which finds nothing today and stays active for future code.
  Convention, therefore:
  - Globally `ignore = ["S603", "S607"]` in `[tool.ruff.lint]`, each with a
    one-line rationale comment, rather than scattering 22 identical `# noqa`
    suppressions across the six core modules.
  - `per-file-ignores` for `"tests/**"` covering `S101`, `S105`, `S106`,
    `S108`, `S603`, `S607` — asserts, dummy passwords, and temp paths are
    correct idiom in test code, not defects.
  - The single `src` `S101` (a type-narrowing `assert` in `restic.py`) is
    replaced with an explicit `None`-guard, since `python -O` would strip the
    assert and the guarded branch is real.
  - The injection-detecting rules stay enabled, so a future `shell=True` or
    `os.system` call fails the existing `ruff check` gate.
- **OpenSSF Scorecard is advisory, not gated.** Rationale: (1) several Scorecard
  checks are structurally unwinnable for a solo-maintainer repo (e.g.
  Code-Review penalizes self-merge; Fuzzing requires OSS-Fuzz), so an enforced
  threshold would red-line CI for reasons that cannot be fixed; and (2)
  Scorecard is largely a *meta-measurement* of controls this posture already
  enforces individually (pinning, permissions, branch protection, SAST) — gating
  on it too would itself be duplication. It runs for trend visibility only.

### Confirmation

The posture is satisfied when:

- Every merge to `main` is green across the CI `gates` job, CodeQL, `zizmor`,
  and `dependency-review`.
- The GitHub **Security** tab shows zero unresolved high/critical alerts.
- A reported vulnerability has a defined private channel (§B) and a stated
  acknowledgement window.
- The §D checklist is fully checked off in repository settings.

## More Information

- This is the first ADR in `docs/adr/`; it establishes the **MADR** format as
  the convention for the remaining architecture decisions tracked in `todo.md`.
- Related project docs: `CLAUDE.md` (architecture + gates), `CONTRIBUTING.md`,
  `.github/workflows/ci.yml`, `.github/dependabot.yml`.
- Implementation of this ADR is intentionally out of scope for the ADR itself;
  it will be carried out under a separate implementation plan and pull request.
