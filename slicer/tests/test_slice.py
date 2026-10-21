"""Slicing without the settings: presets, purposes, the G-code that comes back, and the service
against a fake Orca and a fake Moonraker. One test runs the real Orca when it's installed."""
import asyncio
import base64
import json
import os
import shutil
import stat
import struct
import sys
from pathlib import Path

import pytest
from aiohttp import FormData, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench_slice as sl  # noqa: E402
import slice_service as S  # noqa: E402

REAL_ORCA = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
HERE = Path(__file__).resolve().parent


# ── a small preset library, shaped like Orca's ───────────────────────────────

def write(root: Path, rel: str, d: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))


@pytest.fixture
def profiles(tmp_path):
    system, user = tmp_path / "system", tmp_path / "user"
    write(system, "Voron/machine/base.json", {"name": "Voron base", "printable_area": ["0x0", "350x0", "350x350", "0x350"],
                                              "machine_start_gcode": "PRINT_START TOOL=[initial_tool]"})
    write(system, "Voron/machine/v24.json", {"name": "Voron 2.4 350", "inherits": "Voron base", "nozzle_diameter": ["0.4"]})
    write(system, "Voron/process/std.json", {"name": "0.20mm Standard @Voron", "layer_height": "0.2", "wall_loops": "3",
                                             "sparse_infill_density": "15%", "sparse_infill_pattern": "crosshatch",
                                             "top_shell_layers": "4", "bottom_shell_layers": "3", "enable_support": "0",
                                             "support_type": "normal(auto)", "seam_position": "nearest",
                                             "compatible_printers": ["Voron 2.4 350"]})
    write(system, "Voron/filament/asa.json", {"name": "Generic ASA", "filament_type": ["ASA"], "hot_plate_temp": ["110"],
                                              "cool_plate_temp": ["0"]})
    write(user, "machine/Workshop.json", {"name": "Workshop", "inherits": "Voron 2.4 350", "from": "User"})
    write(user, "filament/asa.json", {"name": "My ASA", "inherits": "Generic ASA", "nozzle_temperature": ["260"]})
    # A copy of the system name in a lower-priority folder must not win.
    write(tmp_path / "later", "x.json", {"name": "0.20mm Standard @Voron", "layer_height": "0.3"})
    return [str(user), str(system), str(tmp_path / "later")]


@pytest.fixture
def printer():
    return sl.Printer(id="workshop", name="Workshop", machine="Workshop", process="0.20mm Standard @Voron",
                      materials={"ASA": "My ASA"}, plate="High Temp Plate", tools=8)


# ── presets ──────────────────────────────────────────────────────────────────

def test_resolve_folds_parents_in_and_first_folder_wins(profiles):
    p = sl.Presets(profiles)
    m = p.resolve("Workshop")
    assert m["nozzle_diameter"] == ["0.4"] and m["machine_start_gcode"].startswith("PRINT_START")
    assert m["name"] == "Workshop" and "inherits" not in m
    assert p.resolve("0.20mm Standard @Voron")["layer_height"] == "0.2"


def test_a_parent_is_looked_up_in_its_own_vendor_like_orca_does(tmp_path):
    """fdm_klipper_common is in Custom/ and in Voron/ with different values; Custom sorts first. Orca gives a Voron
    machine Voron's base (found against a desktop file's own settings, 5 October 2026: jerk 12, not Custom's 9)."""
    system = tmp_path / "system"
    write(system, "Custom/machine/fdm_klipper_common.json", {"name": "fdm_klipper_common", "machine_max_jerk_x": ["9", "9"]})
    write(system, "Voron/machine/fdm_klipper_common.json", {"name": "fdm_klipper_common", "machine_max_jerk_x": ["12", "12"]})
    write(system, "Voron/machine/v24.json", {"name": "Voron 2.4 350", "inherits": "fdm_klipper_common"})
    user = tmp_path / "user"
    write(user, "machine/mine.json", {"name": "Mine", "inherits": "Voron 2.4 350"})
    p = sl.Presets([str(user), str(system)])
    assert p.resolve("Mine")["machine_max_jerk_x"] == ["12", "12"]
    assert p.resolve("fdm_klipper_common")["machine_max_jerk_x"] == ["9", "9"]     # asked by name: first folder wins
    assert sl.vendor_of(str(system), str(system / "Voron/machine/v24.json")) == "Voron"
    assert sl.vendor_of(str(user), str(user / "machine/mine.json")) == ""


def test_a_printer_json_learned_from_files_loads_its_own_presets_first(tmp_path):
    """docs/slicer-profile.md: the printer writes printer.json ("learned") and presets/0-learned/ from its files.
    0-learned sorts before 0-resolved and the person's own folders, so a name in both is the learned one."""
    sys.path.insert(0, str(HERE.parent.parent / "printer"))
    import orca_profile as op
    block = {"printer_settings_id": "Their Voron", "print_settings_id": "0.20mm Standard @Voron",
             "filament_settings_id": '"Their PLA"', "layer_height": "0.24", "seam_position": "back",
             "nozzle_diameter": "0.4", "printable_area": "0x0,300x0,300x300,0x300", "filament_type": "PLA",
             "nozzle_temperature": "245", "machine_start_gcode": r"PRINT_START BED=[bed_temperature_initial_layer_single]\nG90",
             "curr_bed_type": "Textured PEI Plate"}
    home = tmp_path / "elyir-bench-slicer"
    learned = op.presets(block, op.load_keys(), 0, "2.3.1")
    for kind, preset in learned.items():
        write(home / "presets" / "0-learned", op.preset_file(preset["name"]), preset)
    write(home / "presets" / "0-resolved", "std.json", {"name": "0.20mm Standard @Voron", "layer_height": "0.2"})
    write(home / "presets" / "2-local" / "process", "std.json", {"name": "0.20mm Standard @Voron", "layer_height": "0.3"})
    pj = {"machine": "Their Voron", "process": "0.20mm Standard @Voron", "plate": "Textured PEI Plate", "tools": 1,
          "materials": {"PLA": "Their PLA"}, "learned": {"id": "abcd1234", "at": 1, "from_files": ["a.gcode"]}}
    (home / "printer.json").write_text(json.dumps(pj))
    printer = sl.Printer.from_config("theirs", {**json.loads((home / "printer.json").read_text()),
                                                "presets": [str(home / "presets")]})
    presets = sl.Presets([*printer.presets])
    assert presets.resolve("0.20mm Standard @Voron")["layer_height"] == "0.24"     # not 0-resolved's, not 2-local's
    p = sl.plan(printer, sl.Request(purpose="everyday", material="PLA"), presets)
    assert p.process["seam_position"] == "back"
    assert p.machine["machine_start_gcode"] == "PRINT_START BED=[bed_temperature_initial_layer_single]\nG90"
    assert p.machine["printable_area"] == ["0x0", "300x0", "300x300", "0x300"] and sl.bed_of(p.machine)[:2] == [300, 300]
    assert p.filament["nozzle_temperature"] == ["245"] and p.process["curr_bed_type"] == "Textured PEI Plate"
    assert p.process["compatible_printers"] == ["Their Voron"] and p.machine["from"] == "system"


def test_every_file_this_slicer_writes_says_so_near_its_top(tmp_path):
    g = tmp_path / "plate_1.gcode"
    g.write_text("; HEADER_BLOCK_START\n; generated by OrcaSlicer 2.4.2 on 2026-10-05 at 10:00:00\n"
                 "; total layer number: 10\n; HEADER_BLOCK_END\nG28\n")
    sl.mark_ours(str(g))
    sl.mark_ours(str(g))                                              # once
    assert g.read_text().splitlines()[:3] == ["; HEADER_BLOCK_START", "; generated by OrcaSlicer 2.4.2 on 2026-10-05 at 10:00:00",
                                              "; sliced by Elyir Bench"]
    assert g.read_text().count("; sliced by Elyir Bench") == 1
    bare = tmp_path / "bare.gcode"
    bare.write_text("G28\nG1 X1\n")
    sl.mark_ours(str(bare))
    assert bare.read_text() == "; sliced by Elyir Bench\nG28\nG1 X1\n"


def test_missing_parent_and_loops_say_which(tmp_path):
    write(tmp_path, "a.json", {"name": "A", "inherits": "B"})
    write(tmp_path, "b.json", {"name": "B", "inherits": "A"})
    write(tmp_path, "c.json", {"name": "C", "inherits": "nowhere"})
    p = sl.Presets([str(tmp_path)])
    with pytest.raises(sl.PresetError, match="itself"):
        p.resolve("A")
    with pytest.raises(sl.PresetError, match="nowhere"):
        p.resolve("C")


def test_cli_presets_are_system_and_name_the_printer(profiles, printer):
    plan = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    assert plan.machine["type"] == "machine" and plan.machine["from"] == "system"
    assert plan.process["compatible_printers"] == ["Workshop"]
    assert plan.filament["compatible_printers"] == ["Workshop"] and plan.filament["type"] == "filament"


# ── purposes become changes, each with what it replaced and why ──────────────

def test_strong_changes_only_what_differs(profiles, printer):
    plan = sl.plan(printer, sl.Request(purpose="strong", material="ASA"), sl.Presets(profiles))
    by_key = {c.key: c for c in plan.changes}
    assert by_key["wall_loops"].was == "3" and by_key["wall_loops"].value == "5"
    assert by_key["sparse_infill_pattern"].value == "gyroid"
    assert "layer_height" not in by_key                   # 0.2 already
    assert all(c.why for c in plan.changes)
    assert plan.process["wall_loops"] == "5"


def test_every_purpose_is_a_complete_answer(profiles, printer):
    for purpose in sl.PURPOSES:
        plan = sl.plan(printer, sl.Request(purpose=purpose, material="ASA"), sl.Presets(profiles))
        assert plan.process["layer_height"] in ("0.12", "0.2", "0.28")


def test_supports_auto_and_off(profiles, printer):
    on = sl.plan(printer, sl.Request(material="ASA", supports="auto"), sl.Presets(profiles))
    off = sl.plan(printer, sl.Request(material="ASA", supports="off"), sl.Presets(profiles))
    assert on.process["enable_support"] == "1"
    # the kind of support is the preset's own, never swapped
    assert on.process["support_type"] == sl.Presets(profiles).resolve(printer.process).get("support_type")
    assert not [c for c in on.changes if c.key == "support_type"]
    assert off.process["enable_support"] == "0"
    assert not [c for c in off.changes if c.source == "supports"]   # already off: nothing to say


def test_supports_normal_or_tree(profiles, printer):
    """design/supports/, A: the person's kind. The preset prints normal, so asking for normal changes nothing more."""
    tree = sl.plan(printer, sl.Request(material="ASA", supports="tree"), sl.Presets(profiles))
    normal = sl.plan(printer, sl.Request(material="ASA", supports="normal"), sl.Presets(profiles))
    assert tree.process["support_type"] == "tree(auto)" and tree.process["enable_support"] == "1"
    assert [c.key for c in tree.changes if c.source == "supports"] == ["enable_support", "support_type"]
    assert normal.process["support_type"] == "normal(auto)"
    assert [c.key for c in normal.changes if c.source == "supports"] == ["enable_support"]
    assert sl.support_kind(sl.Presets(profiles).resolve(printer.process)) == "normal"
    assert sl.support_kind({"support_type": "tree(manual)"}) == "tree" and sl.support_kind({}) == "normal"


def test_a_persons_own_settings_go_last(profiles, printer):
    """design/edit-settings/, C: kept for the purpose, then this print's; each says whose it is."""
    req = sl.Request(material="ASA", kept={"wall_loops": "4"}, settings={"sparse_infill_density": "25", "wall_loops": 5})
    p = sl.plan(printer, req, sl.Presets(profiles))
    assert p.process["wall_loops"] == "5" and p.process["sparse_infill_density"] == "25%"
    mine = [(c.key, c.value, c.source) for c in p.changes if c.source in ("kept", "you")]
    assert mine == [("wall_loops", "4", "kept"), ("sparse_infill_density", "25%", "you"), ("wall_loops", "5", "you")]
    assert p.before["wall_loops"] == "3" and p.values["wall_loops"] == "5"
    assert "brim_type" not in p.values                          # per part now (design/brim/, A)
    strong = sl.plan(printer, sl.Request(purpose="strong", material="ASA", kept={"wall_loops": "6"}), sl.Presets(profiles))
    assert strong.before["wall_loops"] == "5" and "every Strong print" in [c for c in strong.changes if c.source == "kept"][0].why


def test_only_the_short_list_can_be_changed():
    assert sl.edit_value("layer_height", "0.16") == "0.16" and sl.edit_value("sparse_infill_density", "40%") == "40%"
    assert sl.edit_value("seam_position", "back") == "back"
    for key, value in [("nozzle_temperature", "250"), ("wall_loops", "0"), ("layer_height", "0.15"), ("sparse_infill_density", "33"),
                       ("brim_type", "painted"), ("wall_loops", "lots")]:
        with pytest.raises(ValueError):
            sl.edit_value(key, value)
    assert sl.Request(material="ASA", settings={"nozzle_temperature": "250"}).problems(
        sl.Printer(id="o", name="O", machine="m", process="p", materials={"ASA": "x"})) == ["nozzle_temperature can't be changed here"]


def test_petg_is_set_up_not_to_string(profiles, printer):
    printer.materials["PETG"] = "My ASA"           # the fixture's only filament preset; the material is what counts
    p = sl.plan(printer, sl.Request(material="PETG"), sl.Presets(profiles))
    assert p.filament["nozzle_temperature"] == ["235"] and p.filament["filament_retraction_length"] == ["1"]
    assert p.filament["filament_z_hop_types"] == ["Spiral Lift"] and p.process["reduce_crossing_wall"] == "1"
    why = {c.key: c for c in p.changes}
    assert why["reduce_crossing_wall"].source == "spool" and why["nozzle_temperature"].as_dict()["label"] == "Nozzle"
    assert "reduce_crossing_wall" not in sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles)).process or \
        sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles)).process["reduce_crossing_wall"] != "1"


def test_every_part_is_labelled_so_it_can_be_skipped(profiles, printer):
    p = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    assert p.process["exclude_object"] == "1" and p.process["gcode_label_objects"] == "1"
    assert sl.part_file(0, "bushing.stl", 7) == "p0c7__bushing.stl"
    assert sl.display_name("p0c7__buildplate_bushing_open.stl") == "Buildplate bushing open"


def test_plate_is_a_printer_fact(profiles, printer):
    """Orca defaults to Cool Plate, where this ASA says 0 °C: the bed would never heat."""
    plan = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    plate = [c for c in plan.changes if c.key == "curr_bed_type"]
    assert len(plate) == 1 and plate[0].source == "printer"
    assert plan.process["curr_bed_type"] == "High Temp Plate"


def test_a_printer_that_wipes_its_nozzle_gets_a_loop_around_the_part(profiles, printer):
    printer.skirt_loops = 1
    plan = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    skirt = [c for c in plan.changes if c.key == "skirt_loops"]
    assert plan.process["skirt_loops"] == "1" and skirt[0].source == "printer" and "brush" in skirt[0].why
    assert sl.Printer.from_config("x", {"machine": "m", "process": "p", "materials": {}, "skirt_loops": 1}).skirt_loops == 1


def test_spool_colour_goes_in_as_a_filament_list(profiles, printer):
    plan = sl.plan(printer, sl.Request(material="asa", color="#ff8800"), sl.Presets(profiles))
    assert plan.filament["filament_colour"] == ["#FF8800"]


def test_no_colour_chosen_is_no_colour_in_the_file(profiles, printer):
    """The preset's own colour (Anycubic's PETG: #F2754E) made a Kobra ask for red PETG nobody chose (8 October 2026)."""
    plan = sl.plan(printer, sl.Request(material="asa"), sl.Presets(profiles))
    assert plan.filament["filament_colour"] == [""] and not [c for c in plan.changes if c.key == "filament_colour"]


def test_request_problems(printer):
    assert sl.Request(material="ASA").problems(printer) == []
    bad = sl.Request(purpose="pretty", supports="maybe", material="NYLON", color="red", slot=8).problems(printer)
    assert len(bad) == 5


# ── what comes back ──────────────────────────────────────────────────────────

GCODE = """; HEADER_BLOCK_START
; total layer number: 127
; HEADER_BLOCK_END
PRINT_START EXTRUDER=260 BED=110 TOOL=0
;TYPE:Outer wall
G1 X1 Y1
;TYPE:Support
G1 X2 Y2
; MACRO TOOL=0 stays as it is
; filament used [g] = 11.10
; total filament used [g] = 11.10
; estimated printing time (normal mode) = 1h 2m 3s
"""


def test_read_result(tmp_path):
    g = tmp_path / "p.gcode"
    g.write_text(GCODE)
    assert sl.read_result(str(g)) == {"seconds": 3723, "grams": 11.1, "layers": 127, "supports": True, "grams_each": [11.1]}


SUPPORT_GCODE = """M83
;LAYER_CHANGE
;Z:0.2
;HEIGHT:0.2
G1 X10 Y10 Z0.2
;TYPE:Outer wall
G1 X20 Y10 E1
;TYPE:Support
G1 X20 Y20 E0.5
G1 X30 Y20
G1 X30 Y30 E-0.8
;TYPE:Support interface
G1 X40 Y30 E0.2
;LAYER_CHANGE
;HEIGHT:0.2
G1 Z0.4
;TYPE:Support
G1 X40 Y40 E0.3
"""


def test_support_lines_only_extruding_support_moves(tmp_path):
    g = tmp_path / "s.gcode"
    g.write_text(SUPPORT_GCODE)
    r = sl.support_lines(str(g))
    v = struct.unpack(f"<{r['count'] * 5}h", base64.b64decode(r["segs"]))
    # travel and retraction left out; interface counts; tenths of a mm
    assert r["count"] == 3 and r["width"] == 0.45
    assert v[:5] == (200, 100, 200, 200, 2) and v[5:10] == (300, 300, 400, 300, 2) and v[10:] == (400, 300, 400, 400, 4)
    thin = sl.support_lines(str(g), limit=1)          # every other layer left out, drawn wider to close the gap
    assert thin["count"] == 2 and thin["width"] == 0.6


LAYER_GCODE = """M82
G92 E0
;TYPE:Custom
G1 X0 Y0 E5
;LAYER_CHANGE
;Z:0.2
;HEIGHT:0.2
G1 Z0.6
G1 X10 Y10 Z0.2
;TYPE:Outer wall
G1 X20 Y10 E6
;TYPE:Inner wall
G1 X20 Y20 E7
;TYPE:Sparse infill
G1 X15 Y15 E7.5
G1 X5 Y5
;LAYER_CHANGE
;Z:0.4
;HEIGHT:0.2
G1 Z0.4
;TYPE:Outer wall
G1 X30 Y10 E8
;TYPE:Support interface
G1 X30 Y30 E8.2
G1 X40 Y30 E8.1
"""


def _unpack(r, key="segs", n=5):
    return struct.unpack(f"<{r['count'] * n}h", base64.b64decode(r[key]))


def test_layers_read_once_then_one_at_a_time(tmp_path):
    g = tmp_path / "l.gcode"
    g.write_text(LAYER_GCODE)
    public, starts = sl.layer_index(str(g))
    # the start G-code's purge isn't a layer; a z-hop doesn't move the layer; absolute E counted from G92
    assert public["count"] == 2 and public["z"] == [0.2, 0.4]
    assert public["walls"]["count"] == 2
    assert _unpack(public["walls"]) == (100, 100, 200, 100, 2, 50, 50, 300, 100, 4)
    assert struct.unpack("<2H", base64.b64decode(public["walls"]["layer"])) == (0, 1)
    first = sl.layer_paths(str(g), starts[0][0], starts[1][0], starts[0][1], 0.2)
    assert list(base64.b64decode(first["kinds"])) == [sl.WALL, sl.INNER, sl.INFILL]
    assert _unpack(first)[10:] == (200, 200, 150, 150, 2)
    last = sl.layer_paths(str(g), starts[1][0], None, starts[1][1], 0.4)
    # the nozzle's place carries over from the layer before; a retraction draws nothing
    assert _unpack(last) == (50, 50, 300, 100, 4, 300, 100, 300, 300, 4)
    assert list(base64.b64decode(last["kinds"])) == [sl.WALL, sl.SUPPORT]
    thin, _ = sl.layer_index(str(g), limit=1)
    assert thin["walls"]["count"] == 1 and thin["width"] == 0.45


def test_use_slot_rewrites_only_the_start_macro(tmp_path):
    g = tmp_path / "p.gcode"
    g.write_text(GCODE)
    assert sl.use_slot(str(g), 5)
    text = g.read_text()
    assert "PRINT_START EXTRUDER=260 BED=110 TOOL=5" in text
    assert "; MACRO TOOL=0 stays as it is" in text
    assert "\nT5\n" not in text


def test_with_a_unit_the_slot_is_loaded_after_the_start_too(tmp_path):
    # the filament-unit service's start macro doesn't load TOOL= (found on the main test printer, 21 October 2026)
    g = tmp_path / "p.gcode"
    g.write_text(GCODE.replace(" TOOL=0", ""))
    assert sl.use_slot(str(g), 0, load=True)
    text = g.read_text()
    assert text.index("PRINT_START") < text.index("\nT0\n")


def test_names_read_like_orcas():
    assert sl.gcode_name("/x/soldering iron mount.stl", "asa", 2914) == "soldering_iron_mount_ASA_48m34s.gcode"
    assert sl.short_duration(4560) == "1h16m"
    assert sl.parse_duration(" 1d 2h 3m 4s") == 93784


def test_explain_in_plain_words():
    assert sl.explain("plate 1: Nothing to be sliced, ... no object is fully inside the print volume", "Workshop") \
        == "It doesn't fit on Workshop's bed."
    assert "details" in sl.explain("something new", "Workshop")


# ── the service, against a fake Orca and a fake Moonraker ────────────────────

FAKE_ORCA = """#!/usr/bin/env python3
import json, os, sys, zipfile
a = sys.argv
out = a[a.index("--outputdir") + 1]
settings = a[a.index("--load-settings") + 1].split(";")
proc = json.load(open(settings[1]))
if "toobig" in a[-1]:
    print("[error] plate 1: Nothing to be sliced, no object is fully inside the print volume")
    sys.exit(1)
models = a[a.index("--export-3mf") + 2:] if "--export-3mf" in a else [a[-1]]
PER_PLATE = 25                                   # like 40 x 50 mm bushings on a 350 mm bed
plates = [[(os.path.basename(m), proc.get("brim_type", "auto_brim")) for m in models[i:i + PER_PLATE]]
          for i in range(0, len(models), PER_PLATE)]
if a[-1].endswith(".3mf"):                       # an arranged plate sliced as it is: each object's own brim
    import xml.etree.ElementTree as ET
    root = ET.fromstring(zipfile.ZipFile(a[-1]).read("Metadata/model_settings.config"))
    meta = lambda e, k: next((m.get("value") for m in e.findall("metadata") if m.get("key") == k), None)
    objs = {o.get("id"): (meta(o, "name"), meta(o, "brim_type") or proc.get("brim_type", "auto_brim")) for o in root.iter("object")}
    plates = [[objs[meta(i, "object_id")] for i in p.iter("model_instance")] for p in root.iter("plate")]
if "--slice" in a:
    for k, on in enumerate(plates, 1):
        open(os.path.join(out, f"plate_{k}.gcode"), "w").write(
            "; total layer number: 10\\nPRINT_START BED=110 TOOL=0\\n"
            f"; wall_loops = {proc['wall_loops']}\\n" + "".join(f"; brim {n} = {b}\\n" for n, b in on) +
            f"; total filament used [g] = {2.5 * len(on):.2f}\\n; estimated printing time (normal mode) = {5 * len(on)}m 1s\\n")
if "--export-3mf" in a:
    objs, items, plate_xml, named = [], [], [], []
    for k, on in enumerate(plates, 1):
        inst = []
        for j, (m, _) in enumerate(on):
            oid = 2 * (len(objs) + 1)
            named.append(f'<object id="{oid}"><metadata key="name" value="{m}"/></object>')
            objs.append(f'<object id="{oid}" type="model"><components><component p:path="/3D/Objects/{os.path.basename(m)}_{oid}.model" '
                        f'objectid="{oid - 1}" transform="1 0 0 0 1 0 0 0 1 5 5 3"/></components></object>')
            # turned a quarter: x' = -y, y' = x
            items.append(f'<item objectid="{oid}" transform="0 1 0 -1 0 0 0 0 1 {100 + 60 * (j % 5) + 1000 * (k - 1)} {40 + 60 * (j // 5)} 0"/>')
            inst.append(f'<model_instance><metadata key="object_id" value="{oid}"/></model_instance>')
        plate_xml.append(f'<plate><metadata key="plater_id" value="{k}"/>{"".join(inst)}</plate>')
    with zipfile.ZipFile(os.path.join(out, a[a.index("--export-3mf") + 1]), "w") as z:
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
                   'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"><resources>'
                   + "".join(objs) + "</resources><build>" + "".join(items) + "</build></model>")
        z.writestr("Metadata/model_settings.config", "<config>" + "".join(named) + "".join(plate_xml) + "</config>")
"""


class FakeMoonraker:
    def __init__(self):
        self.uploads = []
        self.db = {}

    def app(self):
        app = web.Application()

        async def upload(r):
            form = await r.post()
            f = form["file"]
            self.uploads.append({"name": f.filename, "body": f.file.read().decode(), "print": form.get("print")})
            return web.json_response({"item": {"path": f.filename, "root": "gcodes"},
                                      "print_started": form.get("print") == "true", "action": "create_file"})
        async def db_item(r):
            body = await r.json()
            self.db[(body["namespace"], body["key"])] = body["value"]
            return web.json_response({"namespace": body["namespace"], "key": body["key"], "value": body["value"]})
        app.router.add_post("/server/files/upload", upload)
        async def db_get(r):
            key = (r.query["namespace"], r.query["key"])
            if key not in self.db:
                return web.json_response({"error": {"code": 404}}, status=404)
            return web.json_response({"result": {"namespace": key[0], "key": key[1], "value": self.db[key]}})
        app.router.add_post("/server/database/item", db_item)
        app.router.add_get("/server/database/item", db_get)
        return app


@pytest.fixture
async def rig(tmp_path, profiles, aiohttp_server, aiohttp_client):
    orca = tmp_path / "orca"
    orca.write_text(FAKE_ORCA)
    orca.chmod(orca.stat().st_mode | stat.S_IEXEC)
    moon = FakeMoonraker()
    mserver = await aiohttp_server(moon.app())
    config = {
        "orca": [sys.executable, str(orca)], "nice": 0, "profiles": profiles,
        "origins": ["http://localhost:5173"],
        "printers": {"workshop": {"name": "Workshop", "machine": "Workshop", "process": "0.20mm Standard @Voron",
                              "plate": "High Temp Plate", "tools": 8, "materials": {"ASA": "My ASA"},
                              "moonraker": f"http://127.0.0.1:{mserver.port}"}},
    }
    svc = S.Service(config, str(tmp_path / "work"))
    client = await aiohttp_client(svc.app())
    return client, moon, svc


def model_form(name="bracket.stl", **fields):
    form = FormData()
    form.add_field("model", b"solid x\nendsolid x\n", filename=name)
    for k, v in fields.items():
        form.add_field(k, str(v))
    return form


async def wait_done(client, jid):
    for _ in range(100):
        d = await (await client.get(f"/slice/{jid}")).json()
        if d["state"] in ("done", "failed"):
            return d
        await asyncio.sleep(0.05)
    raise AssertionError("slice never finished")


async def test_slice_then_send(rig):
    client, moon, _ = rig
    r = await client.post("/slice", data=model_form(printer="workshop", purpose="strong", material="ASA",
                                                    color="#202020", slot=4))
    assert r.status == 202
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done", d
    assert d["gcode"] == "bracket_ASA_5m1s.gcode"
    assert d["estimate"] == {"seconds": 301, "time": "5m1s", "grams": 2.5, "layers": 10}
    assert d["request"]["slot"] == 3 and d["warnings"] == []
    assert {"wall_loops", "curr_bed_type", "filament_colour"} <= {c["key"] for c in d["changes"]}

    body = await (await client.get(f"/slice/{d['id']}/gcode")).text()
    assert "TOOL=3" in body and "; wall_loops = 5" in body
    assert body.splitlines()[0] == "; sliced by Elyir Bench"          # so the printer never learns from it
    assert d["values"]["wall_loops"] == "5" and d["before"]["wall_loops"] == "5"
    lines = await (await client.get(f"/slice/{d['id']}/supports")).json()
    assert set(lines) == {"count", "width", "segs"}

    sent = await (await client.post(f"/slice/{d['id']}/send")).json()
    assert sent == {"sent": "bracket_ASA_5m1s.gcode", "printing": False, "later": []}
    assert moon.uploads[0]["print"] is None and "TOOL=3" in moon.uploads[0]["body"]


async def test_a_slot_the_start_gcode_cant_take_is_loaded_after_it(rig, tmp_path):
    client, _, svc = rig
    orca = Path(svc.orca[1])
    orca.write_text(orca.read_text().replace("PRINT_START BED=110 TOOL=0", "PRINT_START BED=110"))
    r = await client.post("/slice", data=model_form(printer="workshop", material="ASA", slot=2))
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done" and not d["warnings"]
    body = await (await client.get(f"/slice/{d['id']}/gcode")).text()
    assert "PRINT_START BED=110\nT1\n" in body


async def test_send_and_print_only_when_asked(rig):
    client, moon, _ = rig
    r = await client.post("/slice", data=model_form(printer="workshop", material="ASA"))
    d = await wait_done(client, (await r.json())["id"])
    sent = await (await client.post(f"/slice/{d['id']}/send", json={"print": True})).json()
    assert sent["printing"] is True and moon.uploads[0]["print"] == "true"


async def test_bad_requests_are_refused_before_slicing(rig, tmp_path):
    client, _, svc = rig
    r = await client.post("/slice", data=model_form(printer="workshop", material="NYLON"))
    assert r.status == 400 and "NYLON" in (await r.json())["error"]
    r = await client.post("/slice", data=model_form(name="photo.jpg", printer="workshop"))
    assert r.status == 400
    r = await client.post("/slice", data=model_form(printer="nobody"))
    assert r.status == 400
    r = await client.post("/slice", data=model_form(printer="workshop", material="ASA", settings="walls please"))
    assert r.status == 400 and "settings must be" in (await r.json())["error"]
    assert not svc.jobs and not any((tmp_path / "work").iterdir())     # nothing left behind


async def test_a_failed_slice_says_why_in_plain_words(rig):
    client, _, _ = rig
    r = await client.post("/slice", data=model_form(name="toobig.stl", printer="workshop", material="ASA"))
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "failed"
    assert d["error"] == "It doesn't fit on Workshop's bed."
    assert "fully inside" in d["error_detail"]
    assert (await client.get(f"/slice/{d['id']}/gcode")).status == 409


async def test_a_cancelled_slice_never_runs(rig, tmp_path):
    client, _, svc = rig
    orca = Path(svc.orca[1])
    orca.write_text(orca.read_text().replace("a = sys.argv", "import time; time.sleep(0.4)\na = sys.argv"))
    first = await (await client.post("/slice", data=model_form(printer="workshop", material="ASA"))).json()
    second = await (await client.post("/slice", data=model_form(printer="workshop", material="ASA"))).json()
    await asyncio.sleep(0.1)                                   # the first is slicing, the second queued
    for jid in (first["id"], second["id"]):
        d = await (await client.delete(f"/slice/{jid}")).json()
        assert d["state"] == "cancelled"
    await asyncio.sleep(0.8)
    for jid in (first["id"], second["id"]):
        d = await (await client.get(f"/slice/{jid}")).json()
        assert d["state"] == "cancelled" and "gcode" not in d


async def test_options_and_cors(rig):
    client, _, _ = rig
    r = await client.get("/slice/options", headers={"Origin": "http://localhost:5173"})
    d = await r.json()
    assert [p["id"] for p in d["purposes"]] == ["draft", "everyday", "display", "strong"]
    assert d["printers"][0] == {"id": "workshop", "name": "Workshop", "materials": ["ASA"], "slots": 8,
                                "bed": [350.0, 350.0, 0.0], "base": "0.20mm Standard @Voron", "supports": "normal",
                                "unit": True, "purges": ["tower"], "change_seconds": 105}
    assert d["supports"] == ["auto", "normal", "tree", "off"]
    walls = next(e for e in d["editable"] if e["key"] == "wall_loops")
    assert walls["label"] == "Walls" and (walls["min"], walls["max"], walls["step"]) == (1, 10, 1)
    assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    r = await client.get("/slice/options", headers={"Origin": "http://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


# ── models: measured, resized, pictured ──────────────────────────────────────

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAYAAAC56t6BAAAAEklEQVR4nGP4z8DwnwEIGBgYAEb2Avyh0rr+AAAAAElFTkSuQmCC")


def binary_stl(path: Path, size: float) -> None:
    text = _cube_stl(size)
    tris = [tuple(float(v) for v in l.split()[1:]) for l in text.splitlines() if l.strip().startswith("vertex")]
    out = bytearray(b"\0" * 80 + struct.pack("<I", len(tris) // 3))
    for i in range(0, len(tris), 3):
        out += struct.pack("<12fH", 0, 0, 0, *[c for v in tris[i:i + 3] for c in v], 0)
    path.write_bytes(bytes(out))


def test_model_size_reads_binary_and_text_stl_and_obj(tmp_path):
    binary_stl(tmp_path / "b.stl", 20)
    (tmp_path / "t.stl").write_text(_cube_stl(30))
    (tmp_path / "m.obj").write_text("v 0 0 0\nv 10 4 2\nf 1 2 1\n")
    assert sl.model_size(str(tmp_path / "b.stl")) == [20, 20, 20]
    assert sl.model_size(str(tmp_path / "t.stl")) == [30, 30, 30]
    assert sl.model_size(str(tmp_path / "m.obj")) == [10, 4, 2]
    (tmp_path / "x.step").write_text("ISO-10303-21;")
    assert sl.model_size(str(tmp_path / "x.step")) is None


def test_fit_scale_is_whole_percent_and_never_grows():
    assert sl.fit_scale([412, 190, 140], [350, 350, 340]) == 0.83   # 350 x 0.98 / 412, rounded down
    assert sl.fit_scale([46, 34, 25], [350, 350, 340]) == 1.0
    assert sl.fit_scale(None, [350, 350, 340]) == 1.0
    assert sl.fit_scale([100, 100, 500], [350, 350, 340]) == 0.68   # too tall: 340 / 500


def test_scale_model_keeps_the_format(tmp_path):
    binary_stl(tmp_path / "b.stl", 20)
    (tmp_path / "t.stl").write_text(_cube_stl(30))
    sl.scale_model(str(tmp_path / "b.stl"), str(tmp_path / "b2.stl"), 0.5)
    sl.scale_model(str(tmp_path / "t.stl"), str(tmp_path / "t2.stl"), 0.5)
    assert sl.model_size(str(tmp_path / "b2.stl")) == [10, 10, 10]
    assert sl.model_size(str(tmp_path / "t2.stl")) == [15, 15, 15]


def test_embed_thumbnail_the_way_moonraker_reads_it(tmp_path):
    g = tmp_path / "p.gcode"
    g.write_text(GCODE)
    sl.embed_thumbnail(str(g), PNG)
    lines = g.read_text().splitlines()
    i = lines.index("; HEADER_BLOCK_END")
    assert lines[i + 2].startswith("; thumbnail begin 2x3 ")
    b64 = "".join(l[2:] for l in lines[i + 3:lines.index("; thumbnail end")])
    assert base64.b64decode(b64) == PNG
    with pytest.raises(ValueError):
        sl.png_size(b"GIF89a")


async def test_upload_once_slice_many(rig, tmp_path):
    client, moon, _ = rig
    form = FormData()
    form.add_field("model", _cube_stl(40).encode(), filename="cube.stl")
    m = await (await client.post("/slice/models", data=form)).json()
    assert m["name"] == "cube.stl" and m["size"] == [40, 40, 40]
    ids = []
    for purpose in ("everyday", "strong"):
        r = await client.post("/slice", json={"model": m["model"], "printer": "workshop", "purpose": purpose,
                                              "material": "ASA", "slot": 2, "scale": 0.5,
                                              "thumbnail": base64.b64encode(PNG).decode()})
        assert r.status == 202, await r.text()
        ids.append((await r.json())["id"])
    for jid in ids:
        d = await wait_done(client, jid)
        assert d["state"] == "done" and d["parts"] == [{"model": "cube.stl", "copies": 1, "scale": 0.5, "lay": "file", "brim": "auto", "spool": 0,
                                                       "brim_pick": {"kind": "none", "why": "Low and wide on 4 cm²: it stays down by itself", "by": "auto", "rule": "none"}}]
        body = await (await client.get(f"/slice/{jid}/gcode")).text()
        assert "; thumbnail begin 2x3" in body and "TOOL=1" in body
    assert all(c["label"] for c in d["changes"])


async def test_json_slice_refusals(rig):
    client, _, _ = rig
    r = await client.post("/slice", json={"model": "nope", "printer": "workshop"})
    assert r.status == 400 and "upload" in (await r.json())["error"]
    form = FormData()
    form.add_field("model", b"ISO-10303-21;", filename="part.step")
    m = await (await client.post("/slice/models", data=form)).json()
    assert m["size"] is None
    r = await client.post("/slice", json={"model": m["model"], "printer": "workshop", "material": "ASA", "scale": 0.5})
    assert r.status == 400 and "resized" in (await r.json())["error"]
    r = await client.post("/slice", json={"model": m["model"], "printer": "workshop", "material": "ASA", "thumbnail": "!!"})
    assert r.status == 400


# ── which way down (design/orientation/, A) ──────────────────────────────────

def plate_stl(path: Path, tilt_deg: float) -> None:
    """A 30 x 20 x 3 mm plate, tipped up by tilt_deg about the X axis and resting on its lowest point."""
    import math
    t = math.radians(tilt_deg)
    def rot(v):
        x, y, z = v
        return (x, y * math.cos(t) - z * math.sin(t), y * math.sin(t) + z * math.cos(t))
    V = [rot(v) for v in [(x, y, z) for x in (0, 30) for y in (0, 20) for z in (0, 3)]]
    zmin = min(v[2] for v in V)
    V = [(x, y, z - zmin) for x, y, z in V]
    F = [(0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3), (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6)]
    out = bytearray(b"\0" * 80 + struct.pack("<I", len(F)))
    for f in F:
        out += struct.pack("<12fH", 0, 0, 0, *[c for i in f for c in V[i]], 0)
    path.write_bytes(bytes(out))


def test_a_plate_on_its_edge_is_laid_flat_and_a_flat_one_is_left(tmp_path):
    plate_stl(tmp_path / "edge.stl", 60)
    plate_stl(tmp_path / "flat.stl", 0)
    edge, flat = sl.lying(str(tmp_path / "edge.stl")), sl.lying(str(tmp_path / "flat.stl"))
    assert edge["flat_better"] and edge["down_area"] == 0 and edge["flat_area"] == 600
    assert not flat["flat_better"] and flat["down_area"] == 600
    assert sl.size_laid_flat(str(tmp_path / "edge.stl"), edge["flat_normal"]) == [30, 20, 3]
    sl.lay_flat(str(tmp_path / "edge.stl"), str(tmp_path / "laid.stl"), edge["flat_normal"])
    laid = sl.lying(str(tmp_path / "laid.stl"))
    assert laid["down_area"] == 600 and not laid["flat_better"]


def test_a_cube_is_never_turned(tmp_path):
    (tmp_path / "c.stl").write_text(_cube_stl(20))
    assert not sl.lying(str(tmp_path / "c.stl"))["flat_better"]


async def test_lay_flat_turns_before_slicing_and_says_so(rig, tmp_path):
    client, _, _ = rig
    plate_stl(tmp_path / "edge.stl", 60)
    form = FormData()
    form.add_field("model", (tmp_path / "edge.stl").read_bytes(), filename="edge.stl")
    m = await (await client.post("/slice/models", data=form)).json()
    assert m["lying"]["flat_better"] and m["lying"]["size_flat"] == [30, 20, 3]
    r = await client.post("/slice", json={"model": m["model"], "printer": "workshop", "material": "ASA", "lay": "flat"})
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done" and d["parts"][0]["lay"] == "flat"
    lying = [c for c in d["changes"] if c["key"] == "orientation"]
    assert lying and lying[0]["source"] == "model" and lying[0]["label"] == "Lying"
    assert (await client.post("/slice", json={"model": m["model"], "printer": "workshop", "material": "ASA", "lay": "upside"})).status == 400


# ── more than one on the plate (design/plate/, A) ─────────────────────────────

async def _upload(client, name, body):
    form = FormData()
    form.add_field("model", body.encode() if isinstance(body, str) else body, filename=name)
    return (await (await client.post("/slice/models", data=form)).json())["model"]


async def test_different_parts_on_one_plate(rig):
    client, moon, _ = rig
    arm, knife = await _upload(client, "[a]_cutting_arm_g2e.stl", _cube_stl(20)), await _upload(client, "knife.stl", _cube_stl(8))
    r = await client.post("/slice", json={"parts": [{"model": arm}, {"model": knife, "copies": 2}],
                                          "printer": "workshop", "material": "ASA"})
    assert r.status == 202, await r.text()
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done", d
    assert [p["copies"] for p in d["parts"]] == [1, 2]
    assert d["plates"] == [{"plate": 1, "seconds": 901, "time": "15m1s", "grams": 7.5, "counts": [1, 2],
                            "gcode": "cutting_arm_g2e_and_1_more_ASA_15m1s.gcode"}]
    # where Orca put each copy: the centre of its box on the bed, and how far it turned it
    assert d["placed"][0] == {"part": 0, "x": 95.0, "y": 45.0, "turn": 90.0}
    assert [p["part"] for p in d["placed"]] == [0, 1, 1]
    sent = await (await client.post(f"/slice/{d['id']}/send")).json()
    assert sent["later"] == [] and ("elyir-bench", "next_plates") not in moon.db


async def test_what_doesnt_fit_goes_on_a_second_plate_and_is_noted_for_now(rig):
    client, moon, _ = rig
    bushing = await _upload(client, "[a]_buildplate_bushing_open_x1_r1s.stl", _cube_stl(30))
    r = await client.post("/slice", json={"parts": [{"model": bushing, "copies": 30}], "printer": "workshop", "material": "ASA"})
    d = await wait_done(client, (await r.json())["id"])
    assert [(p["plate"], p["counts"]) for p in d["plates"]] == [(1, [25]), (2, [5])]
    assert d["plates"][0]["gcode"] == "buildplate_bushing_open_x25_1of2_ASA_2h5m.gcode"
    assert d["plates"][1]["gcode"] == "buildplate_bushing_open_x5_2of2_ASA_25m1s.gcode"
    assert d["estimate"]["seconds"] == 125 * 60 + 1 and len(d["placed"]) == 25
    sent = await (await client.post(f"/slice/{d['id']}/send", json={"print": True})).json()
    assert sent["printing"] and sent["later"] == [d["plates"][1]["gcode"]]
    assert [u["print"] for u in moon.uploads] == ["true", None]
    assert moon.db[("elyir-bench", "next_plates")] == [{"after": d["plates"][0]["gcode"], "file": d["plates"][1]["gcode"],
                                                     "count": 5, "what": "5 copies of buildplate bushing open"}]


async def test_how_many_fit(rig):
    client, _, _ = rig
    bushing = await _upload(client, "bushing.stl", _cube_stl(40))
    r = await client.post("/slice/fit", json={"parts": [{"model": bushing, "copies": 3}], "part": 0, "printer": "workshop"})
    assert await r.json() == {"part": 0, "fits": 25, "others_fit": True, "at_least": False}
    assert (await client.post("/slice/fit", json={"parts": [{"model": bushing}], "part": 4, "printer": "workshop"})).status == 400


async def test_what_fits_of_several_parts_as_they_are(rig):
    client, _, _ = rig
    a, b = await _upload(client, "stand.stl", _cube_stl(40)), await _upload(client, "clip.stl", _cube_stl(10))
    r = await client.post("/slice/fit", json={"parts": [{"model": a, "copies": 2}, {"model": b, "copies": 4}], "part": None, "printer": "workshop"})
    assert await r.json() == {"counts": [2, 4], "plates": 1, "fits": True}
    r = await client.post("/slice/fit", json={"parts": [{"model": a, "copies": 2}, {"model": b, "copies": 30}], "part": None, "printer": "workshop"})
    assert await r.json() == {"counts": [2, 23], "plates": 2, "fits": False}          # the stand-in puts 25 on a plate


async def test_parts_are_checked(rig):
    client, _, _ = rig
    m = await _upload(client, "a.stl", _cube_stl(10))
    for bad in ([], [{"model": m, "copies": 0}], [{"model": m, "copies": 999}], [{"model": "nope"}], "a.stl"):
        r = await client.post("/slice", json={"parts": bad, "printer": "workshop", "material": "ASA"})
        assert r.status == 400, bad


def test_names_for_people_and_plates():
    assert sl.display_name("[a]_buildplate_bushing_open_x1_r1s.stl") == "Buildplate bushing open"
    assert sl.display_name("p3__phone-stand.STL") == "Phone stand"
    assert sl.plural("Bushing", 5) == "5 bushings" and sl.plural("Knife holder", 1) == "1 knife holder"
    assert sl.plural("Box", 2) == "2 boxes" and sl.plural("Battery cover", 3) == "3 battery covers"
    assert sl.plate_words(["a.stl", "b.stl"], [2, 3]) == "5 parts"
    assert sl.gcode_name("mount.stl", "petg", 208) == "mount_PETG_3m28s.gcode"
    assert sl.gcode_name("p0__mount.stl", "PETG", 208, [4]) == "mount_x4_PETG_3m28s.gcode"
    assert sl.gcode_name("arm.stl", "PETG", 60, [1, 0, 2], 2, 3) == "arm_and_1_more_2of3_PETG_1m0s.gcode"
    assert sl.fit_guess([40, 50, 6], [350, 350, 340]) == 76 and sl.fit_guess(None, None) == 50
    assert sl.fit_guess([6, 16, 8], [350, 350, 340]) == sl.FIT_CAP


async def test_a_sent_plate_is_remembered_so_a_skipped_part_can_print_again(rig, tmp_path):
    """design/skip-objects/: Finished offers to print a skipped part again, from the same model, the same way."""
    client, moon, svc = rig
    _boxes_stl(tmp_path / "block.stl", [((0, 0, 0), (30, 20, 10))])
    form = FormData()
    form.add_field("model", (tmp_path / "block.stl").read_bytes(), filename="block.stl")
    m = (await (await client.post("/slice/models", data=form)).json())["model"]
    r = await client.post("/slice", json={"parts": [{"model": m, "copies": 3, "lay": "side", "down": [1.0, 0.0, 0.0]}],
                                          "printer": "workshop", "purpose": "strong", "material": "ASA", "slot": 2})
    d = await wait_done(client, (await r.json())["id"])
    await client.post(f"/slice/{d['id']}/send")
    rec = moon.db[("elyir-bench", "sliced")][d["gcode"]]
    assert rec["parts"] == [{"model": m, "name": "block.stl", "scale": 1.0, "lay": "side", "brim": "auto", "down": [1.0, 0.0, 0.0]}]
    assert rec["purpose"] == "strong" and rec["material"] == "ASA" and rec["slot"] == 2
    svc.models.clear()                                    # a restart: the file is still on disk for a day
    f = await client.get(f"/slice/models/{m}/file")
    assert f.status == 200 and await f.read() == (tmp_path / "block.stl").read_bytes()
    again = await client.post("/slice", json={"parts": [{"model": m, "copies": 1}], "printer": "workshop", "material": "ASA"})
    assert again.status == 202
    assert (await client.get("/slice/models/000000000000/file")).status == 404


# ── the real Orca, when it's here ────────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(REAL_ORCA), reason="OrcaSlicer isn't installed here")
def test_real_orca_slices_a_cube(tmp_path, profiles):
    """Uses Orca's bundled Voron presets, so it runs on any Mac with Orca installed."""
    bundled = "/Applications/OrcaSlicer.app/Contents/Resources/profiles"
    presets = sl.Presets([bundled])
    machine = next(n for n in presets.by_name if n == "Voron 2.4 350 0.4 nozzle")
    printer = sl.Printer(id="v", name="Voron", machine=machine, process="0.20mm Standard @Voron",
                         materials={"ASA": "Generic ASA @System"}, plate="High Temp Plate", tools=4)
    plan = sl.plan(printer, sl.Request(purpose="draft", material="ASA", slot=2), presets)
    sl.write_plan(plan, str(tmp_path))
    (tmp_path / "out").mkdir()
    cube = tmp_path / "cube.stl"
    cube.write_text(_cube_stl(20))
    import subprocess
    subprocess.run(sl.orca_command([REAL_ORCA], str(tmp_path), str(cube), str(tmp_path / "out"), False),
                   check=True, capture_output=True, timeout=120)
    g = str(tmp_path / "out" / "plate_1.gcode")
    # Orca's stock Voron start G-code passes no TOOL=, so there's no slot to point at.
    assert not sl.use_slot(g, 2)
    res = sl.read_result(g)
    assert res["layers"] and res["seconds"] and res["grams"]
    text = Path(g).read_text()
    assert "; layer_height = 0.28" in text and "; curr_bed_type = High Temp Plate" in text


def _cube_stl(size: float) -> str:
    v = [(x, y, z) for x in (0, size) for y in (0, size) for z in (0, size)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    out = ["solid cube"]
    for a, b, c in faces:
        out += ["facet normal 0 0 0", " outer loop"] + [f"  vertex {' '.join(map(str, v[i]))}" for i in (a, b, c)] \
            + [" endloop", "endfacet"]
    return "\n".join(out + ["endsolid cube"]) + "\n"


# ── which side down: real contact, and any side (design/orientation/) ─────────

def _boxes_stl(path: Path, boxes) -> None:
    F = [(0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3), (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6)]
    tris = []
    for (x0, y0, z0), (x1, y1, z1) in boxes:
        V = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        tris += [[V[i] for i in f] for f in F]
    out = bytearray(b"\0" * 80 + struct.pack("<I", len(tris)))
    for t in tris:
        out += struct.pack("<12fH", 0, 0, 0, *[c for v in t for c in v], 0)
    path.write_bytes(bytes(out))


def test_a_side_is_what_touches_the_plate_not_every_face_that_way(tmp_path):
    # a 30 x 20 x 10 block with a 30 x 20 x 5 step beside it: two tops face up, only the higher one would rest on the plate
    _boxes_stl(tmp_path / "step.stl", [((0, 0, 0), (30, 20, 10)), ((30, 0, 0), (60, 20, 5))])
    up = next(s for s in sl.sides(str(tmp_path / "step.stl")) if s["normal"][2] > 0.99)
    assert up["contact"] == 600 and up["size"] == [60, 20, 10]
    down = next(s for s in sl.sides(str(tmp_path / "step.stl")) if s["normal"][2] < -0.99)
    assert down["contact"] == 1200, "the bottom is one plane: both blocks touch"
    assert sl.lying(str(tmp_path / "step.stl"))["flat_better"] is False


async def test_a_part_lies_on_the_side_picked(rig, tmp_path):
    client, _, _ = rig
    _boxes_stl(tmp_path / "block.stl", [((0, 0, 0), (30, 20, 10))])
    form = FormData()
    form.add_field("model", (tmp_path / "block.stl").read_bytes(), filename="block.stl")
    m = await (await client.post("/slice/models", data=form)).json()
    assert len(m["lying"]["sides"]) == 6
    side = [1.0, 0.0, 0.0]
    r = await client.post("/slice", json={"parts": [{"model": m["model"], "lay": "side", "down": side}], "printer": "workshop", "material": "ASA"})
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done" and d["parts"][0] == {"model": "block.stl", "copies": 1, "scale": 1, "lay": "side", "down": side, "brim": "auto", "spool": 0,
                                                      "brim_pick": {"kind": "all", "why": "30 mm tall on a 10 mm base: a rim keeps it standing", "by": "auto", "rule": "all"}}
    assert [c["value"] for c in d["changes"] if c["key"] == "orientation"] == ["on the side you picked"]
    assert (await client.post("/slice", json={"parts": [{"model": m["model"], "lay": "side"}], "printer": "workshop", "material": "ASA"})).status == 400


async def test_the_pressure_advance_tower(rig, tmp_path):
    client, _, _ = rig
    r = await client.post("/slice/test", json={"printer": "workshop", "test": "pressure_advance", "material": "ASA", "slot": 3})
    assert r.status == 202, await r.text()
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done" and d["gcode"].startswith("pressure_advance_test_ASA")
    body = await (await client.get(f"/slice/{d['id']}/gcode")).text()
    lines = body.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("PRINT_START"))
    assert "TOOL=2" in lines[i]
    assert lines[i + 1] == "SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=1 ACCEL=500"
    assert lines[i + 2] == "TUNING_TOWER COMMAND=SET_PRESSURE_ADVANCE PARAMETER=ADVANCE START=0 FACTOR=0.0025"
    assert "; wall_loops = 1" in body
    assert (await client.post("/slice/test", json={"printer": "workshop", "test": "flow", "material": "ASA"})).status == 400
    sl.pa_tower_stl(str(tmp_path / "t.stl"))
    assert sl.model_size(str(tmp_path / "t.stl")) == [50, 51.2, 34]


# ── 3MF read as its parts ─────────────────────────────────────────────────────

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _cube_mesh(size: float) -> str:
    v = [(x, y, z) for x in (0, size) for y in (0, size) for z in (0, size)]
    f = [(0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3), (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6)]
    return ("<mesh><vertices>" + "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in v) + "</vertices><triangles>"
            + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in f) + "</triangles></mesh>")


def _three_mf(path: Path, model: str, extra: dict = None) -> None:
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
        for k, v in (extra or {}).items():
            z.writestr(k, v)


def test_a_plain_3mf_two_bodies_together_and_copies_counted(tmp_path):
    # a CAD export: two bodies touching (one thing), and a clip placed twice, turned the same way
    model = (f'<model unit="inch" xmlns="{CORE}"><resources>'
             f'<object id="1" name="Base" type="model">{_cube_mesh(1)}</object>'
             f'<object id="2" name="Lid" type="model">{_cube_mesh(1)}</object>'
             f'<object id="3" name="Clip" type="model">{_cube_mesh(0.5)}</object></resources><build>'
             '<item objectid="1"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 1"/>'
             '<item objectid="3" transform="1 0 0 0 1 0 0 0 1 5 0 0"/><item objectid="3" transform="1 0 0 0 1 0 0 0 1 8 0 0"/></build></model>')
    _three_mf(tmp_path / "planter.3mf", model)
    parts = {p["name"]: p for p in sl.three_mf_parts(str(tmp_path / "planter.3mf"))}
    assert set(parts) == {"Clip", "planter"} and parts["Clip"]["copies"] == 2
    zs = [v[2] for t in parts["planter"]["tris"] for v in t]
    assert max(zs) == pytest.approx(50.8), "inches to mm, and the lid sits on the base"


def test_a_bambu_3mf_follows_components_and_leaves_modifiers_out(tmp_path):
    root = (f'<model unit="millimeter" xmlns="{CORE}" xmlns:p="{PROD}"><resources><object id="10" type="model"><components>'
            '<component p:path="/3D/Objects/arm.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
            '<component p:path="/3D/Objects/arm.model" objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
            '</components></object></resources><build><item objectid="10" transform="0 1 0 -1 0 0 0 0 1 100 100 0"/></build></model>')
    sub = f'<model unit="millimeter" xmlns="{CORE}"><resources><object id="1" type="model">{_cube_mesh(10)}</object><object id="2" type="model">{_cube_mesh(30)}</object></resources></model>'
    settings = ('<config><object id="10"><metadata key="name" value="gbp_arm.stl"/><part id="1" subtype="normal_part"/>'
                '<part id="2" subtype="modifier_part"/></object></config>')
    _three_mf(tmp_path / "arm.3mf", root, {"3D/Objects/arm.model": sub, "Metadata/model_settings.config": settings})
    (part,) = sl.three_mf_parts(str(tmp_path / "arm.3mf"))
    assert part["name"] == "gbp_arm.stl" and len(part["tris"]) == 12, "the 30 mm modifier isn't printed"
    xs = sorted({round(v[0], 3) for t in part["tris"] for v in t})
    assert xs == [90, 100], "turned a quarter as placed: x' = -y + 100"


async def test_a_3mf_uploads_as_its_parts(rig, tmp_path):
    client, _, svc = rig
    model = (f'<model unit="millimeter" xmlns="{CORE}"><resources><object id="1" name="Clip" type="model">{_cube_mesh(10)}</object>'
             f'<object id="2" name="Hook" type="model">{_cube_mesh(20)}</object></resources><build>'
             '<item objectid="1"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 40 0 0"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 80 0 0"/></build></model>')
    _three_mf(tmp_path / "set.3mf", model)
    form = FormData()
    form.add_field("model", (tmp_path / "set.3mf").read_bytes(), filename="set.3mf")
    r = await client.post("/slice/models", data=form)
    assert r.status == 201, await r.text()
    d = await r.json()
    assert d["from"] == "set.3mf" and [(m["name"], m["copies"], m["size"]) for m in d["models"]] == [("Clip.stl", 2, [10, 10, 10]), ("Hook.stl", 1, [20, 20, 20])]
    s = await client.post("/slice", json={"parts": [{"model": m["model"], "copies": m["copies"]} for m in d["models"]], "printer": "workshop", "material": "ASA"})
    assert (await wait_done(client, (await s.json())["id"]))["state"] == "done"
    bad = FormData()
    bad.add_field("model", b"not a zip", filename="broken.3mf")
    r = await client.post("/slice/models", data=bad)
    assert r.status == 400 and "3MF" in (await r.json())["error"]


# ── a brim for each part (design/brim/, A) ───────────────────────────────────

def test_brim_rule_from_how_it_stands():
    """The plate that started it, measured by sides(): the vent sits low and wide, the plug and the CAN mount stand tall."""
    assert sl.brim_rule(4467, [154.8, 153.7, 45.0], "PETG") == ("none", "Low and wide on 45 cm²: it stays down by itself")
    assert sl.brim_rule(1721, [96.1, 25.0, 63.8], "PETG") == ("all", "64 mm tall on a 25 mm base: a rim keeps it standing")
    assert sl.brim_rule(432, [44.4, 18.6, 37.6], "PETG")[0] == "all"
    assert sl.brim_rule(150, [20, 20, 5], "PLA") == ("all", "Touches the plate on only 1.5 cm²: a rim holds it down")
    assert sl.brim_rule(5000, [120, 60, 10], "ASA")[0] == "ears"      # long, in a material that lifts at the corners
    assert sl.brim_rule(5000, [120, 60, 10], "PETG")[0] == "none"
    assert sl.brim_rule(900, [30, 30, 40], "PLA") == ("none", "Sits on 9 cm²: it stays down by itself")


def test_brim_pick_yours_then_kept_then_the_rule(tmp_path):
    lying = {"flat_normal": [0, 0, -1], "down_area": 432.0,
             "sides": [{"normal": [0, 0, -1], "contact": 432.0, "size": [44.4, 18.6, 37.6], "support": 0}]}
    part = sl.Part(model=str(tmp_path / "m.stl"), lying=lying)
    assert sl.brim_pick(part, "PETG") == {"kind": "all", "why": "38 mm tall on a 19 mm base: a rim keeps it standing", "by": "auto", "rule": "all"}
    assert sl.brim_pick(sl.Part(model="x.stl", lying=lying, scale=0.5), "PETG")["why"].startswith("19 mm tall on a 9 mm base")
    req = sl.Request(material="PETG", kept={"brim_type": "no_brim"})
    default = sl.brim_default(req, "Everyday")
    assert default == ("none", "You keep this for every Everyday print", "kept")
    assert sl.brim_pick(part, "PETG", default)["kind"] == "none"
    assert sl.brim_pick(sl.Part(model="x.stl", lying=lying, brim="ears"), "PETG", default) == \
        {"kind": "ears", "why": "You picked this for it", "by": "you", "rule": "all"}
    assert sl.brim_pick(sl.Part(model="x.step"), "PETG")["kind"] == "auto"     # not measurable here: Orca decides
    assert sl.Part(model="x.stl", brim="wide").problems() == ["brim must be auto, none, ears or all"]


def test_a_kept_brim_is_no_longer_plate_wide(profiles, printer):
    req = sl.Request(material="ASA", kept={"brim_type": "no_brim"}, settings={"brim_type": "outer_only"})
    assert req.problems(printer) == []
    p = sl.plan(printer, req, sl.Presets(profiles))
    assert "brim_type" not in p.process and not [c for c in p.changes if c.key == "brim_type"]
    assert sl.brim_default(req, "Everyday") == ("all", "You set this for this print", "you")


def test_every_setting_says_each_parts_brim(tmp_path):
    parts = [sl.Part(model="a/vent.stl"), sl.Part(model="a/vent_plug.stl")]
    picks = [{"kind": "none", "why": "Low and wide", "by": "auto"}, {"kind": "all", "why": "Tall", "by": "auto"}]
    rows = [(c.label, c.value, c.was, c.why) for c in sl.model_changes(parts, picks) if c.key == "brim_type"]
    assert rows == [("Brim · Vent", "None", "Orca's own", "Low and wide"), ("Brim · Vent plug", "All round", "Orca's own", "Tall")]


def test_set_brims_gives_each_object_its_parts_brim(tmp_path):
    import zipfile
    src, dst = tmp_path / "plates.3mf", tmp_path / "brims.3mf"
    config = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2"><metadata key="name" value="p0c0__vent.stl"/><metadata key="brim_type" value="auto_brim"/></object>
  <object id="4"><metadata key="name" value="p1c0__plug.stl"/></object>
  <object id="6"><metadata key="name" value="p1c1__plug.stl"/></object>
  <plate><metadata key="plater_id" value="1"/></plate>
</config>"""
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("Metadata/model_settings.config", config)
        z.writestr("Metadata/plate_1.gcode", "G1")
        z.writestr("3D/3dmodel.model", "<model/>")
    sl.set_brims(str(src), str(dst), ["no_brim", "outer_only"])
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(dst) as z:
        assert "Metadata/plate_1.gcode" not in z.namelist() and "3D/3dmodel.model" in z.namelist()
        root = ET.fromstring(z.read("Metadata/model_settings.config"))
    got = {next(m.get("value") for m in o.findall("metadata") if m.get("key") == "name"):
           [m.get("value") for m in o.findall("metadata") if m.get("key") == "brim_type"] for o in root.iter("object")}
    assert got == {"p0c0__vent.stl": ["no_brim"], "p1c0__plug.stl": ["outer_only"], "p1c1__plug.stl": ["outer_only"]}


async def test_parts_that_want_different_brims_each_get_their_own(rig, tmp_path):
    """Arranged first with room for a brim all round, then the 3MF sliced with each object's own (design/brim/, A)."""
    client, _, _ = rig
    _boxes_stl(tmp_path / "slab.stl", [((0, 0, 0), (60, 40, 4))])
    big, small = await _upload(client, "slab.stl", (tmp_path / "slab.stl").read_bytes()), await _upload(client, "pin.stl", _cube_stl(8))
    r = await client.post("/slice", json={"parts": [{"model": big}, {"model": small, "copies": 2}], "printer": "workshop", "material": "ASA"})
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done", d
    assert [p["brim_pick"]["kind"] for p in d["parts"]] == ["none", "all"]
    body = await (await client.get(f"/slice/{d['id']}/gcode")).text()
    assert "; brim p0c0__slab.stl = no_brim" in body and "; brim p1c1__pin.stl = outer_only" in body
    assert d["plates"][0]["counts"] == [1, 2]
    assert [(c["label"], c["value"]) for c in d["changes"] if c["key"] == "brim_type"] == [("Brim · Slab", "None"), ("Brim · Pin", "All round")]
    # one brim for all of them: one run, in the preset; a part's own pick wins over the rule
    r = await client.post("/slice", json={"parts": [{"model": big, "brim": "all"}, {"model": small}], "printer": "workshop", "material": "ASA"})
    d = await wait_done(client, (await r.json())["id"])
    assert d["parts"][0]["brim_pick"] == {"kind": "all", "why": "You picked this for it", "by": "you", "rule": "none"}
    body = await (await client.get(f"/slice/{d['id']}/gcode")).text()
    assert "; brim p0c0__slab.stl = outer_only" in body and "; brim p1c0__pin.stl = outer_only" in body
    assert (await client.post("/slice", json={"parts": [{"model": big, "brim": "huge"}], "printer": "workshop", "material": "ASA"})).status == 400


# ── slicing for other printers (docs/slicer.md, "Slicing for other printers") ─

class PrinterMoonraker(FakeMoonraker):
    """A printer that joins a slicer elsewhere: its slicing profile in its config folder, like Desk's."""
    def __init__(self, files):
        super().__init__()
        self.files = {path: [json.dumps(d).encode(), 1000.0] for path, d in files.items()}

    def app(self):
        app = super().app()

        async def listing(r):
            assert r.query["root"] == "config"
            return web.json_response({"result": [{"path": p, "modified": m, "size": len(b)} for p, (b, m) in self.files.items()]})
        async def file(r):
            got = self.files.get(r.match_info["path"])
            return web.Response(body=got[0]) if got else web.Response(status=404)
        app.router.add_get("/server/files/list", listing)
        app.router.add_get("/server/files/config/{path:.*}", file)
        return app


DESK_PROFILE = {
    "elyir-bench-slicer/printer.json": {"machine": "Desk", "process": "0.20mm Standard @Voron", "tools": 1,
                                      "materials": {"ASA": "My ASA", "PETG": "Desk PETG"}},
    "elyir-bench-slicer/presets/0-resolved/Desk.json": {"name": "Desk", "inherits": "Voron 2.4 350",
                                                      "printable_area": ["0x0", "300x0", "300x300", "0x300"]},
    # the same name as Workshop's own ASA, set up differently: each printer must slice with its own
    "elyir-bench-slicer/presets/0-resolved/My ASA.json": {"name": "My ASA", "inherits": "Generic ASA", "nozzle_temperature": ["245"]},
    "elyir-bench-slicer/presets/0-resolved/Desk PETG.json": {"name": "Desk PETG", "filament_type": ["PETG"]},
}


@pytest.fixture
async def host(tmp_path, profiles, aiohttp_server, aiohttp_client):
    """Workshop's slicer, lending: Workshop is its own printer, Desk joins through its own Moonraker."""
    orca = tmp_path / "orca"
    orca.write_text(FAKE_ORCA)
    orca.chmod(orca.stat().st_mode | stat.S_IEXEC)
    workshop, desk = FakeMoonraker(), PrinterMoonraker(DESK_PROFILE)
    m1, m3 = await aiohttp_server(workshop.app()), await aiohttp_server(desk.app())
    config = {
        "orca": [sys.executable, str(orca)], "nice": 0, "profiles": profiles, "lend": True, "allow": "anyone",
        "printers": {"workshop": {"name": "Workshop", "machine": "Workshop", "process": "0.20mm Standard @Voron", "tools": 8,
                              "materials": {"ASA": "My ASA"}, "moonraker": f"http://127.0.0.1:{m1.port}"}},
    }
    svc = S.Service(config, str(tmp_path / "work"))
    client = await aiohttp_client(svc.app())
    return client, svc, workshop, desk, f"http://127.0.0.1:{m3.port}", config


AS_Desk = {"X-Elyir-Bench-Printer": "desk"}
AS_Workshop = {"X-Elyir-Bench-Printer": "workshop"}


async def test_a_printer_joins_with_its_own_profile_and_slices_for_itself(host):
    client, svc, workshop, desk, desk_url, _ = host
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert r.status == 200, await r.text()
    entry = await r.json()
    assert entry["name"] == "Desk" and entry["materials"] == ["ASA", "PETG"] and entry["bed"][:2] == [300, 300]
    assert entry["joined"] is True and entry["slots"] == 1

    # Each printer's "My ASA" is its own.
    assert svc.presets["desk"].resolve("My ASA")["nozzle_temperature"] == ["245"]
    assert svc.presets["workshop"].resolve("My ASA")["nozzle_temperature"] == ["260"]

    # Through Desk's nginx: only Desk is offered, so the app can't pick Workshop's settings for it.
    opts = await (await client.get("/slice/options", headers=AS_Desk)).json()
    assert [p["id"] for p in opts["printers"]] == ["desk"]
    assert [p["id"] for p in (await (await client.get("/slice/options", headers=AS_Workshop)).json())["printers"]] == ["workshop"]

    # A slice that doesn't name the printer is for the one it came through, and goes to its Moonraker.
    r = await client.post("/slice", data=model_form(material="ASA"), headers=AS_Desk)
    assert r.status == 202, await r.text()
    d = await wait_done(client, (await r.json())["id"])
    assert d["state"] == "done" and d["printer"] == "desk"
    sent = await (await client.post(f"/slice/{d['id']}/send", headers=AS_Desk)).json()
    assert sent["sent"] and len(desk.uploads) == 1 and not workshop.uploads


async def test_through_a_printer_nothing_of_another_printer_is_reachable(host):
    client, _, _, _, desk_url, _ = host
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 200
    r = await client.post("/slice", data=model_form(printer="workshop", material="ASA"), headers=AS_Desk)
    assert r.status == 403 and "Desk" in (await r.json())["error"]

    form = FormData()
    form.add_field("model", b"solid x\nendsolid x\n", filename="clip.stl")
    up = await (await client.post("/slice/models", data=form, headers=AS_Desk)).json()
    # Workshop can't slice, or download, the model Desk uploaded
    r = await client.post("/slice", json={"parts": [{"model": up["model"]}], "material": "ASA"}, headers=AS_Workshop)
    assert r.status == 400 and "no such model" in (await r.json())["error"]
    assert (await client.get(f"/slice/models/{up['model']}/file", headers=AS_Workshop)).status == 404
    assert (await client.get(f"/slice/models/{up['model']}/file", headers=AS_Desk)).status == 200

    r = await client.post("/slice", json={"parts": [{"model": up["model"]}], "material": "ASA"}, headers=AS_Desk)
    jid = (await r.json())["id"]
    assert (await client.get(f"/slice/{jid}", headers=AS_Workshop)).status == 404
    assert (await client.get(f"/slice/{jid}", headers=AS_Desk)).status == 200

    # A printer that never joined is told so, in words the app shows.
    r = await client.get("/slice/options", headers={"X-Elyir-Bench-Printer": "studio"})
    assert r.status == 404 and "studio hasn't joined" in (await r.json())["error"]


async def test_joining_says_what_is_missing(host):
    client, _, _, desk, desk_url, _ = host
    del desk.files["elyir-bench-slicer/presets/0-resolved/Desk PETG.json"]
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert r.status == 422 and "Desk PETG" in (await r.json())["error"]
    del desk.files["elyir-bench-slicer/printer.json"]
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert r.status == 422 and "elyir-bench-slicer/printer.json" in (await r.json())["error"]
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": "http://127.0.0.1:9"})
    assert r.status == 422 and "can't be reached" in (await r.json())["error"]
    assert (await client.put("/slice/printers/workshop", json={"name": "Workshop", "moonraker": desk_url})).status == 409
    assert (await client.get("/slice/printers/desk")).status == 404


async def test_a_slicer_that_doesnt_lend_refuses_to_join(tmp_path, profiles, aiohttp_client):
    config = {"orca": [sys.executable, "-c", "pass"], "profiles": profiles,
              "printers": {"workshop": {"name": "Workshop", "machine": "Workshop", "process": "0.20mm Standard @Voron",
                                    "materials": {"ASA": "My ASA"}}}}
    client = await aiohttp_client(S.Service(config, str(tmp_path / "work")).app())
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": "http://desk.local:7125"})
    assert r.status == 403 and "slice_for_others" in (await r.json())["error"]


async def test_a_joined_printer_survives_a_restart_and_its_profile_follows_the_printer(host, tmp_path, aiohttp_client):
    client, _, _, desk, desk_url, config = host
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 200

    again = S.Service(config, str(tmp_path / "work"))
    assert "desk" in again.printers and again.presets["desk"].resolve("My ASA")["nozzle_temperature"] == ["245"]

    # Someone edits Desk's ASA on Desk (Mainsail's editor): the next look copies it again.
    desk.files["elyir-bench-slicer/presets/0-resolved/My ASA.json"] = [
        json.dumps({"name": "My ASA", "inherits": "Generic ASA", "nozzle_temperature": ["250"]}).encode(), 2000.0]
    c2 = await aiohttp_client(again.app())
    await c2.get("/slice/options", headers=AS_Desk)
    assert again.presets["desk"].resolve("My ASA")["nozzle_temperature"] == ["250"]

    assert (await c2.delete("/slice/printers/desk")).status == 200
    r = await c2.get("/slice/options", headers=AS_Desk)
    assert r.status == 403 and (await r.json())["refused"] is True     # stopped from the slicer: said no, for a day
    assert "desk" not in S.Service(config, str(tmp_path / "work")).printers


# ── asking first (design/slicing-elsewhere/, A): a yes on the slicer's own screen ──

@pytest.fixture
async def asking(host, tmp_path, aiohttp_client):
    """Workshop's slicer as a printer lends it: a printer that wants to join waits for a yes."""
    _, _, workshop, desk, desk_url, config = host
    svc = S.Service({**config, "allow": "ask"}, str(tmp_path / "work-ask"))
    return await aiohttp_client(svc.app()), svc, desk, desk_url


async def test_a_printer_asks_and_slices_once_the_slicer_says_yes(asking):
    client, svc, desk, desk_url = asking
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert r.status == 202 and (await r.json()) == {"id": "desk", "name": "Desk", "waiting": True, "slicer": "Workshop"}
    # Desk's phone is told what it waits for, in words, with who to ask
    r = await client.get("/slice/options", headers=AS_Desk)
    d = await r.json()
    assert r.status == 403 and d["waiting"] is True and d["slicer"] == "Workshop" and "say yes" in d["error"]
    # asking again on the next apply doesn't make a second ask
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 202
    asks = await (await client.get("/slice/asks", headers=AS_Workshop)).json()
    assert [(a["id"], a["name"], a["kind"]) for a in asks["asks"]] == [("desk", "Desk", "printer")] and asks["slicer"] == "Workshop"
    # only Workshop itself answers: not the printer that asks
    assert (await client.get("/slice/asks", headers=AS_Desk)).status == 403
    assert (await client.post("/slice/asks/desk/allow", headers=AS_Desk)).status == 403
    r = await client.post("/slice/asks/desk/allow", headers=AS_Workshop)
    assert r.status == 200 and (await r.json())["joined"] is True
    opts = await (await client.get("/slice/options", headers=AS_Desk)).json()
    assert [p["id"] for p in opts["printers"]] == ["desk"] and opts["slicer"] == {"name": "Workshop", "here": False}
    own = await (await client.get("/slice/options", headers=AS_Workshop)).json()
    assert own["slicer"] == {"name": "Workshop", "here": True}
    listed = await (await client.get("/slice/printers", headers=AS_Workshop)).json()
    assert [(p["id"], p["joined"]) for p in listed["printers"]] == [("workshop", False), ("desk", True)]
    assert not (await (await client.get("/slice/asks", headers=AS_Workshop)).json())["asks"]


async def test_no_is_kept_for_a_day_and_stop_counts_as_no(asking, tmp_path):
    client, svc, desk, desk_url = asking
    await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert (await client.post("/slice/asks/desk/refuse", headers=AS_Workshop)).status == 200
    r = await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    assert r.status == 403 and (await r.json())["refused"] is True       # every apply doesn't ask again
    r = await client.get("/slice/options", headers=AS_Desk)
    assert r.status == 403 and "said no" in (await r.json())["error"]
    svc.refused["desk"] -= S.REFUSED_FOR                                  # a day later it may ask again
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 202
    assert (await client.post("/slice/asks/desk/allow", headers=AS_Workshop)).status == 200
    # Stop for Desk, on Workshop's Care: gone, and not asked again today
    assert (await client.delete("/slice/printers/desk", headers=AS_Workshop)).status == 200
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 403
    # the ask, the yes and the no survive a restart
    again = S.Service({"orca": svc.orca, "profiles": svc.profiles, "lend": True, "allow": "ask", "printers": {}}, str(tmp_path / "work-ask"))
    assert "desk" in again.refused and "desk" not in again.printers


async def test_a_queued_slice_says_what_it_waits_behind(host):
    client, svc, _, _, desk_url, _ = host
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 200
    orca = Path(svc.orca[1])
    orca.write_text(orca.read_text().replace("a = sys.argv", "import time; time.sleep(0.6)\na = sys.argv"))
    mine = await (await client.post("/slice", data=model_form(material="ASA"), headers=AS_Workshop)).json()
    await asyncio.sleep(0.15)
    theirs = await (await client.post("/slice", data=model_form(material="ASA"), headers=AS_Desk)).json()
    d = await (await client.get(f"/slice/{theirs['id']}", headers=AS_Desk)).json()
    assert d["state"] == "queued" and d["ahead"] == 1 and d["behind"] == "Workshop"
    assert (await wait_done(client, mine["id"]))["state"] == "done"


def test_the_old_joined_file_is_still_read(tmp_path, profiles):
    work = tmp_path / "work"
    (work / "printers" / "desk" / "presets").mkdir(parents=True)
    (work / "printers" / "desk" / "printer.json").write_text(json.dumps(DESK_PROFILE["elyir-bench-slicer/printer.json"]))
    for path, d in DESK_PROFILE.items():
        if "/presets/" in path:
            f = work / "printers" / "desk" / path[len("elyir-bench-slicer/"):]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d))
    (work / "printers.json").write_text(json.dumps({"desk": {"name": "Desk", "moonraker": "http://desk.local:7125", "files": {}, "joined": 1}}))
    svc = S.Service({"orca": ["x"], "profiles": profiles, "lend": True, "printers": {}}, str(work))
    assert "desk" in svc.printers                                         # Desk, joined on 4 October before asking existed


async def test_the_installer_can_see_a_printer_is_waiting_or_was_told_no(asking):
    client, _, _, desk_url = asking
    await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})
    d = await (await client.get("/slice/printers/desk")).json()
    assert d["waiting"] is True and d["slicer"] == "Workshop"
    await client.post("/slice/asks/desk/refuse", headers=AS_Workshop)
    r = await client.get("/slice/printers/desk")
    assert r.status == 403 and (await r.json())["refused"] is True


# ── Elyir Bench's start macro (docs/start-macro.md, docs/setup-card.md) ─────────

def test_with_the_start_macro_its_two_lines_go_around_the_start_gcode(profiles, printer):
    plain = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    assert plain.machine["machine_start_gcode"] == "PRINT_START TOOL=[initial_tool]", "without it: as it is"
    printer.start_macro = True
    plan = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    assert plan.machine["machine_start_gcode"] == (
        "ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]\n"
        "PRINT_START TOOL=[initial_tool]\n"
        "ELYIR_BENCH_PRINT_START_DONE")
    again = sl.plan(printer, sl.Request(material="ASA"), sl.Presets(profiles))
    assert again.machine["machine_start_gcode"] == plan.machine["machine_start_gcode"], "the preset itself isn't changed"


def test_the_start_macro_wrap_keeps_their_lines_and_never_doubles():
    theirs = "G28\nPRINT_START BED=[bed_temperature_initial_layer_single]\n"
    wrapped = sl.wrap_start_gcode(theirs)
    assert wrapped.splitlines()[1:3] == ["G28", "PRINT_START BED=[bed_temperature_initial_layer_single]"]
    assert wrapped.startswith(sl.START_MACRO_BEFORE + "\n") and wrapped.endswith("\n" + sl.START_MACRO_AFTER)
    assert sl.wrap_start_gcode(wrapped) == wrapped
    assert sl.wrap_start_gcode("") == sl.START_MACRO_BEFORE + "\n" + sl.START_MACRO_AFTER


def test_printer_json_turns_it_on_only_when_it_says_true():
    base = {"machine": "m", "process": "p", "materials": {}}
    assert sl.Printer.from_config("x", {**base, "start_macro": True}).start_macro is True
    assert sl.Printer.from_config("x", base).start_macro is False
    assert sl.Printer.from_config("x", {**base, "start_macro": "yes"}).start_macro is False


# ── this machine's own printer: printer.json read from its folder, again when it changes (docs/slicer-profile.md) ──

async def test_the_printers_own_printer_json_is_read_when_it_appears_and_when_it_changes(tmp_path, profiles, aiohttp_client,
                                                                                         monkeypatch):
    """A stranger's printer starts with no printer.json; the component writes one learned from their files, and the
    slicer uses it from the next request, with no apply in between."""
    orca = tmp_path / "orca"
    orca.write_text(FAKE_ORCA)
    orca.chmod(orca.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "config" / "elyir-bench-slicer"
    (home / "presets").mkdir(parents=True)
    config = {"orca": [sys.executable, str(orca)], "nice": 0, "profiles": profiles, "name": "Their Voron",
              "printers": {"voron": {"name": "Their Voron", "moonraker": "http://127.0.0.1:1", "home": str(home),
                                     "presets": [str(home / "presets")]}}}
    svc = S.Service(config, str(tmp_path / "work"))
    client = await aiohttp_client(svc.app())
    head = {S.PRINTER_HEADER: "voron"}
    r = await client.get("/slice/options", headers=head)
    assert r.status == 404 and (await r.json())["settings"] is False
    assert "Slice one file in OrcaSlicer" in (await r.json())["error"]

    (home / "printer.json").write_text(json.dumps({"machine": "Workshop", "process": "0.20mm Standard @Voron",
                                                   "materials": {"ASA": "My ASA"}, "learned": {"id": "a1"}}))
    monkeypatch.setattr(S, "HOME_CHECK", 0)
    opts = await (await client.get("/slice/options", headers=head)).json()
    assert [p["id"] for p in opts["printers"]] == ["voron"] and opts["printers"][0]["materials"] == ["ASA"]
    write(home / "presets" / "0-learned", "fine.json", {"name": "0.16mm Fine", "layer_height": "0.16", "wall_loops": "3"})
    (home / "printer.json").write_text(json.dumps({"machine": "Workshop", "process": "0.16mm Fine",
                                                   "materials": {"ASA": "My ASA", "PLA": "My ASA"}, "learned": {"id": "b2"}}))
    opts = await (await client.get("/slice/options", headers=head)).json()
    assert opts["printers"][0]["materials"] == ["ASA", "PLA"] and opts["printers"][0]["base"] == "0.16mm Fine"
    (home / "printer.json").write_text("{ half written")
    opts = await (await client.get("/slice/options", headers=head)).json()
    assert opts["printers"][0]["base"] == "0.16mm Fine"           # the one before still slices


# ── slicing like their prints: a learned profile's Everyday is theirs (5 October 2026) ─────────

def test_on_a_learned_profile_everyday_is_exactly_their_settings_and_the_others_adjust(profiles, tmp_path):
    theirs = tmp_path / "learned"
    write(theirs, "process.json", {"name": "Their 0.16 fine", "inherits": "0.20mm Standard @Voron", "layer_height": "0.16",
                                   "wall_loops": "4", "sparse_infill_density": "25%"})
    write(theirs, "petg.json", {"name": "Their PETG", "inherits": "Generic ASA", "nozzle_temperature": ["245"],
                                "filament_type": ["PETG"]})
    presets = sl.Presets([str(theirs), *profiles])
    learned = sl.Printer.from_config("voron", {"machine": "Workshop", "process": "Their 0.16 fine",
                                               "materials": {"PETG": "Their PETG"}, "learned": {"id": "a1b2"}})
    assert learned.learned
    everyday = sl.plan(learned, sl.Request(purpose="everyday", material="PETG"), presets)
    assert everyday.process["layer_height"] == "0.16" and everyday.process["wall_loops"] == "4"
    assert everyday.process["sparse_infill_density"] == "25%"
    assert everyday.filament["nozzle_temperature"] == ["245"]          # their PETG, not the spool's 235
    assert not [c for c in everyday.changes if c.source in ("purpose", "spool")]
    strong = sl.plan(learned, sl.Request(purpose="strong", material="PETG"), presets)
    assert strong.process["wall_loops"] == "5"                          # other purposes still adjust from theirs
    handmade = sl.Printer.from_config("voron", {"machine": "Workshop", "process": "Their 0.16 fine",
                                                "materials": {"PETG": "Their PETG"}})
    assert not handmade.learned
    assert sl.plan(handmade, sl.Request(purpose="everyday", material="PETG"), presets).process["layer_height"] == "0.2"


async def test_stopping_a_printer_fails_its_waiting_slices_in_words_and_the_queue_goes_on(host):
    # Workshop, 5 October 2026: a slice for Desk waiting in line when Workshop stopped slicing for it crashed (KeyError)
    client, svc, _, _, desk_url, _ = host
    assert (await client.put("/slice/printers/desk", json={"name": "Desk", "moonraker": desk_url})).status == 200
    orca = Path(svc.orca[1])
    orca.write_text(orca.read_text().replace("a = sys.argv", "import time; time.sleep(0.6)\na = sys.argv"))
    mine = await (await client.post("/slice", data=model_form(material="ASA"), headers=AS_Workshop)).json()
    await asyncio.sleep(0.15)
    theirs = await (await client.post("/slice", data=model_form(material="ASA"), headers=AS_Desk)).json()
    assert (await client.delete("/slice/printers/desk", headers=AS_Workshop)).status == 200
    assert (await wait_done(client, mine["id"]))["state"] == "done"            # the queue carries on
    job = svc.jobs[theirs["id"]]                     # Desk itself is told "said no" from now on (403)
    assert job.state == "failed" and "stopped slicing for Desk" in job.error


# ── a named filament (design/bench-material/, B) ─────────────────────────────

def library(tmp_path):
    lib = tmp_path / "lib"
    write(lib, "OrcaFilamentLibrary/filament/base/fdm_filament_pla.json",
          {"type": "filament", "name": "fdm_filament_pla", "filament_type": ["PLA"], "instantiation": "false"})
    write(lib, "OrcaFilamentLibrary/filament/Polymaker/PolyTerra PLA @base.json",
          {"type": "filament", "name": "PolyTerra PLA @base", "inherits": "fdm_filament_pla", "instantiation": "false",
           "filament_vendor": ["Polymaker"], "nozzle_temperature": ["215"]})
    write(lib, "OrcaFilamentLibrary/filament/Polymaker/PolyTerra PLA @System.json",
          {"type": "filament", "name": "PolyTerra PLA @System", "inherits": "PolyTerra PLA @base", "instantiation": "true",
           "compatible_printers": []})
    write(lib, "OrcaFilamentLibrary/filament/Generic PLA @System.json",
          {"type": "filament", "name": "Generic PLA @System", "inherits": "fdm_filament_pla", "instantiation": "true",
           "filament_vendor": ["Generic"]})
    write(lib, "Anycubic/filament/kobra.json", {"type": "filament", "name": "Anycubic PLA @Kobra", "instantiation": "true",
                                                 "filament_type": ["PLA"]})
    return str(lib)


def test_the_library_is_orcas_own_pickable_filaments(tmp_path):
    lib = sl.library_filaments(sl.Presets([library(tmp_path)]))
    assert lib == [{"preset": "Generic PLA @System", "name": "Generic PLA", "brand": "Generic", "material": "PLA"},
                   {"preset": "PolyTerra PLA @System", "name": "PolyTerra PLA", "brand": "Polymaker", "material": "PLA"}]
    assert [f["name"] for f in sl.search_filaments(lib, "polymaker")] == ["PolyTerra PLA"]
    assert [f["name"] for f in sl.search_filaments(lib, "terra pla")] == ["PolyTerra PLA"]
    assert sl.search_filaments(lib, "", "PETG") == []


def test_a_named_filament_is_sliced_with_its_own_settings(tmp_path, profiles, printer):
    presets = sl.Presets([*profiles, library(tmp_path)])
    plan = sl.plan(printer, sl.Request(material="PLA", filament="PolyTerra PLA @System"), presets)
    assert plan.filament["nozzle_temperature"] == ["215"] and plan.filament["filament_vendor"] == ["Polymaker"]
    assert sl.Request(material="PLA", filament="PolyTerra PLA @System").problems(printer) == []
    assert sl.Request(material="PLA").problems(printer)   # without one, the printer still needs its own PLA


def test_search_puts_a_name_that_starts_so_and_everyday_materials_first():
    lib = [{"preset": f"{n} @System", "name": n, "brand": "Polymaker", "material": m}
           for n, m in (("Fiberon PA6-CF", "PA6-CF"), ("Panchroma PLA", "PLA"), ("PolyLite ABS", "ABS"), ("PolyTerra PLA", "PLA"))]
    assert [f["name"] for f in sl.search_filaments(lib, "poly")] == ["PolyLite ABS", "PolyTerra PLA", "Panchroma PLA", "Fiberon PA6-CF"]


def test_a_kobra_3_slices_with_anycubics_own_bed_temperatures(tmp_path):
    """Anycubic's Kobra 3 presets fill in only the High Temp Plate's bed temperatures (textured is 45 for every
    material, ABS too); a PETG print sliced at 45 came off the bed (7 October 2026). The Max's textured ones are real."""
    pj = json.loads((HERE.parent.parent / "bench" / "profiles" / "kobra-3" / "printer.json").read_text())
    assert pj["plate"] == "High Temp Plate"
    home = tmp_path / "presets"
    write(home / "machine", "m.json", {"name": pj["machine"], "nozzle_diameter": ["0.4"], "printable_area": ["0x0", "250x0", "250x250", "0x250"]})
    write(home / "process", "p.json", {"name": pj["process"], "layer_height": "0.2"})
    write(home / "filament", "f.json", {"name": pj["materials"]["PETG"], "filament_type": ["PETG"], "hot_plate_temp": ["70"],
                                        "hot_plate_temp_initial_layer": ["70"], "textured_plate_temp": ["45"]})
    printer = sl.Printer.from_config("kobra-3", {**pj, "presets": [str(home)]})
    p = sl.plan(printer, sl.Request(purpose="everyday", material="PETG"), sl.Presets([*printer.presets]))
    assert p.process["curr_bed_type"] == "High Temp Plate"
    assert next(c.why for c in p.changes if c.key == "curr_bed_type") == pj["plate_why"]
    assert json.loads((HERE.parent.parent / "bench" / "profiles" / "kobra-3-max" / "printer.json").read_text())["plate"] == "Textured PEI Plate"


def test_the_kobra_3_max_lays_its_top_down_as_the_kobra_3_does(tmp_path):
    """Anycubic's Max process puts 1.00 into top surfaces, the Kobra 3's 0.97; a Max print's top came out rough (8 October
    2026). The box's own process for the Max inherits Anycubic's with the Kobra 3's top flow."""
    root = HERE.parent.parent / "bench" / "profiles" / "kobra-3-max"
    pj = json.loads((root / "printer.json").read_text())
    own = json.loads(next((root / "presets").glob("*.json")).read_text())
    assert pj["process"] == own["name"] and own["type"] == "process"
    assert own["inherits"] == "0.20mm Standard @Anycubic Kobra 3 Max 0.4 nozzle" and own["top_solid_infill_flow_ratio"] == "0.97"
    home = tmp_path / "presets"
    write(home / "machine", "m.json", {"name": pj["machine"], "nozzle_diameter": ["0.4"], "printable_area": ["0x0", "420x0", "420x420", "0x420"]})
    write(home / "process", "anycubic.json", {"name": own["inherits"], "layer_height": "0.2", "top_solid_infill_flow_ratio": "1"})
    write(home / "process", "bench.json", own)
    write(home / "filament", "f.json", {"name": pj["materials"]["PETG"], "filament_type": ["PETG"]})
    printer = sl.Printer.from_config("kobra-3-max", {**pj, "presets": [str(home)]})
    p = sl.plan(printer, sl.Request(purpose="draft", material="PETG"), sl.Presets([*printer.presets]))
    assert p.process["top_solid_infill_flow_ratio"] == "0.97" and p.process["top_shell_layers"] == "5"


# ── Print the rest (design/power-loss/): the part of a model above where a print stopped ──

def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [[v[i] for i in t] for t in f]


def test_cut_above_keeps_the_top_set_on_the_plate_and_closed(tmp_path):
    # an L (a slab and a back wall) and a ring around a hole, standing 10 mm up as a model might
    tris = _box(0, 0, 10, 40, 30, 15) + _box(0, 22, 15, 40, 30, 40)
    tris += _box(60, 0, 10, 80, 5, 30) + _box(60, 15, 10, 80, 20, 30) + _box(60, 5, 10, 65, 15, 30) + _box(75, 5, 10, 80, 15, 30)
    src, dst = tmp_path / "stand.stl", tmp_path / "rest.stl"
    sl.write_stl(str(src), tris)
    assert sl.cut_above(str(src), str(dst), 12.2)
    assert sl.model_size(str(dst)) == pytest.approx([80.0, 30.0, 17.8], abs=0.01)
    rest = sl._triangles(str(dst))
    assert min(v[2] for t in rest for v in t) == pytest.approx(0, abs=1e-3)
    # the cut faces the plate
    cap = [t for t in rest if all(abs(v[2]) < 1e-3 for v in t)]
    assert cap and all((sl._normal_area(t)[0] or [0, 0, 0])[2] < 0 for t in cap if sl._normal_area(t)[1] > 1e-6)


def test_a_closed_model_stays_closed_when_cut(tmp_path):
    src, dst = tmp_path / "box.stl", tmp_path / "rest.stl"
    sl.write_stl(str(src), _box(0, 0, 0, 20, 10, 30))
    assert sl.cut_above(str(src), str(dst), 12.2)
    edges = {}
    for t in sl._triangles(str(dst)):
        for i in range(3):
            k = tuple(sorted((tuple(round(c, 3) for c in t[i]), tuple(round(c, 3) for c in t[(i + 1) % 3]))))
            edges[k] = edges.get(k, 0) + 1
    assert all(n == 2 for n in edges.values())


def test_cut_above_the_top_is_nothing(tmp_path):
    src = tmp_path / "box.stl"
    sl.write_stl(str(src), _box(0, 0, 0, 10, 10, 10))
    assert not sl.cut_above(str(src), str(tmp_path / "rest.stl"), 10)


async def test_the_rest_of_a_model_laid_on_its_side_is_cut_as_it_was_printed(rig, tmp_path):
    """design/power-loss/: Print the rest cuts the model the way the plate had it (laid on its side here: 10 mm tall)."""
    client, moon, svc = rig
    _boxes_stl(tmp_path / "block.stl", [((0, 0, 0), (30, 20, 10))])
    m = await _upload(client, "block.stl", (tmp_path / "block.stl").read_bytes())
    r = await client.post(f"/slice/models/{m}/cut", json={"z": 4, "lay": "side", "down": [1.0, 0.0, 0.0], "scale": 1})
    assert r.status == 201, await r.text()
    cut = await r.json()
    assert cut["name"] == "block_rest.stl" and cut["size"][2] == pytest.approx(26, abs=0.01)
    f = await client.get(f"/slice/models/{cut['model']}/file")
    assert f.status == 200
    assert (await client.post(f"/slice/models/{m}/cut", json={"z": 40, "lay": "side", "down": [1.0, 0.0, 0.0]})).status == 422
    assert (await client.post("/slice/models/000000000000/cut", json={"z": 4})).status == 404
    assert (await client.post(f"/slice/models/{m}/cut", json={})).status == 400
