"""A plate with supports on whose parts need none is arranged as if they were off (Orca leaves ~24 mm round each part
when supports are on, 2 mm when off) and sliced with them on."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench_slice as sl  # noqa: E402
from test_multicolor import _done, _upload, real  # noqa: E402,F401
from test_slice import REAL_ORCA, _boxes_stl  # noqa: E402
from test_supports_where import BRACKET, SHELF_UNDERSIDE, marks_on  # noqa: E402

TRAY = [((3, 3, 0), (107, 107, 2)), ((0, 0, 0), (3, 110, 30)), ((107, 0, 0), (110, 110, 30)),
        ((3, 0, 0), (107, 3, 30)), ((3, 107, 0), (107, 110, 30))]      # a floor and four walls, open on top


def test_a_tray_needs_none_a_bracket_does(tmp_path):
    tray, bracket = tmp_path / "tray.stl", tmp_path / "bracket.stl"
    _boxes_stl(tray, TRAY)
    _boxes_stl(bracket, BRACKET)
    assert sl.needs_supports(str(tray)) is False
    assert sl.needs_supports(str(bracket)) is True
    assert sl.needs_supports(str(bracket), threshold=0.1) is True       # its shelf is flat underneath
    (tmp_path / "x.step").write_text("ISO-10303-21;")
    assert sl.needs_supports(str(tmp_path / "x.step")) is None


def test_supportless_only_when_supports_are_on_and_nothing_gets_them(tmp_path):
    tray, bracket = tmp_path / "tray.stl", tmp_path / "bracket.stl"
    _boxes_stl(tray, TRAY)
    _boxes_stl(bracket, BRACKET)
    t, b = sl.Part(model=str(tray)), sl.Part(model=str(bracket))
    on = sl.Request(supports="tree")
    assert sl.supportless(on, [t, t], [str(tray)] * 2, 40)
    assert not sl.supportless(on, [t, b], [str(tray), str(bracket)], 40)
    assert not sl.supportless(sl.Request(supports="off"), [t], [str(tray)], 40)       # Orca packs it close anyway
    assert not sl.supportless(sl.Request(supports="tree", orient=True), [t], [str(tray)], 40)
    only = sl.Request(supports="tree", supports_where="only")
    assert sl.supportless(only, [b], [str(bracket)], 40)                             # nothing marked: nothing supported
    here = sl.Part(model=str(bracket), support_marks=marks_on(len(BRACKET) * 12, SHELF_UNDERSIDE, 1))
    assert not sl.supportless(only, [here], [str(bracket)], 40)
    marked_tray = sl.Part(model=str(tray), support_marks=marks_on(len(TRAY) * 12, [0], 1))
    assert not sl.supportless(on, [marked_tray], [str(tray)], 40)


# ── with the real Orca: nine 110 mm trays on a 350 mm bed fit 2 mm apart, not 24 ─────────────────

@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
async def test_service_fits_nine_trays_with_supports_on(real, tmp_path):
    _boxes_stl(tmp_path / "tray.stl", TRAY)
    m = await _upload(real, "tray.stl", (tmp_path / "tray.stl").read_bytes())
    r = await real.post("/slice/fit", json={"printer": "v", "parts": [{"model": m["model"], "copies": 9}], "part": None,
                                            "supports": "tree"})
    assert r.status == 200, await r.text()
    assert (await r.json())["counts"] == [9]
    bad = await real.post("/slice/fit", json={"printer": "v", "parts": [{"model": m["model"]}], "part": None, "supports": "lots"})
    assert bad.status == 400


@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
async def test_service_slices_nine_trays_on_one_plate_with_supports_still_on(real, tmp_path):
    _boxes_stl(tmp_path / "tray.stl", TRAY)
    m = await _upload(real, "tray.stl", (tmp_path / "tray.stl").read_bytes())
    r = await real.post("/slice", json={"printer": "v", "purpose": "draft", "supports": "tree", "material": "ASA",
                                        "parts": [{"model": m["model"], "copies": 9}]})
    assert r.status == 202, await r.text()
    d = await _done(real, (await r.json())["id"])
    assert d["state"] == "done", d.get("error_detail") or d.get("error")
    assert [p["counts"] for p in d["plates"]] == [[9]]
    assert any(c["key"] == "enable_support" and c["value"] == "1" for c in d["changes"])


@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
def test_the_arranged_plate_is_sliced_with_supports_back_on(tmp_path):
    """Arranged with arrange.json (supports off), sliced with process.json on top: a bracket still gets supports."""
    import subprocess
    pr = sl.Printer(id="v", name="Workshop", machine="Voron 2.4 350 0.4 nozzle", process="0.20mm Standard @Voron",
                    materials={"ASA": "Generic ASA @System"})
    presets = sl.Presets(["/Applications/OrcaSlicer.app/Contents/Resources/profiles"])
    p = sl.plan(pr, sl.Request(material="ASA", supports="tree"), presets)
    sl.write_plan(p, str(tmp_path))
    model = tmp_path / sl.part_file(0, "bracket.stl", 0)
    _boxes_stl(model, BRACKET)
    out = tmp_path / "out"
    out.mkdir()
    process = sl.write_arrange_process(p, str(tmp_path))
    subprocess.run(sl.orca_command([REAL_ORCA], str(tmp_path), [str(model)], str(out), False, slice_it=False,
                                   process=process), check=True, capture_output=True, timeout=300)
    subprocess.run(sl.orca_slice_3mf([REAL_ORCA], str(tmp_path), str(out / sl.PLATES_3MF), str(out)),
                   check=True, capture_output=True, timeout=300)
    assert sl.read_result(str(out / "plate_1.gcode"))["supports"] is True
