"""Folder browser intent: navigation computes the right parent for both an
empty root (OneDrive) and a non-empty root (Proton), and a chosen target folder
is persisted so the user never has to re-pick it or edit a config file.
"""
from printbridge.config import Config
from printbridge.core import Core
from printbridge.providers.base import parent_folder


def test_parent_folder_onedrive_empty_root():
    assert parent_folder("", "") is None            # at root
    assert parent_folder("/Scans", "") == ""        # back to root
    assert parent_folder("/Scans/2026", "") == "/Scans"


def test_parent_folder_proton_nonempty_root():
    assert parent_folder("/my-files", "/my-files") is None
    assert parent_folder("/my-files/P", "/my-files") == "/my-files"
    assert parent_folder("/my-files/P/Q", "/my-files") == "/my-files/P"


def test_chosen_folder_persists_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    cfg = Config(database=str(tmp_path / "t.db"),
                 services={"onedrive": {"client_id": "abc"}})
    core = Core(cfg)
    core.set_folder("onedrive", "upload", "/Invoices")
    assert core.provider("onedrive").upload_folder == "/Invoices"
    # A fresh Core on the same DB applies the stored choice.
    assert Core(cfg).provider("onedrive").upload_folder == "/Invoices"
