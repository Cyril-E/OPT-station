"""Translation contracts: complete UI messages without changing stored data."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings

STATIC = Path(__file__).parents[1] / "openprinttag_app/static"


def catalog():
    return json.loads((STATIC / "translations.js").read_text().split("Object.freeze(", 1)[1].rsplit(");", 1)[0])


def test_catalog_keeps_interpolation_parameters_and_covers_dynamic_messages():
    messages = catalog()
    for source, english in messages.items():
        assert isinstance(english, str) and english.strip(), source
        assert sorted(re.findall(r"\{\d+\}", source)) == sorted(re.findall(r"\{\d+\}", english)), source
    for name in ("app.js", "printer.js", "notifications.js", "power.js", "mcp.js", "maintenance.js", "updates.js", "https.js", "assistant.js", "configuration.js", "photos.js", "inventory-filters.js", "theme.js"):
        for literal in re.findall(r'\bmsg\(("(?:[^"\\]|\\.)*")', (STATIC / name).read_text()):
            source = json.loads(literal)
            assert source in messages or source == "{0}{1}", (name, source)
    assert messages["Configuration"] == "Settings"
    assert messages["Inconnu"] == "Unknown"


def test_static_labels_and_accessibility_attributes_are_marked_for_translation():
    messages = catalog()
    stack, missing = [], []
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            for key in ("placeholder", "alt", "title", "aria-label"):
                if attrs.get(key) in messages and messages[attrs[key]] != attrs[key]:
                    if key not in attrs.get("data-i18n-attrs", "").split():
                        missing.append((tag, key, attrs[key]))
            if tag not in void:
                stack.append((tag, attrs))

        def handle_endtag(self, tag):
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == tag:
                    del stack[index:]
                    break

        def handle_data(self, value):
            value = value.strip()
            if stack and value in messages and messages[value] != value and "data-i18n" not in stack[-1][1]:
                missing.append((stack[-1][0], value))

    Parser().feed((STATIC / "index.html").read_text())
    assert not missing


def test_language_preference_is_per_browser_and_templates_keep_canonical_values(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        main = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Inconnu", "material_name": "Ma bobine française"}
        created = client.post("/api/favorites", json={"name": "Configuration", "kind": "model", "main": main}).json()
        response = client.get("/api/favorites", headers={"Accept-Language": "en"})
        assert response.json()["items"][0] == created
        assert response.json()["items"][0]["main"] == main
        page = client.get("/").text
        assert 'id="language-select"' in page and 'value="en"' in page and 'value="fr"' in page
        assert 'id="mcp-info"' in page and 'id="mcp-dialog"' in page
        assert 'value="model"' in page and 'value="favorite"' in page
        assert page.index('/static/translations.js') < page.index('/static/i18n.js') < page.index('/static/theme.js')
