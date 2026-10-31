from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings


@pytest.fixture
def station(tmp_path):
    settings = Settings(tmp_path)
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield app, client, settings


def read(client):
    response = client.get("/api/reader/tag")
    assert response.status_code == 200, response.text
    return response.json()


def identity(tag):
    return {"expected_uid": tag["uid"], "expected_revision": tag["revision"]}


def prepare(client, tag, **values):
    return client.post("/api/reader/prepare", json={**identity(tag), "mode": "update", **values})


def test_inventory_remove_then_rescan_does_not_restore_membership(station):
    app, client, settings = station
    tag = read(client)
    added = client.post("/api/inventory/add", json=identity(tag)).json()
    duplicate = client.post("/api/inventory/add", json=identity(tag)).json()
    assert duplicate["id"] == added["id"]
    assert len(client.get("/api/inventory").json()["items"]) == 1
    removed = client.post(f"/api/inventory/{added['id']}/remove", json={"version": duplicate["version"]})
    assert removed.status_code == 200
    assert client.get("/api/inventory").json()["items"] == []
    scanned = read(client)
    assert scanned["inventory"]["in_stock"] is False
    assert scanned["revision"] == tag["revision"]
    readded = client.post("/api/inventory/add", json=identity(scanned)).json()
    assert readded["id"] == added["id"]


def test_printer_simulation_only_refreshes_inventory_on_scan(station):
    app, client, settings = station
    tag = read(client)
    added = client.post("/api/inventory/add", json=identity(tag)).json()
    before = tag["aux"]["consumed_weight"]
    result = client.post("/api/simulator/consume", json={"amount_g": 25})
    assert result.status_code == 200, result.text
    stale = client.get(f"/api/inventory/{added['id']}").json()
    assert stale["aux"]["consumed_weight"] == before
    scanned = read(client)
    assert scanned["aux"]["consumed_weight"] == before + 25
    assert scanned["inventory"]["id"] == added["id"]
    updated = client.get(f"/api/inventory/{added['id']}").json()
    assert updated["aux"]["consumed_weight"] == before + 25


def test_prepared_write_rejects_changed_tag_data_and_replay(station):
    app, client, settings = station
    tag = read(client)
    result = prepare(client, tag, main={"primary_color": "#112233"})
    assert result.status_code == 200, result.text
    token = result.json()["preview_id"]
    client.post("/api/simulator/consume", json={"amount_g": 10}).raise_for_status()
    changed = read(client)
    response = client.post("/api/reader/write", json={"preview_id": token})
    assert response.status_code == 409
    assert read(client)["revision"] == changed["revision"]
    assert client.post("/api/reader/write", json={"preview_id": token}).status_code == 409


def test_prepared_write_rejects_replaced_tag(station):
    app, client, settings = station
    tag = read(client)
    token = prepare(client, tag, aux={"consumed_weight": 200}).json()["preview_id"]
    client.post("/api/simulator/select", json={"uid": "E004010000000002"}).raise_for_status()
    assert client.post("/api/reader/write", json={"preview_id": token}).status_code == 409


def test_successful_edit_preserves_identity_and_updates_known_spool(station):
    app, client, settings = station
    tag = read(client)
    added = client.post("/api/inventory/add", json=identity(tag)).json()
    proposal = prepare(client, tag, main={"primary_color": "#112233"}, aux={"consumed_weight": 250})
    assert proposal.status_code == 200, proposal.text
    assert len(proposal.json()["changes"]) == 2
    response = client.post("/api/reader/write", json={"preview_id": proposal.json()["preview_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["verified"] is True
    assert response.json()["simulation"] is True
    after = response.json()["tag"]
    assert after["main"]["primary_color"] == "#112233"
    assert after["instance_uuid"] == tag["instance_uuid"]
    assert after["main"]["brand_name"] == tag["main"]["brand_name"]
    assert after["inventory"]["id"] == added["id"]
    assert client.get("/api/operations").json()["items"][0]["status"] == "complete"


def test_main_protection_still_allows_aux_edit(station):
    app, client, settings = station
    client.post("/api/simulator/select", json={"uid": "E004010000000002"}).raise_for_status()
    tag = read(client)
    assert tag["protections"]["main"] is True
    assert prepare(client, tag, main={"primary_color": "#001122"}).status_code == 423
    assert prepare(client, tag, aux={"consumed_weight": 100}).status_code == 200


def test_favorite_creation_two_bobbins_are_distinct_and_persist(station):
    app, client, settings = station
    main = {"material_class": "FFF", "material_type": "PLA", "brand_name": "Essai", "nominal_netto_full_weight": 1000, "primary_color": "#789abc"}
    favorite = client.post("/api/favorites", json={"name": "Mon PLA", "main": main})
    assert favorite.status_code == 200, favorite.text
    ids = []
    for _ in range(2):
        client.post("/api/simulator/blank", json={}).raise_for_status()
        tag = read(client)
        proposal = client.post("/api/reader/prepare", json={**identity(tag), "mode": "create", "main": main, "aux": {}, "favorite_id": favorite.json()["id"]})
        assert proposal.status_code == 200, proposal.text
        written = client.post("/api/reader/write", json={"preview_id": proposal.json()["preview_id"]}).json()["tag"]
        assert written["remaining_weight"] is None  # Absence de consommé != zéro.
        assert written["provenance"]["kind"] == "favorite"
        ids.append(written["instance_uuid"])
        client.post("/api/inventory/add", json=identity(written)).raise_for_status()
    assert ids[0] != ids[1]
    other = create_app(settings)
    with TestClient(other, client=("127.0.0.1", 12346)) as second:
        assert len(second.get("/api/inventory").json()["items"]) == 2
        assert second.get("/api/favorites").json()["items"][0]["name"] == "Mon PLA"


def test_favorite_rejects_per_instance_fields(station):
    app, client, settings = station
    for name, value in [("instance_uuid", "0" * 32), ("actual_netto_full_weight", 987), ("brand_specific_instance_id", "copied")]:
        response = client.post("/api/favorites", json={"name": "Interdit", "main": {name: value}})
        assert response.status_code == 422, response.text


def test_remote_inventory_and_favorites_without_remote_nfc(station):
    app, local, settings = station
    tag = read(local)
    item = local.post("/api/inventory/add", json=identity(tag)).json()
    with TestClient(app, client=("192.0.2.35", 12345)) as remote:
        assert remote.get("/api/status").json()["local_station"] is False
        assert remote.get("/api/reader/tag").status_code == 403
        assert remote.get("/api/simulator/tags").status_code == 403
        assert remote.post("/api/reader/prepare", json={**identity(tag), "mode": "update", "main": {}}).status_code == 403
        assert remote.get("/api/inventory").json()["items"][0]["id"] == item["id"]
        assert remote.post(f"/api/inventory/{item['id']}/remove", json={"version": item["version"]}).status_code == 200
        response = remote.post("/api/favorites", json={"name": "Favori réseau", "main": {"material_class": "FFF"}})
        assert response.status_code == 200
    assert local.get("/api/inventory").json()["items"] == []
    assert local.get("/api/favorites").json()["items"][0]["name"] == "Favori réseau"


def test_mutations_require_json_same_origin_and_known_host(station):
    app, client, settings = station
    response = client.post("/api/favorites", json={"name": "X", "main": {}}, headers={"Origin": "http://unrelated.invalid"})
    assert response.status_code == 403
    assert client.post("/api/simulator/blank", content="{}").status_code == 415
    assert client.get("/api/status", headers={"Host": "unrelated.invalid"}).status_code == 400


def test_uncertain_write_does_not_retry_or_claim_success(station, monkeypatch):
    app, client, settings = station
    tag = read(client)
    proposal = prepare(client, tag, aux={"consumed_weight": 175}).json()
    original = app.state.reader.write
    writes = []

    def interrupted(image):
        writes.append(image)
        original(image)
        raise OSError("connexion interrompue après écriture")

    monkeypatch.setattr(app.state.reader, "write", interrupted)
    response = client.post("/api/reader/write", json={"preview_id": proposal["preview_id"]})
    assert response.status_code == 503
    assert "incertain" in response.json()["detail"]
    assert len(writes) == 1
    assert read(client)["aux"]["consumed_weight"] == 175
    assert client.post("/api/reader/write", json={"preview_id": proposal["preview_id"]}).status_code == 409
    assert app.state.store.operations()[0]["status"] == "uncertain"


def test_verified_tag_with_database_failure_is_reported_separately(station, monkeypatch):
    app, client, settings = station
    tag = read(client)
    client.post("/api/inventory/add", json=identity(tag)).raise_for_status()
    proposal = prepare(client, tag, aux={"consumed_weight": 150}).json()
    original = app.state.store.observe

    def failure(snapshot):
        raise sqlite3.OperationalError("disque indisponible")

    monkeypatch.setattr(app.state.store, "observe", failure)
    response = client.post("/api/reader/write", json={"preview_id": proposal["preview_id"]})
    assert response.status_code == 503
    assert "écrit et vérifié" in response.json()["detail"]
    assert app.state.store.operations()[0]["status"] == "tag_verified"
    monkeypatch.setattr(app.state.store, "observe", original)
    assert read(client)["aux"]["consumed_weight"] == 150


def test_uncertain_write_stays_explicit_even_when_journal_fails(station, monkeypatch):
    app, client, settings = station
    tag = read(client)
    proposal = prepare(client, tag, aux={"consumed_weight": 150}).json()
    original = app.state.reader.write

    def interrupted(image):
        original(image)
        raise OSError("interruption après écriture")

    def journal_failure(*args, **kwargs):
        raise sqlite3.OperationalError("journal indisponible")

    monkeypatch.setattr(app.state.reader, "write", interrupted)
    monkeypatch.setattr(app.state.store, "end_operation", journal_failure)
    response = client.post("/api/reader/write", json={"preview_id": proposal["preview_id"]})
    assert response.status_code == 503
    assert "incertain" in response.json()["detail"]
    assert "Relire le tag" in response.json()["detail"]
    assert read(client)["aux"]["consumed_weight"] == 150
    assert client.post("/api/reader/write", json={"preview_id": proposal["preview_id"]}).status_code == 409


@pytest.mark.parametrize("raw", [" 8594173672666 ", "  FORMAT-FABRICANT-INCONNU\n"])
def test_qr_raw_provenance_survives_write_and_restart(station, raw):
    app, client, settings = station
    client.post("/api/simulator/blank", json={}).raise_for_status()
    tag = read(client)
    report = client.post("/api/qr/inspect", json={"text": raw}).json()
    main = report["main"] or {"material_class": "FFF", "brand_name": "Essai manuel"}
    proposal = client.post("/api/reader/prepare", json={**identity(tag), "mode": "create", "main": main, "qr_raw": raw})
    assert proposal.status_code == 200, proposal.text
    written = client.post("/api/reader/write", json={"preview_id": proposal.json()["preview_id"]})
    assert written.status_code == 200, written.text
    assert written.json()["tag"]["provenance"]["raw"] == raw
    other = create_app(settings)
    with TestClient(other, client=("127.0.0.1", 12346)) as second:
        assert read(second)["provenance"]["raw"] == raw


def test_simulation_does_not_populate_real_inventory(station, monkeypatch):
    from openprinttag_app.nfc import HardwareReader
    from openprinttag_app.readers import ReaderUnavailable
    def offline(*args, **kwargs):
        raise ReaderUnavailable("Lecteur de test absent.")
    monkeypatch.setattr(HardwareReader, "_run", offline)
    app, client, settings = station
    client.post("/api/inventory/add", json=identity(read(client))).raise_for_status()
    hardware_settings = Settings(settings.data_dir, mode="hardware")
    hardware = create_app(hardware_settings)
    with TestClient(hardware, client=("127.0.0.1", 1234)) as real:
        assert real.get("/api/status").json()["reader"]["connected"] is False
        assert real.get("/api/inventory").json()["items"] == []
        assert real.get("/api/reader/tag").status_code == 503
        assert real.get("/api/simulator/tags").status_code == 409
    assert settings.database != hardware_settings.database
