"""A filament unit set up from the screen (design/unit-setup/, B, stage 2): `elyir-bench unit scan|install|putback`.
Happy Hare's and AFC's installers are stand-ins here that write what theirs write; nothing upstream runs."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402

MAIN = "usb-Klipper_stm32h723xx_2B0035000F51313236343430-if00"
MMB = "usb-Klipper_stm32g0b1xx_4F0034000A50425539393020-if00"
ERB = "usb-Klipper_rp2040_E66138935F4B6A2B-if00"
TOOL = "1f0e5a2c9b11"

PRINTER_CFG = f"""[include mainsail.cfg]
[include macros/*.cfg]

[mcu]
serial: /dev/serial/by-id/{MAIN}

[mcu EBBCan]
canbus_uuid: {TOOL}

[printer]
kinematics: corexy

#*# <---------------------- SAVE_CONFIG ---------------------->
#*# [probe]
"""

MOONRAKER_CONF = "[server]\nhost: 0.0.0.0\n\n[update_manager mainsail]\ntype: web\n"

AFC_UNIT_TEMPLATE = """[include mcu/AFC_Lite.cfg]

[mcu Turtle_1]
canbus_uuid: <replace with your can UUID>
#serial: <replace with your /dev/serial/by-id/...> and comment out canbus_uuid above

[AFC_BoxTurtle Turtle_1]
hub: Turtle_1
"""


class Rig:
    def __init__(self, tmp_path, monkeypatch):
        self.home = tmp_path / "home"
        self.data = self.home / "printer_data"
        self.config = self.data / "config"
        (self.config / "macros").mkdir(parents=True)
        (self.config / "printer.cfg").write_text(PRINTER_CFG)
        (self.config / "moonraker.conf").write_text(MOONRAKER_CONF)
        (self.config / "macros" / "start.cfg").write_text("[gcode_macro PRINT_START]\ngcode:\n  G28\n")
        self.extras = self.home / "klipper" / "klippy" / "extras"
        self.extras.mkdir(parents=True)
        (self.extras / "probe.py").write_text("")
        (self.home / "moonraker" / "moonraker" / "components").mkdir(parents=True)
        monkeypatch.setattr(a, "HOME", self.home)
        monkeypatch.setattr(a, "BASE", self.home / "elyir-bench")
        monkeypatch.setattr(a, "STATE", self.home / "elyir-bench" / "state.json")
        self.facts = {"printer_data": str(self.data), "print_state": "standby", "ace_units": 0,
                      "moonraker": {"url": "http://127.0.0.1:7125", "conf": str(self.config / "moonraker.conf")}}
        self.restarts: list[str] = []
        self.ready = ["ready"]          # what Klipper does at each restart, in turn (the last one repeats)
        self.answers = True
        self.upstream_fails = False
        self.ran: list[list[str]] = []
        self.fetched: list[str] = []
        monkeypatch.setattr(a, "printing_now", lambda facts: None)
        monkeypatch.setattr(a, "port_here", lambda mcu: True)
        monkeypatch.setattr(a, "missing_packages", lambda pkgs: [])
        monkeypatch.setattr(a, "fetch_program", self.fetch)
        monkeypatch.setattr(a, "unit_upstream", self.upstream)
        monkeypatch.setattr(a, "unit_restart_klipper", self.restart)
        monkeypatch.setattr(a, "klipper_has", lambda facts, name: self.answers)

    def fetch(self, kind):
        self.fetched.append(kind)
        d = self.home / a.UNIT_PROGRAMS[kind]["dir"]
        d.mkdir(exist_ok=True)
        return d

    def restart(self, facts):
        state = self.ready.pop(0) if len(self.ready) > 1 else self.ready[0]
        self.restarts.append(state)
        return {"klipper": state, "message": "Klipper started with it." if state == "ready" else
                "mcu 'mmu': Unable to connect."}

    def upstream(self, cmd, cwd, env=None, timeout=900):
        """What their installers write: their folder, the include, a moonraker section and code linked into Klipper."""
        self.ran.append(cmd)
        if self.upstream_fails:
            raise a.StepFailed("its installer stopped: make: *** [install] Error 1")
        cfg = self.config / "printer.cfg"
        if cwd.name == "Happy-Hare":
            assert "CONFIG_PARAM_NUM_GATES" in (cwd / ".mmu_config").read_text()
            (self.config / "mmu" / "base").mkdir(parents=True)
            (self.config / "mmu" / "base" / "mmu.cfg").write_text("[mmu_machine]\n")
            (self.config / "printer.cfg.old-20261022").write_text(cfg.read_text())
            cfg.write_text("[include mmu/base/*.cfg]\n[include mmu/macros/*.cfg]\n" + cfg.read_text())
            moon = self.config / "moonraker.conf"
            moon.write_text(moon.read_text() + "\n[update_manager happy-hare]\ntype: git_repo\npath: ~/Happy-Hare\n"
                            "\n[mmu_server]\nenable_file_preprocessor: True\n")
            (self.extras / "mmu").mkdir()
            (self.extras / "mmu_machine.py").symlink_to(cwd / "extras" / "mmu_machine.py")
        else:
            (self.config / "AFC" / "mcu").mkdir(parents=True)
            (self.config / "AFC" / "AFC.cfg").write_text("[AFC]\nVarFile: ../printer_data/config/AFC/AFC.var\n")
            (self.config / "AFC" / "AFC_Turtle_1.cfg").write_text(AFC_UNIT_TEMPLATE)
            cfg.write_text(cfg.read_text().replace("#*# <----", "[include AFC/*.cfg]\n\n#*# <----", 1))
            (self.extras / "AFC.py").symlink_to(cwd / "extras" / "AFC.py")

    def state(self):
        return json.loads((self.home / "elyir-bench" / "state.json").read_text()) if (self.home / "elyir-bench" / "state.json").exists() else {}

    def kept_dirs(self):
        return sorted(p.name for p in self.data.iterdir() if p.name.startswith(a.UNIT_KEPT))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


def install(rig, unit="ercf_v2", board="mmb_1_1", slots=8, mcu=f"/dev/serial/by-id/{MMB}", s=None):
    said = []
    out = a.unit_install(rig.facts, s or {}, unit, board, slots, mcu, said.append)
    return out, said


# ---- the pairs ---------------------------------------------------------------------------------------------------

def test_the_pairs_start_with_ercf_on_an_mmb_and_box_turtle_on_an_afc_lite_and_none_is_tested_on_hardware_yet():
    pairs = {(p["unit"], p["board"]) for p in a.UNIT_PAIRS}
    assert ("ercf_v2", "mmb_1_1") in pairs and ("box_turtle", "afc_lite") in pairs
    assert all(p["tested_on_hardware"] is False for p in a.UNIT_PAIRS)
    for p in a.UNIT_PAIRS:
        kind = a.UNIT_KINDS[p["unit"]]["kind"]
        assert p["default"] in p["slots"]
        if kind == "happy_hare":
            assert a.UNIT_KINDS[p["unit"]]["hh"].startswith("MMU_TYPE_") and a.UNIT_BOARDS[p["board"]]["hh"].startswith("BOARD_TYPE_")
        else:
            assert p["afc"] and p["afc_mcu"]
    # one pin for each program, in one place
    assert {k: len(v["commit"]) for k, v in a.UNIT_PROGRAMS.items()} == {"happy_hare": 40, "afc": 40}
    cat = a.unit_catalog()
    assert [u["name"] for u in cat["units"]] == ["Box Turtle", "Night Owl", "ERCF v2", "Tradrack"]
    assert cat["programs"]["happy_hare"] == {"name": "Happy Hare", "version": "4.1", "guide": "https://github.com/moggieuk/Happy-Hare/wiki"}


def test_happy_hares_settings_name_the_unit_the_board_the_gates_and_the_port(rig):
    pair = a.unit_pair("ercf_v2", "mmb_1_1")
    text = a.render_hh_config(pair, 8, f"/dev/serial/by-id/{MMB}", rig.facts)
    lines = text.splitlines()
    for want in ("CONFIG_MMU_TYPE_ERCF_2_0=y", "CONFIG_PARAM_NUM_GATES=8", "CONFIG_BOARD_TYPE_MMB_1_1=y",
                 "CONFIG_CHOICE_MMU_CONNECTION_TYPE_SERIAL=y", "CONFIG_CHOICE_MMU_SERIAL_DEVICE_OTHER=y",
                 f'CONFIG_MMU_SERIAL_DEVICE_OTHER="/dev/serial/by-id/{MMB}"',
                 f'CONFIG_KLIPPER_CONFIG_HOME="{rig.config}"'):
        assert want in lines
    can = a.render_hh_config(a.unit_pair("tradrack", "easy_brd_2"), 10, "can:1a2b3c4d5e6f", rig.facts).splitlines()
    assert "CONFIG_MMU_TYPE_TRADRACK_1_0=y" in can and "CONFIG_BOARD_TYPE_MELLOW_EASY_BRD_CAN_2=y" in can
    assert 'CONFIG_MMU_CANBUS_UUID_OTHER="1a2b3c4d5e6f"' in can and "CONFIG_CHOICE_MMU_CONNECTION_TYPE_CANBUS=y" in can


def test_afcs_run_sets_its_menus_answers_and_calls_its_own_installer(rig):
    run = a.render_afc_run(a.unit_pair("box_turtle", "afc_lite"), rig.facts, rig.home / "AFC-Klipper-Add-On")
    assert "installation_type='BoxTurtle (4-Lane)'" in run
    assert "git_install='False'" in run and f"printer_config_dir='{rig.config}'" in run
    assert ". ./include/install_functions.sh || exit 1" in run
    assert run.rstrip().splitlines()[-2:] == ["install_afc", "exclude_from_klipper_git"]
    assert subprocess.run(["bash", "-n", "-c", run]).returncode == 0
    owl = a.render_afc_run(a.unit_pair("night_owl", "erb_2"), rig.facts, rig.home / "AFC-Klipper-Add-On")
    assert "installation_type='NightOwl'" in owl


def test_afcs_unit_gets_its_port_and_loses_the_templates_placeholders():
    usb = a.render_mcu_port(AFC_UNIT_TEMPLATE, "mcu Turtle_1", f"/dev/serial/by-id/{MMB}")
    assert f"[mcu Turtle_1]\nserial: /dev/serial/by-id/{MMB}\n\n[AFC_BoxTurtle Turtle_1]" in usb
    assert "<replace" not in usb
    can = a.render_mcu_port(AFC_UNIT_TEMPLATE, "mcu Turtle_1", "can:1a2b3c4d5e6f")
    assert "[mcu Turtle_1]\ncanbus_uuid: 1a2b3c4d5e6f\n" in can and "serial" not in can.split("[AFC_BoxTurtle")[0]


# ---- the board scan ----------------------------------------------------------------------------------------------

def test_the_scan_finds_boards_klipper_doesnt_use_yet_and_says_probably(rig):
    here = {"serial": [MAIN, MMB, "usb-ANYCUBIC_ACE_1-if00"], "can": [TOOL]}
    found = a.unit_found(rig.facts, here)
    assert found == [{"mcu": f"/dev/serial/by-id/{MMB}", "chip": "stm32g0b1xx", "words": "STM32G0B1 on USB"}]
    assert a.unit_probably("ercf_v2", found) == {"family": "mmb", "mcu": f"/dev/serial/by-id/{MMB}"}
    assert a.unit_probably("tradrack", found)["family"] == "mmb"
    assert a.unit_probably("box_turtle", found) is None          # an AFC-Lite isn't an STM32G0B1
    # an RP2040 could be an EASY-BRD or an ERB: not a guess
    rp = a.unit_found(rig.facts, {"serial": [MAIN, ERB], "can": []})
    assert a.unit_probably("ercf_v2", rp) is None and a.unit_probably("night_owl", rp)["family"] == "erb"
    # two new boards: which one is the unit's isn't a guess either
    assert a.unit_probably("ercf_v2", a.unit_found(rig.facts, {"serial": [MMB, ERB], "can": []})) is None
    # a CAN board that hasn't been claimed yet
    can = a.unit_found(rig.facts, {"serial": [MAIN], "can": [TOOL, "aa11bb22cc33"]})
    assert can == [{"mcu": "can:aa11bb22cc33", "chip": None, "words": "A board on CAN"}]


# ---- installing --------------------------------------------------------------------------------------------------

def test_happy_hare_is_installed_with_a_copy_kept_first_then_klipper_restarts_once(rig):
    out, said = install(rig)
    ids = [m["progress"]["id"] for m in said]
    assert ids == ["fetch", "settings", "restart", "answers", "answers"]
    assert [m["progress"]["step"] for m in said][:4] == ["Fetching Happy Hare 4.1", "Writing its settings",
                                                        "Restarting Klipper, once", "Checking the unit answers"]
    assert rig.fetched == ["happy_hare"] and rig.restarts == ["ready"]
    assert rig.ran[0][:4] == ["./install.sh", "-z", "-y", "-s"]
    assert out == {"kind": "happy_hare", "unit": "ercf_v2", "board": "mmb_1_1", "slots": 8, "program": "Happy Hare 4.1",
                   "kept": str(rig.data / rig.kept_dirs()[0])}
    kept = rig.data / rig.kept_dirs()[0]
    assert (kept / "printer.cfg").read_text() == PRINTER_CFG
    assert (rig.config / "printer.cfg").read_text().startswith("[include mmu/base/*.cfg]")
    # Mainsail's updater never moves Happy Hare past the version Bench tested; its own Moonraker section stays
    moon = (rig.config / "moonraker.conf").read_text()
    assert "[update_manager happy-hare]" not in moon and "[mmu_server]" in moon and "[update_manager mainsail]" in moon
    k = rig.state()["unit_kept"]
    assert k["unit"] == "ercf_v2" and k["program"] == "Happy Hare 4.1"
    assert k["changed"]["printer.cfg"] is True and k["changed"]["mmu/base/mmu.cfg"] is False
    assert str(rig.extras / "mmu_machine.py") in k["added"]
    assert a.unit_kept_view()["board"] == "mmb_1_1"


def test_put_it_back_restores_the_config_takes_their_code_out_and_restarts_klipper(rig):
    install(rig)
    (rig.config / "macros" / "mine.cfg").write_text("[gcode_macro MINE]\ngcode:\n")   # written after: stays
    said = []
    out = a.unit_putback(rig.facts, {}, said.append)
    assert out["put_back"] is True and out["klipper"] == "ready"
    assert [m["progress"]["id"] for m in said] == ["settings", "restart"]
    assert (rig.config / "printer.cfg").read_text() == PRINTER_CFG
    assert (rig.config / "moonraker.conf").read_text() == MOONRAKER_CONF
    assert not (rig.config / "mmu").exists() and not (rig.config / "printer.cfg.old-20261022").exists()
    assert not (rig.extras / "mmu_machine.py").is_symlink() and not (rig.extras / "mmu").exists()
    assert (rig.extras / "probe.py").exists() and (rig.config / "macros" / "mine.cfg").exists()
    assert "unit_kept" not in rig.state() and rig.restarts == ["ready", "ready"]
    assert rig.kept_dirs()   # the copy itself stays
    with pytest.raises(a.StepFailed, match="no copy"):
        a.unit_putback(rig.facts, {}, said.append)


def test_afc_gets_its_port_written_and_its_include(rig):
    out, _ = install(rig, "box_turtle", "afc_lite", None, f"/dev/serial/by-id/{MAIN.replace('2B00', '3C00')}")
    assert out["slots"] == 4 and out["program"] == "AFC 1.2" and rig.ran[0][0] == "bash"
    unit = (rig.config / "AFC" / "AFC_Turtle_1.cfg").read_text()
    assert "serial: /dev/serial/by-id/usb-Klipper_stm32h723xx_3C00" in unit and "<replace" not in unit
    assert "[include AFC/*.cfg]" in (rig.config / "printer.cfg").read_text()
    a.unit_putback(rig.facts, {}, lambda m: None)
    assert not (rig.config / "AFC").exists() and (rig.config / "printer.cfg").read_text() == PRINTER_CFG


def test_never_while_printing_and_never_beside_another_unit_or_an_ace(rig, monkeypatch):
    monkeypatch.setattr(a, "printing_now", lambda facts: "vase.gcode, 40 %")
    with pytest.raises(a.StepFailed, match="Printing: vase.gcode"):
        install(rig)
    monkeypatch.setattr(a, "printing_now", lambda facts: None)
    (rig.config / "printer.cfg").write_text("[include AFC/*.cfg]\n" + PRINTER_CFG)
    with pytest.raises(a.StepFailed, match="AFC is set up on this printer already"):
        install(rig)
    (rig.config / "printer.cfg").write_text(PRINTER_CFG)
    with pytest.raises(a.StepFailed, match="ACE Pro"):
        install(rig, s={"filament_units": "elyir"})
    rig.facts["ace_units"] = 1
    with pytest.raises(a.StepFailed, match="ACE Pro"):
        install(rig)
    rig.facts["ace_units"] = 0
    with pytest.raises(a.StepFailed, match="doesn't know"):
        install(rig, "night_owl", "mmb_1_1")
    with pytest.raises(a.StepFailed, match="slots"):
        install(rig, slots=7)
    monkeypatch.setattr(a, "port_here", lambda mcu: False)
    with pytest.raises(a.StepFailed, match="isn't plugged in"):
        install(rig)
    assert rig.fetched == [] and rig.kept_dirs() == [] and rig.restarts == []


def test_when_klipper_doesnt_start_with_it_the_old_settings_go_back_at_once(rig):
    rig.ready = ["error", "ready"]
    with pytest.raises(a.StepFailed, match=r"Klipper didn't start with it: mcu 'mmu': Unable to connect\. Your old settings are back"):
        install(rig)
    assert (rig.config / "printer.cfg").read_text() == PRINTER_CFG and not (rig.config / "mmu").exists()
    assert not (rig.extras / "mmu_machine.py").is_symlink()
    assert "unit_kept" not in rig.state() and rig.restarts == ["error", "ready"]


def test_when_their_installer_stops_nothing_is_changed(rig):
    rig.upstream_fails = True
    with pytest.raises(a.StepFailed, match=r"its installer stopped: .*Error 1\. Nothing was changed"):
        install(rig)
    assert (rig.config / "printer.cfg").read_text() == PRINTER_CFG and "unit_kept" not in rig.state()
    assert rig.restarts == []


def test_when_klipper_starts_but_the_unit_doesnt_answer_the_copy_is_kept_for_put_it_back(rig):
    rig.answers = False
    with pytest.raises(a.StepFailed, match="Happy Hare didn't answer. Your old settings are kept"):
        install(rig)
    assert rig.state()["unit_kept"]["unit"] == "ercf_v2"


def test_the_command_says_who_it_is_then_its_steps_and_its_answer_last(rig, monkeypatch, capsys):
    monkeypatch.setattr(a, "detect", lambda: rig.facts)
    monkeypatch.setattr(a, "load_settings", lambda facts: {"filament_units": "klipperace"})
    monkeypatch.setattr(a, "resolve_slicer", lambda facts, s: s)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    code = a.main(["--json", "unit", "install", "--unit", "ercf_v2", "--board", "mmb_1_1", "--slots", "8",
                   "--mcu", f"/dev/serial/by-id/{MMB}", "--kind", "happy_hare"])
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert code == 0 and lines[0]["started"] == "unit-install"
    assert [ln["progress"]["id"] for ln in lines[1:-1]] == ["fetch", "settings", "restart", "answers", "answers"]
    assert lines[-1]["result"]["program"] == "Happy Hare 4.1"
    code = a.main(["--json", "unit", "install", "--unit", "box_turtle", "--board", "afc_lite", "--mcu", "x", "--kind", "happy_hare"])
    assert code == 1 and json.loads(capsys.readouterr().out.splitlines()[-1]) == {"failed": "box_turtle isn't run by happy_hare."}


# ---- removing Bench gives Mainsail its updater back ---------------------------------------------------------------

def test_removing_bench_puts_their_update_entry_back_and_their_copy_on_its_branch(rig, monkeypatch):
    install(rig)
    assert rig.state()["unit_kept"]["updater"] == "[update_manager happy-hare]\ntype: git_repo\npath: ~/Happy-Hare"
    home = rig.home / "Happy-Hare"
    (home / ".git").mkdir()
    gits = []
    monkeypatch.setattr(a.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    monkeypatch.setattr(a, "run", lambda cmd, check=True, timeout=600: gits.append(cmd))
    assert a.unit_hand_back(rig.facts) == "Happy Hare stays, and Mainsail updates it again"
    moon = (rig.config / "moonraker.conf").read_text()
    assert moon.count("[update_manager happy-hare]") == 1 and "path: ~/Happy-Hare" in moon and "[mmu_server]" in moon
    assert gits == [["/usr/bin/git", "-C", str(home), "checkout", "--quiet", "-B", "main"],
                    ["/usr/bin/git", "-C", str(home), "branch", "--quiet", "--set-upstream-to=origin/main", "main"]]
    a.unit_hand_back(rig.facts)   # twice: still one entry
    assert (rig.config / "moonraker.conf").read_text().count("[update_manager happy-hare]") == 1


def test_afcs_entry_is_one_like_its_own_since_its_run_never_writes_one(rig, monkeypatch):
    install(rig, unit="box_turtle", board="afc_lite", slots=4)
    monkeypatch.setattr(a.shutil, "which", lambda name: None)
    a.unit_hand_back(rig.facts)
    moon = (rig.config / "moonraker.conf").read_text()
    assert "[update_manager afc-software]\ntype: git_repo\npath: ~/AFC-Klipper-Add-On\n" in moon
    assert f"origin: {a.UNIT_PROGRAMS['afc']['repo']}\nprimary_branch: main\n" in moon


def test_nothing_to_hand_back_without_a_unit_bench_set_up_or_after_put_it_back(rig):
    before = (rig.config / "moonraker.conf").read_text()
    assert a.unit_hand_back(rig.facts) is None
    install(rig)
    a.unit_putback(rig.facts, {}, lambda m: None)
    assert a.unit_hand_back(rig.facts) is None
    assert (rig.config / "moonraker.conf").read_text() == before
