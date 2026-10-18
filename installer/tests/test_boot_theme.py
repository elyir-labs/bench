# The Plymouth theme the BootScreen step installs, as kiosk/boot/make-plymouth.py builds it.
import importlib.util
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("make_plymouth", ROOT / "kiosk" / "boot" / "make-plymouth.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
MARK = json.loads((ROOT / "app" / "src" / "boot" / "mark.json").read_text())


def pixels(path):
    data = path.read_bytes()
    w, h = struct.unpack(">II", data[16:24])
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    rows = [raw[y * (w * 4 + 1) + 1:(y + 1) * (w * 4 + 1)] for y in range(h)]
    return w, h, rows


def accent_px(path):
    acc = mp.hex_rgb(MARK["colors"]["accent"])
    w, h, rows = pixels(path)
    return sum(1 for r in rows for x in range(w) if tuple(r[x * 4:x * 4 + 3]) == acc and r[x * 4 + 3] == 255)


def test_theme_builds_from_the_mark(tmp_path):
    mp.main(str(tmp_path))
    names = {p.name for p in tmp_path.iterdir()}
    assert {"elyir-bench.plymouth", "elyir-bench.script", "pupil.png"} <= names
    assert all(f"ring-{i}.png" in names for i in range(mp.FRAMES + 1))
    script = (tmp_path / "elyir-bench.script").read_text()
    assert not re.findall(r"@[A-Z_]+@", script)     # every placeholder filled
    assert f"* {MARK['handoff']} *" in script        # the handoff the app picks up from
    # the ring image is the ring's size at 2x: radius plus half the stroke, both sides
    w, h, _ = pixels(tmp_path / "ring-0.png")
    assert w == h and abs(w - 2 * (MARK["ring"]["r"] + MARK["ring"]["stroke"] / 2) * mp.SCALE) <= 5
    # frame 0 is only the track; the arc grows frame by frame; frame 100 is a closed ring
    a0, a50, a100 = (accent_px(tmp_path / f"ring-{i}.png") for i in (0, 50, 100))
    assert a0 == 0 and 0 < a50 < a100
    assert abs(a50 / a100 - 0.5) < 0.05
    # A′: "hi" first, then the track draws itself round; its last frame is the empty ring the fill starts from
    assert "hi.png" in names and all(f"outline-{i}.png" in names for i in range(mp.OUTLINE + 1))
    assert all(px == 0 for r in pixels(tmp_path / "outline-0.png")[2] for px in r[3::4])
    assert pixels(tmp_path / f"outline-{mp.OUTLINE}.png")[2] == pixels(tmp_path / "ring-0.png")[2]
    assert '"hi.png"' in script and '"outline-"' in script


def test_cover_draws_the_handoff_frame(tmp_path):
    # kiosk/boot/cover.py covers cage's black until Chromium has a window: Plymouth's last frame,
    # from the theme's own images, at the panel's size and the app's fit
    mp.main(str(tmp_path))
    spec = importlib.util.spec_from_file_location("cover", ROOT / "kiosk" / "boot" / "cover.py")
    cover = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cover)
    mark = json.loads((tmp_path / "cover.json").read_text())
    assert mark["handoff"] == MARK["handoff"] and mark["center"] == MARK["center"]
    W, H = 800, 480
    buf = cover.frame(W, H, tmp_path, mark)
    rgb = lambda x, y: (buf[(y * W + x) * 4 + 2], buf[(y * W + x) * 4 + 1], buf[(y * W + x) * 4])
    near = lambda c, want: all(abs(a - b) <= 3 for a, b in zip(c, want))
    bg, acc = mp.hex_rgb(MARK["colors"]["bg"]), mp.hex_rgb(MARK["colors"]["accent"])
    cx, cy, r = *MARK["center"], MARK["ring"]["r"]
    assert near(rgb(0, 0), bg) and near(rgb(W - 1, H - 1), bg)
    assert near(rgb(cx, cy), acc)                      # the pupil
    assert near(rgb(cx, cy - r), acc)                  # twelve o'clock: the arc starts there
    assert near(rgb(cx + r, cy), acc)                  # a quarter turn: under the handoff
    left = rgb(cx - r, cy)                             # three quarters: past it, only the track
    assert not near(left, acc) and not near(left, bg)
