"""The shared Token Factory client must survive callers that use asyncio.run() per
call (the benchmark): a client bound to a closed event loop is replaced."""
import asyncio

import app.services.nemotron_planner as npl


def test_new_client_after_previous_loop_closed(monkeypatch):
    monkeypatch.setattr(npl, "_client", None)
    monkeypatch.setattr(npl, "_own_client", None)
    monkeypatch.setattr(npl, "_own_client_loop", None)

    async def grab():
        return npl._get_client()

    first = asyncio.run(grab())
    second = asyncio.run(grab())            # new loop; the first one is closed
    assert first is not second

    async def twice():
        return npl._get_client(), npl._get_client()

    a, b = asyncio.run(twice())             # same loop: reused
    assert a is b


def test_client_set_from_outside_is_left_alone(monkeypatch):
    fake = object.__new__(type("Fake", (), {"is_closed": False}))
    monkeypatch.setattr(npl, "_client", fake)

    async def grab():
        return npl._get_client()

    assert asyncio.run(grab()) is fake
    assert asyncio.run(grab()) is fake
