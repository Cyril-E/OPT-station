"""Keep HTML, scripts and styles coherent after a station update."""
import hashlib
import importlib
import os
from pathlib import Path
import re

from fastapi.testclient import TestClient

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings


def test_browser_assets_revalidate_with_a_content_version(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("192.0.2.42", 1234)) as client:
        page = client.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        assets = re.findall(r'(?:src|href)="(/static/[^"?]+)\?v=([a-f0-9]{16})"', page.text)
        assert {Path(path).name for path, _ in assets} == {"translations.js", "i18n.js", "app.js", "printer.js", "notifications.js", "power.js", "mcp.js", "maintenance.js", "updates.js", "https.js", "theme.js", "style.css", "favicon.svg"}
        for path, version in assets:
            response = client.get(path + "?v=" + version)
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest().startswith(version)
            assert response.headers["cache-control"] == "no-cache"
            unchanged = client.get(path + "?v=" + version, headers={"If-None-Match": response.headers["etag"]})
            assert unchanged.status_code == 304
            assert unchanged.headers["cache-control"] == "no-cache"


def test_asset_version_changes_even_when_deployment_keeps_same_size_and_timestamp(tmp_path, monkeypatch):
    module = importlib.import_module("openprinttag_app.app")
    static = tmp_path / "static"
    static.mkdir()
    for name in ("translations.js", "i18n.js", "app.js", "printer.js", "notifications.js", "power.js", "mcp.js", "maintenance.js", "updates.js", "https.js", "theme.js", "style.css", "favicon.svg"):
        (static / name).write_text("old content")
    (static / "index.html").write_text('<script src="/static/app.js"></script>')
    monkeypatch.setattr(module, "STATIC", static)
    app = create_app(Settings(tmp_path / "data"))
    with TestClient(app) as client:
        before = client.get("/").text
        file = static / "app.js"
        stamp = file.stat()
        file.write_text("new content")
        os.utime(file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        after = client.get("/").text
        assert before != after
        url = re.search('src="([^"]+)"', after).group(1)
        assert client.get(url).text == "new content"
