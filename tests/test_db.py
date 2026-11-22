"""The activity log is the user-visible protocol, so its intent is: every scan
and print is recorded with when/what/status, and failures are kept (not hidden).
"""
from printbridge.db import ActivityLog


def test_record_and_recent_are_ordered_newest_first(tmp_path):
    log = ActivityLog(tmp_path / "t.db")
    log.record("scan", "a.pdf", service="onedrive")
    log.record("print", "b.pdf")
    rows = log.recent()
    assert [r.filename for r in rows] == ["b.pdf", "a.pdf"]
    assert rows[1].kind == "scan" and rows[1].service == "onedrive"


def test_failures_are_persisted_not_swallowed(tmp_path):
    """A failed scan must remain visible in the protocol with its reason."""
    log = ActivityLog(tmp_path / "t.db")
    aid = log.record("scan", "x.pdf", service="onedrive", status="pending")
    log.update_status(aid, "error", "printer offline")
    row = log.recent()[0]
    assert row.status == "error"
    assert row.detail == "printer offline"


def test_kind_filter(tmp_path):
    log = ActivityLog(tmp_path / "t.db")
    log.record("scan", "a.pdf")
    log.record("print", "b.pdf")
    assert all(r.kind == "scan" for r in log.recent(kind="scan"))
    assert all(r.kind == "print" for r in log.recent(kind="print"))


def test_set_size(tmp_path):
    log = ActivityLog(tmp_path / "t.db")
    aid = log.record("scan", "a.pdf")
    log.set_size(aid, 2048)
    assert log.recent()[0].size_bytes == 2048
