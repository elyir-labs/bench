"""Changing filament by hand on a printer without a filament unit (design/change-filament/, B):
the printer warms up and takes the old filament out, a person pulls it and pushes the new one
in, the printer pushes it through, and a person checks the colour. Also the check after a
filament unit's swap, and staying warm for ten minutes after a change while idle."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

SENSOR = "filament_switch_sensor toolhead_sensor"
BLACK, WHITE = "#1C1C1E", "#F4F4F2"


def tracker(head=True, sensor=True, spool=("#1C1C1E", "PETG")):
    t = a.IntentTracker("Desk", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    t.has_unit = False
    status = {"print_stats": {"state": "standby", "filename": ""}, "pause_resume": {"is_paused": False},
              "heater_bed": {"temperature": 25, "target": 0}, "extruder": {"temperature": 25, "target": 0}, "ace": {}}
    if sensor:
        t.head_sensor = SENSOR
        status[SENSOR] = {"filament_detected": head}
    t.update_status(status, now=0.0)
    if spool:
        t.remember_spool(*spool, now=0.0)
        t.remember_spool(WHITE, "PLA", now=0.0)   # so Black PETG is in recent...
        t.remember_spool(*spool, now=0.0)          # ...and back on the printer
    return t


def act(t, action, now=1.0, **args):
    """Plan an action and apply it the way the component does. Returns what work() sends."""
    plan = a.plan_action(action, args, t)
    assert plan, f"{action} was refused"
    for kind, payload in plan:
        if kind == a.ActionPlan.CHANGE:
            t.change_input(payload, now=now)
    return t.work(now=now)


def heat(t, temp, now=2.0):
    t.update_status({"extruder": {"temperature": temp, "target": temp}}, now=now)
    return t.work(now=now)


def head(t, loaded, now=3.0):
    t.update_status({SENSOR: {"filament_detected": loaded}}, now=now)
    return t.work(now=now)


def view(t, now=5.0):
    return t.intent(now=now)


def ids(i):
    return [x["id"] for x in i["actions"]]


# ---- starting it ------------------------------------------------------------------------

def test_the_spool_offers_change_and_take_it_out_and_load_when_empty():
    s = view(tracker())["spools"][0]
    assert [(x["label"], x["args"]["kind"]) for x in s["actions"]] == [("Change filament", "change"), ("Take it out", "unload")]
    empty = view(tracker(head=False))["spools"][0]
    assert [(x["label"], x["args"]["kind"]) for x in empty["actions"]] == [("Load filament", "load")]


def test_only_without_a_unit_and_not_while_printing():
    t = tracker()
    t.has_unit = True
    assert a.plan_action("change_start", {"kind": "change"}, t) == []
    t = tracker()
    t.update_status({"print_stats": {"state": "printing"}}, now=1.0)
    assert a.plan_action("change_start", {"kind": "change"}, t) == []
    assert view(t)["spools"][0]["actions"] == []


def test_warms_to_the_temperature_of_what_is_coming_out():
    t = tracker()
    assert act(t, "change_start", kind="change") == [("gcode", "M104 S240")]   # PETG, not a fixed 220
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("preparing", "change_warm", "Changing filament")
    assert [s["label"] for s in i["steps"]] == ["Warming up", "Taking out Black PETG", "Pull it out",
                                               "Push in the new one", "Pushing it through", "Check it"]
    assert [s.get("you", False) for s in i["steps"]] == [False, False, True, True, False, True]
    assert ids(i) == ["change_stop"]
    assert i["change"]["art"] == "heat" and (i["change"]["n"], i["change"]["of"]) == (1, 6)


# ---- the whole routine ---------------------------------------------------------------------

def test_change_from_start_to_finish():
    t = tracker()
    act(t, "change_start", kind="change")
    assert t.work(now=1.5) == []   # still heating: nothing sent twice
    assert heat(t, 239) == [("macro", "UNLOAD_FILAMENT TEMP=240")]
    assert view(t)["phase"] == "change_unload" and view(t)["change"]["art"] == "out"
    assert t.work(now=2.5) == []   # the macro is running

    t.change_done(None, now=4.0)
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "change_pull", "Pull the filament out.")
    assert "I'll notice" in i["detail"] and ids(i) == ["change_out", "change_stop"]

    head(t, False)   # the sensor sees it go
    i = view(t)
    assert (i["phase"], i["headline"]) == ("change_push", "Push the new filament in.")
    assert i["change"]["ask"] and i["change"]["choices"][0]["label"] == "Same as before"
    assert [c["label"] for c in i["change"]["choices"]] == ["Same as before", "White PLA"]

    head(t, True)    # pushed in, but nobody has said what it is yet
    assert view(t)["headline"] == "Got it. What is it?"
    assert act(t, "change_what", color=WHITE, material="pla") == [("macro", "LOAD_FILAMENT TEMP=210")]
    assert view(t)["headline"] == "Changing filament" and view(t)["phase"] == "change_load"

    t.change_done(None, now=6.0)
    i = view(t)
    assert (i["phase"], i["headline"]) == ("change_check", "Is it coming out clean white?")
    assert i["detail"] == "If there's still black in it, I'll push more through."
    assert ids(i) == ["change_good", "change_more"]

    assert act(t, "change_more")[0][0] == "macro"
    assert view(t)["headline"] == "Pushing more through"
    t.change_done(None, now=7.0)
    assert view(t)["phase"] == "change_check"

    act(t, "change_good", now=8.0)
    i = view(t, now=9.0)
    assert i["change"] is None and i["state"] == "ready"
    assert i["spools"][0]["name"] == "White PLA" and i["spools"][0]["source"] == "told"


def test_answer_first_then_the_sensor_starts_the_feed():
    t = tracker()
    act(t, "change_start", kind="change"); heat(t, 240); t.change_done(None); head(t, False)
    act(t, "change_what", color=WHITE, material="PLA")
    assert view(t)["headline"] == "Push the White PLA in."
    assert head(t, True) == [("macro", "LOAD_FILAMENT TEMP=210")]


def test_without_a_sensor_a_person_says_out_and_in():
    t = tracker(sensor=False)
    act(t, "change_start", kind="change"); heat(t, 240); t.change_done(None)
    i = view(t)
    assert i["detail"] == "Gently, from the top of the head. Then tell me."
    act(t, "change_out")
    act(t, "change_what", color=WHITE, material="PLA")
    i = view(t)
    assert i["detail"] == "Until it stops. Then tell me." and i["actions"][0]["primary"]
    assert act(t, "change_in") == [("macro", "LOAD_FILAMENT TEMP=210")]


def test_a_sensor_already_clear_after_unloading_cant_see_the_pull():
    t = tracker()
    act(t, "change_start", kind="change"); heat(t, 240)
    head(t, False)               # the unload pulled it past the sensor
    t.change_done(None)
    i = view(t)
    assert i["phase"] == "change_pull" and i["detail"].endswith("Then tell me.")
    head(t, False)
    assert view(t)["phase"] == "change_pull"
    act(t, "change_out")
    assert view(t)["phase"] == "change_push"


def test_take_it_out_stops_after_the_pull_and_stays_warm():
    t = tracker()
    act(t, "change_start", kind="unload")
    assert [s["id"] for s in view(t)["steps"]] == ["warm", "unload", "pull"]
    assert view(t)["headline"] == "Taking out Black PETG"
    heat(t, 240); t.change_done(None); head(t, False, now=10.0)
    i = view(t, now=11.0)
    assert i["change"] is None and i["phase"] == "warm"
    assert "Staying warm for 10 more minutes in case you print next." in i["detail"]
    assert ids(i) == ["cool_down"]


def test_load_into_an_empty_head():
    t = tracker(head=False)
    act(t, "change_start", kind="load")
    assert [s["id"] for s in view(t)["steps"]] == ["push", "load", "check"]
    act(t, "change_what", color=WHITE, material="PLA")
    assert head(t, True) == [("macro", "LOAD_FILAMENT TEMP=210")]


# ---- staying warm ----------------------------------------------------------------------------

def test_heaters_go_off_ten_minutes_after_an_idle_change():
    t = tracker()
    act(t, "change_start", kind="unload"); heat(t, 240); t.change_done(None); head(t, False, now=10.0)
    assert t.work(now=10.0 + 9 * 60) == []
    assert view(t, now=10.0 + 9 * 60 + 30)["detail"].endswith("Staying warm for 1 more minute in case you print next.")
    assert t.work(now=10.0 + 10 * 60) == [("gcode", "TURN_OFF_HEATERS")]
    assert t.work(now=10.0 + 11 * 60) == []


def test_a_print_started_while_warm_keeps_its_heaters():
    t = tracker()
    act(t, "change_start", kind="unload"); heat(t, 240); t.change_done(None); head(t, False, now=10.0)
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=20.0)
    assert t.work(now=20.0 + 15 * 60) == []


# ---- stopping and failing ----------------------------------------------------------------------

def test_stop_while_waiting_turns_the_heaters_off():
    t = tracker()
    act(t, "change_start", kind="change"); heat(t, 240); t.change_done(None)
    assert act(t, "change_stop") == [("gcode", "TURN_OFF_HEATERS")]
    assert view(t)["change"] is None


def test_stop_while_a_macro_runs_waits_for_it():
    t = tracker()
    act(t, "change_start", kind="change"); heat(t, 240)
    act(t, "change_stop")
    i = view(t)
    assert i["detail"] == "Stopping after this step." and i["actions"] == []
    t.change_done(None)
    assert t.work() == [("gcode", "TURN_OFF_HEATERS")] and t._change is None


def test_a_failed_macro_is_a_problem_with_try_again():
    t = tracker()
    act(t, "change_start", kind="change"); heat(t, 240)
    t.change_done("Extrude below minimum temp")
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("problem", "change_failed", "Taking out Black PETG didn't finish.")
    assert i["raw"] == "Extrude below minimum temp" and ids(i) == ["change_retry", "change_end"]
    assert act(t, "change_retry") == [("macro", "UNLOAD_FILAMENT TEMP=240")]


def test_answers_out_of_turn_are_refused():
    t = tracker()
    act(t, "change_start", kind="change")
    assert not t.change_input({"op": "good"}) and not t.change_input({"op": "out"})
    assert a.plan_action("change_what", {"material": "not a material!"}, t) == []
    assert a.plan_action("change_start", {"kind": "change"}, t) == []   # one at a time


# ---- mid-print -------------------------------------------------------------------------------

def paused(t, line):
    t.update_status({"print_stats": {"state": "printing", "filename": "phone_stand.gcode", "info": {"current_layer": 56}},
                     "extruder": {"temperature": 215, "target": 215}}, now=1.0)
    t.on_gcode_response(line, now=1.0)
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=1.0)


def test_colour_change_offers_the_routine_instead_of_carry_on():
    t = tracker()
    paused(t, "// M600")
    i = view(t)
    assert i["headline"] == "Time to change the color." and ids(i) == ["change_start", "cancel"]
    assert i["actions"][0]["label"] == "Change it now"


def test_colour_change_keeps_the_print_temperature_and_ends_with_carry_on():
    t = tracker()
    paused(t, "// M600")
    assert act(t, "change_start", kind="change") == [("macro", "UNLOAD_FILAMENT TEMP=215")]   # no warm step
    assert [s["id"] for s in view(t)["steps"]] == ["unload", "pull", "push", "load", "check"]
    t.change_done(None); head(t, False)
    act(t, "change_what", color=WHITE, material="PLA")
    assert head(t, True) == [("macro", "LOAD_FILAMENT TEMP=215")]
    t.change_done(None)
    assert a.plan_action("resume", {}, t) == []   # not before the check
    act(t, "change_good")
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "change_done", "White PLA is in.")
    assert i["detail"] == "Phone Stand carries on from layer 57." or i["detail"].endswith("carries on from layer 57.")
    assert ids(i) == ["resume", "change_more"] and i["expires"]
    plan = a.plan_action("resume", {}, t)
    assert [k for k, _ in plan] == [a.ActionPlan.CHANGE, a.ActionPlan.RESUME]
    t.change_input(plan[0][1])
    assert t._change is None and t._keep_warm_until is None


def test_an_m600_that_already_unloaded_starts_at_the_new_spool():
    t = tracker()
    paused(t, "// M600")
    head(t, False)
    act(t, "change_start", kind="change")
    assert [s["id"] for s in view(t)["steps"]] == ["push", "load", "check"]


def test_runout_without_a_unit_loads_through_the_routine():
    t = tracker()
    paused(t, "// Filament runout detected (Toolhead)")
    i = view(t)
    assert i["headline"] == "Black PETG ran out." and i["actions"][0]["label"] == "Load a new spool"
    act(t, "change_start", kind="change")
    assert view(t)["steps"][0]["id"] == "unload"   # the tail still has to come out


# ---- the check after a filament unit's swap -----------------------------------------------------

def ace_tracker():
    t = a.IntentTracker("Workshop", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    t.has_unit = True
    t.update_status({"print_stats": {"state": "standby"}, "extruder": {"temperature": 25, "target": 0},
                     "heater_bed": {"target": 0},
                     "ace": {"gate_color": ["D9534F", "F1F1F1"], "gate_material": ["PLA", "PLA"], "selected_gate": 0,
                             "slots": [{"status": "ready"}, {"status": "ready"}]}}, now=0.0)
    return t


def test_a_swap_that_purges_ends_with_the_check():
    t = ace_tracker()
    t.begin_swap(1, 0, True, now=1.0)
    assert view(t)["steps"][-1] == {"id": "check", "label": "Check it", "status": "todo", "you": True}
    t.update_status({"ace": {"selected_gate": 1}}, now=2.0)
    t.end_swap(None, now=3.0)
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "change_check", "Is it coming out clean white?")
    assert [s["status"] for s in i["steps"]] == ["done"] * (len(i["steps"]) - 1) + ["now"]
    assert i["change"]["choices"] == []
    act(t, "change_good")
    assert view(t)["state"] == "ready" and t._keep_warm_until is None


def test_a_same_colour_swap_has_no_check():
    t = ace_tracker()
    t.begin_swap(1, 0, False, now=1.0)
    t.end_swap(None, now=3.0)
    assert t._change is None


def test_pushing_more_through_after_a_swap_heats_first_and_cools_after():
    t = ace_tracker()
    t.begin_swap(1, 0, True, now=1.0)
    t.end_swap(None, now=3.0)
    cmds = act(t, "change_more")
    assert cmds[0][0] == "macro" and cmds[0][1].startswith("M109 S210")
    t.change_done(None)
    assert act(t, "change_good") == [("gcode", "M104 S0")]


# ---- telling the phone --------------------------------------------------------------------------

def test_your_turn_tells_the_phone_only_after_half_a_minute():
    t = tracker()
    n = a.Notifier("b")
    n.observe(view(t, now=0.0), now=0.0)
    act(t, "change_start", kind="change"); heat(t, 240); t.change_done(None)
    assert n.observe(view(t, now=10.0), now=10.0) == []
    assert n.observe(view(t, now=25.0), now=25.0) == []
    sent = n.observe(view(t, now=41.0), now=41.0)
    assert len(sent) == 1 and sent[0]["title"] == "Desk needs you" and sent[0]["body"].startswith("Pull the filament out.")
    assert n.observe(view(t, now=80.0), now=80.0) == []
