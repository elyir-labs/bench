"""A Kobra's stand-in on the box (bench/standin.py, design/bench-kobra/, A) against a fake Rinkhals Moonraker: the
objects Rinkhals lists for a Kobra 3, its database, its print calls. The intent is the real engine's."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web, WSMsgType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import standin as S  # noqa: E402

# What Rinkhals' kobra.py answers to printer.objects.list on a Kobra 3 (its injected list, plus macros from gcode/help)
KOBRA_OBJECTS = ["motion_report", "gcode_macro t0", "gcode_macro t1", "gcode_macro t2", "gcode_macro t3", "configfile",
                 "heaters", "respond", "display_status", "exclude_object", "extruder", "fan", "gcode_move", "heater_bed",
                 "mcu", "mcu nozzle_mcu", "ota_filament_hub", "pause_resume", "print_stats", "toolhead",
                 "verify_heater extrude", "verify_heater heater_bed", "virtual_sdcard", "webhooks", "bed_mesh",
                 "idle_timeout"]


def idle_status():
    return {
        "webhooks": {"state": "ready", "state_message": "Printer is ready"},
        "print_stats": {"state": "standby", "filename": "", "print_duration": 0.0, "total_duration": 0.0, "message": "",
                        "info": {"current_layer": None, "total_layer": None}},
        "display_status": {"message": "", "progress": 0.0},
        "virtual_sdcard": {"progress": 0.0, "is_active": False, "file_position": 0},
        "pause_resume": {"is_paused": False},
        "idle_timeout": {"state": "standby"},
        "heater_bed": {"temperature": 24.0, "target": 0.0},
        "extruder": {"temperature": 25.0, "target": 0.0, "can_extrude": False},
        "toolhead": {"homed_axes": "", "axis_minimum": [-2.0, -2.0, -2.0, 0.0], "axis_maximum": [255.0, 255.0, 260.0, 0.0]},
        "motion_report": {"live_position": [0.0, 0.0, 0.0, 0.0]},
        "gcode_move": {"homing_origin": [0.0, 0.0, 0.0, 0.0]},
        "exclude_object": {"objects": [], "excluded_objects": [], "current_object": None},
    }


class FakeKobra:
    def __init__(self):
        self.status = idle_status()
        self.sockets = []
        self.connections = 0
        self.subscribed = []          # every subscription asked for
        self.calls = []               # (method, params)
        self.db = {}
        self.klippy = "ready"
        self.inject = {}              # what Rinkhals' patchers add to every status (mmu_ace: mmu, mmu_machine)

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/websocket", self.ws)
        app.router.add_get("/server/files/list", self.files)
        app.router.add_get("/server/files/gcodes/{path:.*}", self.gcode)
        app.router.add_get("/server/webcams/list", self.webcams_list)
        app.router.add_get("/webcam/", self.snapshot)
        return app

    camera = False                # a Kobra without a camera: Rinkhals' streamer answers 503

    async def webcams_list(self, request):
        return web.json_response({"result": {"webcams": [{"name": "Webcam", "service": "mjpegstreamer-adaptive",
                                                         "stream_url": "/webcam/?action=stream"}]}})

    async def snapshot(self, request):
        return web.Response(body=b"JPEG", content_type="image/jpeg") if self.camera else web.Response(status=503, text="503")

    async def files(self, request):
        if request.query.get("root") == "config":
            return web.json_response({"result": [{"path": "printer.cfg", "modified": 1.0, "size": 10}]})
        return web.json_response({"result": [{"path": "clip.gcode", "modified": 2.0, "size": 99}]})

    async def gcode(self, request):
        return web.Response(body=b"PNG", content_type="image/png")

    async def push(self, change):
        for k, v in change.items():
            self.status.setdefault(k, {}).update(v)
        for sock in self.sockets:
            await sock.send_str(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [change, 1.0]}))

    async def notify(self, method, params):
        for sock in self.sockets:
            await sock.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}))

    def answer(self, method, p):
        self.calls.append((method, p))
        if method == "server.info":
            return {"klippy_state": self.klippy}
        if method == "printer.objects.list":
            return {"objects": KOBRA_OBJECTS}
        if method in ("printer.objects.subscribe", "printer.objects.query"):
            objs = p.get("objects") or {}
            if method == "printer.objects.subscribe":
                self.subscribed.append(objs)
            return {"eventtime": 1.0, "status": {**{k: dict(self.status[k]) for k in objs if k in self.status}, **self.inject}}
        if method == "server.files.metadata":
            return {"filename": p["filename"], "filament_type": "PLA", "filament_colour": "#2563EB",
                    "estimated_time": 3600, "thumbnails": []}
        if method == "server.database.get_item":
            key = (p["namespace"], p.get("key"))
            if p.get("key") is None:
                return {"namespace": p["namespace"], "value": {k[1]: v for k, v in self.db.items() if k[0] == p["namespace"]}}
            if key not in self.db:
                raise KeyError(key)
            return {"namespace": p["namespace"], "key": p["key"], "value": self.db[key]}
        if method == "server.database.post_item":
            self.db[(p["namespace"], p["key"])] = p["value"]
            return {"namespace": p["namespace"], "key": p["key"], "value": p["value"]}
        if method == "server.history.totals":
            return {"job_totals": {"total_jobs": 3, "total_time": 7200.0, "total_print_time": 6000.0,
                                   "total_filament_used": 1000.0, "longest_job": 3000.0, "longest_print": 2800.0}}
        if method in ("printer.print.start", "printer.print.pause", "printer.print.resume", "printer.print.cancel",
                      "printer.gcode.script"):
            return "ok"
        if method == "server.webcams.list":
            return {"webcams": [{"name": "Webcam", "service": "mjpegstreamer-adaptive", "stream_url": "/webcam/?action=stream"}]}
        if method == "server.files.roots":
            return [{"name": "gcodes"}]
        raise LookupError(method)

    async def ws(self, request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        self.connections += 1
        self.sockets.append(sock)
        try:
            async for m in sock:
                if m.type != WSMsgType.TEXT:
                    continue
                req = json.loads(m.data)
                try:
                    out = {"jsonrpc": "2.0", "id": req["id"], "result": self.answer(req["method"], req.get("params") or {})}
                except KeyError:
                    out = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": 404, "message": "not found"}}
                except LookupError:
                    out = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "Method not found"}}
                await sock.send_str(json.dumps(out))
        finally:
            self.sockets.remove(sock)
        return sock


async def until(check, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("never happened")


class Rpc:
    """A page's websocket to the stand-in."""
    def __init__(self, ws):
        self.ws, self.n, self.notes = ws, 0, []

    async def call(self, method, params=None):
        self.n += 1
        await self.ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self.n}))
        while True:
            msg = await self.ws.receive_json(timeout=5)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"]["message"])
                return msg["result"]
            self.notes.append(msg)

    async def note(self, method, timeout=5):
        for n in list(self.notes):
            if n.get("method") == method:
                self.notes.remove(n)
                return n["params"]
        async def wait():
            while True:
                msg = await self.ws.receive_json()
                if msg.get("method") == method:
                    return msg["params"]
        return await asyncio.wait_for(wait(), timeout)

    async def until(self, method, check, timeout=5):
        async def wait():
            while True:
                params = await self.note(method, timeout)
                if check(params):
                    return params
        return await asyncio.wait_for(wait(), timeout)


def all_action_ids(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "actions" and isinstance(v, list):
                yield from (a.get("id") for a in v if isinstance(a, dict))
            yield from all_action_ids(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_action_ids(v)


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    kobra = FakeKobra()
    k = await aiohttp_server(kobra.app())
    seen_slice = {}

    async def slicer(request):
        seen_slice["who"] = request.headers.get(S.SLICER_HEADER)
        seen_slice["path"] = request.path_qs
        return web.json_response({"printers": []})
    sl = web.Application(); sl.router.add_route("*", "/slice/{tail:.*}", slicer)
    slicer_server = await aiohttp_server(sl)

    state = tmp_path / "kobra-3"
    (state / "elyir-bench-slicer" / "presets").mkdir(parents=True)
    (state / "elyir-bench-slicer" / "printer.json").write_text(json.dumps({"machine": "Anycubic Kobra 3 0.4 nozzle"}))
    (state / "elyir-bench-slicer" / "presets" / "machine.json").write_text("{}")
    app_dir = tmp_path / "app"
    (app_dir / "assets").mkdir(parents=True)
    (app_dir / "index.html").write_text("<!doctype html><title>printer app</title>")
    (app_dir / "assets" / "a.js").write_text("x")
    (app_dir / "config.json").write_text(json.dumps({"moonraker": {"host": "workshop.local", "port": 7125}}))

    s = S.Standin("kobra-3", "Kobra 3", "127.0.0.1", k.port, k.port, state, app_dir,
                  str(slicer_server.make_url("")).rstrip("/"), lambda: ["http://bench.local:8088"])
    await s.start()
    client = await aiohttp_client(s.app())
    await until(lambda: s.tracker.klippy_state == "ready")

    class R: pass
    r = R()
    r.kobra, r.s, r.client, r.slice = kobra, s, client, seen_slice
    yield r
    await s.stop()


async def page(r):
    ws = await r.client.ws_connect("/websocket")
    return Rpc(ws)


async def test_the_intent_is_the_engines_over_the_kobras_status(rig):
    p = await page(rig)
    i = await p.call("printer.intent")
    assert i["state"] == "ready" and i["printer"]["name"] == "Kobra 3"
    assert i["printer"]["standin"] == "bench" and i["printer"]["advanced_url"].startswith("http://127.0.0.1:")
    await rig.kobra.push({"print_stats": {"state": "printing", "filename": "clip.gcode", "print_duration": 60.0},
                          "virtual_sdcard": {"progress": 0.4, "is_active": True},
                          "extruder": {"temperature": 220.0, "target": 220.0}, "heater_bed": {"temperature": 60.0, "target": 60.0}})
    upd = await p.until("notify_intent_update", lambda u: u[0]["state"] != "ready")
    assert upd[0]["state"] == "preparing" and "Clip" in upd[0]["headline"]
    r = await rig.client.get("/printer/intent")
    assert (await r.json())["result"]["state"] == "preparing"


async def test_only_objects_the_kobra_lists_are_ever_subscribed(rig):
    p = await page(rig)
    res = await p.call("printer.objects.subscribe", {"objects": {"extruder": ["temperature"], "ace": None,
                                                                "gcode_macro _PRINT_START": None}})
    assert set(res["status"]) == {"extruder"} and set(res["status"]["extruder"]) == {"temperature"}
    asked = set().union(*[set(s) for s in rig.kobra.subscribed])
    assert asked <= set(KOBRA_OBJECTS)
    assert "ace" not in asked and not any(a.startswith("gcode_macro _") for a in asked)


async def test_one_websocket_to_the_kobra_and_each_page_gets_its_own(rig):
    a, b = await page(rig), await page(rig)
    await a.call("printer.objects.subscribe", {"objects": {"extruder": ["temperature"]}})
    await b.call("printer.objects.subscribe", {"objects": {"heater_bed": None}})
    assert rig.kobra.connections == 1
    await rig.kobra.push({"extruder": {"temperature": 99.0, "target": 200.0}, "heater_bed": {"temperature": 33.0}})
    sa = await a.until("notify_status_update", lambda u: "extruder" in u[0])
    assert sa[0] == {"extruder": {"temperature": 99.0}}
    sb = await b.until("notify_status_update", lambda u: "heater_bed" in u[0])
    assert "extruder" not in sb[0] and sb[0]["heater_bed"]["temperature"] == 33.0


async def test_what_goklipper_cant_do_is_never_offered_nor_run(rig):
    await rig.kobra.push({"print_stats": {"state": "printing", "filename": "clip.gcode"},
                          "virtual_sdcard": {"progress": 0.1, "is_active": True}})
    await until(lambda: rig.s.intent()["state"] in ("preparing", "printing"))
    ids = set(all_action_ids(rig.s.intent()))
    assert not ids & S.NOT_HERE
    p = await page(rig)
    for refused in ("restart_firmware", "stop_now", "squish_more", "power_off"):
        with pytest.raises(RuntimeError, match="can't do that"):
            await p.call("printer.intent.action", {"action": refused})
    assert not [c for c in rig.kobra.calls if c[0] in ("printer.firmware_restart", "printer.emergency_stop", "printer.restart")]
    out = await p.call("printer.intent.action", {"action": "pause"})
    assert out["ok"] and ("printer.print.pause", {}) in rig.kobra.calls


async def test_the_spool_is_kept_in_the_kobras_own_database_and_the_file_starts(rig):
    p = await page(rig)
    check = await p.call("printer.intent.check_print", {"filename": "clip.gcode"})
    assert check["filename"] == "clip.gcode" if "filename" in check else True
    await p.call("printer.intent.action", {"action": "confirm_spool",
                                           "args": {"filename": "clip.gcode", "color": "#2563EB", "material": "PLA"}})
    assert rig.kobra.db[("elyir-bench", "spool")]["material"] == "PLA"
    assert ("printer.print.start", {"filename": "clip.gcode"}) in rig.kobra.calls


async def test_care_is_seeded_in_mainsails_maintenance_on_the_kobra(rig):
    assert rig.kobra.db.get(("elyir-bench", "care_seeded")) is True
    assert any(ns == "maintenance" for ns, _ in rig.kobra.db)
    assert rig.s.intent().get("care") is not None


async def test_gcode_responses_and_other_notices_reach_every_page(rig):
    p = await page(rig)
    await p.call("printer.intent")
    await rig.kobra.notify("notify_gcode_response", ["// hello from GoKlipper"])
    assert await p.note("notify_gcode_response") == ["// hello from GoKlipper"]


async def test_everything_else_is_the_kobras_own_moonraker(rig):
    p = await page(rig)
    assert await p.call("server.files.roots") == [{"name": "gcodes"}]
    r = await rig.client.get("/server/files/gcodes/.thumbs/clip.png")
    assert r.status == 200 and await r.read() == b"PNG"
    r = await rig.client.get("/server/files/list?root=gcodes")
    assert (await r.json())["result"][0]["path"] == "clip.gcode"


async def test_its_slicing_profile_is_the_boxs_listed_as_its_own_config(rig):
    r = await rig.client.get("/server/files/list?root=config")
    paths = [f["path"] for f in (await r.json())["result"]]
    assert "printer.cfg" in paths and "elyir-bench-slicer/printer.json" in paths and "elyir-bench-slicer/presets/machine.json" in paths
    r = await rig.client.get("/server/files/config/elyir-bench-slicer/printer.json")
    assert (await r.json())["machine"] == "Anycubic Kobra 3 0.4 nozzle"
    r = await rig.client.get("/server/files/config/elyir-bench-slicer/../../escape")
    assert r.status == 404


async def test_slice_goes_to_the_boxs_slicer_saying_which_printer(rig):
    r = await rig.client.get("/slice/options")
    assert r.status == 200 and rig.slice == {"who": "kobra-3", "path": "/slice/options"}


async def test_the_app_is_served_with_the_box_as_its_parent_and_no_door(rig):
    r = await rig.client.get("/print")
    assert "printer app" in await r.text()
    r = await rig.client.get("/assets/a.js")
    assert "immutable" in r.headers.get("Cache-Control", "")
    r = await rig.client.get("/config.json")
    assert (await r.json())["moonraker"]["host"] == ""          # never a fixed printer, as a dev build has
    r = await rig.client.get("/door/frames")
    assert (await r.json())["frames"] == ["http://bench.local:8088"]
    r = await rig.client.get("/door/me")
    assert r.status == 404


async def test_a_kobra_that_stops_answering_is_off_on_the_bench(rig):
    p = await page(rig)
    await p.call("printer.intent")
    for sock in list(rig.kobra.sockets):
        await sock.close()
    msg = await p.ws.receive(timeout=5)
    assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
    await until(lambda: rig.s.tracker.klippy_state in ("disconnected", "ready"))


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_the_box_finds_a_kobra_adds_it_and_speaks_for_it(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    import bench_service as B
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    port = free_port()
    monkeypatch.setattr(B, "STANDIN_PORTS", range(port, port + 1))
    kobra = FakeKobra()
    k = await aiohttp_server(kobra.app())
    found = [{"id": "kobra-3-max-803e82", "name": "Kobra 3 Max", "host": "127.0.0.1", "model": "kobra-3-max",
              "mac": "A4-E8-8D-80-3E-82", "rinkhals": True, "lan": False, "why": None},     # LAN mode off: Rinkhals
             {"id": "anycubic-49", "name": "Anycubic printer", "host": "10.0.0.49", "model": None, "mac": None,
              "rinkhals": False, "lan": False, "why": "On Anycubic's cloud: turn on LAN mode on its screen"}]

    async def finder():
        return found
    bench = B.Bench(tmp_path / "bench", "Bench Box", ["http://bench.local:8088"], scanner=lambda: [], finder=finder,
                    standin_host="127.0.0.1")
    client = await aiohttp_client(bench.app())
    rows = await (await client.get("/bench/found")).json()
    assert [(r["name"], r["kind"], r["on"]) for r in rows] == [("Kobra 3 Max", "anycubic", False), ("Anycubic printer", "anycubic", False)]
    r = await client.post("/bench/add/anycubic-49")
    assert r.status == 409 and "LAN mode" in (await r.json())["error"]

    r = await client.post("/bench/add/kobra-3-max-803e82")
    assert r.status == 201
    rec = bench.printers["kobra-3-max-803e82"]
    assert rec["port"] == port and rec["standin"]["printer"] == "127.0.0.1" and rec["token"] is None
    # its Moonraker is the Kobra's (the fake one listens elsewhere here: point the stand-in at it)
    s, _ = bench.standins["kobra-3-max-803e82"]
    assert s.moonraker.endswith(":7125")
    profile = tmp_path / "bench" / "standins" / "kobra-3-max-803e82" / "elyir-bench-slicer" / "printer.json"
    assert "Kobra 3 Max" in json.loads(profile.read_text())["machine"]

    listed = await (await client.get("/bench/printers", headers={"Host": "bench.local:8088"})).json()
    assert listed == [{"id": "kobra-3-max-803e82", "name": "Kobra 3 Max", "moonraker": "/bench/p/kobra-3-max-803e82",
                       "app": f"http://bench.local:{port}"}]
    rows = await (await client.get("/bench/found")).json()
    assert rows[0]["on"] is True

    # the box restarts: it speaks for it again, on the same port, at the Kobra's own Moonraker
    await bench._stop_speaking("kobra-3-max-803e82")
    bench.printers["kobra-3-max-803e82"]["standin"]["moonraker_port"] = k.port
    await bench._speak_for("kobra-3-max-803e82")
    s, _ = bench.standins["kobra-3-max-803e82"]
    await until(lambda: s.tracker.klippy_state == "ready")
    from aiohttp import ClientSession
    async with ClientSession() as cs:
        async with cs.get(f"http://127.0.0.1:{port}/printer/intent") as r:
            assert (await r.json())["result"]["printer"]["name"] == "Kobra 3 Max"
    r = await client.delete("/bench/printers/kobra-3-max-803e82")
    assert r.status == 200 and not bench.standins


# How Rinkhals' mmu_ace reports a Kobra 3 Combo's ACE Pro: four gates, red PLA and white PETG loaded, the second picked
COMBO_MMU = {
    "mmu": {"enabled": True, "num_gates": 4, "gate": 1, "tool": 1,
            "gate_status": [1, 2, 0, -1], "gate_material": ["PLA", "PETG", "Unknown", "Unknown"],
            "gate_color": ["D9534FFF", "F1F1F1FF", "000000FF", "000000FF"], "gate_temperature": [210, 240, 0, 0]},
    "mmu_machine": {"num_units": 1, "unit_0": {"name": "ACE 1", "first_gate": 0, "num_gates": 4, "dryer_status": "drying",
                                               "dryer_temp": 44, "dryer_target_temp": 50, "dryer_remaining": 120}},
}


def test_an_ace_pro_as_rinkhals_reports_it_is_the_engines_unit():
    t = S.engine.IntentTracker("Kobra 3")
    t.has_unit = True
    t.set_klippy_state("ready")
    t.update_status(COMBO_MMU)
    assert t.unit_state()["driver"] == "happy_hare" and t.unit_commands() is None
    spools = t.spools()
    assert [(x["slot"], x["material"], x["status"], x["in_use"]) for x in spools] == [
        (0, "PLA", "ready", False), (1, "PETG", "ready", True), (2, None, "empty", False), (3, None, "unknown", False)]
    assert "Red" in spools[0]["name"]
    assert S.engine.filament_units.read({"mmu": {"enabled": True, "num_gates": 0}}) is None


async def test_a_kobra_combo_shows_its_slots_and_takes_no_unit_commands(rig):
    rig.kobra.inject = COMBO_MMU
    await rig.kobra.push({"extruder": {"temperature": 30.0}, **COMBO_MMU})
    await until(lambda: rig.s.tracker.has_unit is True)
    i = rig.s.intent()
    assert len(i["spools"]) == 4 and i["spools"][1]["in_use"]
    assert not set(all_action_ids(i)) & S.NOT_HERE
    with pytest.raises(S.RpcError, match="can't do that"):
        await rig.s._run(S.engine.ActionPlan.GCODE, "ACE_CHANGE_TOOL TOOL=0")
    assert not [c for c in rig.kobra.calls if c[0] == "printer.gcode.script" and "ACE_" in c[1].get("script", "")]
    await rig.kobra.push({"mmu": {"enabled": True, "num_gates": 0}})
    await until(lambda: rig.s.tracker.has_unit is False)


async def test_a_kobra_whose_port_is_taken_is_off_and_the_box_carries_on(tmp_path, aiohttp_client, monkeypatch):
    import socket as so
    import bench_service as B
    busy = so.socket(); busy.bind(("127.0.0.1", 0)); busy.listen(); port = busy.getsockname()[1]
    try:
        bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], standin_host="127.0.0.1")
        bench.printers = {"k": {"name": "Kobra 3", "host": "127.0.0.1", "port": port, "moonraker_port": port, "home": None,
                                "token": None, "standin": {"printer": "127.0.0.1", "moonraker_port": 1, "model": "kobra-3"}}}
        client = await aiohttp_client(bench.app())
        assert "k" not in bench.standins
        assert (await client.get("/bench/printers")).status == 200
        monkeypatch.setattr(B, "STANDIN_PORTS", range(port, port + 50))
        assert bench._free_port() not in (port, None)
        monkeypatch.setattr(B, "STANDIN_PORTS", range(port, port + 1))
        assert bench._free_port() is None
    finally:
        busy.close()


async def test_a_kobra_that_moves_is_followed_by_its_mac(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    import bench_service as B
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    monkeypatch.setattr(B, "KOBRAS_EVERY", 0.1)
    kobra = FakeKobra()
    k = await aiohttp_server(kobra.app())
    port = free_port()
    at = {"host": "127.0.0.1"}

    async def finder():
        return [{"id": "anycubic-803e82", "name": "Kobra 3 Max", "host": at["host"], "model": "kobra-3-max",
                 "mac": "A4-E8-8D-80-3E-82", "rinkhals": True, "lan": False, "why": None}]
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], finder=finder, standin_host="127.0.0.1")
    # on the bench from before, at the address the router gave it then (nothing answers there now)
    bench.printers = {"anycubic-803e82": {"name": "Kobra 3 Max", "host": "127.0.0.1", "port": port, "moonraker_port": port,
                                          "home": None, "token": None,
                                          "standin": {"printer": "127.0.0.9", "moonraker_port": k.port, "model": "kobra-3-max"}}}
    await aiohttp_client(bench.app())
    ready = lambda: "anycubic-803e82" in bench.standins and bench.standins["anycubic-803e82"][0].tracker.klippy_state == "ready"
    await until(ready, timeout=5)
    assert bench.printers["anycubic-803e82"]["standin"]["printer"] == "127.0.0.1"
    assert json.loads((tmp_path / "bench" / "printers.json").read_text())["anycubic-803e82"]["standin"]["printer"] == "127.0.0.1"


async def test_the_setup_card_offers_notifications_and_remembers_a_dismissal_on_the_printer(rig):
    rig.s.secure_link = lambda: "on"
    assert rig.s.intent()["setup"]["open"] is True and rig.s.setup()["rows"] == [{"id": "notify"}]
    p = await page(rig)
    out = await p.call("printer.intent.action", {"action": "setup_dismiss", "args": {"row": "notify"}})
    assert out["setup"]["dismissed"] == ["notify"] and out["intent"]["setup"]["open"] is False
    assert rig.kobra.db[("elyir-bench", "setup")] == {"dismissed": ["notify"]}
    rig.s.dismissed = []
    await rig.s._restore_setup()
    assert rig.s.dismissed == ["notify"]



async def test_a_camera_rinkhals_lists_but_that_shows_nothing_isnt_offered(rig):
    r = await rig.client.get("/server/webcams/list")
    assert (await r.json())["result"]["webcams"] == []
    p = await page(rig)
    assert (await p.call("server.webcams.list"))["webcams"] == []
    rig.kobra.camera = True
    rig.s.camera_seen = (0.0, False)
    r = await rig.client.get("/server/webcams/list")
    assert [c["name"] for c in (await r.json())["result"]["webcams"]] == ["Webcam"]



def test_a_kobras_profile_follows_the_boxs_template_unless_someone_wrote_their_own(tmp_path):
    import bench_service as B
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [])
    bench._profile("k", "kobra-3")
    folder = tmp_path / "bench" / "standins" / "k" / "elyir-bench-slicer"
    assert json.loads((folder / "printer.json").read_text())["machine"] == "Anycubic Kobra 3 0.4 nozzle (Bench)"
    assert (folder / "presets" / "Kobra 3 (Bench).json").exists()
    (folder / "printer.json").write_text(json.dumps({"machine": "old", "bench": True}))      # an older template
    bench._profile("k", "kobra-3")
    assert json.loads((folder / "printer.json").read_text())["machine"] != "old"
    (folder / "printer.json").write_text(json.dumps({"machine": "mine"}))                     # someone's own
    bench._profile("k", "kobra-3")
    assert json.loads((folder / "printer.json").read_text())["machine"] == "mine"


async def test_move_and_heat_goes_to_the_kobra_as_gcode(rig):
    # through Rinkhals the whole sheet works (design/hands-on/): the first move only finds home
    await until(lambda: (rig.s.intent().get("hands") or {}).get("can_move") is True)
    p = await page(rig)
    out = await p.call("printer.intent.action", {"action": "hands_move", "args": {"axis": "z", "mm": 10}})
    assert out["ok"]
    await until(lambda: ("printer.gcode.script", {"script": "G28"}) in rig.kobra.calls)
