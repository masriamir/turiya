import json
import subprocess

import pytest
from hypothesis import given
from hypothesis import strategies as st

from turiya import restic
from turiya.restic import ErrorEvent, FileEvent, SummaryEvent

JSON_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=80),
)
JSON_VALUE = st.recursive(
    JSON_SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=30), children, max_size=4),
    ),
    max_leaves=12,
)


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


@given(st.one_of(st.text(max_size=2048), JSON_VALUE.map(json.dumps)))
def test_parse_event_never_raises_for_arbitrary_text_or_json(line: str) -> None:
    event = restic.parse_event(line)

    assert event is None or isinstance(event, FileEvent | SummaryEvent | ErrorEvent)


@given(st.dictionaries(st.text(max_size=30), JSON_VALUE, max_size=8))
def test_parse_summary_preserves_any_json_object(payload: dict[str, object]) -> None:
    payload["message_type"] = "summary"

    event = restic.parse_event(json.dumps(payload))

    assert isinstance(event, SummaryEvent)
    assert event.data == payload


@given(st.sampled_from([float("nan"), float("inf"), float("-inf"), True, False]))
def test_parse_verbose_status_uses_zero_for_non_finite_or_boolean_size(size: float | bool) -> None:
    line = json.dumps(
        {"message_type": "verbose_status", "action": "new", "item": "🙂/report", "data_size": size}
    )

    event = restic.parse_event(line)

    assert isinstance(event, FileEvent)
    assert event.size == 0


@given(
    st.text().filter(
        lambda value: value not in {"verbose_status", "summary", "error", "exit_error"}
    )
)
def test_parse_unknown_message_types_are_ignored(message_type: str) -> None:
    event = restic.parse_event(json.dumps({"message_type": message_type, "item": "東京"}))

    assert event is None
