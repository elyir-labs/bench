"""Slicing like their own prints (design/getting-started/), the printer's side of docs/slicer-profile.md: the component
reads the profile at the end of the printer's own Orca files, says what it found (GET /printer/intent/profile), and
writes elyir-bench-slicer/printer.json and presets/0-learned/ for the slicer. Against the stand-in Moonraker of
test_component.py and made-up files from test_orca_profile.py."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_component import FakeConfig, FakeWebRequest, KlippyState, load, run  # noqa: E402
from test_orca_profile import gcode  # noqa: E402

KEYS = str(Path(__file__).resolve().parent.parent.parent / "slicer" / "orca_keys.json")
OBJECTS = ["webhooks", "print_stats", "toolhead", "extruder", "heater_bed", "gcode_macro PRINT_START",
           "gcode_macro PRINT_END"]


class Loop:
    def __init__(self):
        self.later = []

    def delay_callback(self, delay, fn, *args):
        self.later.append(fn)

    def create_task(self, coro):
        coro.close()


class Folders:
    def __init__(self, tmp):
        self.dirs = {"gcodes": tmp / "gcodes", "config": tmp / "config"}
        for d in self.dirs.values():
            d.mkdir()

    def get_directory(self, root="gcodes"):
        return str(self.dirs[root])

    def get_file_metadata(self, filename):
        return {}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A stranger's Voron 2.4 300 with their own PRINT_START, no unit, nothing of Elyir Bench's slicing set up yet."""
    server, comp = load(tmp_path, monkeypatch)
    comp.eventloop = Loop()
    folders = Folders(tmp_path)
    server.components["file_manager"] = folders
    comp.orca_keys = KEYS
    comp.klippy_apis.objects = list(OBJECTS)
    axis = {"max": [300, 300, 280, 0]}

    async def query(objs):
        return {"toolhead": {"axis_maximum": axis["max"]}} if "toolhead" in objs else {}
    monkeypatch.setattr(comp.klippy_apis, "query_objects", query)
    return server, comp, folders, axis


def gcodes(folders):
    return Path(folders.dirs["gcodes"])


def home(folders):
    return Path(folders.dirs["config"]) / "elyir-bench-slicer"


def start(server, comp):
    run(comp.component_init())
    server.kc.state = KlippyState.READY
    run(server.handlers["server:klippy_ready"]())
    run(comp._scan_profiles())


def act(comp, action, **args):
    return run(comp._handle_action(FakeWebRequest(action=action, args=args)))


def profile(comp):
    return run(comp._handle_profile(FakeWebRequest()))


def test_a_strangers_files_agree_so_they_are_used_by_themselves(rig):
    server, comp, folders, _ = rig
    g = gcodes(folders)
    gcode(g / "bracket_PLA_1h.gcode", mtime=1_000_000, used="10, 0, 0")
    (g / "old").mkdir()
    gcode(g / "old" / "lid_PETG_2h.gcode", mtime=900_000, used="0, 10, 0")
    gcode(g / "ours_PLA_3m.gcode", {"layer_height": "0.28"}, mtime=1_100_000, marker=True)   # never learned from
    start(server, comp)
    got = profile(comp)
    assert got["state"] == "using" and got["told"] is False and got["newer"] is None
    assert got["bed_klipper"] == [300.0, 300.0]
    [found] = got["found"]
    assert got["using"] == found["id"] and found["files"] == 2 and found["slicer"] == "OrcaSlicer 2.3"
    assert found["printer"] == "Voron 2.4 300" and found["process"] == "0.20mm Standard @Voron" and found["nozzle"] == 0.4
    assert found["materials"] == {"PLA": {"preset": "Generic PLA @Voron", "files": 1},
                                  "PETG": {"preset": "Fancy PETG @Voron", "files": 1}}
    assert found["checks"] == {"bed_ok": True, "bed_klipper": [300.0, 300.0], "start_ok": True} and found["start"] == "PRINT_START"
    assert "source" not in found and "auto" not in got

    pj = json.loads((home(folders) / "printer.json").read_text())
    assert pj["machine"] == "My Voron" and pj["process"] == "0.20mm Standard @Voron" and pj["plate"] == "Textured PEI Plate"
    assert pj["tools"] == 1 and "start_macro" not in pj
    assert pj["materials"] == {"PLA": "Generic PLA @Voron", "PETG": "Fancy PETG @Voron"}
    assert pj["learned"]["id"] == found["id"] and pj["learned"]["from_files"] == ["bracket_PLA_1h.gcode", "old/lid_PETG_2h.gcode"]
    learned = home(folders) / "presets" / "0-learned"
    names = {json.loads(p.read_text())["name"]: json.loads(p.read_text()) for p in learned.glob("*.json")}
    assert set(names) == {"My Voron", "0.20mm Standard @Voron", "Generic PLA @Voron", "Fancy PETG @Voron"}
    assert names["My Voron"]["type"] == "machine" and names["Fancy PETG @Voron"]["nozzle_temperature"] == ["240"]
    assert names["0.20mm Standard @Voron"]["layer_height"] == "0.2"      # not our own file's 0.28


def test_told_is_kept_in_moonrakers_database(rig):
    server, comp, folders, _ = rig
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    start(server, comp)
    got = act(comp, "profile_told")
    assert got["profile"]["told"] is True
    assert server.components["database"].data["elyir-bench"]["profile"] == {"told": True, "keep": []}
    again = type(comp)(FakeConfig(server))
    run(again.component_init())
    assert again._profile_saved["told"] is True


def test_a_hand_made_printer_json_is_never_touched(rig):
    server, comp, folders, _ = rig
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    home(folders).mkdir()
    mine = '{"machine": "Workshop", "process": "0.20mm Standard @Voron", "materials": {"PLA": "PLA @Voron"}}'
    (home(folders) / "printer.json").write_text(mine)
    start(server, comp)
    got = profile(comp)
    assert got["state"] == "yours" and got["using"] is None and len(got["found"]) == 1
    with pytest.raises(Exception, match="set by hand"):
        act(comp, "profile_use", id=got["found"][0]["id"])
    assert (home(folders) / "printer.json").read_text() == mine
    assert not (home(folders) / "presets" / "0-learned").exists()


def test_files_that_disagree_are_asked_about_and_the_pick_replaces_what_was_learned(rig):
    server, comp, folders, _ = rig
    g = gcodes(folders)
    gcode(g / "a.gcode", mtime=1_000_000)
    gcode(g / "b.gcode", {"nozzle_diameter": "0.6", "print_settings_id": "0.30mm Draft @Voron",
                          "filament_settings_id": '"Other PLA";"x";"y"'}, mtime=1_000_100)
    start(server, comp)
    got = profile(comp)
    assert got["state"] == "ask" and got["using"] is None
    assert [f["nozzle"] for f in got["found"]] == [0.6, 0.4] and [f["files"] for f in got["found"]] == [1, 1]
    assert not (home(folders) / "printer.json").exists()
    act(comp, "profile_use", id=got["found"][0]["id"])
    learned = home(folders) / "presets" / "0-learned"
    assert (learned / "Other PLA.json").exists()
    act(comp, "profile_use", id=got["found"][1]["id"])
    got = profile(comp)
    assert got["state"] == "using" and got["using"] == got["found"][1]["id"]
    assert not (learned / "Other PLA.json").exists() and (learned / "Generic PLA @Voron.json").exists()
    with pytest.raises(Exception, match="any more"):
        act(comp, "profile_use", id="nothere")


def test_newer_files_with_other_settings_are_offered_once(rig):
    server, comp, folders, _ = rig
    g = gcodes(folders)
    gcode(g / "a.gcode", mtime=1_000_000)
    start(server, comp)
    using = profile(comp)["using"]
    gcode(g / "b.gcode", {"print_settings_id": "0.16mm Fine @Voron"}, mtime=time.time() + 60)
    run(server.handlers["file_manager:filelist_changed"]({"action": "create_file", "item": {"root": "gcodes", "path": "b.gcode"}}))
    assert comp.eventloop.later[-1] == comp._scan_profiles                  # looked at again a few seconds later
    run(comp._scan_profiles())
    got = profile(comp)
    assert got["state"] == "newer" and got["using"] == using and got["newer"] != using   # offered, never switched
    act(comp, "profile_keep")
    got = profile(comp)
    assert got["state"] == "using" and server.components["database"].data["elyir-bench"]["profile"]["keep"] == [got["found"][0]["id"]]
    run(server.handlers["file_manager:filelist_changed"]({"action": "create_file", "item": {"root": "config", "path": "x"}}))
    assert not comp._profile_scan_due                                       # only the gcodes folder counts


def test_no_file_with_settings_says_none(rig):
    server, comp, folders, _ = rig
    (gcodes(folders) / "cura.gcode").write_text(";Generated with Cura_SteamEngine 5.7\nG28\n")
    start(server, comp)
    got = profile(comp)
    assert (got["state"], got["found"], got["using"]) == ("none", [], None)


def test_a_profile_that_doesnt_fit_klipper_is_never_used_by_itself(rig):
    server, comp, folders, axis = rig
    axis["max"] = [350, 350, 330, 0]
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    start(server, comp)
    got = profile(comp)
    assert got["state"] == "ask" and got["found"][0]["checks"]["bed_ok"] is False and got["bed_klipper"] == [350.0, 350.0]
    assert not (home(folders) / "printer.json").exists()


def test_their_start_macro_must_be_there(rig):
    server, comp, folders, _ = rig
    comp.klippy_apis.objects = ["toolhead", "gcode_macro START_PRINT"]
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    start(server, comp)
    assert profile(comp)["found"][0]["checks"]["start_ok"] is False and profile(comp)["state"] == "ask"


def test_a_printer_with_a_filament_unit_gets_its_slots_and_the_start_macro_flag(rig):
    server, comp, folders, _ = rig
    comp.klippy_apis.objects = OBJECTS + ["ace", "gcode_macro ELYIR_BENCH_PRINT_START"]
    comp.tracker.update_status({"ace": {"gate_color": ["#FFFFFF"] * 8, "gate_material": ["PLA"] * 8}})
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    start(server, comp)
    pj = json.loads((home(folders) / "printer.json").read_text())
    assert pj["tools"] == 8 and pj["start_macro"] is True


def test_files_are_read_once_per_version(rig, monkeypatch):
    server, comp, folders, _ = rig
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_000)
    start(server, comp)
    import moonraker.components.printer_intent as pi
    reads = []
    real = pi.orca.read
    monkeypatch.setattr(pi.orca, "read", lambda p: reads.append(p) or real(p))
    run(comp._scan_profiles())
    assert reads == []
    gcode(gcodes(folders) / "a.gcode", mtime=1_000_500)
    run(comp._scan_profiles())
    assert len(reads) == 1
