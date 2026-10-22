"""Setting up a Happy Hare or AFC unit from the screen (design/unit-setup/, B, stage 2): which unit, which board and
how many slots, then the installer (its command's lines heard as the component hears them), then stage 1's check as
the rest of the setup, or the way back with Put it back."""

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "installer"))
import elyir_bench_intent as a  # noqa: E402
import elyir_bench as installer  # noqa: E402
from test_unit_check import ercf  # noqa: E402

P = a.ActionPlan
MMB = "/dev/serial/by-id/usb-Klipper_stm32g0b1xx_4F0034000A50425539393020-if00"


def bare(now=0.0, **over):
    """A printer with no filament unit (one spool), whose installer can set one up."""
    t = a.IntentTracker("Workshop")
    t.has_unit = False
    t.unit_installer = True
    t.set_klippy_state("ready")
    t.update_status({"print_stats": {"state": "standby"}, "extruder": {"temperature": 25, "target": 0}})
    for k, v in over.items():
        setattr(t, k, v)
    return t


def scan(found=(MMB,), kept=None):
    """What `elyir-bench --json unit scan` answers: the catalog, with these boards on USB that Klipper doesn't use."""
    here = {"serial": [f.rsplit("/", 1)[-1] for f in found], "can": []}
    got = [{"mcu": f"/dev/serial/by-id/{n}", "chip": installer.serial_chip(n),
            "words": f"{installer.chip_words(installer.serial_chip(n))} on USB"} for n in here["serial"]]
    return {"catalog": installer.unit_catalog(), "found": got,
            "probably": {u: installer.unit_probably(u, got) for u in installer.UNIT_KINDS}, "kept": kept}


def act(t, aid, now=1.0, **args):
    plan = a.plan_action(aid, args, t)
    assert plan, f"{aid} refused"
    for kind, payload in plan:
        assert kind == P.UNIT_SETUP
        assert t.unit_setup_input(payload, now=now), f"{aid} {payload} not taken"
    return t.work(now=now)


def view(t, now=2.0):
    return t.intent(now=now)["unit_setup"]


def labels(v):
    return [x["label"] for x in v["actions"]]


def started(t=None, found=(MMB,)):
    t = t or bare()
    jobs = act(t, "unit_setup_start")
    assert jobs == [("unit_scan", None)]
    t.unit_setup_heard({"started": "unit-scan", "pid": 42})
    t.unit_setup_heard(scan(found))
    return t


def picked(unit="ercf_v2", found=(MMB,)):
    t = started(found=found)
    act(t, "unit_setup_unit", unit=unit)
    act(t, "unit_setup_next")
    return t


# ---- offered where, and never where ------------------------------------------------------------------------

def test_set_one_up_is_offered_on_a_printer_with_no_unit_only():
    t = bare()
    offer = t.intent(now=0)["unit_setup_offer"]
    assert offer["action"]["id"] == "unit_setup_start" and offer["action"]["label"] == "Set one up" and offer["why"] is None
    assert bare(has_unit=True).intent(now=0)["unit_setup_offer"] is None               # a unit is there already
    assert bare(unit_installer=False).intent(now=0)["unit_setup_offer"] is None        # no installer to run (the web demo)
    assert bare(units_watch_only=True).intent(now=0)["unit_setup_offer"] is None       # a Kobra through a Bench Box
    ace = bare()
    ace.set_units_on_usb(1)                                                            # an ACE Pro needs no setup
    assert ace.intent(now=0)["unit_setup_offer"] is None
    assert a.plan_action("unit_setup_start", {}, bare(has_unit=True)) == []


def test_never_while_printing_and_it_says_why():
    t = bare()
    t.update_status({"print_stats": {"state": "printing"}})
    assert t.intent(now=0)["unit_setup_offer"]["why"] == "Not while it's printing."
    assert a.plan_action("unit_setup_start", {}, t) == []
    t = bare()
    t.set_klippy_state("shutdown")
    assert t.unit_setup_offer()["why"] == "The printer isn't ready."


# ---- the steps ------------------------------------------------------------------------------------------------

def test_which_unit_shows_the_four_pictures_with_their_slots_and_software():
    t = started()
    v = view(t)
    assert v["step"] == "unit" and (v["n"], v["of"]) == (1, 5) and v["headline"] == "Which unit is it?"
    assert v["detail"] == "An ACE Pro needs no setup: Bench finds it by itself."
    assert [(u["name"], u["line"]) for u in v["units"]] == [
        ("Box Turtle", "4 to 8 slots · AFC"), ("Night Owl", "2 slots · AFC"),
        ("ERCF v2", "6 to 12 slots · Happy Hare"), ("Tradrack", "6 to 12 slots · Happy Hare")]
    assert [g["name"] for g in v["guides"]] == ["Happy Hare", "AFC"]
    assert labels(v) == ["Close", "Next"]
    assert a.plan_action("unit_setup_unit", {"unit": "prusa_mmu"}, t) == [(P.UNIT_SETUP, {"op": "unit", "unit": "prusa_mmu"})]
    assert not t.unit_setup_input({"op": "unit", "unit": "prusa_mmu"})   # not one Bench can set up
    assert not t.unit_setup_input({"op": "next"})                         # nothing picked yet


def test_which_board_puts_the_one_on_usb_first_as_probably_with_the_slots():
    t = picked()
    v = view(t)
    assert v["step"] == "board" and v["n"] == 2 and v["where"] == "Set up a filament unit · ERCF v2"
    assert v["headline"] == "Which board is it wired to?"
    assert v["detail"] == "Bench sees one board on USB that Klipper doesn't use yet. It looks like a BTT MMB."
    assert [(b["name"], b["line"], b["probably"]) for b in v["boards"]] == [
        ("BTT MMB", "v1.0, v1.1 or v2", True), ("Mellow EASY-BRD", "v1 or v2", False), ("Fysetc ERB", "v1 or v2", False)]
    assert v["family"] == "mmb" and v["board"] == "mmb_1_0" and v["mcu"] == MMB
    assert v["slots"] == {"choices": [6, 8, 9, 12], "value": 8}
    act(t, "unit_setup_board", board="mmb_1_1")
    act(t, "unit_setup_slots", slots="9")
    v = view(t)
    assert v["board"] == "mmb_1_1" and v["slots"]["value"] == 9
    assert labels(v) == ["Back", "Set it up"]
    assert not t.unit_setup_input({"op": "slots", "slots": 7})
    act(t, "unit_setup_back")
    assert view(t)["step"] == "unit" and view(t)["unit"] == "ercf_v2"


def test_a_box_turtles_board_has_no_slot_choice_and_no_board_on_usb_means_look_again():
    t = picked("night_owl", found=())
    v = view(t)
    assert v["slots"] is None and v["board"] == "erb_2" and v["mcu"] is None
    assert v["detail"].startswith("Bench doesn't see a board on USB or CAN that Klipper doesn't use yet.")
    assert labels(v) == ["Back", "Look again"]
    assert not t.unit_setup_input({"op": "install"})   # no port to set it up on
    assert act(t, "unit_setup_scan") == [("unit_scan", None)]
    assert view(t)["looking"] is True
    t.unit_setup_heard(scan((MMB.replace("stm32g0b1xx", "rp2040"),)))
    assert view(t)["mcu"].endswith("rp2040_4F0034000A50425539393020-if00") and view(t)["boards"][0]["probably"]


def test_two_new_boards_ask_which_one():
    other = MMB.replace("4F00", "5A00")
    t = picked(found=(MMB, other))
    v = view(t)
    assert v["detail"] == "Bench sees 2 boards that Klipper doesn't use yet. Pick the unit's below."
    assert [p["mcu"] for p in v["ports"]] == [MMB, other] and v["mcu"] is None
    act(t, "unit_setup_port", mcu=other)
    assert view(t)["mcu"] == other


def install(t, now=5.0):
    jobs = act(t, "unit_setup_install", now=now)
    assert jobs == [("unit_install", {"unit": "ercf_v2", "board": "mmb_1_0", "slots": 8, "mcu": MMB, "kind": "happy_hare"})]
    t.unit_setup_heard({"started": "unit-install", "pid": 43}, now=now)
    return t


def test_installing_shows_its_checklist_the_note_and_the_phones_next_card():
    t = install(picked())
    t.unit_setup_heard({"progress": {"id": "fetch", "step": "Fetching Happy Hare 4.1", "done": 0, "of": 4}}, now=5)
    t.unit_setup_heard({"progress": {"id": "restart", "step": "Restarting Klipper, once", "done": 2, "of": 4}}, now=60)
    v = view(t, now=61)
    assert v["step"] == "installing" and v["n"] == 3 and v["actions"] == []
    assert v["where"] == "Set up a filament unit · ERCF v2 on a BTT MMB"
    assert v["headline"] == "Setting up Happy Hare for your ERCF…"
    assert v["headline_phone"] == "Setting up Happy Hare on Workshop…"
    steps = v["progress"]["steps"]
    assert [(s["label"], s["state"]) for s in steps] == [
        ("Fetched Happy Hare 4.1", "done"), ("Wrote its settings", "done"), ("Restarting Klipper, once", "now"),
        ("Checking the unit answers", "next")]
    assert steps[1]["sub"] == "8 slots on the BTT MMB, with a copy of the old ones."
    assert 0 < v["progress"]["pct"] < 0.95 and v["progress"]["words"] == "About 30 seconds"
    assert v["note"]["title"] == "Klipper restarts once." and "Put it back" in v["note"]["foot"]
    assert v["next"]["text"].startswith("Push a little filament into each of the 8 slots. Workshop's screen")
    # the printer is busy: nothing else starts, and the top bar says so
    i = t.intent(now=61)
    assert i["state"] == "preparing" and i["phase"] == "unit_setup" and i["headline"] == "Setting up a filament unit"
    assert t.hands_why_not() == "Not while a filament unit is set up."
    assert not t.unit_setup_input({"op": "close"})


def test_a_failure_says_it_plainly_with_try_again_and_put_it_back_when_a_copy_is_kept():
    t = install(picked())
    t.unit_setup_heard({"progress": {"id": "restart", "step": "Restarting Klipper, once", "done": 2, "of": 4}}, now=30)
    t.unit_setup_heard({"failed": "Klipper didn't start with it: mcu 'mmu': Unable to connect. Your old settings are back."}, now=40)
    v = view(t)
    assert v["step"] == "failed" and v["headline"] == "Happy Hare isn't set up yet."
    assert v["why"].startswith("Klipper didn't start with it")
    assert [s["state"] for s in v["progress"]["steps"]] == ["done", "done", "failed", "next"]
    assert labels(v) == ["Close", "Try again"]          # the copy went back by itself: nothing to put back
    jobs = act(t, "unit_setup_retry", now=50)
    assert jobs[0][0] == "unit_install" and view(t)["step"] == "installing"
    # the unit didn't answer: the copy is kept, and Put it back is offered
    t.unit_kept = {"program": "Happy Hare 4.1"}
    t.unit_setup_heard({"failed": "Klipper started, but Happy Hare didn't answer. Your old settings are kept."}, now=60)
    assert labels(view(t)) == ["Close", "Put it back", "Try again"]
    assert act(t, "unit_setup_putback", now=70) == [("unit_putback", None)]
    assert view(t)["step"] == "putting_back"
    t.unit_setup_heard({"result": {"put_back": True, "klipper": "ready"}}, now=90)
    v = view(t)
    assert v["step"] == "put_back" and v["headline"] == "Your old settings are back." and labels(v) == ["Done"]
    assert t.unit_kept is None
    act(t, "unit_setup_close")
    assert t.intent(now=91)["unit_setup"] is None


def test_once_installed_the_check_takes_over_as_steps_4_and_5_with_the_old_settings_row():
    t = install(picked())
    t.unit_setup_heard({"result": {"kind": "happy_hare", "unit": "ercf_v2", "board": "mmb_1_0", "slots": 8,
                                   "program": "Happy Hare 4.1", "kept": "/x/config-before-unit-2026-10-22"}}, now=100)
    assert t.unit_kept["program"] == "Happy Hare 4.1"
    assert view(t, 101)["step"] == "installed" and not t.unit_setup_input({"op": "close"})
    # Klipper is back with the unit: the check starts, and the setup's own view steps aside
    t.has_unit = True
    t.update_status(ercf(8))
    t.work(now=102)
    i = t.intent(now=103)
    assert i["unit_setup"] is None and i["unit_check"] is not None
    uc = i["unit_check"]
    assert (uc["n"], uc["of"], uc["title"]) == (4, 5, "Set up a filament unit")
    for g in t._check.slots:
        t._check.marks[g]["state"] = "ok"
    t._check.phase, t._check.tube = "ready", 742.0
    uc = t.intent(now=104)["unit_check"]
    assert (uc["n"], uc["of"]) == (5, 5)
    rows = uc["ready"]["rows"]
    assert rows[0] == {"title": "Happy Hare 4.1", "sub": "Bench moves it to a newer version only after testing it."}
    assert rows[-1] == {"title": "Your old settings · kept", "sub": "Care › Filament unit › Put it back."}
    assert "is set up, checked and measured" in uc["detail"]
    t.unit_check_input({"op": "done"})
    t.work(now=105)
    assert t._setup is None and t.intent(now=106)["unit_check"] is None


def test_a_unit_that_never_shows_up_is_said():
    t = install(picked())
    t.unit_setup_heard({"result": {"program": "Happy Hare 4.1"}}, now=100)
    t.work(now=100 + 61)
    v = view(t, 162)
    assert v["detail"].startswith("The unit didn't show up in Klipper") and labels(v) == ["Done"]


def test_care_offers_put_it_back_while_a_copy_is_kept():
    t = bare()
    assert t.intent(now=0)["unit_putback"] is None
    t = bare(has_unit=True, unit_kept={"program": "AFC 1.2", "unit": "box_turtle"})
    offer = t.intent(now=0)["unit_putback"]
    assert offer["action"]["id"] == "unit_setup_putback" and offer["why"] is None
    assert offer["line"] == "Your settings from before AFC 1.2 was set up."
    assert act(t, "unit_setup_putback") == [("unit_putback", None)]
    v = view(t)
    assert v["step"] == "putting_back" and v["headline"] == "Putting your old settings back…"
    t.update_status({"print_stats": {"state": "printing"}})
    assert t.unit_putback_offer()["why"] == "Not while it's printing."


def test_the_installer_not_starting_is_a_failure_too():
    t = install(picked())
    t.unit_setup_heard({"failed": "Bench's installer didn't start."})
    assert view(t)["step"] == "failed" and view(t)["why"] == "Bench's installer didn't start."
