import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from elyir_bench_intent import Notifier, NOTIFY_REPEAT_GUARD_SECONDS  # noqa: E402

T0 = 1_757_000_000.0
JOB = {"name": "Phone stand", "filename": "phone_stand.gcode"}


def intent(state, phase, headline="", detail="", job=JOB):
    return {"state": state, "phase": phase, "headline": headline, "detail": detail,
            "job": job, "printer": {"name": "Workshop"}}


def run(n, *steps):
    """Feed (t, intent) pairs; return every event, flattened."""
    out = []
    for t, i in steps:
        out += n.observe(i, T0 + t)
    return out


def test_first_look_only_primes():
    n = Notifier("b1")
    assert n.observe(intent("needs_you", "runout", "White PLA ran out."), T0) == []


def test_runout_during_print_notifies_with_first_sentence():
    n = Notifier("b1")
    ev = run(n, (0, intent("printing", "printing")),
             (5, intent("needs_you", "runout", "White PLA ran out.",
                        "Load a new spool into slot 2, or let me switch. I'll keep everything warm.")))
    assert len(ev) == 1
    e = ev[0]
    assert e["kind"] == "needs_you" and e["urgency"] == "high"
    assert e["title"] == "Workshop needs you"
    assert e["body"] == "White PLA ran out. Load a new spool into slot 2, or let me switch."
    assert e["tag"] == "workshop-attention" and e["url"] == "/"
    assert e["boot"] == "b1" and e["job"] == "phone_stand.gcode"


def test_same_alert_again_soon_is_a_flap():
    n = Notifier("b1")
    runout = intent("needs_you", "runout", "White PLA ran out.")
    ev = run(n, (0, intent("printing", "printing")), (5, runout),
             (60, intent("printing", "printing")), (90, runout))
    assert [e["kind"] for e in ev] == ["needs_you"]
    later = run(n, (100, intent("printing", "printing")), (100 + NOTIFY_REPEAT_GUARD_SECONDS + 1, runout))
    assert [e["kind"] for e in later] == ["needs_you"]


def test_problem_only_when_something_was_happening():
    n = Notifier("b1")
    idle_problem = run(n, (0, intent("ready", "idle", job=None)),
                       (5, intent("problem", "shutdown", "The printer stopped itself.", job=None)))
    assert idle_problem == []
    n = Notifier("b1")
    ev = run(n, (0, intent("printing", "printing")),
             (5, intent("problem", "heater", "The nozzle or bed isn't heating properly.", "I stopped the print. Check it.")))
    assert [(e["kind"], e["title"]) for e in ev] == [("problem", "Workshop stopped")]


def test_offline_flapping_after_restart_stays_quiet():
    n = Notifier("b1")
    ev = run(n, (0, intent("problem", "offline", job=None)),
             (5, intent("preparing", "starting_up", job=None)),
             (9, intent("problem", "offline", job=None)))
    assert ev == []


def test_finished_then_ready_to_lift_once_each():
    n = Notifier("b1")
    ev = run(n, (0, intent("printing", "printing")),
             (10, intent("finished", "cooling", "Done.")),
             (600, intent("finished", "ready_to_lift", "Done.")),
             (601, intent("ready", "idle", job=None)),
             (602, intent("finished", "ready_to_lift", "Done.")))
    assert [e["kind"] for e in ev] == ["finished", "ready_to_lift"]
    assert ev[0]["title"] == "Workshop: Phone stand is done"
    assert "I'll tell you" in ev[0]["body"]
    assert ev[1]["title"] == "Workshop: Phone stand is ready to lift off"
    assert ev[0]["tag"] == ev[1]["tag"] == "workshop-job"
    assert ev[0]["urgency"] == "normal"


def test_finished_already_cool_is_one_message():
    n = Notifier("b1")
    ev = run(n, (0, intent("printing", "printing")), (10, intent("finished", "ready_to_lift", "Done.")))
    assert [e["kind"] for e in ev] == ["finished"]
    assert "Lift it off whenever you like" in ev[0]["body"]


def test_next_job_can_finish_again():
    n = Notifier("b1")
    other = {"name": "Benchy", "filename": "benchy.gcode"}
    ev = run(n, (0, intent("printing", "printing")), (10, intent("finished", "ready_to_lift")),
             (20, intent("ready", "idle", job=None)),
             (30, intent("preparing", "heating", job=other)), (40, intent("printing", "printing", job=other)),
             (50, intent("finished", "cooling", job=other)))
    assert [(e["kind"], e["job"]) for e in ev] == [("finished", "phone_stand.gcode"), ("finished", "benchy.gcode")]


def test_ids_rise_and_survive_a_restart():
    a = Notifier("b1")
    ev1 = run(a, (0, intent("printing", "printing")), (5, intent("needs_you", "runout", "x")))
    b = Notifier("b2")   # Moonraker restarted: new boot, clock-based ids still go up
    ev2 = run(b, (6, intent("printing", "printing")), (7, intent("needs_you", "color_change", "y")))
    assert ev2[0]["id"] > ev1[0]["id"] and ev2[0]["boot"] == "b2"


def test_same_runout_in_the_next_print_still_notifies():
    n = Notifier("b1")
    runout = intent("needs_you", "runout", "White PLA ran out.")
    ev = run(n, (0, intent("printing", "printing")), (5, runout),
             (30, intent("printing", "printing")), (60, intent("finished", "ready_to_lift")),
             (70, intent("ready", "idle", job=None)),
             (80, intent("preparing", "heating")),          # same file again
             (90, intent("printing", "printing")), (95, runout))
    assert [e["kind"] for e in ev] == ["needs_you", "finished", "needs_you"]
