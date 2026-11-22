"""eSCL (AirScan) client: pull a scan from the printer over plain HTTP.

eSCL is just HTTP + a little XML, so no SANE or vendor driver is needed — which
is what keeps the "no extra tools" promise. Flow per the eSCL spec:
  1. POST a ScanSettings XML to {base}/ScanJobs  -> 201, Location = job URI
  2. GET {job}/NextDocument  -> document bytes; repeat until 404 (no more pages)

NOTE: written against the eSCL spec but NOT verified against a physical device
here. First real scan is the integration test.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_SCAN_NS = "http://schemas.hp.com/imaging/escl/2011/05/03"
_PWG_NS = "http://www.pwg.org/schemas/2010/12/sm"


@dataclass
class ScanSettings:
    resolution: int = 300
    color_mode: str = "RGB24"        # or "Grayscale8"
    document_format: str = "application/pdf"
    source: str = "Platen"            # "Platen" (glass) or "Feeder" (ADF)


def _settings_xml(s: ScanSettings) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<scan:ScanSettings xmlns:scan="{_SCAN_NS}" xmlns:pwg="{_PWG_NS}">'
        f"<pwg:Version>2.6</pwg:Version>"
        f"<scan:Intent>Document</scan:Intent>"
        f"<pwg:InputSource>{s.source}</pwg:InputSource>"
        f"<scan:ColorMode>{s.color_mode}</scan:ColorMode>"
        f"<scan:DocumentFormatExt>{s.document_format}</scan:DocumentFormatExt>"
        f"<scan:XResolution>{s.resolution}</scan:XResolution>"
        f"<scan:YResolution>{s.resolution}</scan:YResolution>"
        f"</scan:ScanSettings>"
    )


class Scanner:
    def __init__(self, host: str, escl_path: str = "/eSCL", *, timeout: float = 120.0) -> None:
        self.base = f"http://{host}{escl_path.rstrip('/')}"
        self.timeout = timeout

    def reachable(self, timeout: float = 8.0) -> tuple[bool, str]:
        """Probe the scanner via eSCL ScannerCapabilities. (ok, detail)."""
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(f"{self.base}/ScannerCapabilities")
        except Exception as exc:
            return False, str(exc)
        if resp.status_code == 200:
            return True, "eSCL erreichbar"
        return False, f"HTTP {resp.status_code}"

    def scan(self, settings: ScanSettings | None = None) -> bytes:
        """Perform one scan and return the document bytes (concatenated pages).

        For PDF, each NextDocument is typically the full multi-page document.
        """
        s = settings or ScanSettings()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base}/ScanJobs",
                content=_settings_xml(s).encode("utf-8"),
                headers={"Content-Type": "text/xml"},
            )
            resp.raise_for_status()
            job = resp.headers.get("Location")
            if not job:
                raise RuntimeError("Scanner did not return a job location.")
            # Location may be absolute or relative.
            if job.startswith("http"):
                next_doc = f"{job.rstrip('/')}/NextDocument"
            else:
                next_doc = f"{self.base.rsplit('/eSCL', 1)[0]}{job.rstrip('/')}/NextDocument"

            pages: list[bytes] = []
            while True:
                r = client.get(next_doc)
                if r.status_code == 404:
                    break  # no more documents
                r.raise_for_status()
                pages.append(r.content)
            if not pages:
                raise RuntimeError("Scan produced no document (empty feeder?).")
            return b"".join(pages)
