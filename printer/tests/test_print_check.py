"""Before a print: does the file's filament match what's loaded? And spools entered by hand."""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402


def spool(slot, color, material="PLA", status="ready", rfid=False):
    return {"slot": slot, "color": color, "material": material, "status": status, "in_use": False, "rfid": rfid, "grams": None}


LOADED = [spool(0, "#D9534F"), spool(1, "#F1F1F1"), spool(2, "#2B2B2B"), spool(3, None, None, "empty")]


def meta(colors, types, weights=None):
    m = {"filament_colors": colors, "filament_type": ";".join(types)}
    if weights is not None:
        m["filament_weights"] = weights
    return m


def test_loaded_colours_are_ok():
    r = a.check_print("stand.gcode", meta(["#D9534F", "#F1F1F1"], ["PLA", "PLA"]), LOADED)
    assert r["ok"] and r["missing"] == []


def test_only_used_filaments_count():
    # Orca lists every profile filament; weights say only the first is used
    r = a.check_print("x.gcode", meta(["#2B2B2B", "#FF8800"], ["PLA", "PETG"], [12.0, 0]), LOADED)
    assert r["ok"]


def test_missing_colour_offers_the_free_slot():
    r = a.check_print("vase.gcode", meta(["#FF8800"], ["PETG"]), LOADED)
    assert not r["ok"]
    assert r["headline"] == "This needs Orange PETG."
    assert r["short"] == "Needs Orange PETG"
    assert "slot 4" in r["detail"]
    ids = [x["id"] for x in r["actions"]]
    assert ids == ["open_materials", "start_file"]
    assert r["actions"][0]["primary"] and r["actions"][1]["args"] == {"filename": "vase.gcode"}


def test_same_colour_wrong_material_says_so():
    r = a.check_print("w.gcode", meta(["#F2F2F2"], ["PETG"]), LOADED)
    assert not r["ok"]
    assert "slot 2" in r["detail"] and "PLA" in r["detail"]


def test_pla_plus_matches_pla():
    r = a.check_print("p.gcode", meta(["#2B2B2B"], ["PLA+"]), LOADED)
    assert r["ok"]


def test_full_unit_suggests_swapping():
    full = [spool(i, c) for i, c in enumerate(["#D9534F", "#F1F1F1", "#2B2B2B", "#3B82F6"])]
    r = a.check_print("v.gcode", meta(["#22AA22"], ["PLA"]), full)
    assert not r["ok"] and "every slot is full" in r["detail"]


def test_nothing_to_check_without_unit_or_metadata():
    assert a.check_print("a.gcode", meta(["#FF8800"], ["PETG"]), [])["ok"]
    assert a.check_print("a.gcode", {}, LOADED)["ok"]
    assert a.check_print("a.gcode", None, LOADED)["ok"]


def test_three_missing_says_and_more():
    r = a.check_print("m.gcode", meta(["#FF8800", "#22AA22", "#8B5CF6"], ["PLA", "PLA", "PLA"]), LOADED)
    assert r["headline"].endswith("and more.")


# ---- set_spool --------------------------------------------------------------

def tracker_with_ace():
    t = a.IntentTracker("TEST", now=0)
    t.update_status({"ace": {
        "gate_color": ["D9534F", "F1F1F1", "2B2B2B", "FFFFFF"],
        "gate_material": ["PLA", "PLA", "PLA", ""],
        "gate_temp": [210, 210, 210, 230],
        "slots": [{"status": "ready", "rfid": 1, "color": [217, 83, 79], "type": "PLA"},
                  {"status": "ready", "rfid": 0}, {"status": "ready", "rfid": 0}, {"status": "empty"}],
    }}, now=0)
    return t


def klipper_params(line):
    """Parse a G-code line the way Klipper does for extended commands (gcode.py):
    cut at ';', split the rest like a shell (quotes removed, '#' starts a comment)."""
    import shlex
    line = line.split(";", 1)[0]
    raw = line.split(None, 1)[1] if " " in line else ""
    lex = shlex.shlex(raw, posix=True)
    lex.whitespace_split = True
    lex.commenters = "#;"
    return {k.upper(): v for k, v in (arg.split("=", 1) for arg in lex)}


def saved(plan, name):
    """The value SAVE_VARIABLE would store, parsed exactly as Klipper parses it."""
    for kind, payload in plan:
        if kind == a.ActionPlan.GCODE and f"VARIABLE={name} " in payload:
            params = klipper_params(payload)
            assert params["VARIABLE"] == name
            return ast.literal_eval(params["VALUE"])   # what save_variables.py does
    return None


def test_set_spool_writes_colour_material_and_temp():
    plan = a.plan_action("set_spool", {"slot": 3, "color": "#ff8800", "material": "petg"}, tracker_with_ace())
    assert saved(plan, "ace_gate_color") == ["D9534F", "F1F1F1", "2B2B2B", "FF8800"]
    assert saved(plan, "ace_gate_type") == ["PLA", "PLA", "PLA", "PETG"]
    assert saved(plan, "ace_gate_temp") == [210, 210, 210, 240]
    # every command survives Klipper's own parsing (a parse error there shuts Klipper down)
    for kind, p in plan:
        if kind == a.ActionPlan.GCODE:
            ast.literal_eval(klipper_params(p)["VALUE"])
    # and the intent layer hears it was said, so "New spool in slot 4" stops asking
    assert plan[-1] == (a.ActionPlan.SLOT, {"op": "told", "slot": 3})


def test_same_material_keeps_custom_temperature():
    plan = a.plan_action("set_spool", {"slot": 1, "color": "#000000", "material": "PLA"}, tracker_with_ace())
    assert saved(plan, "ace_gate_color")[1] == "000000"
    assert saved(plan, "ace_gate_temp") is None


def test_tagged_spool_is_refused():
    assert a.plan_action("set_spool", {"slot": 0, "color": "#000000", "material": "PLA"}, tracker_with_ace()) == []


def test_bad_input_is_refused():
    t = tracker_with_ace()
    assert a.plan_action("set_spool", {"slot": 9, "color": "#000000", "material": "PLA"}, t) == []
    assert a.plan_action("set_spool", {"slot": 1, "color": "red", "material": "PLA"}, t) == []
    assert a.plan_action("set_spool", {"slot": 1, "color": "#000000", "material": "PLA; G28"}, t) == []
    assert a.plan_action("set_spool", {"slot": "x", "color": "#000000", "material": "PLA"}, t) == []


def test_start_file():
    assert a.plan_action("start_file", {"filename": "a.gcode"}, tracker_with_ace()) == [(a.ActionPlan.START_FILE, "a.gcode")]
    assert a.plan_action("start_file", {}, tracker_with_ace()) == []


def test_one_spool_one_slot_wording():
    two_free = LOADED[:3] + [spool(3, None, None, "empty"), spool(4, None, None, "empty")]
    r = a.check_print("v.gcode", meta(["#FF8800"], ["PETG"]), two_free)
    assert "slot 4 or 5" in r["detail"]
    r = a.check_print("v.gcode", meta(["#FF8800", "#22AA22"], ["PETG", "PLA"]), two_free)
    assert r["detail"].startswith("They aren't loaded") and "empty slots" in r["detail"]


def test_spools_carry_a_name():
    sp = {s["slot"]: s for s in tracker_with_ace().spools()}
    assert sp[1]["name"] == "White PLA"
    assert sp[3]["status"] == "empty" and sp[3]["name"] is None   # nothing set yet
    t = tracker_with_ace()
    for kind, payload in a.plan_action("set_spool", {"slot": 3, "color": "#FF8800", "material": "PETG"}, t):
        if kind != a.ActionPlan.GCODE:
            continue
        params = klipper_params(payload)
        field = {"ace_gate_color": "gate_color", "ace_gate_type": "gate_material", "ace_gate_temp": "gate_temp"}[params["VARIABLE"]]
        t.update_status({"ace": {field: ast.literal_eval(params["VALUE"])}}, now=0)
    assert {s["slot"]: s for s in t.spools()}[3]["name"] == "Orange PETG"


# ---- filament units that didn't get picked up ---------------------------------

def tracker_two_units_known_one():
    t = a.IntentTracker("Workshop", now=0)
    t.set_klippy_state("ready", "Printer is ready", now=0)
    t.update_status({"print_stats": {"state": "standby"}, "heater_bed": {"target": 0}, "extruder": {"target": 0},
                     "ace": {"devices": [{"name": "ACE_1", "gate_offset": 0, "status": {"slots": [{"status": "ready"}] * 4}}],
                             "gate_color": ["FFFFFF"] * 4, "gate_material": ["PLA"] * 4}}, now=0)
    t.set_units_on_usb(2)
    return t


def test_missing_unit_is_noticed_and_offers_to_look_again():
    t = tracker_two_units_known_one()
    u = t.units()
    assert u["present"] == 2 and u["known"] == 1 and u["missing"] == 1
    assert u["notice"]["headline"] == "One filament unit isn't showing up."
    i = t.intent(now=1)
    assert i["state"] == "ready" and i["phase"] == "unit_missing"
    assert "isn't showing up" in i["detail"]
    assert [x["id"] for x in i["actions"]] == ["rescan_units"] and i["actions"][0]["primary"]


def test_no_notice_when_all_units_known():
    t = tracker_two_units_known_one()
    t.set_units_on_usb(1)
    assert t.units()["missing"] == 0 and t.units()["notice"] is None
    assert t.intent(now=1)["phase"] == "idle"


def test_unknown_usb_count_is_not_a_problem():
    t = tracker_two_units_known_one()
    t.set_units_on_usb(None)
    assert t.units()["missing"] == 0


def test_rescan_restarts_software_but_never_mid_print():
    t = tracker_two_units_known_one()
    assert a.plan_action("rescan_units", {}, t) == [(a.ActionPlan.KLIPPY_RESTART, None)]
    t.update_status({"print_stats": {"state": "printing"}}, now=2)
    assert a.plan_action("rescan_units", {}, t) == []


def test_component_reads_ace_units_and_device_numbers(tmp_path):
    for name, (vid, pid, devnum) in {"3-1.3.2": ("28e9", "018a", 12), "3-1.3.3": ("28e9", "018a", 40),
                                     "1-1": ("1d50", "614e", 3)}.items():
        d = tmp_path / name
        d.mkdir()
        (d / "idVendor").write_text(vid + "\n")
        (d / "idProduct").write_text(pid + "\n")
        (d / "devnum").write_text(f"{devnum}\n")
    (tmp_path / "usb1").mkdir()   # a hub entry without ids
    src = open(os.path.join(os.path.dirname(__file__), "..", "printer_intent.py")).read()
    ns = {"os": os, "Optional": __import__("typing").Optional, "Dict": __import__("typing").Dict, "Any": __import__("typing").Any}
    exec(src[src.index("ACE_USB_IDS"):src.index("class PrinterIntent")], ns)
    assert ns["units_on_usb"](str(tmp_path)) == {"3-1.3.2": 12, "3-1.3.3": 40}
    assert ns["units_on_usb"](str(tmp_path / "nope")) is None


def test_a_unit_that_keeps_reconnecting_is_called_out():
    t = tracker_two_units_known_one()
    t.observe_usb_units({"3-1.1.3": 10, "3-1.3.3": 20}, now=0)
    for i, devnum in enumerate((21, 22, 23), start=1):   # 1.3.3 comes back three times
        t.observe_usb_units({"3-1.1.3": 10, "3-1.3.3": devnum}, now=i * 5)
    u = t.units()
    assert u["flapping"] == 1 and u["actions"] == []
    assert u["notice"]["headline"] == "A filament unit keeps disconnecting."
    assert "3 times" in u["notice"]["detail"]
    i = t.intent(now=20)
    assert i["phase"] == "unit_flapping" and i["actions"] == []   # no Look again: it can't help
    # quiet for over two minutes: back to normal
    t.observe_usb_units({"3-1.1.3": 10, "3-1.3.3": 23}, now=200)
    assert t.units()["flapping"] == 0


def test_one_reconnect_is_not_flapping():
    t = tracker_two_units_known_one()
    t.observe_usb_units({"3-1.1.3": 10, "3-1.3.3": 20}, now=0)
    t.observe_usb_units({"3-1.1.3": 10, "3-1.3.3": 21}, now=5)
    assert t.units()["flapping"] == 0


# ---- what the file's sheet says about each filament (design/print-library/, B) ----

def test_uses_names_the_slot_each_filament_comes_from():
    r = a.check_print("stand.gcode", meta(["#D9534F", "#F1F1F1"], ["PLA", "PLA"]), LOADED)
    assert [u["line"] for u in r["uses"]] == ["Red PLA is loaded, slot 1", "White PLA is loaded, slot 2"]
    assert [u["slot"] for u in r["uses"]] == [0, 1] and all(u["loaded"] for u in r["uses"])


def test_uses_says_what_isnt_loaded():
    r = a.check_print("holder.gcode", meta(["#2B2B2B", "#FF8800"], ["PETG", "PLA"]), LOADED)
    assert [(u["line"], u["loaded"]) for u in r["uses"]] == [
        ("Black PETG isn't loaded", False), ("Orange PLA isn't loaded", False)]


def test_uses_without_a_unit_only_names_the_filament():
    r = a.check_print("a.gcode", meta(["#FF8800"], ["PETG"]), [])
    assert r["uses"] == [{"color": "#FF8800", "material": "PETG", "loaded": None, "slot": None, "line": "Uses Orange PETG"}]
    assert a.check_print("a.gcode", None, LOADED)["uses"] == []
