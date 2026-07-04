# Security Scanning Posture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the automated security scanning posture decided in `docs/adr/0001-security-scanning-posture.md` — a `SECURITY.md`, tuned Ruff `S` rules, hardened + SHA-pinned workflows, new dependency-review / zizmor / Scorecard workflows, and the repository-settings checklist.

**Architecture:** Everything that can be code is code. Ruff config changes live in `pyproject.toml`; each scanner is its own GitHub Actions workflow under `.github/workflows/`; the existing `ci.yml` and `codeql.yml` are hardened in place. Repository settings that have no file representation are applied via `gh api` in the final task. All actions are pinned to full commit SHAs with a trailing `# <version>` comment; Dependabot's existing `github-actions` ecosystem entry bumps them.

**Tech Stack:** Python 3.14 + uv, Ruff (flake8-bandit `S`), GitHub Actions, CodeQL, OpenSSF Scorecard, zizmor, `actions/dependency-review-action`, `gh` CLI.

## Global Constraints

- **Repository:** `masriamir/turiya`, **public**.
- **Enforcement level: maximum** — new scanners block PRs; only OpenSSF Scorecard is advisory (per ADR).
- **Action pinning:** every `uses:` MUST be a full 40-char commit SHA with a trailing `# <tag>` comment. No `@v*` tag or branch refs anywhere.
- **Checkout hardening:** every `actions/checkout` step MUST set `persist-credentials: false` (zizmor `artipacked`).
- **Least privilege:** every workflow sets a top-level `permissions: {}` and grants the minimum per-job scopes.
- **Pinned SHAs to use verbatim** (resolved 2026-07-03):
  | Action | Pin | Comment |
  |---|---|---|
  | `actions/checkout` | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` | `# v7.0.0` |
  | `astral-sh/setup-uv` | `37802adc94f370d6bfd71619e3f0bf239e1f3b78` | `# v7` |
  | `github/codeql-action/*` | `54f647b7e1bb85c95cddabcd46b0c578ec92bc1a` | `# v4` |
  | `actions/dependency-review-action` | `a1d282b36b6f3519aa1f3fc636f609c47dddb294` | `# v5.0.0` |
  | `zizmorcore/zizmor-action` | `192e21d79ab29983730a13d1382995c2307fbcaa` | `# v0.5.7` |
  | `ossf/scorecard-action` | `4eaacf0543bb3f2c246792bd56e8cdeffafb205a` | `# v2.4.3` |
  | `actions/upload-artifact` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | `# v7.0.1` |
- **Gates that must stay green** (run before every commit): `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run ty check`.
- **Branch:** all work lands on `docs/security-scanning-adr` (already checked out; the ADR is already committed there).

---

### Task 1: Enable and tune Ruff `S` (flake8-bandit) + fix the `src` `S101`

**Files:**
- Modify: `pyproject.toml` (the `[tool.ruff.lint]` block, currently line ~30–31)
- Modify: `src/turiya/restic.py:88` (replace the type-narrowing `assert`)
- Test: `tests/test_restic.py` (add one test, mirroring the existing `FakePopen` pattern)

**Interfaces:**
- Consumes: `turiya.restic.stream(repo, args, *, password, dry_run=False)` (existing generator), `turiya.errors.ResticError` (existing).
- Produces: no new public API. `restic.stream` now raises `ResticError` instead of `AssertionError` when the subprocess yields no stdout pipe.

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_restic.py` (it already imports `subprocess`, `pytest`, and `restic`):

```python
def test_stream_raises_resticerror_when_no_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    class NoStdoutPopen:
        stdout = None

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: NoStdoutPopen())
    gen = restic.stream("repo", ["backup"], password="x")
    with pytest.raises(ResticError):
        next(gen)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_restic.py::test_stream_raises_resticerror_when_no_stdout -v`
Expected: FAIL — raises `AssertionError` (from the current `assert proc.stdout is not None`), not `ResticError`.

- [ ] **Step 3: Replace the assert with a real guard**

In `src/turiya/restic.py`, replace this line inside `stream()` (currently line 88):

```python
    assert proc.stdout is not None
```

with:

```python
    if proc.stdout is None:  # defensive: PIPE requested above, so this is unreachable in practice
        raise ResticError("restic produced no output stream")
```

Ensure `ResticError` is imported at the top of `src/turiya/restic.py`. Check the existing imports; if it is not already imported, add:

```python
from turiya.errors import ResticError
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_restic.py::test_stream_raises_resticerror_when_no_stdout -v`
Expected: PASS.

- [ ] **Step 5: Enable and tune `S` in `pyproject.toml`**

Replace the current `[tool.ruff.lint]` block:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

with:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "S"]
# S603 fires on every subprocess.run regardless of safety (detects nothing on
# its own); S607 fires because we resolve system tools (restic/rclone/launchctl/
# sudo/find/security) via PATH by design. The injection-detecting rules in the S
# family (S602 shell=True, S604, S605, S609) stay active as a guardrail.
ignore = ["S603", "S607"]

[tool.ruff.lint.per-file-ignores]
# Test code legitimately uses asserts (S101), dummy credentials (S105/S106),
# hardcoded temp paths (S108), and spawns subprocesses (S603/S607).
"tests/**" = ["S101", "S105", "S106", "S108", "S603", "S607"]
```

Leave the existing `[tool.ruff.lint.flake8-bugbear]` block below it untouched.

- [ ] **Step 6: Verify the full lint + format + type gates are clean**

Run: `uv run ruff check .`
Expected: `All checks passed!` (0 errors — the `src` `S603`/`S607` are ignored, the `S101` is fixed, tests are per-file-ignored).

Run: `uv run ruff format --check .`
Expected: no reformatting needed.

Run: `uv run pytest`
Expected: all tests pass.

Run: `uv run mypy src tests` then `uv run ty check`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/turiya/restic.py tests/test_restic.py
git commit -m "feat(security): enable and tune ruff flake8-bandit (S) rules"
```

---

### Task 2: Add `SECURITY.md` and enable private vulnerability reporting

**Files:**
- Create: `SECURITY.md` (repo root — GitHub auto-detects it here)

**Interfaces:** none (documentation + a repo setting).

- [ ] **Step 1: Write `SECURITY.md`**

Create `SECURITY.md` with exactly this content:

```markdown
# Security Policy

## Supported Versions

turiya is released from `main` and versioned with semantic versioning. Security
fixes are applied to the current `2.x` line.

| Version | Supported |
|---------|-----------|
| `2.x`   | ✅        |
| `< 2.0` | ❌        |

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's **[private vulnerability reporting](https://github.com/masriamir/turiya/security/advisories/new)**
(the "Report a vulnerability" button under this repository's **Security** tab).
This creates a private advisory visible only to you and the maintainer.

You can expect an acknowledgement within **3 business days**. We will confirm the
issue, agree on a disclosure timeline with you, and credit you in the advisory
unless you prefer to remain anonymous.

## Scope

**In scope** — defects in turiya's own code, including:

- handling of the restic repository password (Keychain access, environment
  passing, and log redaction);
- construction of `restic`, `rclone`, `launchctl`, and other subprocess
  invocations;
- the launchd/pmset scheduling artifacts turiya writes.

**Out of scope** — vulnerabilities in `restic`, `rclone`, the cloud remotes, or
macOS themselves. Please report those to their respective upstream projects.

## Safe Harbor

We consider good-faith security research that respects this policy to be
authorized. We will not pursue or support legal action against researchers who
report vulnerabilities responsibly and avoid privacy violations, data
destruction, or service disruption while investigating.
```

- [ ] **Step 2: Verify GitHub recognizes the policy**

Run: `test -f SECURITY.md && echo "present"`
Expected: `present`. (After merge, the file surfaces at the repo's **Security → Policy** tab; nothing else to verify locally.)

- [ ] **Step 3: Commit**

```bash
git add SECURITY.md
git commit -m "docs(security): add SECURITY.md vulnerability disclosure policy"
```

- [ ] **Step 4: Enable private vulnerability reporting (repo setting — do now so the link in `SECURITY.md` works)**

Run:

```bash
gh api -X PUT repos/masriamir/turiya/private-vulnerability-reporting
```

Expected: HTTP 204 (no output). Verify:

```bash
gh api repos/masriamir/turiya/private-vulnerability-reporting --jq '.enabled'
```

Expected: `true`.

---

### Task 3: Harden and SHA-pin the existing workflows (`codeql.yml`, `ci.yml`)

**Files:**
- Modify: `.github/workflows/codeql.yml` (full rewrite below)
- Modify: `.github/workflows/ci.yml` (pin two actions + harden checkout)

**Interfaces:** none. The CodeQL check-run name stays `analyze (python)`; the CI check-run name stays `gates` (both are referenced as required checks in Task 7).

- [ ] **Step 1: Rewrite `.github/workflows/codeql.yml`**

Replace the entire file with:

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "27 4 * * 1"
  workflow_dispatch:

permissions: {}

jobs:
  analyze:
    name: analyze (python)
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false

      - name: Initialize CodeQL
        uses: github/codeql-action/init@54f647b7e1bb85c95cddabcd46b0c578ec92bc1a # v4
        with:
          languages: python
          build-mode: none
          queries: security-and-quality

      - name: Perform CodeQL analysis
        uses: github/codeql-action/analyze@54f647b7e1bb85c95cddabcd46b0c578ec92bc1a # v4
        with:
          category: "/language:python"
```

- [ ] **Step 2: Harden the checkout + pin actions in `.github/workflows/ci.yml`**

In `.github/workflows/ci.yml`, make three edits (leave everything else — `concurrency`, the restic install, the gate steps — untouched):

Change:
```yaml
      - uses: actions/checkout@v7
```
to:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
```

Change:
```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v7
```
to:
```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7
```

(The existing top-level `permissions: contents: read` in `ci.yml` is already least-privilege — leave it.)

- [ ] **Step 3: Validate both workflows parse and are pin-clean**

Run:
```bash
uvx zizmor@1 --offline .github/workflows/codeql.yml .github/workflows/ci.yml
```
Expected: no `unpinned-uses` and no `artipacked` findings for these two files. (Offline mode skips 3 token-only audits, which is fine here.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/codeql.yml .github/workflows/ci.yml
git commit -m "ci(security): SHA-pin actions and harden codeql/ci workflows"
```

---

### Task 4: Add the dependency-review workflow (blocking on PRs)

**Files:**
- Create: `.github/workflows/dependency-review.yml`

**Interfaces:** produces a required PR check named `dependency-review` (referenced in Task 7).

- [ ] **Step 1: Create `.github/workflows/dependency-review.yml`**

```yaml
name: Dependency Review

on:
  pull_request:
    branches: [main]

permissions: {}

jobs:
  dependency-review:
    name: dependency-review
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false

      - name: Dependency Review
        uses: actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294 # v5.0.0
        with:
          fail-on-severity: low
          deny-licenses: GPL-2.0-only, GPL-3.0-only, AGPL-3.0-only
          comment-summary-in-pr: on-failure
```

- [ ] **Step 2: Validate it parses and is pin-clean**

Run:
```bash
uvx zizmor@1 --offline .github/workflows/dependency-review.yml
```
Expected: no `unpinned-uses` / `artipacked` findings.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/dependency-review.yml
git commit -m "ci(security): add blocking dependency-review workflow"
```

> **Note on `deny-licenses`:** on the first PR run, if a transitive dependency has no SPDX-detectable license the action reports it as "unknown" — triage it then (confirm the real license and, if benign, it will pass; the current direct deps `typer`/`pydantic` and their transitives are BSD/MIT/Apache). Do not remove the line to silence it; investigate the specific dependency.

---

### Task 5: Add the zizmor workflow (pedantic, blocking) and prove the repo is clean

**Files:**
- Create: `.github/workflows/zizmor.yml`

**Interfaces:** produces a required PR check named `zizmor` (referenced in Task 7); uploads SARIF to the Security tab.

- [ ] **Step 1: Create `.github/workflows/zizmor.yml`**

```yaml
name: zizmor

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions: {}

jobs:
  zizmor:
    name: zizmor
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false

      - name: Run zizmor
        uses: zizmorcore/zizmor-action@192e21d79ab29983730a13d1382995c2307fbcaa # v0.5.7
        with:
          persona: pedantic
```

- [ ] **Step 2: Run zizmor in pedantic mode over ALL workflows locally**

Run:
```bash
uvx zizmor@1 --persona=pedantic --offline .github/workflows
```
Expected: **0 findings** across `ci.yml`, `codeql.yml`, `dependency-review.yml`, and `zizmor.yml`.

If pedantic surfaces a finding that is a deliberate, accepted design choice (not something to fix), suppress it *inline* at the offending line with a documented comment rather than lowering the persona:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0 # zizmor: ignore[<audit-name>] <one-line reason>
```
Do this only after confirming the finding is genuinely non-actionable; the goal is a clean pedantic run with every exception visible in-file.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/zizmor.yml
git commit -m "ci(security): add blocking zizmor workflow (pedantic)"
```

---

### Task 6: Add the OpenSSF Scorecard workflow (advisory) and README badge

**Files:**
- Create: `.github/workflows/scorecard.yml`
- Modify: `README.md` (add a badge near the top, after the title block)

**Interfaces:** none required by other tasks. Publishes SARIF to the Security tab and results to the public Scorecard API (for the badge). **Not** a gating check.

- [ ] **Step 1: Create `.github/workflows/scorecard.yml`**

```yaml
name: Scorecard

on:
  branch_protection_rule:
  schedule:
    - cron: "18 5 * * 1"
  push:
    branches: [main]
  workflow_dispatch:

permissions: {}

jobs:
  analysis:
    name: Scorecard analysis
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      id-token: write
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false

      - name: Run analysis
        uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a # v2.4.3
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true

      - name: Upload artifact
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: SARIF file
          path: results.sarif
          retention-days: 5

      - name: Upload to code scanning
        uses: github/codeql-action/upload-sarif@54f647b7e1bb85c95cddabcd46b0c578ec92bc1a # v4
        with:
          sarif_file: results.sarif
```

- [ ] **Step 2: Validate pedantic-clean (Scorecard workflow included)**

Run:
```bash
uvx zizmor@1 --persona=pedantic --offline .github/workflows
```
Expected: still **0 findings** (now including `scorecard.yml`). Apply the same inline-suppression rule from Task 5 Step 2 if needed.

- [ ] **Step 3: Add the Scorecard badge to `README.md`**

In `README.md`, immediately after the `# turiya` title line and its one-line description (before the `Targets:` line), insert a blank line and this badge:

```markdown
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/masriamir/turiya/badge)](https://scorecard.dev/viewer/?uri=github.com/masriamir/turiya)
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/scorecard.yml README.md
git commit -m "ci(security): add advisory OpenSSF Scorecard workflow and badge"
```

> **Note:** the badge and the Scorecard API results only populate after this workflow runs on `main` post-merge; the badge may 404 until then. This is expected.

---

### Task 7: Apply repository settings and required-check ruleset; accept the ADR

**Files:**
- Modify: `docs/adr/0001-security-scanning-posture.md` (flip Status to Accepted)
- Create: `scratchpad only` — a temporary `ruleset.json` (not committed)

**Interfaces:** none. This task realizes ADR §D. Several steps are `gh api` calls, not file changes; run them against `masriamir/turiya`.

- [ ] **Step 1: Enable the two secret-scanning knobs**

Run:
```bash
gh api -X PATCH repos/masriamir/turiya \
  -f 'security_and_analysis[secret_scanning_non_provider_patterns][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_validity_checks][status]=enabled'
```
Verify:
```bash
gh api repos/masriamir/turiya --jq '.security_and_analysis | {np: .secret_scanning_non_provider_patterns.status, vc: .secret_scanning_validity_checks.status}'
```
Expected: `{"np":"enabled","vc":"enabled"}`.

(Private vulnerability reporting was already enabled in Task 2 Step 4.)

- [ ] **Step 2: Write the branch-protection ruleset JSON**

Write this to a scratch file (e.g. the session scratchpad, NOT the repo):

```json
{
  "name": "main protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      }
    },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "gates" },
          { "context": "analyze (python)" },
          { "context": "zizmor" },
          { "context": "dependency-review" },
          { "context": "CodeQL" }
        ]
      }
    }
  ]
}
```

Notes: `strict_required_status_checks_policy: true` = "require branches up to date". `required_approving_review_count: 0` because this is a solo repo — the rule still forces a PR (no direct pushes to `main`) without blocking on an unavailable second reviewer. The `"CodeQL"` context is the code-scanning results check; `"analyze (python)"` is the workflow job run — both are listed so code-scanning results gate merges.

- [ ] **Step 3: Apply the ruleset**

Run (replace `<path>` with the scratch file path):
```bash
gh api -X POST repos/masriamir/turiya/rulesets --input <path>/ruleset.json
```
Expected: JSON describing the created ruleset with `"enforcement": "active"`. Verify:
```bash
gh api repos/masriamir/turiya/rulesets --jq '.[] | {name, enforcement}'
```
Expected: includes `{"name":"main protection","enforcement":"active"}`.

- [ ] **Step 4: Flip the ADR status to Accepted**

In `docs/adr/0001-security-scanning-posture.md`, change:
```markdown
- **Status:** Proposed
```
to:
```markdown
- **Status:** Accepted
```

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0001-security-scanning-posture.md
git commit -m "docs(adr): accept ADR-0001 security scanning posture"
```

- [ ] **Step 6: Open the PR (do NOT merge — the maintainer merges)**

```bash
git push -u origin docs/security-scanning-adr
gh pr create --fill --base main
```

Then verify on the PR that the new checks (`gates`, `analyze (python)`, `zizmor`, `dependency-review`, CodeQL) all run and pass. Address any failures before requesting review. Leave merging to the maintainer.

---

## Self-Review

**Spec coverage (ADR §A–F + Consequences):**
- §A already-in-place controls — no code change; affirmed in ADR. ✓ (no task needed)
- §B `SECURITY.md` + private vuln reporting — Task 2. ✓
- §C Ruff `S` — Task 1; dependency-review — Task 4; zizmor — Task 5; CodeQL hardening — Task 3; SHA-pin all — Tasks 3–6; Scorecard advisory — Task 6. ✓
- §D repo settings (private reporting, secret-scan knobs, ruleset, up-to-date, PR-required) — Task 2 Step 4 + Task 7. ✓
- §E rejected controls — nothing to implement (correctly absent). ✓
- §F deferred publish controls — nothing to implement now (correctly absent). ✓
- Consequences: ruff `S` tuning (global ignore + per-file-ignore + restic guard) — Task 1; `# zizmor: ignore` escape hatch — Task 5 Step 2. ✓

**Placeholder scan:** No TBD/TODO. Every workflow, config block, and test is shown in full. The only `<path>` placeholder (Task 7 Step 3) is a local scratch path, explained in place. ✓

**Type/name consistency:** Check-run names are consistent between the workflows that produce them and the ruleset that requires them — `gates` (ci.yml job), `analyze (python)` (codeql.yml job `name:`), `zizmor` (zizmor.yml job), `dependency-review` (dependency-review.yml job), plus the `CodeQL` code-scanning context. SHAs match the Global Constraints table everywhere they appear. `ResticError` is the existing error type used in both the test and the guard. ✓
