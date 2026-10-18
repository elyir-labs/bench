"""The power button (design/power/, A): a press is Turn off (the nozzle cools first), a second press while it waits
is now, mid-print it's ignored, and with no printer answering it powers off at once."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import power_key as pk  # noqa: E402


def intent(**power):
    return {"power": dict({"allowed": True, "why": None, "cool_to": 50.0, "kind": None}, **power)}


def test_a_press_is_turn_off_and_a_second_is_now():
    assert pk.decide(intent()) == "off"
    assert pk.decide(intent(kind="off", going=False, progress=0.2)) == "now"


def test_mid_print_restarting_or_already_going_it_is_ignored():
    assert pk.decide(intent(allowed=False, why="Not while it's printing.")) == "nothing"
    assert pk.decide(intent(kind="restart", going=False)) == "nothing"
    assert pk.decide(intent(kind="off", going=True)) == "nothing"


def test_no_printer_answering_or_an_older_one_powers_off_at_once():
    assert pk.decide(None) == "halt"
    assert pk.decide({"state": "ready"}) == "halt"


def test_the_button_is_found_by_name(tmp_path):
    for n, name in (("event0", "pwr_button"), ("event2", "vc4-hdmi")):
        d = tmp_path / n / "device"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n")
    assert pk.find_button(str(tmp_path)) == "/dev/input/event0"
    (tmp_path / "event0" / "device" / "name").write_text("vc4-hdmi-1\n")
    assert pk.find_button(str(tmp_path)) is None


def test_a_press_asks_the_printer_and_falls_back_to_poweroff(monkeypatch):
    calls, ran = [], []
    monkeypatch.setattr(pk.subprocess, "run", lambda cmd, check=False: ran.append(cmd))

    def ask(url, path, body=None, timeout=4):
        calls.append((path, body))
        if path == "/printer/intent":
            return intent()
        raise OSError("refused")
    monkeypatch.setattr(pk, "ask", ask)
    assert pk.press("http://127.0.0.1:7125") == "halt"   # the printer didn't take it: off as before
    assert calls[1] == ("/printer/intent/action", {"action": "power_off", "source": "power button"})
    assert ran == [["sudo", "-n", "systemctl", "poweroff"]]
    calls.clear(); ran.clear()
    monkeypatch.setattr(pk, "ask", lambda url, path, body=None, timeout=4: intent() if path == "/printer/intent" else {"ok": True})
    assert pk.press("http://127.0.0.1:7125") == "off" and ran == []
