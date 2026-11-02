"""Ingress limits apply to received bytes before framework JSON buffering."""
import asyncio
import json
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings


def receive_chunks(app, chunks, *, path="/api/configuration/network", headers=(), method="PUT"):
    received, sent = [], []

    async def request():
        iterator = iter(chunks)
        finished = asyncio.Event()

        async def receive():
            try:
                chunk = next(iterator)
            except StopIteration:
                await finished.wait()
                return {"type": "http.disconnect"}
            received.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": True}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished.set()

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "http_version": "1.1", "method": method, "scheme": "http", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), *headers],
                 "client": ("192.0.2.20", 50000), "server": ("testserver", 80)}
        # A final empty message lets the downstream JSON parser finish a valid body.
        original_receive = receive
        remaining = len(chunks)

        async def complete_receive():
            nonlocal remaining
            if remaining:
                remaining -= 1
                message = await original_receive()
                message["more_body"] = remaining > 0
                return message
            await finished.wait()
            return {"type": "http.disconnect"}

        await app(scope, complete_receive, send)

    asyncio.run(request())
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    return status, received


def test_chunked_json_is_bounded_even_when_remote_access_is_disabled(tmp_path):
    app = create_app(Settings(tmp_path))
    app.state.network.set_mode("disabled")
    chunks = [b" " * 100_000] * 5 + [b'{"mode":"disabled"}']
    status, received = receive_chunks(app, chunks)
    assert status == 413
    assert sum(received) == 300_000  # stop at the first excess chunk


def test_false_declared_length_does_not_override_actual_byte_count(tmp_path):
    app = create_app(Settings(tmp_path))
    status, received = receive_chunks(app, [b" " * 128_000] * 4,
                                      headers=[(b"content-length", b"2")])
    assert status == 413
    assert len(received) == 3


def test_json_at_the_limit_is_still_delivered_to_the_handler(tmp_path):
    app = create_app(Settings(tmp_path))
    body = json.dumps({"mode": "disabled"}).encode()
    body = b" " * (256_000 - len(body)) + body
    status, received = receive_chunks(app, [body[:128_000], body[128_000:]])
    assert status == 200
    assert sum(received) == 256_000
    assert app.state.network.mode == "disabled"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_json_mutation_methods_share_the_limit(tmp_path, method):
    app = create_app(Settings(tmp_path))
    status, received = receive_chunks(app, [b" " * 128_001] * 4, method=method)
    assert status == 413
    assert len(received) == 2


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_aliases_are_bounded_before_sdk_dispatch(tmp_path, path):
    app = create_app(Settings(tmp_path))
    app.state.mcp_configuration.save(True, 0)
    status, received = receive_chunks(app, [b" " * 128_001] * 4, path=path, method="POST")
    assert status == 413
    assert len(received) == 2


def test_large_route_still_accepts_more_than_ordinary_budget(tmp_path):
    app = create_app(Settings(tmp_path))
    # The real route rejects the invalid import content (422), after ingress
    # accepts its 300 KB body under the existing larger import allowance.
    status, received = receive_chunks(app, [b" " * 300_000 + b"{}"],
                                      path="/api/library/import/preview", method="POST")
    assert status == 422
    assert sum(received) > 256_000
