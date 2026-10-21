"""A change at a height and painting (design/paint-and-height/, C with A, and A): what the request carries, the
arranged 3MF edited for Orca, and real slices."""
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench_slice as sl  # noqa: E402
from test_multicolor import WHITE, _done, _upload, real  # noqa: E402,F401
from test_slice import REAL_ORCA, _boxes_stl  # noqa: E402

BLACK = "#2B2B2B"
SIGN = [((0, 0, 0), (100, 36, 3.2)), ((15, 10, 3.2), (40, 26, 5)), ((55, 10, 3.2), (85, 26, 5))]   # a plate, two raised letters


def two():
    return [sl.Spool(material="ASA", color=WHITE, slot=0), sl.Spool(material="ASA", color=BLACK, slot=1)]


# ── what can be asked ────────────────────────────────────────────────────────

def test_a_height_needs_colors_and_goes_up():
    assert sl.Request(spools=two(), heights=[sl.Height(3.2, 1)]).height_problems() == []
    assert "needs the plate's colors" in sl.Request(heights=[sl.Height(3.2, 1)]).height_problems()[0]
    assert "heights must go up, each once" in sl.Request(spools=two(), heights=[sl.Height(5, 1), sl.Height(3, 0)]).height_problems()
    assert any("one of the plate's 2 colors" in p for p in sl.Request(spools=two(), heights=[sl.Height(3, 2)]).height_problems())
    assert any("one after the other" in p for p in sl.Request(spools=two(), one_after_other=True, heights=[sl.Height(3, 1)]).height_problems())


def test_paint_is_runs_on_an_stl():
    assert sl.Part(model="a.stl", paint=[0, 10, 2, 2]).problems() == []
    assert sl.Part(model="a.stl", paint=[0, 10, 2, 2]).painted() == {1}
    assert "paint must be" in sl.Part(model="a.stl", paint=[0, 10, 2]).problems()[0]
    assert "paint must be" in sl.Part(model="a.stl", paint=[17, 1]).problems()[0]
    assert "paint must be" in sl.Part(model="a.stl", paint=[1, 0]).problems()[0]
    assert sl.Part(model="a.obj", paint=[1, 1]).problems() == ["only STL models can be painted"]


# ── the 3MF for Orca ─────────────────────────────────────────────────────────

def test_a_change_goes_on_the_first_layer_above():
    assert sl.layer_top(3.2, 0.2, 0.2) == 3.4        # letters from 3.2 mm: their first layer
    assert sl.layer_top(3.25, 0.2, 0.2) == 3.6       # the layer 3.2 to 3.4 starts below it
    assert sl.layer_top(3.2, 0.2, 0.28) == 3.56      # Draft's layers
    assert sl.layer_top(0.1, 0.25, 0.2) == 0.45
    assert sl.layer_top(2.0, 0.3, 0.1) == 2.1


def test_heights_on_every_plate():
    xml = sl.heights_xml([sl.Height(3.2, 1), sl.Height(4.4, 0)], two(), 2, 0.2, 0.2).decode()
    assert xml.count("<plate>") == 2 and '<plate_info id="2" />' in xml
    assert '<layer top_z="3.4" type="2" extruder="2" color="#2B2B2B"' in xml and 'top_z="4.6" type="2" extruder="1"' in xml
    assert xml.count('<mode value="MultiAsSingle" />') == 2


def test_paint_codes_read_back():
    for state in range(1, 17):
        assert sl.paint_state(sl.paint_code(state)) == state
    assert (sl.paint_code(1), sl.paint_code(2), sl.paint_code(3), sl.paint_code(4)) == ("4", "8", "0C", "1C")
    assert sl.unrun([0, 2, 3, 1]) == [0, 0, 3]


def _arranged(tmp_path, tris, shift=(-50, -18, -2.5), order=None, drop=0):
    """An arranged 3MF as Orca writes it: the mesh moved (its middle to 0), vertices shared, maybe reordered."""
    faces = [tris[i] for i in (order or range(len(tris)))][drop:]
    verts, index = [], {}
    def vi(v):
        k = tuple(round(c + d, 4) for c, d in zip(v, shift))
        if k not in index:
            index[k] = len(verts)
            verts.append(k)
        return index[k]
    tri_xml = "".join(f'<triangle v1="{vi(a)}" v2="{vi(b)}" v3="{vi(c)}"/>' for a, b, c in faces)
    mesh = ("<model><resources><object id=\"1\"><mesh><vertices>" + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
            + f"</vertices><triangles>{tri_xml}</triangles></mesh></object></resources></model>")
    path = tmp_path / "plates.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("3D/Objects/p0c0__sign.stl_1.model", mesh)
        z.writestr("Metadata/model_settings.config", '<config><object id="2"><metadata key="name" value="p0c0__sign.stl"/></object>'
                   '<plate><metadata key="plater_id" value="1"/></plate></config>')
        z.writestr("Metadata/plate_1.gcode", "old")
    return path


def _paint_of(path):
    data = zipfile.ZipFile(path).read("3D/Objects/p0c0__sign.stl_1.model").decode()
    return data.count('paint_color="8"'), data


@pytest.mark.parametrize("order,drop", [(None, 0), ("reversed", 0), (None, 1)])
def test_paint_finds_its_triangles_moved_reordered_or_one_dropped(tmp_path, order, drop):
    _boxes_stl(tmp_path / "sign.stl", SIGN)
    tris = sl._triangles(str(tmp_path / "sign.stl"))
    states = [0] * 12 + [2] * 24                                       # the letters in the plate's second color
    src = _arranged(tmp_path, tris, order=list(reversed(range(len(tris)))) if order else None, drop=drop)
    done = sl.edit_plates(str(src), str(tmp_path / "own.3mf"), paint={0: (tris, states)},
                          heights=sl.heights_xml([sl.Height(3.2, 1)], two(), 1, 0.2, 0.2))
    n, data = _paint_of(tmp_path / "own.3mf")
    letters_left = 24 - (1 if drop and order else 0)
    assert n == done[0] == letters_left and 'paint_color="4"' not in data
    with zipfile.ZipFile(tmp_path / "own.3mf") as z:
        assert "Metadata/custom_gcode_per_layer.xml" in z.namelist() and "Metadata/plate_1.gcode" not in z.namelist()


def test_set_brims_still_only_touches_brims(tmp_path):
    _boxes_stl(tmp_path / "sign.stl", SIGN)
    src = _arranged(tmp_path, sl._triangles(str(tmp_path / "sign.stl")))
    sl.set_brims(str(src), str(tmp_path / "b.3mf"), ["no_brim"])
    with zipfile.ZipFile(tmp_path / "b.3mf") as z:
        assert 'value="no_brim"' in z.read("Metadata/model_settings.config").decode()
        assert "Metadata/custom_gcode_per_layer.xml" not in z.namelist()
        assert "paint_color" not in z.read("3D/Objects/p0c0__sign.stl_1.model").decode()


# ── real slices ──────────────────────────────────────────────────────────────

def _changes(gcode: str):
    z, out = None, []
    for line in gcode.splitlines():
        if line.startswith(";Z:"):
            z = float(line[3:])
        elif line.startswith("T") and line[1:].strip().isdigit() and z is not None:
            out.append((z, line.strip()))
    return out


SPOOLS = [{"material": "ASA", "color": WHITE, "slot": 1}, {"material": "ASA", "color": BLACK, "slot": 2}]


@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
async def test_service_letters_from_a_height(real, tmp_path):
    _boxes_stl(tmp_path / "sign.stl", SIGN)
    m = await _upload(real, "sign.stl", (tmp_path / "sign.stl").read_bytes())
    r = await real.post("/slice", json={"printer": "v", "purpose": "draft", "parts": [{"model": m["model"]}],
                                        "spools": SPOOLS, "heights": [{"z": 3.2, "spool": 1}]})
    assert r.status == 202, await r.text()
    d = await _done(real, (await r.json())["id"])
    assert d["state"] == "done", d.get("error_detail") or d.get("error")
    assert d["request"]["heights"] == [{"z": 3.2, "spool": 1}]
    assert d["colors"]["unit_changes"] == 1 and d["colors"]["spools"][1]["heights"] == [3.2]
    body = await (await real.get(f"/slice/{d['id']}/gcode")).text()
    assert [c for c in _changes(body) if c[0] > 0.5] == [(3.56, "T1")]   # Draft: 0.2 mm, then 0.28 mm layers


@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
async def test_service_painted_letters(real, tmp_path):
    _boxes_stl(tmp_path / "sign.stl", SIGN)
    m = await _upload(real, "sign.stl", (tmp_path / "sign.stl").read_bytes())
    part = {"model": m["model"], "copies": 2, "paint": [0, 12, 2, 24]}
    r = await real.post("/slice", json={"printer": "v", "purpose": "draft", "parts": [part], "spools": SPOOLS})
    assert r.status == 202, await r.text()
    d = await _done(real, (await r.json())["id"])
    assert d["state"] == "done", d.get("error_detail") or d.get("error")
    assert d["parts"][0]["painted"] == [1] and d["colors"]["spools"][1]["painted"] == [0] and not d.get("warnings")
    body = await (await real.get(f"/slice/{d['id']}/gcode")).text()
    assert [c for c in _changes(body) if c[0] > 0.5] == [(3.56, "T1")]   # both copies' letters at once, as by height
    bad = await real.post("/slice", json={"printer": "v", "parts": [{**part, "paint": [0, 12, 3, 24]}], "spools": SPOOLS})
    assert bad.status == 400 and "paint uses a color the plate hasn't got" in (await bad.json())["error"]
    short = await real.post("/slice", json={"printer": "v", "purpose": "draft", "parts": [{**part, "paint": [0, 12, 2, 20]}], "spools": SPOOLS})
    d = await _done(real, (await short.json())["id"])
    assert d["state"] == "failed" and "paint it again" in d["error"]
