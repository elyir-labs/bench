"""Printer or Bench Box (design/role/, B), the component's side: the scan's board count, role_box running
`elyir-bench --json role controller` in the background and following its lines, a failure said, role_back, and never
while printing. Against the stand-in Moonraker of test_component.py and a stand-in `elyir-bench`."""
import json
import shlex
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bring_component import NO_CONFIG, act, rig  # noqa: E402,F401
from test_component import run  # noqa: E402

STEP = json.dumps({"progress": {"step": "Its screen", "done": 1, "of": 3}})


def role_installer(cli: Path, ends: str) -> Path:
    """`elyir-bench --json role controller`: who it is, a step, then (as on a printer) Moonraker stopping ends it all,
    or it fails and says why. A scan answers with no boards (nothing plugged in)."""
    asked = cli.parent / "asked-role"
    tail = {"stop": "sleep 30", "fail": "echo " + shlex.quote(json.dumps({"failed": "The Bench app's site didn't start."}))}[ends]
    cli.write_text("#!/bin/sh\n"
                   f"echo \"$@\" >> {asked}\n"
                   "echo \"{\\\"started\\\": \\\"$2\\\", \\\"pid\\\": $$}\"\n"
                   "case \"$2\" in\n"
                   "  bring) echo " + shlex.quote(json.dumps({"sources": [], "found": [], "boards": 0})) + " ;;\n"
                   f"  role) echo {shlex.quote(STEP)}; {tail} ;;\n"
                   "esac\n")
    cli.chmod(0o755)
    return asked


def tick_until(comp, until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        comp._bring_tick()
        comp._role_tick()
        if until(comp._bring_view()):
            return comp._bring_view()
        time.sleep(0.05)
    raise AssertionError(f"never got there: {comp._bring_view()}")


def test_nothing_plugged_in_says_no_boards(rig):
    server, comp, _ = rig
    role_installer(Path(comp.cli), "stop")
    comp._bring_scanned = True    # the scan by itself is test_bring_component's; this one is asked for
    act(comp, "bring_scan")
    got = tick_until(comp, lambda b: b["state"] == "idle" and b["boards"] is not None)
    assert got["boards"] == 0 and got["role"] is None


def test_role_box_runs_the_installer_and_follows_its_steps(rig, monkeypatch):
    server, comp, _ = rig
    asked = role_installer(Path(comp.cli), "stop")
    monkeypatch.setattr("socket.gethostname", lambda: "bench-box")
    act(comp, "role_box")
    b = comp._bring_view()
    assert b["role"] == {"state": "switching", "progress": None, "why": None, "url": "http://bench-box.local:8088/"}
    got = tick_until(comp, lambda b: (b["role"] or {}).get("progress") is not None)
    assert got["role"]["progress"] == {"step": "Its screen", "done": 1, "of": 3}
    assert got["role"]["state"] == "switching"
    assert "--json role controller" in asked.read_text().splitlines()
    with pytest.raises(Exception, match="becoming a Bench Box now"):
        act(comp, "role_box")


def test_a_failure_is_said_and_role_back_clears_it(rig):
    server, comp, _ = rig
    role_installer(Path(comp.cli), "fail")
    act(comp, "role_box")
    got = tick_until(comp, lambda b: (b["role"] or {}).get("state") == "failed")
    assert got["role"]["why"] == "The Bench app's site didn't start."
    act(comp, "role_back")
    assert comp._bring_view()["role"] is None


def test_never_while_printing(rig):
    server, comp, _ = rig
    role_installer(Path(comp.cli), "stop")
    comp.tracker.status.setdefault("print_stats", {})["state"] = "printing"
    with pytest.raises(Exception, match="printing"):
        act(comp, "role_box")
    assert comp._bring_view()["role"] is None
