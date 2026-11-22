"""The Proton list parser turns CLI JSON into printable files. Intent: it must
pick out files, skip folders, and derive clean names + remote paths regardless
of the exact (undocumented) wrapper shape — so Cloud->Print never tries to
"print" a folder or a mis-named entry.
"""
import json

from printbridge.providers.protondrive import _parse_folders_json, _parse_list_json


def test_parses_flat_list_and_skips_folders():
    out = json.dumps([
        {"name": "a.pdf", "type": "file"},
        {"name": "Reports", "type": "folder"},
        {"name": "b.png", "type": "file"},
    ])
    files = _parse_list_json(out, "/my-files/PrintBridge/ToPrint")
    assert [f.name for f in files] == ["a.pdf", "b.png"]
    assert files[0].id == "/my-files/PrintBridge/ToPrint/a.pdf"


def test_parses_dict_wrapped_list():
    out = json.dumps({"items": [{"name": "c.pdf", "type": "file"}]})
    files = _parse_list_json(out, "/my-files/P")
    assert [f.name for f in files] == ["c.pdf"]


def test_isfolder_flag_variant_is_respected():
    out = json.dumps([
        {"name": "sub", "isFolder": True},
        {"filename": "d.pdf"},
    ])
    files = _parse_list_json(out, "/x")
    assert [f.name for f in files] == ["d.pdf"]


def test_real_proton_schema_wraps_name_value():
    """Regression: Proton's `filesystem list --json` wraps names as
    {"ok": true, "value": "X"}. Taking the dict verbatim produced a garbage
    folder name/path and broke uploads — names must be unwrapped.
    """
    out = json.dumps([
        {"name": {"ok": True, "value": "scan.pdf"}, "type": "file"},
        {"name": {"ok": True, "value": "ToPrint"}, "type": "folder"},
    ])
    files = _parse_list_json(out, "/my-files/PrintBridge")
    assert [f.name for f in files] == ["scan.pdf"]
    assert files[0].id == "/my-files/PrintBridge/scan.pdf"
    folders = _parse_folders_json(out, "/my-files/PrintBridge")
    assert [f.name for f in folders] == ["ToPrint"]
    assert folders[0].path == "/my-files/PrintBridge/ToPrint"
