#!/usr/bin/env python3
"""Keep the boot eye on the panel while Chromium starts (design/boot/, direction A).

    python3 kiosk/boot/cover.py [theme-dir]

cage draws black from the moment it takes the screen until its first window has a picture, and a
cold Chromium takes seconds to get there. This is that first window: Plymouth's handoff frame (the
ring at mark.json's handoff, the pupil) on the boot background, drawn from the theme's own images,
so the panel goes from Plymouth's last frame to this one to the app's first without a black gap.
It leaves once cage gives the focus to another window (Chromium's), after a minute at most, or with cage.

A plain Wayland client in plain python3 (wl_shm + xdg-shell spoken over the socket): the panel
needs nothing installed for it. Theme dir defaults to kiosk/boot/plymouth next to this file.
"""
import hashlib
import json
import math
import os
import pathlib
import select
import socket
import struct
import sys
import time
import zlib

HERE = pathlib.Path(__file__).resolve().parent
LIFETIME = 60.0     # seconds: never outlive a Chromium that didn't come up (cage's black is no worse)


# ── the picture ──────────────────────────────────────────────────────────────

def read_png(path: pathlib.Path) -> tuple[int, int, bytes]:
    """An 8-bit RGBA PNG (what make-plymouth.py writes) as (width, height, RGBA bytes)."""
    b = path.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", f"{path} isn't a PNG"
    i, idat, w, h = 8, b"", 0, 0
    while i < len(b):
        n, t = struct.unpack(">I4s", b[i:i + 8])
        d = b[i + 8:i + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", d[:10])
            assert (depth, ctype) == (8, 6), f"{path}: only 8-bit RGBA"
        elif t == b"IDAT":
            idat += d
        i += 12 + n
    raw, stride, bpp = zlib.decompress(idat), w * 4, 4
    out, prev = bytearray(h * stride), bytearray(stride)
    for y in range(h):
        f, row = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride if f else 0):     # make-plymouth.py writes every row unfiltered
            a = row[x - bpp] if x >= bpp else 0
            up, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1:
                row[x] = (row[x] + a) & 255
            elif f == 2:
                row[x] = (row[x] + up) & 255
            elif f == 3:
                row[x] = (row[x] + (a + up) // 2) & 255
            elif f == 4:
                p = a + up - c
                pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = row
        prev = row
    return w, h, bytes(out)


def paste(buf: bytearray, W: int, H: int, img: tuple[int, int, bytes], k: float, cx: float, cy: float) -> None:
    """Draw img over buf (XRGB8888, W x H), scaled by k (bilinear) and centered on (cx, cy)."""
    iw, ih, px = img
    dw, dh = iw * k, ih * k
    x0, y0 = max(0, math.floor(cx - dw / 2)), max(0, math.floor(cy - dh / 2))
    x1, y1 = min(W, math.ceil(cx + dw / 2)), min(H, math.ceil(cy + dh / 2))

    def at(x: int, y: int) -> tuple[float, float, float, float]:   # premultiplied, 0 outside
        if 0 <= x < iw and 0 <= y < ih:
            o = (y * iw + x) * 4
            a = px[o + 3] / 255
            return px[o] * a, px[o + 1] * a, px[o + 2] * a, a
        return 0.0, 0.0, 0.0, 0.0

    for y in range(y0, y1):
        sy = (y + 0.5 - (cy - dh / 2)) / k - 0.5
        ty, fy = math.floor(sy), sy - math.floor(sy)
        for x in range(x0, x1):
            sx = (x + 0.5 - (cx - dw / 2)) / k - 0.5
            tx, fx = math.floor(sx), sx - math.floor(sx)
            p = [0.0, 0.0, 0.0, 0.0]
            for (ox, oy, wgt) in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                                  (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
                if wgt:
                    q = at(tx + ox, ty + oy)
                    for c in range(4):
                        p[c] += q[c] * wgt
            if p[3] <= 0:
                continue
            o = (y * W + x) * 4          # XRGB8888 in memory, little-endian: B, G, R, X
            buf[o] = min(255, round(p[2] + buf[o] * (1 - p[3])))
            buf[o + 1] = min(255, round(p[1] + buf[o + 1] * (1 - p[3])))
            buf[o + 2] = min(255, round(p[0] + buf[o + 2] * (1 - p[3])))


def cached_frame(W: int, H: int, theme: pathlib.Path, mark: dict) -> bytes:
    """frame(), kept in ~/.cache between boots: drawing it takes a Pi a few tenths of a second of black."""
    ring = theme / f"ring-{round(mark['handoff'] * mark['frames'])}.png"
    key = hashlib.sha1(json.dumps(mark, sort_keys=True).encode() + ring.read_bytes()
                       + (theme / "pupil.png").read_bytes()).hexdigest()[:12]
    cache = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache") / "elyir-bench"
    path = cache / f"boot-cover-{W}x{H}-{key}.xrgb"
    try:
        data = path.read_bytes()
        if len(data) == W * H * 4:
            return data
    except OSError:
        pass
    data = bytes(frame(W, H, theme, mark))
    try:
        cache.mkdir(parents=True, exist_ok=True)
        for old in cache.glob("boot-cover-*.xrgb"):     # another release's picture (a turned panel keeps both sizes)
            if not old.name.endswith(f"-{key}.xrgb"):
                old.unlink()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        pass    # a read-only home: drawn again next time
    return data


def frame(W: int, H: int, theme: pathlib.Path, mark: dict) -> bytearray:
    """Plymouth's handoff frame at W x H: the same fit as the app's 800x480 viewBox and elyir-bench.script."""
    bg = mark["colors"]["bg"]
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    buf = bytearray(bytes((b, g, r, 255)) * (W * H))
    dw, dh = mark["design"]
    s = min(W / dw, H / dh)
    cx, cy = W / 2 + (mark["center"][0] - dw / 2) * s, H / 2 + (mark["center"][1] - dh / 2) * s
    k = s / mark["img_scale"]
    paste(buf, W, H, read_png(theme / f"ring-{round(mark['handoff'] * mark['frames'])}.png"), k, cx, cy)
    paste(buf, W, H, read_png(theme / "pupil.png"), k, cx, cy)
    return buf


# ── a Wayland client, just enough of one ──────────────────────────────────────

XRGB8888 = 1
ACTIVATED = 4       # xdg_toplevel state


class Wayland:
    def __init__(self):
        path = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        if not path.startswith("/"):
            path = os.path.join(os.environ["XDG_RUNTIME_DIR"], path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.next_id, self.inbuf = 2, b""      # 1 is wl_display

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id - 1

    def send(self, obj: int, op: int, args: bytes = b"", fds: list[int] | None = None) -> None:
        msg = struct.pack("<II", obj, ((8 + len(args)) << 16) | op) + args
        if fds:
            socket.send_fds(self.sock, [msg], fds)
        else:
            self.sock.sendall(msg)

    @staticmethod
    def string(s: str) -> bytes:
        b = s.encode() + b"\0"
        return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)

    def events(self, timeout: float | None):
        """Yield (object, opcode, args) for whatever arrives within timeout; EOF raises."""
        r, _, _ = select.select([self.sock], [], [], timeout)
        if r:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("compositor gone")
            self.inbuf += data
        while len(self.inbuf) >= 8:
            obj, so = struct.unpack("<II", self.inbuf[:8])
            size = so >> 16
            if len(self.inbuf) < size:
                break
            yield obj, so & 0xFFFF, self.inbuf[8:size]
            self.inbuf = self.inbuf[size:]


def read_string(b: bytes, o: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", b, o)[0]
    return b[o + 4:o + 4 + n - 1].decode(), o + 4 + n + (-n % 4)


def show(theme: pathlib.Path, mark: dict) -> None:
    wl = Wayland()
    registry, done = wl.new_id(), wl.new_id()
    wl.send(1, 1, struct.pack("<I", registry))          # wl_display.get_registry
    wl.send(1, 0, struct.pack("<I", done))              # wl_display.sync
    globs: dict[str, tuple[int, int]] = {}
    synced = False
    while not synced:
        for obj, op, a in wl.events(5):
            if obj == registry and op == 0:             # wl_registry.global
                name = struct.unpack_from("<I", a)[0]
                iface, o = read_string(a, 4)
                globs[iface] = (name, struct.unpack_from("<I", a, o)[0])
            elif obj == done:
                synced = True
            elif obj == 1 and op == 0:
                raise RuntimeError("wayland error before anything was drawn")

    def bind(iface: str, version: int) -> int:
        name, have = globs[iface]
        oid = wl.new_id()
        wl.send(registry, 0, struct.pack("<I", name) + wl.string(iface) + struct.pack("<II", min(version, have), oid))
        return oid

    compositor, shm, wm = bind("wl_compositor", 4), bind("wl_shm", 1), bind("xdg_wm_base", 1)
    surface, xsurface, toplevel = wl.new_id(), wl.new_id(), wl.new_id()
    wl.send(compositor, 0, struct.pack("<I", surface))                   # create_surface
    wl.send(wm, 2, struct.pack("<II", xsurface, surface))                # get_xdg_surface
    wl.send(xsurface, 1, struct.pack("<I", toplevel))                    # get_toplevel
    wl.send(toplevel, 3, wl.string("elyir-bench-boot"))                    # set_app_id
    wl.send(surface, 6)                                                  # commit: ask for a size

    size, drawn, was_active, pool = (0, 0), (0, 0), False, None
    deadline = time.monotonic() + LIFETIME
    while time.monotonic() < deadline:
        for obj, op, a in wl.events(max(0.0, deadline - time.monotonic())):
            if obj == 1 and op == 0:                                     # wl_display.error
                return
            if obj == wm and op == 0:                                    # ping
                wl.send(wm, 3, a[:4])
            elif obj == toplevel and op == 0:                            # configure: w, h, states
                w, h, n = struct.unpack_from("<iiI", a)
                states = struct.unpack_from(f"<{n // 4}I", a, 12)
                if w > 0 and h > 0:
                    size = (w, h)
                if ACTIVATED in states:
                    was_active = True
                elif was_active:
                    return                                               # another window has the panel now
            elif obj == toplevel and op == 1:                            # close
                return
            elif obj == xsurface and op == 0:                            # configure done: ack, draw
                wl.send(xsurface, 4, a[:4])
                if size == (0, 0):
                    size = (800, 480)
                if size != drawn:
                    W, H = size
                    pixels = cached_frame(W, H, theme, mark)
                    fd = os.memfd_create("elyir-bench-boot")
                    os.write(fd, pixels)
                    pool, buffer = wl.new_id(), wl.new_id()
                    wl.send(shm, 0, struct.pack("<Ii", pool, len(pixels)), [fd])          # create_pool
                    os.close(fd)
                    wl.send(pool, 0, struct.pack("<IiiiiI", buffer, 0, W, H, W * 4, XRGB8888))
                    wl.send(surface, 1, struct.pack("<Iii", buffer, 0, 0))                # attach
                    wl.send(surface, 2, struct.pack("<iiii", 0, 0, W, H))                 # damage
                    drawn = size
                wl.send(surface, 6)                                                       # commit


def main() -> None:
    theme = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "plymouth"
    mark = json.loads((theme / "cover.json").read_text())
    try:
        show(theme, mark)
    except (ConnectionError, OSError):
        pass    # cage went away first: nothing to cover


if __name__ == "__main__":
    main()
