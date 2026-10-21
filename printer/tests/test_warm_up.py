"""Warming up before a print (design/warm-up/, direction D): Ready offers one tap for the spool
in the head and Move and heat beside it (its Heat the bed asks for the rest); the printer warms the bed, the chamber when the
material wants one (up to PRINT_START's own limit) and the nozzle a little; it says when it's
warm, tells the phone, and turns itself off after half an hour without a print."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

CHAMBER = "temperature_sensor Chamber"


def tracker(chamber_max=30.0, head_material="ASA", chamber_sensor=True):
    t = a.IntentTracker("Workshop", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    t.has_unit = True
    status = {"print_stats": {"state": "standby", "filename": ""}, "pause_resume": {"is_paused": False},
              "heater_bed": {"temperature": 22, "target": 0}, "extruder": {"temperature": 25, "target": 0},
              "gcode_macro _PRINT_START_SETTINGS": {"chamber_max": chamber_max},
              "ace": {"gate_color": ["F4F4F2", "1C1C1E", "8A8D91", "3B82F6"],
                      "gate_material": ["PLA", "PETG", head_material or "", "PLA"],
                      "selected_gate": 2 if head_material else -1,
                      "slots": [{"status": "ready"}] * 4}}
    if chamber_sensor:
        status[CHAMBER] = {"temperature": 22}
    t.update_status(status, now=0.0)
    return t


def act(t, action, now=1.0, **args):
    plan = a.plan_action(action, args, t)
    assert plan, f"{action} was refused"
    gcode = []
    for kind, payload in plan:
        if kind == a.ActionPlan.WARM:
            t.warm_input(payload, now=now)
        elif kind == a.ActionPlan.GCODE:
            gcode.append(payload)
    return gcode + [s for _, s in t.work(now=now)]


def temps(t, now, bed, chamber=None, bed_target=None):
    st = {"heater_bed": {"temperature": bed}}
    if bed_target is not None:
        st["heater_bed"]["target"] = bed_target
    if chamber is not None:
        st[CHAMBER] = {"temperature": chamber}
    t.update_status(st, now=now)
    return [s for _, s in t.work(now=now)]


def view(t, now=2.0):
    return t.intent(now=now)


# ---- where it starts -----------------------------------------------------------------

def test_ready_offers_the_spool_in_the_head_and_move_and_heat():
    i = view(tracker())
    assert i["phase"] == "idle"
    assert [(x["id"], x["label"], x["primary"]) for x in i["actions"]] == [
        ("warm_up", "Warm up for ASA", True), ("hands_open", "Move and heat", False)]
    assert i["actions"][0]["args"] == {"material": "ASA"}


def test_nothing_in_the_head_asks():
    i = view(tracker(head_material=None))
    assert [(x["id"], x["label"]) for x in i["actions"]] == [("warm_choose", "Warm up"), ("hands_open", "Move and heat")]


def test_the_question_lists_loaded_materials_head_first():
    opts = view(tracker())["warm"]["options"]
    assert [(o["label"], o["args"]["note"]) for o in opts] == [
        ("ASA", "Gray, in the head"), ("PLA", "White and Blue"), ("PETG", "Black, slot 2")]


def test_not_offered_while_printing_or_warm():
    t = tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode"}}, now=1.0)
    assert a.plan_action("warm_up", {"material": "ASA"}, t) == []
    t = tracker()
    t.update_status({"heater_bed": {"target": 60}}, now=1.0)
    i = view(t)
    assert [x["id"] for x in i["actions"]] == ["cool_down"] and "options" not in (i["warm"] or {})


# ---- warming -------------------------------------------------------------------------------

def test_asa_warms_bed_chamber_and_a_little_nozzle():
    t = tracker()
    assert act(t, "warm_up", material="ASA") == ["M140 S105", "M104 S150"]
    t.update_status({"heater_bed": {"target": 105}, "extruder": {"target": 150}}, now=1.5)
    i = view(t)
    assert (i["state"], i["phase"], i["headline"]) == ("ready", "warming_up", "Warming up for ASA")
    assert i["detail"].endswith("You can print now; it carries on.")
    assert [x["id"] for x in i["actions"]] == ["cool_down"]
    w = i["warm"]
    assert w["active"] and not w["warm"] and w["bed"] == {"temperature": 22, "target": 105}
    assert w["chamber"] == {"temperature": 22, "target": 30} and w["minutes"] >= 1


def test_pla_warms_only_the_bed():
    t = tracker()
    assert act(t, "warm_up", material="PLA") == ["M140 S60", "M104 S150"]
    assert view(t)["warm"]["chamber"] is None


def test_no_chamber_wait_on_a_printer_without_one():
    assert tracker(chamber_max=0).warm_targets("ASA")["chamber"] == 0
    assert tracker(chamber_sensor=False).warm_targets("ASA")["chamber"] == 0


def test_warm_when_bed_and_chamber_get_there_then_off_after_half_an_hour():
    t = tracker()
    act(t, "warm_up", material="ASA")
    temps(t, 100.0, 105, 25, bed_target=105)
    assert view(t, 101.0)["phase"] == "warming_up"     # the chamber isn't there yet
    temps(t, 400.0, 105, 30)
    i = view(t, 401.0)
    assert (i["phase"], i["headline"]) == ("warmed", "Warm for ASA")
    assert i["detail"] == "Staying warm for 30 minutes. Print whenever you like."
    assert temps(t, 400.0 + 29 * 60, 105, 31) == []
    assert temps(t, 400.0 + 30 * 60, 105, 31) == ["TURN_OFF_HEATERS"]
    assert t._warm is None


def test_a_chamber_that_never_gets_there_counts_as_warm_after_twenty_minutes():
    t = tracker()
    act(t, "warm_up", material="ASA")
    temps(t, 100.0, 105, 26, bed_target=105)
    temps(t, 1.0 + 20 * 60, 105, 27)
    assert view(t, 2.0 + 20 * 60)["phase"] == "warmed"


def test_a_print_takes_over():
    t = tracker()
    act(t, "warm_up", material="ASA")
    t.update_status({"heater_bed": {"target": 105}, "print_stats": {"state": "printing", "filename": "x.gcode"}}, now=50.0)
    assert t.work(now=50.0) == [] and t._warm is None


def test_cool_down_stops_it():
    t = tracker()
    act(t, "warm_up", material="ASA")
    assert act(t, "cool_down") == ["TURN_OFF_HEATERS"]
    assert t._warm is None


def test_heaters_turned_off_elsewhere_end_it():
    t = tracker()
    act(t, "warm_up", material="ASA")
    t.update_status({"heater_bed": {"target": 105}}, now=2.0)
    temps(t, 60.0, 50, bed_target=0)
    assert t._warm is None


def test_a_target_that_arrives_late_keeps_warming():
    """A Kobra over LAN mode is asked every 3 s, so its new targets come a few seconds after (7 October 2026)."""
    t = tracker()
    act(t, "warm_up", material="ASA")
    temps(t, 8.0, 25, bed_target=0)
    assert t._warm is not None
    temps(t, 9.0, 26, bed_target=105)
    assert view(t, 9.5)["warm"]["active"] is True


def test_a_printer_that_never_takes_it_gives_up():
    t = tracker()
    act(t, "warm_up", material="ASA")
    temps(t, 20.0, 25, bed_target=0)
    assert t._warm is not None
    temps(t, 1.0 + a.WARM_TARGET_GRACE + 1, 25, bed_target=0)
    assert t._warm is None


def test_refuses_an_unknown_material():
    assert a.plan_action("warm_up", {"material": "WOOD"}, tracker()) == []


# ---- the phone ---------------------------------------------------------------------------------

def test_the_phone_hears_when_it_is_warm():
    t = tracker()
    n = a.Notifier("b")
    n.observe(view(t, 0.5), now=0.5)
    act(t, "warm_up", material="ASA")
    t.update_status({"heater_bed": {"target": 105}}, now=1.5)
    assert n.observe(view(t, 2.0), now=2.0) == []
    temps(t, 400.0, 105, 30)
    sent = n.observe(view(t, 401.0), now=401.0)
    assert [(e["kind"], e["title"], e["body"]) for e in sent] == [
        ("warmed", "Workshop is warm for ASA", "Staying warm for 30 minutes.")]
