"""Scan-Inbox intent: a file the printer drops via SMB is uploaded exactly once
to the configured cloud service, half-written files are left alone, and a failed
upload is moved aside (not lost, not retried forever) and shown in the protocol.
"""
import pytest

from printbridge.config import Config, ScanInboxConfig
from printbridge.core import Core
from printbridge.providers.base import LinkState, ProviderStatus


class FakeProvider:
    key = "fake"
    label = "Fake"
    experimental = False
    supports_incoming = False

    def __init__(self):
        self.uploaded = []
        self.fail = False

    def status(self):
        return ProviderStatus(LinkState.LINKED, "ok")

    def upload(self, filename, data):
        if self.fail:
            raise RuntimeError("boom")
        self.uploaded.append((filename, len(data)))


def _core(tmp_path, monkeypatch, min_age=0, enabled=True):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cfg = Config(
        database=str(tmp_path / "t.db"),
        scan_inbox=ScanInboxConfig(enabled=enabled, dir=str(inbox),
                                   service="fake", min_age_seconds=min_age),
    )
    core = Core(cfg)
    fp = FakeProvider()
    core._providers = {"fake": fp}
    return core, inbox, fp


def test_uploads_new_file_once_and_removes_it(tmp_path, monkeypatch):
    core, inbox, fp = _core(tmp_path, monkeypatch)
    (inbox / "doc.pdf").write_bytes(b"hello")
    assert core.poll_scan_inbox() == 0             # first sight: record size, wait
    assert core.poll_scan_inbox() == 1             # size stable -> upload
    assert fp.uploaded == [("doc.pdf", 5)]
    assert not (inbox / "doc.pdf").exists()        # consumed on success
    assert core.poll_scan_inbox() == 0             # nothing left to do
    rows = [a for a in core.log.recent() if a.kind == "scan"]
    assert len(rows) == 1 and rows[0].status == "success"


def test_growing_file_waits_until_size_is_stable(tmp_path, monkeypatch):
    """A file still being written (size changing) must not be processed — this
    is what stops truncated scans from being uploaded."""
    core, inbox, fp = _core(tmp_path, monkeypatch)
    p = inbox / "growing.pdf"
    p.write_bytes(b"part")
    assert core.poll_scan_inbox() == 0             # first sight
    p.write_bytes(b"part-and-more-data")           # grew -> still writing
    assert core.poll_scan_inbox() == 0             # size changed -> keep waiting
    assert core.poll_scan_inbox() == 1             # stable now -> upload
    assert fp.uploaded[0][0] == "growing.pdf"


def test_skips_files_still_being_written(tmp_path, monkeypatch):
    core, inbox, fp = _core(tmp_path, monkeypatch, min_age=3600)
    (inbox / "fresh.pdf").write_bytes(b"x")
    assert core.poll_scan_inbox() == 0             # too new -> skipped
    assert (inbox / "fresh.pdf").exists()
    assert fp.uploaded == []


def test_failed_upload_is_moved_aside_and_logged(tmp_path, monkeypatch):
    core, inbox, fp = _core(tmp_path, monkeypatch)
    fp.fail = True
    (inbox / "bad.pdf").write_bytes(b"x")
    assert core.poll_scan_inbox() == 0             # stability pass
    assert core.poll_scan_inbox() == 0             # processed, upload fails
    assert not (inbox / "bad.pdf").exists()
    assert (inbox / "_failed" / "bad.pdf").exists()
    assert [a for a in core.log.recent() if a.status == "error"]


def test_toggle_persists(tmp_path, monkeypatch):
    core, inbox, fp = _core(tmp_path, monkeypatch, enabled=True)
    assert core.scan_inbox_enabled() is True
    core.set_scan_inbox(False)
    assert core.scan_inbox_enabled() is False
    assert Core(core.config).scan_inbox_enabled() is False
