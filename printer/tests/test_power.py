# Pins turning the printer off (design/power/, A, picked 5 October 2026): heaters off, wait for the nozzle to drop
# below the hot-end fan's 50°, then go; never mid-print; Keep it on and Turn off now; a refusal is a problem.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from elyir_bench_intent import ActionPlan, POWER_COOL_TEMP, POWER_MAX_WAIT_SECONDS, plan_action  # noqa: E402
from test_intent import T0, ready_tracker  # noqa: E402


def hot(t, nozzle=186.0):
    t.update_status({"extruder": {"temperature": nozzle, "target": 0.0}}, now=T0)
    return t


def run(t, action, now=T0):
    plan = plan_action(action, {}, t)
    for kind, payload in plan:
        if kind == ActionPlan.POWER:
            t.power_input(payload, now=now)
    return plan


def test_offered_when_ready_with_why_not_while_printing():
    t = ready_tracker()
    assert t.intent(T0)["power"]["allowed"] is True
    p = ready_tracker("printing")
    view = p.intent(T0)["power"]
    assert view["allowed"] is False and view["why"] == "Not while it's printing."
    assert plan_action("power_off", {}, p) == []
    assert plan_action("power_off", {}, ready_tracker("paused")) == []


def test_turn_off_switches_the_heaters_off_then_waits_for_the_nozzle():
    t = hot(ready_tracker())
    plan = run(t, "power_off")
    assert (ActionPlan.GCODE, "TURN_OFF_HEATERS") in plan
    assert plan[-1] == (ActionPlan.POWER, {"op": "start", "kind": "off"})
    i = t.intent(T0 + 5)
    assert (i["state"], i["phase"], i["headline"]) == ("preparing", "turning_off", "Turning off")
    assert "stops in about 3 minutes, at 50°" in i["detail"]
    assert [a["id"] for a in i["actions"]] == ["power_keep", "power_now"]
    assert [a["label"] for a in i["actions"]] == ["Keep it on", "Turn off now"]
    assert t.power_due(T0 + 5) is None
    assert i["power"]["kind"] == "off" and i["power"]["progress"] == 0


def test_it_goes_once_the_nozzle_is_below_the_fan_temperature():
    t = hot(ready_tracker())
    run(t, "power_off")
    t.update_status({"extruder": {"temperature": 118.0}}, now=T0 + 60)
    assert round(t.intent(T0 + 60)["power"]["progress"], 2) == 0.5
    assert t.power_due(T0 + 60) is None
    t.update_status({"extruder": {"temperature": POWER_COOL_TEMP - 1}}, now=T0 + 150)
    assert t.power_due(T0 + 150) == "off"
    t.power_going(T0 + 150)
    assert t.power_due(T0 + 151) is None   # once
    i = t.intent(T0 + 151)
    assert i["actions"] == [] and i["detail"].startswith("Now.") and i["power"]["going"] is True


def test_cool_already_goes_at_once_and_restart_says_so():
    t = ready_tracker()
    run(t, "power_restart")
    assert t.power_due(T0) == "restart"
    t2 = hot(ready_tracker())
    run(t2, "power_restart")
    i = t2.intent(T0)
    assert i["phase"] == "restarting" and i["actions"][1]["label"] == "Restart now"


def test_keep_it_on_and_turn_off_now():
    t = hot(ready_tracker())
    run(t, "power_off")
    run(t, "power_keep")
    assert t.intent(T0)["state"] == "ready" and t.power_due(T0) is None
    assert plan_action("power_keep", {}, t) == []
    run(t, "power_off")
    run(t, "power_now")
    assert t.power_due(T0) == "off"


def test_klipper_down_or_a_long_wait_goes_anyway():
    t = hot(ready_tracker())
    run(t, "power_off")
    assert t.power_due(T0 + POWER_MAX_WAIT_SECONDS) == "off"
    t2 = hot(ready_tracker())
    run(t2, "power_off")
    t2.set_klippy_state("shutdown", "MCU 'mcu' shutdown", now=T0 + 1)
    assert t2.power_due(T0 + 1) == "off"


def test_when_the_system_refuses_it_says_so_and_can_try_again():
    t = ready_tracker()
    run(t, "power_off")
    t.power_going(T0)
    t.power_failed("DBusError: Permission denied")
    i = t.intent(T0 + 3)
    assert (i["state"], i["phase"]) == ("problem", "power_failed")
    assert i["headline"] == "Workshop couldn't turn itself off."
    assert i["raw"] == "DBusError: Permission denied"
    assert [a["id"] for a in i["actions"]] == ["power_retry", "power_keep"]
    assert t.power_due(T0 + 3) is None
    run(t, "power_retry")
    assert t.power_due(T0 + 4) == "off"
