"""First layer: squish more, squish less (design/first-layer/, direction B). On layers 1 to 3 Now offers
Further / Closer (0.025 mm a press, SET_GCODE_OFFSET Z_ADJUST ... MOVE=1) with the total in words; at the
end "Keep this first layer?" saves it in [save_variables] for the shared PRINT_START to
apply, recording whether Z was found by the Eddy's scan or by tap. Care can go back; when the way of finding
Z changes, Now asks once whether to clear the old value."""

import ast
import os
import shlex
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import elyir_bench_intent as a  # noqa: E402

FILE = "bracket.gcode"


def tracker(saved=None, tap=False, save_variables=True, offset=0.0):
    t = a.IntentTracker("Workshop", now=0.0)
    t.set_klippy_state("ready", "Printer is ready", now=0.0)
    t.has_unit = True
    status = {"print_stats": {"state": "standby", "filename": "", "info": {"current_layer": None, "total_layer": None}},
              "pause_resume": {"is_paused": False},
              "heater_bed": {"temperature": 60, "target": 60}, "extruder": {"temperature": 240, "target": 240},
              "gcode_macro _PRINT_START_SETTINGS": {"chamber_max": 30.0, "tap": tap},
              "gcode_macro _PRINT_START": {"stage": ""},
              "gcode_move": {"homing_origin": [0.0, 0.0, offset, 0.0]},
              "motion_report": {"live_position": [100.0, 100.0, 30.0, 0.0]},
              "ace": {"gate_color": ["F4F4F2"], "gate_material": ["PETG"], "selected_gate": 0, "slots": [{"status": "ready"}]}}
    if save_variables:
        status["save_variables"] = {"variables": dict({"ace_current_index": 0}, **(saved or {}))}
    t.update_status(status, now=0.0)
    return t


def klipper(t, scripts, now=5.0):
    """Run what the engine sent the way Klipper would, and report the result back as status."""
    for script in scripts:
        for line in script.splitlines():
            cmd, _, rest = line.partition(" ")
            params = {k.upper(): v for k, v in (arg.split("=", 1) for arg in shlex.split(rest))}
            if cmd == "SET_GCODE_OFFSET":
                z = t.status["gcode_move"]["homing_origin"][2]
                z = z + float(params["Z_ADJUST"]) if "Z_ADJUST" in params else float(params["Z"])
                t.update_status({"gcode_move": {"homing_origin": [0.0, 0.0, round(z, 4), 0.0]}}, now=now)
            elif cmd == "SAVE_VARIABLE":
                v = dict(t.status["save_variables"]["variables"])
                v[params["VARIABLE"]] = ast.literal_eval(params["VALUE"])
                t.update_status({"save_variables": {"variables": v}}, now=now)


def start_printing(t, layer=1, now=1.0, kept_offset=None):
    """PRINT_START has run (and put any kept value into the offset); the first layer is going down."""
    if kept_offset is not None:
        t.update_status({"gcode_move": {"homing_origin": [0.0, 0.0, kept_offset, 0.0]}}, now=now)
    t.update_status({"print_stats": {"state": "printing", "filename": FILE,
                                     "info": {"current_layer": layer, "total_layer": 15}},
                     "motion_report": {"live_position": [120.0, 140.0, 0.2, 0.0]}}, now=now)


def act(t, action, now=2.0):
    plan = a.plan_action(action, {}, t)
    assert plan, f"{action} was refused"
    for kind, payload in plan:
        assert kind == a.ActionPlan.FIRST_LAYER
        assert t.first_layer_input(payload, now=now)
    sent = [s for _, s in t.work(now=now)]
    klipper(t, sent, now=now)
    return sent


def refused(t, action):
    return a.plan_action(action, {}, t) == []


def finish(t, now=100.0, state="complete"):
    t.update_status({"print_stats": {"state": state}}, now=now)
    sent = [s for _, s in t.work(now=now)]
    klipper(t, sent, now=now)
    return sent


def fl(t, now=3.0):
    return t.intent(now=now)["first_layer"]


# ---- when it's offered --------------------------------------------------------------

def test_offered_on_layers_one_to_three_only():
    t = tracker()
    assert fl(t)["adjust"] is None
    start_printing(t, layer=1)
    adj = fl(t)["adjust"]
    assert [x["id"] for x in adj["actions"]] == ["squish_less", "squish_more"]
    assert [x["label"] for x in adj["actions"]] == ["Further", "Closer"]
    assert adj["words"] == "As the printer finds it" and adj["mm"] == "0.000 mm"
    t.update_status({"print_stats": {"info": {"current_layer": 3, "total_layer": 15}}}, now=4.0)
    assert fl(t, 4.0)["adjust"] is not None
    t.update_status({"print_stats": {"info": {"current_layer": 4, "total_layer": 15}}}, now=5.0)
    assert fl(t, 5.0)["adjust"] is None
    assert refused(t, "squish_more")


def test_not_while_getting_ready_or_paused():
    t = tracker()
    t.update_status({"print_stats": {"state": "paused", "filename": FILE},
                     "pause_resume": {"is_paused": True}, "gcode_macro _PRINT_START": {"stage": "mesh"}}, now=1.0)
    assert fl(t)["adjust"] is None and refused(t, "squish_less")
    t.update_status({"gcode_macro _PRINT_START": {"stage": ""}, "pause_resume": {"is_paused": False}}, now=2.0)
    start_printing(t)
    assert fl(t)["adjust"] is not None
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=4.0)
    assert t.intent(now=4.0)["first_layer"]["adjust"] is None and refused(t, "squish_less")


def test_without_layer_numbers_the_first_layers_are_the_low_ones():
    t = tracker()
    start_printing(t, layer=None)
    assert fl(t)["adjust"] is None   # still getting ready, as far as anyone can tell
    t.on_gcode_response("// Printing, good luck!", now=1.5)   # the shared PRINT_START's last words
    t.update_status({"virtual_sdcard": {"progress": 0.01}}, now=2.0)
    assert fl(t)["adjust"] is not None
    t.update_status({"motion_report": {"live_position": [120.0, 140.0, 1.4, 0.0]}}, now=4.0)
    assert fl(t, 4.0)["adjust"] is None


# ---- pressing Further / Closer --------------------------------------------------------

def test_further_and_closer_nudge_the_offset_live():
    t = tracker()
    start_printing(t)
    assert act(t, "squish_less") == ["SET_GCODE_OFFSET Z_ADJUST=0.025 MOVE=1"]
    assert act(t, "squish_more") == ["SET_GCODE_OFFSET Z_ADJUST=-0.025 MOVE=1"]
    act(t, "squish_more")
    adj = fl(t)["adjust"]
    assert adj["total"] == -0.025 and adj["words"] == "A touch closer" and adj["mm"] == "−0.025 mm"
    assert t.status["gcode_move"]["homing_origin"][2] == -0.025


def test_the_total_in_words_first():
    t = tracker()
    start_printing(t)
    for _ in range(12):
        act(t, "squish_less")
    adj = fl(t)["adjust"]
    assert (adj["words"], adj["mm"]) == ("A little further", "+0.300 mm")
    assert a.squish_words(0.05) == "A touch further" and a.squish_words(-0.35) == "Quite a bit closer"
    assert a.squish_words(0.5) == "A lot further" and a.squish_words(0.0) == "As the printer finds it"


def test_no_more_than_half_a_millimetre_either_way():
    t = tracker()
    start_printing(t)
    for _ in range(20):
        act(t, "squish_less")
    adj = fl(t)["adjust"]
    assert adj["total"] == 0.5
    assert [x["id"] for x in adj["actions"]] == ["squish_more"]
    assert refused(t, "squish_less")


# ---- at the end ------------------------------------------------------------------------

def test_the_end_takes_the_nudges_back_out_and_asks_to_keep():
    t = tracker()
    start_printing(t)
    for _ in range(12):
        act(t, "squish_less")
    assert finish(t) == ["SET_GCODE_OFFSET Z=0.000"]   # they were for this print
    i = t.intent(now=101.0)
    assert i["state"] == "finished"
    keep = i["first_layer"]["keep"]
    assert keep["headline"] == "Keep this first layer?"
    assert keep["detail"] == "You moved it a little further from the bed (+0.300 mm)."
    assert [x["id"] for x in keep["actions"]] == ["keep_first_layer", "keep_for_sheet", "just_this_once"]
    assert [x["label"] for x in keep["actions"]] == ["For every print", "Only on this sheet", "Just this once"]


def test_keep_saves_it_for_print_start_measured_against_scan():
    t = tracker()
    start_printing(t)
    for _ in range(12):
        act(t, "squish_less")
    finish(t)
    sent = act(t, "keep_first_layer", now=1000.0)
    assert sent == ["\n".join(["SAVE_VARIABLE VARIABLE=first_layer_z VALUE=0.300",
                               "SAVE_VARIABLE VARIABLE=first_layer_against VALUE='\"scan\"'",
                               "SAVE_VARIABLE VARIABLE=first_layer_history VALUE='[0.000]'",
                               "SAVE_VARIABLE VARIABLE=first_layer_at VALUE=1000"])]
    v = t.status["save_variables"]["variables"]
    assert (v["first_layer_z"], v["first_layer_against"], v["first_layer_history"]) == (0.3, "scan", [0.0])
    assert v["ace_current_index"] == 0   # the filament unit's variables are left alone
    f = fl(t)
    assert f["keep"] is None
    assert (f["kept"]["words"], f["kept"]["mm"], f["kept"]["against"], f["kept"]["used"]) == ("A little further", "+0.300 mm", "scan", True)
    assert f["kept"]["back"]["words"] == "As the printer finds it"
    assert not any("Z_OFFSET_APPLY" in s for s in sent)   # never into the probe


def test_just_this_once_saves_nothing():
    t = tracker()
    start_printing(t)
    act(t, "squish_more")
    finish(t)
    assert act(t, "just_this_once") == []
    assert fl(t)["keep"] is None
    assert "first_layer_z" not in t.status["save_variables"]["variables"]


def test_nothing_to_keep_when_nothing_moved():
    t = tracker()
    start_printing(t)
    assert finish(t) == []
    assert fl(t)["keep"] is None and refused(t, "keep_first_layer")


def test_a_stopped_print_can_keep_it_too():
    t = tracker()
    start_printing(t)
    act(t, "squish_less")
    finish(t, state="cancelled")
    i = t.intent(now=101.0)
    assert i["headline"] == "Print stopped." and i["first_layer"]["keep"] is not None
    assert t.intent(now=101.0 + a.CANCELLED_NOTE_SECONDS)["first_layer"]["keep"] is None


def test_a_new_print_drops_an_unanswered_question():
    t = tracker()
    start_printing(t)
    act(t, "squish_less")
    finish(t)
    t.update_status({"print_stats": {"state": "printing", "filename": "other.gcode",
                                     "info": {"current_layer": 1, "total_layer": 15}}}, now=200.0)
    f = fl(t, 200.0)
    assert f["keep"] is None and f["adjust"]["total"] == 0.0


def test_a_restart_in_between_leaves_the_offset_alone():
    t = tracker()
    start_printing(t)
    act(t, "squish_less")
    # Stop now: the restart clears Klipper's offset before the print is seen to end
    t.update_status({"gcode_move": {"homing_origin": [0.0, 0.0, 0.0, 0.0]}}, now=50.0)
    assert finish(t, state="standby") == []


def test_without_save_variables_it_still_nudges_but_cannot_keep():
    t = tracker(save_variables=False)
    start_printing(t)
    act(t, "squish_less")
    finish(t)
    f = fl(t)
    assert f["can_keep"] is False and f["keep"] is None and f["kept"] is None
    assert refused(t, "keep_first_layer")


# ---- with a value kept before -----------------------------------------------------------

def test_a_kept_value_is_where_the_next_print_starts_from():
    t = tracker(saved={"first_layer_z": 0.3, "first_layer_against": "scan", "first_layer_history": [0.0]})
    start_printing(t, kept_offset=0.3)
    adj = fl(t)["adjust"]
    assert (adj["total"], adj["words"]) == (0.3, "A little further")
    act(t, "squish_more")
    assert finish(t) == ["SET_GCODE_OFFSET Z=0.300"]   # back to what PRINT_START applied
    keep = fl(t)["keep"]
    assert keep["detail"] == "You moved it a touch closer to the bed (−0.025 mm)."
    act(t, "keep_first_layer", now=1000.0)
    v = t.status["save_variables"]["variables"]
    assert v["first_layer_z"] == 0.275 and v["first_layer_history"] == [0.0, 0.3]


def test_back_to_how_it_was():
    t = tracker(saved={"first_layer_z": 0.275, "first_layer_against": "scan", "first_layer_history": [0.0, 0.3]})
    kept = fl(t)["kept"]
    assert [x["label"] for x in kept["actions"]] == ["Back to how it was"]
    assert kept["back"]["mm"] == "+0.300 mm"
    act(t, "first_layer_back")
    v = t.status["save_variables"]["variables"]
    assert v["first_layer_z"] == 0.3 and v["first_layer_history"] == [0.0]
    act(t, "first_layer_back")
    kept = fl(t)["kept"]
    assert kept["z"] == 0.0 and kept["actions"] == [] and kept["back"] is None
    assert refused(t, "first_layer_back")


# ---- when tap arrives ---------------------------------------------------------------------

def test_tap_arrives_asks_once_to_clear_and_print_start_skips_the_old_value():
    t = tracker(saved={"first_layer_z": 0.3, "first_layer_against": "scan", "first_layer_history": [0.0]}, tap=True)
    assert t.z_by() == "tap" and t._applied_first_layer() == 0.0
    ask = fl(t)["ask"]
    assert ask["headline"] == "Workshop now finds its own first layer. Clear your old adjustment?"
    assert [x["label"] for x in ask["actions"]] == ["Clear it", "Keep it"]
    assert fl(t)["kept"]["used"] is False
    act(t, "first_layer_clear")
    v = t.status["save_variables"]["variables"]
    assert (v["first_layer_z"], v["first_layer_against"], v["first_layer_history"]) == (0.0, "tap", [0.0, 0.3])
    assert fl(t)["ask"] is None and refused(t, "first_layer_clear")


def test_tap_arrives_and_keeping_the_old_value_moves_it_onto_tap():
    t = tracker(saved={"first_layer_z": 0.05, "first_layer_against": "scan"}, tap=True)
    act(t, "first_layer_keep_old")
    v = t.status["save_variables"]["variables"]
    assert (v["first_layer_z"], v["first_layer_against"]) == (0.05, "tap")
    assert fl(t)["ask"] is None and t._applied_first_layer() == 0.05


def test_the_question_waits_until_the_printer_is_free():
    t = tracker(saved={"first_layer_z": 0.3, "first_layer_against": "scan"}, tap=True)
    start_printing(t)
    assert fl(t)["ask"] is None
    assert fl(t)["adjust"]["total"] == 0.0   # PRINT_START didn't apply a scan value on top of tap


def test_keeping_under_tap_records_tap():
    t = tracker(saved={"first_layer_z": 0.0, "first_layer_against": "tap"}, tap=True)
    start_printing(t)
    act(t, "squish_more")
    finish(t)
    act(t, "keep_first_layer", now=1000.0)
    v = t.status["save_variables"]["variables"]
    assert (v["first_layer_z"], v["first_layer_against"]) == (-0.025, "tap")


def test_the_tap_stage_is_leveling():
    assert a.PRINT_START_STAGES["tap"] == "leveling"
    t = tracker()
    t.update_status({"print_stats": {"state": "paused", "filename": FILE}, "pause_resume": {"is_paused": True},
                     "gcode_macro _PRINT_START": {"stage": "tap"}}, now=1.0)
    i = t.intent(now=1.0)
    assert i["state"] == "preparing" and i["phase"] == "leveling"


# ---- sheets (design/first-layer-sheets/, C) ---------------------------------------------------

def act_with(t, action, now=2.0, **args):
    plan = a.plan_action(action, args, t)
    assert plan, f"{action} {args} was refused"
    for kind, payload in plan:
        assert t.first_layer_input(payload, now=now)
    sent = [s for _, s in t.work(now=now)]
    klipper(t, sent, now=now)
    return sent


def nudged_and_finished(t, by="squish_more", times=2, kept_offset=None):
    start_printing(t, kept_offset=kept_offset)
    for _ in range(times):
        act(t, by)
    finish(t)


def test_only_on_this_sheet_keeps_a_value_for_that_sheet_and_puts_it_on():
    t = tracker(saved={"first_layer_z": 0.0, "first_layer_against": "scan", "first_layer_history": []})
    nudged_and_finished(t)
    keep = fl(t)["keep"]
    assert keep["sheet"] is None and keep["sheets"][:3] == ["Smooth PEI", "Textured PEI", "Satin PEI"]
    act_with(t, "keep_for_sheet", now=1000.0, name="Textured PEI")
    v = t.status["save_variables"]["variables"]
    assert v["first_layer_sheets"] == {"Textured PEI": {"z": -0.05, "at": 1000}} and v["first_layer_sheet"] == "Textured PEI"
    assert v["first_layer_z"] == 0.0   # every other print stays as it was
    f = fl(t)
    assert f["keep"] is None
    assert [(x["name"], x["mm"], x["on"]) for x in f["kept"]["sheets"]] == [("Textured PEI", "−0.050 mm", True)]
    assert [x["label"] for x in f["kept"]["sheets"][0]["actions"]] == ["Forget it"]
    assert f["sheet"]["on"] == "Textured PEI" and [o["name"] for o in f["sheet"]["options"]] == ["Textured PEI", ""]


def test_a_print_on_a_sheet_starts_from_its_value_and_keeps_into_it():
    saved = {"first_layer_z": 0.1, "first_layer_against": "scan", "first_layer_history": [0.0],
             "first_layer_sheets": {"Textured PEI": {"z": -0.05, "at": 1000}}, "first_layer_sheet": "Textured PEI"}
    t = tracker(saved=saved)
    nudged_and_finished(t, times=1, kept_offset=-0.05)
    keep = fl(t)["keep"]
    assert keep["headline"] == "Keep it for the Textured PEI sheet?" and keep["sheet"] == "Textured PEI"
    assert [x["label"] for x in keep["actions"]] == ["Keep it", "Just this once"]
    act(t, "keep_first_layer", now=2000.0)
    v = t.status["save_variables"]["variables"]
    assert v["first_layer_sheets"]["Textured PEI"]["z"] == -0.075 and v["first_layer_z"] == 0.1


def test_print_asks_which_sheet_only_when_the_values_differ():
    same = {"first_layer_z": 0.0, "first_layer_against": "scan", "first_layer_sheets": {"Smooth PEI": {"z": 0.0, "at": 1}}}
    assert fl(tracker(saved=same))["sheet"] is None
    differ = dict(same, first_layer_sheets={"Smooth PEI": {"z": 0.0, "at": 1}, "Textured PEI": {"z": -0.05, "at": 2}},
                  first_layer_sheet="Textured PEI")
    t = tracker(saved=differ)
    assert [o["name"] for o in fl(t)["sheet"]["options"]] == ["Smooth PEI", "Textured PEI", ""]
    act_with(t, "first_layer_sheet", name="Smooth PEI")
    assert t.status["save_variables"]["variables"]["first_layer_sheet"] == "Smooth PEI"
    act_with(t, "first_layer_sheet", name="")
    assert fl(t)["sheet"]["on"] == ""
    assert refused_with(t, "first_layer_sheet", name="Glass")


def test_forgetting_the_sheet_on_the_bed_goes_back_to_every_print():
    t = tracker(saved={"first_layer_z": 0.1, "first_layer_against": "scan",
                       "first_layer_sheets": {"Textured PEI": {"z": -0.05, "at": 1}}, "first_layer_sheet": "Textured PEI"})
    act_with(t, "first_layer_forget", name="Textured PEI")
    v = t.status["save_variables"]["variables"]
    assert v["first_layer_sheets"] == {} and v["first_layer_sheet"] == ""
    assert fl(t)["sheet"] is None


def test_a_sheet_name_is_plain_and_short():
    t = tracker(saved={"first_layer_z": 0.0, "first_layer_against": "scan"})
    nudged_and_finished(t)
    for bad in ("", "x" * 30, "Bad'quote", '"', "a;b"):
        assert refused_with(t, "keep_for_sheet", name=bad)
    act_with(t, "keep_for_sheet", name="Satin 0.4")
    assert t.status["save_variables"]["variables"]["first_layer_sheet"] == "Satin 0.4"


def refused_with(t, action, **args):
    return a.plan_action(action, args, t) == []
