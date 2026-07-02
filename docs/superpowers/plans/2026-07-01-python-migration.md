# Python Migration (v2.0.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the turiya bash tool as a library-first Python 3.14 package (`turiya`) at feature parity with v1.0.0, folding in items 2 (de-hardcode name), 10 (CLI UX), and 11 (flexible scheduling).

**Architecture:** A layered package under `src/turiya/`: low-level modules (`config`, `errors`, `keychain`, `restic`, `rclone`, `logging`, `scheduling`) with a single clear responsibility each, an `operations/` layer that contains the backup/restore/status/query/setup logic and emits structured events, and a thin Typer `cli` on top. The future read-only dashboard imports `operations` + `config` directly, never `cli`.

**Tech Stack:** Python 3.14, uv (env/lock), Typer (CLI), pydantic v2 (config), pytest (tests), ruff (lint+format), mypy + ty (type checks). restic/rclone/security invoked via `subprocess`. No `jq`.

## Global Constraints

- Python **3.14** (`requires-python = ">=3.14"`); uv manages the interpreter and `uv.lock`.
- All tooling config in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.ty]`, `[tool.pytest.ini_options]`). Runtime config is TOML.
- Runtime dependencies limited to `typer` and `pydantic` (v2). Everything else stdlib. Do NOT add `jq`, `jinja2`, `keyring`, or a TOML writer.
- Config read-only via stdlib `tomllib`. Config location: `~/.config/turiya/config.toml`, overridable via `TURIYA_CONFIG`.
- `RESTIC_PASSWORD` in the environment short-circuits the Keychain lookup (test hook).
- restic invoked with `--json --verbose=2` for streaming ops; **stderr is always captured and merged** — restic writes fatal errors as `message_type: "exit_error"` JSON to stderr. Never swallow a restic failure.
- JSONL log schema is **byte-compatible with v1.0.0**: envelope `{ts, op, repo, level, event, ...}`; `repo` is `null` for repo-agnostic events; events ∈ `run_start | file | summary | error | run_end | prune`; files `ops.jsonl` + `<op>.jsonl` + `<op>.log` under the log dir; size-rotated at `max_bytes`; `json_per_file=false` suppresses only `file` events.
- All commands run via `uv run` (e.g. `uv run pytest`, `uv run ruff check .`, `uv run mypy src`, `uv run ty check`).
- Every module gets type hints; `mypy src` and `ty check` must pass clean.
- Behavior parity reference: the v1.0.0 bash implementation at git tag `v1.0.0` (files `backup.sh`, `restore.sh`, `status.sh`, `query.sh`, `install.sh`, `uninstall.sh`, `lib/*.sh`) and the design spec `docs/superpowers/specs/2026-07-01-python-migration-design.md`.
- Work on a local branch `feat/python-migration`; `main` stays at v1.0.0 until cutover (final task).

---

### Task 1: Project scaffolding & toolchain

**Files:**
- Create: `pyproject.toml`, `src/turiya/__init__.py`, `src/turiya/py.typed`, `tests/__init__.py`, `tests/test_smoke.py`
- Create: `.gitignore` additions (`.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `dist/`)

**Interfaces:**
- Produces: an installable `turiya` package importable as `import turiya`; `uv run` toolchain for all later tasks.

- [ ] **Step 1: Create the branch**

```bash
cd /Users/amir/workspace/turiya
git checkout -b feat/python-migration
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "turiya"
version = "2.0.0"
description = "Automated encrypted multi-cloud backups via restic + rclone on macOS"
requires-python = ">=3.14"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
]

[project.scripts]
turiya = "turiya.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/turiya"]

[dependency-groups]
dev = ["pytest>=8", "mypy>=1.10", "ty>=0.0.1", "ruff>=0.5"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.14"
strict = true
files = ["src", "tests"]

[tool.ty]
# ty is configured here; defaults are fine for now

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

- [ ] **Step 3: Create package skeleton**

`src/turiya/__init__.py`:
```python
"""turiya: automated encrypted multi-cloud backups via restic + rclone."""

__version__ = "2.0.0"
```

`src/turiya/py.typed`: (empty file — PEP 561 marker)

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Write the smoke test**

`tests/test_smoke.py`:
```python
import turiya


def test_version() -> None:
    assert turiya.__version__ == "2.0.0"
```

- [ ] **Step 5: Sync and run the toolchain**

```bash
uv sync
uv run pytest tests/test_smoke.py
uv run ruff check .
uv run mypy src
uv run ty check
```
Expected: `pytest` passes (1 test); `ruff`, `mypy`, `ty` all report no errors. If `ty` is unavailable on PyPI at this version, note it in the report and continue with ruff+mypy (do not block).

- [ ] **Step 6: Update `.gitignore` and commit**

Append to `.gitignore`:
```
# Python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
```

```bash
git add pyproject.toml uv.lock src/turiya tests .gitignore
git commit -m "feat: scaffold turiya Python package with uv toolchain"
```

---

### Task 2: `errors.py` — exception hierarchy

**Files:**
- Create: `src/turiya/errors.py`, `tests/test_errors.py`

**Interfaces:**
- Produces: `TuriyaError` (base), `ConfigError`, `KeychainError`, `ResticError`, `RcloneError`, `SchedulingError` — all accept a message string; used by every later module.

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`:
```python
import pytest

from turiya.errors import (
    ConfigError,
    KeychainError,
    RcloneError,
    TuriyaError,
    ResticError,
    SchedulingError,
)


@pytest.mark.parametrize(
    "exc",
    [ConfigError, KeychainError, ResticError, RcloneError, SchedulingError],
)
def test_subclasses_of_base(exc: type[TuriyaError]) -> None:
    assert issubclass(exc, TuriyaError)
    instance = exc("boom")
    assert str(instance) == "boom"
    assert isinstance(instance, TuriyaError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py`
Expected: FAIL (ModuleNotFoundError: turiya.errors).

- [ ] **Step 3: Implement `errors.py`**

```python
"""Typed exception hierarchy for turiya."""


class TuriyaError(Exception):
    """Base class for all turiya errors."""


class ConfigError(TuriyaError):
    """Configuration is missing, unreadable, or invalid."""


class KeychainError(TuriyaError):
    """The restic password could not be retrieved from or stored in the Keychain."""


class ResticError(TuriyaError):
    """A restic invocation failed."""


class RcloneError(TuriyaError):
    """An rclone invocation failed or a remote is missing."""


class SchedulingError(TuriyaError):
    """launchd/pmset scheduling setup failed."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_errors.py && uv run mypy src && uv run ruff check .`
Expected: PASS; no type or lint errors.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/errors.py tests/test_errors.py
git commit -m "feat: add typed exception hierarchy"
```

---

### Task 3: `config.py` — TOML config models, loading, validation

**Files:**
- Create: `src/turiya/config.py`, `tests/test_config.py`, `tests/fixtures/valid_config.toml`

**Interfaces:**
- Consumes: `errors.ConfigError`.
- Produces:
  - Pydantic models: `Schedule(weekday: int | None, hour: int, minute: int)`, `Repo(url: str)`, `Retention(keep_daily/keep_weekly/keep_monthly/keep_yearly: int)`, `Keychain(account: str, service: str)`, `Identity(label: str)`, `Power(wake_offset_minutes: int)`, `LoggingConfig(dir: Path, max_bytes: int, json_per_file: bool)`, `Config(identity, keychain, schedules: list[Schedule], repos: list[Repo], sources: list[Path], excludes: list[str], retention, power, logging)`.
  - `DEFAULT_CONFIG_PATH: Path` = `~/.config/turiya/config.toml` (expanded).
  - `resolve_config_path(explicit: Path | None) -> Path` — explicit arg, else `$TURIYA_CONFIG`, else `DEFAULT_CONFIG_PATH`.
  - `load(path: Path | None = None) -> Config` — resolve, read via `tomllib`, validate; raise `ConfigError` with an actionable message on any failure.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/valid_config.toml`:
```toml
# Root-level keys (sources/excludes) must precede all [table]/[[array]] headers.
sources = ["~/Documents", "~/Desktop"]
excludes = [".DS_Store", "node_modules"]

[identity]
label = "com.example.turiya"

[keychain]
account = "restic"
service = "turiya"

[[schedule]]
weekday = 0
hour = 10
minute = 0

[power]
wake_offset_minutes = 5

[[repo]]
url = "rclone:gdrive:turiya-backups"

[[repo]]
url = "rclone:dropbox:turiya-backups"

[retention]
keep_daily = 7
keep_weekly = 4
keep_monthly = 6
keep_yearly = 1

[logging]
dir = "~/.local/log/turiya"
max_bytes = 5242880
json_per_file = true
```

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py`:
```python
from pathlib import Path

import pytest

from turiya import config
from turiya.errors import ConfigError

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_load_valid_config() -> None:
    cfg = config.load(FIXTURE)
    assert cfg.identity.label == "com.example.turiya"
    assert cfg.keychain.account == "restic"
    assert [r.url for r in cfg.repos] == [
        "rclone:gdrive:turiya-backups",
        "rclone:dropbox:turiya-backups",
    ]
    assert len(cfg.schedules) == 1
    assert cfg.schedules[0].hour == 10
    assert cfg.retention.keep_daily == 7
    assert cfg.logging.max_bytes == 5242880
    assert cfg.logging.json_per_file is True


def test_paths_are_expanded() -> None:
    cfg = config.load(FIXTURE)
    assert cfg.sources[0] == Path.home() / "Documents"
    assert cfg.logging.dir == Path.home() / ".local/log/turiya"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURIYA_CONFIG", str(FIXTURE))
    cfg = config.load()
    assert cfg.identity.label == "com.example.turiya"


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        config.load(tmp_path / "does-not-exist.toml")


def test_empty_repos_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[identity]\nlabel="x"\n[keychain]\naccount="a"\nservice="s"\n'
        '[[schedule]]\nhour=1\nminute=0\n[power]\nwake_offset_minutes=5\n'
        'sources=["~/x"]\nexcludes=[]\n'
        "[retention]\nkeep_daily=1\nkeep_weekly=1\nkeep_monthly=1\nkeep_yearly=1\n"
        '[logging]\ndir="~/l"\nmax_bytes=1\njson_per_file=true\n'
    )
    with pytest.raises(ConfigError, match="repo"):
        config.load(bad)


def test_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "broken.toml"
    bad.write_text("this is = = not valid toml")
    with pytest.raises(ConfigError):
        config.load(bad)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py`
Expected: FAIL (module/attribute not defined).

- [ ] **Step 4: Implement `config.py`**

```python
"""Load and validate the TOML runtime configuration."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ConfigError

DEFAULT_CONFIG_PATH = Path("~/.config/turiya/config.toml").expanduser()


def _expand(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


class Schedule(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


class Repo(BaseModel):
    url: str = Field(min_length=1)


class Retention(BaseModel):
    keep_daily: int = Field(ge=0)
    keep_weekly: int = Field(ge=0)
    keep_monthly: int = Field(ge=0)
    keep_yearly: int = Field(ge=0)


class Keychain(BaseModel):
    account: str = Field(min_length=1)
    service: str = Field(min_length=1)


class Identity(BaseModel):
    label: str = Field(min_length=1)


class Power(BaseModel):
    wake_offset_minutes: int = Field(default=5, ge=0)


class LoggingConfig(BaseModel):
    dir: Path
    max_bytes: int = Field(default=5242880, gt=0)
    json_per_file: bool = True

    @field_validator("dir", mode="before")
    @classmethod
    def _expand_dir(cls, v: str | Path) -> Path:
        return _expand(v)


class Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identity: Identity
    keychain: Keychain
    schedules: list[Schedule] = Field(alias="schedule", min_length=1)
    repos: list[Repo] = Field(alias="repo", min_length=1)
    sources: list[Path] = Field(min_length=1)
    excludes: list[str] = Field(default_factory=list)
    retention: Retention
    power: Power = Field(default_factory=Power)
    logging: LoggingConfig

    @field_validator("sources", mode="before")
    @classmethod
    def _expand_sources(cls, v: list[str]) -> list[Path]:
        return [_expand(s) for s in v]


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("TURIYA_CONFIG")
    if env:
        return Path(env)
    return DEFAULT_CONFIG_PATH


def load(path: Path | None = None) -> Config:
    resolved = resolve_config_path(path)
    if not resolved.is_file():
        raise ConfigError(f"Config file not found at {resolved}")
    try:
        with resolved.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config at {resolved} is not valid TOML: {exc}") from exc
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config at {resolved}:\n{exc}") from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean types and lint.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/config.py tests/test_config.py tests/fixtures/valid_config.toml
git commit -m "feat: add pydantic TOML config loading and validation"
```

---

### Task 4: `keychain.py` — macOS `security` wrapper

**Files:**
- Create: `src/turiya/keychain.py`, `tests/test_keychain.py`

**Interfaces:**
- Consumes: `config.Config`, `errors.KeychainError`.
- Produces:
  - `get_password(cfg: Config) -> str` — returns `$RESTIC_PASSWORD` if set, else runs `security find-generic-password -a <account> -s <service> -w`; raises `KeychainError` on failure.
  - `set_password(cfg: Config, password: str) -> None` — `security add-generic-password -a -s -w`.
  - `delete_password(cfg: Config) -> None` — `security delete-generic-password -a -s`; missing entry is not an error.

- [ ] **Step 1: Write the failing tests**

`tests/test_keychain.py`:
```python
import subprocess
from pathlib import Path

import pytest

from turiya import config, keychain
from turiya.errors import KeychainError

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def _cfg() -> config.Config:
    return config.load(FIXTURE)


def test_env_password_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTIC_PASSWORD", "from-env")

    def _boom(*a: object, **k: object) -> object:
        raise AssertionError("security must not be called when RESTIC_PASSWORD is set")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert keychain.get_password(_cfg()) == "from-env"


def test_get_password_from_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESTIC_PASSWORD", raising=False)
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="secret\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert keychain.get_password(_cfg()) == "secret"
    assert calls[0][0] == "security"
    assert "find-generic-password" in calls[0]


def test_get_password_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESTIC_PASSWORD", raising=False)

    def _fail(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(KeychainError, match="Keychain"):
        keychain.get_password(_cfg())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_keychain.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `keychain.py`**

```python
"""Retrieve and manage the restic repository password via the macOS Keychain."""

from __future__ import annotations

import os
import subprocess

from .config import Config
from .errors import KeychainError


def get_password(cfg: Config) -> str:
    env = os.environ.get("RESTIC_PASSWORD")
    if env:
        return env
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError(
            "Could not retrieve the restic password from the Keychain. "
            "Run `turiya setup`, or check keychain.account/keychain.service "
            f"in the config. (security exit {result.returncode})"
        )
    return result.stdout.strip()


def set_password(cfg: Config, password: str) -> None:
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
            "-w",
            password,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError(f"Failed to store password in the Keychain: {result.stderr.strip()}")


def delete_password(cfg: Config) -> None:
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
        ],
        capture_output=True,
        text=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_keychain.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/keychain.py tests/test_keychain.py
git commit -m "feat: add Keychain password wrapper with RESTIC_PASSWORD override"
```

---

### Task 5: `logging.py` — structured JSONL + human logging

**Files:**
- Create: `src/turiya/logging.py`, `tests/test_logging.py`

**Interfaces:**
- Consumes: `config.LoggingConfig`.
- Produces: `StructuredLogger` class:
  - `__init__(self, op: str, log_config: LoggingConfig)` — sets `self.human` (`<dir>/<op>.log`), `self.jsonl` (`<dir>/<op>.jsonl`), `self.combined` (`<dir>/ops.jsonl`); creates dir; rotates each of the three at `max_bytes`.
  - `emit_event(self, *, repo: str | None, level: str, event: str, **fields: object) -> None` — writes one JSON line `{ts, op, repo, level, event, **fields}` to `<op>.jsonl` and `ops.jsonl`.
  - `log_human(self, message: str) -> None` — appends `[YYYY-MM-DD HH:MM:SS] message` to `<op>.log` and prints it to stdout.
  - `run_start(self) -> None` / `run_end(self, *, success: bool) -> None` — convenience wrappers emitting `run_start` / `run_end` (level `info`/`error`, `status` `success`/`failure`).
  - Property `json_per_file: bool` (from config) so operations can decide whether to emit `file` events.

- [ ] **Step 1: Write the failing tests**

`tests/test_logging.py`:
```python
import json
from pathlib import Path

from turiya.config import LoggingConfig
from turiya.logging import StructuredLogger


def _logcfg(tmp_path: Path, max_bytes: int = 5_000_000) -> LoggingConfig:
    return LoggingConfig(dir=tmp_path, max_bytes=max_bytes, json_per_file=True)


def test_emit_event_writes_both_files(tmp_path: Path) -> None:
    log = StructuredLogger("backup", _logcfg(tmp_path))
    log.emit_event(repo="rclone:gdrive:x", level="info", event="file", action="new", path="/a", size=12)
    for name in ("backup.jsonl", "ops.jsonl"):
        line = (tmp_path / name).read_text().strip()
        obj = json.loads(line)
        assert obj["op"] == "backup"
        assert obj["repo"] == "rclone:gdrive:x"
        assert obj["event"] == "file"
        assert obj["action"] == "new"
        assert obj["size"] == 12
        assert "ts" in obj


def test_repo_none_serializes_as_null(tmp_path: Path) -> None:
    log = StructuredLogger("status", _logcfg(tmp_path))
    log.emit_event(repo=None, level="info", event="run_start")
    obj = json.loads((tmp_path / "status.jsonl").read_text().strip())
    assert obj["repo"] is None


def test_human_log_is_plaintext(tmp_path: Path) -> None:
    log = StructuredLogger("backup", _logcfg(tmp_path))
    log.log_human("hello world")
    content = (tmp_path / "backup.log").read_text().strip()
    assert content.endswith("hello world")
    assert content.startswith("[")


def test_rotation_when_over_max_bytes(tmp_path: Path) -> None:
    existing = tmp_path / "backup.jsonl"
    tmp_path.mkdir(exist_ok=True)
    existing.write_text("x" * 100)
    StructuredLogger("backup", _logcfg(tmp_path, max_bytes=50))
    backups = list(tmp_path.glob("backup.jsonl.*.bak"))
    assert len(backups) == 1
    assert not existing.exists()


def test_run_start_and_end(tmp_path: Path) -> None:
    log = StructuredLogger("query", _logcfg(tmp_path))
    log.run_start()
    log.run_end(success=False)
    lines = [json.loads(x) for x in (tmp_path / "query.jsonl").read_text().splitlines()]
    assert lines[0]["event"] == "run_start"
    assert lines[-1]["event"] == "run_end"
    assert lines[-1]["level"] == "error"
    assert lines[-1]["status"] == "failure"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_logging.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `logging.py`**

```python
"""Structured JSON Lines logging plus human-readable logs (byte-compatible with v1.0.0)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import LoggingConfig


class StructuredLogger:
    def __init__(self, op: str, log_config: LoggingConfig) -> None:
        self.op = op
        self.json_per_file = log_config.json_per_file
        self._max_bytes = log_config.max_bytes
        log_config.dir.mkdir(parents=True, exist_ok=True)
        self.human = log_config.dir / f"{op}.log"
        self.jsonl = log_config.dir / f"{op}.jsonl"
        self.combined = log_config.dir / "ops.jsonl"
        for path in (self.human, self.jsonl, self.combined):
            self._rotate(path)

    def _rotate(self, path: Path) -> None:
        if path.exists() and path.stat().st_size > self._max_bytes:
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            path.rename(path.with_name(f"{path.name}.{stamp}.bak"))

    def emit_event(self, *, repo: str | None, level: str, event: str, **fields: object) -> None:
        record: dict[str, object] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "op": self.op,
            "repo": repo,
            "level": level,
            "event": event,
        }
        record.update(fields)
        line = json.dumps(record) + "\n"
        with self.jsonl.open("a") as fh:
            fh.write(line)
        with self.combined.open("a") as fh:
            fh.write(line)

    def log_human(self, message: str) -> None:
        stamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        with self.human.open("a") as fh:
            fh.write(stamped + "\n")
        print(stamped)

    def run_start(self) -> None:
        self.emit_event(repo=None, level="info", event="run_start")

    def run_end(self, *, success: bool) -> None:
        self.emit_event(
            repo=None,
            level="info" if success else "error",
            event="run_end",
            status="success" if success else "failure",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_logging.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/logging.py tests/test_logging.py
git commit -m "feat: add structured JSONL and human logging (v1.0.0-compatible schema)"
```

---

### Task 6: `restic.py` — subprocess wrapper and event model

**Files:**
- Create: `src/turiya/restic.py`, `tests/test_restic.py`

**Interfaces:**
- Consumes: `errors.ResticError`.
- Produces:
  - Event dataclasses: `FileEvent(action: str, path: str, size: int)`, `SummaryEvent(data: dict[str, object])`, `ErrorEvent(message: str)`. Type alias `ResticEvent = FileEvent | SummaryEvent | ErrorEvent`.
  - `parse_event(line: str) -> ResticEvent | None` — parse one restic `--json` line; return `None` for lines that carry no event we track (e.g. `status` progress ticks, `scan_finished`, non-JSON noise).
  - `stream(repo: str, args: Sequence[str], *, password: str, dry_run: bool = False) -> Iterator[ResticEvent]` — run `restic -r <repo> <args> --json --verbose=2 [--dry-run]` with `RESTIC_PASSWORD` in env, merge stdout+stderr, yield parsed events. On non-zero exit with no `ErrorEvent` seen, yield a synthesic `ErrorEvent("restic exited with status N")`.
  - `run_json(repo: str, args: Sequence[str], *, password: str) -> object` — run `restic -r <repo> <args> --json`, capture output, return `json.loads(stdout)`; raise `ResticError` (with the real message parsed from stderr if present) on non-zero exit.

- [ ] **Step 1: Write the failing tests**

`tests/test_restic.py`:
```python
from turiya import restic
from turiya.restic import ErrorEvent, FileEvent, SummaryEvent


def test_parse_file_event() -> None:
    line = '{"message_type":"verbose_status","action":"new","item":"/a.txt","data_size":12}'
    ev = restic.parse_event(line)
    assert isinstance(ev, FileEvent)
    assert ev.action == "new"
    assert ev.path == "/a.txt"
    assert ev.size == 12


def test_parse_skips_scan_finished() -> None:
    line = '{"message_type":"verbose_status","action":"scan_finished","item":"","data_size":0}'
    assert restic.parse_event(line) is None


def test_parse_skips_status_tick() -> None:
    line = '{"message_type":"status","percent_done":0.5}'
    assert restic.parse_event(line) is None


def test_parse_summary_event() -> None:
    line = '{"message_type":"summary","files_new":2,"snapshot_id":"abc"}'
    ev = restic.parse_event(line)
    assert isinstance(ev, SummaryEvent)
    assert ev.data["files_new"] == 2
    assert ev.data["snapshot_id"] == "abc"


def test_parse_exit_error_event() -> None:
    line = '{"message_type":"exit_error","code":10,"message":"Fatal: repo does not exist"}'
    ev = restic.parse_event(line)
    assert isinstance(ev, ErrorEvent)
    assert "repo does not exist" in ev.message


def test_parse_non_json_returns_none() -> None:
    assert restic.parse_event("Fatal: something plain") is None


def test_parse_restore_event_uses_size_key() -> None:
    line = '{"message_type":"verbose_status","action":"restored","item":"/b","size":7}'
    ev = restic.parse_event(line)
    assert isinstance(ev, FileEvent)
    assert ev.size == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_restic.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `restic.py`**

```python
"""Run restic via subprocess and parse its --json output into typed events."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from .errors import ResticError


@dataclass
class FileEvent:
    action: str
    path: str
    size: int


@dataclass
class SummaryEvent:
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class ErrorEvent:
    message: str


ResticEvent = FileEvent | SummaryEvent | ErrorEvent


def parse_event(line: str) -> ResticEvent | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    mtype = obj.get("message_type")
    if mtype == "verbose_status":
        action = str(obj.get("action", "unknown"))
        if action == "scan_finished":
            return None
        size_raw = obj.get("data_size", obj.get("size", 0))
        size = int(size_raw) if isinstance(size_raw, int | float) else 0
        return FileEvent(action=action, path=str(obj.get("item", "")), size=size)
    if mtype == "summary":
        return SummaryEvent(data=obj)
    if mtype in ("error", "exit_error"):
        message = obj.get("message")
        if not isinstance(message, str):
            err = obj.get("error")
            message = err.get("message") if isinstance(err, dict) else "unknown restic error"
        return ErrorEvent(message=str(message))
    return None


def _env(password: str) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = password
    return env


def stream(
    repo: str,
    args: Sequence[str],
    *,
    password: str,
    dry_run: bool = False,
) -> Iterator[ResticEvent]:
    cmd = ["restic", "-r", repo, *args, "--json", "--verbose=2"]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_env(password),
    )
    saw_error = False
    assert proc.stdout is not None
    for line in proc.stdout:
        event = parse_event(line)
        if event is None:
            continue
        if isinstance(event, ErrorEvent):
            saw_error = True
        yield event
    code = proc.wait()
    if code != 0 and not saw_error:
        yield ErrorEvent(message=f"restic exited with status {code}")


def run_json(repo: str, args: Sequence[str], *, password: str) -> object:
    cmd = ["restic", "-r", repo, *args, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env(password))
    if result.returncode != 0:
        message = f"restic exited with status {result.returncode}"
        for line in (result.stderr + result.stdout).splitlines():
            event = parse_event(line)
            if isinstance(event, ErrorEvent):
                message = event.message
                break
        raise ResticError(message)
    return json.loads(result.stdout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_restic.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/restic.py tests/test_restic.py
git commit -m "feat: add restic subprocess wrapper and typed event parsing"
```

---

### Task 7: `rclone.py` — remote verification

**Files:**
- Create: `src/turiya/rclone.py`, `tests/test_rclone.py`

**Interfaces:**
- Consumes: `config.Config`, `errors.RcloneError`.
- Produces:
  - `list_remotes() -> list[str]` — runs `rclone listremotes`, returns remote names without the trailing `:`; raises `RcloneError` on failure.
  - `remote_of(repo_url: str) -> str | None` — extract `<remote>` from `rclone:<remote>:<path>`; return `None` if the url is not an rclone url.
  - `missing_remotes(cfg: Config) -> list[str]` — remotes referenced by config repos that are not in `list_remotes()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_rclone.py`:
```python
import subprocess
from pathlib import Path

import pytest

from turiya import config, rclone

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_remote_of_extracts_name() -> None:
    assert rclone.remote_of("rclone:gdrive:turiya-backups") == "gdrive"
    assert rclone.remote_of("/local/path") is None


def test_list_remotes_parses_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="gdrive:\ndropbox:\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    assert rclone.list_remotes() == ["gdrive", "dropbox"]


def test_missing_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="gdrive:\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    assert rclone.missing_remotes(config.load(FIXTURE)) == ["dropbox"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rclone.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `rclone.py`**

```python
"""Verify that the rclone remotes referenced by the config exist."""

from __future__ import annotations

import subprocess

from .config import Config
from .errors import RcloneError


def list_remotes() -> list[str]:
    result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RcloneError(f"`rclone listremotes` failed: {result.stderr.strip()}")
    return [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]


def remote_of(repo_url: str) -> str | None:
    if not repo_url.startswith("rclone:"):
        return None
    rest = repo_url[len("rclone:") :]
    name, _, _ = rest.partition(":")
    return name or None


def missing_remotes(cfg: Config) -> list[str]:
    available = set(list_remotes())
    missing: list[str] = []
    for repo in cfg.repos:
        name = remote_of(repo.url)
        if name is not None and name not in available and name not in missing:
            missing.append(name)
    return missing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rclone.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/rclone.py tests/test_rclone.py
git commit -m "feat: add rclone remote verification"
```

---

### Task 8: `scheduling.py` — launchd plist rendering + pmset (items 2 + 11)

**Files:**
- Create: `src/turiya/scheduling.py`, `src/turiya/templates/launchd.plist.tmpl`, `tests/test_scheduling.py`

**Interfaces:**
- Consumes: `config.Config`, `config.Schedule`, `errors.SchedulingError`.
- Produces:
  - `plist_label(cfg: Config, index: int) -> str` — `cfg.identity.label` for index 0, else `f"{label}.{index}"` (unique label per schedule).
  - `render_plist(cfg: Config, schedule: Schedule, *, label: str, program: list[str]) -> str` — render the launchd plist XML from the template, filling label, program args, and `StartCalendarInterval` (Weekday only if `schedule.weekday is not None`; always Hour+Minute), plus stdout/stderr log paths under `cfg.logging.dir`.
  - `earliest_wake_time(cfg: Config) -> tuple[int, int]` — `(hour, minute)` of the earliest schedule minus `cfg.power.wake_offset_minutes` (wrap across the hour boundary; clamp at 0).
  - `install(cfg: Config, *, program: list[str]) -> None` and `uninstall(cfg: Config) -> None` — write plist(s) to `~/Library/LaunchAgents/<label>.plist`, `launchctl load/unload`, and set/cancel the pmset wake. Raise `SchedulingError` on failure. (These shell out; unit-test the pure functions above, exercise install/uninstall only in the integration/setup task where they can be mocked.)

- [ ] **Step 1: Write the template**

`src/turiya/templates/launchd.plist.tmpl`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
$program_args
    </array>
    <key>StartCalendarInterval</key>
    <dict>
$calendar
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$stdout_path</string>
    <key>StandardErrorPath</key>
    <string>$stderr_path</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_scheduling.py`:
```python
from pathlib import Path

from turiya import config, scheduling
from turiya.config import Schedule

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_plist_label_uniqueness() -> None:
    cfg = config.load(FIXTURE)
    assert scheduling.plist_label(cfg, 0) == "com.example.turiya"
    assert scheduling.plist_label(cfg, 1) == "com.example.turiya.1"


def test_render_plist_includes_label_and_schedule() -> None:
    cfg = config.load(FIXTURE)
    xml = scheduling.render_plist(
        cfg,
        Schedule(weekday=0, hour=10, minute=0),
        label="com.example.turiya",
        program=["/opt/venv/bin/turiya", "backup"],
    )
    assert "<string>com.example.turiya</string>" in xml
    assert "<key>Weekday</key>" in xml
    assert "<integer>10</integer>" in xml  # hour
    assert "/opt/venv/bin/turiya" in xml


def test_render_plist_omits_weekday_when_none() -> None:
    cfg = config.load(FIXTURE)
    xml = scheduling.render_plist(
        cfg,
        Schedule(weekday=None, hour=3, minute=30),
        label="x",
        program=["turiya", "backup"],
    )
    assert "<key>Weekday</key>" not in xml
    assert "<key>Hour</key>" in xml


def test_earliest_wake_time_subtracts_offset() -> None:
    cfg = config.load(FIXTURE)  # single schedule 10:00, offset 5
    assert scheduling.earliest_wake_time(cfg) == (9, 55)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduling.py`
Expected: FAIL (module not defined).

- [ ] **Step 4: Implement `scheduling.py`**

```python
"""Render and install launchd schedules and the pmset wake (items 2 + 11)."""

from __future__ import annotations

import subprocess
from importlib.resources import files
from pathlib import Path
from string import Template

from .config import Config, Schedule
from .errors import SchedulingError

_TEMPLATE = Template(
    (files("turiya") / "templates" / "launchd.plist.tmpl").read_text(encoding="utf-8")
)


def plist_label(cfg: Config, index: int) -> str:
    return cfg.identity.label if index == 0 else f"{cfg.identity.label}.{index}"


def render_plist(cfg: Config, schedule: Schedule, *, label: str, program: list[str]) -> str:
    program_args = "\n".join(f"        <string>{arg}</string>" for arg in program)
    cal_lines = []
    if schedule.weekday is not None:
        cal_lines.append(f"        <key>Weekday</key>\n        <integer>{schedule.weekday}</integer>")
    cal_lines.append(f"        <key>Hour</key>\n        <integer>{schedule.hour}</integer>")
    cal_lines.append(f"        <key>Minute</key>\n        <integer>{schedule.minute}</integer>")
    return _TEMPLATE.substitute(
        label=label,
        program_args=program_args,
        calendar="\n".join(cal_lines),
        stdout_path=str(cfg.logging.dir / "launchd.log"),
        stderr_path=str(cfg.logging.dir / "launchd-err.log"),
    )


def earliest_wake_time(cfg: Config) -> tuple[int, int]:
    earliest = min(cfg.schedules, key=lambda s: (s.hour, s.minute))
    total = earliest.hour * 60 + earliest.minute - cfg.power.wake_offset_minutes
    if total < 0:
        total = 0
    return total // 60, total % 60


def install(cfg: Config, *, program: list[str]) -> None:
    agents = Path("~/Library/LaunchAgents").expanduser()
    agents.mkdir(parents=True, exist_ok=True)
    for index, schedule in enumerate(cfg.schedules):
        label = plist_label(cfg, index)
        dest = agents / f"{label}.plist"
        dest.write_text(render_plist(cfg, schedule, label=label, program=program))
        subprocess.run(["launchctl", "unload", str(dest)], capture_output=True, text=True)
        result = subprocess.run(["launchctl", "load", str(dest)], capture_output=True, text=True)
        if result.returncode != 0:
            raise SchedulingError(f"launchctl load failed for {label}: {result.stderr.strip()}")
    hour, minute = earliest_wake_time(cfg)
    subprocess.run(
        ["sudo", "pmset", "repeat", "wakeorpoweron", "MTWRFSU", f"{hour:02d}:{minute:02d}:00"],
        check=False,
    )


def uninstall(cfg: Config) -> None:
    agents = Path("~/Library/LaunchAgents").expanduser()
    for index in range(len(cfg.schedules)):
        label = plist_label(cfg, index)
        dest = agents / f"{label}.plist"
        if dest.exists():
            subprocess.run(["launchctl", "unload", str(dest)], capture_output=True, text=True)
            dest.unlink()
    subprocess.run(["sudo", "pmset", "repeat", "cancel"], check=False)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduling.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 6: Commit**

```bash
git add src/turiya/scheduling.py src/turiya/templates/launchd.plist.tmpl tests/test_scheduling.py
git commit -m "feat: add launchd plist rendering and pmset scheduling (items 2 + 11)"
```

---

### Task 9: Integration test harness (fixtures over real restic repos)

**Files:**
- Create: `tests/conftest.py`, `tests/integration/__init__.py`, `tests/integration/test_harness_smoke.py`

**Interfaces:**
- Produces pytest fixtures used by all operation integration tests:
  - `restic_repos(tmp_path) -> list[Path]` — creates and `restic init`s two local repos under `tmp_path`, with `RESTIC_PASSWORD=testpass123` set for the session.
  - `source_tree(tmp_path) -> Path` — a fixture directory with `docs/report.txt` and `notes/todo.md`.
  - `harness_config(tmp_path, restic_repos, source_tree) -> Path` — writes a `config.toml` pointing at the two local repos + the source tree + a log dir under tmp; sets `TURIYA_CONFIG` to it. Returns the config path.

- [ ] **Step 1: Write `conftest.py`**

```python
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

PASSWORD = "testpass123"


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    (root / "docs").mkdir(parents=True)
    (root / "notes").mkdir(parents=True)
    (root / "docs" / "report.txt").write_text("quarterly report\n")
    (root / "notes" / "todo.md").write_text("- buy milk\n")
    return root


@pytest.fixture
def restic_repos(tmp_path: Path) -> list[Path]:
    repos = [tmp_path / "repo-a", tmp_path / "repo-b"]
    env = {**os.environ, "RESTIC_PASSWORD": PASSWORD}
    for repo in repos:
        subprocess.run(["restic", "-r", str(repo), "init"], check=True, capture_output=True, env=env)
    return repos


@pytest.fixture
def harness_config(
    tmp_path: Path,
    restic_repos: list[Path],
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    cfg = tmp_path / "config.toml"
    # NOTE: root-level keys (sources/excludes) MUST come before any [table] or
    # [[array]] header, or TOML absorbs them into the preceding table.
    cfg.write_text(
        f'sources = ["{source_tree}"]\nexcludes = ["*.tmp"]\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(cfg))
    monkeypatch.setenv("RESTIC_PASSWORD", PASSWORD)
    yield cfg
```

- [ ] **Step 2: Write a harness smoke test**

`tests/integration/test_harness_smoke.py`:
```python
from pathlib import Path

from turiya import config, restic


def test_harness_repos_are_empty(harness_config: Path) -> None:
    cfg = config.load()
    for repo in cfg.repos:
        snaps = restic.run_json(repo.url, ["snapshots"], password="testpass123")
        assert snaps == []
```

`tests/integration/__init__.py`: (empty file)

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/integration/test_harness_smoke.py`
Expected: PASS (repos initialize empty). Requires `restic` on PATH.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/integration
git commit -m "test: add integration harness fixtures over real local restic repos"
```

---

### Task 10: `operations/backup.py`

**Files:**
- Create: `src/turiya/operations/__init__.py`, `src/turiya/operations/backup.py`, `tests/integration/test_backup.py`

**Interfaces:**
- Consumes: `config.Config`, `keychain.get_password`, `restic.stream`, `restic.run_json`, `logging.StructuredLogger`.
- Produces:
  - `resolve_targets(cfg, *, include, pattern, glob) -> list[str]` — if any of include/pattern/glob given, union their resolutions (include = literal existing paths; pattern = `find <source> -path "*P*"`; glob = `find <source> -name "G"`), raising `ResticError`-free `ValueError`/`ConfigError` on a no-match or missing include; else return `cfg.sources` as strings. (Mirror v1.0.0 `backup.sh` semantics exactly, including error-on-no-match.)
  - `run(cfg, *, dry_run=False, include=(), pattern=(), glob=(), exclude=()) -> bool` — returns overall success. For each repo: `restic.stream(repo, ["backup", *targets, *exclude_flags], ...)`, log each `FileEvent` (respecting `json_per_file`) and `SummaryEvent`; run `forget --prune` per retention on success (non-dry-run) via `run_json` and emit a `prune` event; emit `run_start`/`run_end`. Empty `repos`/`sources` are already prevented by config validation.

- [ ] **Step 1: Write the integration tests**

`tests/integration/test_backup.py`:
```python
import json
from pathlib import Path

from turiya import config, restic
from turiya.operations import backup


def test_plain_backup_creates_snapshot(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123")
    assert isinstance(snaps, list) and len(snaps) == 1


def test_glob_restricts_targets(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123")
    paths = snaps[-1]["paths"]  # type: ignore[index]
    assert any(p.endswith("todo.md") for p in paths)


def test_glob_no_match_returns_false(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("*.nonexistent-xyz",)) is False


def test_backup_emits_valid_jsonl(harness_config: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    for line in (cfg.logging.dir / "backup.jsonl").read_text().splitlines():
        json.loads(line)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_backup.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `operations/backup.py`**

`src/turiya/operations/__init__.py`: (empty file)

```python
"""Backup operation: port of v1.0.0 backup.sh."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from ..config import Config
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import ErrorEvent, FileEvent, SummaryEvent, run_json, stream


def _find(source: str, flag: str, value: str) -> list[str]:
    result = subprocess.run(
        ["find", source, flag, value], capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line]


def resolve_targets(
    cfg: Config,
    *,
    include: Sequence[str],
    pattern: Sequence[str],
    glob: Sequence[str],
) -> list[str] | None:
    """Return target paths, or None if a pattern/glob/include matched nothing."""
    if not (include or pattern or glob):
        return [str(s) for s in cfg.sources]
    targets: list[str] = []
    for path in include:
        from pathlib import Path

        if not Path(path).exists():
            return None
        targets.append(path)
    for pat in pattern:
        matches = [m for s in cfg.sources for m in _find(str(s), "-path", f"*{pat}*")]
        if not matches:
            return None
        targets.extend(matches)
    for g in glob:
        matches = [m for s in cfg.sources for m in _find(str(s), "-name", g)]
        if not matches:
            return None
        targets.extend(matches)
    return targets


def run(
    cfg: Config,
    *,
    dry_run: bool = False,
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("backup", cfg.logging)
    log.run_start()
    password = get_password(cfg)

    targets = resolve_targets(cfg, include=include, pattern=pattern, glob=glob)
    if targets is None:
        log.log_human("ERROR: include/pattern/glob matched no files.")
        log.run_end(success=False)
        return False

    exclude_flags = [f"--exclude={p}" for p in (*cfg.excludes, *exclude)]
    retention = [
        "--keep-daily", str(cfg.retention.keep_daily),
        "--keep-weekly", str(cfg.retention.keep_weekly),
        "--keep-monthly", str(cfg.retention.keep_monthly),
        "--keep-yearly", str(cfg.retention.keep_yearly),
    ]

    overall = True
    for repo in cfg.repos:
        url = repo.url
        log.log_human(f"--- Repository: {url} ---")
        repo_ok = True
        for event in stream(url, ["backup", *targets, *exclude_flags], password=password, dry_run=dry_run):
            if isinstance(event, FileEvent):
                if log.json_per_file:
                    log.emit_event(repo=url, level="info", event="file",
                                   action=event.action, path=event.path, size=event.size)
                log.log_human(f"{event.action} {event.path}")
            elif isinstance(event, SummaryEvent):
                log.emit_event(repo=url, level="info", event="summary", **event.data)
            elif isinstance(event, ErrorEvent):
                repo_ok = False
                log.emit_event(repo=url, level="error", event="error", message=event.message)
                log.log_human(f"ERROR: {event.message}")
        if repo_ok and not dry_run:
            try:
                run_json(url, ["forget", *retention, "--prune"], password=password)
                log.emit_event(repo=url, level="info", event="prune")
            except Exception as exc:  # noqa: BLE001
                log.emit_event(repo=url, level="warn", event="prune", message=str(exc))
        overall = overall and repo_ok

    log.run_end(success=overall)
    return overall
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_backup.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/operations tests/integration/test_backup.py
git commit -m "feat: add backup operation (port of backup.sh)"
```

---

### Task 11: `operations/restore.py`

**Files:**
- Create: `src/turiya/operations/restore.py`, `tests/integration/test_restore.py`

**Interfaces:**
- Consumes: `config.Config`, `keychain.get_password`, `restic.stream`, `logging.StructuredLogger`.
- Produces: `resolve_repo(cfg, repo_filter: str | None) -> str` (substring match against `cfg.repos[].url`; first repo if filter is `None`; raise `ConfigError` if a non-empty filter matches nothing). `run(cfg, *, repo=None, snapshot="latest", target, include=(), pattern=(), glob=(), exclude=()) -> bool` — restic `restore <snapshot> --target <target>` with all of include/pattern/glob mapped to repeated `--include` and exclude to repeated `--exclude`; stream + log events; `run_start`/`run_end`.

- [ ] **Step 1: Write the integration tests**

`tests/integration/test_restore.py`:
```python
from pathlib import Path

from turiya import config
from turiya.operations import backup, restore


def test_full_restore(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    out = tmp_path / "restore-out"
    assert restore.run(cfg, target=str(out)) is True
    files = list(out.rglob("*.txt")) + list(out.rglob("*.md"))
    assert any(f.name == "report.txt" for f in files)
    assert any(f.name == "todo.md" for f in files)


def test_glob_restore_one_file(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    out = tmp_path / "restore-glob"
    assert restore.run(cfg, target=str(out), glob=("todo.md",)) is True
    names = {f.name for f in out.rglob("*") if f.is_file()}
    assert "todo.md" in names
    assert "report.txt" not in names


def test_restore_bad_snapshot_returns_false(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    assert restore.run(cfg, snapshot="nonexistent", target=str(tmp_path / "x")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_restore.py`
Expected: FAIL.

- [ ] **Step 3: Implement `operations/restore.py`**

```python
"""Restore operation: port of v1.0.0 restore.sh."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..config import Config
from ..errors import ConfigError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import ErrorEvent, FileEvent, SummaryEvent, stream


def resolve_repo(cfg: Config, repo_filter: str | None) -> str:
    if repo_filter:
        for repo in cfg.repos:
            if repo_filter in repo.url:
                return repo.url
        raise ConfigError(f"No repo matching '{repo_filter}' in config.")
    return cfg.repos[0].url


def run(
    cfg: Config,
    *,
    repo: str | None = None,
    snapshot: str = "latest",
    target: str,
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("restore", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    url = resolve_repo(cfg, repo)
    Path(target).mkdir(parents=True, exist_ok=True)

    args = ["restore", snapshot, "--target", target]
    for pat in (*include, *pattern, *glob):
        args += ["--include", pat]
    for pat in exclude:
        args += ["--exclude", pat]

    ok = True
    for event in stream(url, args, password=password):
        if isinstance(event, FileEvent):
            if log.json_per_file:
                log.emit_event(repo=url, level="info", event="file",
                               action=event.action, path=event.path, size=event.size)
            log.log_human(f"{event.action} {event.path}")
        elif isinstance(event, SummaryEvent):
            log.emit_event(repo=url, level="info", event="summary", **event.data)
        elif isinstance(event, ErrorEvent):
            ok = False
            log.emit_event(repo=url, level="error", event="error", message=event.message)
            log.log_human(f"ERROR: {event.message}")

    log.run_end(success=ok)
    return ok
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_restore.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/operations/restore.py tests/integration/test_restore.py
git commit -m "feat: add restore operation (port of restore.sh)"
```

---

### Task 12: `operations/status.py`

**Files:**
- Create: `src/turiya/operations/status.py`, `tests/integration/test_status.py`

**Interfaces:**
- Consumes: `config.Config`, `keychain.get_password`, `restic.run_json`, `logging.StructuredLogger`.
- Produces:
  - `snapshot_matches(paths: list[str], *, pattern, glob, exclude) -> bool` — client-side filter: keep if (no pattern/glob given) OR any path substring-matches a pattern OR any path basename fnmatch-matches a glob; drop if any path substring/basename matches an exclude. (Mirror v1.0.0 `status.sh`.)
  - `run(cfg, *, mode="latest", include=(), pattern=(), glob=(), exclude=()) -> bool` — for each repo: `restic snapshots --json [--latest 1] [--path P...]` via `run_json`; apply client-side `snapshot_matches`; print + emit a `summary` event per kept snapshot. `mode="check"` runs `restic check` per repo. On a repo failure emit `error` + continue; `run_end` reflects overall.

- [ ] **Step 1: Write the integration tests**

`tests/integration/test_status.py`:
```python
from pathlib import Path

from turiya import config
from turiya.operations import backup, status


def test_status_all_lists_snapshots(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert status.run(cfg, mode="all") is True
    out = capsys.readouterr().out
    assert out.strip() != ""


def test_snapshot_matches_filters() -> None:
    paths = ["/Users/x/src/notes"]
    assert status.snapshot_matches(paths, pattern=("notes",), glob=(), exclude=()) is True
    assert status.snapshot_matches(paths, pattern=("photos",), glob=(), exclude=()) is False
    assert status.snapshot_matches(paths, pattern=(), glob=(), exclude=("notes",)) is False
    assert status.snapshot_matches(paths, pattern=(), glob=("notes",), exclude=()) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_status.py`
Expected: FAIL.

- [ ] **Step 3: Implement `operations/status.py`**

```python
"""Status operation: port of v1.0.0 status.sh."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import PurePath
from typing import Any, cast

from ..config import Config
from ..errors import ResticError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import run_json


def snapshot_matches(
    paths: list[str],
    *,
    pattern: Sequence[str],
    glob: Sequence[str],
    exclude: Sequence[str],
) -> bool:
    if pattern or glob:
        keep = False
        for p in paths:
            if any(pat in p for pat in pattern):
                keep = True
            if any(fnmatch.fnmatch(PurePath(p).name, g) for g in glob):
                keep = True
        if not keep:
            return False
    for p in paths:
        if any(ex in p for ex in exclude) or any(fnmatch.fnmatch(PurePath(p).name, ex) for ex in exclude):
            return False
    return True


def run(
    cfg: Config,
    *,
    mode: str = "latest",
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("status", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    overall = True

    for repo in cfg.repos:
        url = repo.url
        print(f"\n=== {url} ===")
        if mode == "check":
            try:
                run_json(url, ["check"], password=password)
                log.emit_event(repo=url, level="info", event="summary", check="ok")
            except ResticError as exc:
                overall = False
                log.emit_event(repo=url, level="error", event="error", message=str(exc))
            continue

        args = ["snapshots"]
        for path in include:
            args += ["--path", path]
        if mode == "latest":
            args += ["--latest", "1"]
        try:
            snaps = cast(list[dict[str, Any]], run_json(url, args, password=password))
        except ResticError as exc:
            overall = False
            log.emit_event(repo=url, level="error", event="error", message=str(exc))
            continue

        for snap in snaps:
            paths = [str(p) for p in snap.get("paths", [])]
            if not snapshot_matches(paths, pattern=pattern, glob=glob, exclude=exclude):
                continue
            short = str(snap.get("short_id", ""))
            when = str(snap.get("time", ""))
            print(f"  {short}  {when}  {', '.join(paths)}")
            log.emit_event(repo=url, level="info", event="summary", snapshot_id=short, time=when)

    log.run_end(success=overall)
    return overall
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_status.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/operations/status.py tests/integration/test_status.py
git commit -m "feat: add status operation (port of status.sh)"
```

---

### Task 13: `operations/query.py`

**Files:**
- Create: `src/turiya/operations/query.py`, `tests/integration/test_query.py`

**Interfaces:**
- Consumes: `config.Config`, `keychain.get_password`, `restic.run_json`, `logging.StructuredLogger`, `restore.resolve_repo`.
- Produces: `run(cfg, *, repo=None, since=None, until=None, find=None, versions=None, json_output=False) -> bool` — exactly one of {since/until group, find, versions} must be set (raise `ConfigError` otherwise). Modes mirror v1.0.0 `query.sh`: date-range filters `snapshots --json` by `.time`; find/versions use `find --json [--reverse]`; per-repo restic failure emits `error` and continues (does not abort); `run_end` reflects overall success. When `json_output`, print raw JSON per repo instead of a table.

- [ ] **Step 1: Write the integration tests**

`tests/integration/test_query.py`:
```python
from pathlib import Path

import pytest

from turiya import config
from turiya.errors import ConfigError
from turiya.operations import backup, query


def test_find_locates_file(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, find="todo.md") is True
    assert "todo.md" in capsys.readouterr().out


def test_since_past_lists(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, since="2020-01-01") is True
    assert capsys.readouterr().out.strip() != ""


def test_mutual_exclusivity(harness_config: Path) -> None:
    cfg = config.load()
    with pytest.raises(ConfigError):
        query.run(cfg, find="x", since="2020-01-01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_query.py`
Expected: FAIL.

- [ ] **Step 3: Implement `operations/query.py`**

```python
"""Query operation: port of v1.0.0 query.sh."""

from __future__ import annotations

import json
from typing import Any, cast

from ..config import Config
from ..errors import ConfigError, ResticError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import run_json
from .restore import resolve_repo


def run(
    cfg: Config,
    *,
    repo: str | None = None,
    since: str | None = None,
    until: str | None = None,
    find: str | None = None,
    versions: str | None = None,
    json_output: bool = False,
) -> bool:
    modes = [bool(since or until), bool(find), bool(versions)]
    if sum(modes) != 1:
        raise ConfigError("Specify exactly one of --since/--until, --find, or --versions.")

    log = StructuredLogger("query", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    repos = [resolve_repo(cfg, repo)] if repo else [r.url for r in cfg.repos]

    overall = True
    for url in repos:
        try:
            if since or until:
                snaps = cast(list[dict[str, Any]], run_json(url, ["snapshots"], password=password))
                rows = [
                    s for s in snaps
                    if (not since or str(s.get("time", "")) >= since)
                    and (not until or str(s.get("time", "")) <= until)
                ]
                log.emit_event(repo=url, level="info", event="summary", mode="date_range", match_count=len(rows))
                _print_snaps(url, rows, json_output)
            else:
                target = find or versions
                args = ["find", cast(str, target)]
                if versions:
                    args.append("--reverse")
                result = cast(list[dict[str, Any]], run_json(url, args, password=password))
                matches = [m for entry in result for m in entry.get("matches", [])]
                mode = "find" if find else "versions"
                log.emit_event(repo=url, level="info", event="summary", mode=mode, match_count=len(matches))
                _print_finds(url, result, json_output)
        except ResticError as exc:
            overall = False
            log.emit_event(repo=url, level="error", event="error", message=str(exc))
            print(f"ERROR: query on {url} failed: {exc}")

    log.run_end(success=overall)
    return overall


def _print_snaps(url: str, rows: list[dict[str, Any]], json_output: bool) -> None:
    if json_output:
        print(json.dumps(rows))
        return
    if rows:
        print(f"\n--- {url} ---")
        for s in rows:
            paths = ", ".join(str(p) for p in s.get("paths", []))
            print(f"  {s.get('short_id', '')}  {s.get('time', '')}  {paths}")


def _print_finds(url: str, result: list[dict[str, Any]], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result))
        return
    for entry in result:
        snap = entry.get("snapshot", "")
        for m in entry.get("matches", []):
            print(f"  {snap}  {m.get('path', '')}  {m.get('size', 0)} bytes  {m.get('mtime', '')}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_query.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/operations/query.py tests/integration/test_query.py
git commit -m "feat: add query operation (port of query.sh)"
```

---

### Task 14: `operations/setup.py` — setup/teardown wiring

**Files:**
- Create: `src/turiya/operations/setup.py`, `tests/test_setup.py`

**Interfaces:**
- Consumes: `config.Config`, `keychain`, `rclone`, `restic.run_json`, `scheduling`, `logging.StructuredLogger`.
- Produces:
  - `default_program() -> list[str]` — the argv launchd should invoke: `[sys.executable, "-m", "turiya", "backup"]` (module entry, robust regardless of console-script path).
  - `run(cfg: Config, *, password: str | None = None, program: list[str] | None = None) -> None` — store password (if given) via `keychain.set_password`; verify `rclone.missing_remotes` is empty (raise `RcloneError` listing missing); `restic init` any uninitialized repo (via `run_json(..., ["snapshots"])` probe, then `restic -r url init` on failure); `scheduling.install`. 
  - `teardown(cfg: Config) -> None` — `scheduling.uninstall`; leave Keychain + cloud repos intact (matching v1.0.0 uninstall's safe default).
- Unit-test the pure `default_program` and the repo-init decision logic with `restic`/`scheduling` calls monkeypatched; do not perform real launchd/pmset changes in tests.

- [ ] **Step 1: Write the tests**

`tests/test_setup.py`:
```python
import sys
from pathlib import Path

from turiya import config
from turiya.operations import setup

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_default_program_uses_module_entry() -> None:
    prog = setup.default_program()
    assert prog[0] == sys.executable
    assert prog[1:3] == ["-m", "turiya"]
    assert prog[-1] == "backup"


def test_setup_raises_on_missing_remotes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load(FIXTURE)
    monkeypatch.setattr("turiya.operations.setup.rclone.missing_remotes", lambda c: ["dropbox"])
    import pytest

    from turiya.errors import RcloneError

    with pytest.raises(RcloneError, match="dropbox"):
        setup.run(cfg, program=["x"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py`
Expected: FAIL.

- [ ] **Step 3: Implement `operations/setup.py`**

```python
"""Setup/teardown wiring: port of v1.0.0 install.sh / uninstall.sh."""

from __future__ import annotations

import subprocess
import sys

from .. import keychain, rclone, scheduling
from ..config import Config
from ..errors import RcloneError, ResticError
from ..restic import run_json


def default_program() -> list[str]:
    return [sys.executable, "-m", "turiya", "backup"]


def _repo_initialized(url: str, password: str) -> bool:
    try:
        run_json(url, ["snapshots"], password=password)
        return True
    except ResticError:
        return False


def run(cfg: Config, *, password: str | None = None, program: list[str] | None = None) -> None:
    if password is not None:
        keychain.set_password(cfg, password)
    resolved_password = keychain.get_password(cfg)

    missing = rclone.missing_remotes(cfg)
    if missing:
        raise RcloneError(f"rclone remotes not configured: {', '.join(missing)}. Run `rclone config`.")

    import os

    env = {**os.environ, "RESTIC_PASSWORD": resolved_password}
    for repo in cfg.repos:
        if not _repo_initialized(repo.url, resolved_password):
            result = subprocess.run(
                ["restic", "-r", repo.url, "init"], capture_output=True, text=True, env=env
            )
            if result.returncode != 0:
                raise ResticError(f"Failed to init repo {repo.url}: {result.stderr.strip()}")

    scheduling.install(cfg, program=program or default_program())


def teardown(cfg: Config) -> None:
    scheduling.uninstall(cfg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/operations/setup.py tests/test_setup.py
git commit -m "feat: add setup/teardown wiring (port of install.sh/uninstall.sh)"
```

---

### Task 15: `cli.py` — Typer application (+ `__main__`)

**Files:**
- Create: `src/turiya/cli.py`, `src/turiya/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: every `operations.*` module, `config.load`, `errors.TuriyaError`.
- Produces: a Typer `app` with subcommands `backup`, `restore`, `status`, `query`, `setup`, `teardown`. Each loads config via `config.load()`, calls the matching operation, maps a `False`/exception to a non-zero exit (`typer.Exit(code=1)`), and prints `TuriyaError` messages cleanly. `__main__.py` calls `app()` so `python -m turiya` works (used by launchd).

- [ ] **Step 1: Write the tests**

`tests/test_cli.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from turiya.cli import app

runner = CliRunner()


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("backup", "restore", "status", "query", "setup", "teardown"):
        assert cmd in result.stdout


def test_backup_runs_against_harness(harness_config: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0


def test_query_mutual_exclusivity_exits_nonzero(harness_config: Path) -> None:
    result = runner.invoke(app, ["query", "--find", "x", "--since", "2020-01-01"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py`
Expected: FAIL (module not defined).

- [ ] **Step 3: Implement `cli.py` and `__main__.py`**

`src/turiya/cli.py`:
```python
"""Typer CLI — thin layer mapping subcommands to operations."""

from __future__ import annotations

import typer

from . import config
from .errors import TuriyaError
from .operations import backup as backup_op
from .operations import query as query_op
from .operations import restore as restore_op
from .operations import setup as setup_op
from .operations import status as status_op

app = typer.Typer(add_completion=False, help="turiya: encrypted multi-cloud backups.")


def _load() -> config.Config:
    try:
        return config.load()
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def backup(
    dry_run: bool = typer.Option(False, "--dry-run"),
    include: list[str] = typer.Option([], "--include"),
    pattern: list[str] = typer.Option([], "--pattern"),
    glob: list[str] = typer.Option([], "--glob"),
    exclude: list[str] = typer.Option([], "--exclude"),
) -> None:
    ok = backup_op.run(_load(), dry_run=dry_run, include=include, pattern=pattern, glob=glob, exclude=exclude)
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def restore(
    target: str = typer.Option(..., "--target"),
    repo: str | None = typer.Option(None, "--repo"),
    snapshot: str = typer.Option("latest", "--snapshot"),
    include: list[str] = typer.Option([], "--include"),
    pattern: list[str] = typer.Option([], "--pattern"),
    glob: list[str] = typer.Option([], "--glob"),
    exclude: list[str] = typer.Option([], "--exclude"),
) -> None:
    ok = restore_op.run(_load(), repo=repo, snapshot=snapshot, target=target,
                        include=include, pattern=pattern, glob=glob, exclude=exclude)
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def status(
    mode: str = typer.Option("latest", "--mode", help="latest | all | check"),
    include: list[str] = typer.Option([], "--include"),
    pattern: list[str] = typer.Option([], "--pattern"),
    glob: list[str] = typer.Option([], "--glob"),
    exclude: list[str] = typer.Option([], "--exclude"),
) -> None:
    ok = status_op.run(_load(), mode=mode, include=include, pattern=pattern, glob=glob, exclude=exclude)
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def query(
    repo: str | None = typer.Option(None, "--repo"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    find: str | None = typer.Option(None, "--find"),
    versions: str | None = typer.Option(None, "--versions"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        ok = query_op.run(_load(), repo=repo, since=since, until=until, find=find,
                          versions=versions, json_output=json_output)
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def setup(password: str | None = typer.Option(None, "--password")) -> None:
    try:
        setup_op.run(_load(), password=password)
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def teardown() -> None:
    setup_op.teardown(_load())
```

`src/turiya/__main__.py`:
```python
from .cli import app

if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py && uv run mypy src && uv run ruff check .`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add src/turiya/cli.py src/turiya/__main__.py tests/test_cli.py
git commit -m "feat: add Typer CLI wiring all operations"
```

---

### Task 16: Full-suite gate, docs, and cutover to v2.0.0

**Files:**
- Delete: `backup.sh`, `restore.sh`, `status.sh`, `query.sh`, `install.sh`, `uninstall.sh`, `lib/common.sh`, `lib/logging.sh`, `backup.conf`, `com.amir.turiya.plist.template`
- Create: `config.example.toml`
- Modify: `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `.copilot-instructions.md`

**Interfaces:** none (integration/cutover).

- [ ] **Step 1: Full green-suite gate**

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv run ty check
```
Expected: all tests pass; ruff, mypy, ty clean. Do not proceed to deletion until this is green.

- [ ] **Step 2: Add `config.example.toml`**

Create `config.example.toml` at the repo root with the exact schema from the design spec's section 3 (identity, keychain, one `[[schedule]]`, power, two example `[[repo]]` entries, sources, excludes, retention, logging), for users to copy to `~/.config/turiya/config.toml`.

- [ ] **Step 3: Remove the bash implementation**

```bash
git rm backup.sh restore.sh status.sh query.sh install.sh uninstall.sh \
       lib/common.sh lib/logging.sh backup.conf com.amir.turiya.plist.template
```
(They remain recoverable at the `v1.0.0` tag.)

- [ ] **Step 4: Rewrite `README.md`**

Replace the bash usage throughout with: the bootstrap (`brew install restic rclone`, `uv tool install .` or `uv sync`), first-run (`turiya setup`), and the Python CLI reference for `backup`/`restore`/`status`/`query`/`setup`/`teardown` with their flags. Update the repository-structure section to the `src/turiya/` layout. Remove all `jq` references. State config lives at `~/.config/turiya/config.toml` (copy from `config.example.toml`).

- [ ] **Step 5: Update `CLAUDE.md` and `.copilot-instructions.md`**

Replace the bash-specific conventions (bash 3.2 array guards, shellcheck, `lib/*.sh`) with the Python conventions: uv workflow, ruff/mypy/ty/pytest gates, layered package + operations + thin Typer CLI, TOML config + pydantic, the preserved JSONL schema, and "what not to touch" (the core public API the dashboard depends on; the JSONL schema). Keep the logging-schema section (unchanged format).

- [ ] **Step 6: Update `CHANGELOG.md`**

Add:
```markdown
## [2.0.0] - <date>

### Changed
- Rewrote the entire tool from bash to a library-first Python 3.14 package
  (`turiya`): layered core (config/keychain/restic/rclone/logging/
  scheduling + operations) with a thin Typer CLI. Behavior parity with 1.0.0.

### Added
- Item 2: launchd job label is config-driven (no hardcoded name).
- Item 10: full CLI help/validation via Typer.
- Item 11: multiple/flexible schedules via `[[schedule]]` config tables.

### Removed
- The bash implementation and its `jq` runtime dependency (recoverable at tag `v1.0.0`).
```

- [ ] **Step 7: Commit, merge to main, tag**

```bash
git add -A
git commit -m "feat!: replace bash implementation with Python package (v2.0.0)"
git checkout main
git merge --no-ff feat/python-migration -m "merge: Python migration (v2.0.0)"
git tag -a v2.0.0 -m "v2.0.0 — library-first Python rewrite"
uv run pytest   # re-verify on main
```

---

## Self-Review Notes

- **Spec coverage:** Toolchain/packaging → Task 1; errors → Task 2; TOML config + pydantic + location/override → Task 3; Keychain + RESTIC_PASSWORD hook → Task 4; JSONL schema (v1.0.0-compatible) → Task 5; restic subprocess + stderr/exit_error + event model → Task 6; rclone → Task 7; scheduling + items 2/11 → Task 8; test harness over real repos → Task 9; operations parity (backup/restore/status/query) → Tasks 10-13; setup/teardown → Task 14; Typer CLI + item 10 → Task 15; cutover/versioning/docs → Task 16. All spec sections covered.
- **Placeholder scan:** every code step has complete, runnable code; every test step has real assertions and an exact command with expected result.
- **Type/interface consistency:** `Config`/model field names are used identically across config, keychain, logging, restic, operations, scheduling. `StructuredLogger.emit_event(repo=, level=, event=, **fields)` and `.log_human`/`.run_start`/`.run_end` signatures are consistent at every call site. `restic.stream`/`run_json`/`parse_event` and the `FileEvent`/`SummaryEvent`/`ErrorEvent` dataclasses match across restic and all operations. `resolve_repo` is defined once (restore) and reused by query. `resolve_targets` returns `list[str] | None` and its `None` (no-match) path is handled in `backup.run`.
- **Known follow-ons (out of scope, per spec):** items 3, 4-remainder, 8, 9, and the dashboard remain separate sub-projects consuming this core.
