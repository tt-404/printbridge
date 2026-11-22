"""The IPP encoder replaces a system print stack, so its byte layout must be
correct: a valid Print-Job header, the document appended after end-of-attributes,
and a correct success/failure reading of the response.
"""
from printbridge.printer import build_print_job, parse_status_code


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
