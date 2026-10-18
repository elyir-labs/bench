"""Finish setting up (design/getting-started/, C), the printer's side of docs/setup-card.md: the card's rows
and the What works sheet from what the component already sees, rows closed with × kept in Moonraker's
database, the printer's screen on a 120-second trial, and the start macro's include added or taken out
through the installer. Against the stand-in Moonraker of test_component.py and a stand-in installer."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_component import FakeConfig, FakeWebRequest, KlippyState, load, run  # noqa: E402

STRANGER = ["webhooks", "print_stats", "heater_bed", "extruder", "filament_switch_sensor runout",
            "gcode_macro PRINT_START", "gcode_macro PAUSE"]
BOARD = {"board": "Raspberry Pi 4, 2 GB, Debian 12", "verdict": "everything", "why_not": None,
         "differences": [], "note": None}


class Tasks:
    """The event loop, holding on to what the component starts in the background until the test runs it."""
    def __init__(self):
        self.waiting = []

    def delay_callback(self, *_):
        pass

    def create_task(self, coro):
        self.waiting.append(coro)

    def drain(self):
        while self.waiting:
            run(self.waiting.pop(0))


class Files:
    def __init__(self, root):
        self.root = root

    def get_directory(self, root="gcodes"):
        return str(self.root)

    def get_file_metadata(self, filename):
        return {}


class Webcams:
    def __init__(self, n):
        self.n = n

    def get_webcams(self):
        return {f"cam{i}": object() for i in range(self.n)}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A stranger's Voron just after the install command: KlipperScreen on its screen, a runout sensor, a
    camera, their own PRINT_START, no unit, and Mainsail calling it Studio too."""
    server, comp = load(tmp_path, monkeypatch)
    loop = Tasks()
    comp.eventloop = loop
    config = tmp_path / "config"
    config.mkdir()
    (config / "elyir-bench.conf").write_text("[elyir-bench]\nprinter_name: Studio\n# elyir-bench | klipperscreen | none\n"
                                           "panel: klipperscreen\n")
    server.components["file_manager"] = Files(config)
    server.components["webcam"] = Webcams(1)
    server.components["database"].data["mainsail"] = {"general": {"printername": "studio"}}
    comp.installer_state = str(tmp_path / "state.json")
    Path(comp.installer_state).write_text(json.dumps({"version": "2026.10.05-abc", "expectations": BOARD}))
    comp.cli, comp.klipperscreen_unit = str(tmp_path / "elyir-bench"), str(tmp_path / "KlipperScreen.service")
    Path(comp.klipperscreen_unit).write_text("[Service]\n")
    installer(comp, tmp_path)
    comp.klippy_apis.objects = list(STRANGER)
    server.kc.state = KlippyState.READY
    run(comp.component_init())
    run(server.handlers["server:klippy_ready"]())
    return server, comp, loop, tmp_path


def installer(comp, tmp_path, code=0, report="[]", then_objects=None):
    """The `elyir-bench` command: says what it was asked in `asked`, answers with `report`."""
    asked = tmp_path / "asked"
    Path(comp.cli).write_text(f"#!/bin/sh\necho \"$@\" >> {asked}\necho '{report}'\nexit {code}\n")
    Path(comp.cli).chmod(0o755)
    if then_objects is not None:
        comp.klippy_apis.objects = then_objects
    return asked


def act(server, comp, action, **args):
    return run(comp._handle_action(FakeWebRequest(action=action, args=args)))


def setup(comp):
    return run(comp._setup())


def test_a_strangers_printer_just_after_the_install(rig):
    server, comp, loop, _ = rig
    got = setup(comp)
    assert (got["name"], got["name_from"]) == ("Studio", "mainsail")
    assert got["rows"] == [{"id": "notify"}, {"id": "screen", "state": "offer"}, {"id": "works", "now": 3, "with_macro": 3}]
    assert got["dismissed"] == []
    w = got["works"]
    assert w["board"] == BOARD
    assert [(f["id"], f["group"]) for f in w["features"]] == [
        ("core", "now"), ("runout", "now"), ("camera", "now"), ("steps", "with_macro"), ("cancel", "with_macro"),
        ("squish", "with_macro"), ("unit", "not_here")]
    assert w["features"][1]["note"] == "Your runout sensor" and w["features"][3]["note"] == "Rough today, from your messages"
    assert w["features"][-1]["note"] == "No ACE Pro found"
    assert (w["include"], w["include_why"], w["include_text"]) == ("off", None, "[include elyir-bench.cfg]")
    assert w["slicer_lines"] == {
        "before": "ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]",
        "after": "ELYIR_BENCH_PRINT_START_DONE"}
    i = comp._current()
    assert i["setup"] == {"open": True} and i["printer"]["screen_trial"] is None


def test_a_chamber_sensor_adds_its_wait_and_no_camera_or_sensor_is_said(rig):
    server, comp, loop, _ = rig
    server.components["webcam"] = Webcams(0)
    comp.klippy_apis.objects = ["print_stats", "temperature_sensor Chamber", "ace"]
    run(server.handlers["server:klippy_ready"]())
    f = {x["id"]: x for x in setup(comp)["works"]["features"]}
    assert f["chamber"] == {"id": "chamber", "group": "with_macro", "label": "Wait for the chamber to warm"}
    assert f["camera"]["group"] == "not_here" and f["camera"]["note"] == "No camera found"
    assert f["runout"]["group"] == "now" and f["unit"]["group"] == "now"   # the unit says when a spool runs out


def test_dismissed_rows_are_kept_in_moonrakers_database(rig):
    server, comp, loop, _ = rig
    act(server, comp, "setup_dismiss", row="works")
    act(server, comp, "setup_dismiss", row="works")
    assert server.components["database"].data["elyir-bench"]["setup"]["dismissed"] == ["works"]
    again = type(comp)(FakeConfig(server))
    run(again.component_init())
    assert setup(again)["dismissed"] == ["works"]


def test_the_card_closes_when_every_row_is_done_or_dismissed(rig):
    server, comp, loop, _ = rig
    act(server, comp, "setup_dismiss", row="works")
    act(server, comp, "setup_dismiss", row="screen")
    assert comp._current()["setup"]["open"] is True, "notify is still to do"
    comp.tracker.phones_notified = True
    assert comp._current()["setup"]["open"] is False


def test_try_it_fetches_switches_and_the_trial_is_kept(rig, monkeypatch):
    server, comp, loop, tmp_path = rig
    asked = installer(comp, tmp_path)
    act(server, comp, "screen_try")
    assert len(loop.waiting) == 1
    coro = loop.waiting.pop()
    seen = []
    real = comp._run_cli

    async def watched(*args, **kw):
        seen.append(comp._screen_row())
        return await real(*args, **kw)
    monkeypatch.setattr(comp, "_run_cli", watched)
    run(coro)
    assert seen == [{"id": "screen", "state": "fetching"}]
    assert asked.read_text() == "--json panel elyir-bench\n"
    assert setup(comp)["rows"][1] == {"id": "screen", "state": "trial"}
    assert comp._current()["printer"]["screen_trial"] == {"seconds_left": 120}
    act(server, comp, "screen_keep")
    assert setup(comp)["rows"][1] == {"id": "screen", "state": "done"}
    assert comp._current()["printer"]["screen_trial"] is None
    assert server.components["database"].data["elyir-bench"]["setup"]["screen"] == "done"
    with pytest.raises(Exception, match="isn't on trial"):
        act(server, comp, "screen_keep")


def test_a_trial_nobody_answers_goes_back_by_itself(rig, monkeypatch):
    server, comp, loop, tmp_path = rig
    mod = sys.modules[type(comp).__module__]
    asked = installer(comp, tmp_path)
    clock = {"now": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["now"])
    act(server, comp, "screen_try")
    loop.drain()
    clock["now"] += 12
    assert comp._current()["printer"]["screen_trial"] == {"seconds_left": 108}
    comp._check_trial()
    assert comp._trial_until is not None
    clock["now"] += 108
    comp._check_trial()
    loop.drain()
    assert asked.read_text() == "--json panel elyir-bench\n--json panel klipperscreen\n"
    assert setup(comp)["rows"][1] == {"id": "screen", "state": "kept_klipperscreen"}
    assert server.components["database"].data["elyir-bench"]["setup"]["screen"] == "kept_klipperscreen"


def test_back_to_klipperscreen_now(rig):
    server, comp, loop, tmp_path = rig
    asked = installer(comp, tmp_path)
    act(server, comp, "screen_try")
    loop.drain()
    act(server, comp, "screen_back")
    loop.drain()
    assert asked.read_text().splitlines()[-1] == "--json panel klipperscreen"
    assert setup(comp)["rows"][1]["state"] == "kept_klipperscreen"


def test_parts_that_cant_be_had_are_said_and_nothing_changes(rig):
    server, comp, loop, tmp_path = rig
    report = json.dumps([{"step": "panel", "status": "fail", "detail": "Debian GNU/Linux 11 (bullseye) has no chromium package "
                                                                         "for the x11 panel. Set panel_backend: auto"},
                         {"step": "apply", "status": "fail", "detail": "Debian 11 has no chromium package"}])
    installer(comp, tmp_path, code=1, report=report)
    act(server, comp, "screen_try")
    loop.drain()
    row = setup(comp)["rows"][1]
    assert row == {"id": "screen", "state": "cant",
                   "why": "Debian GNU/Linux 11 (bullseye) has no chromium package for the x11 panel. Nothing changed."}
    assert comp._current()["printer"]["screen_trial"] is None
    act(server, comp, "setup_dismiss", row="screen")     # OK
    assert "screen" in setup(comp)["dismissed"]


def test_a_board_that_cant_run_the_screen_says_so_and_refuses(rig):
    server, comp, loop, _ = rig
    Path(comp.installer_state).write_text(json.dumps({"expectations": {
        **BOARD, "verdict": "differences",
        "differences": ["The screen stays on KlipperScreen: this system can't run Elyir Bench there."]}}))
    assert setup(comp)["rows"][1] == {"id": "screen", "state": "cant",
                                      "why": "This system can't run Elyir Bench on its screen. Nothing changed."}
    with pytest.raises(Exception, match="can't run Elyir Bench"):
        act(server, comp, "screen_try")
    assert loop.waiting == []


def test_no_screen_row_without_klipperscreen_or_when_the_install_already_shows_it(rig):
    server, comp, loop, tmp_path = rig
    (tmp_path / "config" / "elyir-bench.conf").write_text("[elyir-bench]\npanel: elyir-bench\n")
    assert [r["id"] for r in setup(comp)["rows"]] == ["notify", "works"]
    (tmp_path / "config" / "elyir-bench.conf").write_text("[elyir-bench]\npanel: klipperscreen\n")
    Path(comp.klipperscreen_unit).unlink()
    assert [r["id"] for r in setup(comp)["rows"]] == ["notify", "works"]
    with pytest.raises(Exception, match="no screen"):
        act(server, comp, "screen_try")


def test_the_include_goes_in_through_the_installer_and_moves_the_features_to_now(rig):
    server, comp, loop, tmp_path = rig
    asked = installer(comp, tmp_path, then_objects=STRANGER + ["gcode_macro ELYIR_BENCH_PRINT_START"])
    act(server, comp, "include_add")
    assert setup(comp)["works"]["include"] == "off", "not started until the loop runs it"
    coro = loop.waiting.pop()
    run(coro)
    assert asked.read_text() == "--json startmacro on\n"
    got = setup(comp)
    assert got["works"]["include"] == "on"
    assert {f["group"] for f in got["works"]["features"] if f["id"] in ("steps", "cancel", "squish")} == {"now"}
    assert got["rows"][-1] == {"id": "works", "now": 6, "with_macro": 0}
    installer(comp, tmp_path, then_objects=list(STRANGER))
    act(server, comp, "include_remove")
    loop.drain()
    assert asked.read_text().splitlines()[-1] == "--json startmacro off"
    assert setup(comp)["works"]["include"] == "off"


def test_the_include_waits_for_the_print_and_a_failure_is_said(rig):
    server, comp, loop, tmp_path = rig
    comp.tracker.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}})
    with pytest.raises(Exception, match="until the print is done"):
        act(server, comp, "include_add")
    comp.tracker.update_status({"print_stats": {"state": "complete"}})
    report = json.dumps([{"step": "apply", "status": "fail",
                          "detail": "Klipper didn\u2019t start again: Option x is not valid in section printer"},
                         {"step": "undone", "status": "done", "detail": "start macro"}])
    installer(comp, tmp_path, code=1, report=report)
    act(server, comp, "include_add")
    states = []
    real = comp._publish
    comp._publish = lambda force=False: (states.append(comp._include_state()), real(force))
    loop.drain()
    assert states[0] == "adding"
    w = setup(comp)["works"]
    assert (w["include"], w["include_why"]) == ("failed", "Klipper didn’t start again: Option x is not valid in section printer")
    assert comp._current()["setup"]["open"] is True


def test_our_own_print_start_already_does_what_the_macro_would(rig):
    server, comp, loop, _ = rig
    comp.klippy_apis.objects = STRANGER + ["gcode_macro _PRINT_START"]
    run(server.handlers["server:klippy_ready"]())
    got = setup(comp)
    assert got["rows"][-1] == {"id": "works", "now": 6, "with_macro": 0}
    assert all("note" not in f for f in got["works"]["features"] if f["id"] == "steps")


def test_the_name_comes_from_the_host_or_the_person(rig, monkeypatch):
    server, comp, loop, _ = rig
    mod = sys.modules[type(comp).__module__]
    server.components["database"].data["mainsail"] = {"general": {"printername": "Voron 2.4"}}
    monkeypatch.setattr(mod.socket, "gethostname", lambda: "studio.local")
    assert setup(comp)["name_from"] == "hostname"
    monkeypatch.setattr(mod.socket, "gethostname", lambda: "voron")
    assert setup(comp)["name_from"] == "you"


def test_the_name_changes_only_the_line_it_should():
    from importlib import import_module
    pi = sys.modules.get("moonraker.components.printer_intent") or import_module("printer_intent")
    conf = "[server]\nhost: 0.0.0.0\n\n[printer_intent]\nprinter_name: Voron\nadvanced_url: http://voron.local/\n\n[update_manager]\n"
    got = pi.set_conf_name(conf, "printer_intent", "Workshop")
    assert got == conf.replace("printer_name: Voron", "printer_name: Workshop")
    assert pi.set_conf_name("[elyir-bench]\npanel: elyir-bench\n", "elyir-bench", "Desk") == "[elyir-bench]\nprinter_name: Desk\npanel: elyir-bench\n"
    assert pi.set_conf_name("[server]\n", "printer_intent", "X") == "[server]\n"


def test_change_renames_what_elyir_bench_shows_at_once_and_keeps_it_but_not_the_network_name(rig):
    server, comp, loop, tmp_path = rig
    (tmp_path / "config" / "moonraker.conf").write_text("[server]\nhost: 0.0.0.0\n\n[printer_intent]\nprinter_name: Studio\n")
    got = act(server, comp, "setup_name", name="  Workshop  ")
    assert got["setup"]["name"] == "Workshop" and got["setup"]["name_from"] == "you"
    assert comp._current()["printer"]["name"] == "Workshop"
    assert "printer_name: Workshop" in (tmp_path / "config" / "elyir-bench.conf").read_text()
    assert "printer_name: Workshop" in (tmp_path / "config" / "moonraker.conf").read_text()
    assert not (tmp_path / "asked").exists() or "rename" not in (tmp_path / "asked").read_text()   # no hostname change
    with pytest.raises(Exception):
        act(server, comp, "setup_name", name=" ")


def test_the_secure_link_is_off_waiting_or_on():
    from importlib import import_module
    pi = sys.modules.get("moonraker.components.printer_intent") or import_module("printer_intent")
    asked = []
    def ask(api, name, secret):
        asked.append((api, name, secret))
        return {"carried": name == "workshop"}
    assert pi.secure_link_state({}, ask) == "off" and not asked                    # never claimed: the relay isn't asked
    assert pi.secure_link_state({"name": "desk", "secret": "s"}, ask) == "waiting"  # claimed, not approved yet
    assert pi.secure_link_state({"name": "workshop", "secret": "s"}, ask) == "on"
    assert pi.secure_link_state({"name": "desk", "secret": "s"}, lambda *a: None) == "waiting"   # no answer
    assert asked[0] == ("https://api.elyir.app", "desk", "s")


def test_the_setup_card_says_where_the_secure_link_is(rig):
    server, comp, loop, tmp_path = rig
    assert setup(comp)["secure_link"] == "off"           # the rig's printer never claimed a name
