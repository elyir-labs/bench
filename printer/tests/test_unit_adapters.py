"""Happy Hare and AFC as filament units Bench drives (design/ace-driver/, stage 5): their status read into the same
slots, their own commands sent, and nothing offered that the unit can't do."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402
import filament_units as fu  # noqa: E402

P = a.ActionPlan


def same(was, now):
    return str(was or "").upper() == now


ERCF = {   # Happy Hare v4 on an ERCF: six gates, gate 2 in the head, gate 4 empty, gate 5 not checked yet
    "mmu": {"enabled": True, "num_gates": 6, "gate": 2, "tool": 2, "filament": "Loaded", "action": "Idle",
            "gate_status": [1, 1, 2, 1, 0, -1],
            "gate_material": ["PLA", "PETG", "PLA", "ASA", "", ""],
            "gate_color": ["ff0000", "00ff00", "ffffffff", "", "", ""],
            "gate_temperature": [210, 240, 215, 260, 200, 200],
            "endless_spool_enabled": 1},
    "mmu_machine": {"happy_hare_version": 4.1, "num_units": 1, "num_gates": 6,
                    "unit_0": {"name": "ercf", "display_name": "ERCF", "first_gate": 0, "num_gates": 6, "selector_type": "LinearSelector"}},
}


def lane(name, unit, load=True, prep=True, color="#FF0000", material="PLA", tool=False, temp=None):
    return {"name": name, "unit": unit, "load": load, "prep": prep, "tool_loaded": tool, "color": color,
            "material": material, "extruder_temp": temp, "map": None}


AFC = {   # a Box Turtle and a Night Owl, listed out of order; leg2 is in the head, lane3 has only just gone in
    "AFC": {"lanes": ["lane1", "leg1", "lane2", "lane3", "leg2"], "current_load": "leg2", "current_state": "Idle"},
    "AFC_stepper lane1": lane("lane1", "Turtle_1", color="#ff0000"),
    "AFC_stepper lane2": lane("lane2", "Turtle_1", load=False, prep=False, color="", material=None),
    "AFC_stepper lane3": lane("lane3", "Turtle_1", load=False, prep=True),
    "AFC_lane leg1": lane("leg1", "Owl_1", color="#00FF00", material="PETG", temp=240),
    "AFC_lane leg2": lane("leg2", "Owl_1", color="#0000FF", material="ASA", tool=True),
}


def tracker(status, watch_only=False):
    t = a.IntentTracker("Workshop")
    t.has_unit = True
    t.units_watch_only = watch_only
    t.set_klippy_state("ready")
    t.update_status({"print_stats": {"state": "standby"}, "extruder": {"temperature": 25, "target": 0}, **status})
    return t


# ---- Happy Hare ----------------------------------------------------------------------

def test_happy_hare_reads_gates_the_head_and_carry_on():
    u = fu.read(ERCF)
    assert u["driver"] == "happy_hare" and u["selected"] == 2 and u["carry_on"] is True
    assert [(s["status"], s["color"], s["material"]) for s in u["slots"]] == [
        ("ready", "#FF0000", "PLA"), ("ready", "#00FF00", "PETG"), ("ready", "#FFFFFF", "PLA"),
        ("ready", None, "ASA"), ("empty", None, None), ("unknown", None, None)]
    assert u["lists"]["temp"][3] == 260 and u["lists"]["material"][1] == "PETG"
    unloaded = fu.read({**ERCF, "mmu": dict(ERCF["mmu"], filament="Unloaded")})
    assert unloaded["selected"] is None   # the selector stays on gate 2 with nothing in the head


def test_the_gcode_happy_hare_takes():
    hh = fu.commands(fu.read(ERCF))
    assert hh.name == "happy_hare" and hh.kind == "gcode"
    assert hh.change_tool(3) == "MMU_CHANGE_TOOL GATE=3 STANDALONE=1"
    assert hh.change_tool(3, purge=False) == "MMU_CHANGE_TOOL GATE=3 STANDALONE=1 SKIP_PURGE=1"
    assert hh.change_tool(-1) == "MMU_UNLOAD"
    assert hh.mark_loaded(1) == "MMU_RECOVER GATE=1 LOADED=1" and hh.mark_loaded(-1) == "MMU_RECOVER LOADED=0"
    assert hh.carry_on(False) == "MMU_ENDLESS_SPOOL ENABLE=0"
    lists = fu.read(ERCF)["lists"]
    temps = {"PLA": 210, "PETG": 240}
    # the gate keeps its temperature when the material doesn't change; Happy Hare would reset it if TEMP were left out
    assert hh.set_spool(lists, 6, 3, "#AABBCC", "ASA", temps, same) == [
        "MMU_GATE_MAP GATE=3 COLOR=aabbcc MATERIAL=ASA TEMP=260"]
    assert hh.set_spool(lists, 6, 0, "#AABBCC", "PETG", temps, same) == [
        "MMU_GATE_MAP GATE=0 COLOR=aabbcc MATERIAL=PETG TEMP=240"]
    for what in ("move", "dry", "stop_drying", "feed_assist"):
        assert not fu.can(hh, what)


def test_a_kobra_reporting_happy_hares_shape_stays_watched():
    t = tracker(ERCF, watch_only=True)
    assert t.unit_commands() is None and a.plan_spool_move("load_spool", {"slot": 0}, t) == []


def test_happy_hare_loads_unloads_and_sets_spools_from_the_screen():
    t = tracker(ERCF)
    steps = a.plan_spool_move("load_spool", {"slot": 0}, t)
    assert steps and steps[0][0] == P.SWAP and steps[0][1]["to"] == 0
    assert a.swap_gcode(steps[0][1], t.unit_commands()).startswith("MMU_CHANGE_TOOL GATE=0 STANDALONE=1")
    assert a.plan_spool_move("unload_spool", {}, t)[0][1]["to"] == -1
    assert a.plan_action("carry_on", {"on": False}, t) == [("gcode", "MMU_ENDLESS_SPOOL ENABLE=0")]
    assert a.plan_set_spool({"slot": 1, "color": "#112233", "material": "PETG"}, t) == [
        ("gcode", "MMU_GATE_MAP GATE=1 COLOR=112233 MATERIAL=PETG TEMP=240")]


def test_nothing_is_offered_that_happy_hare_cant_do():
    t = tracker(ERCF)
    for action, args in (("move_filament", {"slot": 1, "mm": 50}), ("feed_assist", {"slot": 2, "on": True}),
                         ("dry_unit", {"unit": 0, "hours": 4}), ("stop_drying", {"unit": 0})):
        assert a.plan_slot(action, args, t) == [], action
    assert all(not u["actions"] for u in t.unit_list(t.spools(), now=0))   # no dryer, no Dry
    spools = {s["slot"]: s for s in t.spools()}
    acts = t.spool_actions(spools[0], can_move=True)
    assert acts["move"] is False and acts["actions"][0]["id"] == "load_spool"
    assert t.spool_actions(spools[4], can_move=True)["fix"] is None   # no "Pull it in" without a move


def test_a_swap_on_happy_hare_asks_a_person_to_pull_the_spool_out():
    t = tracker(ERCF)
    for kind, payload in a.plan_action("swap_start", {"slot": 1}, t):
        assert kind == P.SLOT
        t.slot_input(payload, now=1)
    assert t.work(now=2) == []          # the unit can't pull back: straight to the person
    assert t._change["step"] == "swap" and t._change["stuck"] is True


# ---- AFC -----------------------------------------------------------------------------

def test_afc_reads_lanes_grouped_by_unit():
    u = fu.read(AFC)
    assert u["driver"] == "afc" and u["lanes"] == ["lane1", "lane2", "lane3", "leg1", "leg2"]
    assert [(x["alias"], x["offset"], x["n"], x["dryer"]) for x in u["units"]] == [("Turtle 1", 0, 3, None), ("Owl 1", 3, 2, None)]
    assert u["selected"] == 4 and u["carry_on"] is None and u["feed_assist"] is None
    assert [(s["status"], s["color"], s["material"]) for s in u["slots"]] == [
        ("ready", "#FF0000", "PLA"), ("empty", None, None), ("unknown", None, None),
        ("ready", "#00FF00", "PETG"), ("ready", "#0000FF", "ASA")]
    assert fu.read({"AFC": {"lanes": []}}) is None
    assert fu.afc_lane_objects(["AFC", "AFC_stepper lane1", "AFC_lane leg1", "AFC_hub Turtle_1", "extruder"]) == [
        "AFC_stepper lane1", "AFC_lane leg1"]


def test_the_gcode_afc_takes_names_the_lane():
    afc = fu.commands(fu.read(AFC))
    assert afc.name == "afc"
    assert afc.change_tool(3) == "CHANGE_TOOL LANE=leg1" and afc.change_tool(-1) == "TOOL_UNLOAD"
    assert afc.move(0, -300) == "LANE_MOVE LANE=lane1 DISTANCE=-300"
    assert afc.mark_loaded(4) == "SET_LANE_LOADED LANE=leg2" and afc.mark_loaded(-1) == "UNSET_LANE_LOADED"
    assert afc.set_spool({}, 5, 1, "#AABBCC", "PETG", {}, same) == [
        "SET_COLOR LANE=lane2 COLOR=AABBCC", "SET_MATERIAL LANE=lane2 MATERIAL=PETG"]
    assert not fu.can(afc, "dry") and not fu.can(afc, "carry_on") and fu.can(afc, "move")


def test_afc_from_the_screen():
    t = tracker(AFC)
    steps = a.plan_spool_move("load_spool", {"slot": 0}, t)
    assert a.swap_gcode(steps[0][1], t.unit_commands()) == "CHANGE_TOOL LANE=lane1"
    assert a.plan_slot("move_filament", {"slot": 0, "mm": -a.MOVE_STEPS_MM[0]}, t) == [
        ("gcode", f"LANE_MOVE LANE=lane1 DISTANCE={-a.MOVE_STEPS_MM[0]}")]
    assert a.plan_slot("carry_on", {"on": True}, t) == []
    assert all(not u["actions"] for u in t.unit_list(t.spools(), now=0))
    # a swap pulls back through the unit, as on an ACE
    for kind, payload in a.plan_action("swap_start", {"slot": 0}, t):
        t.slot_input(payload, now=1)
    assert t.work(now=2) == [("macro", f"LANE_MOVE LANE=lane1 DISTANCE={-a.PULLBACK_STEP_MM}")]
