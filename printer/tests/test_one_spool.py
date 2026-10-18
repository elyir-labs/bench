"""A printer without a filament unit: one spool, known from what a person said, Spoolman,
or a guess from the last print, and asked about when that isn't enough."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

SENSOR = "filament_switch_sensor toolhead_sensor"


def tracker(head=True, sensor=True, now=0.0):
    t = a.IntentTracker("Desk", now=now)
    t.set_klippy_state("ready", "Printer is ready", now=now)
    t.has_unit = False
    status = {"print_stats": {"state": "standby", "filename": ""}, "heater_bed": {"target": 0},
              "extruder": {"temperature": 25, "target": 0}, "ace": {}}   # Klipper answers {} for a missing object
    if sensor:
        t.head_sensor = SENSOR
        status[SENSOR] = {"filament_detected": head}
    t.update_status(status, now=now)
    return t


def spool(t):
    spools = t.intent(now=100.0)["spools"]
    assert len(spools) == 1
    return spools[0]


def meta(color, material):
    return {"filament_colors": [color], "filament_type": material}


def plan(t, action, **args):
    return a.plan_action(action, args, t)


# ---- what the one spool shows ------------------------------------------------------

def test_nothing_known_is_one_unknown_spool_in_the_head():
    s = spool(tracker())
    assert s["direct"] and s["source"] == "unknown" and s["name"] is None
    assert s["status"] == "ready" and s["in_use"]
    # moving filament is the change routine's job (test_change_filament.py); no quiet fix here
    assert [x["id"] for x in s["actions"]] == ["change_start", "change_start"] and s["fix"] is None


def test_no_sensor_and_nothing_known_is_unknown():
    assert spool(tracker(sensor=False))["status"] == "unknown"


def test_told_spool_shows_its_name_and_when():
    t = tracker()
    t.remember_spool("#111111", "petg", now=50.0)
    s = spool(t)
    assert (s["name"], s["material"], s["source"]) == ("Black PETG", "PETG", "told")
    assert s["since"] == a._iso(50.0) and not s["changed"]


def test_empty_head_keeps_the_last_name():
    t = tracker(head=False)
    t.remember_spool("#FFFFFF", "PLA", now=50.0)
    s = spool(t)
    assert s["status"] == "empty" and s["name"] == "White PLA" and not s["in_use"]


def test_spoolman_wins_and_brings_grams():
    t = tracker()
    t.remember_spool("#FFFFFF", "PLA")
    t.spoolman_spool = {"color": "FF8800", "material": "PETG", "grams": 642.4}
    s = spool(t)
    assert (s["source"], s["name"], s["grams"], s["status"]) == ("spoolman", "Orange PETG", 642, "ready")
    t.spoolman_spool["grams"] = 50
    assert spool(t)["status"] == "low"


def test_a_unit_printer_is_unchanged():
    t = tracker()
    t.has_unit = True
    assert t.intent(now=100.0)["spools"] == []


def test_no_unit_notices_or_look_again():
    t = tracker()
    t.set_units_on_usb(0)
    i = t.intent(now=100.0)
    assert i["units"] is None
    assert i["head"]["mismatch"] is None and i["head"]["notice"] is None


# ---- filament out and back in -------------------------------------------------------

def test_filament_out_and_back_might_be_a_different_spool():
    t = tracker(head=True)
    t.remember_spool("#111111", "PLA", now=10.0)
    t.update_status({SENSOR: {"filament_detected": False}}, now=20.0)
    assert not spool(t)["changed"]
    t.update_status({SENSOR: {"filament_detected": True}}, now=30.0)
    s = spool(t)
    assert s["changed"] and s["name"] is None and s["material"] is None
    assert s["was"] == {"name": "Black PLA", "color": "#111111", "material": "PLA"}
    assert t.direct_spool_dirty


def test_told_while_empty_then_loaded_is_not_a_change():
    t = tracker(head=True)
    t.update_status({SENSOR: {"filament_detected": False}}, now=20.0)
    t.remember_spool("#111111", "PETG", now=25.0)
    t.update_status({SENSOR: {"filament_detected": True}}, now=30.0)
    assert not spool(t)["changed"] and spool(t)["name"] == "Black PETG"


def test_saying_what_it_is_clears_the_change():
    t = tracker(head=True)
    t.remember_spool("#111111", "PLA", now=10.0)
    t.update_status({SENSOR: {"filament_detected": False}}, now=20.0)
    t.update_status({SENSOR: {"filament_detected": True}}, now=30.0)
    for kind, payload in plan(t, "set_spool", slot=0, color="#FF8800", material="PETG"):
        assert kind == a.ActionPlan.REMEMBER_SPOOL
        t.remember_spool(payload["color"], payload["material"], now=40.0)
    s = spool(t)
    assert not s["changed"] and s["name"] == "Orange PETG" and s["source"] == "told"


def test_restored_record_survives_a_restart():
    t = tracker()
    t.remember_spool("#111111", "PLA", now=10.0)
    record = dict(t.direct_spool)
    t2 = tracker()
    t2.restore_spool(record)
    assert spool(t2)["name"] == "Black PLA" and not t2.direct_spool_dirty
    t3 = tracker()
    t3.restore_spool({"source": "nonsense"})
    assert spool(t3)["source"] == "unknown"


# ---- a guess from the print ---------------------------------------------------------

def start_print(t, filename, m, now=60.0):
    t.update_status({"print_stats": {"state": "printing", "filename": filename}}, now=now)
    t.set_metadata(filename, m)


def test_a_print_with_nothing_known_leaves_a_guess():
    t = tracker()
    start_print(t, "benchy.gcode", meta("#222222", "PETG"))
    s = spool(t)
    assert (s["source"], s["name"], s["guess_from"]) == ("guess", "Black PETG", "Benchy")


def test_a_print_doesnt_overwrite_what_someone_said():
    t = tracker()
    t.remember_spool("#FFFFFF", "PLA", now=10.0)
    start_print(t, "benchy.gcode", meta("#222222", "PETG"))
    assert spool(t)["source"] == "told" and spool(t)["name"] == "White PLA"


def test_a_print_after_a_change_becomes_the_guess():
    t = tracker()
    t.remember_spool("#FFFFFF", "PLA", now=10.0)
    t.update_status({SENSOR: {"filament_detected": False}}, now=20.0)
    t.update_status({SENSOR: {"filament_detected": True}}, now=30.0)
    start_print(t, "benchy.gcode", meta("#222222", "PETG"))
    s = spool(t)
    assert s["source"] == "guess" and not s["changed"] and s["name"] == "Black PETG"


def test_a_multicolour_file_leaves_no_guess():
    t = tracker()
    start_print(t, "two.gcode", {"filament_colors": ["#222222", "#FFFFFF"], "filament_type": "PLA;PLA"})
    assert spool(t)["source"] == "unknown"


# ---- at print time --------------------------------------------------------------------

def check(t, color, material):
    return a.check_print("vase.gcode", meta(color, material), t.spools())


def test_told_and_matching_prints_without_a_word():
    t = tracker()
    t.remember_spool("#222222", "PLA+")
    assert check(t, "#202020", "PLA")["ok"]


def test_told_and_different_says_what_is_loaded():
    t = tracker()
    t.remember_spool("#FFFFFF", "PLA")
    r = check(t, "#222222", "PETG")
    assert not r["ok"] and not r["ask"]
    assert r["headline"] == "This needs Black PETG."
    assert r["detail"].startswith("White PLA is loaded.") and "behave differently" in r["detail"]
    assert [x["id"] for x in r["actions"]] == ["confirm_spool", "start_file"]
    assert r["actions"][0]["args"] == {"filename": "vase.gcode", "color": "#222222", "material": "PETG"}


def test_a_file_with_no_colour_checks_only_the_material():
    """Sliced with no colour chosen: Orca writes `filament_colour = ""` (8 October 2026)."""
    t = tracker()
    t.remember_spool(None, "PETG")
    for none in ("", '""'):
        assert check(t, none, "PETG")["ok"]
    assert check(t, "", "PLA")["headline"] == "This needs PLA."


def test_told_same_material_other_colour_mentions_the_colour():
    t = tracker()
    t.remember_spool("#FFFFFF", "PETG")
    assert "color will be different" in check(t, "#222222", "PETG")["detail"]


def test_unknown_asks_and_the_answer_is_remembered():
    t = tracker()
    r = check(t, "#222222", "PETG")
    assert not r["ok"] and r["ask"]
    assert r["headline"] == "This file uses Black PETG. Is that what's loaded?"
    assert [x["id"] for x in r["actions"]] == ["confirm_spool", "open_materials"]
    p = plan(t, "confirm_spool", **r["actions"][0]["args"])
    assert p == [(a.ActionPlan.REMEMBER_SPOOL, {"color": "#222222", "material": "PETG"}),
                 (a.ActionPlan.START_FILE, "vase.gcode")]


def test_matching_guess_doesnt_ask_but_a_different_one_does():
    t = tracker()
    t.remember_spool("#222222", "PETG", source="guess", filename="benchy.gcode")
    assert check(t, "#222222", "PETG")["ok"]
    r = check(t, "#FFFFFF", "PLA")
    assert r["ask"] and r["detail"] == "Your last print used Black PETG."


def test_changed_asks_and_says_what_was_there():
    t = tracker(head=True)
    t.remember_spool("#222222", "PETG", now=10.0)
    t.update_status({SENSOR: {"filament_detected": False}}, now=20.0)
    t.update_status({SENSOR: {"filament_detected": True}}, now=30.0)
    r = check(t, "#222222", "PETG")
    assert r["ask"] and r["detail"] == "The filament has been changed since Black PETG."


def test_empty_head_says_load_it_first():
    t = tracker(head=False)
    r = check(t, "#222222", "PETG")
    assert r["headline"] == "Load Black PETG first."
    assert [x["id"] for x in r["actions"]] == ["confirm_spool", "start_file"]


def test_spoolman_mismatch_points_to_the_spool_not_a_confirm():
    t = tracker()
    t.spoolman_spool = {"color": "#FFFFFF", "material": "PLA", "grams": 500}
    r = check(t, "#222222", "PETG")
    assert [x["id"] for x in r["actions"]] == ["open_materials", "start_file"]


# ---- actions ---------------------------------------------------------------------------

def test_set_spool_needs_a_material_and_takes_no_unit_commands():
    t = tracker()
    assert plan(t, "set_spool", slot=0, color="#FFFFFF", material="") == []
    assert plan(t, "set_spool", slot=0, material="PLA") == [(a.ActionPlan.REMEMBER_SPOOL, {"color": None, "material": "PLA"})]
    assert plan(t, "load_spool", slot=0) == [] and plan(t, "unload_spool") == []
    assert plan(t, "mark_loaded", slot=0) == []


def test_confirm_spool_only_without_a_unit():
    t = tracker()
    t.has_unit = True
    assert plan(t, "confirm_spool", filename="vase.gcode", material="PLA") == []


def test_runout_doesnt_talk_about_slots():
    t = tracker()
    t.remember_spool("#222222", "PETG")
    t.update_status({"print_stats": {"state": "printing", "filename": "vase.gcode"}}, now=60.0)
    t.on_gcode_response("// Filament runout detected", now=61.0)
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=62.0)
    i = t.intent(now=63.0)
    assert i["headline"] == "Black PETG ran out."
    # the change routine loads it, so the print only carries on once it reaches the nozzle
    assert "slot" not in i["detail"] and "Load a new spool and I'll walk you through it." in i["detail"]
    assert i["actions"][0]["id"] == "change_start"


def test_the_ready_line_says_what_is_loaded():
    t = tracker()
    assert t.intent(now=100.0)["detail"] == "Filament loaded."
    t.remember_spool("#222222", "PETG", source="guess")
    assert t.intent(now=100.0)["detail"] == "Probably Black PETG loaded."
    t.remember_spool("#222222", "PETG")
    i = t.intent(now=100.0)
    assert (i["detail"], i["phase"]) == ("Black PETG loaded.", "idle")
    assert [x["label"] for x in i["actions"]] == ["Warm up for PETG", "Something else"]   # test_warm_up.py
    t.update_status({SENSOR: {"filament_detected": False}}, now=200.0)
    assert t.intent(now=200.0)["detail"] == "No filament loaded."
    assert tracker(sensor=False).intent(now=100.0)["detail"] == ""


def test_spools_that_were_on_before_become_quick_answers():
    t = tracker(head=True)
    t.remember_spool("#FFFFFF", "PLA", now=1.0)
    t.remember_spool("#FF8800", "PETG", now=2.0)
    t.remember_spool("#FAFAFA", "PLA", now=3.0)     # white PLA again: not listed twice
    t.remember_spool("#222222", "PETG", now=4.0)
    s = spool(t)
    assert [r["name"] for r in s["recent"]] == ["White PLA", "Orange PETG"]
    # filament out and back in: "Same as before" is the black PETG, so it isn't in the list too
    t.update_status({SENSOR: {"filament_detected": False}}, now=5.0)
    t.update_status({SENSOR: {"filament_detected": True}}, now=6.0)
    s = spool(t)
    assert s["was"]["name"] == "Black PETG"
    assert [r["name"] for r in s["recent"]] == ["White PLA", "Orange PETG"]
    t.remember_spool("#FF8800", "PETG", now=7.0)    # it was the orange
    assert [r["name"] for r in spool(t)["recent"]] == ["Black PETG", "White PLA"]
