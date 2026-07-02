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
