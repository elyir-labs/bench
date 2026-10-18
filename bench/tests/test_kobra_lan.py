"""A Kobra over Anycubic's LAN mode (bench/kobra_lan.py, design/kobra-lan/, B), against a fake printer: its handshake
encrypted as a real one's, and an MQTT stand-in replaying the reports a real Kobra 3 sent through a print on 6 October
2026 (fixtures/kobra3-lan-print.json). What the box says is the real engine's, through the stand-in."""
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kobra_lan as L  # noqa: E402
import standin as S  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "kobra3-lan-print.json").read_text())
TOKEN = "abcdefghijklmnopqrstuvwxyz012345"      # 32 characters, as the printer's
LOCAL = "1234567890abcdef"
MODEL, DEVICE = "20024", "d" * 32


def encrypt(obj: dict) -> str:
    pad = PKCS7(128).padder()
    raw = pad.update(json.dumps(obj).encode()) + pad.finalize()
    enc = Cipher(algorithms.AES(TOKEN[16:32].encode()), modes.CBC(LOCAL.encode())).encryptor()
    return base64.b64encode(enc.update(raw) + enc.finalize()).decode()


class Printer:
    """The HTTP side: /info, the signed /ctrl, and the upload."""
    def __init__(self, mode="lan"):
        self.mode, self.signed, self.uploads = mode, [], []

    def app(self):
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_get("/info", self.info)
        app.router.add_post("/ctrl", self.ctrl)
        app.router.add_post("/gcode_upload", self.upload)
        return app

    async def info(self, r):
        base = f"http://{r.host}"
        return web.json_response({"modelName": "Anycubic Kobra 3", "modelId": MODEL, "ctrlType": self.mode, "token": TOKEN,
                                  "ctrlInfoUrl": f"{base}/ctrl", "fileUploadurl": f"{base}/gcode_upload?s=up", "version": "2.4.6.7"})

    async def ctrl(self, r):
        q = r.query
        self.signed.append(q["sign"] == L.sign(TOKEN, int(q["ts"]), q["nonce"]))
        return web.json_response({"code": 200, "data": {"token": LOCAL, "info": encrypt(
            {"broker": "mqtts://127.0.0.1:9883", "username": "u", "password": "p", "deviceId": DEVICE, "devicecrt": "", "devicepk": ""})}})

    async def upload(self, r):
        assert r.query.get("s") == "up"
        form = await r.post()
        self.uploads.append((form["filename"], form["gcode"].file.read()))
        return web.json_response({"code": 200, "data": {"gcode": form["filename"]}})


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


class FakeMqtt:
    """paho's client as far as kobra_lan uses it; an info query is answered with the printer's current info."""
    made = []

    def __init__(self):
        self.published, self.info, self.on_connect, self.on_message = [], {"state": "free", "temp": {}}, None, None
        FakeMqtt.made.append(self)

    def username_pw_set(self, u, p): self.login = (u, p)
    def tls_set(self, *a, **k): self.tls = True
    def tls_insecure_set(self, on): pass
    def subscribe(self, topic): self.sub = topic
    def connect(self, host, port, keepalive=60): self.on_connect(self, None, None, 0)
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass

    def report(self, kind, data, state="done", action="report"):
        body = {"type": kind, "action": action, "state": state, "code": 200, "data": data}
        self.on_message(self, None, Msg(f"{L.PREFIX}/printer/public/{MODEL}/{DEVICE}/{kind}/report", json.dumps(body).encode()))

    mute = 0                # info queries left unanswered, as a real Kobra leaves one now and then

    def publish(self, topic, payload):
        msg = json.loads(payload)
        self.published.append((topic.rsplit("/", 1)[-1], topic.split("/")[3], msg["action"], msg["data"]))
        if msg["action"] == "query" and msg["type"] == "tempature" and "targets" in self.__dict__:
            self.report("tempature", {"curr_hotbed_temp": 79, "curr_nozzle_temp": 148, **self.targets}, action="query")
        if msg["action"] == "query" and msg["type"] == "info":
            if self.mute:
                self.mute -= 1
                return
            self.report("info", self.info)


async def until(check, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("never happened")


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    monkeypatch.setattr(L, "RECONNECT", 0.05)
    FakeMqtt.made = []
    printer = Printer()
    http = await aiohttp_server(printer.app())
    s = S.Standin("kobra-3", "Kobra 3", "127.0.0.1", 0, 0, tmp_path / "kobra-3", None, None, lambda: [],
                  via="lan", lan_mqtt=FakeMqtt, lan_port=http.port)
    s.up.poll = 0.05
    await s.start()
    client = await aiohttp_client(s.app())
    await until(lambda: s.up.up and s.tracker.klippy_state == "ready")

    class R: pass
    r = R()
    r.s, r.client, r.printer, r.mqtt, r.tmp = s, client, printer, FakeMqtt.made[-1], tmp_path
    yield r
    await s.stop()


def test_the_handshake_signs_as_anycubics_slicer_does():
    assert L.sign(TOKEN, 1791331648301, "aB3dE6") == hashlib.md5(
        (hashlib.md5(TOKEN[:16].encode()).hexdigest() + "1791331648301" + "aB3dE6").encode()).hexdigest()
    assert L.decrypt(encrypt({"broker": "mqtts://x:9883"}), TOKEN, LOCAL) == {"broker": "mqtts://x:9883"}


async def test_lan_mode_off_says_so(aiohttp_server):
    p = Printer(mode="cloud")
    http = await aiohttp_server(p.app())
    from aiohttp import ClientSession
    async with ClientSession() as s:
        with pytest.raises(L.RpcError, match="LAN mode is off"):
            await L.handshake(s, "127.0.0.1", http.port)


async def test_a_real_kobra_3_print_reads_on_the_box_as_it_happened(rig):
    """The recorded print, report by report: getting ready (warming, then the box's steps), printing from layer 1,
    the finish as Done; Done stays done once the bed is said clear, across the box's restart."""
    assert rig.printer.signed == [True] and rig.mqtt.login == ("u", "p") and rig.mqtt.sub.endswith(f"{MODEL}/{DEVICE}/#")
    said = []
    for rep in FIXTURE:
        if rep["topic"] == "info/report":
            rig.mqtt.info = rep["data"]
            rig.mqtt.report("info", rep["data"])
        else:
            rig.mqtt.report(rep["topic"].split("/")[0], rep["data"], state=rep["state"], action=rep["action"] or "report")
        await asyncio.sleep(0)
        i = rig.s.intent()
        now = next((x["id"] for x in i.get("steps") or [] if x["status"] == "now"), None)
        if not said or said[-1] != (i["state"], now):
            said.append((i["state"], now))
    assert said[0] == ("ready", None)
    assert ("preparing", "warming") in said
    assert said.index(("preparing", "warming")) < said.index(("printing", None)) < said.index(("finished", None))
    i = rig.s.intent()
    assert i["state"] == "finished" and i["headline"] == "Done."
    out = await rig.s.action("taken_off", {})
    assert out["intent"]["state"] == "ready"
    rig.mqtt.report("info", rig.mqtt.info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "standby")
    # the box restarts: the printer is still free with the same last job, and it isn't Done again
    assert L.status_from(rig.mqtt.info)["print_stats"]["state"] == "standby"
    assert rig.s.up.store.d["history"][0]["status"] == "completed"


def test_the_stages_lan_mode_names_are_the_engines_steps():
    st = L.status_from({"state": "busy", "project": {"state": "auto_leveling", "filename": "x.gcode", "pause": 0}})
    assert st["print_stats"]["state"] == "printing" and "leveling" in st["display_status"]["message"].lower()
    assert L.status_from({"state": "busy", "project": {"state": "paused", "pause": 1}})["print_stats"]["state"] == "paused"
    assert L.status_from({"state": "busy", "project": {"state": "stoped", "pause": 4}})["print_stats"]["state"] == "cancelled"
    free = {"state": "free", "last_project": {"state": "finished", "filename": "x.gcode", "print_time": 20, "total_layers": 9}}
    assert L.status_from(free)["print_stats"]["state"] == "standby"     # finished before the box saw it run


ORCA = """; HEADER_BLOCK_START
; generated by OrcaSlicer 2.4.2 on 2026-10-06 at 19:00:00
; total layer number: 62
; total filament weight [g] : 7.52
; estimated printing time (normal mode) = 20m 50s
; HEADER_BLOCK_END
; THUMBNAIL_BLOCK_START
; thumbnail begin 2x2 100
; """ + base64.b64encode(b"\\x89PNG fake").decode() + """
; thumbnail end
; THUMBNAIL_BLOCK_END
G28
G1 X10 Y10
; CONFIG_BLOCK_START
; filament_type = PETG
; filament_colour = #8A8D91
; nozzle_temperature_initial_layer = 230
; hot_plate_temp_initial_layer = 45
; layer_height = 0.2
; CONFIG_BLOCK_END
"""


async def test_a_file_the_box_sends_is_uploaded_read_and_started(rig):
    rig.mqtt.info = {"state": "free", "temp": {}}
    from aiohttp import FormData
    form = FormData()
    form.add_field("file", ORCA.encode(), filename="base_PETG_20m50s.gcode")
    form.add_field("print", "true")
    r = await rig.client.post("/server/files/upload", data=form)
    assert r.status == 201 and (await r.json())["print_started"] is True
    assert rig.printer.uploads[0][0] == "base_PETG_20m50s.gcode" and rig.printer.uploads[0][1] == ORCA.encode()
    start = [p for p in rig.mqtt.published if p[2] == "start"][-1]
    assert start[:3] == ("print", "slicer", "start") and start[3]["filename"] == "base_PETG_20m50s.gcode"
    assert start[3]["md5"] == hashlib.md5(ORCA.encode()).hexdigest() and start[3]["filesize"] == len(ORCA.encode())
    meta = await rig.s.up.call("server.files.metadata", {"filename": "base_PETG_20m50s.gcode"})
    assert (meta["estimated_time"], meta["filament_type"], meta["first_layer_extr_temp"], meta["layer_count"]) == (1250, "PETG", 230.0, 62)
    assert meta["filament_colors"] == ["#8A8D91"] and meta["thumbnails"][0]["relative_path"] == ".thumbs/base_PETG_20m50s-2x2.png"
    r = await rig.client.get("/server/files/gcodes/.thumbs/base_PETG_20m50s-2x2.png")
    assert r.status == 200
    check = await rig.s.check_print("base_PETG_20m50s.gcode")
    assert check["ask"] is True and "PETG" in check["headline"]      # one spool nobody described: it asks


async def test_commands_go_as_anycubics_slicer_sends_them_and_raw_gcode_doesnt(rig):
    rig.mqtt.info = {"state": "busy", "project": {"state": "printing", "filename": "x.gcode", "pause": 0, "curr_layer": 3}, "temp": {}}
    await until(lambda: rig.s.status.get("print_stats", {}).get("state") == "printing")
    for action, sent in (("pause", "pause"), ("resume", "resume"), ("cancel", "stop")):
        await rig.s.up.call(f"printer.print.{action}")
        assert rig.mqtt.published[-1] == ("print", "slicer", sent, {"taskid": "-1"})
    await rig.s.up.call("printer.gcode.script", {"script": "M140 S60\nM104 S200"})
    assert rig.mqtt.published[-1] == ("print", "web", "update", {"taskid": "-1", "settings": {"target_hotbed_temp": 60, "target_nozzle_temp": 200}})
    with pytest.raises(L.RpcError, match="LAN mode"):
        await rig.s.up.call("printer.gcode.script", {"script": "G28"})


async def test_what_a_moonraker_keeps_is_kept_on_the_box(rig):
    r = await rig.client.post("/server/database/item", json={"namespace": "elyir-bench", "key": "spool", "value": {"material": "PETG"}})
    assert r.status == 200
    r = await rig.client.get("/server/database/item?namespace=elyir-bench&key=spool")
    assert (await r.json())["result"]["value"] == {"material": "PETG"}
    assert (await rig.client.get("/server/webcams/list")).status == 200
    r = await rig.client.get("/server/files/list?root=config")
    assert (await r.json())["result"] == []                # no profile copied in this rig; never the printer's own config
    assert (await rig.client.get("/door/me")).status == 404
    assert rig.s.intent()["printer"]["advanced_url"] is None


async def test_the_box_adds_a_kobra_over_lan_mode_and_follows_its_switch_both_ways(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    import bench_service as B
    import socket as so
    monkeypatch.setattr(L, "RECONNECT", 0.05)
    monkeypatch.setattr(L.LanUpstream, "_client", lambda self: FakeMqtt())
    printer = Printer()
    http = await aiohttp_server(printer.app())
    with so.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    monkeypatch.setattr(B, "STANDIN_PORTS", range(port, port + 1))
    found = [{"id": "anycubic-0a6990", "name": "Kobra 3", "host": "127.0.0.1", "model": "kobra-3", "mac": "A4-E8-8D-0A-69-90",
              "rinkhals": False, "lan": True, "via": "lan", "why": None, "lan_port": http.port, "version": "2.4.6.7"}]

    async def finder():
        return found
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], finder=finder, standin_host="127.0.0.1")
    client = await aiohttp_client(bench.app())
    rows = await (await client.get("/bench/found")).json()
    assert rows[0]["why"] is None and rows[0]["via"] == "lan" and rows[0]["version"] == "2.4.6.7"
    assert (await client.post("/bench/add/anycubic-0a6990")).status == 201
    rec = bench.printers["anycubic-0a6990"]
    assert rec["standin"]["via"] == "lan"
    s, _ = bench.standins["anycubic-0a6990"]
    await until(lambda: s.up.up and s.tracker.klippy_state == "ready")
    assert s.lan and printer.signed == [True]
    # LAN mode turned off on one with Rinkhals: the box speaks for it through Rinkhals' Moonraker
    found[0].update(rinkhals=True, lan=False, via="moonraker")
    bench.anycubic_scanned = 0.0
    await bench._scan_anycubic()
    assert bench.printers["anycubic-0a6990"]["standin"]["via"] == "moonraker" and not bench.standins["anycubic-0a6990"][0].lan
    # and back on: LAN mode again, Rinkhals or not
    found[0].update(lan=True, via="lan")
    bench.anycubic_scanned = 0.0
    await bench._scan_anycubic()
    assert bench.printers["anycubic-0a6990"]["standin"]["via"] == "lan" and bench.standins["anycubic-0a6990"][0].lan
    await bench._stop_speaking("anycubic-0a6990")


async def test_lan_mode_is_preferred_to_rinkhals(aiohttp_server, monkeypatch):
    """Anycubic's own LAN mode when it's on; Rinkhals' Moonraker only when it's off (design/kobra-lan/)."""
    import anycubic as A
    from aiohttp import ClientSession
    mode = {"ctrlType": "lan"}

    async def info(r):
        return web.json_response({"modelName": "Anycubic Kobra 3", "modelId": MODEL, "usn": "uuid:fdm:A4-E8-8D-0A-69-90",
                                  "version": "2.4.6.7", **mode})

    async def system_info(r):
        return web.json_response({"result": {"system_info": {"network": {"wlan0": {"mac_address": "a4:e8:8d:0a:69:90"}}}}})
    app = web.Application()
    app.router.add_get("/info", info)
    app.router.add_get("/machine/system_info", system_info)
    http = await aiohttp_server(app)
    for port in ("ANYCUBIC_PORT", "LAN_PORT", "MOONRAKER_PORT"):     # one fake answers on all three: Rinkhals and LAN mode
        monkeypatch.setattr(A, port, http.port)
    async with ClientSession() as session:
        got = await A.look(session, "127.0.0.1")
        assert (got["via"], got["rinkhals"], got["lan"]) == ("lan", True, True)
        mode["ctrlType"] = "cloud"
        got = await A.look(session, "127.0.0.1")
        assert (got["via"], got["lan"]) == ("moonraker", False)


OLDER = {"state": "finished", "filename": "base_PETG_20m50s.gcode", "print_time": 20, "total_layers": 62, "curr_layer": 62, "progress": 100}


def running(layer, state="printing", **more):
    return {"state": "busy", "temp": {}, "last_project": OLDER,
            "project": {"state": state, "filename": "cube.gcode", "pause": 0, "curr_layer": layer, "total_layers": 72,
                        "print_time": 4, "remain_time": 9, "progress": 5, **more}}


async def test_a_stopped_print_ends_stopped_not_as_the_last_finished_one(rig):
    """A Kobra 3, 7 October 2026: after a stop, last_project still names yesterday's finished print."""
    for info in (running(3), running(3, state="stoped", pause=4), {"state": "free", "temp": {}, "last_project": OLDER}):
        rig.mqtt.info = info
        rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "cancelled")
    assert rig.s.intent()["headline"] != "Done."
    job = rig.s.up.store.d["history"][0]
    assert (job["filename"], job["status"], job["print_duration"]) == ("cube.gcode", "cancelled", 240.0)


async def test_a_stop_the_box_missed_is_not_a_finish_of_the_same_file_before(rig):
    before = {**OLDER, "filename": "cube.gcode", "total_layers": 72, "print_time": 13}
    for info in ({**running(3), "last_project": before}, {"state": "free", "temp": {}, "last_project": before}):
        rig.mqtt.info = info
        rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "cancelled")
    again = {**before, "print_time": 14}             # the same file, printed to the end this time
    for info in ({**running(71), "last_project": before}, {"state": "free", "temp": {}, "last_project": again}):
        rig.mqtt.info = info
        rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "complete")
    assert rig.s.intent()["headline"] == "Done."
    assert rig.s.up.store.d["history"][0]["status"] == "completed"


async def test_a_file_sent_without_printing_waits_on_the_box_and_goes_with_its_start(rig):
    """A Kobra that's sent a file warms up and waits on "Downloading files" for a start (7 October 2026)."""
    rig.mqtt.info = {"state": "free", "temp": {}}
    from aiohttp import FormData
    form = FormData()
    form.add_field("file", ORCA.encode(), filename="cube.gcode")
    form.add_field("print", "false")
    r = await rig.client.post("/server/files/upload", data=form)
    assert r.status == 201 and (await r.json())["item"]["path"] == "cube.gcode"
    assert rig.printer.uploads == [] and not [p for p in rig.mqtt.published if p[2] == "start"]
    assert (await rig.s.up.call("server.files.metadata", {"filename": "cube.gcode"}))["layer_count"] == 62
    await rig.s.action("start_file", {"filename": "cube.gcode"})
    assert rig.printer.uploads == [("cube.gcode", ORCA.encode())]
    assert [p for p in rig.mqtt.published if p[2] == "start"][-1][3]["filename"] == "cube.gcode"


def test_the_first_layer_bed_is_the_plates_the_file_was_sliced_for(tmp_path):
    f = tmp_path / "x.gcode"
    f.write_text(ORCA.replace("; hot_plate_temp_initial_layer = 45", "; curr_bed_type = Textured PEI Plate\n"
                              "; hot_plate_temp_initial_layer = 70\n; textured_plate_temp_initial_layer = 45"))
    assert L.gcode_metadata(f, tmp_path / "thumbs")["first_layer_bed_temp"] == 45.0


async def test_an_unanswered_query_now_and_then_isnt_a_lost_printer(rig, monkeypatch):
    monkeypatch.setattr(L, "CALL_TIMEOUT", 0.1)
    made = len(FakeMqtt.made)
    rig.mqtt.mute = L.MISSES - 1
    await until(lambda: rig.mqtt.mute == 0)
    await asyncio.sleep(0.3)
    assert rig.s.up.up and len(FakeMqtt.made) == made
    rig.mqtt.mute = L.MISSES
    await until(lambda: len(FakeMqtt.made) > made)
    await until(lambda: rig.s.up.up)


async def test_an_idle_kobra_is_turned_off_as_the_orca_plugin_sets_temperatures(rig):
    """A print update to 0 is ignored by an idle Kobra 3 (7 October 2026), and Kobra 3 #2 ignored a print update
    altogether: warming sends both, the same targets; off only the Orca plugin's way."""
    rig.mqtt.info = {"state": "free", "temp": {}}
    rig.mqtt.report("info", rig.mqtt.info)
    await rig.s.up.call("printer.gcode.script", {"script": "M140 S80\nM104 S150"})
    assert rig.mqtt.published[-2:] == [("print", "web", "update", {"taskid": "-1", "settings": {"target_hotbed_temp": 80, "target_nozzle_temp": 150}}),
                                       ("tempature", "web", "set", {"type": 2, "target_hotbed_temp": 80, "target_nozzle_temp": 150})]
    await rig.s.up.call("printer.gcode.script", {"script": "TURN_OFF_HEATERS"})
    assert rig.mqtt.published[-1] == ("tempature", "web", "set", {"type": 2, "target_hotbed_temp": 0, "target_nozzle_temp": 0})
    await rig.s.up.call("printer.gcode.script", {"script": "M140 S0"})
    assert rig.mqtt.published[-1] == ("tempature", "web", "set", {"type": 1, "target_hotbed_temp": 0, "target_nozzle_temp": 0})


async def test_the_heaters_targets_are_the_tempature_querys(rig):
    """After a cool-down, info and the pushed tempature reports still say the last print update's targets."""
    stale = {"curr_hotbed_temp": 80, "curr_nozzle_temp": 150, "target_hotbed_temp": 80, "target_nozzle_temp": 150}
    rig.mqtt.info = {"state": "free", "temp": stale}
    rig.mqtt.targets = {"target_hotbed_temp": 0, "target_nozzle_temp": 0}
    await until(lambda: rig.s.up.status.get("extruder", {}).get("target") == 0 and rig.s.up.status["extruder"]["temperature"] == 148)
    rig.mqtt.report("tempature", {**stale, "taskid": "-1"}, action="auto")
    assert rig.s.up.status["heater_bed"]["target"] == 0 and rig.s.up.status["extruder"]["target"] == 0


async def test_warming_an_idle_kobra_is_no_job(rig):
    rig.mqtt.info = {"state": "free", "temp": {}}
    rig.mqtt.report("info", rig.mqtt.info)
    rig.mqtt.report("print", {"settings": {"target_hotbed_temp": 80, "target_nozzle_temp": 150}}, state="updated", action="update")
    rig.mqtt.report("info", rig.mqtt.info)
    assert rig.s.up.status["print_stats"]["state"] == "standby" and rig.s.up.store.d["history"] == []



async def test_a_print_seen_to_its_last_layer_is_done_before_the_printer_says_so(rig):
    """After a print a Kobra stays busy a while and only then updates last_project: two prints that finished were put
    down as stopped (8 October 2026)."""
    for info in (running(71), running(72, progress=100), {"state": "busy", "temp": {}, "last_project": OLDER}):
        rig.mqtt.info = info
        rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "complete")
    assert rig.s.intent()["headline"] == "Done." and rig.s.status["print_stats"]["filename"] == "cube.gcode"
    job = rig.s.up.store.d["history"][0]
    assert (job["filename"], job["status"], job["print_duration"]) == ("cube.gcode", "completed", 240.0)


async def test_a_finished_print_the_kobra_still_reports_is_done(rig):
    """A Kobra keeps a finished job in its info, at 100% with nothing left, until someone touches its screen (a Kobra 3,
    9 October 2026: a whole day, shown on the bench as still printing)."""
    for info in (running(71), running(72, progress=100, remain_time=0)):
        rig.mqtt.info = info
        rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "complete")
    assert rig.s.intent()["headline"] == "Done."
    assert [j["status"] for j in rig.s.up.store.d["history"]] == ["completed"]
    rig.mqtt.report("info", rig.mqtt.info)             # still reported: no second job
    await asyncio.sleep(0.1)
    assert len(rig.s.up.store.d["history"]) == 1 and rig.s.status["print_stats"]["state"] == "complete"


async def test_a_finished_print_found_when_the_box_starts_is_done_not_printing(rig):
    info = running(72, progress=100, remain_time=0)
    rig.mqtt.info = info
    rig.mqtt.report("info", info)
    await until(lambda: rig.s.status["print_stats"]["state"] == "complete")
    assert rig.s.status["print_stats"]["filename"] == "cube.gcode" and not rig.s.up.store.d["history"]
