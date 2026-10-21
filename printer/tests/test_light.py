"""The chamber light (design/chamber-light/, A): Bench finds the light, asks once when a printer has two, turns it on
full white, gives a status strip its effects back when it goes off, and turns it off by itself after the printer has
been quiet for 30 minutes, never during a print."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

PIN, STRIP = "output_pin case_light", "neopixel caselight"


def tracker(lights=(PIN,), extra=None, choice=None):
    t = a.IntentTracker("Desk", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    status = {"print_stats": {"state": "standby", "filename": ""}, "pause_resume": {"is_paused": False},
              "heater_bed": {"temperature": 22, "target": 0}, "extruder": {"temperature": 25, "target": 0}}
    if PIN in lights:
        status[PIN] = {"value": 0.0}
    if STRIP in lights:
        status["led_effect rainbow"] = {"enabled": True}
    status.update(extra or {})
    t.update_status(status, now=0.0)
    t.light_objects = list(lights)
    t.light_choice = choice
    return t


def act(t, action, now=1.0, **args):
    plan = a.plan_action(action, args, t)
    assert plan, f"{action} was refused"
    for kind, payload in plan:
        assert kind == a.ActionPlan.LIGHT
        t.light_input(payload, now=now)
    return [script for _, script in t.work(now=now)]


def test_the_light_is_found_by_name():
    objects = ["output_pin caselight", "neopixel sb_leds", "neopixel caselight", "output_pin goose_belt",
               "neopixel btt_mini12864", "output_pin knomi_pwr", "led_effect rainbow", "led chamber"]
    assert a.light_candidates(objects) == ["output_pin caselight", "neopixel caselight", "led chamber"]


def test_no_light_no_switch():
    t = tracker(lights=())
    assert t.intent(now=1.0)["light"] is None
    assert a.plan_action("light_on", {}, t) == []


def test_an_on_off_light_switches_its_pin():
    t = tracker()
    assert t.intent(now=1.0)["light"] == {"on": False, "ask": None}
    assert act(t, "light_on") == ["SET_PIN PIN=case_light VALUE=1"]
    t.update_status({PIN: {"value": 1.0}}, now=2.0)
    assert t.intent(now=2.0)["light"]["on"] is True
    assert act(t, "light_off", now=3.0) == ["SET_PIN PIN=case_light VALUE=0"]


def test_a_pin_turned_on_elsewhere_shows_as_on():
    t = tracker()
    t.update_status({PIN: {"value": 1.0}}, now=1.0)
    assert t.intent(now=1.0)["light"]["on"] is True


def test_a_strip_goes_white_and_gets_its_status_effects_back():
    t = tracker(lights=(STRIP,))
    on = act(t, "light_on")
    assert on == ['STOP_LED_EFFECTS LEDS="neopixel:caselight"\nSET_LED LED=caselight RED=1 GREEN=1 BLUE=1']
    assert t.intent(now=1.0)["light"]["on"] is True
    t.update_status({"led_effect rainbow": {"enabled": False}}, now=2.0)
    assert act(t, "light_off", now=3.0) == ["SET_LED LED=caselight RED=0 GREEN=0 BLUE=0\nSET_LED_EFFECT EFFECT=rainbow"]
    assert t.intent(now=3.0)["light"]["on"] is False


def test_a_strip_without_effects_just_goes_white():
    t = tracker(lights=(STRIP,))
    del t.status["led_effect rainbow"]
    assert act(t, "light_on") == ["SET_LED LED=caselight RED=1 GREEN=1 BLUE=1"]


def test_two_lights_ask_once_which_lights_the_bed():
    t = tracker(lights=(PIN, STRIP))
    light = t.intent(now=1.0)["light"]
    assert light["on"] is False
    assert [o["label"] for o in light["ask"]] == ["On/off light", "LED strip"]
    assert a.plan_action("light_on", {}, t) and not t.light_input({"op": "on"}, now=1.0)
    assert act(t, "light_try", name=STRIP)[0].endswith("SET_LED LED=caselight RED=1 GREEN=1 BLUE=1")
    # trying the other turns the first off again
    sent = act(t, "light_try", now=2.0, name=PIN)
    assert sent == ["SET_LED LED=caselight RED=0 GREEN=0 BLUE=0", "SET_PIN PIN=case_light VALUE=1"]
    t.update_status({PIN: {"value": 1.0}}, now=2.5)
    act(t, "light_pick", now=3.0, name=PIN)
    assert t.light_choice == PIN and t.light_choice_dirty
    assert t.intent(now=3.0)["light"] == {"on": True, "ask": None}


def test_a_light_picked_in_the_settings_needs_no_ask():
    t = tracker(lights=(PIN, STRIP), choice=STRIP)
    assert t.intent(now=1.0)["light"] == {"on": False, "ask": None}


def test_off_by_itself_after_30_quiet_minutes():
    t = tracker()
    act(t, "light_on", now=10.0)
    t.update_status({PIN: {"value": 1.0}}, now=11.0)
    assert t.work(now=10.0 + a.LIGHT_IDLE_SECONDS - 1) == []
    assert t.work(now=10.0 + a.LIGHT_IDLE_SECONDS) == [("gcode", "SET_PIN PIN=case_light VALUE=0")]


def test_never_off_by_itself_during_a_print():
    t = tracker()
    act(t, "light_on", now=10.0)
    t.update_status({PIN: {"value": 1.0}, "print_stats": {"state": "printing", "filename": "x.gcode"}}, now=11.0)
    assert t.work(now=10.0 + 3 * a.LIGHT_IDLE_SECONDS) == []
    # the 30 minutes start when the print ends
    t.update_status({"print_stats": {"state": "complete", "filename": "x.gcode"}}, now=20000.0)
    assert t.work(now=20000.0) == []
    assert t.work(now=20000.0 + a.LIGHT_IDLE_SECONDS) == [("gcode", "SET_PIN PIN=case_light VALUE=0")]


def test_works_from_away():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "door"))
    import door  # noqa: E402
    for action in a.LIGHT_OPS:
        assert action in door.AWAY_ACTIONS, action
