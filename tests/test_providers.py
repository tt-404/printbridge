"""Providers are the community extension point. Intent of these tests:
the registry discovers providers, and each one reports an HONEST status rather
than pretending to be ready — this is what the UI relies on.
"""
import pytest

from printbridge import providers
from printbridge.providers.base import LinkState


def test_builtin_providers_are_registered():
    keys = providers.available_keys()
    assert "onedrive" in keys
    assert "protondrive" in keys


def test_onedrive_without_client_id_is_unlinked_not_crashing():
    p = providers.create("onedrive")
    st = p.status()
    assert st.state is LinkState.UNLINKED
    assert "client_id" in st.message


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
