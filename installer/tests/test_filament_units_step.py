"""filament_units: elyir puts Bench's own filament-unit service in KlipperACE's place (design/ace-driver/, A),
and klipperace puts everything back as it was."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "installer"))
import elyir_bench as a  # noqa: E402

PRINTER_CFG = """[include mainsail.cfg]
[printer]
kinematics: corexy

[save_variables]
filename: ~/variables.cfg

[include ace.cfg]
[include ace_diagnostics.cfg]
[include leds.cfg]

#*# <---------------------- SAVE_CONFIG ---------------------->
#*# [include ace.cfg]
#*# [probe]
"""

MOONRAKER_CONF = """[server]
host: 0.0.0.0

# ACE Manager REST API component
[ace_manager]
poll: 1

[update_manager KlipperACE]
type: git_repo
path: ~/KlipperACE
"""

LOADED = {"printer": {}, "save_variables": {}}   # what Klipper read from the printer's own files: no sensor there

STATUS = {
    "configfile": {"settings": {"filament_switch_sensor extruder_sensor": {"switch_pin": "EBBCan:PB8"},
                                "filament_switch_sensor runout": {"switch_pin": "PG12"}}},
    "ace": {"selected_gate": 1},
    "save_variables": {"variables": {"ace_gate_color": ["00FF00", "C4C7CC", "FFFFFF", "F4F4F2"],
                                     "ace_gate_type": ["PETG", "ABS", "", "ABS"]}},
}


def rig(tmp_path, monkeypatch, printing=None):
    data = tmp_path / "printer_data"
    config = data / "config"
    config.mkdir(parents=True)
    (config / "printer.cfg").write_text(PRINTER_CFG)
    (config / "moonraker.conf").write_text(MOONRAKER_CONF)
    release = tmp_path / "current"
    (release / "units" / "klipper").mkdir(parents=True)
    shutil.copy(REPO / "units" / "klipper" / "elyir_units.cfg", release / "units" / "klipper" / "elyir_units.cfg")
    (release / "units" / "service.py").write_text("")
    monkeypatch.setattr(a, "CURRENT", release)
    etc, units, calls = {}, set(), []

    def sudo(*cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ("systemctl", "disable"):
            units.discard(cmd[-1])
        elif cmd[:2] in (("systemctl", "enable"), ("systemctl", "restart")):
            units.add(cmd[-1])
    real_read = a.read
    monkeypatch.setattr(a, "read", lambda p, default="": etc.get(str(p), default) if str(p).startswith("/etc/") else real_read(p, default))
    monkeypatch.setattr(a, "sudo_write", lambda p, text: etc.__setitem__(p, text))
    monkeypatch.setattr(a, "sudo", sudo)
    monkeypatch.setattr(a, "is_active", lambda u: u in units)
    monkeypatch.setattr(a, "is_enabled", lambda u: u in units)
    monkeypatch.setattr(a, "klipper_restart", lambda facts, wait=90: calls.append(("FIRMWARE_RESTART",)))

    def http_json(url, timeout=None, **kw):
        if "configfile=settings" in url:
            return {"result": {"status": {"configfile": STATUS["configfile"]}}}
        if "configfile=config" in url:
            return {"result": {"status": {"configfile": {"config": LOADED}}}}
        return {"result": {"status": {"ace": STATUS["ace"], "save_variables": STATUS["save_variables"]}}}
    monkeypatch.setattr(a, "http_json", http_json)
    facts = {"printer_data": str(data), "print_state": printing, "user": "pi",
             "moonraker": {"url": "http://127.0.0.1:7125", "conf": str(config / "moonraker.conf")}}
    s = {"filament_units": "elyir", "printer_name": "Workshop", "units_before_macro": "NOZZLE_PRE_TOOL_CHANGE",
         "units_after_macro": "NOZZLE_POST_TOOL_CHANGE", "units_park": "170", "units_purge_moves": "70,348 25,349"}
    return a.Ctx(facts, s), config, etc, units, calls


def test_switching_on_turns_klipperace_off_brings_ours_in_and_carries_the_spools_over(tmp_path, monkeypatch):
    c, config, etc, units, calls = rig(tmp_path, monkeypatch)
    step = a.FilamentUnits()
    ok, why = step.check(c)
    assert not ok and why == "to switch from KlipperACE: elyir_units.cfg, printer.cfg, moonraker.conf"
    step.apply(c)
    cfg = (config / "printer.cfg").read_text()
    assert f"{a.UNITS_OFF}[include ace.cfg]\n{a.UNITS_OFF}[include ace_diagnostics.cfg]\n[include elyir_units.cfg]\n" in cfg
    assert "#*# [include ace.cfg]" in cfg and "[include leds.cfg]" in cfg
    ours = (config / "elyir_units.cfg").read_text()
    assert "pins: EBBCan:PB8" in ours and "[gcode_macro T15]\ngcode: ELYIR_TOOL T=15" in ours
    # KlipperACE made the head's sensor itself, so ours brings one for the screens
    assert "[filament_switch_sensor extruder_sensor]\nswitch_pin: EBBCan:PB8\npause_on_runout: False" in ours
    moon = (config / "moonraker.conf").read_text()
    assert f"{a.UNITS_OFF}[ace_manager]\n{a.UNITS_OFF}poll: 1\n" in moon and "\n[update_manager KlipperACE]" in moon
    assert c.restart_moonraker
    state = json.loads((config / a.UNITS_STATE).read_text())
    assert state["selected"] == 1 and state["spools"]["1"] == {"color": "#C4C7CC", "material": "ABS"} and "2" not in state["spools"]
    assert state["settings"] == {"before_macro": "NOZZLE_PRE_TOOL_CHANGE", "after_macro": "NOZZLE_POST_TOOL_CHANGE", "park": 170.0,
                                 "purge_moves": "70,348 25,349"}
    unit = etc[f"/etc/systemd/system/{a.UNITS_UNIT}"]
    assert "units/service.py --socket" in unit and "--moonraker ws://127.0.0.1:7125/websocket" in unit
    # Klipper lets go of the unit's port before the service starts
    assert calls.index(("FIRMWARE_RESTART",)) < calls.index(("systemctl", "restart", a.UNITS_UNIT))
    assert step.check(c) == (True, "Bench's own service, KlipperACE off")


def test_switching_back_puts_every_line_back_as_it_was(tmp_path, monkeypatch):
    c, config, etc, units, calls = rig(tmp_path, monkeypatch)
    a.FilamentUnits().apply(c)
    c.s["filament_units"] = "klipperace"
    ok, why = a.FilamentUnits().check(c)
    assert not ok and why.startswith("to put KlipperACE back: ")
    a.FilamentUnits().apply(c)
    assert (config / "printer.cfg").read_text() == PRINTER_CFG
    assert (config / "moonraker.conf").read_text() == MOONRAKER_CONF
    assert not (config / "elyir_units.cfg").exists() and a.UNITS_UNIT not in units
    assert a.FilamentUnits().check(c) == (True, "KlipperACE")


def test_never_while_printing_and_not_without_a_head_sensor(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch, printing="printing")
    with pytest.raises(a.StepFailed, match="printing"):
        a.FilamentUnits().apply(c)
    assert (config / "printer.cfg").read_text() == PRINTER_CFG
    c2, _, _, _, _ = rig(tmp_path / "two", monkeypatch)
    monkeypatch.setattr(a, "http_json", lambda url, **kw: {"result": {"status": {"configfile": {"settings": {}}}}})
    assert a.FilamentUnits().check(c2) == (False, "no extruder filament sensor found in Klipper's config, or this release has no units/")


def test_auto_is_the_default_and_is_saved_as_auto(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    c.s.pop("filament_units")
    assert not a.units_on(c.s)
    assert a.FilamentUnits().check(c) == (True, "KlipperACE")
    monkeypatch.setattr(a, "settings_path", lambda facts: config / "elyir-bench.conf")
    facts = dict(c.facts, kiosk={"enabled": False}, klipperscreen={"installed": False}, panel_output=None, host="workshop.local")
    assert a.default_settings(facts)["filament_units"] == "auto"
    a.save_settings(facts, dict(a.default_settings(facts), **c.s, filament_units="elyir"))
    text = (config / "elyir-bench.conf").read_text()
    assert "filament_units: elyir\n" in text and "units_before_macro: NOZZLE_PRE_TOOL_CHANGE\n" in text
    a.save_settings(facts, a.resolve_units(dict(c.facts, ace_units=1), dict(a.default_settings(facts), **c.s, filament_units="auto")))
    assert "filament_units: auto\n" in (config / "elyir-bench.conf").read_text()


def test_auto_drives_an_ace_nothing_else_drives(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    auto = {**c.s, "filament_units": "auto"}
    # KlipperACE's includes are in printer.cfg: it stays KlipperACE's (the person is asked instead)
    assert a.resolve_units(dict(c.facts, ace_units=1), auto)["filament_units"] == "klipperace"
    (config / "printer.cfg").write_text("[include mainsail.cfg]\n[printer]\nkinematics: corexy\n")
    on = a.resolve_units(dict(c.facts, ace_units=1), auto)
    assert on["filament_units"] == "elyir" and on["units_auto"] and a.units_on(on)
    assert a.resolve_units(dict(c.facts, ace_units=0), auto)["filament_units"] == "klipperace"
    # an explicit pick is never second-guessed
    assert a.resolve_units(dict(c.facts, ace_units=1), {**c.s, "filament_units": "klipperace"})["filament_units"] == "klipperace"
    c.s = on
    a.FilamentUnits().apply(c)
    # once on, a Klipper that doesn't answer or an unplugged unit doesn't switch it off again
    monkeypatch.setattr(a, "http_json", lambda url, **kw: (_ for _ in ()).throw(OSError("down")))
    assert a.resolve_units(dict(c.facts, ace_units=0), auto)["filament_units"] == "elyir"


def test_auto_needs_the_head_sensor(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    (config / "printer.cfg").write_text("[printer]\nkinematics: corexy\n")
    monkeypatch.setattr(a, "http_json", lambda url, **kw: {"result": {"status": {"configfile": {"settings": {}}}}})
    assert a.resolve_units(dict(c.facts, ace_units=1), {**c.s, "filament_units": "auto"})["filament_units"] == "klipperace"


def test_a_printer_on_klipperace_is_asked_once(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    state = {}
    monkeypatch.setattr(a, "load_state", lambda: dict(state))
    monkeypatch.setattr(a, "save_state", lambda st: state.update(st))
    monkeypatch.setattr(a, "settings_path", lambda facts: config / "elyir-bench.conf")
    monkeypatch.setattr(a.sys.stdin, "isatty", lambda: True)
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    facts = dict(c.facts, ace_units=1)
    s = a.resolve_units(facts, {**c.s, "filament_units": "auto"})
    assert a.ask_units(facts, s)["filament_units"] == "elyir" and state["units_asked"]
    assert a.ask_units(facts, s) == s                       # asked already: no second question
    state.clear()
    assert a.ask_units(dict(facts, ace_units=0), s) == s    # no unit, no question
    monkeypatch.setattr(a.sys.stdin, "isatty", lambda: False)
    assert a.ask_units(facts, s) == s                       # nobody at a terminal to answer
    assert "units_asked" not in state


def test_remove_takes_our_driver_off(tmp_path, monkeypatch):
    assert any(isinstance(step, a.FilamentUnits) for step in a.REMOVE_STEPS)


def test_once_switched_the_pin_comes_from_our_own_button_and_nothing_flips(tmp_path, monkeypatch):
    c, config, etc, units, calls = rig(tmp_path, monkeypatch)
    a.FilamentUnits().apply(c)
    restarts = calls.count(("FIRMWARE_RESTART",))
    # what Klipper reports once KlipperACE is off: its sensor gone, our button and our sensor there
    STATUS_AFTER = {"gcode_button elyir_units_sensor": {"pin": "EBBCan:PB8"}}
    loaded_after = dict(LOADED, **{"filament_switch_sensor extruder_sensor": {"switch_pin": "EBBCan:PB8"}})

    def http_json(url, timeout=None, **kw):
        if "configfile=settings" in url:
            return {"result": {"status": {"configfile": {"settings": STATUS_AFTER}}}}
        return {"result": {"status": {"configfile": {"config": loaded_after}}}}
    monkeypatch.setattr(a, "http_json", http_json)
    assert a.FilamentUnits().check(c) == (True, "Bench's own service, KlipperACE off")
    a.FilamentUnits().apply(c)
    assert calls.count(("FIRMWARE_RESTART",)) == restarts


def test_a_pin_set_in_elyir_bench_conf_keeps_its_pull_up_and_the_override_gets_it_bare(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    c.s["units_sensor_pin"] = "^EBBCan:PB8"
    a.FilamentUnits().apply(c)
    ours = (config / "elyir_units.cfg").read_text()
    assert "pins: EBBCan:PB8\n" in ours and "switch_pin: ^EBBCan:PB8\n" in ours and "pin: ^EBBCan:PB8\n" in ours


def test_a_printer_with_its_own_sensor_keeps_it(tmp_path, monkeypatch):
    c, config, *_ = rig(tmp_path, monkeypatch)
    monkeypatch.setitem(LOADED, "filament_switch_sensor toolhead", {"switch_pin": "PG12"})
    a.FilamentUnits().apply(c)
    assert "[filament_switch_sensor" not in (config / "elyir_units.cfg").read_text()


def test_a_changed_setting_reaches_a_printer_already_switched_and_the_service_restarts(tmp_path, monkeypatch):
    c, config, etc, units, calls = rig(tmp_path, monkeypatch)
    a.FilamentUnits().apply(c)
    state = json.loads((config / a.UNITS_STATE).read_text())
    state["selected"] = 3
    (config / a.UNITS_STATE).write_text(json.dumps(state))
    c.s["units_park"] = "160"
    assert a.FilamentUnits().check(c) == (False, "the service's settings changed in elyir-bench.conf")
    before = calls.count(("systemctl", "restart", a.UNITS_UNIT))
    a.FilamentUnits().apply(c)
    state = json.loads((config / a.UNITS_STATE).read_text())
    assert state["settings"]["park"] == 160.0 and state["settings"]["purge_moves"] == "70,348 25,349" and state["selected"] == 3
    assert calls.count(("systemctl", "restart", a.UNITS_UNIT)) == before + 1
    assert a.FilamentUnits().check(c) == (True, "Bench's own service, KlipperACE off")
