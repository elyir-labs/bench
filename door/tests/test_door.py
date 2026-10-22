"""The door, against a fake Moonraker and a fake app server: who gets in, what passes, what is sent."""
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aiohttp import ClientSession, WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import door as D  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeMoonraker:
    def __init__(self):
        self.calls: list[dict] = []
        self.boot, self.events = "b1", []
        self.db: dict = {}
        self.sockets: list[web.WebSocketResponse] = []
        self.announced: list[dict] = []
        self.thumb_queries: list[str] = []

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/websocket", self.ws)
        async def thumb(r):
            self.thumb_queries.append(r.query_string)
            return web.Response(body=b"PNG", content_type="image/png")
        app.router.add_get("/server/files/gcodes/.thumbs/benchy-300x300.png", thumb)
        return app

    async def notify(self, method: str, *params):
        for s in self.sockets:
            await s.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": list(params)}))

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            self.calls.append(m)
            p = m.get("params") or {}
            if m["method"] == "printer.intent.events":
                if p.get("boot", self.boot) != self.boot:
                    result = {"boot": self.boot, "events": []}
                else:
                    result = {"boot": self.boot, "events": [e for e in self.events if e["id"] > p.get("after", 0)]}
            elif m["method"] == "connection.send_event":
                self.announced.append(p)
                result = "ok"
            elif m["method"] == "server.database.post_item":
                self.db[(p["namespace"], p["key"])] = p["value"]
                result = {"value": p["value"]}
            else:
                result = {"echo": m["method"]}
            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}))
        self.sockets.remove(ws)
        return ws


def fake_app() -> web.Application:
    app = web.Application()
    async def page(r): return web.Response(text=f"app:{r.path}", content_type="text/html")
    async def slicer(r):   # nginx sends /slice to the slicing service
        body = await r.read()
        return web.json_response({"slicer": r.method, "path": r.path, "bytes": len(body)}, status=201 if r.method == "POST" else 200)
    app.router.add_route("*", "/slice", slicer)
    app.router.add_route("*", "/slice/{tail:.*}", slicer)
    app.router.add_get("/{tail:.*}", page)
    return app


class Clock:
    def __init__(self, t: float):
        self.t = t
    def __call__(self):
        return self.t


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client):
    moon = FakeMoonraker()
    ms = await aiohttp_server(moon.app())
    apps = await aiohttp_server(fake_app())
    sent: list[tuple] = []
    status = {"code": 201}

    def sender(sub, data, headers, ttl, key=None):
        sent.append((sub["endpoint"], json.loads(data), headers, ttl, key))
        return status["code"]

    clock = Clock(datetime(2026, 10, 2, 12, 0, tzinfo=ZoneInfo("America/Chicago")).timestamp())
    door = D.Door(tmp_path / "door", str(ms.make_url("")), str(apps.make_url("")), str(ms.make_url("/webcam")),
                  "workshop.elyir.app", now=clock, sender=sender, home_address="192-0-2-73.workshop.home.elyir.app",
                  printer_name="Workshop")
    door.session = ClientSession()
    away = await aiohttp_client(door.away_app())
    local = await aiohttp_client(door.local_app())
    home = await aiohttp_client(door.house_app())

    class R: pass
    r = R()
    r.door, r.moon, r.away, r.home, r.sent, r.status, r.clock = door, moon, away, home, sent, status, clock
    r.local = local
    yield r
    await door.session.close()


async def paired(r, name="Sam's iPhone") -> dict:
    code = (await (await r.home.post("/door/pair/new")).json())["code"]
    resp = await r.away.post("/door/pair", json={"code": code, "name": name})
    assert resp.status == 200
    token = resp.cookies[D.COOKIE].value
    return {"Cookie": f"{D.COOKIE}={token}"}


# ── who gets in ──────────────────────────────────────────────────────────────

async def test_a_stranger_gets_the_app_and_nothing_else(rig):
    me = await (await rig.away.get("/door/me")).json()
    assert me["paired"] is False and me["away"] is True
    assert await (await rig.away.get("/pair")).text() == "app:/pair"
    for path in ("/websocket", "/server/files/gcodes/.thumbs/benchy-300x300.png", "/webcam/?action=snapshot",
                 "/door/push/key", "/printer/info", "/machine/system_info"):
        assert (await rig.away.get(path)).status == 401, path


async def test_a_code_pairs_once_and_wrong_codes_are_counted(rig):
    code = (await (await rig.home.post("/door/pair/new")).json())["code"]
    assert len(code) == 8
    r = await rig.away.post("/door/pair", json={"code": code.lower(), "name": "  Sam's   phone "})
    assert r.status == 200 and (await r.json())["phone"]["name"] == "Sam's phone"
    assert (await rig.away.post("/door/pair", json={"code": code})).status == 401, "a code works once"
    for _ in range(4):
        await rig.away.post("/door/pair", json={"code": "WRONGONE"})
    r = await rig.away.post("/door/pair", json={"code": "WRONGONE"})
    assert r.status == 429


async def test_a_code_runs_out(rig):
    code = (await (await rig.home.post("/door/pair/new")).json())["code"]
    rig.clock.t += D.CODE_LIFE + 1
    assert (await rig.away.post("/door/pair", json={"code": code})).status == 401


async def test_pairing_needs_a_public_name(rig):
    rig.door.address = None
    assert (await rig.home.post("/door/pair/new")).status == 409


async def test_a_removed_phone_is_a_stranger_at_once(rig):
    h = await paired(rig)
    assert (await (await rig.away.get("/door/me", headers=h)).json())["paired"]
    pid = (await (await rig.home.get("/door/phones")).json())["phones"][0]["id"]
    assert (await rig.home.delete(f"/door/phones/{pid}")).status == 204
    assert not (await (await rig.away.get("/door/me", headers=h)).json())["paired"]


async def test_a_phone_takes_itself_off_from_away(rig):
    h = await paired(rig)
    other = await paired(rig)
    assert (await rig.away.delete("/door/me", headers=h)).status == 204
    assert not (await (await rig.away.get("/door/me", headers=h)).json())["paired"]
    assert (await (await rig.away.get("/door/me", headers=other)).json())["paired"]


async def test_a_stranger_cannot_take_anyone_off(rig):
    await paired(rig)
    assert (await rig.away.delete("/door/me")).status == 401
    assert len((await (await rig.home.get("/door/phones")).json())["phones"]) == 1


async def test_another_site_cannot_act_with_the_cookie(rig):
    h = await paired(rig)
    evil = {**h, "Origin": "https://evil.example"}
    assert (await rig.away.post("/door/push/subscribe", headers=evil, json={})).status == 403
    own = {**h, "Origin": f"http://{rig.away.host}:{rig.away.port}"}
    assert (await rig.away.post("/door/push/subscribe", headers=own, json={})).status == 400   # past the origin check


# ── what passes ──────────────────────────────────────────────────────────────

async def test_a_paired_phone_sees_thumbnails_but_not_other_files(rig):
    h = await paired(rig)
    r = await rig.away.get("/server/files/gcodes/.thumbs/benchy-300x300.png", headers=h)
    assert r.status == 200 and await r.read() == b"PNG"
    assert (await rig.away.get("/server/files/gcodes/benchy.gcode", headers=h)).status == 403
    assert (await rig.away.post("/printer/print/start", headers=h)).status == 403


async def test_the_websocket_passes_watching_and_refuses_the_rest(rig):
    h = await paired(rig)
    ws = await rig.away.ws_connect("/websocket", headers=h)

    async def call(i, method, params=None):
        await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}))
        return json.loads((await ws.receive()).data)

    assert (await call(1, "printer.intent"))["result"] == {"echo": "printer.intent"}
    assert (await call(2, "printer.intent.action", {"action": "pause"}))["result"]["echo"] == "printer.intent.action"
    refused = await call(3, "printer.intent.action", {"action": "start_file", "args": {"filename": "x.gcode"}})
    assert refused["error"]["code"] == 403 and "at the printer" in refused["error"]["message"]
    assert (await call(4, "printer.gcode.script", {"script": "M104 S250"}))["error"]["code"] == 403
    assert (await call(5, "server.database.get_item", {"namespace": "elyir-bench", "key": "phones"}))["result"]
    assert (await call(6, "server.database.get_item", {"namespace": "moonraker"}))["error"]["code"] == 403
    assert (await call(7, "machine.reboot"))["error"]["code"] == 403
    sent = [c["method"] for c in rig.moon.calls]
    assert "printer.gcode.script" not in sent and "machine.reboot" not in sent
    assert not any(c["method"] == "printer.intent.action" and c["params"]["action"] == "start_file" for c in rig.moon.calls)
    # The printer logs who pressed it: away, the door names the paired phone, whatever the app claimed
    pause = next(c for c in rig.moon.calls if c["method"] == "printer.intent.action")
    assert pause["params"]["source"].endswith(", away (paired phone)")

    await rig.moon.notify("notify_gcode_response", "ok")
    await rig.moon.notify("notify_intent_update", {"state": "printing"})
    msg = json.loads((await ws.receive()).data)
    assert msg["method"] == "notify_intent_update", "console output is not passed on"
    await ws.close()


def test_move_and_heat_is_home_only():
    # nothing moves or heats from a phone that can't see the printer (design/hands-on/, C); Cool down still can
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "printer"))
    import elyir_bench_intent as engine
    for action in engine.HANDS_OPS:
        assert D.allowed_call("printer.intent.action", {"action": action}) == "That has to be done at the printer."
    assert D.allowed_call("printer.intent.action", {"action": "cool_down"}) is None


def test_the_first_layer_is_home_only():
    # Further / Closer move the nozzle in a running print (design/first-layer/, 3 October 2026)
    for action in ("squish_less", "squish_more", "keep_first_layer", "just_this_once",
                   "first_layer_back", "first_layer_clear", "first_layer_keep_old", "keep_for_sheet",
                   "first_layer_sheet", "first_layer_forget"):
        assert D.allowed_call("printer.intent.action", {"action": action}) == "That has to be done at the printer."


def test_a_guest_who_only_watches_gets_no_actions_and_ends_on_time(tmp_path):
    # design/bench-remote/, C (9 October 2026): invited to watch, or to step in, for a while
    assert D.allowed_call("printer.objects.subscribe", {}, act=False) is None
    assert D.allowed_call("printer.intent.action", {"action": "pause"}, act=False) == "You can watch, not change anything."
    now = [1000.0]
    phones = D.Phones(tmp_path / "phones.json", lambda: now[0])
    g, token = phones.pair("Jo", "guest", guest={"reach": "watch", "until": 2000.0, "invited_by": "Alex"})
    assert phones.identify(token) is g and D.Phones.public(g)["reach"] == "watch"
    now[0] = 2000.0
    assert phones.identify(token) is None and phones.ended(g)


def test_a_colour_change_switch_is_allowed_away_once_confirmed_and_hands_stay_home():
    # design/colour-change/, A (3 October 2026): a switch may be started from a phone away, with an
    # extra confirmation; putting a spool in needs someone at the printer.
    act = lambda **args: D.allowed_call("printer.intent.action", {"action": "colour_choose", "args": args})
    assert act(slot=1, how="switch") == "Confirm the switch first."
    assert act(slot=1, how="switch", away_ok=True) is None
    assert act(slot=0, how="keep") is None
    assert act(slot=6, how="put_in", away_ok=True) == "That has to be done at the printer."
    assert act(slot=1, how="swap", away_ok=True) == "That has to be done at the printer."
    assert D.allowed_call("printer.intent.action", {"action": "colour_choose"}) == "That has to be done at the printer."
    for action in ("change_good", "change_more"):   # the check, on the camera
        assert D.allowed_call("printer.intent.action", {"action": action}) is None
    for action in ("change_in", "change_what", "print_planned"):
        assert D.allowed_call("printer.intent.action", {"action": action}) == "That has to be done at the printer."


# ── push ─────────────────────────────────────────────────────────────────────

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}


async def subscribed(rig, kinds=None, tz="America/Chicago", name="Sam's iPhone"):
    h = await paired(rig, name)
    r = await rig.away.post("/door/push/subscribe", headers=h, json={"subscription": {**SUB, "endpoint": SUB["endpoint"] + name[:3]}, "kinds": kinds, "tz": tz})
    assert r.status == 204
    return h


def ev(kind, urgency="normal", i=1, tag=None):
    return {"boot": "b1", "id": i, "kind": kind, "urgency": urgency, "title": f"Workshop {kind}", "body": "b",
            "tag": tag or f"workshop-{kind}", "url": "/", "printer": "Workshop", "job": None}


async def test_the_push_key_and_subscription_round_trip(rig):
    h = await subscribed(rig, kinds=["finished"])
    key = (await (await rig.away.get("/door/push/key", headers=h)).json())["publicKey"]
    assert len(key) == 87                    # 65 bytes, base64url without padding
    assert await (await rig.away.get("/door/push/me", headers=h)).json() == {"subscribed": True, "kinds": ["finished"]}
    assert (await rig.away.delete("/door/push/subscribe", headers=h)).status == 204
    assert (await (await rig.away.get("/door/push/me", headers=h)).json())["subscribed"] is False


async def test_no_kinds_means_every_kind_including_new_ones(rig):
    await subscribed(rig, kinds=None, name="All")
    await subscribed(rig, kinds=["finished"], name="Fin")
    assert await rig.door.push.send_event(ev("care_due", "normal")) == 1
    assert await rig.door.push.send_event(ev("finished")) == 2
    _, payload, headers, ttl, key = rig.sent[-1]
    assert payload == {"title": "Workshop finished", "body": "b", "tag": "workshop-finished", "url": "/", "urgency": "normal", "printer": "workshop"}
    assert key is None, "without a key of the phone's own, the printer signs with its own"
    assert headers == {"Urgency": "normal", "Topic": "workshop-finished"} and ttl == D.TTL["finished"]


async def test_low_waits_for_morning_and_high_never_waits(rig):
    await subscribed(rig)
    rig.clock.t = datetime(2026, 10, 2, 23, 30, tzinfo=ZoneInfo("America/Chicago")).timestamp()
    assert await rig.door.push.send_event(ev("care_due", "low", tag="workshop-care")) == 0
    assert await rig.door.push.send_event(ev("care_due", "low", tag="workshop-care")) == 0
    assert len(rig.door.push.held) == 1, "a newer alert with the same tag replaces the held one"
    assert await rig.door.push.send_event(ev("problem", "high")) == 1
    assert await rig.door.push.flush() == 0, "still night"
    rig.clock.t = datetime(2026, 10, 3, 8, 5, tzinfo=ZoneInfo("America/Chicago")).timestamp()
    assert await rig.door.push.flush() == 1
    assert rig.sent[-1][1]["tag"] == "workshop-care" and rig.door.push.held == []


async def test_a_held_alert_that_runs_out_is_dropped(rig):
    await subscribed(rig)
    rig.clock.t = datetime(2026, 10, 2, 21, 0, tzinfo=ZoneInfo("UTC")).timestamp()   # 16:00 Chicago: not quiet
    rig.door.push.phones.items[0]["push"]["tz"] = "Asia/Tokyo"                         # 06:00 in Tokyo: quiet
    e = ev("care_due", "low")
    e["ttl"] = 60
    await rig.door.push.send_event(e)
    rig.clock.t += 3 * 3600
    assert await rig.door.push.flush() == 0 and rig.door.push.held == []


async def test_a_subscription_the_browser_dropped_is_forgotten(rig):
    await subscribed(rig)
    rig.status["code"] = 410
    assert await rig.door.push.send_event(ev("finished")) == 0
    assert rig.door.phones.items[0]["push"] is None


# ── following the printer ────────────────────────────────────────────────────

async def wait_for(cond, timeout=3.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


async def test_the_follower_resyncs_without_replaying_and_then_sends(rig):
    await subscribed(rig)
    rig.moon.events = [ev("finished", i=100), ev("ready_to_lift", i=200)]
    rig.door.follower.cursor = {"boot": "old-boot", "id": 5}
    task = asyncio.create_task(rig.door.follower.run())
    await wait_for(lambda: rig.door.follower.cursor["boot"] == "b1")
    assert rig.door.follower.cursor["id"] == 200 and rig.sent == [], "a new boot replays nothing"
    await wait_for(lambda: rig.moon.db.get(("elyir-bench", "phones")) == 1)

    await rig.moon.notify("notify_elyir_bench_event", ev("problem", "high", i=300))
    await wait_for(lambda: len(rig.sent) == 1)
    await rig.moon.notify("notify_elyir_bench_event", ev("problem", "high", i=300))   # the same event twice
    await asyncio.sleep(0.2)
    assert len(rig.sent) == 1
    task.cancel()


async def test_the_follower_catches_up_within_a_boot(rig):
    await subscribed(rig)
    rig.moon.events = [ev("finished", i=100), ev("ready_to_lift", i=200)]
    rig.door.follower.cursor = {"boot": "b1", "id": 100}
    task = asyncio.create_task(rig.door.follower.run())
    await wait_for(lambda: len(rig.sent) == 1)
    assert rig.sent[0][1]["tag"] == "workshop-ready_to_lift"
    task.cancel()


async def test_the_phone_count_follows_subscriptions(rig):
    task = asyncio.create_task(rig.door.follower.run())
    await wait_for(lambda: rig.moon.db.get(("elyir-bench", "phones")) == 0)
    h = await subscribed(rig)
    await wait_for(lambda: rig.moon.db.get(("elyir-bench", "phones")) == 1)
    await rig.away.delete("/door/push/subscribe", headers=h)
    await wait_for(lambda: rig.moon.db.get(("elyir-bench", "phones")) == 0)
    task.cancel()


def test_quiet_hours_are_the_phones_own():
    t = datetime(2026, 10, 2, 23, 0, tzinfo=ZoneInfo("America/Chicago")).timestamp()
    assert D.quiet_now("America/Chicago", t)
    assert not D.quiet_now("Asia/Tokyo", t)             # 13:00 the next day there
    t2 = datetime(2026, 10, 2, 9, 0, tzinfo=ZoneInfo("Europe/London")).timestamp()
    assert not D.quiet_now("Europe/London", t2) and D.quiet_now("America/Chicago", t2)


async def test_the_real_sender_encrypts_and_signs(tmp_path, aiohttp_server):
    """pywebpush end to end against a stand-in push service: aes128gcm body, VAPID signature, our headers."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    seen = {}

    async def endpoint(request):
        from multidict import CIMultiDict
        seen.update(headers=CIMultiDict(request.headers), body=await request.read())
        return web.Response(status=201)
    app = web.Application()
    app.router.add_post("/push/abc", endpoint)
    srv = await aiohttp_server(app)

    browser = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(browser.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
    sub = {"endpoint": str(srv.make_url("/push/abc")), "keys": {"p256dh": p256dh, "auth": base64.urlsafe_b64encode(b"0123456789abcdef").rstrip(b"=").decode()}}
    phones = D.Phones(tmp_path / "phones.json")
    push = D.Push(tmp_path, phones, "https://workshop.elyir.app")
    status = await asyncio.get_running_loop().run_in_executor(
        None, push._webpush, sub, json.dumps({"title": "t"}), {"Urgency": "high", "Topic": "workshop-attention"}, 3600)
    assert status == 201
    h = seen["headers"]
    assert h["Content-Encoding"] == "aes128gcm" and h["TTL"] == "3600"
    assert h["Urgency"] == "high" and h["Topic"] == "workshop-attention"
    assert h["Authorization"].startswith("vapid t=") and f"k={push.public_key}" in h["Authorization"]
    assert len(seen["body"]) > 80 and b"title" not in seen["body"], "the payload is encrypted"


def test_the_push_subject_is_one_py_vapid_accepts():
    from py_vapid import Vapid02
    v = Vapid02(); v.generate_keys()
    for address in ("workshop.elyir.app", "localhost:8089", "printer.example.net:8443", "192.0.2.40", None, ""):
        sub = D.vapid_subject(address)
        v.sign({"sub": sub, "aud": "https://push.example"})       # raises if py_vapid refuses it
    assert D.vapid_subject("workshop.elyir.app:443") == "https://workshop.elyir.app"
    assert D.vapid_subject("localhost:8089").startswith("mailto:")



# ── one app for every printer, and home before away ──────────────────────────

SHELL = "https://printers.elyir.app"


async def bearer(rig, via="away", name="Shell phone") -> tuple[dict, dict]:
    code = (await (await rig.home.post("/door/pair/new")).json())
    assert code["shell_url"] == f"{SHELL}/add#p=workshop.elyir.app&c={code['code']}"
    client = rig.away if via == "away" else rig.local
    r = await client.post("/door/pair", json={"code": code["code"], "name": name}, headers={"Origin": SHELL})
    assert r.status == 200 and r.headers["Access-Control-Allow-Origin"] == SHELL
    body = await r.json()
    return {"Authorization": f"Bearer {body['token']}", "Origin": SHELL}, body


async def test_the_shell_pairs_and_learns_both_addresses(rig):
    h, body = await bearer(rig)
    assert body["printer"] == {"id": "workshop", "name": "Workshop"}
    assert body["addresses"] == {"away": "https://workshop.elyir.app", "home": "https://192-0-2-73.workshop.home.elyir.app"}
    me = await (await rig.away.get("/door/me", headers=h)).json()
    assert me["paired"] and me["role"] == "away" and "pause" in me["actions"]
    me = await (await rig.local.get("/door/me", headers=h)).json()
    assert me["paired"] and me["role"] == "home" and me["actions"] is None


async def test_the_shell_may_ask_first_and_frame_the_printer(rig):
    r = await rig.away.options("/door/me", headers={"Origin": SHELL, "Access-Control-Request-Method": "GET",
                                                    "Access-Control-Request-Headers": "authorization",
                                                    "Access-Control-Request-Private-Network": "true"})
    assert r.status == 204
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]
    assert r.headers["Access-Control-Allow-Private-Network"] == "true"
    assert (await rig.away.options("/door/me", headers={"Origin": "https://evil.example"})).status == 403
    page = await rig.away.get("/")
    assert f"frame-ancestors 'self'" in page.headers["Content-Security-Policy"] and SHELL in page.headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in page.headers, "only the shell is told it may read"


async def test_a_token_works_in_a_header_a_subprotocol_and_for_images_only_in_the_query(rig):
    h, body = await bearer(rig)
    tok = body["token"]
    assert (await rig.away.get("/door/push/key", headers={"Authorization": f"Bearer {tok}"})).status == 200
    assert (await rig.away.get(f"/server/files/gcodes/.thumbs/benchy-300x300.png?access_token={tok}")).status == 200
    assert (await rig.away.get(f"/door/push/key?access_token={tok}")).status == 401, "the query is for images only"
    ws = await rig.away.ws_connect("/websocket", protocols=("elyir-bench", f"elyir-bench-token.{tok}"), headers={"Origin": SHELL})
    assert ws.protocol == "elyir-bench"
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "printer.intent"}))
    assert json.loads((await ws.receive()).data)["result"] == {"echo": "printer.intent"}
    await ws.close()


async def test_at_home_a_paired_phone_is_as_good_as_the_panel(rig):
    h, _ = await bearer(rig, via="home")
    ws = await rig.local.ws_connect("/websocket", headers=h)
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "printer.gcode.script", "params": {"script": "G28"}}))
    assert json.loads((await ws.receive()).data)["result"] == {"echo": "printer.gcode.script"}
    await rig.moon.notify("notify_gcode_response", "ok")
    assert json.loads((await ws.receive()).data)["method"] == "notify_gcode_response", "everything passes at home"
    await ws.close()
    phones = await rig.local.get("/door/phones", headers=h)
    assert phones.status == 200 and len((await phones.json())["phones"]) == 1
    # a stranger on the home name gets no more than one away does
    assert (await rig.local.get("/printer/info")).status == 401
    assert (await rig.local.get("/door/phones")).status == 401


async def test_at_home_a_paired_phone_prints_a_model_and_away_it_cant_yet(rig):
    """Print a model (design/plate/): uploading and slicing are POSTs to /slice, through nginx."""
    h, _ = await bearer(rig, via="home")
    form = aiohttp.FormData()
    form.add_field("model", b"solid x\nendsolid x\n", filename="bushing.stl")
    up = await rig.local.post("/slice/models", data=form, headers=h)
    assert up.status == 201 and (await up.json())["slicer"] == "POST" and (await up.json())["bytes"] > 0
    r = await rig.local.post("/slice", json={"parts": []}, headers=h)
    assert r.status == 201 and (await r.json())["path"] == "/slice"
    assert (await rig.local.get("/slice/options", headers=h)).status == 200
    assert (await rig.local.post("/slice/models", data=b"x")).status == 401, "a stranger at home can't"
    h2, _ = await bearer(rig)
    away = await rig.away.post("/slice", json={"parts": []}, headers=h2)
    assert away.status == 403 and "away" in (await away.json())["error"]
    assert (await rig.away.get("/slice/options")).status == 401, "nor a stranger away"


async def test_away_the_same_token_gets_the_short_list(rig):
    h, _ = await bearer(rig)
    ws = await rig.away.ws_connect("/websocket", headers=h)
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "printer.gcode.script", "params": {"script": "G28"}}))
    assert json.loads((await ws.receive()).data)["error"]["code"] == 403
    await ws.close()
    assert (await rig.away.get("/door/phones", headers=h)).status == 403


async def test_the_home_name_is_read_fresh(rig, tmp_path):
    rig.door._home_address = None
    rig.door.home_file.write_text(json.dumps({"name": "192-0-2-99.workshop.home.elyir.app"}))
    me = await (await rig.away.get("/door/me")).json()
    assert me["addresses"]["home"] == "https://192-0-2-99.workshop.home.elyir.app"
    rig.door.home_file.write_text(json.dumps({"name": "192-0-2-12.workshop.home.elyir.app"}))
    assert (await (await rig.away.get("/door/me")).json())["addresses"]["home"].startswith("https://192-0-2-12.")


def phone_key() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    d = k.private_numbers().private_value.to_bytes(32, "big")
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"privateKey": D.b64u(d), "publicKey": D.b64u(pub)}


async def test_one_subscription_signed_with_the_phones_own_key(rig):
    h, body = await bearer(rig)
    key = phone_key()
    r = await rig.away.post("/door/push/subscribe", headers=h, json={"subscription": SUB, "tz": "America/Chicago", "vapid": key})
    assert r.status == 204
    await rig.door.push.send_event(ev("finished"))
    assert rig.sent[-1][4] == key["privateKey"] and rig.sent[-1][1]["printer"] == "workshop"
    wrong = {**phone_key(), "publicKey": key["publicKey"]}
    assert (await rig.away.post("/door/push/subscribe", headers=h, json={"subscription": SUB, "vapid": wrong})).status == 400
    # a new key replaces the old one, and removing the phone takes the key with it
    newer = phone_key()
    await rig.away.post("/door/push/subscribe", headers=h, json={"subscription": SUB, "vapid": newer})
    assert rig.door.phones.items[0]["push"]["vapid"]["publicKey"] == newer["publicKey"]
    assert (await rig.home.delete(f"/door/phones/{body['phone']['id']}")).status == 204
    assert newer["privateKey"] not in (rig.door.state / "phones.json").read_text()


async def test_the_real_sender_signs_with_the_phones_key(tmp_path, aiohttp_server):
    from multidict import CIMultiDict
    seen = {}

    async def endpoint(request):
        seen["headers"] = CIMultiDict(request.headers)
        return web.Response(status=201)
    app = web.Application()
    app.router.add_post("/push/x", endpoint)
    srv = await aiohttp_server(app)
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    browser = ec.generate_private_key(ec.SECP256R1())
    p256dh = D.b64u(browser.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    sub = {"endpoint": str(srv.make_url("/push/x")), "keys": {"p256dh": p256dh, "auth": D.b64u(b"0123456789abcdef")}}
    push = D.Push(tmp_path, D.Phones(tmp_path / "phones.json"), "https://workshop.elyir.app")
    key = phone_key()
    status = await asyncio.get_running_loop().run_in_executor(None, push._webpush, sub, "{}", {"Urgency": "normal"}, 60, key["privateKey"])
    assert status == 201 and f"k={key['publicKey']}" in seen["headers"]["Authorization"]
    assert push.public_key not in seen["headers"]["Authorization"]


async def test_the_token_in_an_image_address_never_reaches_moonraker(rig):
    # Moonraker reads access_token as its own login: it would refuse the image and log the token.
    _, body = await bearer(rig, via="home")
    r = await rig.local.get(f"/server/files/gcodes/.thumbs/benchy-300x300.png?access_token={body['token']}&t=5")
    assert r.status == 200 and await r.read() == b"PNG"
    assert rig.moon.thumb_queries[-1] == "t=5"
    _, body = await bearer(rig, name="Away phone")
    r = await rig.away.get(f"/server/files/gcodes/.thumbs/benchy-300x300.png?access_token={body['token']}")
    assert r.status == 200 and "access_token" not in rig.moon.thumb_queries[-1]



# ── asking to connect, instead of typing a code ──────────────────────────────

async def test_a_device_at_home_asks_and_the_panel_lets_it_in(rig):
    r = await rig.local.post("/door/ask", json={"name": "Sam's Mac", "kind": "computer"}, headers={"Origin": SHELL})
    assert r.status == 201
    handle = (await r.json())["handle"]
    assert (await (await rig.local.get(f"/door/ask/{handle}")).json())["state"] == "waiting"
    asks = (await (await rig.home.get("/door/asks")).json())["asks"]
    assert [a["name"] for a in asks] == ["Sam's Mac"] and "handle" not in asks[0], "the panel never sees the handle"
    assert (await rig.home.post(f"/door/asks/{asks[0]['id']}/allow")).status == 200
    got = await (await rig.local.get(f"/door/ask/{handle}")).json()
    assert got["state"] == "allowed" and got["token"] and got["addresses"]["home"].startswith("https://192-0-2-73.")
    again = await (await rig.local.get(f"/door/ask/{handle}")).json()
    assert "token" not in again, "the token is handed over once"
    me = await (await rig.local.get("/door/me", headers={"Authorization": f"Bearer {got['token']}"})).json()
    assert me["paired"] and me["phone"]["name"] == "Sam's Mac"


async def test_asking_is_only_from_the_printers_wifi(rig):
    r = await rig.away.post("/door/ask", json={"name": "Stranger"})
    assert r.status == 403 and (await r.json())["detail"] == "at-home"
    assert (await (await rig.home.get("/door/asks")).json())["asks"] == []


async def test_a_paired_phone_at_home_can_answer_and_one_away_cannot(rig):
    await subscribed(rig)                                    # a paired phone with notifications on
    handle = (await (await rig.local.post("/door/ask", json={"name": "iPad", "kind": "tablet"})).json())["handle"]
    await asyncio.sleep(0.05)
    assert rig.sent[-1][1]["title"] == "iPad wants to connect to Workshop"
    assert rig.sent[-1][1]["body"] == "Allow it at home or on the printer's screen." and rig.sent[-1][2]["Urgency"] == "high"
    phone_h, _ = await bearer(rig, name="Sam's iPhone")
    # away: told where, shown nothing, able to do nothing
    for method, path in (("GET", "/door/asks"), ("POST", "/door/asks/x/allow"), ("POST", "/door/asks/x/refuse")):
        r = await rig.away.request(method, path, headers=phone_h)
        assert r.status == 403 and (await r.json())["detail"] == "at-home", path
    # at home: the same phone sees it and answers
    asks = (await (await rig.local.get("/door/asks", headers=phone_h)).json())["asks"]
    assert (await rig.local.post(f"/door/asks/{asks[0]['id']}/refuse", headers=phone_h)).status == 200
    assert (await (await rig.local.get(f"/door/ask/{handle}")).json())["state"] == "refused"
    assert (await rig.local.get("/door/asks")).status == 401, "a stranger at home cannot see or answer asks"


async def test_asks_run_out_and_do_not_pile_up(rig):
    first = (await (await rig.local.post("/door/ask", json={"name": "A"})).json())["handle"]
    second = (await (await rig.local.post("/door/ask", json={"name": "A again"})).json())["handle"]
    asks = (await (await rig.home.get("/door/asks")).json())["asks"]
    assert [a["name"] for a in asks] == ["A again"], "asking again from the same address replaces the first"
    assert (await rig.local.get(f"/door/ask/{first}")).status == 404
    rig.clock.t += D.ASK_LIFE + 1
    assert (await (await rig.local.get(f"/door/ask/{second}")).json())["state"] == "expired"
    assert (await (await rig.home.get("/door/asks")).json())["asks"] == []
    assert (await rig.home.post("/door/asks/nope/allow")).status == 404


async def test_the_panel_hears_an_ask_at_once(rig):
    task = asyncio.create_task(rig.door.follower.run())
    await wait_for(lambda: rig.door.follower.ws is not None and rig.moon.db.get(("elyir-bench", "phones")) is not None)
    assert any(c["method"] == "server.connection.identify" and c["params"]["type"] == "agent" for c in rig.moon.calls)
    await rig.local.post("/door/ask", json={"name": "Mac"})
    await wait_for(lambda: rig.moon.announced)
    assert rig.moon.announced[-1]["event"] == "elyir_bench_asks" and rig.moon.announced[-1]["data"]["asks"][0]["name"] == "Mac"
    task.cancel()


async def test_away_hears_only_the_doors_own_agent_events(rig):
    h, _ = await bearer(rig)
    ws = await rig.away.ws_connect("/websocket", headers=h)
    await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "printer.intent"}))
    await ws.receive(timeout=3)                              # the door's own connection upstream is up
    await rig.moon.notify("notify_agent_event", {"agent": "spoolman-sync", "event": "x", "data": {"secret": 1}})
    await rig.moon.notify("notify_agent_event", {"agent": "elyir-bench-door", "event": "elyir_bench_asks", "data": {"asks": []}})
    msg = json.loads((await ws.receive(timeout=3)).data)
    assert msg["params"][0]["agent"] == "elyir-bench-door"
    await ws.close()



async def test_the_library_can_be_browsed_from_away_but_not_changed(rig):
    h, _ = await bearer(rig)
    ws = await rig.away.ws_connect("/websocket", headers=h)
    async def call(i, method, params=None):
        await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}))
        return json.loads((await ws.receive(timeout=3)).data)
    assert (await call(1, "server.files.list", {"root": "gcodes"}))["result"] == {"echo": "server.files.list"}
    assert (await call(2, "server.files.get_directory", {"path": "gcodes"}))["result"] == {"echo": "server.files.get_directory"}
    for i, m in enumerate(("server.files.delete_file", "server.files.move", "server.files.delete_directory"), 3):
        assert (await call(i, m, {"path": "gcodes/x.gcode"}))["error"]["code"] == 403, m
    await ws.close()


# ── a Bench Box asks, and is trusted from where its screen is (design/bench-box/, docs/bench.md) ──

BENCH = ["http://bench.local:8088", "http://192.0.2.40:8088", "http://localhost:8088"]


async def test_a_bench_box_asks_with_its_addresses_and_is_trusted_from_them_once_allowed(rig):
    r = await rig.local.post("/door/ask", json={"name": "Bench Box", "kind": "bench", "origins": BENCH})
    assert r.status == 201
    handle = (await r.json())["handle"]
    asks = (await (await rig.home.get("/door/asks")).json())["asks"]
    assert [(a["name"], a["kind"]) for a in asks] == [("Bench Box", "bench")]
    # not trusted before the yes: no CORS, no framing, no acting from its page
    pre = await rig.local.options("/door/me", headers={"Origin": BENCH[0], "Access-Control-Request-Method": "GET"})
    assert pre.status == 403
    assert (await rig.home.post(f"/door/asks/{asks[0]['id']}/allow")).status == 200
    token = (await (await rig.local.get(f"/door/ask/{handle}")).json())["token"]
    h = {"Authorization": f"Bearer {token}", "Origin": BENCH[0]}
    me = await rig.local.get("/door/me", headers=h)
    body = await me.json()
    assert body["paired"] and body["phone"]["kind"] == "bench"
    assert me.headers["Access-Control-Allow-Origin"] == BENCH[0]
    assert set(BENCH) <= set(body["frames"]) and "http://bench.local:8088" in me.headers["Content-Security-Policy"]
    pre = await rig.local.options("/door/me", headers={"Origin": BENCH[1], "Access-Control-Request-Method": "PUT"})
    assert pre.status == 204 and "PUT" in pre.headers["Access-Control-Allow-Methods"]


async def test_a_bench_box_keeps_its_addresses_current_and_nothing_else_can(rig):
    handle = (await (await rig.local.post("/door/ask", json={"name": "Bench Box", "kind": "bench", "origins": BENCH[:1]})).json())["handle"]
    ask = (await (await rig.home.get("/door/asks")).json())["asks"][0]
    await rig.home.post(f"/door/asks/{ask['id']}/allow")
    token = (await (await rig.local.get(f"/door/ask/{handle}")).json())["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = await rig.local.put("/door/me/origins", json={"origins": ["http://bench.local:8088", "http://192.0.2.41:8088"]}, headers=h)
    assert r.status == 200
    assert "http://192.0.2.41:8088" in (await (await rig.local.get("/door/me")).json())["frames"]
    assert (await rig.local.put("/door/me/origins", json={"origins": ["javascript:alert(1)"]}, headers=h)).status == 400
    phone_h, _ = await bearer(rig, via="home")                 # a phone has no addresses to keep
    assert (await rig.local.put("/door/me/origins", json={"origins": BENCH}, headers=phone_h)).status == 403
    # removing the box from Phones takes its addresses with it
    box = next(p for p in rig.door.phones.items if p.get("kind") == "bench")
    rig.door.phones.remove(box["id"])
    assert "http://bench.local:8088" not in (await (await rig.local.get("/door/me")).json())["frames"]


async def test_a_bench_box_must_say_where_its_screen_is(rig):
    r = await rig.local.post("/door/ask", json={"name": "Bench Box", "kind": "bench"})
    assert r.status == 400 and (await r.json())["detail"] == "origins"
    r = await rig.local.post("/door/ask", json={"name": "Bench Box", "kind": "bench", "origins": ["ftp://x"]})
    assert r.status == 400


async def test_the_printers_own_screen_learns_which_bench_boxes_may_frame_it(rig):
    # nginx /door/ on the printer's port is the house listener: the frames a Bench Box needs, at their own route;
    # /door/me there must stay missing, or the printer's own app would think it has to pair
    assert (await rig.home.get("/door/me")).status == 404
    got = await (await rig.home.get("/door/frames")).json()
    assert "https://printers.elyir.app" in got["frames"]
    assert "https://printers.elyir.app" in (await (await rig.local.get("/door/frames")).json())["frames"]
    handle = (await (await rig.local.post("/door/ask", json={"name": "Bench Box", "kind": "bench", "origins": BENCH[:1]})).json())["handle"]
    ask = (await (await rig.home.get("/door/asks")).json())["asks"][0]
    await rig.home.post(f"/door/asks/{ask['id']}/allow")
    assert BENCH[0] in (await (await rig.home.get("/door/frames")).json())["frames"]


# ── Bench Cloud (docs/cloud.md) ──────────────────────────────────────────────

async def test_a_phone_at_home_puts_the_printer_in_its_bench_cloud_house(rig, aiohttp_server, tmp_path):
    async def devices(request):
        body = await request.json()
        if body.get("join_token") != "j_good":
            return web.json_response({"error": "That join code has been used or has run out."}, status=403)
        return web.json_response({"device": "p_workshop", "device_token": "d_workshop", "house": "h_1", "name": "Workshop"})

    app = web.Application()
    app.router.add_post("/v1/devices", devices)
    cloud = await aiohttp_server(app)
    api = str(cloud.make_url("")).rstrip("/")
    phone = await paired(rig)
    assert (await rig.local.post("/door/cloud/join", json={"join_token": "j_good", "api": api})).status == 401
    bad = await rig.local.post("/door/cloud/join", json={"join_token": "j_bad", "api": api}, headers=phone)
    assert bad.status == 502 and (await bad.json())["message"] == "That join code has been used or has run out."
    assert (await rig.local.post("/door/cloud/join", json={"join_token": "j_good", "api": "http://evil.example"},
                                 headers=phone)).status == 400
    ok = await rig.local.post("/door/cloud/join", json={"join_token": "j_good", "api": api}, headers=phone)
    assert (await ok.json()) == {"joined": True, "name": "Workshop", "house": "h_1"}
    saved = tmp_path / "cloud.json"
    assert json.loads(saved.read_text())["token"] == "d_workshop" and (saved.stat().st_mode & 0o777) == 0o600
    status = await (await rig.local.get("/door/cloud", headers=phone)).json()
    assert status == {"joined": True, "name": "Workshop", "house": "h_1", "last": None}
    assert (await (await rig.home.get("/door/cloud")).json())["joined"] is True
    away = await rig.away.post("/door/cloud/join", json={"join_token": "j_good", "api": api}, headers=phone)
    assert away.status == 403 and (await away.json())["message"] == "Bench Cloud is turned on from your phone at home."
    assert (await (await rig.away.get("/door/cloud", headers=phone)).json())["joined"] is True


async def test_a_staging_printer_opens_and_allows_stagings_printers_app(tmp_path):
    door = D.Door(tmp_path / "door", "http://127.0.0.1:7125", "http://127.0.0.1:8088", "http://127.0.0.1/webcam", "studio.elyir.app",
                  printers_app="https://printers-staging.elyir.app/")
    assert {"https://printers-staging.elyir.app", "https://printers.elyir.app"} <= door.origins()
    app = door.house_app()
    from aiohttp.test_utils import TestClient, TestServer
    async with TestClient(TestServer(app)) as c:
        got = await (await c.post("/door/pair/new")).json()
        assert got["shell_url"].startswith("https://printers-staging.elyir.app/add#p=studio.elyir.app&c=")
        assert "https://printers-staging.elyir.app" in (await (await c.get("/door/frames")).json())["frames"]


def test_a_phone_is_remembered_by_the_name_it_came_in_on(tmp_path):
    phones = D.Phones(tmp_path / "phones.json", lambda: 1000.0)
    phone, _ = phones.pair("Sam's iPhone")
    phones.seen(phone, "voron.elyir.app")
    assert json.loads((tmp_path / "phones.json").read_text())[0]["via"] == "voron.elyir.app"   # a new name is written at once
    phones.seen(phone, "p-k7qx2mna.elyir.app")
    assert json.loads((tmp_path / "phones.json").read_text())[0]["via"] == "p-k7qx2mna.elyir.app"


async def test_the_panel_and_a_paired_phone_send_a_report_and_get_a_code(rig):
    calls = []

    async def fake(*args):
        calls.append(args)
        return (0, {"kind": "wrong", "files": ["logs/klippy.log"], "bundle_bytes": 2048}) if "--show" in args else (0, {"code": "R-7K2Q"})
    rig.door._report = fake
    r = await rig.home.get("/door/report?kind=wrong")
    assert r.status == 200 and (await r.json())["files"] == ["logs/klippy.log"]
    r = await rig.home.post("/door/report", json={"kind": "wrong", "context": {"headline": "The nozzle or bed isn't heating properly."}})
    assert r.status == 201 and (await r.json())["code"] == "R-7K2Q"
    assert "--context" in calls[-1] and "--no-details" not in calls[-1]
    assert (await rig.away.post("/door/report", json={"kind": "idea", "note": "x"})).status == 401     # not paired: refused
    phone = await paired(rig)
    r = await rig.away.post("/door/report", json={"kind": "idea", "note": "Show spool weights", "email": "sam@example.net"},
                            headers=phone)
    assert r.status == 201 and "--no-details" in calls[-1] and "Show spool weights" in calls[-1]
    assert (await rig.home.post("/door/report", json={"kind": "nonsense"})).status == 400


async def test_a_report_that_could_not_go_says_why(rig):
    async def fake(*args):
        return 1, {"error": "couldn't reach Elyir (timed out)"}
    rig.door._report = fake
    r = await rig.home.post("/door/report", json={"kind": "wrong"})
    assert r.status == 502 and "couldn't reach Elyir" in (await r.json())["message"]


async def test_the_report_command_is_read_whole_or_by_its_last_line(rig, monkeypatch):
    class Proc:
        returncode = 0
        def __init__(self, out): self.out = out
        async def communicate(self): return self.out, b""
    outs = [b'{\n "kind": "wrong",\n "files": ["logs/klippy.log"]\n}\n', b'gathering\n{"code": "R-7K2Q"}\n']

    async def spawn(*args, **kw):
        return Proc(outs.pop(0))
    monkeypatch.setattr(D.asyncio, "create_subprocess_exec", spawn)
    assert (await rig.door._report("--show")) == (0, {"kind": "wrong", "files": ["logs/klippy.log"]})
    assert (await rig.door._report("--kind", "wrong")) == (0, {"code": "R-7K2Q"})
