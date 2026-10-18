"""The picture in the ring (design/now-illustrated/, direction A): what it's drawn from. Every
number is the printer's own. The stage while getting ready, the head over the bed only while
that's what the picture shows, the levelling pass, the mesh cells covered, how far up it's built."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_intent import ready_tracker, T0  # noqa: E402

BED = {"toolhead": {"axis_minimum": [0, 0, -5, 0], "axis_maximum": [350, 350, 340, 0]}}


def getting_ready(stage, **extra):
    t = ready_tracker()
    t.update_status(BED, now=T0)
    t.update_status({"print_stats": {"state": "paused", "filename": "x.gcode", "info": {}},
                     "pause_resume": {"is_paused": True},
                     "gcode_macro _PRINT_START": {"stage": stage}, **extra}, now=T0)
    return t


def at(t, x, y, z=5.0, now=T0):
    t.update_status({"motion_report": {"live_position": [x, y, z, 0]}}, now=now)


def test_the_stage_is_folded_to_the_drawings_there_are():
    for stage, art in [("home_first", "home"), ("warming", "warming"), ("soaking", "soaking"), ("home", "home"),
                       ("qgl", "level"), ("mesh", "mesh"), ("home_again", "home"), ("heating", "heating"),
                       ("prime", "prime"), ("resume", "prime")]:
        t = getting_ready(stage)
        assert t.intent(T0)["art"]["stage"] == art, stage


def test_the_step_gets_a_second_line_when_there_is_more_to_say():
    i = getting_ready("mesh").intent(T0)
    now = [s for s in i["steps"] if s["status"] == "now"]
    assert now == [{"id": "leveling", "label": "Leveling", "status": "now", "detail": "Mapping the bed"}]
    i = getting_ready("prime").intent(T0)
    assert [s.get("detail") for s in i["steps"] if s["status"] == "now"] == ["Priming the nozzle"]
    i = getting_ready("warming").intent(T0)
    assert all("detail" not in s for s in i["steps"])


def test_the_head_is_there_only_while_the_picture_shows_it():
    t = getting_ready("home")
    at(t, 175, 350, 10.4)
    assert t.intent(T0)["art"]["head"] == [0.5, 1.0, 10]
    t.update_status({"gcode_macro _PRINT_START": {"stage": "heating"}}, now=T0 + 1)
    assert t.intent(T0 + 1)["art"]["head"] is None


def test_the_head_is_rounded_so_small_moves_dont_push_the_intent():
    t = getting_ready("home")
    at(t, 175.0, 175.0)
    first = t.intent(T0)["art"]
    at(t, 176.5, 174.0)
    assert t.intent(T0)["art"] == first


def test_levelling_shows_the_printers_own_range():
    t = getting_ready("qgl")
    assert t.intent(T0)["art"]["level"] is None
    t.on_gcode_response("Retries: 0/5 Probed points range: 0.412500 tolerance: 0.007500", now=T0)
    assert t.intent(T0)["art"]["level"] == {"range": 0.4125, "tolerance": 0.0075}
    t.on_gcode_response("Retries: 2/5 Probed points range: 0.004000 tolerance: 0.007500", now=T0)
    assert t.intent(T0)["art"]["level"]["range"] == 0.004


def test_mesh_lights_the_cells_the_head_has_crossed():
    t = getting_ready("mesh")
    assert t.intent(T0)["art"]["mesh"] == {"n": 5, "seen": 0}
    at(t, 10, 10)                 # front-left cell
    at(t, 340, 10)                # a fast sweep along the front row, seen twice
    seen = t.intent(T0)["art"]["mesh"]["seen"]
    assert seen == 0b11111        # every cell of the first row, not only the two ends
    at(t, 340, 80)
    assert t.intent(T0)["art"]["mesh"]["seen"] & (1 << 9)   # row 2, last column


def test_a_new_mesh_starts_over():
    t = getting_ready("mesh")
    at(t, 340, 10)
    at(t, 10, 10)
    t.update_status({"gcode_macro _PRINT_START": {"stage": "home_again"}}, now=T0 + 1)
    t.update_status({"gcode_macro _PRINT_START": {"stage": "mesh"}}, now=T0 + 2)
    assert t.intent(T0 + 2)["art"]["mesh"]["seen"] == 1   # only the cell under the head


def test_built_follows_layers_not_file_position():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 35, "total_layer": 140}},
                     "virtual_sdcard": {"progress": 0.6}}, now=T0)
    art = t.intent(T0)["art"]
    assert art["built"] == 0.25 and art["stage"] is None and art["head"] is None


def test_built_falls_back_to_height_when_the_slicer_gives_no_layers():
    t = ready_tracker()
    t.update_status(BED, now=T0)
    t.set_metadata("x.gcode", {"object_height": 28.0})
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {}},
                     "motion_report": {"live_position": [100, 100, 7.0, 0]}}, now=T0)
    t.on_gcode_response("Printing, good luck!", now=T0)
    assert t.intent(T0)["art"]["built"] == 0.25


def test_a_paused_print_keeps_its_height():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {"current_layer": 70, "total_layer": 140}},
                     "gcode_macro _PRINT_START": {"stage": ""}}, now=T0)
    t.update_status({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}}, now=T0 + 1)
    i = t.intent(T0 + 1)
    assert i["state"] == "needs_you" and i["art"]["built"] == 0.5


def test_older_print_starts_name_the_drawing_in_their_messages():
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "x.gcode", "info": {}},
                     "display_status": {"message": "Calibrating mesh ........"}}, now=T0)
    assert t.intent(T0)["art"]["stage"] == "mesh"


def test_no_job_no_picture():
    assert ready_tracker().intent(T0)["art"] is None
