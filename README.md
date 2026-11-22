# PrintBridge

[![CI](https://github.com/tt-404/printbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/tt-404/printbridge/actions/workflows/ci.yml)

A small, web-first service that runs on a Raspberry Pi next to a network
printer/scanner and connects it to **cloud services the printer firmware does
not offer** — without touching the printer firmware at all.

You interact with **one web interface**. You never deal with folder structures,
SANE, CUPS, or any tool other than PrintBridge itself.

- **Scan → Cloud:** scan a document on the printer, PrintBridge pulls it over
  eSCL (AirScan) and uploads it to your chosen cloud service.
- **Print:** upload a file in the web UI, PrintBridge sends it to the printer
  over IPP.
- **Cloud → Print:** turn on auto-print and PrintBridge watches a cloud folder;
  any file dropped there is downloaded and printed automatically. A file is
  printed exactly once (tracked in the database), and the original stays in the
  cloud.
- **OCR + auto-rename (optional):** with `ocr.enabled`, each scan runs through
  `ocrmypdf` before upload — the PDF becomes searchable and is renamed from its
  text. Needs `ocrmypdf` + Tesseract installed (`sudo apt install ocrmypdf
  tesseract-ocr tesseract-ocr-deu`); any failure falls back to the original.
  Naming modes (`ocr.naming`): `rules` (offline — date + title, e.g.
  `2026-04-03_Rechnung_Swisscom.pdf`); `letter` (offline heuristic for business
  letters — `<recipient first name>_<sender>_<date>`, e.g.
  `Anna_Swisscom_2026-03-15.pdf`, no key, no model); or `llm`, which asks Claude
  to extract the same more robustly (needs `ANTHROPIC_API_KEY`; set `ocr.model`,
  `claude-haiku-5-5` is cheap). Any failure falls back to the rule-based name.
- **Protocol:** every scan and print is logged — what, when, to/from which
  service, success or failure — and shown in the UI.

It talks to the printer only through open standards (**eSCL** for scanning,
**IPP** for printing), so no vendor driver or system print stack is required.
Built and tested against the **HP OfficeJet Pro 9010**, but anything that
speaks eSCL + IPP should work.

## Status & honesty

This is an early version. Be aware of what is and isn't verified:

- The **activity log, config, provider registry and IPP encoder** are covered
  by unit tests.
- The **scan (eSCL), print submit (IPP) and OneDrive OAuth** code is written
  against the published specs/APIs but has **not yet been run against real
  hardware or a live Microsoft account**. Treat your first real scan/print/
  sign-in as the integration test and please report issues.

## Requirements

- Raspberry Pi (tested target: Pi 5) on the same LAN as the printer
- Python 3.11+
- The printer reachable by IP, with AirScan/eSCL and IPP enabled (default on
  the OfficeJet Pro 9010)

## Install

```bash
git clone <your-repo-url> printbridge
cd printbridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.yaml config.yaml   # set your printer IP
printbridge                           # open http://<pi-ip>:8080
```

To run it as a service, adapt and install `systemd/printbridge.service`.

## Connecting services

Open the web UI → **Dienste** (Services).

### WebDAV / Nextcloud (recommended)

The easiest home-user cloud — no developer app registration, just a URL and an
app-password. Works with Nextcloud, ownCloud, many NAS (Synology/QNAP),
mailbox.org and anything else that speaks WebDAV.

In the web UI → **Dienste**, fill in the WebDAV form:

1. **Server-URL:** your WebDAV root. For Nextcloud this is
   `https://YOURSERVER/remote.php/dav/files/USERNAME/`.
2. **Benutzername:** your account name.
3. **App-Passwort:** create one in Nextcloud under *Settings → Security →
   App passwords* (don't use your main password).

Click **Verbinden** — PrintBridge checks the connection and stores the
app-password locally (chmod 600). Then pick target folders under *Ordner wählen*.

> OneDrive and Google Drive are intentionally not built in: both require a
> developer OAuth app registration (Azure / Google Cloud), which is too much
> friction for this project's home-user audience. The OneDrive implementation
> remains in `providers/onedrive.py` (unregistered) for reference.

### Proton Drive (experimental, via the official CLI)

Proton Drive is supported through Proton's **official `proton-drive` CLI**
(a single binary for Windows/macOS/Linux). It is the one external tool
PrintBridge relies on, and only for Proton.

1. Download the `proton-drive` binary from Proton's Drive download page and put
   it on `PATH` (`chmod +x proton-drive` on macOS/Linux). Confirm with
   `proton-drive version`.
2. Run **`proton-drive auth login` once in a terminal** on the Pi. Login happens
   in the browser; the session is stored in the OS keychain. PrintBridge never
   sees your Proton password.
3. In the web UI → **Dienste**, click **Verbinden** on Proton Drive. PrintBridge
   checks that the CLI is logged in; once it is, the status turns *linked*.

Scans upload to `upload_folder`; files dropped in `print_folder` are auto-printed
(if auto-print is on), the same as OneDrive.

It is marked **experimental** because it depends on an external binary, is new,
and one detail is unverified here: the JSON shape of `filesystem list --json`
(used for Cloud → Print) is parsed tolerantly in
`printbridge/providers/protondrive.py` — if your CLI lists files differently,
adjust `_parse_list_json`. Uploads use fully documented commands. Proton's
fair-use rate limits apply.

## Adding a cloud service (community extensions)

The web UI only ever talks to the `Provider` interface, so a new service is:

1. Subclass the provider protocol (see `providers/base.py`).
2. Implement `status`, `begin_link`, `poll_link`, `unlink`, `upload`. For
   Cloud → Print support, set `supports_incoming = True` and implement
   `list_incoming` + `download` (otherwise set it to `False`).
3. Decorate your factory with `@register("yourservice")`.
4. Import it in `providers/__init__.py`.

It then appears in the UI automatically.

## Development

```bash
pip install -e ".[dev]"
pytest
```
