"""OCR auto-rename intent: turn recognised text into a safe, meaningful
filename (date + title), and never produce an unusable name — fall back to the
original when there is nothing to go on.
"""
from printbridge.ocr import derive_letter_name, derive_name


def test_date_and_title_are_combined():
    text = "Rechnung Swisscom\nRechnungsdatum 03.04.2026\nBetrag CHF 59.00"
    assert derive_name(text, "scan.pdf") == "2026-04-03_Rechnung_Swisscom.pdf"


def test_iso_date_is_kept():
    assert derive_name("Vertrag\n2026-01-15", "x.pdf").startswith("2026-01-15_Vertrag")


def test_title_only_when_no_date():
    assert derive_name("Lieferschein Nr 42", "x.pdf") == "Lieferschein_Nr_42.pdf"


def test_accents_and_symbols_are_sanitised():
    name = derive_name("Prüfbericht Größe & Co.!!!", "x.pdf")
    assert name == "Prufbericht_Grosse_Co.pdf"
    assert all(c.isalnum() or c in "_-." for c in name)


def test_empty_or_noise_falls_back():
    assert derive_name("", "scan-123.pdf") == "scan-123.pdf"
    assert derive_name("   \n  \n", "scan-123.pdf") == "scan-123.pdf"
    assert derive_name("x\n7\n$$", "scan-123.pdf") == "scan-123.pdf"  # no real title


def test_letter_heuristic_extracts_recipient_sender_date():
    text = ("Kanton Zürich\nSicherheitsdirektion\n\n"
            "Herr\nGaëtan Vouillamoz\nMusterstrasse 1\n8000 Zürich\n\n"
            "Zürich, 15.03.2026\n\nSehr geehrter Herr Vouillamoz")
    name = derive_letter_name(text, "scan.pdf")
    assert name.startswith("Gaetan_")      # recipient first name, address block
    assert "Kanton_Zurich" in name          # sender from the letterhead
    assert "2026-03-15" in name             # date normalised


def test_letter_salutation_needs_first_and_last_name():
    text = "Swisscom AG\n\nFrau Anna Meier\n\n01.02.2026\nSehr geehrte Frau Meier"
    assert derive_letter_name(text, "scan.pdf").startswith("Anna_Swisscom")


def test_letter_falls_back_when_empty():
    assert derive_letter_name("", "scan-9.pdf") == "scan-9.pdf"
