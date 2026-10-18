"""Everything a slot can do (design/slots/, direction B): swap a spool, an empty slot, moving
filament, feed assist, drying a unit, and carrying on with a matching spool."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

SENSOR = "filament_switch_sensor extruder_sensor"
P = a.ActionPlan

WHITE, BLUE, GREEN, PURPLE = "FFFFFF", "0000FF", "00FF00", "800080"


def device(i, slots, dryer=None, temp=31):
    return {"name": f"ACE_{i + 1}", "alias": "", "gate_offset": i * 4, "gates": [0, 1, 2, 3], "connected": True,
            "status": {"status": "ready", "temp": temp, "dryer_status": dryer or {"status": "stop", "target_temp": 0,
                                                                                "duration": 0, "remain_time": 0},
                       "slots": slots}}


def tracker(selected=0, colors=(WHITE, WHITE, GREEN, BLUE, WHITE, PURPLE, WHITE, WHITE),
            materials=("PLA", "PLA", "PETG", "PETG", "PLA", "PETG", "", ""),
            status=("ready",) * 6 + ("empty", "empty"), endless=True, dryers=(None, None), assist=None, now=0.0):
    t = a.IntentTracker("Workshop", now=now)
    t.set_klippy_state("ready", "Printer is ready", now=now)
    t.head_sensor = SENSOR
    t.dryer_max = 70
    slots = [{"index": i % 4, "status": st, "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1} for i, st in enumerate(status)]
    t.update_status({
        "print_stats": {"state": "standby", "filename": ""}, "heater_bed": {"target": 0},
        "extruder": {"temperature": 25, "target": 0},
        "ace": {"selected_gate": selected, "gate_color": list(colors), "gate_material": list(materials),
                "gate_temp": [210] * 8, "endless_spool": endless,
                "gate_feed_assist": list(assist) if assist else [False] * 8,
                "devices": [device(0, slots[:4], dryers[0]), device(1, slots[4:], dryers[1])]},
        SENSOR: {"filament_detected": selected >= 0},
    }, now=now)
    return t


def set_slot(t, g, now, **fields):
    devs = [dict(d, status=dict(d["status"], slots=[dict(s) for s in d["status"]["slots"]])) for d in t.status["ace"]["devices"]]
    devs[g // 4]["status"]["slots"][g % 4].update(fields)
    t.update_status({"ace": {"devices": devs}}, now=now)


def plan(t, action, **args):
    return a.plan_action(action, args, t)


def run(t, steps, now):
    """Apply a plan the way the component does, for the parts that stay inside the intent layer."""
    for kind, payload in steps:
        if kind == P.SLOT:
            t.slot_input(payload, now=now)
        elif kind == P.CHANGE:
            t.change_input(payload, now=now)


# ---- swapping a spool ----------------------------------------------------------------

def test_swap_a_spool_that_is_not_in_the_head():
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=1), now=1)
    i = t.intent(now=1)
    assert i["state"] == "preparing" and i["headline"] == "Pulling White PLA back to its spool"
    assert [s["id"] for s in i["steps"]] == ["pullback", "swap", "what"]
    assert i["change"]["kind"] == "slot" and i["change"]["slot"] == 1
    # the unit pulls in steps until the slot says empty
    assert t.work(now=2) == [("macro", "ACE_RETRACT INDEX=1 LENGTH=300")]
    assert t.work(now=3) == []                         # one at a time
    t.change_done(None, now=10)
    assert t.work(now=10) == [("macro", "ACE_RETRACT INDEX=1 LENGTH=300")]
    t.change_done(None, now=20)
    set_slot(t, 1, now=21, status="empty")
    assert t.work(now=21) == []
    i = t.intent(now=21)
    assert i["state"] == "needs_you" and i["phase"] == "change_slot_swap" and i["headline"] == "Swap the spool in slot 2."
    assert "I'll notice" in i["detail"]
    # a person pushes a new spool in; the slot sensor notices
    set_slot(t, 1, now=40, status="ready")
    t.work(now=40)
    i = t.intent(now=40)
    assert i["phase"] == "change_slot_what" and i["headline"] == "What's in slot 2?"
    labels = [c["label"] for c in i["change"]["choices"]]
    assert labels[0] == "White PLA again" and all(c["id"] == "change_what" for c in i["change"]["choices"])
    assert i["new_spool"] is None                     # the routine is already asking
    run(t, plan(t, "change_what", color="#0000FF", material="PETG"), now=41)
    out = t.work(now=41)
    assert t._change is None
    saved = [s for k, s in out if "ace_gate_type" in s]
    assert saved and '"PETG"' in saved[0]


def test_swap_the_spool_in_the_head_takes_it_out_first():
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=0), now=1)
    assert [s["id"] for s in t.intent(now=1)["steps"]] == ["unload", "pullback", "swap", "what"]
    assert t.intent(now=1)["headline"] == "Taking White PLA out of the head"
    assert t.work(now=2) == [("macro", "ACE_CHANGE_TOOL TOOL=-1")]
    t.change_done(None, now=60)
    out = t.work(now=60)
    assert ("gcode", "M104 S0") in out and ("macro", "ACE_RETRACT INDEX=0 LENGTH=300") in out


def test_a_slot_that_never_reads_empty_hands_over_to_a_person():
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=1), now=1)
    for n in range(a.PULLBACK_MAX_MM // a.PULLBACK_STEP_MM):
        assert t.work(now=2 + n)[0][1].startswith("ACE_RETRACT")
        t.change_done(None, now=2 + n)
    t.work(now=50)
    i = t.intent(now=50)
    assert i["phase"] == "change_slot_swap" and "pull it out gently" in i["detail"]
    # it can't see the new one go in either, so "It's in" says so
    run(t, plan(t, "change_in"), now=60)
    t.work(now=60)
    assert t.intent(now=60)["phase"] == "change_slot_what"


def test_a_tagged_spool_names_itself():
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=1), now=1)
    t.work(now=1)
    t.change_done(None, now=5)
    set_slot(t, 1, now=6, status="empty")
    t.work(now=6)
    set_slot(t, 1, now=20, status="ready", type="PETG", color=[0, 0, 255], sku="AHPEGY")
    out = t.work(now=20)
    assert t._change is None and not [s for _, s in out if "SAVE_VARIABLE" in s]


def test_stop_during_a_pull_back_finishes_the_pull_then_stops():
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=1), now=1)
    t.work(now=1)
    run(t, plan(t, "change_stop"), now=2)
    assert t.intent(now=2)["detail"] == "Stopping after this step."
    t.change_done(None, now=5)
    assert t._change is None


def test_swap_refusals():
    t = tracker(selected=0)
    assert plan(t, "swap_start", slot=6) == []         # empty: nothing to swap
    assert plan(t, "swap_start", slot=9) == []
    t.update_status({"print_stats": {"state": "printing"}}, now=1)
    assert plan(t, "swap_start", slot=1) == []
    t = tracker(selected=0)
    run(t, plan(t, "swap_start", slot=1), now=1)
    assert plan(t, "swap_start", slot=2) == [] and plan(t, "load_spool", slot=2) != []   # the plan layer keeps swaps apart
    t2 = tracker(selected=0)
    t2.has_unit = False
    assert plan(t2, "swap_start", slot=1) == []


# ---- a sheet per slot -----------------------------------------------------------------

def test_what_each_slot_offers():
    i = tracker(selected=0).intent(now=1)
    s = {x["slot"]: x for x in i["spools"]}
    assert [x["id"] for x in s[1]["actions"]] == ["load_spool", "swap_start"] and s[1]["move"] is True
    assert [x["id"] for x in s[0]["actions"]] == ["unload_spool", "swap_start"] and s[0]["move"] is False
    assert s[6]["actions"] == [] and s[6]["fix"]["label"] == "It won't catch? Pull it in"
    assert s[0]["assist"] is False and s[1]["assist"] is None


def test_spares_only_same_colour_and_material_and_only_with_carry_on():
    i = tracker(selected=0).intent(now=1)
    s = {x["slot"]: x for x in i["spools"]}
    # three white PLA: 0 (in the head), 1, 4. Green, blue and purple PETG match nothing.
    assert s[0]["spare_note"].startswith("If it runs out mid-print, the White PLA in slot")
    assert s[1]["spare_for"] == 0 or s[4]["spare_for"] == 0
    assert s[2]["spare_note"] is None and s[3]["spare_note"] is None and s[5]["spare_note"] is None
    assert s[0]["spare_for"] is None                   # the one in the head is never the spare
    off = {x["slot"]: x for x in tracker(selected=0, endless=False).intent(now=1)["spools"]}
    assert all(x["spare_note"] is None and x["spare_for"] is None for x in off.values())


# ---- moving filament -------------------------------------------------------------------

def test_move_filament():
    t = tracker(selected=0)
    assert plan(t, "move_filament", slot=1, mm=50) == [(P.GCODE, "ACE_FEED INDEX=1 LENGTH=50")]
    assert plan(t, "move_filament", slot=1, mm=-200) == [(P.GCODE, "ACE_RETRACT INDEX=1 LENGTH=200")]
    assert plan(t, "move_filament", slot=6, mm=100) == [(P.GCODE, "ACE_FEED INDEX=6 LENGTH=100")]   # pull it in
    assert plan(t, "move_filament", slot=0, mm=50) == []      # in the head: would grind cold filament
    assert plan(t, "move_filament", slot=1, mm=37) == []      # only the offered amounts
    assert plan(t, "move_filament", slot=6, mm=-50) == []     # nothing to pull back in an empty slot
    assert plan(t, "move_filament", slot=1, mm=5000) == []
    t.update_status({"print_stats": {"state": "printing"}}, now=1)
    assert plan(t, "move_filament", slot=1, mm=50) == []


# ---- feed assist -----------------------------------------------------------------------

def test_feed_assist_switch():
    t = tracker(selected=0)
    p = plan(t, "feed_assist", slot=0, on=False)
    assert p == [(P.GCODE, "ACE_DISABLE_FEED_ASSIST INDEX=0"), (P.SLOT, {"op": "assist", "slot": 0, "on": False})]
    assert plan(t, "feed_assist", slot=1, on=True) == []      # only the slot feeding the head
    assert plan(t, "feed_assist", slot=0, on=True)[0] == (P.GCODE, "ACE_ENABLE_FEED_ASSIST INDEX=0")


def test_a_print_without_feed_assist_gets_it_back_once():
    t = tracker(selected=0)
    t.update_status({"print_stats": {"state": "printing", "filename": "body.gcode", "info": {"current_layer": 2}}}, now=1)
    assert ("gcode", "ACE_ENABLE_FEED_ASSIST INDEX=0") in t.work(now=2)
    assert ("gcode", "ACE_ENABLE_FEED_ASSIST INDEX=0") not in t.work(now=3)   # once per print and slot


def test_feed_assist_a_person_switched_off_stays_off():
    t = tracker(selected=0)
    run(t, plan(t, "feed_assist", slot=0, on=False), now=1)
    t.update_status({"print_stats": {"state": "printing", "filename": "body.gcode", "info": {"current_layer": 2}}}, now=2)
    assert not [s for _, s in t.work(now=3) if "FEED_ASSIST" in s]


def test_feed_assist_left_alone_while_getting_ready():
    t = tracker(selected=0)
    t.update_status({"print_stats": {"state": "printing", "filename": "body.gcode", "info": {"current_layer": None}}}, now=1)
    assert not [s for _, s in t.work(now=2) if "FEED_ASSIST" in s]


# ---- drying ---------------------------------------------------------------------------

def test_the_most_delicate_material_sets_the_heat():
    units = tracker().intent(now=1)["units"]["list"]
    assert [u["name"] for u in units] == ["Unit 1", "Unit 2"]
    assert units[0]["slots"] == [0, 1, 2, 3] and units[0]["temp"] == 31
    d = units[0]["dry"]   # white PLA x2, green PETG, blue PETG
    assert d["temp"] == 45 and d["hours"] == 4 and d["why"] == "because PLA softens above that"
    assert d["hours_why"] == "PETG's time"
    assert units[0]["actions"] == [a._action("dry_unit", "Dry", unit=0, hours=4)]
    only_pla = tracker(materials=("PLA",) * 6 + ("", "")).intent(now=1)["units"]["list"][0]["dry"]
    assert only_pla["temp"] == 45 and only_pla["hours"] == 2 and only_pla["why"] == "for PLA"


def test_drying_never_above_the_units_limit():
    t = tracker(materials=("PA",) * 6 + ("", ""))
    t.dryer_max = 55
    d = t.intent(now=1)["units"]["list"][0]["dry"]
    assert d["temp"] == 55 and d["why"] == "as warm as this unit goes"


def test_dry_and_stop():
    t = tracker()
    assert plan(t, "dry_unit", unit=1, hours=4) == [(P.GCODE, "ACE_START_DRYING GATE=4 TEMP=45 DURATION=240")]
    assert plan(t, "dry_unit", unit=1, hours=40) == [] and plan(t, "dry_unit", unit=7, hours=4) == []
    assert plan(t, "stop_drying", unit=0) == [(P.GCODE, "ACE_STOP_DRYING GATE=0")]


def test_drying_shows_whether_the_unit_counts_in_seconds_or_minutes():
    minutes = tracker(dryers=(None, {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": 100}))
    u = minutes.intent(now=0)["units"]["list"][1]
    assert u["drying"]["minutes_left"] == 100 and u["drying"]["target"] == 45
    assert u["actions"] == [a._action("stop_drying", "Stop", unit=1)]
    seconds = tracker(dryers=(None, {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": 6000}))
    assert seconds.intent(now=0)["units"]["list"][1]["drying"]["minutes_left"] == 100


def test_the_last_minutes_of_a_dry_read_right_once_the_countdown_shows_seconds():
    def at(t, now, left):
        dryer = {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": left}
        slots = [{"index": i, "status": "ready", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1} for i in range(4)]
        t.update_status({"ace": {"devices": [device(0, slots), device(1, slots, dryer)]}}, now=now)

    t = tracker(dryers=(None, {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": 300}))
    assert t.intent(now=0)["units"]["list"][1]["drying"]["minutes_left"] == 300     # the guess, before any step
    for now, left in ((0.4, 299), (1.4, 298)):
        at(t, now, left)
    assert t.intent(now=2)["units"]["list"][1]["drying"]["minutes_left"] == 5

    m = tracker(dryers=(None, {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": 100}))
    for now, left in ((50, 99), (110, 98)):
        at(m, now, left)
    assert m.intent(now=111)["units"]["list"][1]["drying"]["minutes_left"] == 98


def test_the_phone_hears_a_unit_finished_drying_not_one_that_was_stopped():
    n = a.Notifier("boot")
    dry = lambda left: tracker(dryers=(None, {"status": "drying", "target_temp": 45, "duration": 240, "remain_time": left}))
    n.observe(dry(100).intent(now=0), now=0)                      # priming
    n.observe(dry(2).intent(now=10), now=10)
    ev = n.observe(tracker().intent(now=20), now=20)
    assert [(e["kind"], e["title"], e["body"]) for e in ev] == [("dried", "Workshop: Unit 2 is done drying", "45° for 4 hours. The spools are ready.")]
    n.observe(dry(100).intent(now=30), now=30)
    assert n.observe(tracker().intent(now=40), now=40) == []       # stopped with 100 minutes left


# ---- carrying on with a matching spool --------------------------------------------------

def test_carry_on_switch():
    assert tracker().intent(now=1)["units"]["carry_on"] is True
    assert plan(tracker(), "carry_on", on=False) == [(P.GCODE, "ACE_ENDLESS_SPOOL ENABLE=0")]
    assert plan(tracker(endless=False), "carry_on", on=True) == [(P.GCODE, "ACE_ENDLESS_SPOOL ENABLE=1")]


def test_it_carried_on_says_so_on_now_and_to_the_phone():
    t = tracker(selected=1)
    n = a.Notifier("boot")
    t.update_status({"print_stats": {"state": "printing", "filename": "body.gcode", "info": {"current_layer": 40}},
                     "virtual_sdcard": {"progress": 0.41}}, now=1)
    n.observe(t.intent(now=1), now=1)
    set_slot(t, 1, now=2, status="empty")
    t.on_gcode_response("Endless spool: T1 empty, switching to T4", now=3)
    i = t.intent(now=3)
    assert i["carried"]["headline"] == "Carried on with slot 5."
    assert i["carried"]["detail"] == "White PLA ran out at 41%."
    ev = n.observe(i, now=3)
    assert [(e["kind"], e["title"]) for e in ev] == [("carried_on", "Workshop carried on with slot 5")]
    assert n.observe(t.intent(now=4), now=4) == []
    run(t, plan(t, "carried_ok"), now=5)
    assert t.intent(now=5)["carried"] is None


def test_the_carried_note_goes_away_by_itself():
    t = tracker(selected=1)
    t.on_gcode_response("Endless spool: T1 empty, switching to T4", now=0)
    assert t.intent(now=60)["carried"] is not None
    assert t.intent(now=a.CARRIED_NOTE_SECONDS + 1)["carried"] is None


# ---- a spool pushed into an empty slot -----------------------------------------------------

def test_a_new_spool_is_noticed_and_asked_about():
    t = tracker(selected=0)
    t.intent(now=1)
    set_slot(t, 6, now=2, status="ready")
    n = t.intent(now=2)["new_spool"]
    assert n["headline"] == "New spool in slot 7. What is it?"
    assert all(c["id"] == "set_spool" and c["args"]["slot"] == 6 for c in n["choices"])
    assert [c["label"] for c in n["choices"]][:2] == ["White PLA", "Green PETG"]
    p = plan(t, "set_spool", slot=6, color="#FFFFFF", material="PLA")
    run(t, p, now=3)
    assert t.intent(now=3)["new_spool"] is None


def test_a_tagged_new_spool_needs_no_question():
    t = tracker(selected=0)
    t.intent(now=1)
    set_slot(t, 6, now=2, status="ready", type="PLA", color=[255, 0, 0], sku="AHPLA")
    assert t.intent(now=2)["new_spool"] is None


def test_while_the_unit_switches_nobody_is_needed():
    t = tracker(selected=1)
    n = a.Notifier("boot")
    t.update_status({"print_stats": {"state": "printing", "filename": "body.gcode", "info": {"current_layer": 40}}}, now=1)
    n.observe(t.intent(now=1), now=1)
    t.on_gcode_response("Endless spool: T1 empty, switching to T4", now=2)
    t.update_status({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}}, now=2)
    i = t.intent(now=3)
    assert (i["state"], i["phase"], i["headline"]) == ("preparing", "carrying_on", "Switching to slot 5")
    assert [e["kind"] for e in n.observe(i, now=3)] == ["carried_on"]   # not needs_you
