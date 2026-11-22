"""Optional OCR + auto-rename of scanned PDFs.

Runs the scanned PDF through `ocrmypdf` (Tesseract): this adds a searchable text
layer *and* gives us the recognised text, from which a meaningful filename is
derived (rule-based: a date plus a short title slug). Everything is best-effort —
on any problem the original bytes and name are returned, so a scan is never lost.

`ocrmypdf` is an external tool (apt: ocrmypdf tesseract-ocr tesseract-ocr-deu),
invoked as a subprocess. OCR is opt-in via config, so a base install needs none
of it.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

log = logging.getLogger("printbridge")

# Date formats commonly found on documents -> normalised to YYYY-MM-DD.
_DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"),
     lambda m: f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
     lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
]


def available(binary: str = "ocrmypdf") -> bool:
    return shutil.which(binary) is not None


def _find_date(text: str) -> str | None:
    for rx, fmt in _DATE_RES:
        m = rx.search(text)
        if m:
            try:
                return fmt(m)
            except (ValueError, IndexError):
                continue
    return None


def _slug(s: str, max_len: int = 48) -> str:
    # Keep letters, digits, spaces; drop accents; collapse to a tidy slug.
    s = s.replace("ß", "ss").replace("ẞ", "ss")  # NFKD leaves ß intact
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len].strip().replace(" ", "_")


def derive_name(text: str, fallback: str) -> str:
    """Build a filename from OCR text: '<date>_<title>.pdf', or the fallback."""
    text = (text or "").strip()
    if not text:
        return fallback
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # First line that has a few real letters makes a decent title.
    title = next(
        (ln for ln in lines if len(re.sub(r"[^A-Za-zÄÖÜäöü]", "", ln)) >= 4),
        None,
    )
    date = _find_date(text)
    slug = _slug(title) if title else ""
    parts = [p for p in (date, slug) if p]
    if not parts:
        return fallback
    return "_".join(parts)[:80] + ".pdf"


def ocr_and_rename(data: bytes, original_name: str, *,
                   language: str = "deu+eng", binary: str = "ocrmypdf",
                   timeout: float = 300.0) -> tuple[bytes, str]:
    """OCR the PDF and return (searchable_pdf_bytes, derived_name).

    Falls back to (data, original_name) if OCR is unavailable or fails.
    """
    if not available(binary):
        return data, original_name
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        out = Path(tmp) / "out.pdf"
        sidecar = Path(tmp) / "text.txt"
        src.write_bytes(data)
        proc = subprocess.run(
            # --rotate-pages/--deskew straighten tilted or mis-oriented scans
            # (needs the tesseract OSD data) before OCR, for better text + names.
            [binary, "-l", language, "--skip-text", "--rotate-pages", "--deskew",
             "--sidecar", str(sidecar), str(src), str(out)],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0 or not out.exists():
            log.warning("ocrmypdf failed (%s): %s", proc.returncode, proc.stderr.strip()[:200])
            return data, original_name
        text = sidecar.read_text(errors="replace") if sidecar.exists() else ""
        new_name = derive_name(text, original_name)
        return out.read_bytes(), new_name
