"""A USB stick (design/usb/), the component's side: what the installer read off the stick in the intent, the screen
saying it saw it, Not now, and what's ticked handed to the installer's own service."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bring_component import act, rig  # noqa: E402,F401

BOOT = "boot-1"


@pytest.fixture
def stick(rig, monkeypatch):
    _, comp, _ = rig
    b = Path(comp.installer_state).parent
    b.mkdir(parents=True, exist_ok=True)
    real_open = open

    def fake_open(path, *a, **k):
        if path == "/proc/sys/kernel/random/boot_id":
            import io
            return io.StringIO(BOOT + "\n")
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    u = {"boot": BOOT, "dev": "sda1", "id": "AB12", "label": "BENCH", "present": True, "readable": True, "folder": True,
         "app": {"file": "elyir-bench-2026.11.09-bbb.tar.gz", "version": "2026.11.09-bbb", "why": None},
         "os": None, "keys": [{"id": "k1", "kind": "ssh-ed25519", "name": "laptop", "fp": "SHA256:x"}],
         "wifi": {"name": "Home Wi-Fi", "can": True}, "seen": False, "skipped": False, "take": None}
    (b / "usb.json").write_text(json.dumps(u))
    return comp, b


def read(b):
    return json.loads((b / "usb.json").read_text())


def test_no_stick_no_view(rig):
    _, comp, _ = rig
    assert comp._current()["usb"] is None


def test_what_is_on_the_stick(stick):
    comp, b = stick
    v = comp._current()["usb"]
    assert v["app"]["version"] == "2026.11.09-bbb" and v["keys"][0]["name"] == "laptop" and v["take"] is None
    assert "boot" not in v and "dev" not in v
    u = read(b)
    (b / "usb.json").write_text(json.dumps({**u, "boot": "an-earlier-boot"}))
    assert comp._current()["usb"] is None, "from before a restart"


def test_seen_and_not_now(stick, monkeypatch):
    comp, b = stick
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("nothing to start"))
    act(comp, "usb_seen")
    assert read(b)["seen"] is True
    act(comp, "usb_skip")
    u = read(b)
    assert u["skipped"] is True and u["skips"] == ["AB12/2026.11.09-bbb/None"]


def test_whats_ticked_goes_to_the_installers_service(stick, monkeypatch):
    comp, b = stick
    ran = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: ran.append(cmd))
    act(comp, "usb_take", app=True, keys=["k1"], wifi=False)
    assert ran == [["sudo", "-n", "systemctl", "start", "--no-block", "elyir-bench-usb.service"]]
    assert json.loads((b / "usb-take.json").read_text()) == {"id": "AB12", "app": True, "os": False, "keys": ["k1"], "wifi": False}
    act(comp, "usb_report")
    assert json.loads((b / "usb-take.json").read_text()) == {"id": "AB12", "report": True}


def test_one_at_a_time_and_only_with_the_stick_in(stick, monkeypatch):
    comp, b = stick
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    u = read(b)
    (b / "usb.json").write_text(json.dumps({**u, "take": {"state": "copying"}}))
    with pytest.raises(Exception, match="still taking"):
        act(comp, "usb_take", app=True)
    (b / "usb.json").write_text(json.dumps({**u, "present": False}))
    with pytest.raises(Exception, match="back in"):
        act(comp, "usb_report")


def test_closing_a_finished_take(stick):
    comp, b = stick
    u = read(b)
    (b / "usb.json").write_text(json.dumps({**u, "present": False, "take": {"state": "done", "app": "2026.11.09-bbb"}}))
    assert comp._current()["usb"]["take"]["state"] == "done", "the result shows after the stick is out"
    act(comp, "usb_skip")
    assert comp._current()["usb"] is None
