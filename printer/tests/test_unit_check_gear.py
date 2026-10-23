"""Measuring Happy Hare's gear inside Check and measure (design/unit-setup/, "Gear calibration", C with B's mark, picked
22 October 2026): slot 1 with a ruler at a pen mark, the tube back on, the encoder learns from slot 1 and measures the
other slots; a Tradrack's one gear covers every slot; No ruler? Skip it keeps the design value. Also pins the two fixes:
the refusal says what's actually missing, and what's measured is read from save_variables."""

import copy
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import elyir_bench_intent as a  # noqa: E402
import filament_units as fu  # noqa: E402
from test_unit_adapters import tracker  # noqa: E402
from test_unit_check import ercf, finish, turtle, view  # noqa: E402

P = a.ActionPlan
OK = "// Gate {} - Filament detected. Marked available"


def saved(n=4, gear=None, encoder=None, name="ercf"):
    """Happy Hare 4's saved variables for one unit: gear rotation distances (-1 = not measured), the encoder's."""
    v = {f"mmu_{name}_gear_rotation_distances": gear if gear is not None else [-1] * n}
    if encoder is not None:
        v[f"mmu_{name}_encoder_resolution"] = encoder
    return {"save_variables": {"variables": v}}


def fresh(n=4, **mmu):
    """An ERCF on Happy Hare 4 whose gear and encoder aren't measured."""
    return {**ercf(n, encoder={"enabled": True}, **mmu), **saved(n)}


def tradrack(n=4, encoder=False):
    st = ercf(n, encoder={"enabled": True} if encoder else None)
    st["mmu_machine"]["unit_0"].update(name="tradrack", display_name="Tradrack 1", vendor="Tradrack",
                                       variable_rotation_distances=False)
    return {**st, **saved(n, name="tradrack")}


def run(status, now=0.0, gear=False):
    t = tracker(status)
    payload = {"unit": 0, **({"gear": 1} if gear else {})}
    planned = a.plan_action("unit_check_start", payload, t)
    assert planned and planned[0][0] == P.UNIT_CHECK
    assert t.unit_check_input(planned[0][1], now=now)
    return t


def tap(t, aid, now, **args):
    planned = a.plan_action(aid, args, t)
    assert planned, aid
    assert t.unit_check_input(planned[0][1], now=now), aid
    return t.work(now=now)


def slots_pass(t, n, now=0.0):
    """Every slot's check passes; returns what's sent next."""
    out = t.work(now=now)
    for g in range(n):
        assert out == [("macro", f"MMU_CHECK_GATE GATE={g} QUIET=1")], out
        now += 4
        out = finish(t, [OK.format(g)], now=now)
    return out, now + 2


def ruler(t, now, mm=98.5, v4=True):
    """From the gear's first screen to "Put the tube back on"."""
    grip = " GRIP=1" if v4 else ""
    assert tap(t, "unit_check_gear_start", now) == []
    assert view(t, now)["gear"]["step"] == "free"
    assert tap(t, "unit_check_gear_off", now) == [("macro", f"MMU_SELECT GATE=0\nMMU_TEST_MOVE MOVE=20{grip}")]
    assert finish(t, ["// Moved 20.00mm"], now=now + 1) == []
    assert view(t, now + 4)["gear"]["step"] == "mark"
    assert tap(t, "unit_check_gear_marked", now + 5) == [("macro", f"MMU_TEST_MOVE MOVE=100{grip}")]
    finish(t, ["// Moved 100.00mm"], now=now + 6)
    v = view(t, now + 9)
    assert v["gear"]["step"] == "ruler" and v["headline"] == "Measure from the outlet to your mark."
    assert tap(t, "unit_check_gear_type", now + 10) == []
    assert view(t, now + 10)["headline"] == "What does it say at your mark?"
    assert tap(t, "unit_check_gear_measured", now + 11, mm=mm) == [("macro", f"MMU_TEST_MOVE MOVE=-120{grip}")]
    out = finish(t, ["// Moved -120.00mm"], now=now + 12)
    assert out == [("macro", f"MMU_CALIBRATE_GEAR LENGTH=100 MEASURED={mm:g}")]
    finish(t, [f"// MMU gear stepper for gate 0 'rotation_distance' calculated to be 22.3 (currently: 22.6)",
               "// Calibrated rotation distance (22.3) has been saved for gate 0"], now=now + 14)
    return now + 18


# ---- what Happy Hare has measured, from save_variables --------------------------------------------------

def test_the_gear_is_read_from_save_variables_not_the_mmu_status():
    hh = fu.HappyHare()
    unit = {"index": 0, "offset": 0, "n": 4}
    st = fresh()
    s = hh.gear_state(st, unit)
    assert (s["measured"], s["encoder"], s["encoder_ok"], s["per_gate"], s["v4"], s["needed"]) == \
        (False, True, False, True, True, True)
    st = {**fresh(), **saved(gear=[22.6, -1, -1, -1], encoder=1.42)}
    s = hh.gear_state(st, unit)
    assert s["measured"] and s["gear0"] == 22.6 and s["encoder_ok"] and not s["needed"]
    # Happy Hare 3: no unit name in the variable, and no version in mmu_machine
    v3 = ercf(encoder={"enabled": True})
    del v3["mmu_machine"]["happy_hare_version"]
    v3["save_variables"] = {"variables": {"mmu_gear_rotation_distances": [0, 22.1, 22.0, 22.2]}}
    s = hh.gear_state(v3, unit)
    assert not s["measured"] and not s["v4"] and s["needed"]   # 0 is "not measured" too
    # no saved variables at all: nothing can be said, so nothing is asked
    s = hh.gear_state(ercf(), unit)
    assert s["measured"] is None and s["needed"] is None
    # the mmu status says nothing about calibration either way
    assert "calibrated" not in str(ercf()["mmu"]).lower()


def test_a_tradrack_has_one_gear_and_an_encoder_only_with_its_mod():
    hh = fu.HappyHare()
    s = hh.gear_state(tradrack(), {"index": 0, "offset": 0, "n": 4})
    assert not s["per_gate"] and not s["encoder"] and s["needed"]
    s = hh.gear_state(tradrack(encoder=True), {"index": 0, "offset": 0, "n": 4})
    assert s["encoder"]


def test_the_gear_commands_are_happy_hares_only():
    hh = fu.HappyHare()
    assert hh.gear_push(100, v4=True) == "MMU_TEST_MOVE MOVE=100 GRIP=1"
    assert hh.gear_push(100, v4=False) == "MMU_TEST_MOVE MOVE=100"
    assert hh.calibrate_gear(98.5) == "MMU_CALIBRATE_GEAR LENGTH=100 MEASURED=98.5"
    assert hh.calibrate_gate(3, v4=True) == "MMU_CALIBRATE_GATE GATE=3"
    assert hh.calibrate_gate(3, v4=False) == "MMU_CALIBRATE_GATES GATE=3"
    for cmds in (fu.KlipperAce(), fu.Elyir(), fu.Afc(["lane1"])):
        assert not fu.can(cmds, "calibrate_gear") and not fu.can(cmds, "calibrate_encoder")


# ---- when it's offered ---------------------------------------------------------------------------------

def test_the_gear_step_comes_only_when_the_gear_isnt_measured():
    t = run(fresh())
    v = view(t, 1)
    assert (v["n"], v["of"]) == (1, 4)
    assert v["note"] == "0 of 4 checked. Then Bench measures the gear and the tube to the head."
    measured = {**fresh(), **saved(gear=[22.6] * 4, encoder=1.42)}
    t = run(measured)
    assert view(t, 1)["of"] == 3
    out, now = slots_pass(t, 4)
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]
    # no save_variables: Bench can't tell, so the check goes straight on (and Happy Hare's own refusal says)
    t = run(ercf())
    out, now = slots_pass(t, 4)
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]


def test_care_offers_measure_the_gear_for_happy_hare_only_and_never_while_printing():
    t = tracker({**fresh(), **saved(gear=[22.6] * 4, encoder=1.42)})
    offer = t.unit_list(t.spools(), 0)[0]["gear"]
    assert offer["action"]["label"] == "Measure the gear again" and offer["action"]["args"] == {"unit": 0, "gear": 1}
    t = tracker(fresh())
    assert t.unit_list(t.spools(), 0)[0]["gear"]["action"]["label"] == "Measure the gear"
    t = tracker(turtle())
    assert t.unit_list(t.spools(), 0)[0]["gear"] is None
    assert a.plan_action("unit_check_start", {"unit": 0, "gear": 1}, t) == []
    t = tracker(fresh(), watch_only=True)
    assert t.units() is None or all(u["gear"] is None for u in t.unit_list(t.spools(), 0))
    t = tracker(fresh())
    t.update_status({"print_stats": {"state": "printing"}})
    assert t.unit_gear_offer(0)["why"] == "Not while it's printing."
    assert a.plan_action("unit_check_start", {"unit": 0, "gear": 1}, t) == []
    # asked from Care: the gear step comes even though it's measured
    t = run({**fresh(), **saved(gear=[22.6] * 4, encoder=1.42)}, gear=True)
    assert view(t, 1)["of"] == 4


# ---- C with B's mark, on an ERCF ------------------------------------------------------------------------

def test_an_ercf_slot_1_by_ruler_then_the_encoder_measures_the_rest():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    assert out == []
    v = view(t, now)
    assert v["step"] == "gear" and (v["n"], v["of"]) == (2, 4)
    assert v["headline"] == "One ruler, then the encoder does the rest."
    g = v["gear"]
    assert g["step"] == "plan" and g["kind"] == "per_slot"
    assert [p["title"] for p in g["plan"]] == ["Slot 1, with a ruler", "Put the tube back on",
                                               "Slots 2 to 4, by the unit's encoder"]
    assert g["side"]["text"].endswith("it measures the other three about as closely as a ruler.")
    assert [x["label"] for x in v["actions"]] == ["No ruler? Skip it", "Start", "Stop"]
    now = ruler(t, now)
    v = view(t, now)
    assert v["headline"] == "Slot 1's gear is measured. Put the tube back on."
    assert v["detail"].endswith("Then the encoder measures the other slots.")
    assert v["gear"]["rows"][0] == {"title": "Slot 1 · 98.5 mm for 100", "tone": None,
                                    "sub": "Its gear pushed 1.5% short. Bench corrected it."}
    assert v["gear"]["rows"][1]["title"] == "Slots 2 to 4 · next"
    # the tube back on: the encoder learns from slot 1, then each other slot
    assert tap(t, "unit_check_gear_on", now) == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_ENCODER")]
    v = view(t, now + 5)
    assert v["headline"] == "The encoder is learning from slot 1…" and v["gear"]["cards"][0]["line"] == "Measuring…"
    assert v["gear"]["progress"]["seconds"] == 30 and v["gear"]["progress"]["elapsed"] == 5
    out = finish(t, ["// Calibrating over 400.0mm...", "// Calculated resolution of the encoder: 1.4200 (currently: 1.0)",
                     "// Encoder calibration has been saved"], now=now + 20)
    assert out == [("macro", "MMU_CALIBRATE_GATE GATE=1")]
    now += 24
    v = view(t, now)
    assert v["headline"] == "The encoder is measuring slot 2…"
    assert [(c["state"], c["line"]) for c in v["gear"]["cards"]] == [
        ("ok", "By ruler"), ("now", "Measuring…"), ("next", "Next"), ("next", "Next")]
    assert v["gear"]["cards"][0]["sub"] == "98.5 for 100" and v["gear"]["progress"]["seconds"] == 105
    for g in (1, 2, 3):
        out = finish(t, [f"// Calibrating gate {g} over 400.0mm...",
                         f"// Calibrated rotation distance (22.4) has been saved for gate {g}"], now=now)
        now += 4
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]
    finish(t, ["// Calibrated bowden length is 742.0mm"], now=now)
    v = view(t, now + 4)
    assert v["step"] == "ready" and (v["n"], v["of"]) == (4, 4)
    rows = {r["title"]: r["sub"] for r in v["ready"]["rows"]}
    assert rows["The gear · measured"] == "Slot 1 by ruler, 98.5 for 100. Slots 2 to 4 by the encoder."
    assert "The tube to the head · 742 mm" in rows


def test_happy_hare_3_has_no_grip_and_its_own_gate_command():
    st = fresh()
    del st["mmu_machine"]["happy_hare_version"]
    st["save_variables"] = {"variables": {"mmu_gear_rotation_distances": [-1] * 4}}
    t = run(st)
    out, now = slots_pass(t, 4)
    now = ruler(t, now, v4=False)
    tap(t, "unit_check_gear_on", now)
    out = finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    assert out == [("macro", "MMU_CALIBRATE_GATES GATE=1")]


def test_the_number_bench_expects_and_measure_again():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    tap(t, "unit_check_gear_start", now)
    tap(t, "unit_check_gear_off", now)
    finish(t, ["// Moved 20.00mm"], now=now + 1)
    tap(t, "unit_check_gear_more", now + 4)   # nothing showing yet: 20 more
    finish(t, ["// Moved 20.00mm"], now=now + 5)
    tap(t, "unit_check_gear_marked", now + 8)
    finish(t, ["// Moved 100.00mm"], now=now + 9)
    tap(t, "unit_check_gear_type", now + 12)
    # 114: near enough to ask, with Use 114 mm
    assert tap(t, "unit_check_gear_measured", now + 13, mm=114) == []
    sheet = view(t, now + 13)["gear"]["sheet"]
    assert sheet["title"] == "114 mm is more than Bench expects." and not sheet["far"]
    assert [x["label"] for x in sheet["actions"]] == ["Measure again", "Use 114 mm"]
    # 140 can't be the gear: no Use, and That's it with it is refused
    assert tap(t, "unit_check_gear_type", now + 14) == []
    assert tap(t, "unit_check_gear_measured", now + 15, mm=140) == []
    sheet = view(t, now + 15)["gear"]["sheet"]
    assert sheet["title"] == "140 mm can't be the gear." and sheet["far"]
    assert [x["label"] for x in sheet["actions"]] == ["Type it again", "Measure again"]
    assert not t.unit_check_input({"op": "gear_use", "mm": 140})
    # Measure again: back in 100, out 100
    assert tap(t, "unit_check_gear_again", now + 16) == [("macro", "MMU_TEST_MOVE MOVE=-100 GRIP=1\nMMU_TEST_MOVE MOVE=100 GRIP=1")]
    assert view(t, now + 17)["headline"] == "Measuring again…"
    finish(t, ["// Moved -100.00mm", "// Moved 100.00mm"], now=now + 18)
    v = view(t, now + 21)
    assert v["gear"]["sheet"] is None and v["gear"]["tries"] == 2 and v["gear"]["step"] == "pad"
    # 112 then Use 112 mm: everything pushed (20 + 20 + 100) comes back before the gear is saved
    tap(t, "unit_check_gear_measured", now + 22, mm=112)
    assert tap(t, "unit_check_gear_use", now + 23, mm=112) == [("macro", "MMU_TEST_MOVE MOVE=-140 GRIP=1")]
    assert finish(t, ["// Moved -140.00mm"], now=now + 24) == [("macro", "MMU_CALIBRATE_GEAR LENGTH=100 MEASURED=112")]
    # bad numbers never reach the printer
    assert a.plan_action("unit_check_gear_measured", {"mm": "abc"}, t) == []
    assert a.plan_action("unit_check_gear_measured", {"mm": 0}, t) == []


def test_no_ruler_skip_keeps_the_design_value_and_ready_says_so():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    assert tap(t, "unit_check_gear_skip", now) == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]
    finish(t, ["// Calibrated bowden length is 742.0mm"], now=now + 2)
    rows = {r["title"]: r["sub"] for r in view(t, now + 6)["ready"]["rows"]}
    assert rows["The gear · design value"] == \
        "Skipped. Happy Hare uses the unit's design value until it's measured, from Care."


def test_a_slot_the_encoder_throws_out_can_be_tried_again_or_kept_at_its_design_value():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    now = ruler(t, now)
    tap(t, "unit_check_gear_on", now)
    finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    now += 24
    out = finish(t, ["// Calibrating gate 1 over 400.0mm...",
                     "// Calibration ignored because it is not considered valid (>20% difference from reference gate 0)"],
                 now=now)
    assert out == []
    v = view(t, now + 4)
    assert v["headline"] == "Slot 2 wasn't measured." and v["tone"] == "failed"
    assert "kept its design value" in v["detail"]
    assert [x["label"] for x in v["actions"]] == ["Try again", "Skip it", "Stop"]
    assert tap(t, "unit_check_retry", now + 5) == [("macro", "MMU_CALIBRATE_GATE GATE=1")]
    finish(t, ["!! Calibration for gate 1 failed. Aborting, because:", "Filament not detected"], now=now + 6)
    assert "stopped partway" in view(t, now + 9)["detail"]
    assert tap(t, "unit_check_skip", now + 10) == [("macro", "MMU_CALIBRATE_GATE GATE=2")]
    for g in (2, 3):
        out = finish(t, [f"// Calibrated rotation distance (22.4) has been saved for gate {g}"], now=now + 11 + g)
    finish(t, ["// Calibrated bowden length is 742.0mm"], now=now + 20)
    rows = {r["title"]: r["sub"] for r in view(t, now + 24)["ready"]["rows"]}
    assert rows["The gear · measured"] == \
        "Slot 1 by ruler, 98.5 for 100. Slots 3 and 4 by the encoder. Slot 2 kept the design value."


def test_a_slot_left_out_of_the_check_isnt_run_by_the_encoder():
    t = run(fresh())
    t.work(now=0)
    finish(t, [OK.format(0)], now=4)
    finish(t, ["// Gate 1 marked EMPTY (no filament detected during homing)"], now=8)
    assert t.unit_check_input({"op": "skip"})   # slot 2
    out = t.work(now=12)
    for g in (2, 3):
        out = finish(t, [OK.format(g)], now=12 + g * 4)
    now = ruler(t, 30)
    tap(t, "unit_check_gear_on", now)
    out = finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    assert out == [("macro", "MMU_CALIBRATE_GATE GATE=2")]
    assert [c["state"] for c in view(t, now + 24)["gear"]["cards"]] == ["ok", "skipped", "now", "next"]


def test_a_tradrack_one_ruler_covers_every_slot():
    t = run(tradrack())
    out, now = slots_pass(t, 4)
    v = view(t, now)
    assert v["headline"] == "One ruler covers all 4 slots."
    assert v["detail"] == "Tradrack 1 has no encoder. One gear drives every slot, so measuring slot 1 measures them all."
    assert v["gear"]["art"] == "one_gear" and len(v["gear"]["plan"]) == 2
    now = ruler(t, now)
    v = view(t, now)
    assert v["detail"].endswith("Then Bench measures the tube to the head.")
    assert v["gear"]["rows"][1]["title"] == "Slots 2 to 4 · measured too"
    assert tap(t, "unit_check_gear_on", now) == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]
    finish(t, ["// Calibrated bowden length is 742.0mm"], now=now + 2)
    rows = {r["title"]: r["sub"] for r in view(t, now + 6)["ready"]["rows"]}
    assert rows["The gear · measured"] == "Slot 1 by ruler, 98.5 for 100. One gear drives all 4 slots."


def test_a_tradrack_with_its_encoder_mod_has_the_encoder_learn_but_no_per_slot_runs():
    t = run(tradrack(encoder=True))
    out, now = slots_pass(t, 4)
    now = ruler(t, now)
    assert tap(t, "unit_check_gear_on", now) == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_ENCODER")]
    out = finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]


def test_stop_with_filament_out_of_the_outlet_pulls_it_back_first():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    tap(t, "unit_check_gear_start", now)
    tap(t, "unit_check_gear_off", now)
    finish(t, ["// Moved 20.00mm"], now=now + 1)
    tap(t, "unit_check_gear_marked", now + 4)
    finish(t, ["// Moved 100.00mm"], now=now + 5)
    assert t.unit_check_input({"op": "stop"})
    assert t.work(now=now + 9) == [("macro", "MMU_TEST_MOVE MOVE=-120 GRIP=1")]
    assert view(t, now + 9)["detail"] == "Bench pulls the filament back into the unit first."
    t.change_done(None, now=now + 10)
    t.work(now=now + 12)
    assert t.intent(now=now + 13)["unit_check"] is None


def test_a_push_that_fails_says_so_and_tries_again():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    tap(t, "unit_check_gear_start", now)
    tap(t, "unit_check_gear_off", now)
    finish(t, ["!! Operation not possible. No MMU gate selected"], now=now + 1)
    v = view(t, now + 4)
    assert v["detail"] == "Bench couldn't select slot 1. Try again."
    assert [x["label"] for x in v["actions"]] == ["Try again", "Skip it", "Stop"]
    assert tap(t, "unit_check_retry", now + 5) == [("macro", "MMU_SELECT GATE=0\nMMU_TEST_MOVE MOVE=20 GRIP=1")]


# ---- the two fixes: the refusal says what's missing ------------------------------------------------------

REFUSED_ENCODER = ["!! Warning: Calibration steps are not complete for MMU ercf:",
                   "Required:", "- Use MMU_CALIBRATE_ENCODER (with first gate of unit selected)",
                   "Optional (handled by autocal/autotune):",
                   "- Use MMU_CALIBRATE_GEAR (on first gate) to calibrate gear rotation_distance for first gate of unit"]


def test_a_fresh_ercf_on_happy_hare_4_is_refused_for_its_encoder_and_bench_says_encoder():
    st = {**ercf(encoder={"enabled": True}), **saved(gear=[22.6] * 4)}   # gear measured, encoder not
    t = tracker(st)
    t.unit_check_input({"op": "start", "unit": 0}, now=0)
    t._check.gear = None   # as on a printer whose saved variables Bench couldn't read: the console alone says it
    out, now = slots_pass(t, 4)
    finish(t, REFUSED_ENCODER, now=now)
    v = view(t, now + 4)
    assert v["headline"] == "The tube wasn't measured."
    assert v["detail"].startswith("Happy Hare won't measure the tube until the unit's encoder is measured.")
    assert "gear and selector" not in v["detail"] and "selector" not in v["detail"]
    assert [x["label"] for x in v["actions"]] == ["Measure the gear", "Skip it", "Stop"]
    # Measure the gear: the gear step, then back to the tube
    assert tap(t, "unit_check_gear_now", now + 5) == []
    assert view(t, now + 5)["gear"]["step"] == "plan" and view(t, now + 5)["of"] == 4
    now = ruler(t, now + 6)
    tap(t, "unit_check_gear_on", now)
    finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    for g in (1, 2, 3):
        out = finish(t, [f"// Calibrated rotation distance (22.4) has been saved for gate {g}"], now=now + 24 + g)
    assert out == [("macro", "MMU_SELECT GATE=0\nMMU_CALIBRATE_BOWDEN")]


def test_the_refusal_names_the_gear_or_the_selector_only_when_those_are_missing():
    def refused(lines, st=None):
        t = tracker(st or ercf())
        t.unit_check_input({"op": "start", "unit": 0}, now=0)
        out, now = slots_pass(t, 4)
        finish(t, lines, now=now)
        return view(t, now + 4)

    v = refused(["!! Warning: Calibration steps are not complete:", "Required:",
                 "- Use MMU_CALIBRATE_GEAR (with gate 0 selected)", "- Use MMU_CALIBRATE_ENCODER (with gate 0 selected)"])
    assert v["detail"].startswith("Happy Hare won't measure the tube until slot 1's gear and the unit's encoder are measured.")
    v = refused(["!! Warning: Calibration steps are not complete for MMU ercf:", "Required:",
                 "- Use MMU_CALIBRATE_SELECTOR to calibrate selector for gates: 0"])
    assert v["detail"].startswith("Happy Hare won't measure the tube until the selector is measured.")
    assert "Advanced" in v["detail"] and "gear" not in v["detail"]
    assert [x["label"] for x in v["actions"]] == ["Try again", "Skip it", "Stop"]
    # the console names nothing Bench knows: save_variables say what's missing
    st = {**ercf(encoder={"enabled": True}), **saved(gear=[22.6] * 4)}
    t = tracker(st)
    t.unit_check_input({"op": "start", "unit": 0}, now=0)
    t._check.gear = None
    out, now = slots_pass(t, 4)
    finish(t, ["!! Warning: Calibration steps are not complete for MMU ercf:"], now=now)
    assert view(t, now + 4)["detail"].startswith("Happy Hare won't measure the tube until the unit's encoder is measured.")


def test_refused_at_slot_1_for_the_encoder_measures_the_gear_then_goes_on_checking():
    """Happy Hare checks its essential calibration before MMU_CHECK_GATE too, so a fresh ERCF can stop at slot 1."""
    t = run(fresh())
    assert t.work(now=0) == [("macro", "MMU_CHECK_GATE GATE=0 QUIET=1")]
    finish(t, REFUSED_ENCODER, now=3)
    v = view(t, 6)
    assert v["headline"] == "Slot 1 didn't pass."
    assert v["detail"].startswith("Happy Hare won't check slot 1 until the unit's encoder is measured.")
    assert [x["label"] for x in v["actions"]] == ["Measure the gear", "Skip slot 1", "Stop"]
    tap(t, "unit_check_gear_now", 7)
    v = view(t, 7)
    assert v["step"] == "gear" and [p["title"] for p in v["gear"]["plan"]][-1] == "Slots 2 to 4, by the unit's encoder"
    now = ruler(t, 8)
    tap(t, "unit_check_gear_on", now)
    out = finish(t, ["// Calculated resolution of the encoder: 1.4200 (currently: 1.0)"], now=now + 20)
    assert out == [("macro", "MMU_CHECK_GATE GATE=0 QUIET=1")]   # back to the slots
    out = finish(t, [OK.format(0)], now=now + 30)
    for g in (1, 2, 3):
        assert out == [("macro", f"MMU_CHECK_GATE GATE={g} QUIET=1")]
        out = finish(t, [OK.format(g)], now=now + 34 + g * 4)
    assert out == [("macro", "MMU_CALIBRATE_GATE GATE=1")]   # then each slot by the encoder, then the tube


def test_skipping_the_gear_happy_hare_asked_for_leaves_its_refusal_to_skip():
    t = run(fresh())
    t.work(now=0)
    finish(t, REFUSED_ENCODER, now=3)
    tap(t, "unit_check_gear_now", 7)
    tap(t, "unit_check_gear_skip", 8)
    v = view(t, 9)
    assert v["step"] == "slots" and v["headline"] == "Slot 1 didn't pass."
    assert v["detail"] == ("Happy Hare won't check slot 1 until the unit's encoder is measured. "
                           "The gear can be measured from Care later.")
    assert [x["label"] for x in v["actions"]] == ["Try again", "Skip slot 1", "Stop"]


def test_refused_at_another_slot_says_to_check_slot_1_first():
    t = run(fresh())
    t.work(now=0)
    finish(t, ["// Gate 0 marked EMPTY (no filament detected during homing)"], now=1)
    assert t.unit_check_input({"op": "skip"})
    t.work(now=3)
    finish(t, REFUSED_ENCODER, now=4)
    v = view(t, 7)
    assert v["detail"].endswith("check slot 1 first, then try again.")
    assert v["actions"][0]["label"] == "Try again"


def test_a_skipped_gear_isnt_asked_again_until_its_measured():
    t = run(fresh())
    out, now = slots_pass(t, 4)
    tap(t, "unit_check_gear_skip", now)
    assert t.gear_skipped == ["ERCF 1"] and t.gear_skipped_dirty
    t._check = None
    planned = a.plan_action("unit_check_start", {"unit": 0}, t)
    assert t.unit_check_input(planned[0][1], now=now + 10)
    assert view(t, now + 10)["of"] == 3                 # no gear step this time
    # Care still offers it, and measuring it forgets the skip
    t._check = None
    assert a.plan_action("unit_check_start", {"unit": 0, "gear": 1}, t)
    t.gear_skipped_dirty = False
    t.unit_check_input({"op": "start", "unit": 0, "gear": True}, now=now + 20)
    t._check.gear.outcome = "measured"
    t._note_gear(t._check)
    assert t.gear_skipped == [] and t.gear_skipped_dirty
