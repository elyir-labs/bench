"""Loading, unloading and correcting which spool is in the head."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

SENSOR = "filament_switch_sensor extruder_sensor"


def tracker(selected=0, head=True, colors=("00FF00", "0000FF", "75787B", "75787B"),
            materials=("PETG", "PETG", "PETG", "PLA"), slot_status=("ready", "ready", "ready", "empty"), now=0.0):
    t = a.IntentTracker("Workshop", now=now)
    t.set_klippy_state("ready", "Printer is ready", now=now)
    t.head_sensor = SENSOR
    t.update_status({
        "print_stats": {"state": "standby"}, "heater_bed": {"target": 0}, "extruder": {"temperature": 25, "target": 0},
        "ace": {"selected_gate": selected, "gate_color": list(colors), "gate_material": list(materials),
                "slots": [{"status": st} for st in slot_status]},
        SENSOR: {"filament_detected": head},
    }, now=now)
    return t


def plan(t, action, **args):
    return a.plan_action(action, args, t)


# ---- what gets planned ----------------------------------------------------------

def test_switching_colour_purges():
    p = plan(tracker(selected=0), "load_spool", slot=1)
    assert p == [(a.ActionPlan.SWAP, {"to": 1, "from": 0, "purge": True})]
    assert a.swap_gcode(p[0][1]) == "ACE_CHANGE_TOOL TOOL=1"


def test_same_colour_and_material_skips_the_purge():
    t = tracker(selected=2, materials=("PETG", "PETG", "PETG", "PETG"), slot_status=("ready",) * 4)
    p = plan(t, "load_spool", slot=3)   # grey PETG -> grey PETG
    assert p[0][1]["purge"] is False
    assert a.swap_gcode(p[0][1]) == "ACE_CHANGE_TOOL TOOL=3 PURGE=0"


def test_same_colour_other_material_purges():
    t = tracker(selected=2, slot_status=("ready",) * 4)   # grey PETG -> grey PLA
    assert plan(t, "load_spool", slot=3)[0][1]["purge"] is True


def test_empty_head_remembers_what_came_out():
    t = tracker(selected=2, materials=("PETG",) * 4, slot_status=("ready",) * 4)
    t.begin_swap(-1, 2, False, now=1)       # unload grey PETG
    t.end_swap(None, now=60)
    t.update_status({"ace": {"selected_gate": -1}, SENSOR: {"filament_detected": False}}, now=60)
    assert plan(t, "load_spool", slot=3)[0][1]["purge"] is False   # grey PETG again
    assert plan(t, "load_spool", slot=0)[0][1]["purge"] is True    # green


def test_unknown_previous_filament_purges():
    t = tracker(selected=-1, head=False)
    assert plan(t, "load_spool", slot=1)[0][1] == {"to": 1, "from": None, "purge": True}


def test_refusals():
    assert plan(tracker(), "load_spool", slot=3) == []      # slot 4 is empty
    assert plan(tracker(), "load_spool", slot=0) == []      # already loaded
    assert plan(tracker(), "load_spool", slot="x") == []
    t = tracker()
    t.update_status({"print_stats": {"state": "printing"}}, now=1)
    assert plan(t, "load_spool", slot=1) == [] and plan(t, "unload_spool") == [] and plan(t, "mark_loaded", slot=1) == []
    t = tracker()
    t.begin_swap(1, 0, True, now=1)
    assert plan(t, "load_spool", slot=2) == []              # one at a time
    t = tracker()
    t.set_klippy_state("error", "mcu 'EBBCan': Unable to connect", now=1)
    assert plan(t, "load_spool", slot=1) == []


def test_in_a_paused_print_the_head_can_be_corrected_but_nothing_moves():
    t = tracker(selected=2, head=False)
    t.update_status({"print_stats": {"state": "paused"}}, now=1)
    assert plan(t, "mark_loaded", slot=-1) == [(a.ActionPlan.GCODE, "ACE_SET_GATE GATE=-1")]
    assert plan(t, "load_spool", slot=1) == [] and plan(t, "unload_spool") == []
    t.intent(now=1)
    assert [x["id"] for x in t.intent(now=12)["head"]["actions"]] == ["mark_loaded", "head_ok"]


def test_unload_needs_something_loaded():
    assert plan(tracker(selected=0), "unload_spool") == [(a.ActionPlan.SWAP, {"to": -1, "from": 0, "purge": False})]
    assert plan(tracker(selected=-1, head=False), "unload_spool") == []
    assert a.swap_gcode({"to": -1, "from": 0, "purge": False}) == "ACE_CHANGE_TOOL TOOL=-1"


def test_mark_loaded_never_moves_anything():
    assert plan(tracker(), "mark_loaded", slot=2) == [(a.ActionPlan.GCODE, "ACE_SET_GATE GATE=2")]
    assert plan(tracker(), "mark_loaded", slot=-1) == [(a.ActionPlan.GCODE, "ACE_SET_GATE GATE=-1")]
    assert plan(tracker(), "mark_loaded", slot=9) == []


# ---- while it runs -----------------------------------------------------------------

def test_switch_shows_steps_from_the_units_console_lines():
    t = tracker(selected=0)
    t.begin_swap(1, 0, True, now=10)
    i = t.intent(now=11)
    assert i["state"] == "preparing" and i["headline"] == "Switching to Blue PETG"
    assert [s["id"] for s in i["steps"]] == ["unload", "feed", "nozzle", "clean", "check"]   # the colour changes: a person checks it
    assert [s["status"] for s in i["steps"]] == ["now", "todo", "todo", "todo", "todo"]
    assert i["steps"][0]["label"] == "Taking out Green PETG"
    t.on_gcode_response("// ACE: Unloading tool 0...", now=12)
    t.on_gcode_response("// ACE: Feeding from gate to extruder", now=40)
    i = t.intent(now=41)
    assert i["phase"] == "swap_feed" and [s["status"] for s in i["steps"]] == ["done", "now", "todo", "todo", "todo"]
    t.update_status({"extruder": {"temperature": 180, "target": 240}}, now=50)
    assert t.intent(now=50)["detail"] == "Nozzle at 180° of 240°."
    assert i["spools"][1]["actions"] == []        # nothing else moves while this runs


def test_load_into_empty_head_and_no_purge_has_no_unload_or_clean_steps():
    t = tracker(selected=-1, head=False)
    t.begin_swap(1, None, False, now=10)
    i = t.intent(now=11)
    assert i["headline"] == "Loading Blue PETG"
    assert [s["id"] for s in i["steps"]] == ["feed", "nozzle"]


def test_failed_swap_explains_and_offers_try_again():
    t = tracker(selected=0)
    t.begin_swap(1, 0, True, now=10)
    t.end_swap("ACE Error: Gate 1 is not ready (status: empty)", now=20)
    i = t.intent(now=21)
    assert i["state"] == "problem" and i["phase"] == "swap_failed"
    assert i["headline"] == "Loading Blue PETG didn't finish."
    assert "Push the filament into the unit" in i["detail"]
    assert [x["id"] for x in i["actions"]] == ["load_spool", "dismiss_swap"]
    assert i["actions"][0]["args"] == {"slot": 1}
    assert plan(t, "dismiss_swap") == [(a.ActionPlan.ACK_SWAP, None)]
    t.ack_swap()
    assert t.intent(now=22)["state"] == "ready"


def test_finished_swap_goes_back_to_ready():
    t = tracker(selected=0)
    t.begin_swap(1, 0, True, now=10)
    t.end_swap(None, now=100)
    t.update_status({"ace": {"selected_gate": 1}}, now=100)
    assert t.intent(now=101)["phase"] == "change_check"   # "Is it coming out clean?" first
    t.change_input({"op": "good"}, now=102)
    assert t.intent(now=103)["state"] == "ready"


# ---- when the printer's memory and the sensor disagree -------------------------------

def test_filament_in_head_but_no_spool_known():
    t = tracker(selected=-1, head=True)
    assert t.intent(now=1)["head"]["mismatch"] is None          # give it a moment
    i = t.intent(now=12)
    assert i["head"]["mismatch"] == "unknown_spool" and i["phase"] == "head_unknown_spool"
    assert i["head"]["notice"]["headline"] == "There's filament in the head, but I don't know which spool."
    assert [c["args"]["slot"] for c in i["head"]["choices"]] == [0, 1, 2]   # the empty slot isn't offered
    assert i["head"]["choices"][1]["label"] == "Blue PETG"


def test_lookalike_spools_are_told_apart_by_slot():
    t = tracker(selected=-1, head=True, colors=("FFFFFF", "0000FF", "FFFFFF", "FFFFFF"),
                materials=("PLA", "PETG", "PLA", "PLA"))
    t.intent(now=1)
    labels = [c["label"] for c in t.intent(now=12)["head"]["choices"]]
    assert labels == ["White PLA (slot 1)", "Blue PETG", "White PLA (slot 3)"]


def test_head_empty_but_a_spool_thought_loaded():
    t = tracker(selected=2, head=False)
    t.intent(now=1)
    i = t.intent(now=12)
    assert i["head"]["notice"]["headline"] == "The head looks empty, but I think Gray PETG is loaded."
    assert [(x["id"], x.get("args")) for x in i["head"]["actions"]] == [
        ("mark_loaded", {"slot": -1}), ("head_ok", None), ("unload_spool", None)]
    assert i["head"]["actions"][1]["label"] == "Gray PETG is loaded"
    assert [x["id"] for x in i["actions"]] == ["mark_loaded", "head_ok"]   # both answers on Now


def test_saying_the_spool_is_loaded_quiets_the_sensor():
    t = tracker(selected=0, head=False)
    t.intent(now=1)
    assert t.intent(now=12)["head"]["mismatch"] == "phantom_spool"
    assert plan(t, "head_ok") == [(a.ActionPlan.ACK_HEAD, None)]
    t.ack_head()
    i = t.intent(now=13)
    assert i["head"]["mismatch"] is None and i["phase"] != "head_phantom_spool"
    assert i["head"]["slot"] == 0
    assert t.intent(now=100)["head"]["mismatch"] is None          # and it stays quiet


def test_the_word_lasts_until_the_sensor_or_spool_changes():
    t = tracker(selected=0, head=False)
    t.intent(now=1)
    t.intent(now=12)
    t.ack_head()
    t.update_status({SENSOR: {"filament_detected": True}}, now=20)
    t.intent(now=20)                                               # they agree again: the word is spent
    t.update_status({SENSOR: {"filament_detected": False}}, now=30)
    t.intent(now=30)
    assert t.intent(now=41)["head"]["mismatch"] == "phantom_spool"
    t.ack_head()
    t.update_status({"ace": {"selected_gate": 1}}, now=50)       # a different spool: ask about that one
    t.intent(now=50)
    assert t.intent(now=61)["head"]["mismatch"] == "phantom_spool"


def test_head_ok_only_when_the_sensor_reads_empty():
    assert plan(tracker(selected=0, head=True), "head_ok") == []
    assert plan(tracker(selected=-1, head=False), "head_ok") == []


def test_no_mismatch_right_after_a_swap():
    t = tracker(selected=-1, head=True)
    t.begin_swap(1, None, True, now=0)
    t.end_swap(None, now=5)
    t.intent(now=6)
    assert t.intent(now=20)["head"]["mismatch"] is None          # inside the quiet window
    t.intent(now=36)
    assert t.intent(now=47)["head"]["mismatch"] == "unknown_spool"


def test_no_sensor_no_guessing():
    t = tracker(selected=-1, head=True)
    t.head_sensor = None
    t.intent(now=1)
    assert t.intent(now=60)["head"] == {"loaded": None, "slot": None, "mismatch": None, "notice": None, "actions": [], "choices": []}


# ---- what tapping a spool offers -----------------------------------------------------

def test_spool_actions():
    i = tracker(selected=0).intent(now=1)
    s0, s1, s3 = i["spools"][0], i["spools"][1], i["spools"][3]
    assert [x["label"] for x in s0["actions"]] == ["Unload", "Swap the spool"] and s0["fix"]["args"] == {"slot": -1}
    assert s1["actions"][0]["label"] == "Switch to this spool" and s1["actions"][0]["args"] == {"slot": 1}
    assert "cleans the nozzle" in s1["note"]
    assert s1["fix"]["label"] == "Already in the head? Mark as in use"
    assert s3["actions"] == []                                     # empty slot: hands load it (design/slots/)
    assert s3["fix"]["id"] == "move_filament" and s3["fix"]["args"] == {"slot": 3, "mm": 100}
    assert "push its end into slot 4" in s3["note"]
    i = tracker(selected=-1, head=False).intent(now=1)
    assert i["spools"][1]["actions"][0]["label"] == "Load this spool"


def test_no_spool_actions_while_printing():
    t = tracker()
    t.update_status({"print_stats": {"state": "printing"}}, now=1)
    assert all(s["actions"] == [] and s["fix"] is None for s in t.intent(now=2)["spools"])


def test_head_sensor_is_found_by_name():
    names = ["temperature_sensor Chamber", "filament_switch_sensor extruder_sensor", "query_endstops"]
    assert a.IntentTracker.head_sensor_name(names) == "filament_switch_sensor extruder_sensor"
    assert a.IntentTracker.head_sensor_name(names + ["filament_switch_sensor toolhead"]) == "filament_switch_sensor toolhead"
    assert a.IntentTracker.head_sensor_name(["filament_switch_sensor runout"]) is None
