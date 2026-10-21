#!/usr/bin/env python3
"""Build the Plymouth theme for the boot eye from app/src/boot/mark.json.

    python3 kiosk/boot/make-plymouth.py <out-dir>

Writes elyir-bench.plymouth, elyir-bench.script, cover.json, pupil.png, ring-0.png .. ring-100.png (the
track plus 0% .. 100% of the arc, from twelve o'clock, round caps), outline-0.png .. outline-50.png (the track alone,
drawing itself round), and for E the Elyir signature: name-0.png .. name-64.png (elyir being written, by length
along the stroke), dot.png (the i's dot before it lights) and glow.png. Images are drawn at twice the design
size, so the script scales them down on the 800x480 panel and stays sharp on bigger ones.

No dependencies: the panel's installer and the release build both run this with plain python3.
The same geometry draws the app's boot screen, so Plymouth's last frame and the app's first match.
"""
import bisect
import json
import math
import pathlib
import re
import struct
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
MARK = HERE.parent.parent / "app" / "src" / "boot" / "mark.json"
SCALE = 2          # pixels per design unit in the images
SS = 3             # subsamples per pixel side, for antialiasing
FRAMES = 100       # ring-0 .. ring-100: one per percent of the arc
OUTLINE = 50       # outline-0 .. outline-50: the track drawing itself round before the ring fills
NAME = 64          # name-0 .. name-64: elyir written, by length along the stroke
GLOW = 4.2 * 0.68  # the dot's glow reaches this many dot radii, fading out from 0.55 (design/boot/, E)


def png(path: pathlib.Path, w: int, h: int, rgba: bytearray) -> None:
    rows = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def hex_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def ring_frames(m: dict, out: pathlib.Path) -> int:
    r, half = m["ring"]["r"] * SCALE, m["ring"]["stroke"] * SCALE / 2
    size = math.ceil(2 * (r + half)) + 4
    c = size / 2
    accent = hex_rgb(m["colors"]["accent"])
    tr, tg, tb, ta = m["colors"]["track"]
    # Every subsample inside the stroke, with its angle clockwise from twelve o'clock (0..1 turns).
    # Per pixel the angles are kept sorted, so "how much of this pixel is under the first A of the
    # arc" is one bisect. Only pixels near the two round caps need their subsamples looked at.
    pix: dict[tuple[int, int], list[float]] = {}
    pts: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for y in range(size):
        for x in range(size):
            for j in range(SS):
                for i in range(SS):
                    px, py = x + (i + 0.5) / SS - c, y + (j + 0.5) / SS - c
                    if abs(math.hypot(px, py) - r) <= half:
                        a = (math.atan2(px, -py) / (2 * math.pi)) % 1.0
                        pix.setdefault((x, y), []).append(a)
                        pts.setdefault((x, y), []).append((px, py))
    for v in pix.values():
        v.sort()
    n = SS * SS

    def near(pt, k):   # pixels within a cap's reach of a point on the center line
        return {p for p in pix if abs(p[0] - (pt[0] + c)) <= half + 2 and abs(p[1] - (pt[1] + c)) <= half + 2}

    def on_line(t):    # the center-line point at t turns
        return (r * math.sin(2 * math.pi * t), -r * math.cos(2 * math.pi * t))

    start = on_line(0.0)
    start_px = near(start, 0)

    def covered(x, y, angles, A, end, end_px):   # how much of this pixel is under the first A turns, round caps
        if A <= 0:
            return 0.0
        if (x, y) in start_px or (x, y) in end_px:
            inside = 0
            for (px, py), a in zip(pts[(x, y)], angles):
                if a <= A or math.hypot(px - start[0], py - start[1]) <= half \
                        or math.hypot(px - end[0], py - end[1]) <= half:
                    inside += 1
            return inside / n
        return bisect.bisect_right(angles, A) / n

    for f in range(FRAMES + 1):
        A = f / FRAMES
        end = on_line(A)
        end_px = near(end, 0) if 0 < A < 1 else set()
        buf = bytearray(size * size * 4)
        for (x, y), angles in pix.items():
            track = len(angles) / n
            cov = covered(x, y, angles, A, end, end_px)
            # the arc, over the track
            ta_px = ta * track * (1 - cov)
            alpha = cov + ta_px
            if alpha <= 0:
                continue
            o = (y * size + x) * 4
            buf[o:o + 4] = bytes((round((accent[0] * cov + tr * ta_px) / alpha), round((accent[1] * cov + tg * ta_px) / alpha),
                                  round((accent[2] * cov + tb * ta_px) / alpha), round(255 * alpha)))
        png(out / f"ring-{f}.png", size, size, buf)
    # A′: before any progress the track draws itself round from twelve o'clock, an outline with round ends
    for f in range(OUTLINE + 1):
        T = f / OUTLINE
        end = on_line(T)
        end_px = near(end, 0) if 0 < T < 1 else set()
        buf = bytearray(size * size * 4)
        for (x, y), angles in pix.items():
            cov = covered(x, y, angles, T, end, end_px) if T < 1 else len(angles) / n
            if cov > 0:
                o = (y * size + x) * 4
                buf[o:o + 4] = bytes((tr, tg, tb, round(255 * ta * cov)))
        png(out / f"outline-{f}.png", size, size, buf)
    return size


def disc(path: pathlib.Path, r: float, rgb, alpha: float = 1.0) -> int:
    size = math.ceil(2 * r) + 4
    c = size / 2
    buf = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            cov = sum(math.hypot(x + (i + 0.5) / SS - c, y + (j + 0.5) / SS - c) <= r
                      for j in range(SS) for i in range(SS)) / (SS * SS)
            if cov:
                o = (y * size + x) * 4
                buf[o:o + 4] = bytes((*rgb, round(255 * alpha * cov)))
    png(path, size, size, buf)
    return size


def pupil(m: dict, out: pathlib.Path) -> int:
    return disc(out / "pupil.png", m["pupil"]["r"] * SCALE, hex_rgb(m["colors"]["accent"]))


def over_bg(m: dict, rgba) -> tuple[int, int, int]:
    """A translucent color as the solid color it makes on the boot background, so overlapping strokes don't darken."""
    bg = hex_rgb(m["colors"]["bg"])
    return tuple(round(rgba[3] * rgba[i] + (1 - rgba[3]) * bg[i]) for i in range(3))


def path_points(d: str, step: float) -> list[tuple[float, float]]:
    """An SVG path of M and C commands, as points no more than `step` apart in its own units."""
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    assert re.fullmatch(r"M[-\d. ]+(C[-\d. ]+)+", d), "the signature path is M then C commands only"
    x, y = nums[0], nums[1]
    pts = [(x, y)]
    for i in range(2, len(nums), 6):
        x1, y1, x2, y2, x3, y3 = nums[i:i + 6]
        rough = math.dist((x, y), (x1, y1)) + math.dist((x1, y1), (x2, y2)) + math.dist((x2, y2), (x3, y3))
        n = max(2, math.ceil(rough / step))
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            pts.append((u * u * u * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
                        u * u * u * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3))
        x, y = x3, y3
    return pts


def signature(m: dict, out: pathlib.Path) -> dict:
    """elyir being written, NAME + 1 frames cropped to the name, by length along the stroke, round caps.

    Each subsample remembers the length along the stroke at which the pen first covers it, so a frame is
    "every subsample covered by this length" and the strokes that cross over themselves draw in order.
    """
    g = m["signature"]
    k = g["scale"] * SCALE                                  # image pixels per path unit
    half = g["stroke"] * k / 2
    pts = [((px - g["units"][0]) * k, (py - g["units"][1]) * k) for px, py in path_points(g["d"], 0.5 / k)]
    x0 = math.floor(min(p[0] for p in pts) - half) - 2
    y0 = math.floor(min(p[1] for p in pts) - half) - 2
    w = math.ceil(max(p[0] for p in pts) + half) + 2 - x0
    h = math.ceil(max(p[1] for p in pts) + half) + 2 - y0
    sw = w * SS
    first = [math.inf] * (sw * h * SS)
    hs = half * SS
    along = 0.0
    prev = pts[0]
    for p in pts:
        along += math.dist(prev, p)
        prev = p
        cx, cy = (p[0] - x0) * SS - 0.5, (p[1] - y0) * SS - 0.5
        for sy in range(max(0, math.ceil(cy - hs)), min(h * SS - 1, math.floor(cy + hs)) + 1):
            span = math.sqrt(max(0.0, hs * hs - (sy - cy) ** 2))
            row = sy * sw
            for sx in range(max(0, math.ceil(cx - span)), min(sw - 1, math.floor(cx + span)) + 1):
                if first[row + sx] > along:
                    first[row + sx] = along
    inked = {}
    for y in range(h):
        for x in range(w):
            v = sorted(first[(y * SS + j) * sw + x * SS + i] for j in range(SS) for i in range(SS))
            if v[0] < math.inf:
                inked[(x, y)] = v
    ink = over_bg(m, m["colors"]["ink"])
    n = SS * SS
    for f in range(NAME + 1):
        L = along * f / NAME
        buf = bytearray(w * h * 4)
        for (x, y), v in (inked.items() if f else ()):
            cov = bisect.bisect_right(v, L) / n
            if cov:
                o = (y * w + x) * 4
                buf[o:o + 4] = bytes((*ink, round(255 * cov)))
        png(out / f"name-{f}.png", w, h, buf)
    ox, oy = g["origin"][0] + x0 / SCALE, g["origin"][1] + y0 / SCALE
    tx = g["origin"][0] + (g["tittle"][0] - g["units"][0]) * g["scale"]
    ty = g["origin"][1] + (g["tittle"][1] - g["units"][1]) * g["scale"]
    return {"name_x": ox, "name_y": oy, "tittle": (tx, ty)}


def lamp(m: dict, out: pathlib.Path) -> None:
    """The i's dot before it lights, and its glow, both at the pupil's full size: the script shrinks them to the dot."""
    r = m["pupil"]["r"] * SCALE
    disc(out / "dot.png", r, over_bg(m, m["colors"]["ink"]))
    R = r * GLOW
    size = math.ceil(2 * R) + 4
    c = size / 2
    accent = hex_rgb(m["colors"]["accent"])
    buf = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            a = 0.55 * max(0.0, 1 - math.hypot(x + 0.5 - c, y + 0.5 - c) / R)
            if a > 0:
                o = (y * size + x) * 4
                buf[o:o + 4] = bytes((*accent, round(255 * a)))
    png(out / "glow.png", size, size, buf)


def main(out: str) -> None:
    m = json.loads(MARK.read_text())
    d = pathlib.Path(out)
    d.mkdir(parents=True, exist_ok=True)
    ring_frames(m, d)
    pupil(m, d)
    lamp(m, d)
    sig = signature(m, d)
    bg = hex_rgb(m["colors"]["bg"])
    values = {
        "@DW@": m["design"][0], "@DH@": m["design"][1], "@CX@": m["center"][0], "@CY@": m["center"][1],
        "@IMG_SCALE@": SCALE, "@FRAMES@": FRAMES, "@OUTLINE@": OUTLINE, "@HANDOFF@": m["handoff"],
        "@NAME@": NAME, "@NAME_X@": round(sig["name_x"], 2), "@NAME_Y@": round(sig["name_y"], 2),
        "@TX@": round(sig["tittle"][0], 2), "@TY@": round(sig["tittle"][1], 2),
        "@DOT0@": round(m["signature"]["dot"] / (2 * m["pupil"]["r"]), 4),
        "@BG_R@": round(bg[0] / 255, 4), "@BG_G@": round(bg[1] / 255, 4), "@BG_B@": round(bg[2] / 255, 4),
    }
    # what cover.py needs to draw the handoff frame under cage until Chromium has a window (no app/ in a release)
    (d / "cover.json").write_text(json.dumps({
        "design": m["design"], "center": m["center"], "handoff": m["handoff"], "frames": FRAMES,
        "img_scale": SCALE, "colors": {"bg": m["colors"]["bg"]}}) + "\n")
    script = (HERE / "elyir-bench.script").read_text()
    for k, v in values.items():
        script = script.replace(k, str(v))
    left = re.findall(r"@[A-Z_]+@", script)
    assert not left, f"elyir-bench.script has unfilled placeholders: {left}"
    (d / "elyir-bench.script").write_text(script)
    (d / "elyir-bench.plymouth").write_text(
        "[Plymouth Theme]\nName=Elyir Bench\nDescription=The Elyir Bench eye: a ring that fills as the printer starts\n"
        "ModuleName=script\n\n[script]\nImageDir=/usr/share/plymouth/themes/elyir-bench\n"
        "ScriptFile=/usr/share/plymouth/themes/elyir-bench/elyir-bench.script\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
