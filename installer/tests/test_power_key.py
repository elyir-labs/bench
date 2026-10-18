"""The power button's install step (design/power/): found by name, its unit, logind's drop-in, and sudo for it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402

PI5 = '''I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="pwr_button"
P: Phys=gpio-keys/input0

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="vc4-hdmi-0"
'''


def test_a_power_button_is_found_by_name(tmp_path):
    f = tmp_path / "devices"
    f.write_text(PI5)
    assert a.power_button(str(f))
    f.write_text('N: Name="vc4-hdmi-0"\n')
    assert not a.power_button(str(f))
    assert not a.power_button(str(tmp_path / "missing"))


def test_its_unit_listens_as_the_printer_user_and_asks_moonraker():
    unit = a.render_power_key_unit({"user": "pi", "moonraker": {"url": "http://127.0.0.1:7125"}})
    assert "User=pi\nSupplementaryGroups=input\n" in unit
    assert "/printer/power_key.py --moonraker http://127.0.0.1:7125" in unit


def test_logind_leaves_a_short_press_and_keeps_a_long_one():
    assert "HandlePowerKey=ignore\n" in a.LOGIND_POWER_CONF
    assert "HandlePowerKeyLongPress=poweroff\n" in a.LOGIND_POWER_CONF


def test_sudo_covers_it_and_nothing_wider():
    rules = a.render_sudoers("pi")
    for cmd in (f"tee /etc/systemd/system/{a.POWER_KEY_UNIT}", f"tee {a.LOGIND_POWER}", "systemctl kill -s HUP systemd-logind",
                "systemctl poweroff"):
        assert cmd in rules, cmd
    assert "systemctl poweroff *" not in rules


def test_it_is_a_step_for_printers_and_boxes():
    step = next(s for s in a.STEPS if s.name == "power button")
    assert set(step.roles) == {"printer", "controller"}


def test_moonraker_says_when_it_may_not_turn_the_pi_off(monkeypatch):
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}}
    monkeypatch.setattr(a, "http_json", lambda url, timeout=4: {"result": {"warnings": [
        "PolicyKit permission 'org.freedesktop.login1.power-off' not granted. The shutdown API will be disabled"]}})
    assert a.power_blocked(facts) is True
    step = next(s for s in a.STEPS if s.name == "turning off")
    ok, words = step.check(type("C", (), {"facts": facts})())
    assert not ok and "PolicyKit" in words
    monkeypatch.setattr(a, "http_json", lambda url, timeout=4: {"result": {"warnings": []}})
    assert a.power_blocked(facts) is False

    def down(url, timeout=4):
        raise OSError("refused")
    monkeypatch.setattr(a, "http_json", down)
    assert a.power_blocked(facts) is None


def test_without_full_sudo_it_says_what_to_run_once(monkeypatch):
    monkeypatch.setattr(a, "power_blocked", lambda facts: True)
    monkeypatch.setattr(a, "sudo_mode", lambda: "elyir-bench")
    step = next(s for s in a.STEPS if s.name == "turning off")
    try:
        step.apply(type("C", (), {"facts": {}})())
    except a.StepFailed as e:
        assert "set-policykit-rules.sh" in str(e)
    else:
        raise AssertionError("it should have said what to run")
