"""LLM-based filename for scanned letters: <recipient first name>_<sender>_<date>.

Identifying who a letter is addressed to vs. who sent it, and the recipient's
first name, is a judgment/extraction task a regex can't do reliably — so this
asks Claude (Messages API, official SDK) to extract the three fields from the
OCR text and assembles the filename. Everything is best-effort: if the SDK, the
API key or the call is missing/failing, it returns the rule-based fallback, so a
scan is never lost.

The API key is read from the environment (ANTHROPIC_API_KEY) — PrintBridge never
stores it. Model is configurable; a cheap current model (claude-haiku-5-5) is
plenty for this extraction, Opus is the documented default.
"""
from __future__ import annotations

import json
import logging
import re

from .ocr import _find_date, _slug

log = logging.getLogger("printbridge")

_SYSTEM = (
    "You extract metadata from the OCR text of a single scanned letter "
    "(often German/Swiss). Identify:\n"
    "- recipient_first_name: the FIRST name of the person the letter is "
    "addressed TO (the addressee in the recipient address block). Empty string "
    "if it is addressed to a company/department with no person.\n"
    "- sender: the organisation or person who SENT the letter (letterhead / "
    "return address), short form.\n"
    "- date: the date printed on the letter, as YYYY-MM-DD. Empty string if none.\n"
    'Reply with ONLY a JSON object: {"recipient_first_name": "...", '
    '"sender": "...", "date": "..."}. No prose, no code fence.'
)


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {}


def build_filename(data: dict, fallback: str) -> str:
    """Assemble <recipient first name>_<sender>_<date>.pdf from extracted fields."""
    first = _slug(str(data.get("recipient_first_name") or ""), max_len=24)
    sender = _slug(str(data.get("sender") or ""), max_len=40)
    date = _find_date(str(data.get("date") or "")) or ""
    parts = [p for p in (first, sender, date) if p]
    if not parts:
        return fallback
    return "_".join(parts)[:120] + ".pdf"


def llm_name(text: str, fallback: str, *, model: str = "claude-opus-5-5") -> str:
    """Derive a filename via Claude; fall back on any problem."""
    text = (text or "").strip()
    if not text:
        return fallback
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; using rule-based name")
        return fallback
    try:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the env
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            output_config={"effort": "low"},  # cheap/fast extraction
            system=_SYSTEM,
            messages=[{"role": "user", "content": text[:4000]}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        return build_filename(_extract_json(raw), fallback)
    except Exception:
        log.warning("LLM naming failed; using rule-based name", exc_info=True)
        return fallback


def make_namer(model: str):
    """Return a namer(text, fallback) that uses the given model."""
    def namer(text: str, fallback: str) -> str:
        return llm_name(text, fallback, model=model)
    return namer
