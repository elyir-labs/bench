"""The Bench Box's service against the real door (door/door.py): finding a printer, asking it, the yes on
its screen, the token kept here, the box's addresses trusted there, and its live intent passed through."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "door"))
import bench_service as B  # noqa: E402
import door as D  # noqa: E402

ORIGINS = ["http://bench.local:8088", "http://localhost:8088"]


def fake_moonraker() -> web.Application:
    async def ws(request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        async for m in sock:
            if m.type == WSMsgType.TEXT:
                req = json.loads(m.data)
                await sock.send_str(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"state": "ready", "via": "moonraker"}}))
        return sock
    async def thumb(request):
        return web.Response(body=b"PNG", content_type="image/png")
    app = web.Application()
    app.router.add_get("/websocket", ws)
    app.router.add_get("/server/files/gcodes/{path:.*}", thumb)
    return app


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    monkeypatch.setattr(B, "FOLLOW_EVERY", 0.05)
    moon = await aiohttp_server(fake_moonraker())
    door = D.Door(tmp_path / "door", str(moon.make_url("")), str(moon.make_url("")), str(moon.make_url("/webcam")),
                  "workshop.elyir.app", sender=lambda *a, **k: 201, home_address="placeholder", printer_name="Workshop")
    door.session = ClientSession()
    local = await aiohttp_server(door.local_app())          # the door's home name (Caddy, at home)
    panel = await aiohttp_client(door.house_app())          # the printer's own screen answering
    # the printer's nginx: /door/status says its home name
    async def status(request):
        return web.json_response({"home_address": str(local.make_url("")).rstrip("/")})
    nginx = web.Application(); nginx.router.add_get("/door/status", status)
    printer = await aiohttp_server(nginx)
    seen = {"door": True}
    scanner = lambda: [{"id": "workshop", "name": "Workshop", "host": "127.0.0.1", "port": printer.port, "ip": "127.0.0.1",
                        "door": seen["door"], "moonraker": moon.port}]
    bench = B.Bench(tmp_path / "bench", "Bench Box", ORIGINS, scanner=scanner)
    client = await aiohttp_client(bench.app())

    class R: pass
    r = R()
    r.bench, r.client, r.door, r.panel, r.local, r.seen, r.state = bench, client, door, panel, local, seen, tmp_path / "bench"
    yield r
    await door.session.close()


async def until(f, tries=60):
    for _ in range(tries):
        if await f():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_the_box_finds_a_printer_asks_it_and_joins_it_once_it_says_yes(rig):
    found = await (await rig.client.get("/bench/found")).json()
    assert [(f["id"], f["name"], f["door"], f["on"]) for f in found] == [("workshop", "Workshop", True, False)]
    r = await rig.client.post("/bench/ask/workshop")
    assert r.status == 202 and (await r.json())["words"] == "Waiting for a yes on Workshop's screen."
    # on Workshop's screen: the Allow card, kind bench, with where the box's screen is
    asks = (await (await rig.panel.get("/door/asks")).json())["asks"]
    assert [(a["name"], a["kind"]) for a in asks] == [("Bench Box", "bench")]
    assert (await rig.panel.post(f"/door/asks/{asks[0]['id']}/allow")).status == 200
    assert await until(lambda: asyncio.sleep(0, "workshop" in rig.bench.printers))
    ask = next(f for f in await (await rig.client.get("/bench/found")).json() if f["id"] == "workshop")
    assert ask["on"] and ask["ask"] == {"state": "allowed", "words": "Workshop said yes."}
    # the token stays here, never in the list a page gets
    listed = await (await rig.client.get("/bench/printers")).json()
    assert listed == [{"id": "workshop", "name": "Workshop", "moonraker": "/bench/p/workshop", "app": f"http://127.0.0.1:{rig.bench.printers['workshop']['port']}"}]
    assert "token" not in json.dumps(listed) and (rig.state / "printers.json").stat().st_mode & 0o077 == 0
    # and Workshop's door now trusts the box's screen
    assert set(ORIGINS) <= rig.door.origins()


async def test_a_printer_that_says_no_or_has_no_door_is_left_out_and_said_so(rig):
    await rig.client.post("/bench/ask/workshop")
    ask = (await (await rig.panel.get("/door/asks")).json())["asks"][0]
    await rig.panel.post(f"/door/asks/{ask['id']}/refuse")
    assert await until(lambda: asyncio.sleep(0, rig.bench.asks["workshop"]["state"] == "refused"))
    assert rig.bench.asks["workshop"]["words"] == "Workshop said no." and "workshop" not in rig.bench.printers
    rig.seen["door"] = False
    rig.bench.scanned = 0
    r = await rig.client.post("/bench/ask/workshop")
    assert r.status == 409 and "door is off" in (await r.json())["words"]


async def test_a_printers_live_intent_and_pictures_come_through_the_box(rig):
    await rig.client.post("/bench/ask/workshop")
    ask = (await (await rig.panel.get("/door/asks")).json())["asks"][0]
    await rig.panel.post(f"/door/asks/{ask['id']}/allow")
    assert await until(lambda: asyncio.sleep(0, "workshop" in rig.bench.printers))
    ws = await rig.client.ws_connect("/bench/p/workshop/websocket")
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "method": "printer.intent", "id": 7}))
    got = json.loads((await ws.receive(timeout=3)).data)
    assert got == {"jsonrpc": "2.0", "id": 7, "result": {"state": "ready", "via": "moonraker"}}
    await ws.close()
    pic = await rig.client.get("/bench/p/workshop/server/files/gcodes/.thumbs/stand-300x300.png")
    assert pic.status == 200 and await pic.read() == b"PNG"
    assert (await rig.client.get("/bench/p/nobody/server/files/gcodes/x.png")).status == 404
    assert (await rig.client.delete("/bench/printers/workshop")).status == 200
    assert await (await rig.client.get("/bench/printers")).json() == []


def test_a_printer_is_read_from_its_mdns_answer():
    def name(n):
        return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"
    def rr(n, t, data):
        import struct
        return name(n) + struct.pack("!HHIH", t, 1, 120, len(data)) + data
    import struct
    inst, host = "Desk._elyir-printer._tcp.local", "desk.local"
    txt = b"".join(bytes([len(x)]) + x for x in (b"name=Desk", b"id=desk", b"door=1", b"moonraker=7125"))
    body = (rr("_elyir-printer._tcp.local", 12, name(inst)) + rr(inst, 33, struct.pack("!HHH", 0, 0, 8088) + name(host))
            + rr(inst, 16, txt) + rr(host, 1, bytes([192, 0, 2, 58])))
    pkt = struct.pack("!HHHHHH", 0xbe7c, 0x8400, 1, 1, 0, 3) + name("_elyir-printer._tcp.local") + struct.pack("!HH", 12, 1) + body
    assert B.printers_from(B.records(pkt)) == [{"id": "desk", "name": "Desk", "host": "desk.local", "port": 8088,
                                                "ip": "192.0.2.58", "door": True, "moonraker": 7125}]


def test_the_box_knows_its_own_addresses_from_the_port_its_screen_is_on(tmp_path):
    b = B.Bench(tmp_path, "Bench Box", ["http://bench.lan:8088"], scanner=lambda: [], serve_port=8088)
    o = b.origins
    assert o[0] == "http://localhost:8088" and o[1].endswith(".local:8088") and "http://bench.lan:8088" in o
    assert len(o) == len(set(o))


def test_printers_seeded_for_testing_are_on_the_bench_without_a_token(tmp_path):
    bench = B.Bench(tmp_path / "b", "Bench Box", [], scanner=lambda: [])
    bench.printers["desk"] = {"name": "Desk", "host": "desk.local", "port": 8088, "token": "said-yes"}
    bench.seed([{"id": "workshop", "name": "Workshop", "host": "workshop.local", "ip": "192.0.2.73", "port": 8088, "moonraker": 7125},
                {"id": "desk", "name": "Desk", "host": "desk.local", "port": 8088}])
    assert bench.printers["workshop"] == {"name": "Workshop", "host": "192.0.2.73", "port": 8088, "moonraker_port": 7125,
                                      "home": None, "token": None, "seeded": True}
    assert bench.printers["desk"]["token"] == "said-yes"                     # asked before: left as it is
    assert json.loads((tmp_path / "b" / "printers.json").read_text())["workshop"]["seeded"] is True
