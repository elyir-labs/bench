import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import elyir_bench_care as care  # noqa: E402

T0 = 1_757_000_000.0
H = 3600.0


def totals(hours=0.0, metres=0.0):
    return {"total_print_time": hours * H, "total_filament_used": metres * 1000}


def by_name(s):
    return {i["name"]: i for i in s["items"]}


def test_defaults_count_from_now_so_nothing_is_overdue_on_day_one():
    entries = care.default_entries(totals(hours=900), T0)   # an old printer: 900 h already
    s = care.summary(entries, totals(hours=900), T0)
    assert s["due"] == 0 and s["hint"] is None
    assert [i["name"] for i in s["items"]] == ["Wipe the bed", "Clean the nozzle", "Check the belts", "Lubricate the rails"]
    assert by_name(s)["Wipe the bed"]["label"] == "0 of 40 print hours"


def test_due_after_enough_printing_and_hint_names_the_first():
    entries = care.default_entries(totals(), T0)
    s = care.summary(entries, totals(hours=160), T0 + 86400)
    names = by_name(s)
    assert names["Wipe the bed"]["due"] and names["Clean the nozzle"]["due"]
    assert not names["Check the belts"]["due"]
    assert names["Check the belts"]["label"] == "160 of 300 print hours"
    assert s["due"] == 2
    assert s["items"][0]["due"] and s["items"][1]["due"]
    assert s["hint"] == "Time to wipe the bed. 1 more in Care."


def test_done_starts_a_fresh_count_like_mainsail():
    entries = care.default_entries(totals(), T0)
    bed = next(k for k, v in entries.items() if v["name"] == "Wipe the bed")
    writes = care.perform(entries, bed, totals(hours=45), T0 + 100)
    assert len(writes) == 2
    old = writes[bed]
    assert old["end_time"] == T0 + 100 and old["end_printtime"] == 45 * H
    fresh_id, fresh = next((k, v) for k, v in writes.items() if k != bed)
    assert fresh["last_entry"] == bed and fresh["start_printtime"] == 45 * H and fresh["end_time"] is None
    entries.update(writes)
    s = care.summary(entries, totals(hours=46), T0 + 200)
    assert by_name(s)["Wipe the bed"] == {**by_name(s)["Wipe the bed"], "id": fresh_id, "due": False, "label": "1 of 40 print hours"}
    assert care.perform(entries, bed, totals(hours=50), T0 + 300) == {}   # already done


def test_later_quiets_it_for_a_few_print_hours_or_days():
    entries = care.default_entries(totals(), T0)
    bed = next(k for k, v in entries.items() if v["name"] == "Wipe the bed")
    snoozes = {bed: care.later(bed, totals(hours=41), T0)}
    s = care.summary(entries, totals(hours=42), T0 + 3600, snoozes)
    assert not by_name(s)["Wipe the bed"]["due"] and by_name(s)["Wipe the bed"]["snoozed"]
    assert by_name(care.summary(entries, totals(hours=47), T0 + 3600, snoozes))["Wipe the bed"]["due"]
    assert by_name(care.summary(entries, totals(hours=42), T0 + 4 * 86400, snoozes))["Wipe the bed"]["due"]


def test_mainsail_entries_with_filament_and_days_and_its_init_marker():
    entries = {
        "init": {"name": "MAINTENANCE_INIT"},
        "log": {"name": "Replaced hotend", "reminder": {"type": None}, "end_time": None},
        "f": care.new_entry("Dry the PETG", "", {"type": "one-time", "filament": {"bool": True, "value": 100},
                                                  "printtime": {"bool": False}, "date": {"bool": False}}, totals(metres=10), T0),
        "d": care.new_entry("Check the fans", "", {"type": "repeat", "date": {"bool": True, "value": 30},
                                                    "printtime": {"bool": True, "value": 1000}, "filament": {"bool": False}}, totals(), T0),
    }
    s = care.summary(entries, totals(hours=1, metres=60), T0 + 31 * 86400)
    names = by_name(s)
    assert set(names) == {"Dry the PETG", "Check the fans"}
    assert names["Dry the PETG"]["label"] == "50 of 100 m of filament"
    assert names["Check the fans"]["due"] and names["Check the fans"]["label"] == "31 of 30 days"


# ---- wired into the intent and the notifier --------------------------------

from elyir_bench_intent import Notifier  # noqa: E402
from test_intent import ready_tracker  # noqa: E402


def due_summary():
    entries = care.default_entries(totals(), T0)
    return care.summary(entries, totals(hours=45), T0)


def test_ready_screen_mentions_due_care_last_and_only_when_idle():
    t = ready_tracker()
    t.care = due_summary()
    i = t.intent(1_757_000_000.0)
    assert (i["state"], i["phase"]) == ("ready", "care_due")
    assert i["detail"].endswith("Time to wipe the bed.")
    assert i["care"]["hint"] == "Time to wipe the bed." and i["care"]["due"] == 1
    t.update_status({"heater_bed": {"temperature": 50.0, "target": 60.0}})
    warm = t.intent(1_757_000_000.0)
    assert warm["phase"] == "warm" and warm["care"]["hint"] is None and warm["care"]["due"] == 1


def intent(state, care_summary, phase="idle"):
    return {"state": state, "phase": phase, "headline": "", "detail": "", "job": None,
            "printer": {"name": "Workshop"}, "care": care_summary}


def test_care_due_notifies_once_while_ready_never_mid_print():
    n = Notifier("b1")
    s = due_summary()
    assert n.observe(intent("printing", care.summary({}, totals(), T0)), T0) == []   # primes
    assert n.observe(intent("printing", s, "printing"), T0 + 1) == []                # due, but printing
    ev = n.observe(intent("ready", s, "care_due"), T0 + 2)
    assert [(e["kind"], e["urgency"], e["tag"], e["url"], e["job"]) for e in ev] == [("care_due", "low", "workshop-care", "/care", None)]
    assert ev[0]["title"] == "Workshop: time to wipe the bed"
    assert ev[0]["body"].startswith("Wipe the build plate")
    assert n.observe(intent("ready", s, "care_due"), T0 + 3) == []


def test_care_due_again_after_a_snooze_runs_out_but_not_after_a_restart():
    s = due_summary()
    bed = s["items"][0]["id"]
    snoozed = dict(s, items=[dict(s["items"][0], due=False, snoozed=True)] + s["items"][1:], due=0)
    n = Notifier("b1")
    n.observe(intent("ready", care.summary({}, totals(), T0)), T0)
    assert len(n.observe(intent("ready", s, "care_due"), T0 + 1)) == 1
    assert n.observe(intent("ready", snoozed), T0 + 2) == []
    again = n.observe(intent("ready", s, "care_due"), T0 + 3)
    assert [e["kind"] for e in again] == ["care_due"] and bed
    fresh = Notifier("b2")   # Moonraker restarted with the task already due
    assert fresh.observe(intent("ready", s, "care_due"), T0 + 4) == []
