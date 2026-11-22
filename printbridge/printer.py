"""Minimal IPP print client: submit a Print-Job over HTTP, no CUPS required.

IPP is a binary protocol over HTTP. We encode a single Print-Job request by
hand — it is small and fully specified (RFC 8011) — so the project stays
self-contained with no system print stack.

The attribute encoder is pure logic and unit-tested. The actual network submit
has NOT been run against a physical printer in this environment.
"""
from __future__ import annotations

import struct

import httpx

# IPP value tags
_TAG_OPERATION_ATTRS = 0x01
_TAG_END_OF_ATTRS = 0x03
_TAG_CHARSET = 0x47
_TAG_NATURAL_LANG = 0x48
_TAG_URI = 0x45
_TAG_NAME = 0x42            # nameWithoutLanguage
_TAG_MIME = 0x49           # mimeMediaType

_OP_PRINT_JOB = 0x0002
_OP_GET_PRINTER_ATTRS = 0x000B
_VERSION = (2, 0)


def _attr(tag: int, name: str, value: str) -> bytes:
    nb = name.encode("utf-8")
    vb = value.encode("utf-8")
    return struct.pack(">B H", tag, len(nb)) + nb + struct.pack(">H", len(vb)) + vb


def build_print_job(printer_uri: str, document: bytes, *,
                    job_name: str = "printbridge",
                    document_format: str = "application/octet-stream",
                    user: str = "printbridge",
                    request_id: int = 1) -> bytes:
    """Encode a complete IPP Print-Job request including the document."""
    out = bytearray()
    out += struct.pack(">BB H I", _VERSION[0], _VERSION[1], _OP_PRINT_JOB, request_id)
    out.append(_TAG_OPERATION_ATTRS)
    out += _attr(_TAG_CHARSET, "attributes-charset", "utf-8")
    out += _attr(_TAG_NATURAL_LANG, "attributes-natural-language", "en")
    out += _attr(_TAG_URI, "printer-uri", printer_uri)
    out += _attr(_TAG_NAME, "requesting-user-name", user)
    out += _attr(_TAG_NAME, "job-name", job_name)
    out += _attr(_TAG_MIME, "document-format", document_format)
    out.append(_TAG_END_OF_ATTRS)
    out += document
    return bytes(out)


def build_get_printer_attributes(printer_uri: str, *, request_id: int = 1) -> bytes:
    """Encode a Get-Printer-Attributes request — used as a cheap reachability
    probe that does not submit a job."""
    out = bytearray()
    out += struct.pack(">BB H I", _VERSION[0], _VERSION[1], _OP_GET_PRINTER_ATTRS, request_id)
    out.append(_TAG_OPERATION_ATTRS)
    out += _attr(_TAG_CHARSET, "attributes-charset", "utf-8")
    out += _attr(_TAG_NATURAL_LANG, "attributes-natural-language", "en")
    out += _attr(_TAG_URI, "printer-uri", printer_uri)
    out.append(_TAG_END_OF_ATTRS)
    return bytes(out)


def parse_status_code(response: bytes) -> int:
    """Return the IPP status-code from a response. < 0x0100 means success."""
    if len(response) < 4:
        raise ValueError("IPP response too short")
    return struct.unpack(">H", response[2:4])[0]


class Printer:
    def __init__(self, host: str, *, port: int = 631, rp: str = "/ipp/print",
                 timeout: float = 120.0) -> None:
        self.host = host
        self.port = port
        self.rp = rp
        self.timeout = timeout

    @property
    def printer_uri(self) -> str:
        return f"ipp://{self.host}:{self.port}{self.rp}"

    def print_document(self, document: bytes, *, job_name: str = "printbridge",
                       document_format: str = "application/octet-stream") -> None:
        body = build_print_job(self.printer_uri, document,
                               job_name=job_name, document_format=document_format)
        url = f"http://{self.host}:{self.port}{self.rp}"
        resp = httpx.post(url, content=body,
                          headers={"Content-Type": "application/ipp"},
                          timeout=self.timeout)
        resp.raise_for_status()
        code = parse_status_code(resp.content)
        if code >= 0x0100:
            raise RuntimeError(f"Printer rejected job, IPP status 0x{code:04x}")

    def reachable(self, timeout: float = 8.0) -> tuple[bool, str]:
        """Probe the printer via Get-Printer-Attributes. (ok, detail)."""
        url = f"http://{self.host}:{self.port}{self.rp}"
        try:
            resp = httpx.post(url, content=build_get_printer_attributes(self.printer_uri),
                              headers={"Content-Type": "application/ipp"}, timeout=timeout)
        except Exception as exc:
            return False, str(exc)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        try:
            code = parse_status_code(resp.content)
        except ValueError as exc:
            return False, str(exc)
        if code < 0x0100:
            return True, "IPP erreichbar"
        return False, f"IPP-Status 0x{code:04x}"
