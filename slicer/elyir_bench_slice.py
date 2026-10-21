"""Slicing without the settings: a purpose and a spool in, G-code out. See docs/slicer.md.

The engine is OrcaSlicer's command line. Nothing here knows how to slice; it knows which few settings
a person actually decides, and turns those into changes on top of presets they already trust:

  printer   what the machine is (its Orca preset, the plate on it)   never asked, never shown
  spool     what's loaded (material, colour, which slot)              known from the filament unit
  purpose   what the print is for (draft, everyday, display, strong)  the one question
  supports  normal, tree or off (auto: the preset's own kind)         the printer's usual unless someone says no

Every change is recorded with the value it replaced and why, so the Advanced door can show exactly
what was decided. No aiohttp in this file: the service imports it, and so do the tests.
"""
from __future__ import annotations

import base64
import collections
import contextlib
import glob
import json
import math
import os
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MODEL_TYPES = {".stl", ".obj", ".step", ".stp"}
UPLOAD_TYPES = MODEL_TYPES | {".3mf"}   # a 3MF is read as its parts, each kept as an STL (three_mf_parts)
# Every binary STL written here starts with a byte above 127: Orca (admesh) calls a file text if the first 100
# bytes are all below 128, which a small model with a zeroed header can be ("Something is syntactically very
# wrong with this ASCII STL!").
STL_HEADER = (b"\xffelyir-bench" + b" " * 80)[:80]

# ── purposes ─────────────────────────────────────────────────────────────────
# Each is a handful of Orca process keys over the printer's base process. Values are strings, the way
# Orca's own JSON holds them. The reasons are written for the Advanced door, not for the panel.

PURPOSES: Dict[str, Dict[str, Any]] = {
    "draft": {
        "label": "Quick draft",
        "summary": "Fast and light. Checking a fit, or a first try.",
        "set": [
            ("layer_height", "0.28", "Thicker layers: fewer of them, so it prints faster"),
            ("wall_loops", "2", "Two walls are enough to check a shape"),
            ("sparse_infill_density", "10%", "Little inside: it only has to hold its shape"),
            ("top_shell_layers", "5", "Enough solid layers on top to close over the light infill at the thicker layer height"),
            ("bottom_shell_layers", "3", "Fewer solid layers underneath at the thicker layer height"),
        ],
    },
    "everyday": {
        "label": "Everyday",
        "summary": "Good all round. The one to pick when unsure.",
        "set": [
            ("layer_height", "0.2", "The printer's standard layer height"),
            ("wall_loops", "3", "A third wall for parts that get handled"),
            ("sparse_infill_density", "15%", "Enough inside for everyday use"),
        ],
    },
    "display": {
        "label": "Looks best",
        "summary": "Fine layers and a tidy seam, for things people look at.",
        "set": [
            ("layer_height", "0.12", "Thinner layers hide the steps on curves"),
            ("wall_loops", "3", "Extra walls keep the outside smooth"),
            ("sparse_infill_density", "10%", "It's for looking at, so little inside"),
            ("top_shell_layers", "7", "More layers on top keep the same top thickness at fine layers"),
            ("bottom_shell_layers", "5", "More layers underneath at fine layers"),
            ("seam_position", "aligned", "The seam lines up in one place instead of scattering"),
        ],
    },
    "strong": {
        "label": "Strong",
        "summary": "For parts that carry load: brackets, mounts, tools.",
        "set": [
            ("layer_height", "0.2", "Standard layers bond well"),
            ("wall_loops", "5", "Walls carry most of the load, so more of them"),
            ("sparse_infill_density", "40%", "Denser inside"),
            ("sparse_infill_pattern", "gyroid", "Gyroid is strong in every direction"),
            ("top_shell_layers", "5", "Thicker solid top"),
            ("bottom_shell_layers", "5", "Thicker solid bottom"),
        ],
    },
}

# The kind is the person's (design/supports/, A): normal comes off in blocks, tree touches in a few places. auto
# keeps whatever the printer's process preset says (Workshop's is normal), for apps that only know auto or off.
SUPPORTS: Dict[str, List[Tuple[str, str, str]]] = {
    "auto": [
        ("enable_support", "1", "Supports wherever an overhang needs one, and nowhere else"),
    ],
    "normal": [
        ("enable_support", "1", "Supports wherever an overhang needs one, and nowhere else"),
        ("support_type", "normal(auto)", "Normal supports: blocks under each overhang that come off in one piece"),
    ],
    "tree": [
        ("enable_support", "1", "Supports wherever an overhang needs one, and nowhere else"),
        ("support_type", "tree(auto)", "Tree supports: branches that touch the part in a few places"),
    ],
    "off": [
        ("enable_support", "0", "Asked for no supports"),
    ],
}


# ── what a person may change ─────────────────────────────────────────────────
# design/edit-settings/, C: a short list, not Orca's hundreds of keys, each with the control it gets and a range the
# slicer is known to take. A change is for this print, or kept for every print of one purpose on this printer (the
# app keeps those). Temperatures, retraction, speeds and the like stay the spool's and the printer's.
# default: what Orca uses when a preset leaves the key out. choices: (Orca's value, what people call it).

EDITABLE: Dict[str, Dict[str, Any]] = {
    "layer_height": {"kind": "number", "min": 0.08, "max": 0.32, "step": 0.04, "unit": "mm", "default": "0.2",
                     "help": "Thinner layers look smoother on curves and take longer."},
    "wall_loops": {"kind": "number", "min": 1, "max": 10, "step": 1, "default": "2",
                   "help": "Rings around the outside. More are stronger and take longer."},
    "sparse_infill_density": {"kind": "number", "min": 0, "max": 100, "step": 5, "unit": "%", "default": "15%",
                              "help": "How full the inside is. Fuller is stronger and heavier."},
    "sparse_infill_pattern": {"kind": "choice", "default": "crosshatch",
                              "choices": [["crosshatch", "Crosshatch"], ["grid", "Grid"], ["gyroid", "Gyroid"], ["lightning", "Lightning"]],
                              "help": "The shape inside. Gyroid is strong every way; Lightning is the lightest, only holding up the top."},
    "top_shell_layers": {"kind": "number", "min": 0, "max": 12, "step": 1, "unit": "layers", "default": "4",
                         "help": "Solid layers that close the top."},
    "bottom_shell_layers": {"kind": "number", "min": 0, "max": 12, "step": 1, "unit": "layers", "default": "3",
                            "help": "Solid layers on the bottom."},
    "ironing_type": {"kind": "choice", "default": "no ironing", "choices": [["no ironing", "Off"], ["top", "On"]],
                     "help": "Goes over the top surface again to make it smooth. Adds time."},
    "seam_position": {"kind": "choice", "default": "aligned",
                      "choices": [["aligned", "Lined up"], ["nearest", "Nearest"], ["random", "Scattered"], ["back", "At the back"]],
                      "help": "Where each layer starts and ends, which leaves a faint line."},
    "support_on_build_plate_only": {"kind": "choice", "default": "0", "choices": [["0", "Everywhere"], ["1", "From the plate only"]],
                                    "help": "Only supports that stand on the plate, none standing on the part itself."},
}


def edit_value(key: str, value: Any) -> str:
    """A person's value for an editable setting, the way Orca's JSON holds it ("4", "0.16", "25%"), or ValueError
    saying what's wrong."""
    spec = EDITABLE.get(key)
    if spec is None:
        raise ValueError(f"{key} can't be changed here")
    text = str(value).strip()
    if spec["kind"] == "choice":
        if text not in [c[0] for c in spec["choices"]]:
            raise ValueError(f"{key} must be one of {', '.join(c[0] for c in spec['choices'])}")
        return text
    try:
        n = float(text.rstrip("%"))
    except ValueError:
        raise ValueError(f"{key} must be a number") from None
    lo, hi, step = spec["min"], spec["max"], spec["step"]
    if not lo - 1e-9 <= n <= hi + 1e-9 or abs((n - lo) / step - round((n - lo) / step)) > 1e-6:
        raise ValueError(f"{key} must be {lo:g} to {hi:g} in steps of {step:g}")
    out = f"{round(n, 4):g}"
    return out + "%" if spec.get("unit") == "%" else out


def edit_values(process: Dict[str, Any]) -> Dict[str, str]:
    """What a process will print with, for every editable setting."""
    return {k: str(process.get(k, spec["default"])) for k, spec in EDITABLE.items()}


# ── materials ────────────────────────────────────────────────────────────────
# What a material needs whoever's spool it is, over the filament preset: (preset, key, value, why). PETG strings:
# hot, slow to stop oozing, and a straight lift pulls a thread. We saw fine strings across the vent on Workshop,
# 3 October 2026 (240 °C, 0.8 mm at 30 mm/s, no pressure advance, travel straight across the opening).

MATERIALS: Dict[str, List[Tuple[str, str, str, str]]] = {
    "PETG": [
        ("filament", "nozzle_temperature", "235", "A little cooler than the spool's preset: PETG oozes and strings when it's hot"),
        ("filament", "filament_retraction_length", "1", "Pulls back a little more before each travel, so less oozes out"),
        ("filament", "filament_retraction_speed", "40", "Pulls back faster, before the nozzle starts to drip"),
        ("filament", "filament_z_hop_types", "Spiral Lift", "Lifts in a small spiral instead of straight up, which can draw a thread"),
        ("process", "reduce_crossing_wall", "1", "Travels around over the part instead of straight across open space, where strings form"),
    ],
}

# ── calibration prints ────────────────────────────────────────────────────────
# Pressure advance (Klipper's TUNING_TOWER method): a hollow square tower, one wall, corners taken slowly so the
# bulge or gap at each corner shows; pressure advance rises with height, 0.01 for every tick on the front face.
# The person counts ticks to where the corners look best. design: the start of "Tune this spool".

PA_STEP_MM = 4.0          # a tick every 4 mm
PA_PER_TICK = 0.01        # TUNING_TOWER FACTOR = PA_PER_TICK / PA_STEP_MM per mm
PA_TICKS = 8              # 0 to 0.08: Workshop's direct drive sits around 0.02 to 0.06

TESTS: Dict[str, Dict[str, Any]] = {
    "pressure_advance": {
        "set": [
            ("process", "wall_loops", "1", "One wall, so each corner shows what pressure advance does"),
            ("process", "sparse_infill_density", "0%", "Hollow: only the wall matters"),
            ("process", "top_shell_layers", "0", "Open at the top"),
            ("process", "bottom_shell_layers", "2", "A thin floor to hold it together"),
            ("process", "outer_wall_speed", "100", "Fast walls make the corners tell"),
            ("process", "inner_wall_speed", "100", "Fast walls make the corners tell"),
            ("process", "default_acceleration", "500", "Gentle acceleration, the way Klipper's test asks"),
            ("process", "outer_wall_acceleration", "500", "Gentle acceleration, the way Klipper's test asks"),
            ("process", "inner_wall_acceleration", "500", "Gentle acceleration, the way Klipper's test asks"),
            # Orca writes each feature's jerk as Klipper's SQUARE_CORNER_VELOCITY, which would undo the test's slow corners
            *[("process", k, "1", "Corners taken slowly, as in Klipper's test, so pressure advance shows")
              for k in ("default_jerk", "outer_wall_jerk", "inner_wall_jerk", "infill_jerk", "top_surface_jerk",
                        "initial_layer_jerk", "travel_jerk")],
            ("process", "brim_type", "no_brim", "No brim to hide the bottom corners"),
            ("process", "enable_support", "0", "Nothing to support"),
            ("filament", "enable_pressure_advance", "0", "The tower sets pressure advance itself, layer by layer"),
        ],
        # after PRINT_START: corners slow, then pressure advance by height
        "after_start": [
            "SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=1 ACCEL=500",
            f"TUNING_TOWER COMMAND=SET_PRESSURE_ADVANCE PARAMETER=ADVANCE START=0 FACTOR={PA_PER_TICK / PA_STEP_MM:g}",
        ],
    },
}


# ── 3MF: read as its parts (not as a project) ─────────────────────────────────
# What a 3MF from MakerWorld, Printables, Bambu Studio or Orca carries is read as the parts in it, each with
# how many times it's placed and turned as the designer turned it. Its print settings, painting and plate
# layout are left behind: Elyir Bench decides those. Each part goes on as an STL, so everything after is the same.

UNITS = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
NOT_A_PART = {"modifier_part", "negative_part", "support_blocker", "support_enforcer"}


def _matrix(text: Optional[str]) -> List[List[float]]:
    """A 3MF transform ("m00 m01 m02 m10 ... m32", row vectors: p' = p * M) as a 4 x 4 matrix."""
    v = [float(x) for x in (text or "1 0 0 0 1 0 0 0 1 0 0 0").split()]
    return [[v[0], v[1], v[2], 0.0], [v[3], v[4], v[5], 0.0], [v[6], v[7], v[8], 0.0], [v[9], v[10], v[11], 1.0]]


def _mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def three_mf_parts(path: str) -> List[Dict[str, Any]]:
    """The parts of a 3MF: [{name, tris, copies, filaments}], tris in mm as placed (turned as the designer turned
    them), filaments each triangle's filament (1-based: what it's painted, else its part's, else its object's, else 1).
    Follows components into other model files (3MF production extension, as Bambu Studio and Orca write)."""
    with zipfile.ZipFile(path) as z:
        names_in = set(z.namelist())
        root_path = "3D/3dmodel.model"
        if "_rels/.rels" in names_in:
            for rel in ET.fromstring(z.read("_rels/.rels")):
                if rel.get("Type", "").endswith("/3dmodel"):
                    root_path = rel.get("Target", root_path).lstrip("/")
        models: Dict[str, Any] = {}

        def load(p: str):
            p = p.lstrip("/")
            if p not in models:
                models[p] = ET.fromstring(z.read(p))
            return models[p]

        root = load(root_path)
        pre = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        k = UNITS.get(root.get("unit", "millimeter"), 1.0)
        # Bambu Studio / Orca: object names, and which volumes are modifiers rather than the part
        names: Dict[str, str] = {}
        skip: set = set()
        filament: Dict[str, int] = {}            # object or part id → its filament
        if "Metadata/model_settings.config" in names_in:
            for obj in ET.fromstring(z.read("Metadata/model_settings.config")).iter("object"):
                nm = next((m.get("value") for m in obj.findall("metadata") if m.get("key") == "name"), None)
                if nm:
                    names[obj.get("id")] = nm
                for el in (obj, *obj.iter("part")):
                    f = next((m.get("value") for m in el.findall("metadata") if m.get("key") == "extruder"), "")
                    if f.isdigit() and int(f) > 0:
                        filament[el.get("id")] = int(f)
                for part in obj.iter("part"):
                    if part.get("subtype") in NOT_A_PART:
                        skip.add(part.get("id"))

        def objects(model) -> Dict[str, Any]:
            return {o.get("id"): o for o in model.iter(f"{pre}object")}

        cache: Dict[str, Dict[str, Any]] = {}

        def tris_of(model_path: str, oid: str, m: List[List[float]], depth: int = 0, fil: int = 1) -> List[Tuple[List[List[float]], int]]:
            if depth > 8:
                return []
            if model_path not in cache:
                cache[model_path] = objects(load(model_path))
            obj = cache[model_path].get(oid)
            if obj is None:
                return []
            fil = filament.get(oid, fil)
            out: List[Tuple[List[List[float]], int]] = []
            mesh = obj.find(f"{pre}mesh")
            if mesh is not None:
                vs = []
                for v in mesh.iter(f"{pre}vertex"):
                    x, y, zz = float(v.get("x")), float(v.get("y")), float(v.get("z"))
                    vs.append([x * m[0][j] + y * m[1][j] + zz * m[2][j] + m[3][j] for j in range(3)])
                for t in mesh.iter(f"{pre}triangle"):
                    try:
                        out.append(([vs[int(t.get("v1"))], vs[int(t.get("v2"))], vs[int(t.get("v3"))]],
                                    paint_state(t.get("paint_color")) or fil))
                    except (IndexError, TypeError, ValueError):
                        continue
            for c in obj.iter(f"{pre}component"):
                cid = c.get("objectid")
                if cid in skip:
                    continue
                cpath = next((v for kk, v in c.attrib.items() if kk.endswith("}path")), None) or model_path
                out += tris_of(cpath.lstrip("/"), cid, _mul(_matrix(c.get("transform")), m), depth + 1, fil)
            return out

        groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        build = root.find(f"{pre}build")
        for item in (build if build is not None else []):
            if item.tag != f"{pre}item" or item.get("printable") == "0":
                continue
            oid = item.get("objectid")
            m = _matrix(item.get("transform"))
            turn = tuple(round(m[i][j], 3) for i in range(3) for j in range(3))
            key = (oid, turn)
            if key in groups:
                groups[key]["copies"] += 1
                continue
            pairs = tris_of(root_path, oid, m)
            if not pairs:
                continue
            tris = [t for t, _ in pairs]
            if k != 1.0:
                tris = [[[c * k for c in v] for v in t] for t in tris]
            obj = cache[root_path].get(oid)
            name = names.get(oid) or (obj.get("name") if obj is not None else None) or f"{Path(path).stem} {len(groups) + 1}"
            groups[key] = {"name": name, "tris": tris, "copies": 1, "filaments": [f for _, f in pairs]}
        parts = list(groups.values())
        if "Metadata/model_settings.config" not in names_in:
            parts = _assemblies(parts, Path(path).stem)
        return parts


def _assemblies(parts: List[Dict[str, Any]], stem: str) -> List[Dict[str, Any]]:
    """Bodies that overlap or touch are one thing: a CAD export (Fusion and others) writes each body of a part
    as its own object. Only for 3MFs without Bambu/Orca's own object list, which says what belongs together."""
    def box(p):
        vs = [v for t in p["tris"] for v in t]
        return [min(v[i] for v in vs) for i in range(3)], [max(v[i] for v in vs) for i in range(3)]
    single = [p for p in parts if p["copies"] == 1]
    boxes = [box(p) for p in single]
    up = list(range(len(single)))

    def find(i):
        while up[i] != i:
            up[i] = up[up[i]]
            i = up[i]
        return i
    for i in range(len(single)):
        for j in range(i + 1, len(single)):
            a, b = boxes[i], boxes[j]
            if all(a[0][d] <= b[1][d] + 0.05 and b[0][d] <= a[1][d] + 0.05 for d in range(3)):
                up[find(i)] = find(j)
    together: Dict[int, List[int]] = {}
    for i in range(len(single)):
        together.setdefault(find(i), []).append(i)
    out = [p for p in parts if p["copies"] != 1]
    for members in together.values():
        if len(members) == 1:
            out.append(single[members[0]])
        else:
            out.append({"name": stem if len(together) == 1 else f"{stem} {len(out) + 1}",
                        "tris": [t for i in members for t in single[i]["tris"]], "copies": 1,
                        "filaments": [f for i in members for f in single[i].get("filaments", [])]})
    return out


def pa_tower_stl(path: str, side: float = 50.0) -> None:
    """The pressure advance tower: a 50 mm square block (sliced hollow, one wall) with a small tick on the
    front face every PA_STEP_MM, PA_TICKS of them, so the height can be read without calipers."""
    h = PA_STEP_MM * PA_TICKS + 2
    boxes = [((0, 0, 0), (side, side, h))]
    for k in range(1, PA_TICKS + 1):
        z = k * PA_STEP_MM
        boxes.append(((side / 2 - 3, -1.2, z - 0.4), (side / 2 + 3, 0.2, z + 0.4)))
    F = [(0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3), (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6)]
    tris = []
    for (x0, y0, z0), (x1, y1, z1) in boxes:
        V = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        tris += [[V[i] for i in f] for f in F]
    write_stl(path, tris)


def write_stl(path: str, tris) -> None:
    """Triangles as binary STL, each with its real normal. Orca (admesh) decides binary or text from the 128
    bytes after the header: all below 128 reads as text ("Something is syntactically very wrong with this
    ASCII STL!"), which zero normals and small coordinates can be. A unit normal always has a byte above 127."""
    out = bytearray(STL_HEADER + struct.pack("<I", len(tris)))
    for t in tris:
        n, _ = _normal_area(t)
        out += struct.pack("<12fH", *(n or (0.0, 0.0, 1.0)), *[c for v in t for c in v], 0)
    with open(path, "wb") as f:
        f.write(out)


def after_start(gcode: str, lines: List[str]) -> bool:
    """Put lines right after the PRINT_START call (a calibration print's own commands). False if there's none."""
    tmp = gcode + ".tmp"
    done = False
    with open(gcode, errors="replace") as src, open(tmp, "w") as dst:
        for line in src:
            dst.write(line)
            if not done and line.startswith("PRINT_START"):
                dst.write("\n".join(lines) + "\n")
                done = True
    os.replace(tmp, gcode)
    return done


# What each changed key is called on "Every setting". The Orca key is shown beside it in small type.
LABELS: Dict[str, str] = {
    "layer_height": "Layer height", "wall_loops": "Walls", "sparse_infill_density": "Inside",
    "sparse_infill_pattern": "Inside pattern", "top_shell_layers": "Solid top", "bottom_shell_layers": "Solid bottom",
    "seam_position": "Seam", "enable_support": "Supports", "support_type": "Support style",
    "filament_colour": "Color", "curr_bed_type": "Plate",
    "orientation": "Lying", "scale": "Size", "skirt_loops": "Loop around the part",
    "gcode_label_objects": "Parts named in the file", "exclude_object": "Parts can be skipped",
    "nozzle_temperature": "Nozzle", "filament_retraction_length": "Pull back", "filament_retraction_speed": "Pull-back speed",
    "filament_z_hop_types": "Lift", "reduce_crossing_wall": "Travel",
    "brim_type": "Brim", "ironing_type": "Smooth top", "support_on_build_plate_only": "Supports",
    "change_filament_gcode": "Color change", "enable_prime_tower": "Tower", "purge_in_prime_tower": "Purge in the tower",
    "print_sequence": "Order",
}


# ── presets ──────────────────────────────────────────────────────────────────

class PresetError(Exception):
    pass


def vendor_of(root: str, path: str) -> str:
    """The vendor a bundled preset belongs to: Voron for <profiles>/Voron/machine/x.json. A person's own folders
    (machine/x.json, or flat) have none: their parent is looked up by name alone."""
    parts = os.path.relpath(path, root).split(os.sep)
    return parts[0] if len(parts) >= 3 and parts[1] in ("machine", "process", "filament") else ""


class Presets:
    """Orca presets by name, from a list of folders. The first folder that has a name wins, so put
    the person's own presets before the bundled ones. A parent is looked up in its child's vendor first."""

    def __init__(self, roots: List[str]):
        self.by_name: Dict[str, Dict[str, Any]] = {}
        # The same base name is in many vendors' folders (fdm_klipper_common is in Custom, Voron, Vzbot...), with
        # different values. Orca looks a parent up in the child's own vendor, so this does too (vendor_of).
        self.by_vendor: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.vendor: Dict[int, str] = {}
        for root in roots:
            root = os.path.expanduser(root)
            for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
                try:
                    with open(path) as f:
                        d = json.load(f)
                except (OSError, ValueError):
                    continue
                if isinstance(d, dict) and isinstance(d.get("name"), str):
                    self.by_name.setdefault(d["name"], d)
                    vendor = vendor_of(root, path)
                    self.vendor[id(d)] = vendor
                    if vendor:
                        self.by_vendor.setdefault((vendor, d["name"]), d)

    def resolve(self, name: str) -> Dict[str, Any]:
        """The preset with every parent folded in, nearest last."""
        chain, seen = [], set()
        vendor = ""
        while name:
            if name in seen:
                raise PresetError(f"preset {name!r} inherits from itself")
            seen.add(name)
            d = self.by_vendor.get((vendor, name)) or self.by_name.get(name)
            if d is None:
                raise PresetError(f"no preset called {name!r}")
            chain.append(d)
            vendor = self.vendor.get(id(d)) or vendor
            name = d.get("inherits") or ""
        flat: Dict[str, Any] = {}
        for d in reversed(chain):
            flat.update(d)
        flat.pop("inherits", None)
        return flat


LIBRARY = "OrcaFilamentLibrary"
COMMON_MATERIALS = ("PLA", "PETG", "ABS", "ASA", "TPU")


def library_filaments(presets: "Presets") -> List[Dict[str, str]]:
    """Orca's own filament library, the ones a person picks (any printer): {preset, name, brand, material}."""
    out = []
    for name, d in presets.by_name.items():
        if d.get("type") != "filament" or d.get("instantiation") != "true" or presets.vendor.get(id(d)) != LIBRARY:
            continue
        try:
            flat = presets.resolve(name)
        except PresetError:
            continue
        first = lambda v: (v[0] if isinstance(v, list) and v else v) or ""
        out.append({"preset": name, "name": re.sub(r"\s*@System$", "", name), "brand": str(first(flat.get("filament_vendor"))),
                    "material": str(first(flat.get("filament_type"))).upper()})
    return sorted(out, key=lambda f: (f["brand"] != "Generic", f["brand"].lower(), f["name"].lower()))


def search_filaments(library: List[Dict[str, str]], q: str = "", material: str = "", limit: int = 40) -> List[Dict[str, str]]:
    """Every word of q in its brand, name or material; a brand's own name first ("polymaker" finds PolyTerra too)."""
    words = q.lower().split()
    out = [f for f in library if (not material or f["material"] == material.upper())
           and all(w in f"{f['brand']} {f['name']} {f['material']}".lower() for w in words)]
    # a name that starts with what was typed, then the everyday materials, before a brand's specialty ones
    out.sort(key=lambda f: (not (words and f["name"].lower().startswith(words[0])), f["material"] not in COMMON_MATERIALS))
    return out[:limit]


def cli_preset(kind: str, flat: Dict[str, Any], printer_name: str) -> Dict[str, Any]:
    """What Orca's command line accepts. It treats a non-system preset as named after its parent,
    and checks a process or filament lists the printer by that name, so: system, and compatible
    with this printer only."""
    out = dict(flat)
    out["type"] = kind
    out["from"] = "system"
    out["name"] = flat.get("name") or f"elyir-bench {kind}"
    if kind != "machine":
        out["compatible_printers"] = [printer_name]
        out["compatible_printers_condition"] = ""
        out["compatible_prints"] = []
        out["compatible_prints_condition"] = ""
    return out


# ── a request, turned into settings ──────────────────────────────────────────

CHANGE_SECONDS = 105                     # the unit's in-print change on the main test printer, 18 October 2026


@dataclass
class Printer:
    id: str
    name: str
    machine: str                         # Orca machine preset
    process: str                         # the base process every purpose starts from
    materials: Dict[str, str]            # material → Orca filament preset
    plate: Optional[str] = None          # curr_bed_type: which plate temperature Orca uses
    plate_why: Optional[str] = None      # why that plate, when it isn't simply the plate on the printer
    moonraker: Optional[str] = None      # where "send to printer" goes
    tools: int = 1                       # filament slots; a slot above this is refused
    skirt_loops: int = 0                 # a loop around the part re-primes the nozzle after PRINT_START's wipe
    presets: List[str] = field(default_factory=list)   # its own preset folders, before the slicer's shared ones
    start_macro: bool = False            # Elyir Bench's start macro is included: its two lines go around the start G-code
    learned: bool = False                # its profile was learned from its own prints (docs/slicer-profile.md)
    purge: Optional[str] = None          # "chute": it pushes the old color out off the plate at a change (design/multi-color/)
    change_seconds: int = CHANGE_SECONDS # one color change by its filament unit, start to finish

    @property
    def unit(self) -> bool:
        return self.tools > 1

    @classmethod
    def from_config(cls, pid: str, d: Dict[str, Any]) -> "Printer":
        return cls(id=pid, name=d.get("name", pid), machine=d["machine"], process=d["process"],
                   materials={k.upper(): v for k, v in d["materials"].items()}, plate=d.get("plate"),
                   plate_why=d.get("plate_why"), moonraker=d.get("moonraker"), tools=int(d.get("tools", 1)),
                   skirt_loops=int(d.get("skirt_loops", 0)), presets=list(d.get("presets", [])),
                   start_macro=d.get("start_macro") is True, learned=isinstance(d.get("learned"), dict),
                   purge="chute" if d.get("purge") == "chute" else None,
                   change_seconds=int(d.get("change_seconds", CHANGE_SECONDS)))


# ── several colors (design/multi-color/, B) ──────────────────────────────────
# A plate prints with one spool per color. Each comes from a slot of the filament unit or is swapped in by
# hand (the print pauses for it). Orca writes every change as ELYIR_PURGE + T<filament>; assign_spools turns
# that into the slot's T, or an M600 for a swap by hand.

# chute: the printer pushes the old color out off the plate | tower: a tower beside the model takes it |
# both: the chute takes it and a thin tower settles the nozzle | swap: pushed through at a swap by hand
PURGES = ("chute", "tower", "both", "swap")
MAX_SPOOLS = 16
CHANGE_GCODE = "ELYIR_PURGE LENGTH=[flush_length] FROM=[previous_extruder] TO=[next_extruder]\nT[next_extruder]"


@dataclass
class Spool:
    material: str = "PLA"
    color: Optional[str] = None          # "#RRGGBB"
    filament: Optional[str] = None       # an Orca filament preset by name, instead of the printer's own for the material
    slot: Optional[int] = None           # 0-based slot of the filament unit
    hand: bool = False                   # swapped in by hand: the print pauses for it

    def preset(self, printer: Printer) -> str:
        return self.filament or printer.materials[self.material.upper()]


def purges(printer: Printer) -> List[str]:
    """What Between colors offers on this printer, its usual first."""
    if not printer.unit:
        return ["swap", "tower", "both"]
    return ["chute", "tower", "both"] if printer.purge == "chute" else ["tower"]


def default_purge(printer: Printer) -> str:
    if not printer.unit:
        return "swap"
    return "chute" if printer.purge == "chute" else "tower"


def spool_problems(printer: Printer, spools: List["Spool"], purge: Optional[str]) -> List[str]:
    out: List[str] = []
    if len(spools) > MAX_SPOOLS:
        out.append(f"at most {MAX_SPOOLS} colors on one plate")
    slots: Dict[int, int] = {}
    for k, sp in enumerate(spools, 1):
        if sp.material.upper() not in printer.materials and not sp.filament:
            out.append(f"color {k}: {printer.name} has no settings for {sp.material}; it knows {', '.join(printer.materials)}")
        if sp.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", sp.color):
            out.append(f"color {k}: color must look like #RRGGBB")
        if sp.slot is not None:
            if not printer.unit:
                out.append(f"color {k}: {printer.name} has no filament unit, so no slots")
            elif not 0 <= sp.slot < printer.tools:
                out.append(f"color {k}: slot must be 1 to {printer.tools}")
            elif sp.slot in slots and not sp.hand:
                out.append(f"colors {slots[sp.slot]} and {k} both come from slot {sp.slot + 1}")
            else:
                slots[sp.slot] = k
    if purge is not None:
        if purge not in PURGES:
            out.append(f"purge must be one of {', '.join(PURGES)}")
        elif purge == "chute" and printer.purge != "chute" or purge == "both" and printer.unit and printer.purge != "chute":
            out.append(f"{printer.name} has no purge chute")
        elif purge == "swap" and printer.unit and any(not sp.hand for sp in spools[1:]):
            out.append("At the swap is for colors swapped by hand; the unit's changes need the chute or a tower")
    return out


@dataclass
class Request:
    purpose: str = "everyday"
    supports: str = "auto"
    material: str = "PLA"
    filament: Optional[str] = None       # an Orca filament preset by name, instead of the printer's own for the material
    color: Optional[str] = None          # "#RRGGBB"
    slot: Optional[int] = None           # 0-based filament slot; None = the printer's first
    orient: bool = False                 # models from the web usually arrive the right way up
    test: Optional[str] = None           # a calibration print instead of a model: "pressure_advance"
    kept: Dict[str, str] = field(default_factory=dict)       # the person's own for this purpose (design/edit-settings/, C)
    settings: Dict[str, str] = field(default_factory=dict)   # the person's, for this print only
    spools: List[Spool] = field(default_factory=list)        # several colors: one per color, in Orca's filament order
    purge: Optional[str] = None          # PURGES; None = the printer's usual (default_purge)
    one_after_other: bool = False        # each part finished before the next starts: one change per part

    def __post_init__(self) -> None:
        if self.spools:                  # the first color is the plate's material, color and slot as before
            first = self.spools[0]
            self.material, self.color, self.filament, self.slot = first.material, first.color, first.filament, first.slot

    @property
    def colors(self) -> int:
        return max(1, len(self.spools))

    def problems(self, printer: Printer) -> List[str]:
        out = []
        if self.purpose not in PURPOSES:
            out.append(f"purpose must be one of {', '.join(PURPOSES)}")
        if self.supports not in SUPPORTS:
            out.append(f"supports must be one of {', '.join(SUPPORTS)}")
        if self.material.upper() not in printer.materials and not self.filament:
            out.append(f"{printer.name} has no settings for {self.material}; it knows {', '.join(printer.materials)}")
        if self.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.color):
            out.append("color must look like #RRGGBB")
        if self.slot is not None and not 0 <= self.slot < printer.tools:
            out.append(f"slot must be 1 to {printer.tools}")
        if self.test is not None and self.test not in TESTS:
            out.append(f"test must be one of {', '.join(TESTS)}")
        if self.spools or self.purge is not None:
            out += spool_problems(printer, self.spools, self.purge)
        for given in (self.kept, self.settings):
            if not isinstance(given, dict):
                out.append("settings must be an object of setting and value")
                continue
            for k, v in given.items():
                if k == "brim_type" and v in (*BRIMS.values(), "auto_brim"):
                    continue                      # from before brims were per part: the parts' default (brim_default)
                try:
                    edit_value(k, v)
                except ValueError as e:
                    out.append(str(e))
        return out


MAX_COPIES = 200
FIT_CAP = 100                            # arranging more takes a Pi too long; "Fill the plate" says 100+


@dataclass
class Part:
    """One thing on the plate (design/plate/, A): a model and how many of it, every copy the same size
    and the same way up. Purpose, spool and supports belong to the whole plate (Request)."""
    model: str                           # the uploaded file
    copies: int = 1
    scale: float = 1.0                   # 0.84 = 84%: a model too big for the bed, made to fit
    lay: str = "file"                    # file: as the model arrived | flat: on its best side | side: on `down`
    lying: Optional[Dict[str, Any]] = None   # lying(), when the file could be measured
    down: Optional[List[float]] = None   # lay "side": the outward normal of the side the person put down
    brim: str = "auto"                   # auto: picked from its shape (brim_pick) | none | ears | all (design/brim/, A)
    spool: int = 0                       # which of the plate's colors it prints in (Request.spools)

    @property
    def project(self) -> bool:
        """A 3MF that brings its own colors, sliced as it is (three_mf_colors)."""
        return self.model.lower().endswith(".3mf")

    @property
    def name(self) -> str:
        return os.path.basename(self.model)

    def problems(self) -> List[str]:
        out = []
        if not 1 <= self.copies <= MAX_COPIES:
            out.append(f"copies must be 1 to {MAX_COPIES}")
        if not 0.05 <= self.scale <= 4:
            out.append("scale must be between 0.05 and 4")
        if self.lay not in ("file", "flat", "side"):
            out.append("lay must be file, flat or side")
        if self.brim not in ("auto", *BRIMS):
            out.append("brim must be auto, none, ears or all")
        if self.lay == "side" and not (isinstance(self.down, list) and len(self.down) == 3
                                       and all(isinstance(x, (int, float)) for x in self.down)
                                       and 0.9 < math.sqrt(sum(x * x for x in self.down)) < 1.1):
            out.append("lay side needs down: the side's normal, three numbers")
        plain = Path(self.model).suffix.lower() in (".stl", ".obj")
        if self.scale != 1 and not plain:
            out.append("only STL and OBJ models can be resized")
        if self.lay in ("flat", "side") and not plain:
            out.append("only STL and OBJ models can be turned")
        if self.project and self.copies != 1:
            out.append("a 3MF with its own colors prints once")
        if self.spool < 0:
            out.append("spool must be 0 or more")
        return out


@dataclass
class Change:
    key: str
    value: Any
    was: Any
    why: str
    source: str                          # purpose | supports | spool | printer | model
    label: Optional[str] = None          # when the key's own label isn't enough (which part, on a plate of several)

    def as_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label or LABELS.get(self.key, self.key), "value": self.value,
                "was": self.was, "why": self.why, "source": self.source}


@dataclass
class Plan:
    """The presets Orca gets, and every change made to get there."""
    machine: Dict[str, Any]
    process: Dict[str, Any]
    filament: Dict[str, Any]
    changes: List[Change] = field(default_factory=list)
    values: Dict[str, str] = field(default_factory=dict)       # every editable setting, as it will print
    before: Dict[str, str] = field(default_factory=dict)       # the same, before the person's own changes
    more: List[Dict[str, Any]] = field(default_factory=list)   # the second color's filament on, when there are several

    @property
    def filaments(self) -> List[Dict[str, Any]]:
        return [self.filament, *self.more]


def _set(preset: Dict[str, Any], key: str, value: str, why: str, source: str, changes: List[Change],
         per_filament: bool = False) -> None:
    was = preset.get(key)
    new: Any = [value] if per_filament or isinstance(was, list) else value   # filament keys are lists
    if was == new:
        return
    preset[key] = new
    changes.append(Change(key, new, was, why, source))


# Elyir Bench's start macro (printer/klipper/elyir-bench.cfg, docs/start-macro.md), on a printer whose printer.json says
# "start_macro": true (the installer's `elyir-bench startmacro on`). Its first line heats while the file is paused, so
# Cancel works; the person's start G-code then runs exactly as it is; the last line says it's done. The same two
# lines as the printer's Finish setting up card shows (printer/printer_intent.py, docs/setup-card.md).
START_MACRO_BEFORE = ("ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] "
                      "EXTRUDER=[nozzle_temperature_initial_layer]")
START_MACRO_AFTER = "ELYIR_BENCH_PRINT_START_DONE"


def wrap_start_gcode(start: str) -> str:
    """The machine's start G-code between the start macro's two lines, unchanged. Already there (put in by
    hand): left as it is."""
    if "ELYIR_BENCH_PRINT_START" in start:
        return start
    if not start.strip():
        return f"{START_MACRO_BEFORE}\n{START_MACRO_AFTER}"
    end = "" if start.endswith("\n") else "\n"
    return f"{START_MACRO_BEFORE}\n{start}{end}{START_MACRO_AFTER}"


def plan(printer: Printer, req: Request, presets: Presets) -> Plan:
    machine = presets.resolve(printer.machine)
    if printer.start_macro:
        machine["machine_start_gcode"] = wrap_start_gcode(str(machine.get("machine_start_gcode") or ""))
    process = presets.resolve(printer.process)
    filament_name = req.filament or printer.materials[req.material.upper()]
    filament = presets.resolve(filament_name)
    changes: List[Change] = []

    # Slicing like their prints (5 October 2026): on a printer whose profile was learned from its own files,
    # Everyday is exactly their own settings, and the spool's tweaks stay off for materials their files carry.
    # The other purposes still adjust from their settings.
    own = printer.learned and req.purpose == "everyday"
    for key, value, why in ([] if own else PURPOSES[req.purpose]["set"]):
        _set(process, key, value, why, "purpose", changes)
    for key, value, why in SUPPORTS[req.supports]:
        _set(process, key, value, why, "supports", changes)
    for where, key, value, why in ([] if printer.learned else MATERIALS.get(req.material.upper(), [])):
        if where == "filament":
            _set(filament, key, value, why, "spool", changes, per_filament=True)
        else:
            _set(process, key, value, why, "spool", changes)
    before = edit_values(process)
    # the person's own go after the purpose, supports and spool: what they ask for wins. Kept ones first, then this print's.
    if not req.test:
        label = PURPOSES[req.purpose]["label"]
        for key, value in req.kept.items():
            if key == "brim_type":
                continue                          # per part now: brim_default()
            _set(process, key, edit_value(key, value), f"You keep this for every {label} print on {printer.name}", "kept", changes)
        for key, value in req.settings.items():
            if key == "brim_type":
                continue
            _set(process, key, edit_value(key, value), "You set this for this print", "you", changes)
    for where, key, value, why in TESTS.get(req.test or "", {}).get("set", []):
        _set(filament if where == "filament" else process, key, value, why, "purpose", changes, per_filament=where == "filament")
    if req.color:
        _set(filament, "filament_colour", req.color.upper(), "The colour of the spool, so the printer can check it's loaded", "spool", changes,
             per_filament=True)
    else:
        # Nobody chose a colour: the preset's own (Anycubic's PETG is red-orange) isn't a spool for the printer to ask
        # for (8 October 2026). An empty one checks only the material.
        filament["filament_colour"] = [""]
    if printer.plate:
        # Orca picks the bed temperature by plate type and defaults to Cool Plate, where some
        # filament presets say 0: the bed never heats. The plate is a fact about the printer.
        _set(process, "curr_bed_type", printer.plate, printer.plate_why or f"{printer.name} has a {printer.plate}", "printer", changes)
    # Every object labelled for Klipper's [exclude_object], so one that fails can be skipped mid-print
    # (design/skip-objects/). Orca's presets ask for labels but leave exclude_object off: no EXCLUDE_OBJECT_DEFINE.
    _set(process, "gcode_label_objects", "1", "Each part is named in the file, so the printer knows which is which", "printer", changes)
    _set(process, "exclude_object", "1", "A part that fails can be skipped while the rest carry on", "printer", changes)
    if printer.skirt_loops:
        _set(process, "skirt_loops", str(printer.skirt_loops),
             f"{printer.name} wipes its nozzle on a brush just before printing; a loop around the part gets it flowing again",
             "printer", changes)
    more = [_spool_filament(printer, sp, k, presets, changes) for k, sp in enumerate(req.spools[1:], 2)]
    if more:
        _several_colors(printer, req, machine, process, changes)
    if req.one_after_other:
        _set(process, "print_sequence", "by object", "Each part is finished before the next starts, so the color changes "
             "once per part instead of on every layer they share", "you", changes)
    name = machine.get("name", printer.machine)
    return Plan(machine=cli_preset("machine", machine, name), process=cli_preset("process", process, name),
                filament=cli_preset("filament", filament, name), changes=changes, values=edit_values(process), before=before,
                more=[cli_preset("filament", f, name) for f in more])


PURGE_WHY = {
    "chute": "The printer pushes the old color out off the plate, so no tower is needed",
    "tower": "A tower beside the model takes the old color at each change",
    "both": "The printer pushes the old color out, and a thin tower settles the nozzle before each color",
    "swap": "The old color is pushed through at each swap by hand, so no tower is needed",
}


def _spool_filament(printer: Printer, sp: Spool, k: int, presets: "Presets", changes: List[Change]) -> Dict[str, Any]:
    """The filament preset for the k-th color (2 on): its material's own tweaks, its color, and a name of its own
    (Orca keeps one preset per name)."""
    f = presets.resolve(sp.preset(printer))
    for where, key, value, why in ([] if printer.learned else MATERIALS.get(sp.material.upper(), [])):
        if where == "filament":
            n = len(changes)
            _set(f, key, value, why, "spool", changes, per_filament=True)
            if len(changes) > n:
                changes[-1].label = f"{LABELS.get(key, key)}, color {k}"
    f["filament_colour"] = [sp.color.upper() if sp.color else ""]
    f["name"] = f"{f.get('name') or sp.preset(printer)} ({k})"
    return f


def _several_colors(printer: Printer, req: Request, machine: Dict[str, Any], process: Dict[str, Any],
                    changes: List[Change]) -> None:
    mode = req.purge or default_purge(printer)
    by = "you" if req.purge else "printer"
    _set(machine, "single_extruder_multi_material", "1", "One nozzle, several filaments", "printer", changes)
    _set(machine, "change_filament_gcode", CHANGE_GCODE,
         "Each color change names its spool, so the filament unit or a pause does it", "printer", changes)
    tower = mode in ("tower", "both")
    _set(process, "enable_prime_tower", "1" if tower else "0", PURGE_WHY[mode], by, changes)
    if tower:
        # Orca's flush length still goes to the printer with the tower's purge off: the chute takes it (design/multi-color/)
        _set(machine, "purge_in_prime_tower", "0" if mode == "both" else "1", PURGE_WHY[mode], by, changes)


PLATES_3MF = "plates.3mf"


def filament_files(workdir: str, n: int = 1) -> str:
    """Orca's --load-filaments: filament.json, then filament_2.json... for a plate of several colors."""
    return ";".join(f"{workdir}/filament.json" if k == 1 else f"{workdir}/filament_{k}.json" for k in range(1, n + 1))


def orca_command(orca: List[str], workdir: str, models, outdir: str, orient: bool,
                 slice_it: bool = True, filaments: int = 1, ids: Optional[List[int]] = None) -> List[str]:
    """One run for the whole plate: every model, a copy repeated as many times as it's wanted (Orca
    arranges them and puts what doesn't fit on plate 2, 3...). The 3MF says which plate each landed on
    and where (read_plates). slice_it=False only arranges: how many fit, without slicing (fit). ids: each model's
    color, 1-based, when the plate has several."""
    models = [models] if isinstance(models, str) else list(models)
    return [*orca, *(["--slice", "0"] if slice_it else []), "--arrange", "1", "--orient", "1" if orient else "0",
            "--load-settings", f"{workdir}/machine.json;{workdir}/process.json",
            "--load-filaments", filament_files(workdir, filaments),
            *(["--load-filament-ids", ",".join(str(i) for i in ids)] if ids else []),
            "--outputdir", outdir, "--export-3mf", PLATES_3MF, *models]


_PART_FILE = re.compile(r"(?:^|/)p(\d+)(?:c(\d+))?__")


def part_file(i: int, name: str, copy: Optional[int] = None) -> str:
    """What copy `copy` of part i is called on its way into Orca: the name Orca gives the object, so a
    plate can be read back as parts (read_arrangement), and so every copy is its own object to Klipper
    (one with a name of its own can be skipped mid-print: design/skip-objects/)."""
    return f"p{i}__{name}" if copy is None else f"p{i}c{copy}__{name}"


def read_arrangement(three_mf: str) -> Dict[int, List[Dict[str, Any]]]:
    """Which plate each copy landed on, and for plate 1 where: the centre of its box (x, y in mm on the
    bed) and how far Orca turned it (degrees, anticlockwise). From the 3MF Orca exported alongside."""
    with zipfile.ZipFile(three_mf) as z:
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        settings = ET.fromstring(z.read("Metadata/model_settings.config"))
    pre = model.tag[:model.tag.index("}") + 1] if model.tag.startswith("{") else ""   # the 3MF core namespace
    objects: Dict[str, Tuple[int, float, float]] = {}
    for obj in model.iter(f"{pre}object"):
        comp = next(obj.iter(f"{pre}component"), None)
        if comp is None:
            continue
        path = next((v for k, v in comp.attrib.items() if k.endswith("path")), "")
        m = _PART_FILE.search(path)
        if not m:
            continue
        t = [float(v) for v in comp.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0").split()]
        objects[obj.get("id")] = (int(m.group(1)), t[9], t[10])
    items = {it.get("objectid"): [float(v) for v in it.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0").split()]
             for it in model.iter(f"{pre}item")}
    out: Dict[int, List[Dict[str, Any]]] = {}
    for plate in settings.iter("plate"):
        n = int(next((m.get("value") for m in plate.findall("metadata") if m.get("key") == "plater_id"), "1"))
        for inst in plate.iter("model_instance"):
            oid = next((m.get("value") for m in inst.findall("metadata") if m.get("key") == "object_id"), None)
            if oid not in objects:
                continue
            part, cx, cy = objects[oid]
            entry: Dict[str, Any] = {"part": part}
            m = items.get(oid)
            if m and n == 1:
                # 3MF transforms are row-vector: x' = x*m00 + y*m10 + tx, y' = x*m01 + y*m11 + ty
                entry.update(x=round(cx * m[0] + cy * m[3] + m[9], 1), y=round(cx * m[1] + cy * m[4] + m[10], 1),
                             turn=round(math.degrees(math.atan2(m[1], m[0])), 1))
            out.setdefault(n, []).append(entry)
    return out


# ── a brim for each part (design/brim/, A) ───────────────────────────────────
# Orca's command line takes one brim for the plate. A 3MF can carry one per object (model_settings.config), and
# slicing that 3MF honors it: so a plate whose parts want different brims is arranged first (with room for a
# brim all round), each object gets its own, and the 3MF is sliced.

BRIMS = {"none": "no_brim", "ears": "brim_ears", "all": "outer_only"}
BRIM_WORDS = {"none": "None", "ears": "Corners only", "all": "All round", "auto": "Orca's own"}
LIFTS_AT_CORNERS = ("ASA", "ABS")


def _area(mm2: float) -> str:
    cm2 = mm2 / 100
    return f"{cm2:.0f} cm²" if cm2 >= 10 else f"{cm2:.1f} cm²".replace(".0 ", " ")


def down_side(part: "Part") -> Optional[Tuple[float, List[float]]]:
    """The contact (mm²) and size (w, d, h in mm) of the side that goes down, at the part's size, from what
    lying() measured. None when the file couldn't be measured here (STEP)."""
    lying_ = part.lying
    if not lying_:
        return None
    n = part.down if part.lay == "side" else lying_.get("flat_normal") if part.lay == "flat" else [0.0, 0.0, -1.0]
    side = next((o for o in lying_.get("sides") or [] if n and _dot(o["normal"], n) > 0.996), None)
    if side:
        contact, size = side["contact"], side["size"]
    elif part.lay == "file" and lying_.get("down_area") is not None:
        contact, size = lying_["down_area"], model_size(part.model)
    else:
        return None
    if not size:
        return None
    k = part.scale
    return contact * k * k, [x * k for x in size]


def brim_rule(contact: float, size: List[float], material: str) -> Tuple[str, str]:
    """Which brim a part needs, and why, from how it stands: all round when it's tall for its base or barely
    touches; corner pads for long parts in a material that lifts at the corners; otherwise none."""
    w, d, h = size
    narrow, long = min(w, d), max(w, d)
    if h > 1.5 * narrow:
        return "all", f"{h:.0f} mm tall on a {narrow:.0f} mm base: a rim keeps it standing"
    if contact < 300:
        return "all", f"Touches the plate on only {_area(contact)}: a rim holds it down"
    if material.upper() in LIFTS_AT_CORNERS and long > 60:
        return "ears", f"{material.upper()} pulls up at the corners of long parts: pads hold them down"
    if h <= narrow:
        return "none", f"Low and wide on {_area(contact)}: it stays down by itself"
    return "none", f"Sits on {_area(contact)}: it stays down by itself"


def brim_default(req: "Request", purpose_label: str) -> Optional[Tuple[str, str, str]]:
    """A Brim the person set before brims were per part (Every setting, design/edit-settings/): for this print,
    or kept for the purpose. It stands in for the rule on every part they haven't picked for."""
    back = {v: k for k, v in BRIMS.items()}
    for where, value, why in (("you", req.settings.get("brim_type"), "You set this for this print"),
                              ("kept", req.kept.get("brim_type"), f"You keep this for every {purpose_label} print")):
        if value in back:
            return back[value], why, where
    return None


def brim_pick(part: "Part", material: str, default: Optional[Tuple[str, str, str]] = None) -> Dict[str, str]:
    """{kind, why, by, rule}: the brim this part prints with. by is "you" (picked on its sheet), "kept", or
    "auto" (the rule). rule: what the rule picks, so the sheet can still say so after someone picks another.
    kind "auto" leaves it to Orca: only for a file that couldn't be measured here."""
    m = down_side(part)
    rule = brim_rule(m[0], m[1], material) if m else None
    tag = {"rule": rule[0]} if rule else {}
    if part.brim in BRIMS:
        return {"kind": part.brim, "why": "You picked this for it", "by": "you", **tag}
    if default:
        return {"kind": default[0], "why": default[1], "by": default[2], **tag}
    if rule is None:
        return {"kind": "auto", "why": "It couldn't be measured here, so Orca decides", "by": "auto"}
    return {"kind": rule[0], "why": rule[1], "by": "auto", **tag}


def orca_brim(kind: str) -> str:
    return BRIMS.get(kind, "auto_brim")


def set_brims(src: str, dst: str, brims: List[str]) -> None:
    """The arranged 3MF again, each object with its part's brim_type (brims: Orca's value, by part index, read
    from the object's name, p{i}c{k}__...)."""
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            if item.filename.endswith((".gcode", ".md5")):
                continue
            data = zi.read(item.filename)
            if item.filename == "Metadata/model_settings.config":
                root = ET.fromstring(data)
                for obj in root.iter("object"):
                    name = next((m.get("value") for m in obj.findall("metadata") if m.get("key") == "name"), "")
                    found = _PART_FILE.search(name)
                    if found and int(found.group(1)) < len(brims):
                        for old in [m for m in obj.findall("metadata") if m.get("key") == "brim_type"]:
                            obj.remove(old)
                        ET.SubElement(obj, "metadata", key="brim_type", value=brims[int(found.group(1))])
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            zo.writestr(item, data)


def orca_slice_3mf(orca: List[str], workdir: str, three_mf: str, outdir: str, filaments: int = 1) -> List[str]:
    """Slice every plate of an arranged 3MF as it is (no arranging again), with the printer's presets on top.
    Each object keeps the color the arranging gave it (its "extruder" in model_settings.config)."""
    return [*orca, "--slice", "0", "--load-settings", f"{workdir}/machine.json;{workdir}/process.json",
            "--load-filaments", filament_files(workdir, filaments), "--outputdir", outdir, three_mf]


def counts(placed: List[Dict[str, Any]], parts: int) -> List[int]:
    out = [0] * parts
    for p in placed:
        if 0 <= p["part"] < parts:
            out[p["part"]] += 1
    return out


def write_plan(p: Plan, workdir: str) -> None:
    for kind, preset in (("machine", p.machine), ("process", p.process), ("filament", p.filament)):
        with open(os.path.join(workdir, f"{kind}.json"), "w") as f:
            json.dump(preset, f, indent=1)
    for k, preset in enumerate(p.more, 2):
        with open(os.path.join(workdir, f"filament_{k}.json"), "w") as f:
            json.dump(preset, f, indent=1)


# ── reading what came out ────────────────────────────────────────────────────

def parse_duration(text: str) -> Optional[int]:
    """'1d 2h 49m 42s' → seconds."""
    parts = re.findall(r"(\d+)\s*([dhms])", text)
    if not parts:
        return None
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * mult[u] for n, u in parts)


def short_duration(seconds: int) -> str:
    """How Orca names files: 41m9s, 1h16m."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m}m" if h else f"{m}m{s}s"


def read_result(gcode: str) -> Dict[str, Any]:
    """Estimates from Orca's comments, and whether any supports were printed. One pass, no slurp:
    a long print is tens of megabytes."""
    out: Dict[str, Any] = {"seconds": None, "grams": None, "layers": None, "supports": False, "grams_each": []}
    with open(gcode, errors="replace") as f:
        for line in f:
            if line[0] != ";":
                continue
            if line.startswith(";TYPE:Support"):
                out["supports"] = True
            elif line.startswith("; estimated printing time (normal mode)") and out["seconds"] is None:
                out["seconds"] = parse_duration(line.split("=", 1)[1])
            elif line.startswith("; total filament used [g]"):
                try:
                    out["grams"] = round(float(line.split("=", 1)[1]), 1)
                except ValueError:
                    pass
            elif line.startswith("; total layer number:") and out["layers"] is None:
                out["layers"] = int(line.split(":", 1)[1])
            elif line.startswith("; filament used [g] ="):
                try:
                    out["grams_each"] = [round(float(g), 1) for g in line.split("=", 1)[1].split(",")]
                except ValueError:
                    pass
    return out


_AXIS = re.compile(r"([XYZE])(-?\d*\.?\d+)")


def support_lines(gcode: str, limit: int = 12000) -> Dict[str, Any]:
    """Where the supports go (design/supports/, A: the picture on each kind's card): every extruding move
    inside a ;TYPE:Support... section, in mm on the bed. A tree is tens of thousands of short moves, so whole
    layers are left out until `limit` remain, and `width` (mm) is drawn wide enough to close the gaps.
    segs is base64 of little-endian int16s, x0 y0 x1 y1 z in tenths of a mm."""
    layers: List[List[Tuple[float, float, float, float, float]]] = []
    x = y = z = 0.0
    e_abs = False
    last_e = 0.0
    on = False
    height = 0.2
    with open(gcode, errors="replace") as f:
        for line in f:
            c = line[0]
            if c == ";":
                if line.startswith(";TYPE:"):
                    on = line.startswith(";TYPE:Support")
                elif line.startswith(";LAYER_CHANGE"):
                    layers.append([])
                elif line.startswith(";HEIGHT:"):
                    with contextlib.suppress(ValueError):
                        height = float(line[8:]) or height
                continue
            if c != "G" and c != "M":
                continue
            if line.startswith("M82"):
                e_abs = True
                continue
            if line.startswith("M83"):
                e_abs = False
                continue
            if not (line.startswith("G1 ") or line.startswith("G0 ")):
                if line.startswith("G92"):
                    m = re.search(r"E(-?\d*\.?\d+)", line)
                    if m:
                        last_e = float(m.group(1))
                continue
            nx, ny, nz, e = x, y, z, None
            for k, v in _AXIS.findall(line.split(";", 1)[0]):
                if k == "X":
                    nx = float(v)
                elif k == "Y":
                    ny = float(v)
                elif k == "Z":
                    nz = float(v)
                else:
                    e = float(v)
            if e is not None and e_abs:
                e, last_e = e - last_e, e
            if on and e is not None and e > 0 and (nx != x or ny != y) and layers:
                layers[-1].append((x, y, nx, ny, nz))
            x, y, z = nx, ny, nz
    layers = [l for l in layers if l]
    total = sum(len(l) for l in layers)
    step = max(1, math.ceil(total / limit)) if total else 1
    keep = [s for i, l in enumerate(layers) if i % step == 0 for s in l]
    packed = struct.pack(f"<{len(keep) * 5}h", *(max(-32768, min(32767, round(v * 10))) for s in keep for v in s))
    return {"count": len(keep), "width": round(max(0.45, height * step), 2), "segs": base64.b64encode(packed).decode()}


# Layers (design/look/, A with C's layers): a slice's G-code read once into where each layer starts and every
# layer's outer wall, to draw the print up to a cut; then any one layer's paths on request, each move tagged
# with what it prints.
WALL, INNER, INFILL, SUPPORT, OTHER = range(5)
_KIND_OF = (("Outer wall", WALL), ("Overhang wall", WALL), ("External perimeter", WALL), ("Inner wall", INNER),
            ("Perimeter", INNER), ("Support", SUPPORT), ("Skirt", OTHER), ("Brim", OTHER), ("Prime tower", OTHER),
            ("Wipe tower", OTHER), ("Custom", OTHER))


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
    with open(gcode, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", "replace")
            if line.startswith(";LAYER_CHANGE"):
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


_TOOL = re.compile(r"(\bTOOL=)0\b")


def use_slot(gcode: str, slot: int, load: bool = False) -> bool:
    """A one-filament slice always uses tool 0. Point it at the chosen slot instead: TOOL=n on the first
    PRINT_START, for a start macro that loads it, and with load (a printer with a filament unit) T<slot> just
    after it too, since not every start macro does (the filament-unit service's doesn't): when the slot is
    already in the head, that T only resumes. Says whether the slot is asked for at all."""
    if slot == 0 and not load:
        return True
    tmp = gcode + ".tmp"
    done = found = False
    with open(gcode, errors="replace") as src, open(tmp, "w") as dst:
        for line in src:
            if not done and line.startswith("PRINT_START"):
                done = True
                if _TOOL.search(line):
                    line = _TOOL.sub(rf"\g<1>{slot}", line, count=1)
                    found = True
                dst.write(line)
                if load:
                    dst.write(f"T{slot}\n")
                continue
            dst.write(line)
    os.replace(tmp, gcode)
    return found or (done and load)


_ELYIR_PURGE = re.compile(r"^ELYIR_PURGE LENGTH=(-?[\d.]+) FROM=(-?\d+) TO=(\d+)")
_T_LINE = re.compile(r"^T(\d+)\s*$")
_M73_R = re.compile(r"^M73 .*\bR(\d+)")
_START_TOOL = re.compile(r"(\bTOOL=)(\d+)\b")


def assign_spools(gcode: str, spools: List[Spool], printer: Printer, purge: str) -> Dict[str, Any]:
    """A slice of several colors, pointed at where each comes from. Orca writes every change as
    ELYIR_PURGE LENGTH= FROM= TO= then T<color>. A color from a slot becomes T<slot>, with the purge length
    first when the chute takes it (ELYIR_PURGE LENGTH=); one swapped by hand, or any change on a printer
    without a unit, becomes an M600 with the color beside it (;COLOR_CHANGE, read by the printer's color-change
    sheet) and a "by hand" mark so a printer with a unit doesn't plan it onto a spool itself. The first color
    (Orca's choice: with parts one after the other, not always the first spool) needs a slot on a printer with a
    unit: PRINT_START gets TOOL=<slot>, and Orca's first change stays as the slot's T, because not every start
    macro loads TOOL= (the filament-unit service's doesn't; found on the main test printer, 21 October 2026).
    Says what changes when: [{layer, at (seconds into the print, the changes before it included), to, hand,
    purge (mm)}]. ValueError when a color with no slot is used on a printer with a unit."""
    chute = purge in ("chute", "both")
    tmp = gcode + ".tmp"
    changes: List[Dict[str, Any]] = []
    first: Optional[int] = None
    layer, start_min, now_min = 0, None, 0
    pending: Optional[Tuple[float, int]] = None
    with open(gcode, errors="replace") as src, open(tmp, "w") as dst:
        for line in src:
            if line.startswith(";LAYER_CHANGE"):
                layer += 1
            elif line.startswith("M73"):
                m = _M73_R.match(line)
                if m:
                    now_min = int(m.group(1))
                    start_min = now_min if start_min is None else start_min
            elif line.startswith("PRINT_START") and first is None:
                m = _START_TOOL.search(line)
                k = int(m.group(2)) if m else -1
                if 0 <= k < len(spools) and printer.unit:
                    if spools[k].slot is None:
                        raise ValueError(f"Color {k + 1} prints first, so it needs a slot: it's loaded before the print starts.")
                    line = _START_TOOL.sub(rf"\g<1>{spools[k].slot}", line, count=1)
            elif line.startswith("ELYIR_PURGE"):
                m = _ELYIR_PURGE.match(line)
                if m:
                    pending = (float(m.group(1)), int(m.group(2)))
                    continue
            elif pending is not None or (first is not None and line[0] == "T"):
                m = _T_LINE.match(line)
                if m:
                    to = int(m.group(1))
                    length, frm = pending or (0.0, -1)
                    pending = None
                    if first is None:
                        first = to
                        if not printer.unit or to >= len(spools):
                            continue             # what's in the printer
                        if spools[to].slot is None:
                            raise ValueError(f"Color {to + 1} prints first, so it needs a slot: it's loaded before the print starts.")
                        dst.write(f"T{spools[to].slot}\n")
                        continue
                    if to >= len(spools):
                        raise ValueError(f"The slice asks for color {to + 1}, and the plate has {len(spools)}.")
                    sp = spools[to]
                    hand = sp.hand or not printer.unit
                    at = (start_min - now_min) * 60 if start_min is not None else 0
                    changes.append({"layer": layer, "at": int(at + len(changes) * printer.change_seconds), "to": to,
                                    "hand": hand, "purge": round(length, 1)})
                    if hand:
                        line = f";COLOR_CHANGE,T{to},{sp.color or ''}\n; elyir: by hand\nM600\n"
                    elif sp.slot is None:
                        raise ValueError(f"Color {to + 1} has no slot to come from.")
                    else:
                        line = (f"ELYIR_PURGE LENGTH={round(length, 1)}\n" if chute else "") + f"T{sp.slot}\n"
            dst.write(line)
    os.replace(tmp, gcode)
    return {"first": first or 0, "changes": changes}


def paint_state(code: Optional[str]) -> int:
    """The filament a triangle is painted (Bambu Studio / Orca paint_color), 0 when it isn't. A triangle split by the
    brush is a tree; for a picture, its first leaf stands for it. Hex digits are read from the end: the low two
    bits say how many children, the high two the state, and 3 means the next digit adds to it."""
    if not code:
        return 0
    try:
        digits = [int(c, 16) for c in reversed(code.strip())]
    except ValueError:
        return 0
    i = 0
    while i < len(digits):
        d = digits[i]
        i += 1
        if d & 0b11:
            continue                             # split: its first child follows
        state = d >> 2
        if state == 3 and i < len(digits):
            state = digits[i] + 3
        return state
    return 0


def pieces(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A 3MF with colors in pieces to draw: each part's triangles split by filament. [{name, tris, filament}]"""
    out = []
    for p in parts:
        fils = p.get("filaments") or [1] * len(p["tris"])
        for f in sorted(set(fils)):
            out.append({"name": p["name"], "filament": f, "tris": [t for t, g in zip(p["tris"], fils) if g == f]})
    return out


def size_of_tris(parts: List[Dict[str, Any]]) -> Optional[List[float]]:
    """Width, depth and height in mm of three_mf_parts' parts together, as placed."""
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for v in (v for p in parts for t in p["tris"] for v in t):
        for i in range(3):
            lo[i], hi[i] = min(lo[i], v[i]), max(hi[i], v[i])
    return [round(hi[i] - lo[i], 2) for i in range(3)] if lo[0] != float("inf") else None


def three_mf_colors(path: str) -> Optional[Dict[str, Any]]:
    """What a 3MF from Bambu Studio or Orca says about colors: each filament's color and material, which are
    used (by an object or part, a change at a height, or painting), whether it's painted, and its changes at a
    height. None when it prints in one color: then it's read as its parts (three_mf_parts)."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        try:
            cfg = json.loads(z.read("Metadata/project_settings.config")) if "Metadata/project_settings.config" in names else {}
        except ValueError:
            cfg = {}
        colors = [c if isinstance(c, str) else None for c in (cfg.get("filament_colour") or [])]
        types = [t if isinstance(t, str) else None for t in (cfg.get("filament_type") or [])]
        used: set = set()

        def extruder(el) -> Optional[int]:
            for m in el.findall("metadata"):
                v = m.get("value") or ""
                if m.get("key") == "extruder" and v.isdigit() and int(v) > 0:
                    return int(v)
            return None

        objects = (ET.fromstring(z.read("Metadata/model_settings.config")).findall("object")
                   if "Metadata/model_settings.config" in names else [])
        for obj in objects:                      # an object without its own filament prints in the first
            own = extruder(obj) or 1
            used.add(own)
            used |= {extruder(part) or own for part in obj.findall("part")}
        if not objects:
            used.add(1)
        heights = []
        if "Metadata/custom_gcode_per_layer.xml" in names:
            for el in ET.fromstring(z.read("Metadata/custom_gcode_per_layer.xml")).iter("layer"):
                if el.get("type") == "2" and (el.get("extruder") or "").isdigit():
                    heights.append({"z": float(el.get("top_z") or 0), "to": int(el.get("extruder"))})
                    used.add(int(el.get("extruder")))
        painted = any(n.endswith(".model") and b"paint_color=" in z.read(n) for n in names)
    count = max([len(colors), *used, 1])
    if painted:
        used |= set(range(1, count + 1))
    used = used or {1}
    if len(used) < 2:
        return None
    pad = lambda xs: (xs + [None] * count)[:count]
    return {"colors": [{"color": c.upper() if c and re.fullmatch(r"#[0-9A-Fa-f]{6}", c[:7]) else None, "material": t,
                        "used": k in used} for k, (c, t) in enumerate(zip(pad(colors), pad(types)), 1)],
            "painted": painted, "heights": heights}


def gcode_name(model: str, material: str, seconds: Optional[int], how_many: Optional[List[int]] = None,
               plate: int = 1, plates: int = 1) -> str:
    """Named the way Orca names its files, so the rest of Elyir Bench reads it like one. A plate of several
    says so: bushing_x25 (copies), cutting_arm_and_2_more (different parts), _1of2 (one of two plates)."""
    stem = re.sub(r"^p\d+(?:c\d+)?__", "", Path(model).stem)
    stem = _PRINTER_TAGS.sub("", re.sub(r"^(?:\[[^\]]*\][\s_-]*)+", "", stem))      # "[a]_", "_x1_r1s": clutter
    stem = re.sub(r"_+", "_", re.sub(r"[^\w.-]+", "_", stem)).strip("_") or "model"
    on = [n for n in (how_many or []) if n]
    if len(on) > 1:
        stem += f"_and_{len(on) - 1}_more"
    elif on and on[0] > 1:
        stem += f"_x{on[0]}"
    if plates > 1:
        stem += f"_{plate}of{plates}"
    parts = [stem, material.upper()] + ([short_duration(seconds)] if seconds else [])
    return "_".join(parts) + ".gcode"


_PRINTER_TAGS = re.compile(r"(?:[\s_-]+(?:x1c?|x1e|p1[ps]|a1m?|r1s?|mk[34]s?|bambu|bbl))+$", re.I)


def display_name(filename: str) -> str:
    """"[a]_buildplate_bushing_open_x1_r1s.stl" -> "Buildplate bushing open". Mirrors modelName in
    app/src/slice/plan.ts."""
    stem = re.sub(r"\.(stl|obj|step|stp|3mf)$", "", filename, flags=re.I)
    stem = re.sub(r"^p\d+(?:c\d+)?__", "", stem)
    stem = re.sub(r"^(?:\[[^\]]*\][\s_-]*)+", "", stem)
    stem = _PRINTER_TAGS.sub("", stem)
    stem = re.sub(r"[_-]+", " ", stem).strip()
    return (stem[0].upper() + stem[1:]) if stem else filename


def plural(name: str, n: int) -> str:
    """"5 bushings", "1 cutting arm". Only the last word changes; a name of more than two words isn't
    bent ("6 copies of buildplate bushing open")."""
    lower = (name[0].lower() + name[1:]) if name else "thing"
    words = lower.split(" ")
    if len(words) > 2:
        return f"1 copy of {lower}" if n == 1 else f"{n} copies of {lower}"
    if n == 1:
        return f"1 {lower}"
    w = words[-1]
    if re.search(r"(s|x|z|ch|sh)$", w):
        w += "es"
    elif re.search(r"[^aeiou]y$", w):
        w = w[:-1] + "ies"
    else:
        w += "s"
    return f"{n} {' '.join(words[:-1] + [w])}"


def plate_words(names: List[str], how_many: List[int]) -> str:
    """What's on a plate, for Now: "5 bushings", or "4 parts" when they differ."""
    on = [(nm, n) for nm, n in zip(names, how_many) if n]
    if len(on) == 1:
        return plural(display_name(on[0][0]), on[0][1])
    total = sum(n for _, n in on)
    return f"{total} part{'s' if total != 1 else ''}"


_PLAIN = [
    (("fully inside", "over the boundary", "bed size is smaller", "arrang"), "It doesn't fit on {printer}'s bed."),
    (("can not be parsed", "model file"), "The model file couldn't be read. It may be damaged, or not a 3D model."),
    (("out of memory", "triangle count"), "The model is too detailed to slice here. A simpler version of it would work."),
    (("empty",), "There's nothing in the model to print."),
]


def explain(raw: str, printer_name: str) -> str:
    """Orca's reason, in a sentence a person can act on. The raw text stays in the details."""
    low = raw.lower()
    for words, plain in _PLAIN:
        if any(w in low for w in words):
            return plain.format(printer=printer_name)
    return "The slicer couldn't make this one. The details say why."


def support_kind(process: Dict[str, Any]) -> str:
    """The kind of support a process preset prints: "tree" or "normal" (Orca's normal, its default)."""
    return "tree" if str(process.get("support_type", "")).startswith("tree") else "normal"


def options(printers: Dict[str, Printer], beds: Optional[Dict[str, Optional[List[float]]]] = None,
            kinds: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """What a person can choose, for the app to draw. kinds: each printer's usual support (support_kind)."""
    beds, kinds = beds or {}, kinds or {}
    return {
        "purposes": [{"id": k, "label": v["label"], "summary": v["summary"]} for k, v in PURPOSES.items()],
        "supports": list(SUPPORTS),
        "editable": [{"key": k, "label": LABELS.get(k, k), **spec} for k, spec in EDITABLE.items()],
        "printers": [{"id": p.id, "name": p.name, "materials": sorted(p.materials), "slots": p.tools,
                      "bed": beds.get(p.id), "base": p.process, "supports": kinds.get(p.id, "normal"),
                      "unit": p.unit, "purges": purges(p), "change_seconds": p.change_seconds}
                     for p in printers.values()],
        "models": sorted(MODEL_TYPES),
    }


def bed_of(machine: Dict[str, Any]) -> Optional[List[float]]:
    """The build volume [x, y, z] in mm, from Orca's printable_area ("0x0", "350x0", ...) and height."""
    try:
        pts = [tuple(float(v) for v in p.split("x")) for p in machine["printable_area"]]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return [max(xs) - min(xs), max(ys) - min(ys), float(machine.get("printable_height", 0)) or 0.0]
    except (KeyError, ValueError, TypeError):
        return None


# ── models ───────────────────────────────────────────────────────────────────

def _stl_binary(data: bytes) -> bool:
    if len(data) < 84:
        return False
    n = struct.unpack_from("<I", data, 80)[0]
    return len(data) == 84 + n * 50


def _vertices(path: str):
    """Every vertex of an STL (binary or text) or OBJ, as (x, y, z). STEP isn't read here."""
    ext = Path(path).suffix.lower()
    with open(path, "rb") as f:
        data = f.read()
    if ext == ".stl" and _stl_binary(data):
        n = struct.unpack_from("<I", data, 80)[0]
        for rec in struct.iter_unpack("<12x9fH", data[84:84 + n * 50]):
            yield rec[0:3]
            yield rec[3:6]
            yield rec[6:9]
    elif ext == ".stl":
        for m in re.finditer(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data):
            yield tuple(float(v) for v in m.groups())
    elif ext == ".obj":
        for m in re.finditer(rb"(?m)^v\s+(\S+)\s+(\S+)\s+(\S+)", data):
            yield tuple(float(v) for v in m.groups())


def model_size(path: str) -> Optional[List[float]]:
    """Width, depth and height in mm, or None when the file can't be measured here (STEP)."""
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    seen = False
    for v in _vertices(path):
        seen = True
        for i in range(3):
            lo[i] = min(lo[i], v[i])
            hi[i] = max(hi[i], v[i])
    return [round(hi[i] - lo[i], 2) for i in range(3)] if seen else None


def fit_scale(size: Optional[List[float]], bed: Optional[List[float]], margin: float = 0.98) -> float:
    """The largest whole-percent scale (at most 100%) that fits the model on the bed as it lies (Orca
    arranges without turning it). 1.0 when it already fits or either size is unknown."""
    if not size or not bed:
        return 1.0
    x, y, z = size
    bx, by, bz = bed[0] * margin, bed[1] * margin, (bed[2] or float("inf"))
    k = min(1.0, bx / x if x else 1, by / y if y else 1, bz / z if z else 1)
    return 1.0 if k >= 1.0 else int(k * 100) / 100


def scale_model(src: str, dst: str, k: float) -> None:
    """A copy of the model scaled by k about the origin. Orca's own --scale crashes, so it's done here.
    STL comes out binary; OBJ stays OBJ."""
    ext = Path(src).suffix.lower()
    if ext == ".stl":
        with open(src, "rb") as f:
            data = f.read()
        if _stl_binary(data):
            n = struct.unpack_from("<I", data, 80)[0]
            out = bytearray(data[:84])
            for rec in struct.iter_unpack("<12f2s", data[84:84 + n * 50]):
                out += struct.pack("<12f2s", *rec[:3], *[v * k for v in rec[3:12]], rec[12])
        else:
            v = list(_vertices(src))
            write_stl(dst, [[[c * k for c in p] for p in v[i:i + 3]] for i in range(0, len(v) - 2, 3)])
            return
        with open(dst, "wb") as f:
            f.write(out)
    elif ext == ".obj":
        with open(src) as f, open(dst, "w") as g:
            for line in f:
                if line.startswith("v "):
                    parts = line.split()
                    line = "v " + " ".join(f"{float(v) * k:.6g}" for v in parts[1:4]) + "\n"
                g.write(line)
    else:
        raise ValueError(f"can't resize a {ext} file")


def _triangles(path: str) -> List[Tuple[Tuple[float, ...], ...]]:
    v = list(_vertices(path))
    return [tuple(v[i:i + 3]) for i in range(0, len(v) - 2, 3)]


def _normal_area(t) -> Tuple[Optional[List[float]], float]:
    a, b, c = t
    u = [b[k] - a[k] for k in range(3)]
    w = [c[k] - a[k] for k in range(3)]
    n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    length = math.sqrt(sum(x * x for x in n))
    return ([x / length for x in n], length / 2) if length else (None, 0.0)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sides(path: str, tris=None, limit: int = 8) -> List[Dict[str, Any]]:
    """Every side the model can rest on, most contact first: the side facing `normal` goes down. contact is
    the area that would really touch the plate (faces on the model's outermost plane that way, not every
    face pointing that way); size is [w, d, h] lying so; support the area facing down more than 45°
    above the plate, a rough measure of how much needs holding up. design/orientation/ (Which side down)."""
    tris = _triangles(path) if tris is None else tris
    if not tris:
        return []
    groups: Dict[Tuple[float, ...], List[float]] = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    faces = []
    for t in tris:
        n, a = _normal_area(t)
        if n is None:
            continue
        faces.append((t, n, a))
        g = groups[tuple(round(x, 1) for x in n)]
        for i in range(3):
            g[i] += n[i] * a
        g[3] += a
    verts = [v for t, _, _ in faces for v in t]
    out: List[Dict[str, Any]] = []
    for g in sorted(groups.values(), key=lambda g: -g[3])[:24]:
        length = math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2) or 1.0
        n = [g[0] / length, g[1] / length, g[2] / length]
        if any(_dot(n, o["normal"]) > 0.996 for o in out):
            continue
        ext = max(_dot(n, v) for v in verts)
        contact = sum(a for t, m, a in faces if _dot(m, n) > 0.985 and all(abs(_dot(n, v) - ext) < 0.05 for v in t))
        if contact < 1:
            continue
        r = down_rotation(n)
        rot = [[_dot(r[k], v) for k in range(3)] for v in verts]
        lo = [min(p[k] for p in rot) for k in range(3)]
        hi = [max(p[k] for p in rot) for k in range(3)]
        support = 0.0
        for t, m, a in faces:
            mz = _dot(r[2], m)
            if mz < -0.7071 and sum(_dot(r[2], v) for v in t) / 3 - lo[2] > 0.2:
                support += a
        out.append({"normal": [round(x, 5) for x in n], "contact": round(contact, 1),
                    "size": [round(hi[k] - lo[k], 1) for k in range(3)], "support": round(support, 1)})
    out.sort(key=lambda o: -o["contact"])
    best = out[0]["contact"] if out else 0
    return [o for o in out if o["contact"] >= max(20.0, best * 0.02)][:limit]


def lying(path: str) -> Optional[Dict[str, Any]]:
    """How the model sits, and whether lying it on another side is clearly better: the area touching the
    plate as the file has it, and the side with the most real contact (sides()). design/orientation/ (A):
    laid flat for the person when the side that's down touches much less than that one. None for a file
    that can't be read here (STEP)."""
    tris = _triangles(path)
    if not tris:
        return None
    zmin = min(v[2] for t in tris for v in t)
    down = 0.0
    for t in tris:
        n, a = _normal_area(t)
        if n is not None and n[2] < -0.98 and all(abs(v[2] - zmin) < 0.05 for v in t):
            down += a
    every = sides(path, tris)
    if not every:
        return None
    n = every[0]["normal"]
    already = n[2] < -0.98                       # the side with the most contact is the one that's down
    return {"down_area": round(down, 1), "flat_area": every[0]["contact"], "flat_normal": n,
            "flat_better": (not already) and every[0]["contact"] > 2 * max(down, 1.0),
            "tilt": round(math.degrees(math.acos(max(-1.0, min(1.0, -n[2])))), 1), "sides": every}


def down_rotation(normal: List[float]) -> List[List[float]]:
    """The rotation that turns `normal` to point straight down (0, 0, -1)."""
    t = [0.0, 0.0, -1.0]
    ax = [normal[1] * t[2] - normal[2] * t[1], normal[2] * t[0] - normal[0] * t[2], normal[0] * t[1] - normal[1] * t[0]]
    s = math.sqrt(sum(x * x for x in ax))
    c = sum(normal[i] * t[i] for i in range(3))
    if s < 1e-9:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] if c > 0 else [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]
    x, y, z = (a / s for a in ax)
    k = 1 - c
    return [[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
            [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
            [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]


def lay_flat(src: str, dst: str, normal: List[float]) -> None:
    """A copy of the model turned so the side facing `normal` lies on the plate. Written as binary STL."""
    r = down_rotation(normal)
    write_stl(dst, [[[sum(r[i][j] * v[j] for j in range(3)) for i in range(3)] for v in t] for t in _triangles(src)])


def cut_above(src: str, dst: str, z: float) -> bool:
    """The part of the model above z, set down on the plate, written as binary STL (Print the rest,
    design/power-loss/). z counts from the model's own bottom, as a print does. The cut is closed with a fan per
    loop: it lies in the bed's plane, which no layer crosses, so its exact shape doesn't matter to the slicer.
    False when nothing is above z."""
    tris = _triangles(src)
    if not tris:
        return False
    z = min(v[2] for t in tris for v in t) + z + 1e-4
    kept, segs = [], []
    for t in tris:
        up = [v[2] > z for v in t]
        if all(up):
            kept.append([list(v) for v in t])
            continue
        if not any(up):
            continue
        poly, leave, enter = [], None, None
        for i in range(3):
            a, b = t[i], t[(i + 1) % 3]
            if up[i]:
                poly.append(list(a))
            if up[i] != up[(i + 1) % 3]:
                f = (z - a[2]) / (b[2] - a[2])
                p = [a[k] + f * (b[k] - a[k]) for k in range(3)]
                p[2] = z
                poly.append(p)
                if up[i]:
                    leave = p
                else:
                    enter = p
        kept += [[poly[0], poly[k], poly[k + 1]] for k in range(1, len(poly) - 1)]
        segs.append((leave, enter))   # every triangle's cut edge the same way round, so they chain into loops
    if not kept:
        return False
    key = lambda p: (round(p[0], 4), round(p[1], 4))
    starts = {}
    for s in segs:
        starts.setdefault(key(s[0]), []).append(s)
    used = set()
    for s in segs:
        if id(s) in used:
            continue
        loop, cur = [], s
        while cur is not None and id(cur) not in used:
            used.add(id(cur))
            loop.append(cur[0])
            cur = next((n for n in starts.get(key(cur[1]), []) if id(n) not in used), None)
        for k in range(1, len(loop) - 1):
            tri = [loop[0], loop[k], loop[k + 1]]
            n, _ = _normal_area(tri)
            kept.append(tri if not n or n[2] <= 0 else [tri[0], tri[2], tri[1]])
    write_stl(dst, [[[v[0], v[1], v[2] - z] for v in t] for t in kept])
    return True


def size_laid_flat(path: str, normal: List[float]) -> Optional[List[float]]:
    """Width, depth and height once laid on the side facing `normal`."""
    r = down_rotation(normal)
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    seen = False
    for v in _vertices(path):
        seen = True
        p = [sum(r[i][j] * v[j] for j in range(3)) for i in range(3)]
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])
    return [round(hi[i] - lo[i], 2) for i in range(3)] if seen else None


def model_changes(parts: List["Part"], brims: Optional[List[Dict[str, str]]] = None) -> List["Change"]:
    """What was done to the models themselves, for Every setting next to the slicer's own changes. On a
    plate of several, each says which part it's about. brims: brim_pick() for each part."""
    out = []
    for i, p in enumerate(parts):
        who = f" · {display_name(p.name)}" if len(parts) > 1 else ""
        if p.lay == "flat" and p.lying:
            out.append(Change("orientation", "on its flattest side", "as in the file",
                              "The side that was down in the file touched the plate much less. Lying on the flattest side is steadier and usually needs less support",
                              "model", label=f"Lying{who}"))
        elif p.lay == "side" and p.down:
            out.append(Change("orientation", "on the side you picked", "as in the file",
                              "You chose which side goes on the plate", "model", label=f"Lying{who}"))
        if p.scale != 1:
            out.append(Change("scale", f"{round(p.scale * 100)}%", "100%", "It didn't fit on the bed as it was", "model",
                              label=f"Size{who}"))
        b = brims[i] if brims and i < len(brims) else None
        if b and b["kind"] != "auto":
            out.append(Change("brim_type", BRIM_WORDS[b["kind"]], BRIM_WORDS["auto"], b["why"], "model", label=f"Brim{who}"))
    return out


def fit_guess(size: Optional[List[float]], bed: Optional[List[float]]) -> int:
    """How many copies to ask Orca to arrange when finding how many fit: comfortably more than could."""
    if not size or not bed or not size[0] or not size[1]:
        return 50
    return max(2, min(FIT_CAP, math.ceil(bed[0] * bed[1] / (size[0] * size[1]) * 1.2) + 2))


# Every file this slicer writes says so near its top (docs/slicer-profile.md): the printer learns how a person slices
# from their own Orca files, and must never learn from its own (printer/orca_profile.py MARKER).
MARKER = "; sliced by Elyir Bench"


def mark_ours(gcode: str) -> None:
    """The marker line, right after Orca's "; generated by" line (first, when there's none), once."""
    with open(gcode, errors="replace") as f:
        head = f.read(8192)
    if MARKER in head:
        return
    tmp = gcode + ".tmp"
    done = False
    with open(gcode, errors="replace") as src, open(tmp, "w") as dst:
        for i, line in enumerate(src):
            if not done and i == 0 and not line.startswith(("; HEADER_BLOCK_START", "; generated by")):
                dst.write(MARKER + "\n")
                done = True
            dst.write(line)
            if not done and line.startswith("; generated by"):
                dst.write(MARKER + "\n")
                done = True
            elif not done and line.startswith("; HEADER_BLOCK_END"):
                dst.write(MARKER + "\n")          # a header without a generator line
                done = True
    os.replace(tmp, gcode)


def png_size(png: bytes) -> Tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("thumbnail must be a PNG")
    return struct.unpack(">II", png[16:24])


def embed_thumbnail(gcode: str, png: bytes) -> None:
    """Put a picture in the file the way slicers do, so Moonraker extracts it for the Print tab."""
    w, h = png_size(png)
    b64 = base64.b64encode(png).decode()
    block = [f"; THUMBNAIL_BLOCK_START", f"; thumbnail begin {w}x{h} {len(b64)}"]
    block += ["; " + b64[i:i + 78] for i in range(0, len(b64), 78)]
    block += ["; thumbnail end", "; THUMBNAIL_BLOCK_END", ""]
    tmp = gcode + ".tmp"
    done = False
    with open(gcode, errors="replace") as src, open(tmp, "w") as dst:
        for line in src:
            dst.write(line)
            if not done and line.startswith("; HEADER_BLOCK_END"):
                dst.write("\n".join(block) + "\n")
                done = True
    if not done:                                   # no header block: put it first
        with open(tmp) as f:
            rest = f.read()
        with open(tmp, "w") as f:
            f.write("\n".join(block) + "\n" + rest)
    os.replace(tmp, gcode)
