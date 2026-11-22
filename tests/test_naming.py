"""LLM naming assembles <recipient first name>_<sender>_<date> from extracted
fields. Intent: correct field order, date normalised, missing fields dropped,
and a safe fallback when nothing usable was extracted (the API call itself is
not exercised here).
"""
from printbridge.naming import build_filename


def test_builds_recipient_sender_date_in_order():
    data = {"recipient_first_name": "Gaëtan",
            "sender": "Kanton Zürich Sicherheitsdirektion",
            "date": "2026-03-15"}
    assert build_filename(data, "scan.pdf") == \
        "Gaetan_Kanton_Zurich_Sicherheitsdirektion_2026-03-15.pdf"


def test_date_is_normalised_to_iso():
    data = {"recipient_first_name": "Anna", "sender": "Swisscom", "date": "15.03.2026"}
    assert build_filename(data, "scan.pdf") == "Anna_Swisscom_2026-03-15.pdf"


def test_missing_fields_are_omitted():
    data = {"recipient_first_name": "", "sender": "Post", "date": ""}
    assert build_filename(data, "scan.pdf") == "Post.pdf"


def test_all_empty_falls_back():
    data = {"recipient_first_name": "", "sender": "", "date": ""}
    assert build_filename(data, "scan-123.pdf") == "scan-123.pdf"
