"""Only the current, single-spool job can provide a filament estimate."""
import json
from unittest.mock import Mock
import uuid

import pytest

from openprinttag_app.prusa_connect import (
    ConnectClient, ConnectConfiguration, ConnectError, ConnectMonitor, JOB_MAX_AGE_SECONDS,
    PRINTER_URL, TOKEN_URL, compare_job_to_spool, connect_request, job_filament_estimate,
)
from openprinttag_app.storage import Store
from test_prusa_connect import ORG, PRINTER, TOKEN, Cloud, add, configure, sample


NOW = 1730000000
JOB = {"origin_id": 555, "lifetime_id": str(uuid.UUID(int=555)), "state": "PRINTING",
       "path": "/usb/test.bgcode", "model_weight": 117.87, "weight_remaining": 104.9043}
DETAIL = {"uuid": PRINTER, "organization_id": ORG, "last_online": NOW, "connect_state": "PRINTING", "job_info": JOB,
          "api_key": "test-only-private-field"}
SPOOL = sample({"instance_uuid": str(uuid.UUID(int=2))}, consumed=889)


@pytest.mark.parametrize("key,value", [("uuid", ORG), ("organization_id", PRINTER), ("last_online", NOW-121),
                                        ("last_online", NOW+10), ("last_online", None), ("connect_state", "OFFLINE")])
def test_ineligible_printer_returns_no_estimate(key, value):
    assert job_filament_estimate({**DETAIL, key: value}, ORG, SPOOL, NOW) is None


@pytest.mark.parametrize("key,value", [("origin_id", True), ("origin_id", None), ("lifetime_id", None),
                                        ("state", "FIN_OK"), ("model_weight", None), ("model_weight", 0),
                                        ("model_weight", float("nan")), ("path", "")])
def test_ineligible_job_returns_no_estimate(key, value):
    assert job_filament_estimate({**DETAIL, "job_info": {**JOB, key: value}}, ORG, SPOOL, NOW) is None


@pytest.mark.parametrize("remaining", [None, -1, 118, float("nan"), False])
def test_partial_estimates_never_default_to_zero(remaining):
    result = job_filament_estimate({**DETAIL, "job_info": {**JOB, "weight_remaining": remaining}}, ORG, SPOOL, NOW)
    assert result["model_weight_g"] == 117.87
    assert result["remaining_estimate_g"] is None
    assert compare_job_to_spool(result, {**SPOOL, "status": "ready"})["margin_estimate_g"] is None


def test_comparison_uses_loaded_counter_and_respects_unknown_or_empty_spools():
    result = job_filament_estimate(DETAIL, ORG, SPOOL, NOW)
    assert result["filename"] == "test.bgcode" and result["job_id"] == 555
    loaded = {**SPOOL, "status": "unchanged"}
    compared = compare_job_to_spool(result, loaded)
    assert compared["spool_remaining_g"] == 136 and compared["margin_estimate_g"] == pytest.approx(31.0957)
    unknown = compare_job_to_spool(result, {**loaded, "consumed_weight": None})
    assert unknown["spool_remaining_g"] is None and unknown["margin_estimate_g"] is None
    empty = compare_job_to_spool(result, {**loaded, "consumed_weight": 1025})
    assert empty["spool_remaining_g"] == 0 and empty["margin_estimate_g"] == -104.9043
    complete = job_filament_estimate({**DETAIL, "job_info": {**JOB, "weight_remaining": 0}}, ORG, SPOOL, NOW)
    assert complete["remaining_estimate_g"] == 0 and compare_job_to_spool(complete, loaded)["margin_estimate_g"] == 136
    rounded = compare_job_to_spool(result, {**loaded, "status": "rounded_counter", "remaining_weight": 135.8})
    assert rounded["spool_remaining_g"] == 135.8


@pytest.mark.parametrize("status", ["manual_override", "weight_conflict", "older_counter", "rfid_busy", "unmatched"])
def test_conflicts_keep_file_estimate_and_suppress_balance(status):
    result = job_filament_estimate(DETAIL, ORG, SPOOL, NOW)
    compared = compare_job_to_spool(result, {**SPOOL, "status": status})
    assert compared["model_weight_g"] == 117.87
    assert compared["spool_remaining_g"] is None and compared["margin_estimate_g"] is None


def test_upstream_inaccurate_estimates_keeps_only_total():
    result = job_filament_estimate({**DETAIL, "inaccurate_estimates": True}, ORG, SPOOL, NOW)
    assert result["model_weight_g"] == 117.87 and result["remaining_estimate_g"] is None


def test_multi_tool_or_ambiguous_spool_never_requests_a_whole_job_comparison():
    for mmu, types in [(True, ["PRINT_HEAD"]), (None, ["PRINT_HEAD"]), (False, ["FEEDER"]),
                       (False, ["PRINT_HEAD", "PRINT_HEAD"])]:
        printer = {"id": PRINTER, "state": "PRINTING", "fff": {"hasMmuEnabled": mmu, "tools": [{"type": t} for t in types]}}
        fetch = Mock()
        assert ConnectClient(Mock(), fetch).job_filament(printer, ORG, [SPOOL]) is None
        fetch.assert_not_called()


def test_monitor_expires_and_isolates_job_estimates_from_inventory_and_access(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3")
    item = add(store)
    cfg = ConnectConfiguration(tmp_path)
    configure(cfg)
    cloud = Cloud(item)
    stamp = [NOW]
    requested = []
    def fetch(url, headers, body):
        if url == PRINTER_URL + PRINTER:
            requested.append(url)
            assert body is None and headers["Authorization"] == "Bearer " + TOKEN
            if len(requested) > 1:
                raise ConnectError("access", "Unavailable")
            return 200, json.dumps(DETAIL).encode()
        status, raw = cloud(url, headers, body)
        if "OptStationPrinters" in json.loads(body)["query"]:
            parsed = json.loads(raw)
            head = parsed["data"]["printer"]["printers"]["edges"][0]["node"]["fff"]
            head["hasMmuEnabled"] = False
            head["tools"][0]["type"] = "PRINT_HEAD"
            raw = json.dumps(parsed).encode()
        return status, raw
    monitor = ConnectMonitor(cfg, store, fetch=fetch, clock=lambda: stamp[0])
    state = monitor.check(apply=True, force=True)
    assert state["job_filament"]["instance_uuid"] == item["instance_uuid"]
    assert state["job_filament"]["spool_remaining_g"] == 1025 - cloud.consumed
    assert "test-only-private-field" not in json.dumps(state) and store.get_spool(item["id"]) == item
    stamp[0] += JOB_MAX_AGE_SECONDS + 1
    assert monitor.public()["job_filament"] is None
    configure(cfg, sync_consumption=True)
    result = monitor.check(apply=True, force=True)
    assert result["connected"] and result["job_filament"] is None
    assert store.get_spool(item["id"])["aux"]["consumed_weight"] == cloud.consumed
    assert len(requested) == 2


@pytest.mark.parametrize("url,body", [(PRINTER_URL + PRINTER, b'{}'), (PRINTER_URL + "../jobs", None),
    (PRINTER_URL + PRINTER + "?expand=all", None), ("https://example.org/app/printers/" + PRINTER, None),
    (TOKEN_URL, None)])
def test_read_transport_restricts_origin_method_and_path(url, body):
    with pytest.raises(ConnectError, match="Destination"):
        connect_request(url, {}, body)
