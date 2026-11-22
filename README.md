# PrintBridge

A small, web-first service that runs on a Raspberry Pi next to a network
printer/scanner and connects it to **cloud services the printer firmware does
not offer** — without touching the printer firmware at all.

You interact with **one web interface**. You never deal with folder structures,
SANE, CUPS, or any tool other than PrintBridge itself.

- **Scan → Cloud:** scan a document on the printer, PrintBridge pulls it over
  eSCL (AirScan) and uploads it to your chosen cloud service.
- **Print:** upload a file in the web UI, PrintBridge sends it to the printer
  over IPP.
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

### OneDrive

OneDrive works through Microsoft Graph. Microsoft does **not** allow a shared
public client secret, so each deployment needs its own **free** app
registration (one-time, ~2 minutes):

1. Go to the [Azure Portal → App registrations](https://portal.azure.com/) →
   *New registration*.
2. Supported account types: *Personal Microsoft accounts* (or include work/school).
3. Under *Authentication* → *Advanced settings*, enable
   **Allow public client flows** = Yes.
4. Copy the **Application (client) ID** into `config.yaml` →
   `services.onedrive.client_id` (or paste it in the UI).

Then click **Verbinden**. PrintBridge shows a short code; enter it once at
[microsoft.com/devicelogin](https://microsoft.com/devicelogin). Done — from
then on everything is in the UI. No client secret is ever stored, which is why
this is safe to self-host from a public repo.

### Proton Drive — not available yet (on purpose)

Proton Drive has **no official public API**. The only way to reach it today is
through an unofficial, reverse-engineered, end-to-end-encrypted protocol (the
approach `rclone` takes). That is fragile, breaks when Proton changes its apps,
and sits in a terms-of-service grey area.

Rather than ship code that silently fails, PrintBridge lists Proton Drive but
marks it **experimental / unavailable** and refuses uploads with a clear
message. If a maintained, reliable client is adopted, implement the four methods
in `printbridge/providers/protondrive.py`.

## Adding a cloud service (community extensions)

The web UI only ever talks to the `Provider` interface, so a new service is:

1. Subclass the provider protocol (see `providers/base.py`).
2. Implement `status`, `begin_link`, `poll_link`, `unlink`, `upload`.
3. Decorate your factory with `@register("yourservice")`.
4. Import it in `providers/__init__.py`.

It then appears in the UI automatically.

## Development

```bash
pip install -e ".[dev]"
pytest
```
