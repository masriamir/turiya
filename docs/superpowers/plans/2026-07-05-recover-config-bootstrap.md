# `turiya recover-config` Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `turiya recover-config`, a new CLI command that restores
`config.toml` directly from a restic snapshot given only a repo URL and
password — no existing `config.toml` required — closing the weakest step
in `RECOVERY.md`'s manual disaster-recovery procedure.

**Architecture:** Two new thin restic primitives (`find_path`, `dump_file`)
in `src/turiya/restic.py`; a sixth operation, `operations/recover_config.py`,
that deliberately does **not** take `cfg: Config` (there is no config yet —
this is the one intentional exception to that convention, per the accepted
spec); a new `turiya recover-config` Typer command; doc updates.

**Tech Stack:** Python 3.14, existing `restic`/Typer/pydantic stack, no new
dependencies.

## Global Constraints

- No change to any of the five existing operations' signatures
  (`backup.run`, `restore.run`, `status.run`, `query.run`, `setup.run`/
  `teardown`) or the JSONL logging schema.
- The new operation's `run()` signature is exactly
  `run(*, repo: str, password: str, target: Path, force: bool = False) -> bool`
  — no `cfg: Config` parameter, no `StructuredLogger`. This is a deliberate,
  documented exception (see the spec's Design §3), not an oversight.
- `--target` defaults to `config.resolve_config_path(None)` — reuse that
  existing function verbatim, don't re-derive `TURIYA_CONFIG`-or-default
  logic locally.
- Refuse to overwrite an existing file at the target unless `--force` is
  given, raising `ConfigError` before any restic subprocess runs.
- No `--password` CLI flag — password comes from `RESTIC_PASSWORD` env var
  if set, else an interactive hidden prompt. This differs intentionally
  from `turiya setup --password`.
- `dump_file`'s errors are plain text on stderr (not restic's JSON
  `exit_error` shape) — don't route them through `parse_event`.
- All four gates (`pytest`, `ruff check`, `mypy src tests`, `ty check`) clean
  before every commit, per `CLAUDE.md`.

---

### Task 1: Restic primitives — `find_path` and `dump_file`

**Files:**
- Modify: `src/turiya/restic.py` (append after `run_json`)
- Test: `tests/test_restic.py` (append)

**Interfaces:**
- Produces: `find_path(repo: str, snapshot: str, *, password: str, name: str) -> str`
  and `dump_file(repo: str, snapshot: str, path: str, *, password: str) -> bytes`,
  both raising `turiya.errors.ResticError` on failure. Later tasks
  (`operations/recover_config.py`) call these two functions by these exact
  names and signatures.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_restic.py`:

```python
def test_find_path_returns_single_match(monkeypatch: pytest.MonkeyPatch) -> None:
    ls_output = (
        '{"message_type":"snapshot","time":"2026-01-01T00:00:00Z","paths":["/x"]}\n'
        '{"name":"other.txt","type":"file","path":"/x/other.txt","message_type":"node"}\n'
        '{"name":"config.toml","type":"file","path":"/x/config.toml","message_type":"node"}\n'
    )

    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert cmd[:2] == ["restic", "-r"]
        assert "ls" in cmd
        assert "--json" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=ls_output, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    path = restic.find_path("repo", "latest", password="x", name="config.toml")
    assert path == "/x/config.toml"


def test_find_path_raises_on_zero_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    ls_output = '{"message_type":"snapshot","time":"2026-01-01T00:00:00Z","paths":["/x"]}\n'

    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=ls_output, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="no.*config.toml"):
        restic.find_path("repo", "latest", password="x", name="config.toml")


def test_find_path_raises_on_multiple_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    ls_output = (
        '{"name":"config.toml","type":"file","path":"/a/config.toml","message_type":"node"}\n'
        '{"name":"config.toml","type":"file","path":"/b/config.toml","message_type":"node"}\n'
    )

    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=ls_output, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="multiple"):
        restic.find_path("repo", "latest", password="x", name="config.toml")


def test_find_path_raises_resticerror_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from turiya.errors import ResticError

    err = '{"message_type":"exit_error","code":1,"message":"no snapshot found"}\n'

    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=err)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="no snapshot found"):
        restic.find_path("repo", "latest", password="x", name="config.toml")


def test_dump_file_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert "dump" in cmd
        assert cmd[-2:] == ["latest", "/x/config.toml"]
        return subprocess.CompletedProcess(cmd, 0, stdout=b"sources = []\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    content = restic.dump_file("repo", "latest", "/x/config.toml", password="x")
    assert content == b"sources = []\n"


def test_dump_file_raises_on_plaintext_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    def _fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 1, stdout=b"", stderr=b'Fatal: cannot dump file: path "/x" not found in snapshot\n'
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="not found in snapshot"):
        restic.dump_file("repo", "latest", "/x/config.toml", password="x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_restic.py -k "find_path or dump_file" -v`
Expected: FAIL with `AttributeError: module 'turiya.restic' has no attribute 'find_path'` (and same for `dump_file`).

- [ ] **Step 3: Implement `find_path` and `dump_file`**

Append to `src/turiya/restic.py` (after the existing `run_json` function):

```python
def find_path(repo: str, snapshot: str, *, password: str, name: str) -> str:
    cmd = ["restic", "-r", repo, "ls", snapshot, "--recursive", "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env(password))
    if result.returncode != 0:
        message = f"restic exited with status {result.returncode}"
        for line in (result.stderr + result.stdout).splitlines():
            event = parse_event(line)
            if isinstance(event, ErrorEvent):
                message = event.message
                break
        raise ResticError(message)
    matches: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(obj, dict)
            and obj.get("message_type") == "node"
            and obj.get("type") == "file"
            and obj.get("name") == name
        ):
            path = obj.get("path")
            if isinstance(path, str):
                matches.append(path)
    if not matches:
        raise ResticError(f"no file named '{name}' found in {repo}'s {snapshot} snapshot")
    if len(matches) > 1:
        raise ResticError(
            f"multiple files named '{name}' found in {repo}'s {snapshot} snapshot: {matches}"
        )
    return matches[0]


def dump_file(repo: str, snapshot: str, path: str, *, password: str) -> bytes:
    cmd = ["restic", "-r", repo, "dump", snapshot, path]
    result = subprocess.run(cmd, capture_output=True, env=_env(password))
    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors="replace").strip()
        raise ResticError(stderr_text or f"restic dump exited with status {result.returncode}")
    return result.stdout
```

Note: `_env()` already exists in this file and returns `dict[str, str]` for
text-mode subprocess calls — it's reused as-is here; `subprocess.run` in
`dump_file` uses `capture_output=True` without `text=True` (bytes mode), so
`result.stdout`/`result.stderr` are `bytes`, matching the function's `bytes`
return type.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_restic.py -k "find_path or dump_file" -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full unit test file and the gate**

Run: `uv run pytest tests/test_restic.py -v && uv run ruff check src/turiya/restic.py tests/test_restic.py && uv run mypy src/turiya/restic.py tests/test_restic.py`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/restic.py tests/test_restic.py
git commit -m "feat(restic): add find_path/dump_file primitives for single-file recovery"
```

---

### Task 2: `operations/recover_config.py`

**Files:**
- Create: `src/turiya/operations/recover_config.py`
- Test: `tests/test_recover_config.py`

**Interfaces:**
- Consumes: `restic.find_path(repo, snapshot, *, password, name) -> str` and
  `restic.dump_file(repo, snapshot, path, *, password) -> bytes` (Task 1).
- Produces: `run(*, repo: str, password: str, target: Path, force: bool = False) -> bool`,
  raising `turiya.errors.ConfigError` if `target` already exists and
  `force` is `False`. Task 3 (CLI) calls this function by this exact name
  and signature.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recover_config.py`:

```python
from pathlib import Path

import pytest

from turiya import restic
from turiya.errors import ConfigError
from turiya.operations import recover_config


def test_run_writes_recovered_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "config.toml"

    monkeypatch.setattr(
        restic, "find_path", lambda *a, **k: "/home/user/.config/turiya/config.toml"
    )
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = []\n")

    assert recover_config.run(repo="repo", password="x", target=target) is True
    assert target.read_bytes() == b"sources = []\n"


def test_run_refuses_existing_target_without_force(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing content")

    with pytest.raises(ConfigError, match="already exists"):
        recover_config.run(repo="repo", password="x", target=target)

    # refused before touching restic at all: original content untouched
    assert target.read_text() == "existing content"


def test_run_overwrites_existing_target_with_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "config.toml"
    target.write_text("stale content")

    monkeypatch.setattr(restic, "find_path", lambda *a, **k: "/home/user/config.toml")
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = ['fresh']\n")

    assert recover_config.run(repo="repo", password="x", target=target, force=True) is True
    assert target.read_bytes() == b"sources = ['fresh']\n"


def test_run_creates_parent_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "config.toml"

    monkeypatch.setattr(restic, "find_path", lambda *a, **k: "/x/config.toml")
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = []\n")

    assert recover_config.run(repo="repo", password="x", target=target) is True
    assert target.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recover_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'turiya.operations.recover_config'`

- [ ] **Step 3: Implement the operation**

Create `src/turiya/operations/recover_config.py`:

```python
"""Bootstrap recovery: restore config.toml from a snapshot given only a repo URL + password.

No existing config.toml is required to run this — it's the one operation in
this codebase that intentionally does not take a Config or use
StructuredLogger, because its entire purpose is to run before a Config can
be loaded. See docs/superpowers/specs/2026-07-05-recover-config-bootstrap-design.md.
"""

from __future__ import annotations

from pathlib import Path

from .. import restic
from ..errors import ConfigError


def run(*, repo: str, password: str, target: Path, force: bool = False) -> bool:
    if target.exists() and not force:
        raise ConfigError(
            f"{target} already exists; pass --force to overwrite with the recovered version."
        )
    path = restic.find_path(repo, "latest", password=password, name="config.toml")
    content = restic.dump_file(repo, "latest", path, password=password)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    print(f"Recovered {target} from {repo} (latest snapshot).")
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recover_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the gate**

Run: `uv run pytest tests/test_recover_config.py -v && uv run ruff check src/turiya/operations/recover_config.py tests/test_recover_config.py && uv run mypy src/turiya/operations/recover_config.py tests/test_recover_config.py`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/operations/recover_config.py tests/test_recover_config.py
git commit -m "feat: add recover_config operation to bootstrap config.toml from a snapshot"
```

---

### Task 3: CLI wiring — `turiya recover-config`

**Files:**
- Modify: `src/turiya/cli.py`
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `recover_config.run(*, repo: str, password: str, target: Path, force: bool = False) -> bool`
  (Task 2); `config.resolve_config_path(explicit: Path | None = None) -> Path`
  (already exists in `src/turiya/config.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_recover_config_help_lists_new_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "recover-config" in result.stdout


def test_recover_config_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from turiya.operations import recover_config as recover_config_op

    monkeypatch.setenv("RESTIC_PASSWORD", "irrelevant")
    target = tmp_path / "config.toml"

    calls: dict[str, object] = {}

    def _fake_run(*, repo: str, password: str, target: Path, force: bool = False) -> bool:
        calls["repo"] = repo
        calls["password"] = password
        calls["target"] = target
        calls["force"] = force
        target.write_text("recovered")
        return True

    monkeypatch.setattr(recover_config_op, "run", _fake_run)
    result = runner.invoke(
        app, ["recover-config", "--repo", "rclone:gdrive:x", "--target", str(target)]
    )
    assert result.exit_code == 0
    assert calls["repo"] == "rclone:gdrive:x"
    assert calls["password"] == "irrelevant"
    assert calls["target"] == target
    assert calls["force"] is False


def test_recover_config_defaults_target_to_resolve_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from turiya.operations import recover_config as recover_config_op

    monkeypatch.setenv("RESTIC_PASSWORD", "irrelevant")
    default_path = tmp_path / "default-config.toml"
    monkeypatch.setenv("TURIYA_CONFIG", str(default_path))

    calls: dict[str, object] = {}

    def _fake_run(*, repo: str, password: str, target: Path, force: bool = False) -> bool:
        calls["target"] = target
        return True

    monkeypatch.setattr(recover_config_op, "run", _fake_run)
    result = runner.invoke(app, ["recover-config", "--repo", "rclone:gdrive:x"])
    assert result.exit_code == 0
    assert calls["target"] == default_path


def test_recover_config_operation_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from turiya.errors import ConfigError
    from turiya.operations import recover_config as recover_config_op

    monkeypatch.setenv("RESTIC_PASSWORD", "irrelevant")

    def _boom(*args: object, **kwargs: object) -> bool:
        raise ConfigError("already exists")

    monkeypatch.setattr(recover_config_op, "run", _boom)
    result = runner.invoke(
        app, ["recover-config", "--repo", "rclone:gdrive:x", "--target", str(tmp_path / "c.toml")]
    )
    assert result.exit_code == 1
    assert not isinstance(result.exception, ConfigError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k recover_config -v`
Expected: FAIL — `recover-config` not a recognized command (Typer usage error / exit code 2).

- [ ] **Step 3: Wire the command into `cli.py`**

Modify `src/turiya/cli.py`. Add this import alongside the existing operation
imports (after the `restore_op` import, keeping the existing alphabetical
grouping):

```python
from .operations import recover_config as recover_config_op
```

Add this import at the top-level alongside `import typer` (needed for
`Path` and the env lookup):

```python
import os
from pathlib import Path
```

Add this command, placed after `restore` and before `status` (grouped with
the other pre-setup bootstrap concern):

```python
@app.command("recover-config")
def recover_config(
    repo: str = typer.Option(..., "--repo"),
    target: Path | None = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    password = os.environ.get("RESTIC_PASSWORD") or typer.prompt(
        "Restic repository password", hide_input=True
    )
    resolved_target = target or config.resolve_config_path(None)
    try:
        ok = recover_config_op.run(
            repo=repo, password=password, target=resolved_target, force=force
        )
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=0 if ok else 1)
```

Note: this command does **not** call `_load()` — there is no config to load
yet, that's the entire point of this command.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (all existing + 4 new tests)

- [ ] **Step 5: Run the gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run ty check`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/cli.py tests/test_cli.py
git commit -m "feat(cli): wire up turiya recover-config"
```

---

### Task 4: Integration test against a real local restic repo

**Files:**
- Create: `tests/integration/test_recover_config.py`

**Interfaces:**
- Consumes: `recover_config.run(...)` (Task 2); `restic_repos: list[Path]`
  fixture and `PASSWORD = "testpass123"` constant, both already defined in
  `tests/conftest.py`.

- [ ] **Step 1: Write the test**

`tests/` and `tests/integration/` are both real packages (each has an
`__init__.py`), so `PASSWORD` — the fixed password constant already defined
in `tests/conftest.py` and used to `restic init` the `restic_repos` fixture
— is reachable with a relative import: `from ..conftest import PASSWORD`.
This must be the *same* password the repo was initialized with, or `restic
backup` against it in this test will fail to unlock the repo.

Create `tests/integration/test_recover_config.py`:

```python
import os
import subprocess
from pathlib import Path

import pytest

from turiya.errors import ResticError
from turiya.operations import recover_config

from ..conftest import PASSWORD


def _backup_fake_config(repo: Path, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('sources = ["~/Documents"]\n')
    env = {**os.environ, "RESTIC_PASSWORD": PASSWORD}
    subprocess.run(
        ["restic", "-r", str(repo), "backup", str(config_path)],
        check=True,
        capture_output=True,
        env=env,
    )


def test_recover_config_restores_real_snapshot(
    restic_repos: list[Path], tmp_path: Path
) -> None:
    repo = restic_repos[0]
    source_config = tmp_path / "source-home" / ".config" / "turiya" / "config.toml"
    _backup_fake_config(repo, source_config)

    recovered_target = tmp_path / "recovered" / "config.toml"
    ok = recover_config.run(
        repo=str(repo), password=PASSWORD, target=recovered_target
    )
    assert ok is True
    assert recovered_target.read_text() == 'sources = ["~/Documents"]\n'


def test_recover_config_raises_when_repo_has_no_config(
    restic_repos: list[Path], tmp_path: Path
) -> None:
    repo = restic_repos[1]  # initialized but nothing ever backed up to it
    with pytest.raises(ResticError):
        recover_config.run(
            repo=str(repo), password=PASSWORD, target=tmp_path / "config.toml"
        )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_recover_config.py -v`
Expected: PASS (2 tests) — this exercises `find_path`/`dump_file` against a
real `restic` binary, not mocks.

- [ ] **Step 3: Run the gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy src tests && uv run ty check`
Expected: all clean.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_recover_config.py
git commit -m "test: add integration test for recover-config against a real restic repo"
```

---

### Task 5: Documentation — README, CLAUDE.md, RECOVERY.md

**Files:**
- Modify: `README.md`
- Modify: `.claude/CLAUDE.md`
- Modify: `RECOVERY.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a CLI reference entry to `README.md`**

Insert this new subsection into `README.md`'s "## CLI reference" section,
immediately after the existing `### \`turiya setup\` / \`turiya teardown\``
subsection and before the section's closing `---`:

```markdown
### `turiya recover-config`

```bash
turiya recover-config --repo rclone:gdrive:turiya-backups
turiya recover-config --repo rclone:gdrive:turiya-backups --target /tmp/inspect-first.toml
turiya recover-config --repo rclone:gdrive:turiya-backups --force
```

Restores `config.toml` directly from a repo's latest snapshot — no existing
`config.toml` required to run it. Prompts for the restic password (or reads
`RESTIC_PASSWORD`), defaults `--target` to the same path `config.load()`
resolves (`TURIYA_CONFIG` env, else `~/.config/turiya/config.toml`), and
refuses to overwrite an existing file unless `--force` is given. See
`RECOVERY.md` for the full disaster-recovery procedure this fits into.
```

- [ ] **Step 2: Add `recover_config.py` to the repository-structure tree**

In `README.md`'s "## Repository structure" tree, add it to the `operations/`
listing:

```
│   ├── operations/
│   │   ├── backup.py
│   │   ├── restore.py
│   │   ├── status.py
│   │   ├── query.py
│   │   ├── setup.py                         # setup + teardown
│   │   └── recover_config.py                # bootstrap: restore config.toml from a bare repo+password
```

(Replace the existing 5-line `operations/` block with this 6-line one —
only the new last line is added, `setup.py`'s trailing comma/structure is
unchanged.)

- [ ] **Step 3: Add file-map rows to `.claude/CLAUDE.md`**

In the "File map" table, add a row immediately after the existing
`src/turiya/operations/setup.py` row:

```markdown
| `src/turiya/operations/recover_config.py` | `run(*, repo, password, target, force=False) -> bool`. Bootstraps `config.toml` from a bare repo URL + password, before any `Config` exists — the one operation that intentionally skips the `cfg: Config`/`StructuredLogger` convention below. See `docs/superpowers/specs/2026-07-05-recover-config-bootstrap-design.md`. |
```

- [ ] **Step 4: Update `RECOVERY.md` step 3**

In `RECOVERY.md`, replace the existing step 3 (currently reading
`**Recreate \`~/.config/turiya/config.toml\`** — copy back your saved copy
(recommended), or copy \`config.example.toml\` and fill in your
sources/excludes/retention/schedule/repo URLs from memory.`) with:

```markdown
3. **Recreate `~/.config/turiya/config.toml`.** If you have a repo URL and
   the password (from the prerequisites above), run:
   ```bash
   turiya recover-config --repo <your-repo-url>
   ```
   This restores `config.toml` directly from the repo's latest snapshot —
   no existing config needed. If it fails (e.g. the repo predates `turiya`
   backing up its own config), fall back to copying back a saved copy, or
   copying `config.example.toml` and filling in your
   sources/excludes/retention/schedule/repo URLs from memory.
```

- [ ] **Step 5: Verify placement**

Run: `grep -n "recover-config" README.md .claude/CLAUDE.md RECOVERY.md`
Expected: at least one match in each of the three files.

- [ ] **Step 6: Commit**

```bash
git add README.md .claude/CLAUDE.md RECOVERY.md
git commit -m "docs: document turiya recover-config in README, CLAUDE.md, and RECOVERY.md"
```

---

### Task 6: Final gate check

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run ty check`
Expected: all clean, including the new integration test exercising a real
`restic` binary.

- [ ] **Step 2: Confirm working tree is clean**

Run: `git status --short`
Expected: no output (all changes committed across Tasks 1–5).

## Self-Review Notes

- **Spec coverage:** command shape (`--repo`/`--target`/`--force`, no
  `--password`) ✓ Task 3; restic primitives (`find_path`/`dump_file`,
  JSONL parsing, plain-text dump errors) ✓ Task 1; operation layering
  deviation (no `cfg: Config`, no `StructuredLogger`, `print()` output) ✓
  Task 2; error handling (overwrite refusal, zero/multi-match, dump
  failure) ✓ Tasks 1–2; testing (unit + integration + CLI) ✓ Tasks 1, 2, 3,
  4; docs (README CLI reference + repo tree, CLAUDE.md file map, RECOVERY.md
  step 3) ✓ Task 5. No spec section lacks a task.
- **Placeholder scan:** no TBD/TODO; all code blocks are complete,
  runnable content, not descriptions.
- **Type consistency:** `run(*, repo: str, password: str, target: Path, force: bool = False) -> bool`
  is identical across the spec, Task 2's implementation, Task 3's CLI call
  site, and Task 4's integration test. `find_path`/`dump_file` signatures
  match between Task 1's implementation and Task 2's mocked usage.
