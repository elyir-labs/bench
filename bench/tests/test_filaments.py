"""Your filaments on the Bench Box (design/bench-material/, B): added once (the same twice is one), taken off, and Orca's
library searched through the box's slicer."""
import asyncio
import json
import sys
from pathlib import Path

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filaments import Filaments  # noqa: E402

TERRA = {"preset": "PolyTerra PLA @System", "name": "PolyTerra PLA", "brand": "Polymaker", "material": "pla", "color": "#3b3b3b"}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_added_once_kept_and_taken_off(tmp_path):
    async def go():
        app = web.Application()
        Filaments(tmp_path, "http://slicer", lambda: None).routes(app)
        async with TestClient(TestServer(app)) as c:
            r = await c.post("/bench/filaments", json=TERRA)
            f = await r.json()
            assert r.status == 201 and f["material"] == "PLA" and f["color"] == "#3B3B3B" and f["id"]
            again = await (await c.post("/bench/filaments", json={**TERRA, "color": "#3B3B3B"})).json()
            assert again["id"] == f["id"]
            assert len((await (await c.get("/bench/filaments")).json())["mine"]) == 1
            assert (await c.post("/bench/filaments", json={**TERRA, "color": "charcoal"})).status == 400
            assert (await c.delete(f"/bench/filaments/{f['id']}")).status == 200
            assert (await (await c.get("/bench/filaments")).json())["mine"] == []
            assert (await c.delete("/bench/filaments/nope")).status == 404
    run(go())
    assert json.loads((tmp_path / "filaments.json").read_text()) == []


def test_the_library_is_the_slicers(tmp_path):
    async def go():
        slicer = web.Application()

        async def found(request):
            return web.json_response({"filaments": [{"preset": "PolyTerra PLA @System", "name": "PolyTerra PLA",
                                                     "brand": "Polymaker", "material": "PLA"}], "q": request.query.get("q"), "total": 450})
        slicer.router.add_get("/slice/filaments", found)
        async with TestServer(slicer) as s, ClientSession() as session:
            app = web.Application()
            Filaments(tmp_path, str(s.make_url("")), lambda: session).routes(app)
            async with TestClient(TestServer(app)) as c:
                d = await (await c.get("/bench/filaments/library", params={"q": "terra"})).json()
                assert d["q"] == "terra" and d["filaments"][0]["brand"] == "Polymaker" and d["total"] == 450
    run(go())
