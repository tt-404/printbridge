"""FastAPI web application — the only surface the user interacts with."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from .. import discovery
from ..config import Config
from ..core import Core
from ..poller import Poller
from ..providers.base import parent_folder

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    core = Core(config)
    # Tick at most every ~15s so a walk-up scan uploads promptly; cloud
    # auto-print polling shares the same tick.
    poller = Poller(core, min(config.autoprint.interval_seconds, 15))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        poller.start()
        try:
            yield
        finally:
            await poller.stop()

    app = FastAPI(title="PrintBridge", lifespan=lifespan)
    app.state.core = core
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    def ctx(**extra):
        return {"version": __import__("printbridge").__version__, **extra}

    # --- dashboard ---------------------------------------------------------
    @app.get("/")
    async def dashboard(request: Request):
        linked = [
            (key, p) for key, p in core.providers.items()
            if p.status().state.value == "linked"
        ]
        # Linked services we can watch for files to auto-print.
        watched = [
            (p.label, getattr(p, "print_folder", None))
            for _, p in linked if getattr(p, "supports_incoming", False)
        ]
        return templates.TemplateResponse(
            request, "dashboard.html",
            ctx(activity=core.log.recent(limit=10), linked=linked,
                autoprint=core.autoprint_enabled(),
                interval=config.autoprint.interval_seconds,
                watched=watched,
                scaninbox=core.scan_inbox_enabled(),
                scaninbox_dir=config.scan_inbox.dir,
                scaninbox_service=config.scan_inbox.service),
        )

    @app.post("/autoprint/toggle")
    async def autoprint_toggle():
        core.set_autoprint(not core.autoprint_enabled())
        return RedirectResponse("/", status_code=303)

    @app.post("/scaninbox/toggle")
    async def scaninbox_toggle():
        core.set_scan_inbox(not core.scan_inbox_enabled())
        return RedirectResponse("/", status_code=303)

    # --- printer / scanner setup -------------------------------------------
    def _printer_page(request: Request, *, test_result=None, discovered=None,
                      discover_error=None):
        return templates.TemplateResponse(request, "printer.html", ctx(
            host=core.printer_host, escl_path=core.printer_escl_path,
            discovery_available=discovery.available(),
            test_result=test_result, discovered=discovered,
            discover_error=discover_error,
        ))

    @app.get("/printer")
    async def printer_page(request: Request):
        return _printer_page(request)

    @app.post("/printer")
    async def printer_save(host: str = Form(...), escl_path: str = Form("/eSCL")):
        core.set_printer(host, escl_path)
        return RedirectResponse("/printer", status_code=303)

    @app.post("/printer/test")
    async def printer_test(request: Request):
        result = await run_in_threadpool(core.test_printer)
        return _printer_page(request, test_result=result)

    @app.post("/printer/discover")
    async def printer_discover(request: Request):
        try:
            devices = await run_in_threadpool(discovery.discover)
            return _printer_page(request, discovered=devices)
        except Exception as exc:
            return _printer_page(request, discover_error=str(exc))

    # --- services ----------------------------------------------------------
    @app.get("/services")
    async def services(request: Request):
        items = [(key, p, p.status()) for key, p in core.providers.items()]
        return templates.TemplateResponse(request, "services.html", ctx(items=items))

    @app.get("/services/{key}")
    async def service_detail(request: Request, key: str, path: str | None = None):
        p = core.provider(key)
        st = p.status()
        can_browse = getattr(p, "supports_browse", False)
        root = p.browse_root() if can_browse else ""
        current = path if path is not None else root
        folders, error = [], None
        if can_browse and st.state.value == "linked":
            try:
                folders = await run_in_threadpool(p.list_folders, current)
            except Exception as exc:
                error = str(exc)
        parent = parent_folder(current, root) if can_browse else None
        return templates.TemplateResponse(request, "service_detail.html", ctx(
            key=key, provider=p, status=st, can_browse=can_browse,
            current=current, parent=parent, folders=folders, error=error,
            upload_folder=getattr(p, "upload_folder", None),
            print_folder=getattr(p, "print_folder", None),
        ))

    @app.post("/services/{key}/folder")
    async def set_folder(key: str, which: str = Form(...), path: str = Form(...),
                         current: str = Form("")):
        if which in ("upload", "print"):
            core.set_folder(key, which, path)
        return RedirectResponse(f"/services/{key}?path={quote(current)}", status_code=303)

    @app.post("/services/{key}/link")
    async def link(key: str):
        await run_in_threadpool(core.provider(key).begin_link)
        return RedirectResponse("/services", status_code=303)

    @app.post("/services/{key}/configure")
    async def configure(request: Request, key: str):
        p = core.provider(key)
        fields = getattr(p, "credential_fields", None)
        if fields and hasattr(p, "configure"):
            form = await request.form()
            values = {f["name"]: str(form.get(f["name"], "")) for f in fields}
            await run_in_threadpool(lambda: p.configure(**values))
        return RedirectResponse("/services", status_code=303)

    @app.post("/services/{key}/poll")
    async def poll(key: str):
        await run_in_threadpool(core.provider(key).poll_link)
        return RedirectResponse("/services", status_code=303)

    @app.post("/services/{key}/unlink")
    async def unlink(key: str):
        await run_in_threadpool(core.provider(key).unlink)
        return RedirectResponse("/services", status_code=303)

    # --- scan --------------------------------------------------------------
    @app.post("/scan")
    async def scan(service: str = Form(...)):
        try:
            await run_in_threadpool(core.scan_to_service, service)
        except Exception:
            pass  # error already recorded in the activity log; surfaced in UI
        return RedirectResponse("/", status_code=303)

    @app.get("/scan/{service}")
    async def quick_scan(request: Request, service: str):
        """One-tap scan via a plain URL — bookmark it or add it to a phone's
        home screen. Opening the URL scans and uploads, then shows the result.
        (GET has a side effect here by design: home-screen shortcuts issue GET.)
        """
        if service not in core.providers:
            return templates.TemplateResponse(request, "scan_result.html", ctx(
                service=service, label=service, ok=False, known=False,
                filename=None, detail=f"Unbekannter Dienst: {service}"))
        try:
            await run_in_threadpool(core.scan_to_service, service)
        except Exception:
            pass  # recorded in the activity log
        row = next((a for a in core.log.recent(limit=5) if a.kind == "scan"), None)
        return templates.TemplateResponse(request, "scan_result.html", ctx(
            service=service, label=core.providers[service].label, known=True,
            ok=(row.status == "success") if row else False,
            filename=row.filename if row else None,
            detail=row.detail if row else None))

    # --- print -------------------------------------------------------------
    @app.post("/print")
    async def print_file(file: UploadFile):
        data = await file.read()
        fmt = file.content_type or "application/octet-stream"
        try:
            await run_in_threadpool(core.print_document, file.filename or "document", data, fmt)
        except Exception:
            pass  # recorded in the log
        return RedirectResponse("/", status_code=303)

    # --- activity log ------------------------------------------------------
    @app.get("/activity")
    async def activity(request: Request, kind: str | None = None):
        k = kind if kind in ("scan", "print") else None
        return templates.TemplateResponse(
            request, "activity.html",
            ctx(activity=core.log.recent(limit=500, kind=k), filter=k),
        )

    return app
