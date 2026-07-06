"""Load and validate the TOML runtime configuration."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator

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

    _config_path: Path = PrivateAttr()

    @field_validator("sources", mode="before")
    @classmethod
    def _expand_sources(cls, v: list[str]) -> list[Path]:
        return [_expand(s) for s in v]

    @property
    def config_path(self) -> Path:
        """The actual file this Config was loaded from — not re-derived from
        TURIYA_CONFIG/the default, so it stays correct for a Config built via
        an explicit `load(path=...)` that bypasses the env var/default."""
        return self._config_path


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
        cfg = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config at {resolved}:\n{exc}") from exc
    cfg._config_path = resolved
    return cfg
