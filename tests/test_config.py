"""Config must load with sane defaults even with no file, and resolve the DB
path into the data directory so the user never touches the filesystem layout.
"""
from printbridge.config import Config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    cfg = Config.load(tmp_path / "does-not-exist.yaml")
    assert cfg.printer.host == "192.168.0.98"
    assert cfg.web.port == 8080
    assert cfg.database_path == tmp_path / "printbridge.db"


def test_loads_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTBRIDGE_DATA_DIR", str(tmp_path))
    p = tmp_path / "config.yaml"
    p.write_text(
        "printer:\n  host: 10.0.0.5\nweb:\n  port: 9000\n"
        "services:\n  onedrive:\n    enabled: true\n    client_id: abc\n"
    )
    cfg = Config.load(p)
    assert cfg.printer.host == "10.0.0.5"
    assert cfg.web.port == 9000
    assert cfg.services["onedrive"]["client_id"] == "abc"
