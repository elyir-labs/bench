"""`elyir-bench role controller|printer` (docs/bring-it-over.md, "Printer or Bench Box"): the lines the component
reads, in order, and what's put back when the Bench app doesn't come up."""
import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402


@pytest.fixture
def box(monkeypatch):
    calls = {"sudo": [], "run": [], "saved": [], "applies": 0}
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: calls["sudo"].append(cmd))
    monkeypatch.setattr(a, "run", lambda cmd, **kw: calls["run"].append(cmd))
    monkeypatch.setattr(a, "save_settings", lambda facts, s: calls["saved"].append(s.get("role")))
    monkeypatch.setattr(a, "is_enabled", lambda unit: True)
    monkeypatch.setattr(a, "role_apply", lambda: (calls.__setitem__("applies", calls["applies"] + 1), calls.get("apply_ok", True))[1])
    facts = {"host": "garage", "print_state": "standby", "moonraker": {"service": True}}
    s = {"role": "auto", "port": "8088", "panel": "elyir-bench"}
    return facts, s, calls


def lines(capsys):
    return [json.loads(l) for l in capsys.readouterr().out.splitlines()]


def test_a_printer_card_becomes_a_bench_box_in_three_steps_and_stops_moonraker_last(box, capsys):
    facts, s, calls = box
    assert a.role_main(argparse.Namespace(json=True, to="controller"), facts, s) == 0
    out = lines(capsys)
    assert out[0]["started"] == "role"
    assert [o["progress"]["step"] for o in out if "progress" in o] == ["The Bench app", "Its screen", "Klipper and Moonraker off"]
    assert [o["progress"]["done"] for o in out if "progress" in o] == [0, 1, 2]
    assert out[-1] == {"result": {"role": "controller", "url": "http://garage.local:8088/"}}
    assert calls["saved"] == ["controller"] and calls["applies"] == 1
    assert ("rm", "-f", str(a.PRINTER_AVAHI)) in calls["sudo"]                   # not a printer to find any more
    assert ("systemctl", "restart", a.KIOSK_UNIT) in calls["sudo"]               # the panel opens the Bench app
    off = calls["run"][-1]                                                        # outside Moonraker, last
    assert "systemd-run" in off[2] and off[-3:] == ["--now", "klipper", "moonraker"] and "disable" in off


def test_a_bench_app_that_doesnt_come_up_puts_the_printer_back(box, capsys):
    facts, s, calls = box
    calls["apply_ok"] = False
    assert a.role_main(argparse.Namespace(json=True, to="controller"), facts, s) == 1
    out = lines(capsys)
    assert "still a printer" in out[-1]["failed"]
    assert calls["saved"] == ["controller", "auto"] and calls["applies"] == 2     # the role back, applied again
    assert not calls["run"]                                                       # Klipper and Moonraker untouched


def test_not_while_printing(box, capsys):
    facts, s, calls = box
    facts["print_state"] = "printing"
    assert a.role_main(argparse.Namespace(json=True, to="controller"), facts, s) == 1
    assert "printing" in lines(capsys)[-1]["failed"] and not calls["saved"]


def test_already_a_box_says_so_and_changes_nothing(box, capsys):
    facts, s, calls = box
    s["role"] = "controller"
    assert a.role_main(argparse.Namespace(json=True, to="controller"), facts, s) == 0
    assert lines(capsys)[-1]["result"]["already"] and not calls["saved"] and not calls["run"]


def test_the_way_back_brings_klipper_and_moonraker_first(box, capsys):
    facts, s, calls = box
    s["role"] = "controller"
    assert a.role_main(argparse.Namespace(json=True, to="printer"), facts, s) == 0
    out = lines(capsys)
    assert [o["progress"]["step"] for o in out if "progress" in o] == ["Klipper and Moonraker on", "The printer app", "Its screen"]
    assert calls["sudo"][0] == ("systemctl", "enable", "--now", "klipper", "moonraker") and calls["saved"] == ["printer"]


def test_the_narrow_sudo_rule_covers_the_switch():
    rule = a.render_sudoers("pi")
    assert " ".join(a.role_off_cmd()) in rule and "enable --now klipper moonraker" in rule
