"""Skip a part mid-print (design/skip-objects/, A): the parts Klipper's [exclude_object] knows, numbered the
way a person sees the bed from the front, and a skip that refuses what it shouldn't do."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from elyir_bench_intent import ActionPlan, _part_label, _where_words, plan_action  # noqa: E402
from test_intent import T0, ready_tracker  # noqa: E402


def bushings(rows=5, cols=5):
    """Orca-style objects for a grid of bushings, 62 mm apart, as Elyir Bench's slicer names them."""
    out = []
    k = 0
    for r in range(rows):
        for c in range(cols):
            x, y = 42 + c * 62, 47 + r * 62
            out.append({"name": f"p0c{k}__buildplate_bushing_open.stl_id_{k}_copy_0", "center": [x, y],
                        "polygon": [[x - 20, y - 25], [x + 20, y - 25], [x + 20, y + 25], [x - 20, y + 25]]})
            k += 1
    # the slicer's order isn't the person's: shuffle it
    return out[::-1]


def printing(objects, excluded=(), current=None):
    t = ready_tracker()
    t.update_status({"print_stats": {"state": "printing", "filename": "bushing_x25_PETG_2h26m.gcode", "info": {"current_layer": 4}},
                     "toolhead": {"axis_minimum": [0, 0, 0], "axis_maximum": [350, 350, 340]},
                     "exclude_object": {"objects": objects, "excluded_objects": list(excluded), "current_object": current}}, now=T0)
    return t


def test_parts_are_numbered_front_left_to_back_right_with_words():
    objs = bushings()
    t = printing(objs, current=objs[-8]["name"])           # the 8th from the front-left
    p = t.intent(T0)["parts"]
    assert p["total"] == 25 and p["left"] == 25 and p["can_skip"]
    first, seventh, eighth, last = p["items"][0], p["items"][6], p["items"][7], p["items"][24]
    assert first["label"] == "Buildplate bushing open 1" and first["where"] == "front row, far left"
    assert seventh["n"] == 7 and seventh["where"] == "second row from the front, second from left"
    assert eighth["state"] == "printing" and eighth["where"] == "second row from the front, middle"
    assert last["where"] == "back row, far right" and last["center"] == [290, 295]
    assert p["bed"] == [0, 0, 350, 350]


def test_skipping_one_and_never_the_last():
    objs = bushings(1, 2)
    t = printing(objs)
    a, b = t.intent(T0)["parts"]["items"]
    assert plan_action("skip_part", {"name": a["name"]}, t) == [(ActionPlan.GCODE, f"EXCLUDE_OBJECT NAME={a['name']}")]
    t.update_status({"exclude_object": {"excluded_objects": [a["name"]]}}, now=T0 + 1)
    p = t.intent(T0 + 1)["parts"]
    assert p["left"] == 1 and p["skipped"] == ["Buildplate bushing open 1"] and not p["can_skip"]
    assert plan_action("skip_part", {"name": b["name"]}, t) == [], "the last one is Stop, not skip"
    assert plan_action("skip_part", {"name": a["name"]}, t) == [], "already skipped"
    assert plan_action("skip_part", {"name": "nope"}, t) == []
    assert plan_action("skip_part", {"name": "a b"}, t) == []


def test_one_part_or_no_labels_means_no_parts():
    assert printing(bushings(1, 1)).intent(T0)["parts"] is None
    assert printing([]).intent(T0)["parts"] is None
    assert ready_tracker().intent(T0)["parts"] is None


def test_finished_says_what_was_skipped():
    objs = bushings(1, 3)
    t = printing(objs, excluded=[objs[0]["name"]])
    t.update_status({"print_stats": {"state": "complete"}, "heater_bed": {"temperature": 50.0, "target": 0.0}}, now=T0 + 100)
    p = t.intent(T0 + 100)["parts"]
    assert p["left"] == 2 and p["skipped"] == ["Buildplate bushing open 3"] and not p["can_skip"]


def test_names_and_words():
    assert _part_label("p0c7__buildplate_bushing_open.stl_id_7_copy_0") == "Buildplate bushing open"
    assert _part_label("vent.stl_id_0_copy_0") == "Vent"
    assert _part_label("[a]_cutting_arm_g2e.stl_id_2_copy_0") == "Cutting arm g2e"
    assert _where_words(0, 1, 0, 2) == "far left" and _where_words(0, 1, 0, 1) == "on its own"
    assert _where_words(2, 5, 3, 6) == "middle row, third from right"
