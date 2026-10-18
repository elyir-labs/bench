"""The box itself on its own Care (design/power/, A; design/role/'s way back): turn it off or restart it, and make it a
printer again, its run followed from a file. Dry, as in the simulator rig: nothing is turned off or switched."""
import asyncio
import json
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from box import Box, role_state  # noqa: E402

P = lambda step, done: json.dumps({"progress": {"step": step, "done": done, "of": 3}})


def test_the_run_says_its_step_then_fails_or_ends():
    started = json.dumps({"started": "role", "pid": 1})
    assert role_state([started, P("The printer app", 1)], alive=True) == \
        {"state": "switching", "progress": {"step": "The printer app", "done": 1, "of": 3}, "why": None}
    assert role_state([started, P("The printer app", 1), json.dumps({"failed": "the printer app didn't come up"})], alive=False)["why"] == \
        "the printer app didn't come up"
    assert role_state([started, json.dumps({"result": {"role": "printer"}})], alive=False) is None
    assert role_state([started, P("Its screen", 2)], alive=False)["state"] == "failed"   # gone without a word
    assert role_state([], alive=False) is None


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_dry_it_only_says_so(tmp_path):
    async def go():
        app = web.Application()
        Box(tmp_path, tmp_path / "elyir_bench.py", dry=True).add_routes(app)
        async with TestClient(TestServer(app)) as c:
            assert (await (await c.get("/bench/box")).json()) == {"power": True, "role": None}
            r = await (await c.post("/bench/box/power", json={"kind": "restart"})).json()
            assert r == {"ok": True, "kind": "restart", "dry": True}
            r = await (await c.post("/bench/box/role")).json()
            assert r["role"]["state"] == "switching" and r["role"]["progress"]["step"] == "Klipper and Moonraker on"
            assert (await c.post("/bench/box/role")).status == 409          # once at a time
    run(go())
