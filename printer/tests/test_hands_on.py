"""Move and heat by hand (design/hands-on/, C): jobs first (Get at the bed, Clean the nozzle, Heat the
nozzle, Let go of the motors), the controls one tap further. Never while printing; the first move
finds home; moves stay inside the printer's limits; heat set by hand turns itself off; words follow
what moves in Z."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402


def tracker(homed=True, pos=(175.0, 175.0, 30.0), extra=None, head_material="PETG"):
    t = a.IntentTracker("Workshop", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    t.has_unit = True
    status = {"print_stats": {"state": "standby", "filename": ""}, "pause_resume": {"is_paused": False},
              "heater_bed": {"temperature": 22, "target": 0}, "extruder": {"temperature": 25, "target": 0},
              "toolhead": {"homed_axes": "xyz" if homed else "", "axis_minimum": [0, 0, -5, 0], "axis_maximum": [350, 350, 340, 0]},
              "motion_report": {"live_position": [*pos, 0]},
              "ace": {"gate_color": ["F4F4F2", "1C1C1E"], "gate_material": ["PLA", head_material],
                      "selected_gate": 1, "slots": [{"status": "ready"}] * 2}}
    status.update(extra or {})
    t.update_status(status, now=0.0)
    return t


def act(t, action, now=1.0, **args):
    """Run an action like the component does; returns the gcode sent, one script per entry."""
    plan = a.plan_action(action, args, t)
    assert plan, f"{action} was refused"
    gcode = []
    for kind, payload in plan:
        if kind == a.ActionPlan.HANDS:
            t.hands_input(payload, now=now)
        elif kind == a.ActionPlan.WARM:
            t.warm_input(payload, now=now)
        elif kind == a.ActionPlan.GCODE:
            gcode.append(payload)
    return gcode + [script for _, script in t.work(now=now)]


def test_offered_when_free_with_the_words_for_a_gantry():
    t = tracker()
    h = t.intent(now=1.0)["hands"]
    assert h["why_not"] is None
    assert h["z_moves"] == "head"
    assert h["homed"] and h["position"] == {"x": 175.0, "y": 175.0, "z": 30.0}
    assert h["steps"] == [1, 10, 50]
    assert h["clean_temp"] == a.MATERIAL_TEMPS["PETG"]


def test_what_moves_in_z_comes_from_the_config():
    assert tracker(extra={"quad_gantry_level": {"applied": True}}).intent(now=1.0)["hands"]["z_moves"] == "head"
    assert tracker(extra={"z_tilt": {"applied": False}}).intent(now=1.0)["hands"]["z_moves"] == "bed"
    told = {"z_tilt": {}, a.ELYIR_BENCH_START_SETTINGS: {"z_moves": "head"}}
    assert tracker(extra=told).intent(now=1.0)["hands"]["z_moves"] == "head"


def test_not_while_printing():
    t = tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=1.0)
    assert t.hands_why_not() == "Not while it's printing."
    for action in a.HANDS_OPS:
        assert a.plan_action(action, {"axis": "z", "mm": 10}, t) == []


def test_a_move_is_one_absolute_move_inside_the_limits():
    t = tracker()
    assert act(t, "hands_move", axis="z", mm=10) == ["G90\nG1 Z40.00 F900"]
    # taps close together add up before live_position catches up
    assert act(t, "hands_move", now=2.0, axis="z", mm=10) == ["G90\nG1 Z50.00 F900"]
    assert act(t, "hands_move", now=3.0, axis="x", mm=50) == ["G90\nG1 X225.00 Y175.00 F6000"]


def test_moves_stop_at_the_edges_and_z_never_goes_below_the_floor():
    t = tracker(pos=(345.0, 175.0, 8.0))
    assert act(t, "hands_move", axis="x", mm=50) == ["G90\nG1 X350.00 Y175.00 F6000"]
    assert act(t, "hands_move", now=2.0, axis="z", mm=-10) == [f"G90\nG1 Z{a.HANDS_Z_FLOOR:.2f} F900"]
    assert act(t, "hands_move", now=3.0, axis="z", mm=-1) == []   # already there: nothing to send


def test_the_first_move_finds_home():
    t = tracker(homed=False)
    assert act(t, "hands_move", axis="z", mm=10) == ["G28"]
    h = t.intent(now=1.5)["hands"]
    assert h["homing"] and not h["homed"] and h["position"] is None


def test_get_at_the_bed_raises_first_then_moves_back():
    t = tracker()
    assert act(t, "hands_clear") == ["G90\nG1 Z150.00 F900\nG1 X175.00 Y340.00 F6000"]
    i = t.intent(now=2.0)
    assert i["phase"] == "hands_clear" and i["headline"] == "Out of the way"
    assert "The head is up at 150 mm" in i["detail"]
    assert [x["id"] for x in i["actions"]] == ["hands_done", "hands_lower"]
    t.update_status({"motion_report": {"live_position": [175, 340, 150, 0]}}, now=9.0)
    assert act(t, "hands_lower", now=10.0) == ["G90\nG1 Z30.00 F900"]
    assert t.intent(now=11.0)["phase"] != "hands_clear"


def test_get_at_the_bed_on_a_printer_whose_bed_moves():
    t = tracker(extra={"z_tilt": {}})
    act(t, "hands_clear")
    i = t.intent(now=2.0)
    assert "The bed is down at 150 mm" in i["detail"]
    assert i["actions"][1]["label"] == "Raise it again"


def test_get_at_the_bed_homes_first_and_has_nothing_to_go_back_to():
    t = tracker(homed=False)
    assert act(t, "hands_clear") == ["G28\nG90\nG1 Z150.00 F900"]
    assert [x["id"] for x in t.intent(now=2.0)["actions"]] == ["hands_done"]


def test_clean_the_nozzle_heats_for_the_head_spool_and_comes_to_the_front():
    t = tracker()
    temp = a.MATERIAL_TEMPS["PETG"]
    assert act(t, "hands_clean") == [f"M104 S{temp}\nG90\nG1 Z50.00 F900\nG1 X175.00 Y10.00 F6000"]
    t.update_status({"extruder": {"target": temp, "temperature": 120}}, now=2.0)
    i = t.intent(now=2.0)
    assert i["phase"] == "hands_clean" and f"heating to {temp}° for PETG" in i["detail"]
    t.update_status({"extruder": {"temperature": temp - 2}}, now=60.0)
    assert t.intent(now=60.0)["detail"].startswith("It's hot and at the front.")
    assert act(t, "hands_done", now=61.0) == ["M104 S0"]
    assert t.intent(now=62.0)["phase"] != "hands_clean"


def test_heat_set_by_hand_turns_itself_off():
    t = tracker()
    act(t, "hands_heat", heater="bed", target=80)
    act(t, "hands_nozzle", now=2.0)
    t.update_status({"extruder": {"target": 240}, "heater_bed": {"target": 80}}, now=3.0)
    later = 2.0 + a.HANDS_IDLE_SECONDS - 4 * 60
    i = t.intent(now=later)
    assert [x["id"] for x in i["actions"]] == ["hands_done", "hands_keep"]
    assert "turns off by itself in 4 minutes" in i["detail"]
    assert t.work(now=2.0 + a.HANDS_IDLE_SECONDS) == [("gcode", "M104 S0\nM140 S0")]
    assert t.intent(now=2.0 + a.HANDS_IDLE_SECONDS)["hands"]["held"] is None


def test_keep_it_hot_starts_the_wait_again():
    t = tracker()
    act(t, "hands_nozzle")
    t.update_status({"extruder": {"target": 240}}, now=2.0)
    act(t, "hands_keep", now=a.HANDS_IDLE_SECONDS - 60)
    assert t.work(now=a.HANDS_IDLE_SECONDS + 10) == []


def test_turned_off_elsewhere_lets_go():
    t = tracker()
    act(t, "hands_nozzle")
    t.update_status({"extruder": {"target": 240}}, now=2.0)
    t.work(now=2.0)
    t.update_status({"extruder": {"target": 0}}, now=3.0)
    t.work(now=3.0)
    assert t.intent(now=3.0)["hands"]["held"] is None


def test_cool_down_ends_a_job():
    t = tracker()
    act(t, "hands_clean")
    assert "TURN_OFF_HEATERS" in act(t, "cool_down", now=2.0)
    assert t.intent(now=3.0)["hands"]["held"] is None


def test_a_print_takes_over():
    t = tracker()
    act(t, "hands_clear")
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=2.0)
    assert t.work(now=2.0) == []
    assert t.intent(now=2.0)["hands"] is None


def test_motors_off_forgets_where_it_was():
    t = tracker()
    act(t, "hands_move", axis="z", mm=10)
    assert act(t, "hands_motors_off", now=2.0) == ["M84"]
    t.update_status({"toolhead": {"homed_axes": ""}}, now=2.5)
    assert act(t, "hands_move", now=3.0, axis="z", mm=10) == ["G28"]


def test_a_printer_that_reports_no_toolhead_only_heats():
    # a Kobra over Anycubic's LAN mode: heater settings only (bench/kobra_lan.py)
    t = tracker()
    del t.status["toolhead"]
    assert t.intent(now=1.0)["hands"]["can_move"] is False
    for action in a.HANDS_MOVES:
        assert a.plan_action(action, {"axis": "z", "mm": 10}, t) == []
    assert act(t, "hands_nozzle") == [f"M104 S{a.MATERIAL_TEMPS['PETG']}"]
    assert act(t, "hands_heat", now=2.0, heater="bed", target=80) == ["M140 S80"]


def test_push_filament_through_once_the_nozzle_is_hot():
    t = tracker()
    assert t.intent(now=1.0)["hands"]["can_push"] is False
    assert a.plan_action("hands_push", {"mm": 10}, t) == [(a.ActionPlan.HANDS, {"mm": 10, "op": "push"})]
    assert t.hands_input({"op": "push", "mm": 10}, now=1.0) is False   # cold: Klipper would refuse it
    t.update_status({"extruder": {"temperature": 240, "target": 240, "can_extrude": True}}, now=2.0)
    assert t.intent(now=2.0)["hands"]["can_push"] is True
    push = "SAVE_GCODE_STATE NAME=elyir_bench_hands_push\nM83\nG1 E{} F150\nRESTORE_GCODE_STATE NAME=elyir_bench_hands_push"
    assert act(t, "hands_push", now=3.0, mm=50) == [push.format(50)]
    assert act(t, "hands_push", now=4.0, mm=-10) == [push.format(-10)]
    assert t.hands_input({"op": "push", "mm": 500}, now=5.0) is False


def test_nozzle_hot_offers_a_push():
    t = tracker()
    act(t, "hands_nozzle")
    t.update_status({"extruder": {"temperature": 240, "target": 240, "can_extrude": True}}, now=2.0)
    i = t.intent(now=2.0)
    assert i["phase"] == "hands_nozzle" and "pushing filament through" in i["detail"]
    assert [(x["id"], x.get("args")) for x in i["actions"]] == [("hands_done", None), ("hands_push", {"mm": 10})]
