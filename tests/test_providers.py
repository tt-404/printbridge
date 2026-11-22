"""Providers are the community extension point. Intent of these tests:
the registry discovers providers, and each one reports an HONEST status rather
than pretending to be ready — this is what the UI relies on.
"""
import pytest

from printbridge import providers
from printbridge.providers.base import LinkState


def test_builtin_providers_are_registered():
    keys = providers.available_keys()
    assert "webdav" in keys
    assert "protondrive" in keys
    # OneDrive is deliberately not registered (Azure app registration friction).
    assert "onedrive" not in keys


def test_webdav_unconfigured_is_unlinked(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    p = providers.create("webdav")
    assert p.status().state is LinkState.UNLINKED
    assert p.credential_fields  # UI renders a form from these


def test_protondrive_unavailable_without_cli(monkeypatch):
    """Without the proton-drive CLI installed, the provider must report
    UNAVAILABLE and refuse to upload — never silently pretend to work.
    """
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    p = providers.create("protondrive")
    assert p.status().state is LinkState.UNAVAILABLE
    assert p.experimental is True
    with pytest.raises(RuntimeError):
        p.upload("x.pdf", b"data")


def test_unknown_provider_raises():
    with pytest.raises(KeyError):
        providers.create("dropbox")
