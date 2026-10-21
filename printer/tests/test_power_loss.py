# Pins power cuts (design/power-loss/, A, picked 21 October 2026): on a UPS a print holds after 30 s on battery
# (motors on, idle timeout raised, nozzle 150°, bed a little cooler), and carries on by itself once the power has
# been back 30 s and it's warm again; Pause keeps it paused. Without a UPS (or after the battery), the checkpoint
# kept on every layer becomes a lost print on Ready, told to the phone.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from elyir_bench_intent import (ActionPlan, IntentTracker, Notifier, OUTAGE_IDLE_TIMEOUT, plan_action)  # noqa: E402
from test_intent import T0, ready_tracker  # noqa: E402

FILE = "phone_stand_0.2mm_PLA_MK4_1h40m.gcode"
MD = {"layer_height": 0.2, "first_layer_height": 0.2, "object_height": 28, "filament_type": "PLA"}


def printing(t=None, layer=61, now=T0):
    t = t or ready_tracker()
    t.printer_name = "Workshop"
    t.set_metadata(FILE, MD)
    t.update_status({"print_stats": {"state": "printing", "filename": FILE, "info": {"current_layer": layer, "total_layer": 140}},
                     "virtual_sdcard": {"progress": 0.44},
                     "extruder": {"temperature": 215.0, "target": 215.0}, "heater_bed": {"temperature": 60.0, "target": 60.0}}, now=now)
    return t


def gcode(cmds):
    return [s for k, s in cmds if k == "gcode"]


def paused(t, now):
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True},
                     "extruder": {"target": 150.0}, "heater_bed": {"target": 45.0}}, now=now)


def test_a_flicker_does_nothing():
    t = printing()
    t.set_ups({"on_battery": True, "charge": 100})
    assert t.work(T0 + 10) == []
    t.set_ups({"on_battery": False, "charge": 100})
    assert t.work(T0 + 12) == []
    t.set_ups({"on_battery": True, "charge": 100})
    assert t.work(T0 + 40) == []   # a new outage counts from its own start
    assert t.intent(T0 + 40)["state"] == "printing"


def test_thirty_seconds_on_battery_holds_the_print_with_the_motors_on():
    t = printing()
    t.set_ups({"on_battery": True, "charge": 70, "runtime_s": 3000})
    t.work(T0)
    assert gcode(t.work(T0 + 30)) == [f"SET_IDLE_TIMEOUT TIMEOUT={OUTAGE_IDLE_TIMEOUT}", "PAUSE", "M104 S150", "M140 S45"]
    assert t.work(T0 + 31) == []   # once
    paused(t, T0 + 32)
    i = t.intent(T0 + 60)
    assert (i["state"], i["phase"], i["headline"]) == ("needs_you", "power_hold", "The power is out")
    assert "motors stay on" in i["detail"]
    assert [a["id"] for a in i["actions"]] == ["cancel"] and i["actions"][0]["hold"] is True
    assert i["outage"]["battery"] == 70 and i["outage"]["runtime_min"] == 50 and i["outage"]["bed"] == 45
    assert i["expires"] is None


def test_power_back_waits_thirty_seconds_then_heats_then_carries_on():
    t = printing()
    t.set_ups({"on_battery": True})
    t.work(T0)
    t.work(T0 + 30)
    paused(t, T0 + 31)
    t.set_ups({"on_battery": False})
    assert t.work(T0 + 360) == []
    i = t.intent(T0 + 370)
    assert (i["state"], i["phase"], i["headline"]) == ("preparing", "power_back", "The power is back")
    assert i["detail"] == "It held 6 minutes, right where it stopped."
    assert [s["label"] for s in i["steps"]] == ["Power steady for 30 seconds", "Heating the nozzle back to 215°", "Carrying on from layer 61"]
    assert i["outage"]["carry_in"] == 20
    assert [a["id"] for a in i["actions"]] == ["outage_keep", "cancel"]
    assert gcode(t.work(T0 + 390)) == ["M140 S60", "M104 S215"]
    t.update_status({"extruder": {"temperature": 214.0, "target": 215.0}, "heater_bed": {"temperature": 58.0, "target": 60.0}}, now=T0 + 500)
    assert gcode(t.work(T0 + 500)) == ["RESUME"]
    assert t.work(T0 + 501) == []
    i = t.intent(T0 + 501)   # still the power coming back, not a plain pause, until Klipper says printing
    assert i["phase"] == "power_back" and [s["status"] for s in i["steps"]] == ["done", "done", "now"]
    t.update_status({"print_stats": {"state": "printing"}, "pause_resume": {"is_paused": False}}, now=T0 + 503)
    assert gcode(t.work(T0 + 503)) == ["SET_IDLE_TIMEOUT TIMEOUT=600"]
    assert t.intent(T0 + 504)["state"] == "printing"


def test_pause_keeps_it_paused_when_the_power_is_back():
    t = printing()
    t.set_ups({"on_battery": True})
    t.work(T0)
    t.work(T0 + 30)
    paused(t, T0 + 31)
    t.set_ups({"on_battery": False})
    t.work(T0 + 100)
    for kind, payload in plan_action("outage_keep", {}, t):
        assert kind == ActionPlan.OUTAGE
        t.outage_input(payload)
    assert gcode(t.work(T0 + 140)) == ["SET_IDLE_TIMEOUT TIMEOUT=600"]
    assert t.intent(T0 + 141)["phase"] == "paused"


def test_a_print_paused_by_a_person_only_keeps_its_motors_on():
    t = printing()
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=T0)
    t.set_ups({"on_battery": True})
    t.work(T0)
    assert gcode(t.work(T0 + 30)) == [f"SET_IDLE_TIMEOUT TIMEOUT={OUTAGE_IDLE_TIMEOUT}"]
    assert t.intent(T0 + 31)["phase"] == "power_hold"
    t.set_ups({"on_battery": False})
    assert gcode(t.work(T0 + 60)) == ["SET_IDLE_TIMEOUT TIMEOUT=600"]
    assert t.intent(T0 + 61)["phase"] == "paused"


def test_every_layer_is_a_checkpoint_and_an_end_clears_it():
    t = printing(layer=60)
    assert t.checkpoint["layer"] == 60 and t.checkpoint["z"] == 12.0 and t.checkpoint_dirty
    t.checkpoint_dirty = False
    printing(t, layer=60, now=T0 + 1)
    assert not t.checkpoint_dirty
    printing(t, layer=61, now=T0 + 30)
    assert t.checkpoint["z"] == 12.2 and t.checkpoint["nozzle"] == 215.0 and t.checkpoint["material"] == "PLA"
    t.update_status({"print_stats": {"state": "complete"}}, now=T0 + 60)
    assert t.checkpoint is None and t.checkpoint_record() is None


def restarted(record, state="standby", filename=""):
    t = IntentTracker("Workshop", now=T0 + 3600)
    t.restore_checkpoint(record, now=T0 + 3600)
    t.set_klippy_state("ready", now=T0 + 3600)
    t.update_status({"print_stats": {"state": state, "filename": filename, "info": {}}, "pause_resume": {"is_paused": False},
                     "heater_bed": {"temperature": 22.0, "target": 0.0}, "extruder": {"temperature": 22.0, "target": 0.0}}, now=T0 + 3600)
    return t


def test_a_checkpoint_left_after_a_restart_is_a_lost_print():
    cp = printing().checkpoint
    t = restarted(cp)
    i = t.intent(T0 + 3601)
    assert (i["state"], i["phase"]) == ("ready", "lost_print")
    assert i["detail"].startswith("The printer lost power at ")
    lost = i["lost"]
    assert (lost["name"], lost["pct"], lost["z"], lost["layer"], lost["layers"]) == ("Phone stand", 44, 12.2, 61, 140)
    assert t.checkpoint_dirty and t.checkpoint_record()["back"] == T0 + 3600   # kept, with when it came back
    again = restarted(t.checkpoint_record())
    assert again.lost["back"] == T0 + 3600


def test_moonraker_restarting_alone_is_not_a_lost_print():
    cp = printing().checkpoint
    t = restarted(cp, state="printing", filename=FILE)
    assert t.lost is None and t.checkpoint["file"] == FILE


def test_let_it_be_or_a_new_print_clears_the_lost_print():
    t = restarted(printing().checkpoint)
    for kind, payload in plan_action("lost_dismiss", {}, t):
        assert kind == ActionPlan.LOST
        t.lost_input(payload)
    assert t.lost is None and t.checkpoint_record() is None
    t = restarted(printing().checkpoint)
    t.update_status({"print_stats": {"state": "printing", "filename": FILE, "info": {}}}, now=T0 + 4000)
    assert t.lost is None


def test_a_held_print_that_ran_out_of_battery_says_when_the_power_went():
    t = printing()
    t.set_ups({"on_battery": True})
    t.work(T0)
    t.work(T0 + 30)
    assert t.checkpoint["outage_since"] == T0
    lost = restarted(t.checkpoint_record()).intent(T0 + 3601)["lost"]
    assert lost["held"] is True


def test_the_phone_hears_of_a_lost_print_even_on_the_first_look():
    t = restarted(printing().checkpoint)
    n = Notifier("b1")
    ev = n.observe(t.intent(T0 + 3601), T0 + 3601)
    assert [e["kind"] for e in ev] == ["lost"]
    assert ev[0]["title"] == "Workshop lost power mid-print"
    assert ev[0]["body"] == "Phone stand stopped at 44%. Print the rest, or start over."
    assert n.observe(t.intent(T0 + 3602), T0 + 3602) == []


def test_the_phone_hears_the_power_go_and_come_back():
    t = printing()
    n = Notifier("b1")
    n.observe(t.intent(T0), T0)
    t.set_ups({"on_battery": True, "runtime_s": 3000})
    t.work(T0)
    t.work(T0 + 30)
    paused(t, T0 + 31)
    ev = n.observe(t.intent(T0 + 31), T0 + 31)
    assert [(e["kind"], e["title"], e["body"]) for e in ev] == [
        ("needs_you", "Workshop: the power is out", "Holding Phone stand at 44%. Battery: about 50 min.")]
    t.set_ups({"on_battery": False})
    t.work(T0 + 300)
    ev = n.observe(t.intent(T0 + 301), T0 + 301)
    assert [(e["kind"], e["title"]) for e in ev] == [("power_back", "Workshop: the power is back")]
