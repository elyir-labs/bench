"""Colour changes on a printer with a filament unit (design/colour-change/, C as the main path, A as the
fallback; picked on 3 October 2026). The boards are the spec: CReady/CAsk (the Print sheet), CAuto and
CPhone (the unit switches by itself), APause/APicked/AMissing/APhone (the pause, and why), SSwitch/SCheck/SLoad/
SWhat (after a choice). If one of these fails, the screens have drifted from the boards."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

SENSOR = "filament_switch_sensor extruder_sensor"
P = a.ActionPlan
FILE = "colour/phone_stand_0.2mm_PLA_MK4_1h40m.gcode"
RED, WHITE, BLACK, BLUE, YELLOW, WHITE2 = "D9534F", "F1F1F1", "2B2B2B", "3B82F6", "F5C542", "FFFFFF"


def device(i, slots):
    return {"name": f"ACE_{i + 1}", "alias": "", "gate_offset": i * 4, "gates": [0, 1, 2, 3], "connected": True,
            "status": {"status": "ready", "temp": 26, "dryer_status": {"status": "stop", "target_temp": 0, "duration": 0,
                                                                       "remain_time": 0}, "slots": slots}}


def tracker(selected=0, now=0.0):
    """Workshop as the simulator draws it: two units, Red PLA in the head, Black PLA running low, Yellow PETG, two empty."""
    t = a.IntentTracker("Workshop", now=now)
    t.set_klippy_state("ready", "Printer is ready", now=now)
    t.head_sensor = SENSOR
    t.has_unit = True
    status = ["ready"] * 6 + ["empty", "empty"]
    slots = [{"index": i % 4, "status": st, "rfid": 0, "remain": 40 if i == 2 else 600} for i, st in enumerate(status)]
    t.update_status({
        "print_stats": {"state": "standby", "filename": ""}, "heater_bed": {"target": 0},
        "extruder": {"temperature": 25, "target": 0},
        "ace": {"selected_gate": selected, "gate_color": [RED, WHITE, BLACK, BLUE, YELLOW, WHITE2, "FFFFFF", "FFFFFF"],
                "gate_material": ["PLA", "PLA", "PLA", "PLA", "PETG", "PLA", "", ""], "gate_temp": [210] * 8,
                "endless_spool": False, "gate_feed_assist": [False] * 8,
                "devices": [device(0, slots[:4]), device(1, slots[4:])]},
        SENSOR: {"filament_detected": True},
    }, now=now)
    return t


def meta(color="#F4F4F2", layer=56):
    return {"filament_type": "PLA", "filament_colors": ["#D9534F"], "layer_count": 140,
            "colour_changes": [{"layer": layer, "color": color}]}


def set_slot(t, g, now, **fields):
    devs = [dict(d, status=dict(d["status"], slots=[dict(s) for s in d["status"]["slots"]])) for d in t.status["ace"]["devices"]]
    devs[g // 4]["status"]["slots"][g % 4].update(fields)
    t.update_status({"ace": {"devices": devs}}, now=now)


def printing(t, filename=FILE, m=None, now=1.0, layer=55):
    t.set_metadata(filename, m if m is not None else meta())
    t.update_status({"print_stats": {"state": "printing", "filename": filename, "info": {"current_layer": layer, "total_layer": 140}},
                     "virtual_sdcard": {"progress": layer / 140}, "extruder": {"temperature": 215, "target": 215},
                     "display_status": {"message": "Printing, good luck!"}}, now=now)


def m600(t, now, layer=56):
    """Klipper's M600: a console line, then the pause."""
    t.update_status({"print_stats": {"info": {"current_layer": layer, "total_layer": 140}}}, now=now)
    t.on_gcode_response("// M600", now=now)
    t.update_status({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}}, now=now)


def plan_for(t, slot, filename=FILE, m=None, now=0.5, sure=False):
    """What the Print sheet sends on Print, after check_print showed the file."""
    t.note_check(filename, m if m is not None else meta())
    ch = {"slot": slot}
    if sure:
        ch["sure"] = True
    steps = a.plan_action("print_planned", {"filename": filename, "changes": [ch]}, t)
    for kind, payload in steps:
        if kind == P.COLOUR:
            t.colour_input(payload, now=now)
    return steps


def run(t, steps, now):
    for kind, payload in steps:
        if kind == P.COLOUR:
            t.colour_input(payload, now=now)
        elif kind == P.CHANGE:
            t.change_input(payload, now=now)
        elif kind == P.RESUME:
            t.update_status({"pause_resume": {"is_paused": False}, "print_stats": {"state": "printing"}}, now=now)


def tile(i, slot):
    return next(s for s in i["colour"]["slots"] if s["slot"] == slot)


# ---- 1. finding the colour changes in a file ---------------------------------------------------

def test_prusaslicer_names_the_colour_just_before_its_m600():
    lines = ["; filament_colour = #D9534F", "; color_change_gcode = M600"]
    for n in range(1, 60):
        lines += [";LAYER_CHANGE", f";Z:{n * 0.2:.1f}", "G1 X10 Y10 E1"]
        if n == 56:
            lines += [";COLOR_CHANGE,T0,#F4F4F2", "M600"]
    assert a.colour_changes_in(lines) == [{"layer": 56, "color": "#F4F4F2"}]


def test_klippers_layer_number_wins_and_a_bare_m600_has_no_colour():
    lines = ["SET_PRINT_STATS_INFO TOTAL_LAYER_COUNT=140", ";LAYER_CHANGE", "SET_PRINT_STATS_INFO CURRENT_LAYER=1",
             "G1 X1", ";LAYER_CHANGE", "SET_PRINT_STATS_INFO CURRENT_LAYER=30", "M600 ; colour", "G1 X2 E1"]
    assert a.colour_changes_in(lines) == [{"layer": 30, "color": None}]


def test_cura_counts_layers_from_zero_and_a_marker_just_after_counts():
    lines = [";LAYER:0", "G1 X1", ";LAYER:11", "M600", ";COLOR_CHANGE colour #00ff00 for the top", "G1 X2"]
    assert a.colour_changes_in(lines) == [{"layer": 12, "color": "#00FF00"}]


def test_a_marker_far_from_its_m600_says_nothing_and_comments_are_not_commands():
    lines = [";COLOR_CHANGE,T0,#FF0000"] + ["G1 X1 E1"] * 3 + ["M117 hi"] * 10 + [";LAYER_CHANGE", "; M600 in a comment", "M600"]
    assert a.colour_changes_in(lines) == [{"layer": 1, "color": None}]


def test_two_changes_in_order_and_read_from_a_file(tmp_path):
    p = tmp_path / "two.gcode"
    p.write_text("\n".join([";LAYER_CHANGE"] * 10 + [";COLOR_CHANGE,T0,#FFFFFF", "M600"] + [";LAYER_CHANGE"] * 5
                           + [";COLOR_CHANGE,T0,#000000", "M600", "G1 X1 E2"]) + "\n")
    assert a.colour_changes_from_file(str(p)) == [{"layer": 10, "color": "#FFFFFF"}, {"layer": 15, "color": "#000000"}]


# ---- 2. the Print sheet: CReady, CAsk ------------------------------------------------------------

def test_the_file_names_white_so_the_sheet_shows_the_plan():
    t = tracker()
    c = a.check_print(FILE, meta(), t.spools())
    assert c["colour_changes"] == [{"layer": 56, "color": "#F4F4F2", "slot": 1, "not_loaded": False}]
    s = c["colour"]
    assert s["headline"] == "Phone stand changes color once."
    assert s["detail"] == "The file asks for white at layer 56. The unit can do it, so nobody needs to be here."
    assert s["start"] == {"slot": 0, "name": "Red PLA", "color": "#D9534F", "loaded": True, "line": "Slot 1 · in the head"}
    row = s["changes"][0]
    assert (row["label"], row["slot"], row["named_line"]) == ("Layer 56", 1, "Slot 2 · the file's white")
    assert s["labels"]["pause"] == "Pause there and let me choose"


def test_the_file_doesnt_say_so_the_sheet_asks_once():
    t = tracker()
    s = a.check_print(FILE, meta(color=None), t.spools())["colour"]
    assert s["headline"] == "Phone stand changes color at layer 56."
    assert s["detail"] == "The file doesn't say which color. Which spool? Then the unit does it, and nobody needs to be here."
    assert s["changes"][0]["slot"] is None and not s["changes"][0]["not_loaded"]
    chips = {c["slot"]: c for c in s["choices"]}
    assert sorted(chips) == [0, 1, 2, 3, 4, 5]
    assert chips[4]["differs"] and chips[4]["ask"] == "Yellow PETG on a PLA print may not stick. Use it anyway?"
    assert not chips[1]["differs"] and chips[1]["line"] == "Slot 2"


def test_a_colour_that_isnt_loaded_says_so_and_pauses_there():
    t = tracker()
    row = a.check_print(FILE, meta(color="#3BA55C"), t.spools())["colour"]["changes"][0]
    assert row["not_loaded"] and row["slot"] is None
    assert row["missing_line"] == "There's no green in the unit. I'll pause at layer 56."


# ---- by hand, from Bench's own slicer (design/multi-color/, B) -------------------------------------------

def test_a_swap_by_hand_is_marked_and_never_planned_onto_a_spool():
    lines = [";LAYER_CHANGE"] * 40 + [";COLOR_CHANGE,T3,#F1F1F1", "; elyir: by hand", "M600", ";LAYER_CHANGE", "T1"] \
        + [";LAYER_CHANGE"] * 3 + [";COLOR_CHANGE,T2,#D9534F", "M600"]
    assert a.colour_changes_in(lines) == [{"layer": 40, "color": "#F1F1F1", "hand": True}, {"layer": 44, "color": "#D9534F"}]
    t = tracker()
    m = {"filament_type": "PLA;PLA;PLA", "filament_colors": ["#D9534F", "#C9A227", "#F1F1F1"], "layer_count": 140,
         "colour_changes": [{"layer": 40, "color": "#C9A227", "hand": True}]}
    c = a.check_print(FILE, m, t.spools())
    # white is loaded, but the gold the person swaps in isn't, and isn't meant to be: nothing's missing
    assert c["ok"] and not c.get("missing")
    assert c["colour_changes"] == [{"layer": 40, "color": "#C9A227", "slot": None, "not_loaded": True, "hand": True}]
    s = c["colour"]
    assert s["detail"] == "You swap in yellow by hand there. I'll pause and wait for you."
    assert s["changes"][0]["missing_line"] == "You swap in yellow by hand: I'll pause at layer 40."
    assert next(u for u in c["uses"] if u["color"] == "#C9A227")["line"] == "Yellow PLA, swapped in by hand"


def test_by_hand_and_by_the_unit_together():
    t = tracker()
    m = {"filament_type": "PLA", "filament_colors": ["#D9534F", "#F4F4F2", "#C9A227"], "layer_count": 140,
         "colour_changes": [{"layer": 30, "color": "#C9A227", "hand": True}, {"layer": 60, "color": "#C9A227", "hand": True},
                            {"layer": 90, "color": "#F4F4F2"}]}
    s = a.check_print(FILE, m, t.spools())["colour"]
    assert s["detail"] == "You swap 2 by hand, so I'll pause for those; the unit does the rest."
    assert [r["slot"] for r in s["changes"]] == [None, None, 1]


def test_one_spool_printers_are_unchanged():
    t = tracker()
    t.has_unit = False
    c = a.check_print(FILE, meta(), t.spools())
    assert "colour" not in c and "colour_changes" not in c


# ---- 3. the plan the sheet sends back is checked ------------------------------------------------

def test_print_planned_stores_the_plan_then_starts_the_file():
    t = tracker()
    steps = plan_for(t, 1)
    assert [k for k, _ in steps] == [P.COLOUR, P.START_FILE]
    assert steps[0][1] == {"op": "plan", "filename": FILE, "changes": [{"layer": 56, "slot": 1, "color": "#F4F4F2"}]}
    assert t.colour_plan["filename"] == FILE and t.colour_plan_dirty


def test_a_plan_is_refused_unless_it_fits_what_the_sheet_showed():
    t = tracker()
    act = lambda **args: a.plan_action("print_planned", args, t)
    assert act(filename=FILE, changes=[{"slot": 1}]) == []                     # the sheet never showed it
    t.note_check(FILE, meta())
    assert act(filename=FILE, changes=[{"slot": 1}, {"slot": 2}]) == []        # one change, not two
    assert act(filename=FILE, changes=[{"slot": 6}]) == []                     # an empty slot
    assert act(filename=FILE, changes=[{"slot": True}]) == []
    assert act(filename=FILE, changes=[{"slot": 4}]) == []                     # PETG on a PLA print: asked first
    assert act(filename=FILE, changes=[{"slot": 4, "sure": True}])             # ...and never refused
    assert act(filename=FILE, changes=[{"slot": "pause"}])
    printing(t)
    assert act(filename=FILE, changes=[{"slot": 1}]) == []                     # not while printing


def test_the_plan_is_only_for_the_print_of_its_file_started_right_after():
    t = tracker()
    plan_for(t, 1, now=0)
    printing(t, filename="Benchy.gcode", m={}, now=5)                          # another file
    assert t.colour_plan is None and t.colour_plan_dirty

    t = tracker()
    plan_for(t, 1, now=0)
    printing(t, now=a.COLOUR_PLAN_FRESH_SECONDS + 10)                          # the same file, much later
    assert t.colour_plan is None

    t = tracker()
    plan_for(t, 1, now=0)
    printing(t, now=30)
    assert t.colour_plan["started"]
    t.update_status({"print_stats": {"state": "complete"}}, now=500)          # that print is over
    assert t.colour_plan is None


def test_a_claimed_plan_survives_a_restart_mid_print():
    t = tracker()
    plan_for(t, 1, now=0)
    printing(t, now=30)
    record = dict(t.colour_plan)
    t2 = tracker(now=5000)
    t2.restore_colour_plan(record)
    printing(t2, now=5000)
    assert t2.colour_plan and t2.colour_plan["started"]


# ---- 4. C: planned, so nobody's needed -------------------------------------------------------------

def test_a_planned_change_switches_by_itself_and_carries_on():
    t = tracker()
    n = a.Notifier("boot")
    plan_for(t, 1, now=0)
    printing(t, now=10)
    n.observe(t.intent(now=10), now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert (i["state"], i["phase"]) == ("preparing", "colour_auto")
    assert (i["headline"], i["detail"]) == ("Switching to White PLA", "Layer 56, as planned. Nobody's needed.")
    assert [s["label"] for s in i["steps"]] == ["Taking out Red PLA", "Feeding White PLA", "Feeding it to the nozzle", "Cleaning the nozzle"]
    assert i["change"]["pill"] == "Layer 56 of 140" and i["change"]["auto"]
    assert [a_["id"] for a_ in i["actions"]] == ["cancel"] and i["actions"][0]["hold"]
    assert n.observe(i, now=20) == []                                          # nobody is called

    assert t.work(now=21) == [("macro", "ACE_CHANGE_TOOL TOOL=1")]
    assert t.work(now=22) == []
    t.on_gcode_response("// ACE: Unloading tool 0...", now=23)
    assert [s["status"] for s in t.intent(now=23)["steps"]] == ["now", "todo", "todo", "todo"]   # not "loading tool"
    t.on_gcode_response("// ACE: Feeding from gate to extruder", now=30)
    i = t.intent(now=30)
    assert [s["status"] for s in i["steps"]] == ["done", "now", "todo", "todo"]
    t.change_done(None, now=60)
    out = t.work(now=60)
    assert len(out) == 1 and out[0][0] == "macro" and "G1 E60 F150" in out[0][1]   # longer purge, no check
    t.change_done(None, now=80)
    assert t.work(now=80) == [("gcode", "RESUME")]
    i = t.intent(now=80)
    assert i["phase"] == "colour_resuming" and i["state"] == "preparing"
    ev = n.observe(i, now=80)                                                  # the phone hears it afterwards (CPhone)
    assert [(e["kind"], e["title"], e["body"]) for e in ev] == [
        ("carried_on", "Workshop changed to White PLA", "Phone stand, layer 56, as planned. Carrying on.")]
    run(t, [(P.RESUME, None)], now=81)
    i = t.intent(now=81)
    assert i["state"] == "printing"
    assert (i["carried"]["headline"], i["carried"]["detail"]) == ("Changed to White PLA at layer 56.",
                                                                  "As planned. Red PLA went back to slot 1.")
    assert n.observe(i, now=81) == []                                          # once


def test_a_planned_spool_already_in_the_head_just_carries_on():
    t = tracker(selected=1)
    plan_for(t, 1, now=0)
    printing(t, now=10)
    m600(t, now=20)
    assert t.work(now=20) == [("gcode", "RESUME")]
    assert t.intent(now=20)["state"] == "preparing"


def test_if_the_unit_cant_switch_by_itself_it_is_the_pause_and_it_says_so():
    t = tracker()
    plan_for(t, 1, now=0)
    printing(t, now=10)
    m600(t, now=20)
    t.work(now=21)
    t.change_done("ACE: Feed timeout", now=40)
    i = t.intent(now=40)
    assert (i["state"], i["headline"]) == ("problem", "Switching to White PLA didn't finish.")
    run(t, a.plan_action("change_end", {}, t), now=41)
    i = t.intent(now=41)
    assert i["state"] == "needs_you" and i["colour"]["reason"] == "not_switched"
    assert i["detail"] == "The unit couldn't switch to White PLA by itself."
    assert t.work(now=42) == []                                                 # not again by itself


# ---- 5. A: the pause, and why ---------------------------------------------------------------------

def test_started_outside_elyir_it_pauses_with_the_files_colour_picked():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    assert t.work(now=20) == []
    i = t.intent(now=20)
    c = i["colour"]
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "color_change", "Time to change the color.")
    assert i["detail"] == "Phone stand was started outside Elyir Bench, so this one wasn't planned."
    assert (c["reason"], c["picked"], c["asks"]) == ("not_planned", 1, "The file asks for white.")
    assert tile(i, 1)["says"] == ["The file asks for white:", " White PLA, slot 2."]
    assert tile(i, 1)["says_away"] == ["White PLA", ", slot 2. I'll switch, clean the nozzle and show you the check here."]
    assert [x["label"] for x in i["actions"]] == ["Switch to White PLA", "Stop this print"]
    assert i["actions"][0]["args"] == {"slot": 1, "how": "switch"} and i["actions"][0]["style"] == "amber"
    assert i["actions"][1]["hold"]


def test_the_colour_isnt_loaded_so_it_asks_for_a_spool_in_the_free_slot():
    t = tracker()
    printing(t, m=meta(color="#3BA55C"), now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert i["detail"] == "The file asks for green, and there's no green in the unit."
    assert (i["colour"]["reason"], i["colour"]["picked"]) == ("not_loaded", 6)
    assert i["actions"][0]["label"] == "Put a green spool in slot 7"
    assert tile(i, 6)["says"] == ["Slot 7 is free.", " Put a green spool on and push its end in. I'll notice."]


def test_you_asked_to_choose_here():
    t = tracker()
    plan_for(t, "pause", now=0)
    printing(t, now=10)
    m600(t, now=20)
    assert t.work(now=20) == []
    i = t.intent(now=20)
    assert (i["colour"]["reason"], i["detail"]) == ("asked", "You asked to choose here when you started Phone stand.")


def test_nothing_named_and_nothing_picked_keeps_whats_in_the_head():
    t = tracker()
    printing(t, m=meta(color=None), now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert i["colour"]["picked"] == 0 and i["colour"]["asks"] is None
    assert i["actions"][0]["label"] == "Carry on with Red PLA"


def test_workshops_m600_is_recognised_and_an_empty_head_is_never_carried_on_with():
    # Workshop's M600: PAUSE, UNLOAD_FILAMENT, RESPOND "Please load new filament and resume" (the printer's own filament.cfg)
    t = tracker()
    printing(t, m=meta(color=None), now=10)
    t.on_gcode_response("// Please load new filament and resume", now=20)
    t.update_status({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}, SENSOR: {"filament_detected": False}}, now=20)
    i = t.intent(now=20)
    assert i["phase"] == "color_change" and i["colour"]["reason"] == "not_planned"
    red = tile(i, 0)
    assert (red["how"], red["sub"], red["action"]) == (None, "out of the head", None)
    assert i["colour"]["picked"] != 0 and i["actions"][0]["label"].startswith("Switch to")
    assert a.plan_action("colour_choose", {"slot": 0, "how": "keep"}, t) == []


def test_every_slot_says_what_tapping_it_would_do():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    c = i["colour"]
    assert [u["name"] for u in c["units"]] == ["Unit 1", "Unit 2"] and len(c["slots"]) == 8
    red, black, petg, empty = tile(i, 0), tile(i, 2), tile(i, 4), tile(i, 7)
    assert (red["word"], red["sub"], red["tone"], red["how"]) == ("Red", "in the head", "accent", "keep")
    assert red["action"]["label"] == "Carry on with Red PLA"
    assert (black["sub"], black["tone"], black["how"]) == ("PLA, low", "amber", "switch")
    assert (petg["word"], petg["sub"], petg["tone"]) == ("Yellow", "PETG", "amber")
    assert petg["ask"] == {"text": "Yellow PETG on a PLA print may not stick. Use it anyway?", "label": "Use it anyway"}
    assert (empty["word"], empty["sub"], empty["how"], empty["at_printer"]) == ("Empty", "put one in", "put_in", True)
    assert empty["action"]["label"] == "Put a white spool in slot 8"
    assert c["away_note"] == "Slots 7 and 8 are empty. Putting a spool in needs someone at the printer."
    assert tile(i, 1)["confirm_away"]["label"] == "Yes, switch"


def test_one_spool_printers_still_get_the_change_routine():
    t = tracker()
    t.has_unit = False
    del t.status["ace"]
    printing(t, now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert i["colour"] is None and i["actions"][0]["label"] == "Change it now"


# ---- 6. after a choice: switch, check, carry on in one tap ------------------------------------------

def test_switch_then_the_check_then_one_tap_carries_on():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    steps = a.plan_action("colour_choose", {"slot": 1, "how": "switch"}, t)
    assert steps == [(P.COLOUR, {"op": "choose", "slot": 1, "how": "switch"})]
    run(t, steps, now=21)
    i = t.intent(now=21)
    assert (i["state"], i["phase"], i["headline"], i["detail"]) == (
        "preparing", "colour_switch", "Switching to White PLA", "From slot 2. Keep clear of the nozzle.")
    assert [s["label"] for s in i["steps"]] == ["Taking out Red PLA", "Feeding White PLA", "Feeding it to the nozzle",
                                                 "Cleaning the nozzle", "Check it"]
    assert i["steps"][-1]["you"] and [x["id"] for x in i["actions"]] == ["cancel"]
    assert t.work(now=22) == [("macro", "ACE_CHANGE_TOOL TOOL=1")]
    t.change_done(None, now=60)
    assert t.work(now=60) == []
    i = t.intent(now=60)
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "change_colour_check", "Is it coming out clean white?")
    assert i["detail"] == "If there's still red in it, I'll push more through. Then Phone stand carries on from layer 57."
    assert [(x["label"], x["primary"]) for x in i["actions"]] == [("Looks good, carry on", True), ("Push more through", False)]
    assert i["change"]["look"] == "Look at the nozzle on the camera."

    more = a.plan_action("change_more", {}, t)
    run(t, more, now=61)
    out = t.work(now=61)
    assert "G1 E30 F150" in out[0][1] and t.intent(now=62)["headline"] == "Pushing more through"
    t.change_done(None, now=70)
    assert t.intent(now=70)["phase"] == "change_colour_check"

    good = a.plan_action("change_good", {}, t)
    assert good == [(P.CHANGE, {"op": "good"}), (P.RESUME, None)]           # one tap ends the check and carries on
    run(t, good, now=71)
    i = t.intent(now=71)
    assert i["state"] == "printing" and i["change"] is None


def test_keep_carries_on_with_whats_in_the_head():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    assert a.plan_action("colour_choose", {"slot": 0, "how": "keep"}, t) == [
        (P.COLOUR, {"op": "choose", "slot": 0, "how": "keep"}), (P.RESUME, None)]
    assert a.plan_action("colour_choose", {"slot": 1, "how": "keep"}, t) == []


def test_put_a_new_spool_in_an_empty_slot_then_say_what_it_is_then_switch():
    t = tracker()
    printing(t, m=meta(color="#3BA55C"), now=10)
    m600(t, now=20)
    run(t, a.plan_action("colour_choose", {"slot": 6, "how": "put_in"}, t), now=21)
    i = t.intent(now=21)
    assert (i["state"], i["headline"]) == ("needs_you", "Put the new spool in slot 7.")
    assert i["detail"] == "Push its end in until the unit grabs it. I'll notice, ask what it is, then switch to it."
    assert [x["label"] for x in i["actions"]] == ["It's in", "Stop this print"] and not i["actions"][0]["primary"]
    assert (i["change"]["n"], i["change"]["of"], i["change"]["art"]) == (1, 4, "insert")
    assert t.work(now=22) == []
    set_slot(t, 6, now=30, status="ready")                                     # the slot sensor notices
    t.work(now=30)
    i = t.intent(now=30)
    assert (i["headline"], i["detail"]) == ("What's in slot 7?", "It has no tag, so tell me once. Then I'll switch to it.")
    assert i["change"]["choices"][0]["label"] == "Green PLA" and i["change"]["ask"]
    assert i["new_spool"] is None
    run(t, a.plan_action("change_what", {"color": "#3BA55C", "material": "PLA"}, t), now=31)
    out = t.work(now=31)
    assert [k for k, _ in out[:2]] == ["gcode", "gcode"] and "SAVE_VARIABLE VARIABLE=ace_gate_color" in out[0][1]
    assert out[-1] == ("macro", "ACE_CHANGE_TOOL TOOL=6")
    i = t.intent(now=32)
    assert i["headline"] == "Switching to Green PLA" and [s["status"] for s in i["steps"]] == ["done", "done", "now", "todo"]
    t.change_done(None, now=60)
    t.work(now=60)
    assert t.intent(now=60)["headline"] == "Is it coming out clean green?"


def test_the_twenty_minutes_start_again_on_each_step_a_person_takes():
    t = tracker()
    printing(t, m=meta(color="#3BA55C"), now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert i["expires"] == a._iso(20 + a.NEEDS_YOU_HOLD_SECONDS)
    run(t, a.plan_action("colour_choose", {"slot": 6, "how": "put_in"}, t), now=300)
    assert t.intent(now=300)["expires"] == a._iso(300 + a.NEEDS_YOU_HOLD_SECONDS)
    run(t, a.plan_action("change_in", {}, t), now=900)
    assert t.intent(now=900)["expires"] == a._iso(900 + a.NEEDS_YOU_HOLD_SECONDS)


def test_a_different_material_is_asked_about_never_refused():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    assert a.plan_action("colour_choose", {"slot": 4, "how": "switch"}, t) == []
    assert a.plan_action("colour_choose", {"slot": 4, "how": "switch", "sure": True}, t) == [
        (P.COLOUR, {"op": "choose", "slot": 4, "how": "switch"})]


def test_nothing_is_chosen_mid_routine_and_carry_on_waits_for_the_check():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    run(t, a.plan_action("colour_choose", {"slot": 1, "how": "switch"}, t), now=21)
    assert a.plan_action("colour_choose", {"slot": 3, "how": "switch"}, t) == []
    assert a.plan_action("resume", {}, t) == []
    assert a.plan_action("change_good", {}, t) == []


def test_stopping_the_print_ends_the_routine():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    run(t, a.plan_action("colour_choose", {"slot": 1, "how": "switch"}, t), now=21)
    t.update_status({"pause_resume": {"is_paused": False}, "print_stats": {"state": "cancelled"}}, now=30)
    assert t._change is None


# ---- 7. a full slot's spool at the pause: built, off until Workshop's hand test passes ---------------------

def test_swapping_a_full_slot_at_the_pause_is_off_by_default():
    assert a.SLOT_SWAP_WHILE_PAUSED is False
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert all(s["link"] is None for s in i["colour"]["slots"])
    assert a.plan_action("colour_choose", {"slot": 1, "how": "swap"}, t) == []


def test_swapping_a_full_slot_when_switched_on(monkeypatch):
    monkeypatch.setattr(a, "SLOT_SWAP_WHILE_PAUSED", True)
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    assert tile(i, 1)["link"]["label"] == "Or put a different spool in slot 2"
    run(t, a.plan_action("colour_choose", {"slot": 1, "how": "swap"}, t), now=21)
    i = t.intent(now=21)
    assert i["headline"] == "Pulling White PLA back to its spool"
    assert [s["id"] for s in i["steps"]] == ["pullback", "put", "what", "switch", "check"]
    assert t.work(now=22) == [("macro", "ACE_RETRACT INDEX=1 LENGTH=300")]
    t.change_done(None, now=30)
    set_slot(t, 1, now=31, status="empty")
    assert t.work(now=31) == []
    assert t.intent(now=31)["headline"] == "Swap the spool in slot 2."
    set_slot(t, 1, now=40, status="ready")
    t.work(now=40)
    assert t.intent(now=40)["headline"] == "What's in slot 2?"


# ---- 8. away from home: a switch with an extra confirmation, nothing that needs hands -----------------

def test_away_the_switch_is_confirmed_and_putting_a_spool_in_is_at_the_printer():
    t = tracker()
    printing(t, now=10)
    m600(t, now=20)
    i = t.intent(now=20)
    white, empty = tile(i, 1), tile(i, 6)
    assert white["confirm_away"]["text"].startswith("Switch to White PLA from here?")
    assert not white["at_printer"] and empty["at_printer"]
