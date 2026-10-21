"""Filament units in one shape, whatever drives them (design/ace-driver/, A): KlipperACE's `ace` with several
units or one, Happy Hare's `mmu` as Rinkhals reports a Kobra's unit, and the commands each driver takes."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402
import filament_units as fu  # noqa: E402

P = a.ActionPlan


def device(i, slots, dryer=None, temp=31, offset=None):
    return {"name": f"ACE_{i + 1}", "alias": "Left" if i == 0 else "", "gate_offset": i * 4 if offset is None else offset,
            "gates": [0, 1, 2, 3], "connected": i == 0,
            "status": {"status": "ready", "temp": temp, "slots": slots,
                       "dryer_status": dryer or {"status": "stop", "target_temp": 0, "duration": 0, "remain_time": 0}}}


def slot(st="ready", color=(0, 0, 0), kind="", sku="", rfid=1):
    return {"index": 0, "status": st, "sku": sku, "type": kind, "color": list(color), "rfid": rfid}


TWO_UNITS = {
    "selected_gate": 5, "endless_spool": False,
    "gate_color": ["FFFFFF"] * 8, "gate_material": ["PLA"] * 6 + ["", ""], "gate_temp": [210] * 8,
    "gate_feed_assist": [0, 0, 0, 0, 0, 1, 0, 0],
    "devices": [device(0, [slot(), slot(color=(255, 0, 0), kind="PETG", sku="AHPEGY-101", rfid=2), slot(), slot("empty")]),
                device(1, [slot(), slot(), slot("feeding"), slot("empty")])],
}

KOBRA_MMU = {
    "mmu": {"enabled": True, "num_gates": 4, "gate": 1, "gate_status": [1, 2, 0, -1],
            "gate_material": ["PLA", "PETG", "Unknown", "Unknown"],
            "gate_color": ["D9534FFF", "F1F1F1FF", "000000FF", "000000FF"], "gate_temperature": [210, 240, 0, 0]},
    "mmu_machine": {"num_units": 1, "unit_0": {"name": "ACE 1", "first_gate": 0, "num_gates": 4, "dryer_status": "drying",
                                               "dryer_temp": 44, "dryer_target_temp": 50, "dryer_remaining": 120}},
}


def test_klipperace_with_two_units():
    u = fu.read({"ace": TWO_UNITS})
    assert u["driver"] == "klipperace" and u["selected"] == 5 and u["known"] == 2
    assert [(x["index"], x["alias"], x["offset"], x["n"], x["connected"]) for x in u["units"]] == [
        (0, "Left", 0, 4, True), (1, None, 4, 4, False)]
    assert [s["slot"] for s in u["slots"]] == list(range(8))
    # a tag wins over the colors and materials kept for untagged spools; anything but ready or empty is unknown
    assert u["slots"][1] == {"slot": 1, "status": "ready", "color": "#FF0000", "material": "PETG", "tagged": True, "remain": None}
    assert (u["slots"][0]["color"], u["slots"][0]["material"], u["slots"][0]["tagged"]) == ("#FFFFFF", "PLA", False)
    assert u["slots"][6]["status"] == "unknown"
    assert u["feed_assist"] == [False] * 5 + [True, False, False] and u["carry_on"] is False


def test_klipperace_with_one_unit_and_no_devices():
    u = fu.read({"ace": {"selected_gate": -1, "gate_color": ["00FF00", "", "", ""], "gate_material": ["PETG"],
                         "active_gate": ["ready", "ready", "empty", "ready"], "temp": 30, "dryer_status": {"status": "stop"}}})
    assert u["selected"] is None and u["known"] == 1 and u["carry_on"] is None and u["feed_assist"] is None
    assert [(x["offset"], x["n"], x["temp"]) for x in u["units"]] == [(0, 4, 30)]
    assert [(s["status"], s["color"], s["material"]) for s in u["slots"]] == [
        ("ready", "#00FF00", "PETG"), ("ready", None, None), ("empty", None, None), ("ready", None, None)]


def test_happy_hare_as_rinkhals_reports_a_kobras_unit_is_watched_not_driven():
    u = fu.read(KOBRA_MMU)
    assert u["driver"] == "happy_hare" and u["selected"] == 1 and u["known"] == 1
    assert [(s["status"], s["color"], s["material"]) for s in u["slots"]] == [
        ("ready", "#D9534F", "PLA"), ("ready", "#F1F1F1", "PETG"), ("empty", None, None), ("unknown", None, None)]
    assert u["units"][0]["temp"] == 44 and u["units"][0]["dryer"]["status"] == "drying"
    assert fu.commands(u) is None
    assert fu.read({"mmu": {"enabled": True, "num_gates": 0}}) is None
    assert fu.read({"mmu": {"enabled": False, "num_gates": 4}}) is None


def test_klipperace_wins_when_both_are_reported_and_nothing_means_no_unit():
    assert fu.read({"ace": TWO_UNITS, **KOBRA_MMU})["driver"] == "klipperace"
    assert fu.read({}) is None and fu.read({"ace": None}) is None


def test_the_gcode_klipperace_takes():
    k = fu.commands(fu.read({"ace": TWO_UNITS}))
    unit = {"offset": 4}
    assert k.move(2, 50) == "ACE_FEED INDEX=2 LENGTH=50"
    assert k.move(2, -300) == "ACE_RETRACT INDEX=2 LENGTH=300"
    assert k.dry(unit, 55, 240) == "ACE_START_DRYING GATE=4 TEMP=55 DURATION=240"
    assert k.stop_drying(unit) == "ACE_STOP_DRYING GATE=4"
    assert k.feed_assist(1, True) == "ACE_ENABLE_FEED_ASSIST INDEX=1"
    assert k.feed_assist(1, False) == "ACE_DISABLE_FEED_ASSIST INDEX=1"
    assert k.carry_on(True) == "ACE_ENDLESS_SPOOL ENABLE=1"
    assert k.change_tool(3) == "ACE_CHANGE_TOOL TOOL=3"
    assert k.change_tool(3, purge=False) == "ACE_CHANGE_TOOL TOOL=3 PURGE=0"
    assert k.change_tool(-1, purge=False) == "ACE_CHANGE_TOOL TOOL=-1"
    assert k.mark_loaded(0) == "ACE_SET_GATE GATE=0"


def kobra_tracker():
    t = a.IntentTracker("Kobra 3")
    t.has_unit = True
    t.set_klippy_state("ready")
    t.update_status({"print_stats": {"state": "standby"}, **KOBRA_MMU})
    return t


def test_a_unit_bench_can_only_watch_gets_no_commands_from_any_planner():
    t = kobra_tracker()
    assert len(t.spools()) == 4 and t._selected_slot() == 1 and t.unit_commands() is None
    for action, args in (("move_filament", {"slot": 2, "mm": 50}), ("dry_unit", {"unit": 0, "hours": 4}),
                         ("stop_drying", {"unit": 0}), ("carry_on", {"on": True}), ("feed_assist", {"slot": 1, "on": True})):
        assert a.plan_slot(action, args, t) == []
    assert a.plan_spool_move("load_spool", {"slot": 0}, t) == []
    assert a.plan_set_spool({"slot": 2, "color": "#00FF00", "material": "PLA"}, t) == []
    assert a.plan_action("swap_slot", {"slot": 0}, t) == []


SERVICE = {   # units/service.py's state: two units, slot 1 in the head with feed assist, slot 5 tagged
    "units": [{"index": 0, "alias": None, "offset": 0, "n": 4, "connected": True, "temp": 31, "busy": False,
               "dryer": {"status": "stop", "target_temp": 0, "duration": 0, "remain_time": 0}, "firmware": "V1.3.856"},
              {"index": 1, "alias": None, "offset": 4, "n": 4, "connected": True, "temp": 45, "busy": False,
               "dryer": {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": 6000}, "firmware": "V1.3.856"}],
    "slots": [{"slot": g, "status": "empty" if g == 7 else "ready", "color": "#75787B" if g == 5 else "#00FF00" if g == 0 else None,
               "material": "PETG" if g == 5 else "PLA" if g == 0 else None, "tagged": g == 5, "remain": None} for g in range(8)],
    "selected": 1, "feed_assist": [g == 1 for g in range(8)], "carry_on": True, "dryer_max": 55,
}


def service_tracker():
    t = a.IntentTracker("Workshop")
    t.has_unit = True
    t.set_klippy_state("ready")
    t.update_status({"print_stats": {"state": "standby"}, "elyir_units": SERVICE, "ace": TWO_UNITS})
    return t


def test_our_service_wins_over_klipperace_and_reads_as_the_same_shape():
    u = fu.read({"elyir_units": SERVICE, "ace": TWO_UNITS})
    assert u["driver"] == "elyir" and u["selected"] == 1 and u["known"] == 2 and u["dryer_max"] == 55
    assert [x["offset"] for x in u["units"]] == [0, 4] and u["slots"][5]["tagged"] and u["feed_assist"][1]
    assert fu.read({"elyir_units": {"units": [], "slots": []}, "ace": TWO_UNITS})["driver"] == "klipperace"
    t = service_tracker()
    spools = t.spools()
    assert [(s["slot"], s["name"], s["status"], s["in_use"]) for s in spools[:2]] == [(0, "Green PLA", "ready", False),
                                                                                    (1, None, "ready", True)]
    assert spools[5]["rfid"] and spools[7]["status"] == "empty"
    units = t.intent(now=0)["units"]
    assert units["carry_on"] is True and units["list"][1]["drying"]["minutes_left"] == 100


def test_slot_features_become_steps_for_the_service():
    t = service_tracker()
    assert a.plan_slot("move_filament", {"slot": 3, "mm": 50}, t) == [(P.UNIT, {"op": "move", "slot": 3, "mm": 50})]
    temp = t.dry_plan([s for s in t.spools() if s["slot"] < 4])["temp"]
    assert a.plan_slot("dry_unit", {"unit": 0, "hours": 4}, t) == [(P.UNIT, {"op": "dry", "unit": 0, "temp": temp, "minutes": 240})]
    assert a.plan_slot("stop_drying", {"unit": 1}, t) == [(P.UNIT, {"op": "stop_drying", "unit": 1})]
    assert a.plan_slot("carry_on", {"on": False}, t) == [(P.UNIT, {"op": "carry_on", "on": False})]
    assert a.plan_slot("feed_assist", {"slot": 1, "on": False}, t)[0] == (P.UNIT, {"op": "feed_assist", "slot": 1, "on": False})
    assert a.plan_set_spool({"slot": 2, "color": "#FF0000", "material": "PETG"}, t) == [
        (P.UNIT, {"op": "set_spool", "slot": 2, "color": "#FF0000", "material": "PETG"})]
    assert a.plan_spool_move("mark_loaded", {"slot": 2}, t) == [(P.UNIT, {"op": "mark_loaded", "slot": 2})]


def test_load_and_unload_on_the_service_are_one_change_tool_step():
    t = service_tracker()
    assert a.plan_spool_move("load_spool", {"slot": 0}, t) == [(P.SWAP, {"to": 0, "from": 1, "purge": True})]
    assert a.plan_spool_move("unload_spool", {}, t) == [(P.SWAP, {"to": -1, "from": 1, "purge": False})]
    assert a.swap_gcode({"to": 0, "from": 1, "purge": True}, t.unit_commands()) == {"op": "change_tool", "slot": 0, "purge": True}
    assert a.swap_gcode({"to": 0, "from": 1, "purge": False}) == "ACE_CHANGE_TOOL TOOL=0 PURGE=0"
    assert a.plan_action("swap_slot", {"slot": 0}, t) == [(P.UNIT, {"op": "change_tool", "slot": 0, "purge": True}),
                                                          (P.RESUME, None)]
    assert a.plan_slot("swap_start", {"slot": 1}, t) == [(P.SLOT, {"op": "swap", "slot": 1})]


def paused_for_a_change(change):
    t = service_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "two.gcode"}, "virtual_sdcard": {"progress": 0.4}})
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True},
                     "elyir_units": dict(SERVICE, change=change)})
    return t.intent(now=10)


def test_a_change_the_print_asked_for_says_so_and_nobody_is_needed():
    i = paused_for_a_change({"from": 1, "to": 0, "in_print": True, "step": "in", "error": None})
    assert (i["state"], i["phase"], i["headline"]) == ("preparing", "tool_change", "Switching to Green PLA")
    assert i["detail"] == "The file asks for it here. Nobody's needed."
    assert [x["id"] for x in i["actions"]] == ["cancel"]


def test_a_change_that_failed_leaves_the_print_paused_with_try_again():
    i = paused_for_a_change({"from": 1, "to": 0, "in_print": True, "error": "The filament didn't reach the toolhead."})
    assert (i["state"], i["phase"], i["headline"]) == ("problem", "tool_change_failed", "Switching to Green PLA didn't finish.")
    assert "tube between the unit and the head" in i["detail"]
    assert [(x["id"], x.get("args", {}).get("slot")) for x in i["actions"]][0] == ("swap_slot", 0)
    assert a.plan_action("swap_slot", {"slot": 0}, service_tracker())[-1] == (P.RESUME, None)


def test_a_failed_change_that_waited_says_the_nozzle_cooled_and_try_again_heats_it():
    i = paused_for_a_change({"from": 2, "to": 0, "in_print": True, "cooled": True,
                             "error": "The filament didn't come out of the toolhead."})
    assert i["detail"].endswith("The nozzle cooled while it waited; Try again heats it first.")


def test_push_more_through_on_the_service_goes_to_it_and_on_klipperace_stays_gcode():
    t = service_tracker()
    t._change = {"mid": False, "temp": 0}
    t._load_temp = lambda: 250
    assert t._purge_step(30) == ("unit_macro", {"op": "purge", "mm": 30, "temp": 250})
    k = kobra_tracker()
    k.update_status({"ace": TWO_UNITS, "mmu": None})
    k._change = {"mid": False, "temp": 0}
    k._load_temp = lambda: 240
    kind, script = k._purge_step(30)
    assert kind == "macro" and "G1 E30 F150" in script
