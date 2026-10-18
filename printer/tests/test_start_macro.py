"""Elyir Bench's start macro on a printer someone else set up (printer/klipper/elyir-bench.cfg, docs/start-macro.md).
ELYIR_BENCH_PRINT_START runs before the person's own start G-code: it heats while the file is paused (warming,
soaking, the same steps as the shared PRINT_START's), then their start G-code runs as one block (own), shown as
the leveling step under their own name for it. ELYIR_BENCH_PRINT_START_DONE clears the stage: printing has started,
even when nothing says "Printing..." and the slicer reports no layers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

from test_intent import ready_tracker, T0  # noqa: E402

OURS = "gcode_macro _ELYIR_BENCH_PRINT_START"
FILE = "benchy.gcode"


def stranger():
    """A printer with only Elyir Bench's start macro: no shared PRINT_START, no unit, no layer numbers."""
    t = ready_tracker()
    t.update_status({OURS: {"stage": "", "applied_z": 0.0},
                     "gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS": {"chamber_max": 0.0}}, now=T0)
    return t


def warming(t, now=T0 + 1):
    t.update_status({"print_stats": {"state": "paused", "filename": FILE, "info": {}},
                     "pause_resume": {"is_paused": True}, OURS: {"stage": "warming"},
                     "heater_bed": {"temperature": 40.0, "target": 60.0}}, now=now)


def own(t, now=T0 + 60):
    t.update_status({"print_stats": {"state": "printing"}, "pause_resume": {"is_paused": False},
                     OURS: {"stage": "own"}, "heater_bed": {"temperature": 60.0, "target": 60.0}}, now=now)


def done(t, applied_z=0.0, now=T0 + 120):
    t.update_status({OURS: {"stage": "", "applied_z": applied_z}}, now=now)


def test_the_start_macro_is_subscribed_with_the_rest():
    assert a.IntentTracker.SUBSCRIBE[OURS] == ["stage", "applied_z"]
    assert a.IntentTracker.SUBSCRIBE["gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS"] == ["chamber_max", "z_moves"]


def test_warming_and_soaking_are_the_same_steps_as_the_shared_print_start():
    t = stranger()
    warming(t)
    i = t.intent(T0 + 1)
    assert (i["state"], i["phase"]) == ("preparing", "warming")
    assert [x["id"] for x in i["actions"]] == ["cancel", "stop_now"], "Cancel works: the file is paused"
    assert [(s["label"], s["status"]) for s in i["steps"]] == [
        ("Warming the bed", "now"), ("Letting the bed settle", "todo"), ("Your start G-code", "todo"),
        ("Heating the nozzle", "todo")]
    assert i["art"]["stage"] == "warming"
    t.update_status({OURS: {"stage": "soaking"}}, now=T0 + 30)
    assert t.intent(T0 + 30)["phase"] == "soaking"


def test_their_own_start_gcode_is_the_leveling_step_drawn_from_their_messages():
    t = stranger()
    warming(t)
    own(t)
    i = t.intent(T0 + 60)
    assert (i["state"], i["phase"]) == ("preparing", "leveling")
    now = [s for s in i["steps"] if s["status"] == "now"]
    assert now == [{"id": "leveling", "label": "Your start G-code", "status": "now", "detail": "Finding home"}]
    assert i["art"]["stage"] == "home"
    t.update_status({"display_status": {"message": "Calibrating mesh..."}}, now=T0 + 70)
    i = t.intent(T0 + 70)
    assert i["art"]["stage"] == "mesh" and i["phase"] == "leveling"


def test_the_stage_clearing_after_their_start_gcode_means_printing_has_started():
    t = stranger()
    warming(t)
    own(t)
    t.update_status({"display_status": {"message": "Printing..."}}, now=T0 + 80)   # RatOS says so inside its macro
    assert t.intent(T0 + 80)["state"] == "preparing", "still their start G-code until DONE"
    t.update_status({"display_status": {"message": ""}}, now=T0 + 90)
    done(t)
    i = t.intent(T0 + 120)
    assert i["state"] == "printing" and i["headline"] == "Benchy"
    assert i["steps"] == []


def test_without_any_message_done_still_starts_the_print():
    t = stranger()
    warming(t)
    own(t)
    done(t)
    assert t.intent(T0 + 120)["state"] == "printing"


def test_cancel_while_warming_is_not_a_print_that_started():
    t = stranger()
    warming(t)
    t.update_status({"print_stats": {"state": "cancelled"}, "pause_resume": {"is_paused": False},
                     OURS: {"stage": ""}}, now=T0 + 10)
    i = t.intent(T0 + 10)
    assert i["state"] == "ready" and i["headline"] == "Print stopped."


def test_the_next_print_starts_over():
    t = stranger()
    warming(t)
    own(t)
    done(t)
    t.update_status({"print_stats": {"state": "complete"}}, now=T0 + 600)
    t.update_status({"print_stats": {"state": "standby"}}, now=T0 + 700)
    warming(t, now=T0 + 800)
    i = t.intent(T0 + 800)
    assert (i["state"], i["phase"]) == ("preparing", "warming")
    own(t, now=T0 + 860)
    assert t.intent(T0 + 860)["state"] == "preparing"


def test_the_first_layer_it_put_on_is_what_the_squish_starts_from():
    t = stranger()
    t.update_status({"save_variables": {"variables": {"first_layer_z": -0.05, "first_layer_against": "scan"}},
                     "motion_report": {"live_position": [100.0, 100.0, 0.2, 0.0]}}, now=T0)
    warming(t)
    own(t)
    done(t, applied_z=-0.05)
    t.update_status({"print_stats": {"info": {"current_layer": 1, "total_layer": 20}}}, now=T0 + 130)
    assert t._squish["applied"] == -0.05
    adj = t.intent(T0 + 130)["first_layer"]["adjust"]
    assert adj is not None and adj["total"] == -0.05


def test_a_print_without_it_keeps_the_shared_print_starts_rule():
    t = ready_tracker()
    t.update_status({"save_variables": {"variables": {"first_layer_z": -0.05, "first_layer_against": "scan"}},
                     OURS: {"stage": "", "applied_z": 0.0}}, now=T0)
    t.update_status({"print_stats": {"state": "printing", "filename": FILE, "info": {"current_layer": 1}}}, now=T0 + 1)
    assert t._squish["applied"] == -0.05


def test_the_chamber_limit_comes_from_either_settings():
    t = stranger()
    t.update_status({"temperature_sensor enclosure": {"temperature": 30.0},
                     "gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS": {"chamber_max": 45.0}}, now=T0)
    assert t.chamber_limit() == 45.0
    t.update_status({"gcode_macro _PRINT_START_SETTINGS": {"chamber_max": 50.0}}, now=T0)
    assert t.chamber_limit() == 50.0
