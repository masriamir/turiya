import subprocess

import pytest

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


def test_stream_terminates_process_on_early_close(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePopen:
        def __init__(self) -> None:
            self._lines = iter(
                [
                    '{"message_type":"verbose_status","action":"new","item":"/a","data_size":1}\n',
                    '{"message_type":"verbose_status","action":"new","item":"/b","data_size":1}\n',
                ]
            )
            self.stdout = self  # doubles as the stdout iterator
            self._alive = True
            self.terminated = False
            self.closed = False

        def __iter__(self) -> FakePopen:
            return self

        def __next__(self) -> str:
            return next(self._lines)

        def close(self) -> None:
            self.closed = True

        def poll(self) -> int | None:
            return None if self._alive else 0

        def terminate(self) -> None:
            self.terminated = True
            self._alive = False

        def wait(self, timeout: float | None = None) -> int:
            self._alive = False
            return 0

        def kill(self) -> None:
            self._alive = False

    fake = FakePopen()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)
    gen = restic.stream("repo", ["backup"], password="x")
    assert isinstance(next(gen), FileEvent)  # consume one event, then abandon
    gen.close()  # triggers the finally
    assert fake.terminated is True
    assert fake.closed is True


def test_stream_raises_resticerror_when_no_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    class NoStdoutPopen:
        stdout = None

        def __init__(self) -> None:
            self._alive = True
            self.terminated = False

        def poll(self) -> int | None:
            return None if self._alive else 0

        def terminate(self) -> None:
            self.terminated = True
            self._alive = False

        def wait(self, timeout: float | None = None) -> int:
            self._alive = False
            return 0

        def kill(self) -> None:
            self._alive = False

    fake = NoStdoutPopen()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)
    gen = restic.stream("repo", ["backup"], password="x")
    with pytest.raises(ResticError):
        next(gen)
    # The guard fires before the loop ever starts, but it must still be inside
    # the try/finally so the still-running child gets terminated/cleaned up.
    assert fake.terminated is True


def test_find_path_returns_single_match(monkeypatch: pytest.MonkeyPatch) -> None:
    ls_output = (
        '{"message_type":"snapshot","time":"2026-01-01T00:00:00Z","paths":["/x"]}\n'
        '{"name":"other.txt","type":"file","path":"/x/other.txt","message_type":"node"}\n'
        '{"name":"config.toml","type":"file","path":"/x/config.toml","message_type":"node"}\n'
    )

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
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

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
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

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=ls_output, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="multiple"):
        restic.find_path("repo", "latest", password="x", name="config.toml")


def test_find_path_raises_resticerror_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from turiya.errors import ResticError

    err = '{"message_type":"exit_error","code":1,"message":"no snapshot found"}\n'

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=err)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="no snapshot found"):
        restic.find_path("repo", "latest", password="x", name="config.toml")


def test_dump_file_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert "dump" in cmd
        assert cmd[-2:] == ["latest", "/x/config.toml"]
        return subprocess.CompletedProcess(cmd, 0, stdout=b"sources = []\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    content = restic.dump_file("repo", "latest", "/x/config.toml", password="x")
    assert content == b"sources = []\n"


def test_dump_file_raises_on_plaintext_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from turiya.errors import ResticError

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 1, stdout=b"", stderr=b'Fatal: cannot dump file: path "/x" not found in snapshot\n'
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(ResticError, match="not found in snapshot"):
        restic.dump_file("repo", "latest", "/x/config.toml", password="x")
