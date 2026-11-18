"""Updates (design/updates/, A + A), the component's side: the release it runs and the updater's last word in the
intent, and Update now starting the updater's own service, never during a print."""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bring_component import act, rig  # noqa: E402,F401


def base(comp) -> Path:
    b = Path(comp.installer_state).parent
    (b / "current").mkdir(parents=True, exist_ok=True)
    (b / "current" / "VERSION").write_text("2026.11.07-aaa\n")
    return b


def test_no_release_no_row(rig):
    _, comp, _ = rig
    assert comp._current()["update"] is None


def test_the_updaters_last_word(rig):
    _, comp, _ = rig
    b = base(comp)
    assert comp._current()["update"] == {"version": "2026.11.07-aaa", "latest": None, "newer": False, "state": "idle",
                                         "why": None, "done": None, "of": None, "went_back": False, "checked": None}
    (b / "update.json").write_text(json.dumps({"state": "downloading", "latest": {"version": "2026.11.08-bbb"}, "newer": True,
                                               "done": 5, "of": 10, "at": time.time()}))
    u = comp._current()["update"]
    assert u["state"] == "downloading" and u["latest"] == "2026.11.08-bbb" and u["newer"] and (u["done"], u["of"]) == (5, 10)
    (b / "update.json").write_text(json.dumps({"state": "installing", "at": time.time() - 7200}))
    assert comp._current()["update"]["state"] == "idle", "a run the machine restarted under isn't still going"


def test_update_now_starts_the_service(rig, monkeypatch):
    _, comp, _ = rig
    b = base(comp)
    ran = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: ran.append(cmd))
    act(comp, "update_now")
    assert ran == [["sudo", "-n", "systemctl", "start", "--no-block", "elyir-bench-update.service"]]
    assert (b / "update-now").exists()


def test_not_during_a_print(rig, monkeypatch):
    _, comp, _ = rig
    base(comp)
    comp.tracker.status["print_stats"] = {"state": "printing"}
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("started during a print"))
    with pytest.raises(Exception, match="Not while it's printing"):
        act(comp, "update_now")
