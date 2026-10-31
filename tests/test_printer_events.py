"""Transitions réelles de suivi : aucune déduction d'une fin depuis IDLE ou une panne."""
from copy import deepcopy
import json
from types import SimpleNamespace
from contextlib import contextmanager
import socket
import threading
import time

import httpx
import uvicorn

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.printer_events import PrinterEvents, event_frame


def snapshot(state, stamp=1, job_id=42, **extra):
    value = {"name": "Imprimante de test", "configuration_revision": 1,
             "configured": True, "connected": True, "stale": False, "observed_at": str(stamp),
             "printer": {"state": state, "message": None},
             "job": {"id": job_id, "status_id": job_id, "state": None, "consistent": True, "filename": "Pièce.gcode"}}
    value.update(extra)
    return value


def run(*values):
    current = [None]
    events = PrinterEvents(SimpleNamespace(snapshot=lambda: current[0]))
    for current[0] in values:
        result = events.poll(0)
    return result[2]


def test_finished_is_a_confirmed_transition_of_the_same_known_job_only_once():
    values = [snapshot("IDLE"), snapshot("PRINTING", 2), snapshot("FINISHED", 3), snapshot("FINISHED", 4)]
    events = run(*values)
    assert len(events) == 1 and events[0]["kind"] == "finished"
    assert events[0]["job_id"] == 42 and events[0]["filename"] == "Pièce.gcode"
    assert events[0]["observed_at"] == "3"
    assert len(run(*values, snapshot("PRINTING", 5), snapshot("FINISHED", 6))) == 1


@pytest.mark.parametrize("state", ["FINISHED", "ATTENTION", "ERROR", "PAUSED", "IDLE", "PRINTING"])
def test_initial_state_is_silent(state):
    assert run(snapshot(state), snapshot(state, 2)) == []


@pytest.mark.parametrize("end", ["IDLE", "READY", "STOPPED", "BUSY", "ERROR", "ATTENTION", "PAUSED"])
def test_a_stop_or_idle_or_intervention_is_never_a_success(end):
    events = run(snapshot("PRINTING"), snapshot(end, 2), snapshot("FINISHED", 3, job_id=43))
    assert not any(e["kind"] == "finished" for e in events)


def test_intervention_episodes_are_not_repeated_for_each_poll_or_pause_state():
    events = run(snapshot("PRINTING"), snapshot("ATTENTION", 2), snapshot("ATTENTION", 3),
                 snapshot("PAUSED", 4), snapshot("ERROR", 5), snapshot("PRINTING", 6), snapshot("ATTENTION", 7))
    assert [e["kind"] for e in events] == ["intervention", "intervention"]
    assert [e["observed_at"] for e in events] == ["2", "7"]


@pytest.mark.parametrize("fault", [{"connected": False, "stale": True}, {"connected": False}, {"configuration_revision": 2}])
def test_reconnection_or_reconfiguration_resets_the_baseline(fault):
    values = [snapshot("PRINTING"), snapshot("FINISHED", 2, **fault), snapshot("FINISHED", 3, **({"configuration_revision": 2} if "configuration_revision" in fault else {}))]
    assert run(*values) == []


def test_a_different_or_missing_job_identity_cannot_confirm_the_previous_print():
    assert run(snapshot("PRINTING"), snapshot("FINISHED", 2, job_id=43)) == []
    assert run(snapshot("PRINTING", job_id=None), snapshot("FINISHED", 2, job_id=None)) == []
    # The job endpoint can return 204 after completion; a known preceding job supplies its identity.
    events = run(snapshot("PRINTING"), snapshot("FINISHED", 2, job_id=None))
    assert len(events) == 1 and events[0]["job_id"] == 42


@pytest.mark.parametrize("state,job", [("FINISHED", {"id": 42, "state": "PRINTING"}),
                                     ("PRINTING", {"id": 42, "state": "FINISHED"}),
                                     ("FINISHED", {"id": 42, "consistent": False})])
def test_two_gets_that_disagree_do_not_produce_a_finish(state, job):
    assert run(snapshot("PRINTING"), snapshot(state, 2, job=job)) == []


def test_explicit_job_finish_is_usable_when_the_printer_has_already_returned_to_idle():
    value = snapshot("IDLE", 2)
    value["job"]["state"] = "FINISHED"
    assert run(snapshot("PRINTING"), value)[0]["kind"] == "finished"


def test_new_jobs_can_notify_again_and_messages_are_plain_bounded_data():
    attention = snapshot("ERROR", 4, job_id=43)
    attention["printer"]["message"] = "Filament absent <test>\nVérifier la bobine"
    events = run(snapshot("PRINTING"), snapshot("FINISHED", 2), snapshot("PRINTING", 3, job_id=43), attention)
    assert [e["kind"] for e in events] == ["finished", "intervention"]
    assert events[1]["message"] == attention["printer"]["message"]
    assert events[1]["id"] != events[0]["id"]
    frame = event_frame("printer", events[1], events[1]["id"])
    assert frame.count("data: ") == 1 and frame.count("\n\n") == 1
    assert json.loads(frame.split("data: ", 1)[1]) == events[1]


def test_shared_subscribers_receive_the_same_event_id_and_no_history_on_open():
    current = [snapshot("PRINTING")]
    monitor = PrinterEvents(SimpleNamespace(snapshot=lambda: deepcopy(current[0])))
    monitor.subscribe()
    cursor, _, _ = monitor.poll()
    monitor.subscribe()
    second_cursor, _, _ = monitor.poll()
    current[0] = snapshot("FINISHED", 2)
    first = monitor.poll(cursor)[2]
    second = monitor.poll(second_cursor)[2]
    assert first == second and len(first) == 1
    assert monitor.poll()[2] == []
    monitor.unsubscribe(); monitor.unsubscribe()
    assert monitor._subscribers == 0
    monitor.subscribe()
    assert monitor.poll(0)[2] == []  # A new session never replays the previous finish.
    monitor.unsubscribe()


@pytest.mark.parametrize("mode", ["inventory", "disabled"])
def test_remote_inventory_access_cannot_open_a_notification_stream(tmp_path, mode):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as local:
        local.put("/api/configuration/network", json={"mode": mode}).raise_for_status()
        with TestClient(app, client=("192.0.2.42", 1)) as remote:
            response = remote.get("/api/printer/events")
            assert response.status_code == 403
            assert app.state.printer_events._subscribers == 0


def test_foreign_origin_cannot_start_a_stream(tmp_path):
    with TestClient(create_app(Settings(tmp_path)), client=("127.0.0.1", 1)) as client:
        assert client.get("/api/printer/events", headers={"Origin": "https://other.invalid"}).status_code == 403


@contextmanager
def live_server(app):
    class RemoteEvents:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"] == "/api/printer/events":
                scope = {**scope, "client": ("192.0.2.42", 1234)}
            await app(scope, receive, send)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(RemoteEvents(), log_level="error", timeout_graceful_shutdown=3))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.01)
        yield "http://127.0.0.1:" + str(sock.getsockname()[1])
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def frame(lines):
    result = {}
    for line in lines:
        if not line:
            if result:
                return result
            continue
        field, _, value = line.partition(": ")
        result[field] = json.loads(value) if field == "data" else value
    raise AssertionError("The event stream closed unexpectedly")


def until(lines, predicate):
    for _ in range(100):
        value = frame(lines)
        if predicate(value):
            return value
    raise AssertionError("The expected event did not arrive")


def test_live_stream_survives_background_style_connection_and_revokes_access(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    current = [snapshot("IDLE")]
    app.state.printer_events.monitor = SimpleNamespace(snapshot=lambda: deepcopy(current[0]))
    app.state.printer_events.interval = .015
    with live_server(app) as url, httpx.Client(base_url=url, timeout=3, trust_env=False) as client:
        client.put("/api/configuration/network", json={"mode": "full"}).raise_for_status()
        with client.stream("GET", "/api/printer/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            lines = response.iter_lines()
            assert frame(lines)["event"] == "status"
            current[0] = snapshot("PRINTING", 2)
            until(lines, lambda value: value.get("data", {}).get("observed_at") == "2")
            # A streaming response must not block ordinary API requests.
            assert client.get("/api/status").status_code == 200
            current[0] = snapshot("FINISHED", 3)
            finished = until(lines, lambda value: value["event"] == "printer")
            assert finished["data"]["kind"] == "finished"
            assert finished["data"]["filename"] == "Pièce.gcode"
            assert finished["id"] == finished["data"]["id"]
            client.put("/api/configuration/network", json={"mode": "inventory"}).raise_for_status()
            revoked = until(lines, lambda value: value["event"] == "access")
            assert revoked["data"] == {"allowed": False}
            assert list(lines) == []
        deadline = time.monotonic() + 1
        while app.state.printer_events._subscribers:
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert client.get("/api/printer/events").status_code == 403
        client.put("/api/configuration/network", json={"mode": "full"}).raise_for_status()
        with client.stream("GET", "/api/printer/events", headers={"Last-Event-ID": finished["id"]}) as response:
            lines = response.iter_lines()
            assert frame(lines)["event"] == "status"  # An old Last-Event-ID is never replayed.
            current[0] = snapshot("ATTENTION", 4)
            attention = until(lines, lambda value: value["event"] == "printer")
            assert attention["data"]["kind"] == "intervention"
        deadline = time.monotonic() + 1
        while app.state.printer_events._subscribers:
            assert time.monotonic() < deadline
            time.sleep(.01)
