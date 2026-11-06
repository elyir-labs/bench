# A G-code file's layers, for pictures of the print: where each layer starts, every layer's outer wall, and any one
# layer's paths. Shared by the slicer (design/look/: a slice read back) and the printer's Moonraker component
# (design/now-layers/: the ring on Now, for whatever file is printing). Standard library only.
from __future__ import annotations

import base64
import contextlib
import math
import re
import struct
from typing import Any, Dict, List, Optional, Tuple

_AXIS = re.compile(r"([XYZE])(-?\d*\.?\d+)")

# Layers (design/look/, A with C's layers): a slice's G-code read once into where each layer starts and every
# layer's outer wall, to draw the print up to a cut; then any one layer's paths on request, each move tagged
# with what it prints.
WALL, INNER, INFILL, SUPPORT, OTHER = range(5)
_KIND_OF = (("Outer wall", WALL), ("Overhang wall", WALL), ("External perimeter", WALL), ("Inner wall", INNER),
            ("Perimeter", INNER), ("Support", SUPPORT), ("Skirt", OTHER), ("Brim", OTHER), ("Prime tower", OTHER),
            ("Wipe tower", OTHER), ("Custom", OTHER),
            # Cura's names
            ("WALL-OUTER", WALL), ("WALL-INNER", INNER), ("SUPPORT", SUPPORT), ("SKIRT", OTHER), ("PRIME-TOWER", OTHER))


def _kind(name: str) -> int:
    return next((k for prefix, k in _KIND_OF if name.startswith(prefix)), INFILL)


class _Walk:
    """The nozzle through G-code one line at a time: where it is, and the line an extruding move draws."""

    def __init__(self, state: Optional[Tuple[float, float, float, bool, float, int]] = None):
        self.x, self.y, self.z, self.e_abs, self.last_e, self.kind = state or (0.0, 0.0, 0.0, False, 0.0, OTHER)

    def state(self) -> Tuple[float, float, float, bool, float, int]:
        return (self.x, self.y, self.z, self.e_abs, self.last_e, self.kind)

    def step(self, line: str) -> Optional[Tuple[float, float, float, float]]:
        c = line[:1]
        if c == ";":
            if line.startswith(";TYPE:"):
                self.kind = _kind(line[6:].strip())
            return None
        if c != "G" and c != "M":
            return None
        if line.startswith("M82"):
            self.e_abs = True
            return None
        if line.startswith("M83"):
            self.e_abs = False
            return None
        if not (line.startswith("G1 ") or line.startswith("G0 ")):
            if line.startswith("G92"):
                m = re.search(r"E(-?\d*\.?\d+)", line)
                if m:
                    self.last_e = float(m.group(1))
            return None
        nx, ny, e = self.x, self.y, None
        for k, v in _AXIS.findall(line.split(";", 1)[0]):
            if k == "X":
                nx = float(v)
            elif k == "Y":
                ny = float(v)
            elif k == "Z":
                self.z = float(v)
            else:
                e = float(v)
        if e is not None and self.e_abs:
            e, self.last_e = e - self.last_e, e
        seg = (self.x, self.y, nx, ny) if e is not None and e > 0 and (nx != self.x or ny != self.y) else None
        self.x, self.y = nx, ny
        return seg


def _pack16(values: List[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}h", *(max(-32768, min(32767, round(v * 10))) for v in values))).decode()


def layer_index(gcode: str, limit: int = 60000) -> Tuple[Dict[str, Any], List[Tuple[int, Tuple[float, float, float, bool, float, int]]]]:
    """Each layer's height above the plate and every layer's outer wall (segs as support_lines packs them, and
    `layer`: each segment's layer as uint16s), for people; and where each layer starts in the file with the
    nozzle's state there, so layer_paths can read one alone. A tall print has more wall than a phone wants, so
    whole layers of it are left out until `limit` segments remain, drawn wider to close the gaps."""
    walk = _Walk()
    starts: List[Tuple[int, Tuple[float, float, float, bool, float, int]]] = []
    zs: List[Optional[float]] = []
    walls: List[List[Tuple[float, float, float, float]]] = []
    height = 0.2
    pos = 0
    marker = None   # Orca and PrusaSlicer write ";LAYER_CHANGE", Cura ";LAYER:n": whichever comes first
    with open(gcode, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", "replace")
            if marker is None and (line.startswith(";LAYER_CHANGE") or line.startswith(";LAYER:")):
                marker = ";LAYER_CHANGE" if line.startswith(";LAYER_CHANGE") else ";LAYER:"
            if marker and line.startswith(marker):
                starts.append((pos + len(raw), walk.state()))
                zs.append(None)
                walls.append([])
            elif line.startswith(";Z:") and zs and zs[-1] is None:
                with contextlib.suppress(ValueError):
                    zs[-1] = float(line[3:])
            elif line.startswith(";HEIGHT:"):
                with contextlib.suppress(ValueError):
                    height = float(line[8:]) or height
            seg = walk.step(line)
            if seg and walls:
                if zs[-1] is None:
                    zs[-1] = walk.z
                if walk.kind == WALL:
                    walls[-1].append(seg)
            pos += len(raw)
    z = [round(v if v is not None else 0.0, 3) for v in zs]
    total = sum(len(w) for w in walls)
    step = max(1, math.ceil(total / limit)) if total else 1
    keep = [(i, s) for i, w in enumerate(walls) if i % step == 0 for s in w]
    flat = [v for i, s in keep for v in (*s, z[i])]
    public = {"count": len(z), "z": z, "width": round(max(0.45, height * step), 2),
              "walls": {"count": len(keep), "segs": _pack16(flat),
                        "layer": base64.b64encode(struct.pack(f"<{len(keep)}H", *(min(i, 65535) for i, _ in keep))).decode()}}
    return public, starts


def layer_paths(gcode: str, start: int, end: Optional[int], state: Tuple[float, float, float, bool, float, int], z: float) -> Dict[str, Any]:
    """One layer's extruding moves, from where layer_index found it: segs packed as support_lines packs them,
    and `kinds` (base64 bytes): WALL, INNER, INFILL, SUPPORT or OTHER for each."""
    walk = _Walk(state)
    flat: List[float] = []
    kinds = bytearray()
    with open(gcode, "rb") as f:
        f.seek(start)
        chunk = f.read(-1 if end is None else max(0, end - start))
    for line in chunk.decode("ascii", "replace").splitlines():
        seg = walk.step(line)
        if seg:
            flat.extend((*seg, z))
            kinds.append(walk.kind)
    return {"count": len(kinds), "segs": _pack16(flat), "kinds": base64.b64encode(bytes(kinds)).decode()}


if __name__ == "__main__":
    # the printer's Moonraker component runs this in its own process: python3 gcode_layers.py <file> -> layer_index's JSON
    import json
    import sys

    json.dump(layer_index(sys.argv[1])[0], sys.stdout, separators=(",", ":"))
