"""Where supports go (design/supports-where/, A): what the request carries, the marks written into the arranged 3MF
for Orca, a 3MF's own marks kept, and real slices."""
import sys
import os
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench_slice as sl  # noqa: E402
from test_multicolor import _done, _upload, real  # noqa: E402,F401
from test_paint_height import SIGN, _arranged  # noqa: E402
from test_slice import REAL_ORCA, _boxes_stl  # noqa: E402

# a shelf bracket: a base on the plate, a back wall, a shelf that sticks out 15 mm past the base
BRACKET = [((0, 0, 0), (40, 30, 3)), ((0, 25, 3), (40, 30, 22)), ((0, -15, 22), (40, 30, 25))]
SHELF_UNDERSIDE = (24, 25)               # _boxes_stl: each box's bottom is its first two triangles


def marks_on(tris_count, triangles, mark):
    states = [0] * tris_count
    for t in triangles:
        states[t] = mark
    return sl.runs_of(states)


# ── what can be asked ────────────────────────────────────────────────────────

def test_marks_are_runs_of_here_and_not_here_on_an_stl():
    assert sl.Part(model="a.stl", support_marks=[0, 10, 1, 2, 2, 3]).problems() == []
    assert sl.Part(model="a.stl", support_marks=[0, 10, 1, 2, 2, 3]).marked() == {"here": 2, "not_here": 3}
    assert "support_marks must be" in sl.Part(model="a.stl", support_marks=[3, 1]).problems()[0]
    assert "support_marks must be" in sl.Part(model="a.stl", support_marks=[1, 0]).problems()[0]
    assert "support_marks must be" in sl.Part(model="a.stl", support_marks=[1]).problems()[0]
    assert sl.Part(model="a.obj", support_marks=[1, 1]).problems() == ["only STL models can have supports marked"]


def test_runs_of_round_trips_and_says_none_for_nothing():
    assert sl.runs_of([0, 0, 1, 1, 0, 2]) == [0, 2, 1, 2, 0, 1, 2, 1]
    assert sl.unrun(sl.runs_of([0, 0, 1, 1, 0, 2])) == [0, 0, 1, 1, 0, 2]
    assert sl.runs_of([0, 0]) is None


def _presets(tmp_path):
    from test_slice import write
    system = tmp_path / "system"
    write(system, "V/machine/v.json", {"name": "V", "printable_area": ["0x0", "300x0", "300x300", "0x300"]})
    write(system, "V/process/n.json", {"name": "N", "support_type": "normal(auto)", "enable_support": "0", "compatible_printers": ["V"]})
    write(system, "V/process/t.json", {"name": "T", "support_type": "tree(auto)", "enable_support": "0", "compatible_printers": ["V"]})
    write(system, "V/filament/asa.json", {"name": "ASA", "filament_type": ["ASA"]})
    return sl.Presets([str(system)])


@pytest.mark.parametrize("supports,process,kind", [("normal", "N", "normal(manual)"), ("tree", "N", "tree(manual)"),
                                                   ("auto", "T", "tree(manual)"), ("auto", "N", "normal(manual)")])
def test_only_where_i_say_is_orcas_manual_kind(tmp_path, supports, process, kind):
    pr = sl.Printer(id="v", name="V", machine="V", process=process, materials={"ASA": "ASA"})
    p = sl.plan(pr, sl.Request(material="ASA", supports=supports, supports_where="only"), _presets(tmp_path))
    assert p.process["support_type"] == kind and p.process["enable_support"] == "1"
    assert any(c.key == "support_type" and c.why == "Supports only where you said" for c in p.changes)


def test_where_is_left_alone_when_needed_or_off(tmp_path):
    pr = sl.Printer(id="v", name="V", machine="V", process="N", materials={"ASA": "ASA"})
    assert sl.plan(pr, sl.Request(material="ASA", supports="normal"), _presets(tmp_path)).process["support_type"] == "normal(auto)"
    off = sl.plan(pr, sl.Request(material="ASA", supports="off", supports_where="only"), _presets(tmp_path))
    assert off.process["enable_support"] == "0" and off.process["support_type"] == "normal(auto)"
    assert sl.Request(supports_where="anywhere").problems(pr)[0].startswith("supports_where must be one of")


# ── written for Orca ─────────────────────────────────────────────────────────

def test_marks_go_in_as_paint_supports_beside_the_paint(tmp_path):
    _boxes_stl(tmp_path / "sign.stl", SIGN)
    tris = sl._triangles(str(tmp_path / "sign.stl"))
    src = _arranged(tmp_path, tris, order=list(reversed(range(len(tris)))))
    paint = [0] * 12 + [2] * 24
    marks = [0] * 36
    marks[0], marks[1], marks[12] = 1, 1, 2
    painted, marked = sl.edit_plates(str(src), str(tmp_path / "own.3mf"), paint={0: (tris, paint)}, marks={0: (tris, marks)})
    data = zipfile.ZipFile(tmp_path / "own.3mf").read("3D/Objects/p0c0__sign.stl_1.model").decode()
    assert painted == {0: 24} and marked == {0: 3}
    assert data.count('paint_supports="4"') == 2 and data.count('paint_supports="8"') == 1 and data.count('paint_color="8"') == 24


def test_a_3mf_keeps_its_own_support_marks(tmp_path):
    verts = [(x, y, z) for x in (0, 10) for y in (0, 10) for z in (0, 10)]
    faces = [(0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3), (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6)]
    marks = {0: "4", 1: "4", 4: "8"}
    tri_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (f' paint_supports="{marks[i]}"' if i in marks else "") + "/>"
                      for i, (a, b, c) in enumerate(faces))
    model = ('<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<resources><object id="1" type="model"><mesh><vertices>' + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
             + f'</vertices><triangles>{tri_xml}</triangles></mesh></object></resources><build><item objectid="1"/></build></model>')
    path = tmp_path / "cube.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", model)
    part, = sl.three_mf_parts(str(path))
    assert part["marks"] == [1, 1, 0, 0, 2] + [0] * 7
    assert sl.runs_of(part["marks"]) == [1, 2, 0, 2, 2, 1, 0, 7]


# ── the real Orca ────────────────────────────────────────────────────────────

async def _slice(real, model, **more):
    part = {"model": model, **({"support_marks": more.pop("marks")} if "marks" in more else {})}
    r = await real.post("/slice", json={"printer": "v", "purpose": "draft", "material": "ASA", "supports": "normal",
                                        "parts": [part], **more})
    assert r.status == 202, await r.text()
    d = await _done(real, (await r.json())["id"])
    assert d["state"] == "done", d.get("error_detail") or d.get("error")
    return d


@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
async def test_real_not_here_and_only_where_i_say(real, tmp_path):
    _boxes_stl(tmp_path / "bracket.stl", BRACKET)
    m = await _upload(real, "bracket.stl", (tmp_path / "bracket.stl").read_bytes())
    n = len(BRACKET) * 12
    assert (await _slice(real, m["model"]))["supports_added"] is True                     # Orca holds the shelf up
    off = await _slice(real, m["model"], marks=marks_on(n, SHELF_UNDERSIDE, 2))
    assert off["supports_added"] is False and off["parts"][0]["marked"] == {"here": 0, "not_here": 2}
    only = await _slice(real, m["model"], supports_where="only")
    assert only["supports_added"] is False and only["request"]["supports_where"] == "only"   # nothing marked: nothing
    mine = await _slice(real, m["model"], supports_where="only", marks=marks_on(n, SHELF_UNDERSIDE, 1))
    assert mine["supports_added"] is True and not mine.get("warnings")
    stale = await real.post("/slice", json={"printer": "v", "material": "ASA", "parts": [{"model": m["model"], "support_marks": [1, 5]}]})
    d = await _done(real, (await stale.json())["id"])
    assert d["state"] == "failed" and "mark it again" in d["error"]


def test_each_printer_says_how_far_a_face_may_lean():
    assert sl.support_angle({"support_threshold_angle": "40"}) == 40          # Anycubic's Kobra profiles
    assert sl.support_angle({"support_threshold_angle": ["35"]}) == 35
    assert sl.support_angle({"support_threshold_angle": "0"}) == 30           # 0: Orca chooses, which is 30
    assert sl.support_angle({}) == 30
    pr = sl.Printer(id="k", name="K", machine="K", process="P", materials={"PLA": "PLA"})
    assert sl.options({"k": pr}, angles={"k": 40.0})["printers"][0]["support_angle"] == 40
    assert sl.options({"k": pr})["printers"][0]["support_angle"] == 30
