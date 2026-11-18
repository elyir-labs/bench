"""Spots the printer goes to (design/spots/): the cutter walked through (B), numbers under Advanced (C), kept in
save_variables (pick 2, B)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

CUT = "gcode_macro CUT_TIP"


def tracker(macro=True, saved=None, printing=False, x=150.0):
    t = a.IntentTracker("Studio")
    t.set_klippy_state("ready", "Printer is ready")
    st = {"print_stats": {"state": "printing" if printing else "standby"},
          "toolhead": {"homed_axes": "xyz", "axis_minimum": [0, 0, -5], "axis_maximum": [350, 350, 340]},
          "motion_report": {"live_position": [x, 200.0, 20.0, 0]},
          "save_variables": {"variables": dict(saved or {})}, "extruder": {"temperature": 25, "target": 0}}
    if macro:
        st[CUT] = {"pin_loc_x": 20, "pin_loc_x_compressed": 10, "pin_loc_y": 331}
    t.update_status(st)
    return t


def sent(t):
    return [script for kind, script in t.work() if kind == "gcode"]


def test_the_cutter_shows_in_care_not_set_with_the_macro_s_guesses():
    v = tracker().intent()["spots"]
    row = v["rows"][0]
    assert row["kind"] == "cutter" and not row["set"] and row["line"] == "Where the lever meets its screw. Not set yet."
    assert [(x["id"], x["value"], x["set"]) for x in row["values"]] == [("x_touch", 20, False), ("x_pressed", 10, False), ("y", 331, False)]
    assert tracker(macro=False).intent()["spots"] is None


def test_a_saved_spot_reads_as_set():
    row = tracker(saved={"spot_cutter_x_touch": 21.4, "spot_cutter_x_pressed": 1.0, "spot_cutter_y": 331}).intent()["spots"]["rows"][0]
    assert row["set"] and row["line"] == "Touches at X 21.4, Y 331; pressed at X 1."


def test_walked_through_the_cutter_and_saved_only_after_a_clean_cut():
    t = tracker()
    assert t.spots.input({"op": "start", "kind": "cutter"}, now=10)
    go = sent(t)[0]
    assert "G1 Z20.00" in go and "G1 X50.00 Y331.00" in go          # 30 mm clear of the guess, at a safe height
    g = t.intent(now=10)["spots"]["guide"]
    assert (g["step"], g["n"], g["of"], g["axis"]) == ("touch", 1, 3, "xy")
    for _ in range(3):                                                # in line with the screw, front to back
        assert t.spots.input({"op": "move", "axis": "y", "mm": -4}, now=11)
    assert sent(t)[-1] == "G90\nG1 Y319.00 F1200"
    for _ in range(28):
        assert t.spots.input({"op": "move", "mm": -1}, now=11)
    assert not t.spots.input({"op": "move", "mm": -20}, now=11)      # no bigger than the biggest step
    assert sent(t)[-1] == "G90\nG1 X22.00 F1200"
    assert t.spots.input({"op": "next"}, now=12)
    g = t.intent(now=12)["spots"]["guide"]
    assert g["step"] == "press" and g["steps"] == [1, 0.1] and g["kept"]["x_touch"] == 22 and g["kept"]["y"] == 319
    assert not t.spots.input({"op": "move", "axis": "y", "mm": 1}, now=12)   # pressing only goes sideways
    assert not t.spots.input({"op": "move", "mm": -10}, now=12)      # only small steps once it touches
    t.spots.input({"op": "move", "mm": -0.5}, now=12)
    assert not t.spots.input({"op": "next"}, now=12)                  # not pressed in enough
    assert "further toward the screw" in t.intent(now=12)["spots"]["guide"]["error"]
    for _ in range(20):
        t.spots.input({"op": "move", "mm": -1}, now=13)
    assert sent(t)[-1].endswith("F300")                               # pressing goes slowly
    assert t.spots.input({"op": "next"}, now=13)
    assert t.intent(now=13)["spots"]["guide"]["step"] == "try"
    assert t.spots.input({"op": "try"}, now=14)
    assert sent(t) == ["CUT_TIP FINAL_EJECT=1 PIN_X=22 PIN_X_PRESSED=1.5 PIN_Y=319"]
    assert t.intent(now=14)["spots"]["guide"]["trying"]
    t.on_gcode_response("// Tip cut complete", now=40)
    g = t.intent(now=40)["spots"]["guide"]
    assert not g["trying"] and g["asked"]["title"] == "Did it cut clean?"
    assert t.spots.input({"op": "answer", "clean": True}, now=41)
    assert sent(t) == ["SAVE_VARIABLE VARIABLE=spot_cutter_x_touch VALUE=22\n"
                       "SAVE_VARIABLE VARIABLE=spot_cutter_x_pressed VALUE=1.5\n"
                       "SAVE_VARIABLE VARIABLE=spot_cutter_y VALUE=319"]
    assert t.intent(now=41)["spots"]["guide"] is None


def test_not_all_the_way_goes_back_to_pressing():
    t = tracker()
    t.spots.input({"op": "start", "kind": "cutter"}, now=0)
    t.spots.guide.update(step=2, kept={"y": 331, "x_touch": 22, "x_pressed": 12}, tried=True)
    assert t.spots.input({"op": "answer", "clean": False}, now=1)
    assert t.intent(now=1)["spots"]["guide"]["step"] == "press"


def test_cancel_backs_off_the_screw():
    t = tracker()
    t.spots.input({"op": "start", "kind": "cutter"}, now=0)
    sent(t)
    t.spots.input({"op": "move", "mm": -10}, now=1)
    sent(t)
    assert t.spots.input({"op": "cancel"}, now=2)
    assert sent(t) == ["G90\nG1 X50.00 F1200"] and t.spots.guide is None


def test_numbers_under_advanced_are_checked_then_saved():
    t = tracker()
    assert not t.spots.input({"op": "set", "kind": "cutter", "values": {"x_touch": 21, "x_pressed": 400, "y": 331}})
    assert "outside where the head can go" in t.intent()["spots"]["error"]
    assert not t.spots.input({"op": "set", "kind": "cutter", "values": {"x_touch": 21, "x_pressed": 20.5, "y": 331}})
    assert t.spots.input({"op": "set", "kind": "cutter", "values": {"x_touch": "21", "x_pressed": "1", "y": "331"}})
    assert sent(t)[-1].startswith("SAVE_VARIABLE VARIABLE=spot_cutter_x_touch VALUE=21\n")


def test_nothing_moves_while_printing():
    t = tracker(printing=True)
    assert a.plan_action("spot_start", {"kind": "cutter"}, t) == []
    assert not t.spots.input({"op": "start", "kind": "cutter"})
    assert t.intent()["spots"]["why_not"] == "Not while it's printing."
    assert a.plan_action("spot_cancel", {}, t) == [(a.ActionPlan.SPOT, {"op": "cancel"})]
