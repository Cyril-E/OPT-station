"""Portable model/favorite transfer must not mutate physical spools."""
from concurrent.futures import ThreadPoolExecutor
import json

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.library_transfer import LibraryTransfer
from openprinttag_app.storage import Store, ConflictError

MAIN = {"material_class": "FFF", "material_type": "PLA", "brand_name": "Test", "empty_container_weight": 234, "gtin": 2**53 + 11}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def document(*items):
    return json.dumps({"format": "opt-station-library", "version": 1, "items": list(items)})


def item(name="PLA", kind="model", main=None):
    return {"name": name, "kind": kind, "main": MAIN if main is None else main}


def test_roundtrip_subset_has_no_local_identity_or_secret_and_keeps_large_numbers(station, tmp_path):
    app, client = station
    models = [app.state.store.save_favorite("Modèle", MAIN, kind="model"), app.state.store.save_favorite("Favori", MAIN)]
    spool = app.state.store.create_packaged(MAIN, {})
    response = client.post("/api/library/export", json={"identifiers": [models[0]["id"]]})
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    saved = response.json()
    assert saved["items"] == [item("Modèle")]
    assert models[0]["id"] not in response.text and spool["id"] not in response.text
    other = LibraryTransfer(Store(tmp_path / "other.sqlite3"))
    preview = other.preview(response.text)
    result = other.commit(preview["preview_id"], [{"index": 0, "action": "create"}])
    assert result == {"created": 1, "replaced": 0, "skipped": 0}
    assert other.store.favorites()[0]["main"]["gtin"] == 2**53 + 11
    assert other.store.list_spools() == []
    assert app.state.store.get_spool(spool["id"]) == spool
    assert app.state.store.favorites() == sorted(models, key=lambda x: x["name"].lower())


def test_duplicate_choices_skip_rename_replace_and_retry(station):
    app, client = station
    previous = app.state.store.save_favorite("PLA", MAIN, kind="model")
    spool = app.state.store.create_packaged(MAIN, {})
    raw = document(item(main={**MAIN, "empty_container_weight": 250}), item("Nouveau", "favorite"))
    preview = client.post("/api/library/import/preview", json={"document": raw}).json()
    assert preview["items"][0]["existing"]["version"] == 1
    body = {"preview_id": preview["preview_id"], "choices": [{"index": 0, "action": "replace"}, {"index": 1, "action": "create"}]}
    response = client.post("/api/library/import/commit", json=body)
    assert response.status_code == 200 and response.json() == {"created": 1, "replaced": 1, "skipped": 0}
    assert client.post("/api/library/import/commit", json=body).json() == response.json()
    assert len(app.state.store.favorites()) == 2
    assert app.state.store.get_spool(spool["id"]) == spool
    assert next(x for x in app.state.store.favorites() if x["id"] == previous["id"])["main"]["empty_container_weight"] == 250
    transfer = app.state.library_transfer
    second = transfer.preview(document(item()))
    transfer.commit(second["preview_id"], [{"index": 0, "action": "rename", "name": "Copie"}])
    assert len(app.state.store.favorites()) == 3
    third = transfer.preview(document(item()))
    assert transfer.commit(third["preview_id"], [{"index": 0, "action": "skip"}])["skipped"] == 1


def test_atomic_import_failure_stale_library_and_wrong_kind(station):
    app, client = station
    app.state.store.save_favorite("Existing", MAIN, kind="favorite")
    transfer = app.state.library_transfer
    preview = transfer.preview(document(item("New"), item("Existing")))
    with pytest.raises(ValueError):
        transfer.commit(preview["preview_id"], [{"index": 0, "action": "create"}, {"index": 1, "action": "replace"}])
    assert [x["name"] for x in app.state.store.favorites()] == ["Existing"]
    app.state.store.save_favorite("External", MAIN)
    with pytest.raises(ConflictError):
        transfer.commit(preview["preview_id"], [{"index": 0, "action": "create"}, {"index": 1, "action": "skip"}])


@pytest.mark.parametrize("raw", ["not JSON", '{"format":"opt-station-library","version":1,"version":1,"items":[]}',
    document(item(main={"instance_uuid": "d804d00c-ad45-454c-bf12-1fae131c20dc"})),
    document(item(main={"empty_container_weight": -10})), document(item(main={"unknown": 1})),
    document(item("same"), item("Same")), document(item("bad", "bad")), document(item("")),
    '{"format":"opt-station-library","version":true,"items":[]}', " " * 1_000_001])
def test_invalid_files_do_not_change_library(station, raw):
    app, client = station
    response = client.post("/api/library/import/preview", json={"document": raw})
    assert response.status_code in {413, 422}
    assert not app.state.store.favorites()


def test_expiry_concurrent_same_confirmation_and_request_boundaries(station):
    app, client = station
    transfer = app.state.library_transfer
    preview = transfer.preview(document(item()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: transfer.commit(preview["preview_id"], [{"index": 0, "action": "create"}]), range(2)))
    assert results[0] == results[1] and len(app.state.store.favorites()) == 1
    expired = transfer.preview(document(item("Next")))
    transfer.previews[expired["preview_id"]]["expires"] = 0
    with pytest.raises(ConflictError):
        transfer.commit(expired["preview_id"], [{"index": 0, "action": "create"}])
    assert client.post("/api/library/export", json={"identifiers": []}).status_code == 422
    assert client.post("/api/library/import/preview", json={"document": document(item())}, headers={"Origin": "http://evil.invalid"}).status_code == 403
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        assert remote.post("/api/library/import/preview", json={"document": document(item())}).status_code == 200
        client.put("/api/configuration/network", json={"mode": "disabled"})
        assert remote.post("/api/library/import/preview", json={"document": document(item())}).status_code == 403
    app.state.station_power.phase = "requested"
    assert client.post("/api/library/import/preview", json={"document": document(item())}).status_code == 503
