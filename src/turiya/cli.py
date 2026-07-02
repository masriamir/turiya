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
    cfg = _load()
    try:
        ok = backup_op.run(
            cfg, dry_run=dry_run, include=include, pattern=pattern, glob=glob, exclude=exclude
        )
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
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
    cfg = _load()
    try:
        ok = restore_op.run(
            cfg,
            repo=repo,
            snapshot=snapshot,
            target=target,
            include=include,
            pattern=pattern,
            glob=glob,
            exclude=exclude,
        )
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def status(
    mode: str = typer.Option("latest", "--mode", help="latest | all | check"),
    include: list[str] = typer.Option([], "--include"),
    pattern: list[str] = typer.Option([], "--pattern"),
    glob: list[str] = typer.Option([], "--glob"),
    exclude: list[str] = typer.Option([], "--exclude"),
) -> None:
    cfg = _load()
    try:
        ok = status_op.run(
            cfg, mode=mode, include=include, pattern=pattern, glob=glob, exclude=exclude
        )
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
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
        ok = query_op.run(
            _load(),
            repo=repo,
            since=since,
            until=until,
            find=find,
            versions=versions,
            json_output=json_output,
        )
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
    cfg = _load()
    try:
        setup_op.teardown(cfg)
    except TuriyaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
