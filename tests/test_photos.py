"""Photo attachments use isolated inventory data, never physical tags."""
import base64
from io import BytesIO
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.backups import encode_backup, decrypt
from openprinttag_app.config import Settings
from openprinttag_app.photos import MAX_PHOTOS
from openprinttag_app.storage import Store

MAIN = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Photo fixture", "nominal_netto_full_weight": 1000}


def image(size=(180, 120), fmt="PNG", exif=None):
    output = BytesIO()
    Image.new("RGB", size, "orange").save(output, fmt, **({"exif": exif} if exif else {}))
    return output.getvalue()


def payload(content=None):
    return {"image": "data:image/png;base64," + base64.b64encode(content or image()).decode()}


@pytest.fixture
def station(tmp_path):
    ai = Mock(side_effect=AssertionError("Attaching photos must not invoke AI"))
    app = create_app(Settings(tmp_path, network_enabled=True), assistant_fetch=ai)
    spool = app.state.store.create_packaged(MAIN, {"consumed_weight": 123})
    model = app.state.store.save_favorite("Photo model", MAIN, kind="model")
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client, spool, model, ai
    ai.assert_not_called()


def url(kind, item):
    return f"/api/photos/{kind}/{item['id']}"


@pytest.mark.parametrize("kind", ["spool", "template"])
def test_attach_list_preview_restart_delete_without_changing_record(station, kind):
    app, client, spool, model, _ = station
    item = spool if kind == "spool" else model
    endpoint = url(kind, item)
    exif = Image.Exif(); exif[270] = "Private image description"; exif[274] = 6
    result = client.post(endpoint, json=payload(image((2200, 1000), "JPEG", exif)))
    assert result.status_code == 200, result.text
    photo = result.json()
    assert (photo["width"], photo["height"]) == (727, 1600)
    listed = client.get(endpoint).json()["items"]
    assert listed == [photo] and "image" not in photo
    for suffix in ("", "?thumbnail=true"):
        response = client.get(endpoint + "/" + photo["id"] + suffix)
        assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        with Image.open(BytesIO(response.content)) as saved:
            assert saved.format == "JPEG" and not saved.getexif()
    restarted = Store(app.state.store.path)
    assert restarted.photos(kind, item["id"]) == [photo]
    assert restarted.get_spool(spool["id"]) == spool
    assert restarted.favorites() == [model]
    assert client.request("DELETE", endpoint + "/" + photo["id"], json={}).status_code == 200
    assert client.get(endpoint).json() == {"items": []}
    assert client.get(endpoint + "/" + photo["id"]).status_code == 404


def test_permissions_origin_and_cross_record_access(station):
    app, local, spool, model, _ = station
    endpoint = url("spool", spool)
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        photo = remote.post(endpoint, json=payload()).json()
        assert remote.get(endpoint).status_code == 200
        assert remote.post("/api/camera/photos", json={}).status_code == 403
        assert remote.post(endpoint, json={"scan_id": "private-camera-photo"}).status_code == 403
        assert remote.post(endpoint, json=payload(), headers={"Origin": "https://other.invalid"}).status_code == 403
        assert remote.post(endpoint, content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
        other = app.state.store.create_packaged(MAIN, {})
        wrong = url("spool", other) + "/" + photo["id"]
        assert remote.get(wrong).status_code == 404
        assert remote.request("DELETE", wrong, json={}).status_code == 404
        local.put("/api/configuration/network", json={"mode": "disabled"})
        assert remote.get(endpoint).status_code == 403
        assert remote.get(endpoint + "/" + photo["id"]).status_code == 403
        assert remote.post(endpoint, json=payload()).status_code == 403


@pytest.mark.parametrize("body", [{}, {"image": "***"}, {"image": "AA=="}, {"image": "data:image/svg+xml;base64,PHN2Zz4="}, {"image": "AA==", "scan_id": "both"}])
def test_invalid_upload_is_rejected_without_persistence(station, body):
    app, client, spool, _, _ = station
    assert client.post(url("spool", spool), json=body).status_code == 422
    assert app.state.store.photos("spool", spool["id"]) == []


def test_size_limit_and_missing_owner(station):
    _, client, spool, _, _ = station
    assert client.post(url("spool", spool), content=b"x" * 6_100_001, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/photos/spool/absent", json=payload()).status_code == 404
    assert client.post(url("spool", spool), json=payload(image((5000, 4001)))).status_code == 422


def test_photo_limit_archive_and_template_deletion(station):
    app, client, spool, model, _ = station
    for _ in range(MAX_PHOTOS):
        assert client.post(url("spool", spool), json=payload()).status_code == 200
    assert client.post(url("spool", spool), json=payload()).status_code == 422
    assert client.post(f"/api/inventory/{spool['id']}/complete", json={"version": spool["version"]}).status_code == 200
    assert len(client.get(url("spool", spool)).json()["items"]) == MAX_PHOTOS
    assert client.post(url("template", model), json=payload()).status_code == 200
    app.state.store.delete_favorite(model["id"], model["version"])
    with app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM photos WHERE template_id IS NOT NULL").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
    assert len(app.state.store.photos("spool", spool["id"])) == MAX_PHOTOS


@pytest.mark.parametrize("password", [None, "photo-test-password"])
def test_backup_restore_contains_photos_and_detects_changes(station, password):
    app, client, spool, model, _ = station
    a = client.post(url("spool", spool), json=payload()).json()
    b = client.post(url("template", model), json=payload()).json()
    original = app.state.store.photo("spool", spool["id"], a["id"])
    backup = client.post("/api/backups/download", json={"scope": "inventory", "password": password})
    assert backup.status_code == 200, backup.text
    body = {"content": base64.b64encode(backup.content).decode(), "password": password}
    preview = client.post("/api/backups/restore/preview", json=body)
    assert preview.status_code == 200 and preview.json()["photos"] == 2, preview.text
    client.post(url("spool", spool), json=payload())
    assert client.post("/api/backups/restore/commit", json={"preview_id": preview.json()["preview_id"], "confirmed": True}).status_code == 409
    fresh = client.post("/api/backups/restore/preview", json=body).json()
    assert client.post("/api/backups/restore/commit", json={"preview_id": fresh["preview_id"], "confirmed": True}).status_code == 200
    assert app.state.store.photos("spool", spool["id"]) == [a]
    assert app.state.store.photos("template", model["id"]) == [b]
    assert app.state.store.photo("spool", spool["id"], a["id"]) == original
    assert app.state.store.get_spool(spool["id"])["spool_number"] == spool["spool_number"]


def test_configuration_restore_preserves_photos_and_tampered_photo_is_rejected(station):
    app, client, spool, _, _ = station
    added = client.post(url("spool", spool), json=payload()).json()
    record = app.state.backups.collect("configuration")
    preview = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(encode_backup(record)).decode()}).json()
    assert client.post("/api/backups/restore/commit", json={"preview_id": preview["preview_id"], "confirmed": True}).status_code == 200
    assert app.state.store.photos("spool", spool["id"]) == [added]
    record = app.state.backups.collect("inventory")
    photos = record["inventory"]["tables"]["photos"]
    photos["rows"][0][photos["columns"].index("image")] = {"bytes": base64.b64encode(b"not an image").decode()}
    content = base64.b64encode(encode_backup(record)).decode()
    assert client.post("/api/backups/restore/preview", json={"content": content}).status_code == 422
    assert app.state.store.photos("spool", spool["id"]) == [added]


def test_capture_uses_station_camera_and_requires_explicit_attachment(station, monkeypatch):
    app, client, spool, _, _ = station
    camera = app.state.camera
    monkeypatch.setattr(camera, "start_photo", Mock(return_value={"id": "capture-test", "active": False, "state": "found", "preview_ready": True}))
    monkeypatch.setattr(camera, "photo", Mock(return_value=image()))
    assert client.post("/api/camera/photos", json={}).json()["id"] == "capture-test"
    assert client.get(url("spool", spool)).json()["items"] == []
    assert client.post(url("spool", spool), json={"scan_id": "capture-test"}).status_code == 200
    camera.photo.assert_called_once_with("capture-test")


def test_migration_of_v5_is_idempotent_and_keeps_records(station):
    app, _, spool, model, _ = station
    with app.state.store.connect() as db:
        db.execute("DROP TABLE photos")
        db.execute("UPDATE metadata SET value='5' WHERE key='schema_version'")
    for _ in range(2):
        migrated = Store(app.state.store.path)
        assert migrated.get_spool(spool["id"]) == spool
        assert migrated.favorites() == [model]
        assert migrated.photos("spool", spool["id"]) == []
