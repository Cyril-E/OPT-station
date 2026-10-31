"""Official product QR import: exact variant, explicit facts, no physical I/O."""
from email.message import Message
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app import prusa_product as product
from openprinttag_app.prusament import PrusamentError
from openprinttag_app.qr import inspect_qr
from openprinttag_app.spool_qr import decode_spool

RAW = "prusa3d.com/product/prusament-tpu-95a-lipstick-red-500g-nfc/"
URL = "https://www." + RAW
FIXTURE = Path(__file__).parent / "fixtures/prusa-tpu-product.json"


def data():
    return json.loads(FIXTURE.read_text())


def page(value=None, extra=None):
    cache = {"selected": {"data": json.dumps({"product": data() if value is None else value})}}
    if extra is not None:
        cache["other"] = {"data": json.dumps({"product": extra})}
    document = {"props": {"pageProps": {"urqlState": cache}}}
    return '<script type="application/json" id="__NEXT_DATA__">' + json.dumps(document) + '</script>'


def test_imports_only_product_values_for_the_reported_tpu_qr():
    result = product.resolve_prusa_product(RAW, fetch=lambda _: page())
    assert result["raw"] == RAW and result["source_url"] == URL
    assert result["kind"] == "prusa_product" and result["source_scope"] == "product"
    assert result["main"] == {"material_class": "FFF", "brand_name": "Prusament", "material_type": "TPU",
        "material_name": "Prusament TPU 95A Lipstick Red 500g", "nominal_netto_full_weight": 500,
        "filament_diameter": 1.75, "primary_color": "#ff0000", "min_print_temperature": 220,
        "max_print_temperature": 240, "min_bed_temperature": 55, "max_bed_temperature": 75}
    assert result["aux"] == {} and not result["matches"]
    assert product.PRODUCT_NOTICE in result["warnings"] and product.COLOR_NOTICE in result["warnings"]


@pytest.mark.parametrize("raw", [RAW, "www." + RAW, URL, URL.rstrip("/"), "https://" + RAW,
    "http://" + RAW, " HTTPS://WWW.PRUSA3D.COM/product/prusament-tpu-95a-lipstick-red-500g-nfc/\r\n"])
def test_bare_and_complete_urls_select_one_canonical_https_destination(raw):
    fetch = Mock(return_value=page())
    assert inspect_qr(raw)["kind"] == "url"
    result = product.resolve_prusa_product(raw, fetch=fetch)
    assert result["raw"] == raw and result["source_url"] == URL
    fetch.assert_called_once_with(URL)


@pytest.mark.parametrize("raw", [
    "https://example.com/product/prusament-tpu-95a-lipstick-red-500g-nfc/",
    "https://www.prusa3d.com.evil.invalid/product/prusament-tpu-95a-lipstick-red-500g-nfc/",
    "https://127.0.0.1/product/prusament-tpu-95a-lipstick-red-500g-nfc/",
    "prusa3d.com@127.0.0.1/product/prusament-tpu-95a-lipstick-red-500g-nfc/",
    URL.replace("www.prusa3d.com", "user:secret@www.prusa3d.com"),
    URL.replace("www.prusa3d.com", "www.prusa3d.com:443"),
    URL + "?next=http://127.0.0.1", URL + "#other", "//www." + RAW,
    "https://www.prusa3d.com/product/../prusament-example/", URL.replace("-tpu", "-%74pu"),
    "https://www.prusa3d.com/product/original-prusa-core-one/", "file:///etc/passwd",
    URL.replace("www.", "www.\n"), URL.replace("prusament", "prusa ment"),
])
def test_only_documented_product_urls_can_trigger_a_fetch(raw):
    fetch = Mock()
    assert product.resolve_prusa_product(raw, fetch=fetch) is None
    fetch.assert_not_called()


def test_classifier_does_not_fetch_or_derive_fields_from_a_url():
    result = inspect_qr(RAW)
    assert result["main"] == {} and result["raw"] == RAW


def test_variant_selection_ignores_other_colors_and_products():
    other = data(); other.update(slug="product/prusament-tpu-95a-jet-black-500g-nfc/", name="Prusament TPU 95A Jet Black 500g")
    other["parameters"][2]["rgbHex"] = "#000000"
    other["description"] = "Filament diameter 2.85 mm"
    result = product.parse_page(page(extra=other), URL)
    assert result["main"]["primary_color"] == "#ff0000" and result["main"]["filament_diameter"] == 1.75
    with pytest.raises(PrusamentError): product.parse_page(page(other), URL)
    with pytest.raises(PrusamentError): product.parse_page(page(extra=data()), URL)


def test_other_material_weights_decimal_units_and_explicit_ranges():
    value = data(); value.update(name="Prusament PETG Orange 1kg", slug="product/prusament-petg-orange-1kg/")
    value["parameters"][0]["values"][0]["text"] = "1000g"
    value["description"] = "Nozzle temperature <b>230–250 °C</b> Heatbed temperature 80 +/- 10 °C Filament diameter 1,75 mm"
    result = product.parse_page(page(value), "https://www.prusa3d.com/product/prusament-petg-orange-1kg/")
    main = result["main"]
    assert main["material_type"] == "PETG" and main["nominal_netto_full_weight"] == 1000
    assert main["min_print_temperature"] == 230 and main["max_print_temperature"] == 250
    assert main["min_bed_temperature"] == 70 and main["max_bed_temperature"] == 90
    assert main["filament_diameter"] == 1.75


def test_missing_data_is_left_unknown_and_recommendations_are_not_invented_ranges():
    value = data(); value["name"] = "Prusament TPU 95A Lipstick Red"
    value["parameters"] = []; value["description"] = "Nozzle temperature 230 °C. Recommended nozzle 0.4 mm."
    main = product.parse_page(page(value), URL)["main"]
    assert main == {"material_class": "FFF", "brand_name": "Prusament", "material_type": "TPU", "material_name": value["name"]}


@pytest.mark.parametrize("change", ["wrong_brand", "wrong_type", "weight_conflict", "diameter_conflict", "temperature_conflict", "bad_range", "bad_parameters", "empty_name"])
def test_ambiguous_or_changed_product_data_fails_explicitly(change):
    value = data()
    if change == "wrong_brand": value["brand"]["name"] = "Other"
    elif change == "wrong_type": value["detailTemplateType"] = "PRINTER"
    elif change == "weight_conflict": value["parameters"][0]["values"][0]["text"] = "1000g"
    elif change == "diameter_conflict": value["description"] += " Filament diameter 2.85 mm"
    elif change == "temperature_conflict": value["description"] += " Nozzle temperature 250±10 °C"
    elif change == "bad_range": value["description"] = "Nozzle temperature 250–230 °C"
    elif change == "bad_parameters": value["parameters"] = None
    else: value["name"] = ""
    with pytest.raises(PrusamentError, match="illisible"): product.parse_page(page(value), URL)


@pytest.mark.parametrize("html", ["<h1>Not found</h1>", "<script>window.fetch('bad')</script>",
    '<script id="__NEXT_DATA__" type="application/json">not JSON</script>', page() + page(),
    '<script type="application/json" id="__NEXT_DATA__">[]</script>'])
def test_missing_or_malformed_embedded_data_never_executes_script(html):
    with pytest.raises(PrusamentError): product.parse_page(html, URL)


def test_real_shop_page_size_is_supported_but_content_is_still_bounded():
    # The reported shop page is about 730 KiB, larger than a spool page.
    assert product.parse_page(" " * (730 * 1024) + page(), URL)["main"]["material_type"] == "TPU"
    with pytest.raises(PrusamentError): product.parse_page(" " * product.MAX_PAGE + page(), URL)


def test_transport_is_bounded_and_never_follows_redirects_or_fetches_images(monkeypatch):
    headers = Message(); headers["Content-Type"] = "text/html; charset=utf-8"
    response = Mock(); response.headers = headers; response.read.return_value = page().encode()
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    opener = Mock(); opener.open.return_value = response
    factory = Mock(return_value=opener); monkeypatch.setattr(product, "build_opener", factory)
    assert product.fetch_page(URL) == page()
    assert factory.call_args.args[0].proxies == {} and isinstance(factory.call_args.args[1], product.NoRedirect)
    assert opener.open.call_args.args[0].full_url == URL and opener.open.call_args.kwargs["timeout"] == 8
    response.read.assert_called_once_with(product.MAX_PAGE + 1)
    response.read.return_value = b"x" * (product.MAX_PAGE + 1)
    with pytest.raises(PrusamentError): product.fetch_page(URL)
    headers["Content-Type"] = "application/json"
    with pytest.raises(PrusamentError): product.fetch_page(URL)


@pytest.mark.parametrize("error,status", [(HTTPError(URL,404,"private content",{},None),404),
    (HTTPError(URL,302,"private content",{},None),502), (HTTPError(URL,403,"private content",{},None),502),
    (URLError("private diagnostic"),503)])
def test_network_failures_remain_visible_without_echoing_remote_content(monkeypatch,error,status):
    opener=Mock(); opener.open.side_effect=error; monkeypatch.setattr(product,"build_opener",lambda *args:opener)
    with pytest.raises(PrusamentError) as caught: product.fetch_page(URL)
    assert caught.value.status_code == status and "private" not in str(caught.value)


def test_stock_and_model_paths_import_the_same_product_without_hardware_or_duplicate_identity(tmp_path,monkeypatch):
    fetch=Mock(return_value=page())
    app=create_app(Settings(tmp_path,network_enabled=True),prusa_product_fetch=fetch)
    def forbidden(*args,**kwargs): pytest.fail("Product import must not read or write hardware")
    monkeypatch.setattr(app.state.reader,"read",forbidden); monkeypatch.setattr(app.state.reader,"write",forbidden)
    with TestClient(app,client=("192.0.2.42",1)) as client:
        inspection=client.post("/api/qr/inspect",json={"text":RAW})
        assert inspection.status_code == 200,inspection.text
        assert client.get("/api/inventory").json()["items"] == []
        result=inspection.json()
        model=client.post("/api/library/model-source",json={"source":"qr","text":RAW})
        assert model.status_code == 200,model.text
        assert model.json()["main"] == result["main"]
        assert app.state.store.favorites() == []
        fetch.side_effect=AssertionError("Saving reviewed values must remain offline")
        items=[]
        for _ in range(2):
            response=client.post("/api/inventory/packaged",json={"main":result["main"],"aux":{},"qr_raw":RAW})
            assert response.status_code == 200,response.text
            item=response.json();items.append(item)
            assert item["label_state"] == "qr" and item["remaining_weight"] is None
            qr=client.get(f"/api/inventory/{item['id']}/qr?version={item['version']}").json()["text"]
            assert decode_spool(qr)["main"] == item["main"] and decode_spool(qr)["aux"] == {}
        assert items[0]["instance_uuid"] != items[1]["instance_uuid"] and items[0]["spool_number"] != items[1]["spool_number"]
        assert not any(key in items[0]["main"] for key in ("brand_specific_instance_id","actual_netto_full_weight","actual_full_length","manufactured_date","empty_container_weight"))
        assert len(client.get("/api/inventory").json()["items"]) == 2


def test_fetch_errors_keep_stock_empty_and_unrelated_urls_are_not_requested(tmp_path):
    fetch=Mock(side_effect=PrusamentError("Indisponible",503))
    app=create_app(Settings(tmp_path,network_enabled=True),prusa_product_fetch=fetch)
    with TestClient(app,client=("127.0.0.1",1)) as client:
        assert client.post("/api/qr/inspect",json={"text":RAW}).status_code == 503
        fetch.reset_mock()
        report=client.post("/api/qr/inspect",json={"text":"https://example.com/unknown/"})
        assert report.status_code == 200 and report.json()["main"] == {}
        fetch.assert_not_called()
        assert app.state.store.list_spools() == []


def test_reviewed_product_values_can_prepare_and_write_a_simulated_tag_offline(tmp_path):
    fetch=Mock(return_value=page())
    app=create_app(Settings(tmp_path),prusa_product_fetch=fetch)
    with TestClient(app,client=("127.0.0.1",1)) as client:
        inspected=client.post("/api/qr/inspect",json={"text":RAW}).json()
        tag=client.post("/api/simulator/blank",json={}).json()
        fetch.side_effect=AssertionError("NFC preparation and writing must not fetch the page again")
        prepared=client.post("/api/reader/prepare",json={"mode":"create","main":inspected["main"],"aux":{},"qr_raw":RAW,
            "expected_uid":tag["uid"],"expected_revision":tag["revision"]})
        assert prepared.status_code == 200,prepared.text
        written=client.post("/api/reader/write",json={"preview_id":prepared.json()["preview_id"]})
        assert written.status_code == 200,written.text
        assert written.json()["verified"] and written.json()["tag"]["main"]["material_type"] == "TPU"
        assert written.json()["tag"]["aux"] == {} and written.json()["tag"]["remaining_weight"] is None
        assert not app.state.store.list_spools()
