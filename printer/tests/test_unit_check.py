"""Checking and measuring a Happy Hare or AFC unit from the screen (design/unit-setup/, B, stage 1, picked 22 October
2026): each slot's sensor and motor, then the tube to the head (and each AFC lane to its hub), then Ready."""

import copy
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "simulator"))
import elyir_bench_intent as a  # noqa: E402
import filament_units as fu  # noqa: E402
import unit_skins  # noqa: E402
from test_unit_adapters import AFC, ERCF, lane, tracker  # noqa: E402

P = a.ActionPlan


def ercf(n=4, sensors=True, **mmu):
    """An ERCF on Happy Hare 4 with nothing in the head; with sensors, one at each gate's entry."""
    st = copy.deepcopy(ERCF)
    st["mmu"].update({"num_gates": n, "gate": -1, "tool": -1, "filament": "Unloaded", "gate_status": [1] * n,
                      "is_homed": True, **mmu})
    st["mmu_machine"]["unit_0"].update(num_gates=n, display_name="ERCF 1")
    if sensors:
        for g in range(n):
            st[f"filament_switch_sensor mmu_entry_{g}"] = {"filament_detected": True}
    return st


def turtle(n=4, loaded=None):
    """A Box Turtle on AFC with nothing in the head."""
    loaded = [True] * n if loaded is None else loaded
    st = {"AFC": {"lanes": [f"lane{g + 1}" for g in range(n)], "current_load": None, "current_state": "Idle"},
          "AFC_hub Turtle_1": {"afc_bowden_length": 1000.0, "state": False}}
    for g in range(n):
        st[f"AFC_stepper lane{g + 1}"] = dict(lane(f"lane{g + 1}", "Turtle_1", load=loaded[g], prep=loaded[g]),
                                             hub="Turtle_1", dist_hub=60.0)
    return st


def started(status, now=0.0):
    t = tracker(status)
    assert a.plan_action("unit_check_start", {"unit": 0}, t) == [(P.UNIT_CHECK, {"op": "start", "unit": 0})]
    assert t.unit_check_input({"op": "start", "unit": 0}, now=now)
    return t


def finish(t, lines, now, error=None):
    """The command running now ends, having said these lines; the check judges it a moment later."""
    for line in lines:
        t.on_gcode_response(line, now=now)
    t.change_done(error, now=now)
    return t.work(now=now + 2)


def view(t, now=10.0):
    return t.intent(now=now)["unit_check"]


# ---- what's offered ----------------------------------------------------------------------------------

def test_check_and_measure_is_offered_for_happy_hare_and_afc_only():
    for status in (ercf(), turtle()):
        t = tracker(status)
        offer = t.unit_list(t.spools(), 0)[0]["check"]
        assert offer["action"]["id"] == "unit_check_start" and offer["action"]["label"] == "Check and measure"
        assert offer["why"] is None
    ace = {"ace": {"gate_color": ["FF0000"] * 4, "gate_material": ["PLA"] * 4, "selected_gate": -1,
                   "slots": [{"status": "ready"}] * 4}}
    t = tracker(ace)
    assert t.unit_list(t.spools(), 0)[0]["check"] is None
    assert a.plan_action("unit_check_start", {"unit": 0}, t) == []
    t = tracker(ercf(), watch_only=True)   # a Kobra through Rinkhals: watched, never driven
    assert t.units() is None or all(u["check"] is None for u in t.unit_list(t.spools(), 0))
    assert a.plan_action("unit_check_start", {"unit": 0}, t) == []
    for cmds in (fu.KlipperAce(), fu.Elyir()):
        assert not fu.can(cmds, "check_slot")


def test_not_while_printing_with_filament_in_the_head_or_klipper_away():
    t = tracker(ercf())
    t.update_status({"print_stats": {"state": "printing"}})
    assert t.unit_check_offer(0)["why"] == "Not while it's printing."
    assert a.plan_action("unit_check_start", {"unit": 0}, t) == []
    t = tracker(ercf(filament="Loaded", gate=1))
    assert "Take the filament out of the head first" in t.unit_check_offer(0)["why"]
    assert not t.unit_check_input({"op": "start", "unit": 0}, now=0)
    t = tracker(dict(turtle(), AFC=dict(turtle()["AFC"], current_load="lane2")))
    assert t.unit_check_offer(0)["why"].startswith("Take the filament out")
    t = tracker(ercf())
    t.set_klippy_state("shutdown")
    assert t.unit_check_offer(0)["why"] == "The printer isn't ready."


def test_while_checking_the_printer_is_busy_and_nothing_else_moves_the_unit():
    t = started(ercf())
    i = t.intent(now=1)
    assert i["state"] == "preparing" and i["phase"].startswith("unit_check")
    assert a.plan_action("load_spool", {"slot": 1}, t) == []
    assert a.plan_action("warm_up", {"material": "PLA"}, t) == []
    assert t.power_why_not() and t.hands_why_not()
    assert a.plan_action("unit_check_start", {"unit": 0}, t) == []   # one at a time


# ---- each slot -------------------------------------------------------------------------------------

def test_happy_hare_checks_each_gate_with_its_own_command():
    t = started(ercf())
    assert t.work(now=0) == [("macro", "MMU_CHECK_GATE GATE=0 QUIET=1")]
    assert t.work(now=0.5) == []   # handed out once
    out = finish(t, ["// Gate 0 - Filament detected. Marked available"], now=4)
    assert out == [("macro", "MMU_CHECK_GATE GATE=1 QUIET=1")]
    v = view(t)
    assert v["slots"][0] == {"slot": 0, "label": "Slot 1", "state": "ok", "sensor": True, "motor": True, "line": None}
    assert v["detail"] == "Slot 1's sensor saw the filament, and its motor turned." and v["tone"] == "ok"
    assert v["note"] == "1 of 4 checked. Then Bench measures the tube to the head."
    assert (v["step"], v["n"], v["of"]) == ("slots", 1, 3)


def test_an_empty_slot_waits_for_its_sensor_then_checks():
    st = turtle(loaded=[True, True, False, True])
    t = started(st)
    t.work(now=0)
    out = finish(t, [], now=2)
    assert out == [("macro", "LANE_MOVE LANE=lane2 DISTANCE=-10\nLANE_MOVE LANE=lane2 DISTANCE=10")]
    finish(t, [], now=4)
    assert t.work(now=7) == []   # slot 3's sensor doesn't see anything: nothing to send
    i = t.intent(now=7)
    assert i["headline"] == "Push filament into slot 3."
    assert i["detail"] == "Slot 2's sensor saw the filament, and its motor turned."
    assert [x["id"] for x in i["actions"]] == ["unit_check_skip", "unit_check_stop"]   # the sensor says when, no "It's in"
    assert i["actions"][0]["label"] == "Skip slot 3"
    assert view(t)["slots"][2]["line"] == "Waiting…" and view(t)["current"] == 2
    t.update_status({"AFC_stepper lane3": {"load": True, "prep": True}})
    assert t.work(now=8) == [("macro", "LANE_MOVE LANE=lane3 DISTANCE=-10\nLANE_MOVE LANE=lane3 DISTANCE=10")]


def test_a_gate_without_a_sensor_asks_its_in():
    st = ercf(sensors=False)
    st["mmu"]["gate_status"] = [1, -1, 1, 1]
    t = started(st)
    t.work(now=0)
    finish(t, [], now=2)
    i = t.intent(now=5)
    assert i["headline"] == "Push filament into slot 2."
    assert i["actions"][0]["id"] == "unit_check_in" and i["actions"][0]["label"] == "It's in"
    assert a.plan_action("unit_check_in", {}, t) == [(P.UNIT_CHECK, {"op": "in"})]
    t.unit_check_input({"op": "in"})
    assert t.work(now=6) == [("macro", "MMU_CHECK_GATE GATE=1 QUIET=1")]


def test_happy_hare_3_homes_the_selector_first_and_says_so():
    t = started(ercf(is_homed=False))
    assert t.work(now=0) == [("macro", "MMU_HOME\nMMU_CHECK_GATE GATE=0 QUIET=1")]
    assert t.intent(now=1)["detail"] == "Bench finds the unit's home first."


def test_skip_a_slot():
    t = started(turtle(loaded=[True, False, True, True]))
    t.work(now=0)
    finish(t, [], now=2)
    assert t.intent(now=5)["headline"] == "Push filament into slot 2."
    t.unit_check_input({"op": "skip"})
    v = view(t)
    assert v["slots"][1]["state"] == "skipped" and v["detail"] == "Slot 2 skipped." and v["tone"] is None
    assert t.work(now=6)[0][1].startswith("LANE_MOVE LANE=lane3")


def test_a_failed_motor_test_then_try_again():
    t = started(ercf())
    t.work(now=0)
    finish(t, ["!! MMU issue: Failure during check gate 0 :", "Couldn't pick up filament at gate (gate endstop didn't trigger)"], now=4)
    i = t.intent(now=7)
    assert i["headline"] == "Slot 1 didn't pass." and "stopped partway" in i["detail"]
    assert i["raw"].startswith("MMU issue")
    assert [x["id"] for x in i["actions"]] == ["unit_check_retry", "unit_check_skip", "unit_check_stop"]
    assert view(t)["slots"][0]["state"] == "failed" and view(t)["slots"][0]["line"] == "Didn't pass"
    assert t.work(now=8) == []   # waits for a person
    t.unit_check_input({"op": "retry"})
    assert t.work(now=9) == [("macro", "MMU_CHECK_GATE GATE=0 QUIET=1")]
    finish(t, ["// Gate 0 - Filament detected. Marked available"], now=12)
    assert view(t, 14)["slots"][0]["state"] == "ok"


def test_happy_hares_words_become_sentences():
    cases = [(["!! Warning: Calibration steps are not complete for MMU unit0:", "Required: - Use MMU_CALIBRATE_GEAR"],
              "isn't calibrated yet"),
             (["// Gate 0 marked EMPTY (no filament detected during homing)"], "never felt the filament"),
             (["!! Operation not possible. MMU selector is not homed"], "couldn't find its home")]
    for lines, words in cases:
        t = started(ercf())
        t.work(now=0)
        finish(t, lines, now=3)
        assert words in t.intent(now=6)["detail"], lines


def test_afc_failures_are_read_from_the_console():
    t = started(turtle())
    t.work(now=0)
    finish(t, ["!! lane1 didn't move"], now=2)   # LANE_MOVE returns normally; AFC only says it
    assert "motor didn't turn" in t.intent(now=4)["detail"]
    t = started(turtle())
    t.work(now=0)
    t.update_status({"AFC_stepper lane1": {"load": False}})
    finish(t, [], now=2)
    assert "lost the filament" in t.intent(now=4)["detail"]


def test_stop_finishes_the_command_then_ends():
    t = started(ercf())
    t.work(now=0)
    assert a.plan_action("unit_check_stop", {}, t) == [(P.UNIT_CHECK, {"op": "stop"})]
    t.unit_check_input({"op": "stop"})
    i = t.intent(now=1)
    assert i["headline"] == "Stopping" and i["actions"] == [] and i["unit_check"]["stopping"]
    assert finish(t, ["// Gate 0 - Filament detected. Marked available"], now=3) == []
    assert t._check is None and t.intent(now=5)["unit_check"] is None
    t = started(turtle(loaded=[False] * 4))
    t.work(now=0)
    t.unit_check_input({"op": "stop"})   # nothing running: over at once
    assert t._check is None


def test_a_print_started_from_elsewhere_ends_the_check():
    t = started(turtle(loaded=[False] * 4))
    t.work(now=0)
    t.update_status({"print_stats": {"state": "printing"}})
    t.work(now=1)
    assert t._check is None


# ---- measuring, then Ready ------------------------------------------------------------------------

def check_all(t, n, lines, now=0.0):
    out = t.work(now=now)
    for g in range(n):
        out = finish(t, lines(g), now=now + 3 * g + 2)
    return out


def test_happy_hare_measures_the_tube_with_the_first_good_slot():
    t = started(ercf())
    out = check_all(t, 4, lambda g: [f"// Gate {g} - Filament detected. Marked available"])
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]
    v = view(t, 20)
    assert v["step"] == "measure" and v["n"] == 2 and v["headline"] == "Measuring the tube to the head…"
    assert v["measure"]["what"] == "tube" and v["measure"]["seconds"] == 40 and v["measure"]["elapsed"] is not None
    assert v["measure"]["note"] == "Once for the whole unit."
    assert [x["id"] for x in v["actions"]] == ["unit_check_stop"]
    finish(t, ["// Filament homed to extruder after 742.3mm movement", "// Calibrated bowden length is 742.3mm"], now=60)
    i = t.intent(now=63)
    assert i["state"] == "ready"   # the summary holds nothing up
    v = i["unit_check"]
    assert v["step"] == "ready" and v["n"] == 3
    assert v["headline"] == "Ready: 4 slots."
    assert v["detail"] == "ERCF 1 is checked and measured. Load spools, and Bench prints in several colors."
    assert v["ready"]["rows"] == [
        {"title": "Happy Hare 4.1", "sub": "Bench drives ERCF 1 through it."},
        {"title": "4 slots · checked", "sub": "Every sensor and every motor."},
        {"title": "The tube to the head · 742 mm", "sub": "Measured just now."}]
    assert [(x["id"], x["label"]) for x in v["actions"]] == [("unit_check_done", "Done"), ("unit_check_done", "Load spools")]
    t.unit_check_input({"op": "done"})
    assert t.intent(now=64)["unit_check"] is None


def test_afc_measures_each_lane_to_its_hub_then_the_tube():
    t = started(turtle(loaded=[True, True, False, True]))
    t.work(now=0)
    finish(t, [], now=2)
    finish(t, [], now=4)
    t.unit_check_input({"op": "skip"})
    out = t.work(now=6)
    out = finish(t, [], now=8)
    assert out == [("macro", "CALIBRATE_AFC LANE=lane1\nRESPOND TYPE=command MSG=action:prompt_end")]
    assert view(t, 9)["headline"] == "Measuring slot 1 to the hub…"
    out = finish(t, ["// lane1 dist_hub: New: 58.0 Old: 60.0", "// Lane calibration Done!"], now=20)
    assert out[0][1].startswith("CALIBRATE_AFC LANE=lane2")
    out = finish(t, ["// lane2 dist_hub: New: 59.7 Old: 60.0"], now=30)
    out = finish(t, ["// lane4 dist_hub: New: 63.1 Old: 60.0"], now=40)
    assert out == [("macro", "CALIBRATE_AFC BOWDEN=lane1\nRESPOND TYPE=command MSG=action:prompt_end")]
    assert view(t, 41)["measure"]["note"] == "Once for the whole unit. Each slot is measured to the hub first."
    finish(t, ["// afc_bowden_length: New: 742.0 Old: 1000.0", "// Bowden length calibration Done!"], now=90)
    v = view(t, 93)
    assert v["headline"] == "Ready: 3 of 4 slots."
    assert v["ready"]["rows"] == [   # AFC keeps its version out of the status: no row for it
        {"title": "3 of 4 slots · checked", "sub": "Slot 3 skipped. Each one measured to the hub."},
        {"title": "The tube to the head · 742 mm", "sub": "Measured just now."}]


def test_a_tube_that_cant_be_measured_says_why_and_moves_on():
    t = started(ercf(n=2))
    check_all(t, 2, lambda g: [f"// Gate {g} - Filament detected. Marked available"])
    finish(t, ["// No encoder or extruder entry sensor available.", "Use manual calibration method:"], now=30)
    i = t.intent(now=33)
    assert i["headline"] == "The tube wasn't measured." and "without an encoder or a sensor at the head" in i["detail"]
    assert [x["id"] for x in i["actions"]] == ["unit_check_skip", "unit_check_stop"]   # trying again can't help
    t.unit_check_input({"op": "skip"})
    v = view(t, 34)
    assert v["step"] == "ready" and v["detail"] == "ERCF 1 is checked. The tube to the head still needs measuring."
    assert v["ready"]["rows"][-1] == {"title": "The tube to the head · not measured", "sub": "Skipped."}


def test_a_failed_measurement_can_be_tried_again():
    t = started(turtle(n=1))
    t.work(now=0)
    finish(t, [], now=2)
    finish(t, ["// lane1 dist_hub: New: 58.0 Old: 60.0"], now=10)
    finish(t, ["!! Hub is not clear, check before calibration"], now=40)
    i = t.intent(now=43)
    assert i["headline"] == "The tube wasn't measured." and "still in the hub" in i["detail"]
    t.unit_check_input({"op": "retry"})
    assert t.work(now=44)[0][1].startswith("CALIBRATE_AFC BOWDEN=lane1")
    finish(t, ["// afc_bowden_length: New: 750.0 Old: 1000.0"], now=80)
    assert view(t, 83)["ready"]["rows"][-1]["title"] == "The tube to the head · 750 mm"


def test_no_slot_passing_goes_straight_to_ready_and_says_so():
    t = started(turtle(n=2, loaded=[False, False]))
    t.work(now=0)
    t.unit_check_input({"op": "skip"})
    t.unit_check_input({"op": "skip"})
    v = view(t, 2)
    assert v["step"] == "ready" and v["headline"] == "No slot passed."
    assert v["ready"]["rows"][-1]["sub"] == "No slot passed its check."


# ---- the simulator answers it, for both skins -------------------------------------------------------

def run_on_skin(skin, failing=None):
    ace = copy.deepcopy({"devices": [{"status": {"slots": [{"status": "ready"}] * 4}}], "selected_gate": -1,
                         "gate_color": ["FF0000"] * 4, "gate_material": ["PLA"] * 4, "gate_temp": [210] * 4})
    t = tracker(unit_skins.view(skin, ace))
    t.unit_check_input({"op": "start", "unit": 0}, now=0)
    now, sent = 0.0, []
    out = t.work(now=now)
    for _ in range(40):
        if not out:
            if t._check is None or t._check.phase == "ready":
                break
            if t._check.marks[t._check.slots[t._check.cur]]["state"] == "failed" if t._check.phase == "slots" else False:
                t.unit_check_input({"op": "retry"})
            out = t.work(now=now)
            continue
        (kind, script), = out
        sent.append(script)
        for line in script.splitlines():
            seconds, said, measured = unit_skins.check_answer(skin, line, ["ready"] * 4, failing)
            if any(x.startswith("!!") for x in said):
                failing = None
            now += seconds
            for x in said:
                t.on_gcode_response(x, now=now)
        t.change_done(None, now=now)
        now += 2
        out = t.work(now=now)
    return t, sent


def test_the_simulator_answers_the_check_for_happy_hare_and_afc():
    for skin in unit_skins.SKINS:
        t, sent = run_on_skin(skin, failing=2)
        v = view(t, 500)
        assert v["step"] == "ready", skin
        assert v["ready"]["rows"][-1]["title"] == "The tube to the head · 742 mm", skin
        assert sum(1 for s in sent if s.endswith(("GATE=2 QUIET=1", "LANE=lane3 DISTANCE=10"))) == 2, skin   # failed once
        assert all(unit_skins.is_check(skin, s) for s in sent), skin
    assert not unit_skins.is_check("afc", "LANE_MOVE LANE=lane1 DISTANCE=50")   # Move's own stays Move
