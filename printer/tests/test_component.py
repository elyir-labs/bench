"""
The Moonraker component against a stand-in Moonraker: just the calls it makes,
with Klipper's state under the test's control. Replays the startup sequences
that real printers have shown (studio's silent CAN toolhead).
"""

import asyncio
import enum
import importlib
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent


class KlippyState(enum.Enum):
    DISCONNECTED = 1
    STARTUP = 2
    READY = 3
    ERROR = 4
    SHUTDOWN = 5


class FakeKlippyConnection:
    def __init__(self):
        self.state = KlippyState.DISCONNECTED
        self.state_message = ""


class FakeKlippyAPIs:
    def __init__(self, kc):
        self.kc = kc

    async def get_klippy_info(self):
        return {"state": self.kc.state.name.lower(), "state_message": self.kc.state_message}

    objects: list = []
    settings: dict = {}

    async def get_object_list(self):
        return list(self.objects)

    async def query_objects(self, objs):
        return {"configfile": {"settings": self.settings}}

    async def subscribe_objects(self, objs, cb):
        return {"print_stats": {"state": "standby", "filename": ""}, "webhooks": {"state": "ready"}}


class FakeDatabase:
    def __init__(self):
        self.data = {}

    async def get_item(self, ns, key=None, default=None):
        space = self.data.get(ns, {})
        if key is None:
            return dict(space) if space else default
        return space.get(key, default)

    async def insert_item(self, ns, key, value):
        self.data.setdefault(ns, {})[key] = value

    async def delete_item(self, ns, key):
        self.data.get(ns, {}).pop(key, None)


class FakeHistory:
    def __init__(self):
        self.job_totals = {"total_print_time": 0.0, "total_filament_used": 0.0}


class FakeLoop:
    def delay_callback(self, *_):
        pass

    def create_task(self, coro):
        coro.close()


class FakeServer:
    def __init__(self):
        self.kc = FakeKlippyConnection()
        self.components = {"klippy_connection": self.kc, "klippy_apis": FakeKlippyAPIs(self.kc),
                           "database": FakeDatabase(), "history": FakeHistory()}
        self.handlers = {}
        self.sent = []

    def get_event_loop(self):
        return FakeLoop()

    def lookup_component(self, name):
        return self.components[name]

    def register_notification(self, *_):
        pass

    def register_endpoint(self, *_, **__):
        pass

    def register_event_handler(self, name, fn):
        self.handlers[name] = fn

    def send_event(self, name, *args):
        self.sent.append((name, args))

    def error(self, msg, code=400):
        return Exception(msg)


class FakeConfig:
    def __init__(self, server):
        self.server = server

    def get_server(self):
        return self.server

    def get(self, key, default=None):
        return {"printer_name": "Studio"}.get(key, default)


def load(tmp_path, monkeypatch, files=("printer_intent.py", "elyir_bench_intent.py", "filament_units.py", "unit_check.py", "elyir_bench_care.py", "orca_profile.py")):
    """Load printer_intent.py as moonraker.components.printer_intent, as Moonraker does."""
    pkg = tmp_path / "moonraker"
    (pkg / "components").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "components" / "__init__.py").write_text("")
    (pkg / "common.py").write_text(
        "import enum\n"
        "class RequestType(enum.Flag):\n    GET = 1\n    POST = 2\n"
        "class TransportType(enum.Flag):\n    HTTP = 1\n    WEBSOCKET = 2\n")
    for f in files:
        shutil.copy(HERE / f, pkg / "components" / f)
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in [m for m in sys.modules if m == "moonraker" or m.startswith("moonraker.")]:
        monkeypatch.delitem(sys.modules, m)
    mod = importlib.import_module("moonraker.components.printer_intent")
    server = FakeServer()
    comp = mod.load_component(FakeConfig(server))
    return server, comp


@pytest.fixture
def component(tmp_path, monkeypatch):
    return load(tmp_path, monkeypatch)


def run(coro):
    return asyncio.run(coro)


def test_long_startup_then_error_reaches_the_screen(component, monkeypatch):
    server, comp = component
    t0 = time.time()
    clock = {"now": t0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    kc = server.kc

    # Moonraker connected to Klipper, which is retrying a silent toolhead board
    kc.state = KlippyState.STARTUP
    clock["now"] = t0 + 30
    i = comp._current()
    assert (i["state"], i["phase"]) == ("preparing", "starting_up")
    assert "About a minute" in i["detail"]

    clock["now"] = t0 + 125   # 95 s after the startup was first seen
    i = comp._current()
    assert i["state"] == "preparing" and "may not be answering" in i["detail"]
    assert "brain" not in i["headline"]

    # Klipper gives up. Moonraker fires klippy_started but still reports STARTUP
    # until every handler has returned, then reports ERROR.
    kc.state_message = "mcu 'EBBCan': Unable to connect\nError configuring printer\n"
    clock["now"] = t0 + 130
    real = KlippyState.ERROR
    run(server.handlers["server:klippy_started"](real))   # kc.state is still STARTUP here
    kc.state = real
    i = comp._current()
    assert i["state"] == "problem"
    assert i["headline"] == "The print head lost contact for a moment."


def test_ready_shows_starting_up_until_subscribed_then_ready(component):
    server, comp = component
    kc = server.kc
    kc.state = KlippyState.READY      # Klipper is ready before our handler has subscribed
    assert comp._current()["phase"] == "starting_up"
    run(server.handlers["server:klippy_ready"]())
    i = comp._current()
    assert (i["state"], i["phase"]) == ("ready", "idle")


def test_the_dryer_limit_comes_from_klippers_config(component):
    server, comp = component
    server.kc.state = KlippyState.READY
    comp.klippy_apis.objects = ["ace", "print_stats"]
    comp.klippy_apis.settings = {"ace": {"max_dryer_temperature": 70.0}}
    run(server.handlers["server:klippy_ready"]())
    assert comp.tracker.has_unit and comp.tracker.dryer_max == 70.0


def test_disconnect_then_offline_only_after_grace(component, monkeypatch):
    server, comp = component
    run(server.handlers["server:klippy_ready"]())
    server.kc.state = KlippyState.READY
    assert comp._current()["state"] == "ready"
    t0 = time.time()
    monkeypatch.setattr(time, "time", lambda: t0)
    server.kc.state = KlippyState.DISCONNECTED
    run(server.handlers["server:klippy_disconnect"]())
    assert comp._current()["phase"] == "starting_up"
    monkeypatch.setattr(time, "time", lambda: t0 + 120)
    assert comp._current()["phase"] == "offline"


def test_care_seeds_once_comes_due_and_done_or_later_clear_it(component):
    server, comp = component
    db, hist = server.components["database"], server.components["history"]
    hist.job_totals["total_print_time"] = 900 * 3600.0     # an old printer
    run(server.handlers["server:klippy_ready"]())
    server.kc.state = KlippyState.READY
    run(comp._refresh_care())
    tasks = {k: v for k, v in db.data["maintenance"].items()}
    assert sorted(v["name"] for v in tasks.values()) == ["Check the belts", "Clean the nozzle", "Lubricate the rails", "Wipe the bed"]
    assert db.data["elyir-bench"]["care_seeded"] is True
    assert comp._current()["care"]["due"] == 0

    # deleted in Mainsail stays deleted
    belts = next(k for k, v in tasks.items() if v["name"] == "Check the belts")
    run(db.delete_item("maintenance", belts))
    run(comp._refresh_care())
    assert len(db.data["maintenance"]) == 3

    hist.job_totals["total_print_time"] += 45 * 3600.0
    run(comp._refresh_care())
    i = comp._current()
    assert (i["phase"], i["care"]["due"], i["care"]["hint"]) == ("care_due", 1, "Time to wipe the bed.")
    bed = i["care"]["items"][0]["id"]

    run(comp._care_action("care_later", bed))
    assert comp._current()["care"]["due"] == 0 and comp._current()["phase"] == "idle"

    run(comp._care_action("care_done", bed))
    assert db.data["maintenance"][bed]["end_printtime"] == 945 * 3600.0
    fresh = [v for v in db.data["maintenance"].values() if v.get("last_entry") == bed]
    assert len(fresh) == 1 and fresh[0]["start_printtime"] == 945 * 3600.0
    assert comp._current()["care"]["due"] == 0


def test_without_the_care_module_everything_else_still_works(tmp_path, monkeypatch):
    server, comp = load(tmp_path, monkeypatch, files=("printer_intent.py", "elyir_bench_intent.py", "filament_units.py", "unit_check.py"))
    run(server.handlers["server:klippy_ready"]())
    server.kc.state = KlippyState.READY
    run(comp._refresh_care())
    i = comp._current()
    assert (i["state"], i["phase"], i["care"]) == ("ready", "idle", None)


def test_without_a_unit_the_spool_is_remembered_and_spoolman_wins(component):
    server, comp = component
    mod = sys.modules[type(comp).__module__]
    run(comp.component_init())
    run(server.handlers["server:klippy_ready"]())   # the object list has no "ace"
    server.kc.state = KlippyState.READY
    assert comp.tracker.direct
    assert comp._current()["spools"][0]["source"] == "unknown"

    for kind, payload in mod.engine.plan_action("set_spool", {"slot": 0, "color": "#222222", "material": "PETG"}, comp.tracker):
        run(comp._run(kind, payload))
    db = server.components["database"]
    assert db.data["elyir-bench"]["spool"]["material"] == "PETG"

    # Moonraker restarts: a fresh component reads it back
    again = type(comp)(FakeConfig(server))
    run(again.component_init())
    run(server.handlers["server:klippy_ready"]())
    s = again._current()["spools"][0]
    assert (s["name"], s["source"]) == ("Black PETG", "told")

    class Resp:
        def has_error(self):
            return False

        def json(self):
            return {"id": 7, "remaining_weight": 512.6,
                    "filament": {"material": "PLA", "color_hex": "FFFFFF", "name": "Basic"}}

    class Http:
        async def get(self, url):
            assert url == "http://sm/api/v1/spool/7"
            return Resp()

    class Spoolman:
        spool_id = 7
        spoolman_url = "http://sm/api"

    server.components.update({"spoolman": Spoolman(), "http_client": Http()})
    run(again._refresh_spoolman())
    s = again._current()["spools"][0]
    assert (s["name"], s["source"], s["grams"]) == ("White PLA", "spoolman", 513)
    Spoolman.spool_id = None
    run(again._refresh_spoolman())
    assert again._current()["spools"][0]["source"] == "told"


# ── who pressed it (an untraceable Stop now on workshop, 3 October 2026) ─────────

class _Req:
    def __init__(self, conn, ip):
        self._c, self._ip = conn, ip
    def get_client_connection(self):
        return self._c
    def get_ip_address(self):
        return self._ip


class _Conn:
    def __init__(self, name, agent):
        self.client_data = {"name": name}
        self.request = type("R", (), {"headers": {"User-Agent": agent}})()


def test_who_sent_names_the_screen_and_the_connection(component):
    mod = sys.modules[type(component[1]).__module__]
    who_sent, browser_of = mod.who_sent, mod.browser_of
    kiosk = "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    assert who_sent(_Req(_Conn("elyir-bench", kiosk), "127.0.0.1"), "panel") == "panel (elyir-bench, 127.0.0.1, Chrome on CrOS)"
    assert who_sent(_Req(_Conn("elyir-bench", mac), "192.0.2.59"), "phone or computer").endswith("Chrome on Mac)")
    assert who_sent(_Req(None, None), "") == "an unnamed client (http, ?, no browser)"
    assert browser_of("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605 Version/18.0 Mobile/15E148 Safari/604.1") == "Safari on iPhone"


def test_who_sent_never_raises(component):
    who_sent = sys.modules[type(component[1]).__module__].who_sent
    class Broken:
        def get_client_connection(self):
            raise RuntimeError("gone")
    assert who_sent(Broken(), "panel") == "panel"


# ---- colour changes (design/colour-change/): read from the file, cached, and the plan stored ----

class FakeFileManager:
    def __init__(self, root):
        self.root = root

    def get_directory(self, root="gcodes"):
        return str(self.root)

    def get_file_metadata(self, filename):
        return {"filament_type": "PLA", "filament_colors": ["#D9534F"], "layer_count": 3}


class FakeWebRequest:
    def __init__(self, **args):
        self.args = args

    def get_str(self, key, default=None):
        return self.args.get(key, default)

    def get(self, key, default=None):
        return self.args.get(key, default)

    def get_client_connection(self):
        return None

    def get_ip_address(self):
        return "127.0.0.1"


def test_check_print_reads_the_colour_changes_from_the_file_once_and_the_plan_is_stored(component, tmp_path):
    server, comp = component
    gcodes = tmp_path / "gcodes"
    gcodes.mkdir()
    (gcodes / "stand.gcode").write_text(";LAYER_CHANGE\nG1 X1 E1\n;LAYER_CHANGE\n;COLOR_CHANGE,T0,#F4F4F2\nM600\nG1 X2 E1\n")
    server.components["file_manager"] = FakeFileManager(gcodes)
    comp.tracker.has_unit = True
    comp.tracker.set_klippy_state("ready")
    comp.tracker.update_status({"print_stats": {"state": "standby", "filename": ""},
                                "ace": {"selected_gate": 0, "gate_color": ["D9534F", "F1F1F1"], "gate_material": ["PLA", "PLA"],
                                        "slots": [{"status": "ready"}, {"status": "ready"}]}})
    check = run(comp._handle_check_print(FakeWebRequest(filename="stand.gcode")))
    assert check["colour_changes"] == [{"layer": 2, "color": "#F4F4F2", "slot": 1, "not_loaded": False}]
    assert comp._colour_cache["stand.gcode"][2] == [{"layer": 2, "color": "#F4F4F2"}]
    (gcodes / "stand.gcode").write_text("M600\n")          # same size and time would be the cache; this one changed
    assert run(comp._colour_changes("stand.gcode")) == [{"layer": None, "color": None}]
    (gcodes / "stand.gcode").write_text(";LAYER_CHANGE\nG1 X1 E1\n;LAYER_CHANGE\n;COLOR_CHANGE,T0,#F4F4F2\nM600\nG1 X2 E1\n")
    run(comp._handle_check_print(FakeWebRequest(filename="stand.gcode")))

    engine = sys.modules["moonraker.components.printer_intent"].engine
    steps = engine.plan_action("print_planned", {"filename": "stand.gcode", "changes": [{"slot": 1}]}, comp.tracker)
    kind, payload = steps[0]
    run(comp._run(kind, payload))
    db = server.components["database"]
    assert db.data["elyir-bench"]["colour_plan"]["changes"] == [{"layer": 2, "slot": 1, "color": "#F4F4F2"}]
    assert db.data["elyir-bench"]["colour_plan"]["filename"] == "stand.gcode"


def test_the_screen_can_switch_only_with_the_installer_and_klipperscreen(component, tmp_path):
    server, comp = component
    comp.cli, comp.klipperscreen_unit = str(tmp_path / "elyir-bench"), str(tmp_path / "KlipperScreen.service")
    assert comp._current()["printer"]["screen_switch"] is False
    seen = tmp_path / "seen"
    Path(comp.cli).write_text(f"#!/bin/sh\necho \"$@\" > {seen}\n")
    Path(comp.cli).chmod(0o755)
    assert comp._current()["printer"]["screen_switch"] is False, "no KlipperScreen to switch to"
    Path(comp.klipperscreen_unit).write_text("[Service]\n")
    assert comp._current()["printer"]["screen_switch"] is True
    run(comp._switch_screen("klipperscreen"))
    assert seen.read_text() == "--json panel klipperscreen\n"
    assert comp._screen_switching is False


def test_a_switch_that_was_undone_is_told_in_care(component, tmp_path):
    server, comp = component
    comp.cli, comp.klipperscreen_unit = str(tmp_path / "elyir-bench"), str(tmp_path / "KlipperScreen.service")
    report = json.dumps([{"step": "panel", "status": "done", "detail": "applied"},
                         {"step": "health", "status": "fail", "detail": "KlipperScreen keeps restarting"},
                         {"step": "apply", "status": "fail", "detail": "health check failed: KlipperScreen keeps restarting"},
                         {"step": "undone", "status": "done", "detail": "panel"}])
    Path(comp.cli).write_text(f"#!/bin/sh\necho '{report}'\nexit 1\n")
    Path(comp.cli).chmod(0o755)
    run(comp._switch_screen("klipperscreen"))
    assert comp._current()["printer"]["screen_switch_failed"] == \
        "Couldn't show KlipperScreen (KlipperScreen keeps restarting), so the screen went back to Elyir Bench."
    Path(comp.cli).write_text("#!/bin/sh\necho '[]'\n")
    run(comp._switch_screen("klipperscreen"))
    assert comp._current()["printer"]["screen_switch_failed"] is None


def test_the_unit_check_reads_happy_hares_gate_sensors_and_afcs_hubs(component):
    server, comp = component
    seen = {}

    async def subscribe(objs, cb):
        seen.update(objs)
        return {"print_stats": {"state": "standby", "filename": ""}, "webhooks": {"state": "ready"}}
    comp.klippy_apis.subscribe_objects = subscribe
    comp.klippy_apis.objects = ["mmu", "filament_switch_sensor mmu_entry_0", "filament_switch_sensor mmu_pre_gate_1",
                                "filament_switch_sensor runout", "AFC", "AFC_stepper lane1", "AFC_hub Turtle_1"]
    run(server.handlers["server:klippy_ready"]())
    assert seen["filament_switch_sensor mmu_entry_0"] == ["filament_detected"]
    assert seen["filament_switch_sensor mmu_pre_gate_1"] == ["filament_detected"]
    assert "filament_switch_sensor runout" not in seen
    assert "AFC_hub Turtle_1" in seen and seen["AFC_hub Turtle_1"] is None
