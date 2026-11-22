"""Cloud -> Print intent: a file dropped in a watched folder is printed exactly
once, failures are visible and retried, and the toggle persists. These encode
WHY the dedup table exists (never print the same cloud file twice).
"""
import pytest

from printbridge.config import Config
from printbridge.core import Core
from printbridge.providers.base import IncomingFile, LinkState, ProviderStatus


class FakeProvider:
    key = "fake"
    label = "Fake"
    experimental = False
    supports_incoming = True
    print_folder = "/Fake/ToPrint"

    def __init__(self):
        self.files = [IncomingFile("id1", "a.pdf"), IncomingFile("id2", "b.pdf")]
        self.fail_download = False

    def status(self):
        return ProviderStatus(LinkState.LINKED, "ok")

    def list_incoming(self):
        return list(self.files)

    def download(self, file_id):
        if self.fail_download:
            raise RuntimeError("download boom")
        return b"%PDF fake content"

    # unused here
    def begin_link(self): ...
    def poll_link(self): ...
    def unlink(self): ...
    def upload(self, filename, data): ...


@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    c = Core(Config(database=str(tmp_path / "t.db")))
    c._providers = {"fake": FakeProvider()}
    c._printed = []
    monkeypatch.setattr(c.printer, "print_document",
                        lambda data, **kw: c._printed.append(kw.get("job_name")))
    return c


def test_prints_new_files_once(core):
    assert core.poll_incoming_once() == 2
    assert core._printed == ["a.pdf", "b.pdf"]
    # Second pass: same folder contents, nothing re-printed (dedup).
    assert core.poll_incoming_once() == 0
    assert core._printed == ["a.pdf", "b.pdf"]
    # Both recorded as successful prints in the protocol.
    prints = [a for a in core.log.recent() if a.kind == "print"]
    assert len(prints) == 2
    assert all(a.status == "success" for a in prints)


def test_failure_is_logged_once_and_not_marked_printed(core):
    core._providers["fake"].fail_download = True
    assert core.poll_incoming_once() == 0
    errors = [a for a in core.log.recent() if a.status == "error"]
    assert len(errors) == 2  # one per file, first attempt
    # A second failing pass must NOT add more rows (no log spam)...
    assert core.poll_incoming_once() == 0
    assert len([a for a in core.log.recent() if a.status == "error"]) == 2
    # ...and once the printer recovers, the files finally print.
    core._providers["fake"].fail_download = False
    assert core.poll_incoming_once() == 2


def test_autoprint_toggle_persists(core):
    assert core.autoprint_enabled() is False     # config default
    core.set_autoprint(True)
    assert core.autoprint_enabled() is True
    # survives a fresh Core on the same database
    reopened = Core(core.config)
    assert reopened.autoprint_enabled() is True
