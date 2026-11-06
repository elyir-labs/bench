"""A G-code file's layers (printer/gcode_layers.py): Orca's and Cura's marks, each read the same way."""
import base64
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location("gcode_layers", Path(__file__).resolve().parent.parent / "gcode_layers.py")
gl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gl)


def walls(public):
    w = public["walls"]
    return struct.unpack(f"<{w['count'] * 5}h", base64.b64decode(w["segs"]))


def test_cura_layers_and_walls_read_like_orcas(tmp_path):
    cura = tmp_path / "cura.gcode"
    cura.write_text(";FLAVOR:Marlin\nM82\n;LAYER:0\n;TYPE:WALL-OUTER\nG0 X0 Y0 Z0.2\nG1 X10 Y0 E1\n;TYPE:FILL\nG1 X10 Y10 E2\n"
                    ";LAYER:1\n;TYPE:WALL-INNER\nG0 Z0.4\nG1 X0 Y10 E3\n;TYPE:WALL-OUTER\nG1 X0 Y0 E4\n")
    public, starts = gl.layer_index(str(cura))
    assert (public["count"], public["z"], len(starts)) == (2, [0.2, 0.4], 2)
    # the outer walls only, x0 y0 x1 y1 z in tenths: one on each layer
    assert walls(public) == (0, 0, 100, 0, 2, 0, 100, 0, 0, 4)


def test_one_kind_of_layer_mark_is_counted_whichever_comes_first(tmp_path):
    orca = tmp_path / "orca.gcode"
    # an Orca file whose custom G-code happens to print ";LAYER:" as well isn't counted twice
    orca.write_text(";LAYER_CHANGE\n;Z:0.2\n;LAYER:0\n;TYPE:Outer wall\nG1 X0 Y0 Z0.2\nG1 X5 Y0 E1\n;LAYER_CHANGE\n;Z:0.4\n;LAYER:1\n")
    public, _ = gl.layer_index(str(orca))
    assert public["count"] == 2
