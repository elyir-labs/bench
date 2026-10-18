"""The Bench Box from away (bench/away.py, design/bench-remote/ C), against the real door.py's phones, codes and away
list: pairing at the box, invites by link, guests who watch or step in, and that nobody away starts anything."""
import asyncio
import json
import os
import socket
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench_service as B  # noqa: E402
import doors as DR  # noqa: E402
from away import INVITE_LIFE  # noqa: E402

SECRET = "the-box-token-for-workshop"
DAY = 86400


class Clock:
    def __init__(self):
        self.t = 1_760_000_000.0

    def __call__(self):
        return self.t


def fake_moonraker(seen: list) -> web.Application:
    """Answers every call with what it was asked, so a test sees what got past the box."""
    async def ws(request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        await sock.send_str(json.dumps({"jsonrpc": "2.0", "method": "notify_gcode_response", "params": ["ok"]}))
        await sock.send_str(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [{}]}))
        async for m in sock:
            if m.type == WSMsgType.TEXT:
                req = json.loads(m.data)
                seen.append(req)
                await sock.send_str(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"asked": req["method"], "params": req.get("params")}}))
        return sock

    async def thumb(request):
        return web.Response(body=b"PNG", content_type="image/png")

    async def webcam(request):
        return web.Response(body=b"JPEG", content_type="image/jpeg")

    app = web.Application()
    app.router.add_get("/websocket", ws)
    app.router.add_get("/server/files/gcodes/{path:.*}", thumb)
    app.router.add_get("/webcam/{tail:.*}", webcam)
    return app


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client):
    seen: list = []
    moon = await aiohttp_server(fake_moonraker(seen))
    bench_app, printer_app = tmp_path / "bench-app", tmp_path / "app"
    (bench_app / "assets").mkdir(parents=True)
    (printer_app / "assets").mkdir(parents=True)
    (bench_app / "index.html").write_text("<html><head></head><body>bench</body></html>")
    (printer_app / "index.html").write_text("<html><head><title>Printer</title></head><body>printer</body></html>")
    (printer_app / "assets" / "index-abc.js").write_text("printer()")
    (printer_app / "config.json").write_text(json.dumps({"moonraker": {"host": "workshop.local", "port": 7125}}))
    clock = Clock()
    state = tmp_path / "bench"
    bench = B.Bench(state, "Bench Box", [], scanner=lambda: [], now=clock, slicer="http://127.0.0.1:9",
                    printer_app=printer_app, bench_app=bench_app)
    bench.printers["workshop"] = {"name": "Workshop", "host": "127.0.0.1", "port": moon.port, "moonraker_port": moon.port,
                              "home": "http://127.0.0.1:9", "token": SECRET}
    bench.doors.relay(DR.BOX).save({"name": "bench", "address": "bench.elyir.app", "secret": "s", "addr": "a", "token": "t"})
    home = await aiohttp_client(bench.app())          # the box's own service, on the Wi-Fi
    away = await aiohttp_client(bench.away.app())     # its away listener, as Caddy reaches it

    class R:
        pass
    r = R()
    r.bench, r.home, r.away, r.seen, r.clock, r.state = bench, home, away, seen, clock, state
    yield r


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def paired_phone(rig, name="Alex's iPhone"):
    code = (await (await rig.home.post("/bench/phones/code")).json())["code"]
    return (await (await rig.away.post("/door/pair", json={"code": code, "name": name})).json())["token"]


async def guest(rig, reach="watch", lasts="day", name="Jo"):
    phone = await paired_phone(rig)
    inv = await (await rig.away.post("/door/invites", json={"reach": reach, "lasts": lasts}, headers=bearer(phone))).json()
    got = await (await rig.away.post("/door/join", json={"code": inv["code"], "name": name})).json()
    return got["token"], got


async def socket_of(rig, token, path="/bench/p/workshop/websocket"):
    ws = await rig.away.ws_connect(path, protocols=("elyir-bench", f"elyir-bench-token.{token}"))
    for _ in range(1):                                # the status update passes; the G-code response doesn't
        assert json.loads((await ws.receive(timeout=3)).data)["method"] == "notify_status_update"
    return ws


async def call(ws, method, params=None, rid=1):
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": rid}))
    return json.loads((await ws.receive(timeout=3)).data)


async def test_a_phone_pairs_with_a_code_from_the_box_once_and_only_for_ten_minutes(rig):
    made = await (await rig.home.post("/bench/phones/code")).json()
    assert made["url"] == f"https://bench.elyir.app/pair#{made['code']}" and len(made["code"]) == 8
    r = await rig.away.post("/door/pair", json={"code": made["code"], "name": "Alex's iPhone"})
    got = await r.json()
    assert r.status == 200 and got["paired"] and got["phone"]["kind"] == "phone" and "elyir_bench_phone" in r.cookies
    assert (await rig.away.post("/door/pair", json={"code": made["code"], "name": "again"})).status == 401
    late = (await (await rig.home.post("/bench/phones/code")).json())["code"]
    rig.clock.t += 601
    assert (await rig.away.post("/door/pair", json={"code": late, "name": "late"})).status == 401
    me = await (await rig.away.get("/door/me", headers=bearer(got["token"]))).json()
    assert me["paired"] and me["kind"] == "phone" and "pause" in me["actions"] and me["may"] == {"queue": True, "invite": True}
    assert stat.S_IMODE(os.stat(rig.state / "away" / "phones.json").st_mode) == 0o600
    # pairing happens at home only: the box's screen makes the code, nothing away does
    assert (await rig.away.post("/bench/phones/code", headers=bearer(got["token"]))).status == 403


async def test_an_invite_works_once_and_unopened_ends_after_a_day(rig):
    phone = await paired_phone(rig)
    inv = await (await rig.away.post("/door/invites", json={"reach": "step_in", "lasts": "week"}, headers=bearer(phone))).json()
    assert inv["url"] == f"https://bench.elyir.app/join#{inv['code']}" and inv["invited_by"] == "Alex's iPhone"
    assert inv["until"] == rig.clock.t + 7 * DAY and inv["expires"] == rig.clock.t + INVITE_LIFE
    look = await (await rig.away.post("/door/join/look", json={"code": inv["code"]})).json()
    assert look == {"box": {"name": "Bench Box"}, "invited_by": "Alex's iPhone", "reach": "step_in", "until": inv["until"]}
    assert (await rig.away.post("/door/join", json={"code": inv["code"], "name": " "})).status == 400   # a name, first
    r = await rig.away.post("/door/join", json={"code": inv["code"], "name": "Jo"})
    got = await r.json()
    assert r.status == 200 and got["kind"] == "guest" and got["reach"] == "step_in" and got["until"] == inv["until"]
    assert (await rig.away.post("/door/join", json={"code": inv["code"], "name": "Sam"})).status == 401      # once
    # an invite nobody opened: gone the next day
    stale = await (await rig.away.post("/door/invites", json={}, headers=bearer(phone))).json()
    assert stale["reach"] == "watch" and stale["lasts"] == "day"                                            # the default
    forever = await (await rig.home.post("/bench/invites", json={"reach": "watch", "lasts": "removed"})).json()
    assert forever["until"] is None and forever["invited_by"] == "Bench Box"
    rig.clock.t += INVITE_LIFE + 1
    assert (await rig.away.post("/door/join", json={"code": stale["code"], "name": "Sam"})).status == 401
    assert (await (await rig.home.get("/bench/phones")).json())["invites"] == []


async def test_a_guest_whose_time_is_up_is_refused_and_let_go(rig):
    token, _ = await guest(rig, lasts="day")
    assert (await rig.away.get("/bench/printers", headers=bearer(token))).status == 200
    ws = await socket_of(rig, token)
    rig.clock.t += DAY + 1
    assert (await rig.away.get("/bench/printers", headers=bearer(token))).status == 401
    assert not (await (await rig.away.get("/door/me", headers=bearer(token))).json())["paired"]
    await rig.bench.away.sweep()
    assert (await ws.receive(timeout=3)).type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
    assert (await (await rig.home.get("/bench/phones")).json())["guests"] == []


async def test_a_watching_guest_cant_pause_and_one_who_steps_in_can(rig):
    watch, me = await guest(rig, "watch", name="Jo")
    assert me["actions"] == [] and me["may"] == {"queue": False, "invite": False}
    ws = await socket_of(rig, watch)
    assert (await call(ws, "printer.intent"))["result"]["asked"] == "printer.intent"
    refused = await call(ws, "printer.intent.action", {"action": "pause"}, 2)
    assert refused["error"]["code"] == 403 and not any(c["method"] == "printer.intent.action" for c in rig.seen)
    await ws.close()
    step, me = await guest(rig, "step_in", name="Sam")
    assert "pause" in me["actions"] and "start_file" not in me["actions"]
    ws = await socket_of(rig, step)
    got = await call(ws, "printer.intent.action", {"action": "pause", "source": "the app says so"}, 3)
    assert got["result"]["params"]["action"] == "pause"
    assert got["result"]["params"]["source"] == "Sam, away (guest, through the Bench Box)"
    await ws.close()


async def test_nobody_away_starts_heats_moves_sends_gcode_or_touches_files(rig):
    phone = await paired_phone(rig)
    ws = await socket_of(rig, phone)
    for i, (method, params) in enumerate([
            ("printer.intent.action", {"action": "start_file", "args": {"filename": "cube.gcode"}}),
            ("printer.intent.action", {"action": "warm_up"}), ("printer.intent.action", {"action": "taken_off"}),
            ("printer.gcode.script", {"script": "M104 S240"}), ("printer.print.start", {"filename": "cube.gcode"}),
            ("server.files.delete_file", {"path": "gcodes/cube.gcode"}), ("machine.reboot", {}),
            ("server.database.post_item", {"namespace": "elyir-bench", "key": "x", "value": 1})]):
        assert "error" in await call(ws, method, params, 10 + i), method
    assert rig.seen == []
    await ws.close()
    h = bearer(phone)
    for method, path in [("POST", "/screens/workshop/printer/print/start"), ("POST", "/screens/workshop/server/files/upload"),
                         ("GET", "/screens/workshop/server/files/gcodes/cube.gcode"), ("POST", "/screens/workshop/machine/reboot"),
                         ("POST", "/screens/workshop/slice"), ("POST", "/bench/slice/abc/send"),
                         ("POST", "/bench/queue/abc/start"), ("DELETE", "/bench/printers/workshop"), ("POST", "/bench/ask/workshop"),
                         ("POST", "/bench/box/power"), ("GET", "/bench/found"), ("DELETE", "/bench/queue/abc"),
                         ("POST", "/bench/filaments"), ("GET", "/bench/p/workshop/server/files/gcodes/cube.gcode"),
                         ("PUT", "/bench/shelf/0123456789ab/how"), ("PUT", "/bench/shelf/0123456789ab/side")]:
        assert (await rig.away.request(method, path, headers=h)).status == 403, path


async def test_the_bench_away_carries_no_printer_token_or_address(rig):
    assert (await rig.away.get("/bench/printers")).status == 401                  # a stranger: nothing
    phone = await paired_phone(rig)
    r = await rig.away.get("/bench/printers", headers={**bearer(phone), "X-Forwarded-Host": "bench.elyir.app",
                                                       "X-Forwarded-Proto": "https"})
    listed = await r.json()
    assert listed == [{"id": "workshop", "name": "Workshop", "moonraker": "/bench/p/workshop", "app": "https://bench.elyir.app/screens/workshop"}]
    text = json.dumps(listed)
    assert SECRET not in text and "token" not in text and str(rig.bench.printers["workshop"]["port"]) not in text
    pic = await rig.away.get("/bench/p/workshop/server/files/gcodes/.thumbs/cube-300x300.png", headers=bearer(phone))
    assert pic.status == 200 and await pic.read() == b"PNG"


async def test_guests_cant_queue_invite_or_change_the_shelf(rig):
    token, _ = await guest(rig)
    h = bearer(token)
    assert (await rig.away.post("/bench/queue", json={"shelf": "a" * 12}, headers=h)).status == 403
    assert (await rig.away.post("/door/invites", json={"reach": "watch"}, headers=h)).status == 403
    assert (await rig.away.get("/door/invites", headers=h)).status == 403
    assert (await rig.away.delete("/bench/shelf/" + "a" * 12, headers=h)).status == 403
    assert (await rig.away.get("/bench/queue", headers=h)).status == 200                  # watching it is fine


async def test_a_phone_adds_to_the_queue_from_away_and_only_home_starts_it(rig):
    sid = "0123456789ab"
    (rig.state / "shelf" / sid).mkdir(parents=True)
    (rig.state / "shelf" / sid / "item.json").write_text(json.dumps({"id": sid, "name": "Cap", "file": "cap.stl", "added": 1}))
    phone = await paired_phone(rig)
    r = await rig.away.post("/bench/queue", json={"shelf": sid, "copies": 1, "material": "PLA"}, headers=bearer(phone))
    it = await r.json()
    assert r.status == 201 and it["away"] is True and it["by"] == "Alex's iPhone" and it["state"] == "waiting"
    # set up for a printer as it would be, waiting for the bed: still nothing from away starts it
    rig.bench.queue.items[0].update(state="ready", printer="workshop", job="j1")
    assert (await rig.away.post(f"/bench/queue/{it['id']}/start", json={"anyway": True}, headers=bearer(phone))).status == 403
    assert rig.bench.queue.items[0]["state"] == "ready" and rig.seen == []
    assert "post_start" in {getattr(r.handler, "__name__", "") for r in rig.home.app.router.routes()}
    assert all(getattr(r.handler, "__name__", "") != "post_start" for r in rig.away.app.router.routes())


async def test_removing_a_guest_closes_their_connection_at_once_and_presence_is_counted(rig):
    token, me = await guest(rig, name="Jo")
    ws = await socket_of(rig, token)
    ws2 = await socket_of(rig, token, "/screens/workshop/websocket")
    listed = await (await rig.home.get("/bench/phones")).json()
    jo = next(g for g in listed["guests"] if g["name"] == "Jo")
    assert jo["watching"] == 2 and jo["reach"] == "watch" and jo["invited_by"] == "Alex's iPhone"
    assert listed["watching"] == ["Jo"] and [p["name"] for p in listed["phones"]] == ["Alex's iPhone"]
    assert (await (await rig.home.get("/bench/watching")).json()) == {"watching": ["Jo"]}
    assert (await rig.home.delete(f"/bench/phones/{jo['id']}")).status == 204
    for sock in (ws, ws2):
        assert (await sock.receive(timeout=3)).type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
    assert (await (await rig.home.get("/bench/watching")).json()) == {"watching": []}
    assert (await rig.away.get("/bench/printers", headers=bearer(token))).status == 401


async def test_a_printers_own_screens_open_through_the_box(rig):
    page = await (await rig.away.get("/screens/workshop/")).text()                          # its app's own files: open to anyone
    assert '<head><script>window.__ELYIR_BENCH_BASE__="/screens/workshop"</script><title>Printer</title>' in page
    assert await (await rig.away.get("/assets/index-abc.js")).text() == "printer()"
    assert "bench" in await (await rig.away.get("/join")).text()                      # the Bench app's own pages
    assert "bench" in await (await rig.away.get("/p/workshop")).text()                   # its route for an opened printer, too
    # its settings name no printer: it talks to whoever served it, here the box
    assert (await (await rig.away.get("/screens/workshop/config.json")).json())["moonraker"] == {"host": "", "port": 7125}
    assert (await rig.away.get("/config.json")).status == 404 and (await rig.away.get("/screens/workshop/nope.js")).status == 404
    assert not (await (await rig.away.get("/screens/workshop/door/me")).json())["paired"]
    watch, _ = await guest(rig, "watch")
    me = await (await rig.away.get("/screens/workshop/door/me", headers=bearer(watch))).json()
    assert me["role"] == "away" and me["actions"] == [] and me["printer"] == {"id": "workshop", "name": "Workshop"}
    frames = await (await rig.away.get("/screens/workshop/door/frames", headers={"X-Forwarded-Host": "bench.elyir.app",
                                                                        "X-Forwarded-Proto": "https"})).json()
    assert frames == {"frames": ["https://bench.elyir.app"]}
    cam = await rig.away.get("/screens/workshop/webcam/?action=snapshot", headers=bearer(watch))
    assert cam.status == 200 and await cam.read() == b"JPEG"
    assert (await rig.away.get("/screens/workshop/webcam/?action=snapshot")).status == 401
    ws = await socket_of(rig, watch, "/screens/workshop/websocket")
    assert (await call(ws, "printer.intent.action", {"action": "cancel"}))["error"]["code"] == 403
    await ws.close()


async def test_a_page_on_another_site_cant_act_with_a_phones_cookie(rig):
    phone = await paired_phone(rig)
    r = await rig.away.post("/door/invites", json={}, headers={**bearer(phone), "Origin": "https://evil.example"})
    assert r.status == 403


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_the_box_claims_its_own_name_and_caddy_serves_it_in_front_of_the_away_listener(tmp_path, aiohttp_server, aiohttp_client):
    from test_doors import FakeProc, fake_relay
    app, seen = fake_relay(taken=("hillside-box",), suggest="hillside-bench")
    relay = await aiohttp_server(app)
    started = []

    async def spawn(*argv, **kw):
        p = FakeProc(list(argv))
        started.append(p)
        return p
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("#!/bin/sh\n")
        os.chmod(bins / n, 0o755)
    port = free_port()
    doors = DR.Doors(tmp_path / "b", str(relay.make_url("")), bins, spawn=spawn)
    bench = B.Bench(tmp_path / "b", "Bench Box", [], scanner=lambda: [], doors=doors, away_port=port, slicer="http://127.0.0.1:9",
                    box_name="hillside-box")
    home = await aiohttp_client(bench.app())
    assert (await (await home.get("/bench/box/remote")).json())["on"] is False     # remote off: nothing opens by itself
    r = await home.post("/bench/box/remote", json={})
    got = await r.json()
    assert r.status == 200 and got["on"] and got["address"] == "hillside-bench.elyir.app" and got["open"]
    assert [c["name"] for c in seen["claims"]] == ["hillside-box", "hillside-bench"]
    caddy = (tmp_path / "b" / "doors" / "Caddyfile").read_text()
    assert "hillside-bench.elyir.app:9444" in caddy and f"reverse_proxy 127.0.0.1:{port}" in caddy
    frpc = tmp_path / "b" / "box" / "frpc.toml"
    assert 'customDomains = ["hillside-bench.elyir.app"]' in frpc.read_text() and stat.S_IMODE(os.stat(frpc).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "b" / "box" / "relay.json").st_mode) == 0o600
    code = await (await home.post("/bench/phones/code")).json()
    assert code["url"].startswith("https://hillside-bench.elyir.app/pair#")
    # the away listener is up, on loopback only
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.close()
    assert (await (await home.delete("/bench/box/remote")).json()) == {"on": False}
    assert not bench.doors.is_open(DR.BOX) and not (await (await home.get("/bench/box/remote")).json())["on"]
    await doors.close()


SHELL = "https://printers.elyir.app"


async def test_the_printers_app_looks_at_a_model_on_the_bench_with_a_phones_token(rig):
    """design/bench-look/, C: How would it print? from the Printers app, through the box's public name."""
    phone = await paired_phone(rig)
    h = {**bearer(phone), "Origin": SHELL}
    pre = await rig.away.options("/bench/look", headers={"Origin": SHELL, "Access-Control-Request-Method": "POST"})
    assert pre.status == 204 and "Authorization" in pre.headers["Access-Control-Allow-Headers"]
    assert (await rig.away.options("/bench/look", headers={"Origin": "https://evil.example"})).status == 403
    got = await rig.away.get("/bench/intents", headers=h)
    assert got.status == 200 and got.headers["Access-Control-Allow-Origin"] == SHELL and "workshop" in await got.json()
    # sent to look at: the box takes it (its slicer is off in this rig, which it says), not refused at the door
    r = await rig.away.post("/bench/look", data={"model": ("cap.stl", b"solid c\nendsolid c\n")}, headers=h)
    assert r.status not in (401, 403), await r.text()
    # a model looked at stays off the shelf until it's kept
    sid = "0123456789ab"
    (rig.state / "shelf" / sid).mkdir(parents=True)
    (rig.state / "shelf" / sid / "item.json").write_text(json.dumps({"id": sid, "name": "Cap", "file": "cap.stl", "added": rig.clock.t, "look": True}))
    assert await (await rig.away.get("/bench/shelf", headers=h)).json() == []
    kept = await (await rig.away.put(f"/bench/shelf/{sid}/keep", headers=h)).json()
    assert kept["look"] is False and [s["id"] for s in await (await rig.away.get("/bench/shelf", headers=h)).json()] == [sid]
    # still nothing that sends or starts
    assert (await rig.away.post("/bench/slice/abcdefabcdef/send", headers=h)).status == 403


async def test_guests_and_strangers_cant_send_models_to_look_at(rig):
    token, _ = await guest(rig)
    for method, path in (("POST", "/bench/look"), ("PUT", "/bench/shelf/0123456789ab/keep"), ("GET", "/bench/intents"),
                         ("POST", "/bench/shelf/0123456789ab/slice"), ("GET", "/bench/slice/abcdefabcdef/layers")):
        assert (await rig.away.request(method, path, headers={**bearer(token), "Origin": SHELL})).status == 403, path
        assert (await rig.away.request(method, path)).status == 401, path


async def test_a_model_only_looked_at_is_let_go_after_a_day(rig):
    for sid, look in (("aaaaaaaaaaaa", True), ("bbbbbbbbbbbb", False)):
        (rig.state / "shelf" / sid).mkdir(parents=True)
        (rig.state / "shelf" / sid / "item.json").write_text(json.dumps({"id": sid, "name": "x", "file": "x.stl", "added": rig.clock.t, "look": look}))
    rig.clock.t += DAY + 1
    rig.bench.shelf.drop_old_looks()
    assert sorted(p.name for p in (rig.state / "shelf").iterdir()) == ["bbbbbbbbbbbb"]
