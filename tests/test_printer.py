"""The IPP encoder replaces a system print stack, so its byte layout must be
correct: a valid Print-Job header, the document appended after end-of-attributes,
and a correct success/failure reading of the response.
"""
from printbridge.config import Config
from printbridge.core import Core
from printbridge.printer import (
    build_get_printer_attributes,
    build_print_job,
    parse_status_code,
)


def test_print_job_has_valid_header_and_appends_document():
    doc = b"%PDF-1.4 fake"
    body = build_print_job("ipp://host:631/ipp/print", doc, request_id=7)
    # version 2.0, operation Print-Job (0x0002), request-id 7
    assert body[0:2] == b"\x02\x00"
    assert body[2:4] == b"\x00\x02"
    assert body[4:8] == (7).to_bytes(4, "big")
    # operation-attributes-tag present, end-of-attributes (0x03) before the doc
    assert body[8] == 0x01
    assert body.endswith(doc)
    idx = body.index(b"\x03" + doc)
    assert idx > 8  # end-of-attributes separates attrs from document


def test_parse_status_code_success_vs_error():
    ok = b"\x02\x00\x00\x00" + b"\x00\x00\x00\x01"
    assert parse_status_code(ok) == 0x0000
    err = b"\x02\x00\x04\x00" + b"\x00\x00\x00\x01"
    assert parse_status_code(err) == 0x0400


def test_get_printer_attributes_is_a_valid_probe():
    """The reachability probe must be a Get-Printer-Attributes (0x000B) request
    with no document body."""
    body = build_get_printer_attributes("ipp://host:631/ipp/print", request_id=3)
    assert body[0:2] == b"\x02\x00"           # version 2.0
    assert body[2:4] == b"\x00\x0b"           # Get-Printer-Attributes
    assert body[4:8] == (3).to_bytes(4, "big")
    assert body[8] == 0x01                    # operation-attributes-tag
    assert body.endswith(b"\x03")             # ends at end-of-attributes, no doc


def test_set_printer_persists_and_rebuilds(tmp_path, monkeypatch):
    """Changing the printer IP in the UI must persist and actually re-point the
    scanner and printer, with no config-file edit."""
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    cfg = Config(database=str(tmp_path / "t.db"))
    core = Core(cfg)
    core.set_printer("10.1.2.3", "/eSCL")
    assert core.printer_host == "10.1.2.3"
    assert core.scanner.base.startswith("http://10.1.2.3")
    assert core.printer.host == "10.1.2.3"
    # Persisted: a fresh Core picks up the new IP, not the config default.
    assert Core(cfg).printer_host == "10.1.2.3"


def test_test_printer_aggregates_both_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    core = Core(Config(database=str(tmp_path / "t.db")))
    monkeypatch.setattr(core.scanner, "reachable", lambda: (True, "ok"))
    monkeypatch.setattr(core.printer, "reachable", lambda: (False, "timeout"))
    result = core.test_printer()
    assert result["scan_ok"] is True
    assert result["print_ok"] is False
    assert result["print_detail"] == "timeout"
