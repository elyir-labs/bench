"""Bring it over, the component's side (docs/bring-it-over.md): GET /printer/intent/bring, the bring_* actions, the
installer run in the background with its JSON lines followed from a file (across a Moonraker restart too), a fresh
card scanned once by itself, and the export another printer brings this one's database from. Against the stand-in
Moonraker of test_component.py and a stand-in `elyir-bench` that answers like the installer."""

import base64
import json
import shlex
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_component import FakeConfig, FakeWebRequest, KlippyState, load, run  # noqa: E402

NO_CONFIG = "Unable to open config file /home/pi/printer_data/config/printer.cfg\nPrinter is halted\n"
SOURCE = {"id": "card-sda2", "kind": "card", "name": "Voron", "detail": "In a USB reader", "when": 1791100000,
          "files": 19, "gcodes": 46, "history": 212, "boards": ["stm32f446xx", "can 6cc850bbec73"]}
PLAN = {"id": "card-sda2", "config": 19, "history": 212, "spools": True, "mainsail": True,
        "gcodes": {"count": 46, "bytes": 812000000}, "notes": [],
        "boards": [{"name": "Main board", "chip": "stm32f446xx", "match": "same", "words": "STM32F446, same serial"}]}
FOUND = ["Main board · STM32F446 on USB", "Toolhead board · on CAN"]


def installer(path: Path, apply_ends: str = "result") -> Path:
    """`elyir-bench --json bring <kind> …`: says who it is, then answers as the installer does."""
    asked = path.parent / "asked"
    answers = {
        "scan": json.dumps({"sources": [SOURCE], "found": FOUND}),
        "plan": json.dumps({"plan": PLAN}),
        "address": json.dumps({"source": dict(SOURCE, id="printer-studio-local", kind="printer", name="Studio"),
                               "plan": dict(PLAN, id="printer-studio-local")}),
        "apply": {"result": json.dumps({"result": {"klipper": "ready", "message": "Klipper started with it."}}),
                  "failed": json.dumps({"failed": "Moonraker didn't take its history. Nothing was changed."}),
                  "nothing": ""}[apply_ends],
    }
    progress = json.dumps({"progress": {"step": "Keeping your current config", "done": 1, "of": 5}})
    path.write_text("#!/bin/sh\n"
                    f"echo \"$@\" >> {asked}\n"
                    "echo \"{\\\"started\\\": \\\"$3\\\", \\\"pid\\\": $$}\"\n"
                    "case \"$3\" in\n"
                    + "".join(f"  {k}) {'echo ' + shlex.quote(progress) + '; ' if k == 'apply' else ''}"
                              f"{'echo ' + shlex.quote(v) if v else 'true'} ;;\n" for k, v in answers.items())
                    + "esac\n")
    path.chmod(0o755)
    return asked


def settle(comp, until, timeout=5.0):
    """Ticks until the run has answered (the stand-in runs on its own, like the installer)."""
    end = time.time() + timeout
    while time.time() < end:
        comp._bring_tick()
        if until(comp._bring_view()):
            return comp._bring_view()
        time.sleep(0.05)
    raise AssertionError(f"bring never got there: {comp._bring_view()}")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A fresh card: Moonraker up, Klipper in error with no printer.cfg."""
    server, comp = load(tmp_path, monkeypatch)
    comp.installer_state = str(tmp_path / "elyir-bench" / "state.json")
    comp.cli = str(tmp_path / "elyir-bench-cli")
    asked = installer(Path(comp.cli))
    server.kc.state, server.kc.state_message = KlippyState.ERROR, NO_CONFIG
    run(comp.component_init())
    return server, comp, asked


def act(comp, action, **args):
    return run(comp._handle_action(FakeWebRequest(action=action, args=args)))


def test_a_fresh_card_is_looked_at_once_by_itself(rig):
    server, comp, asked = rig
    i = comp._current()
    assert i["state"] == "setup" and i["detail"].startswith("It can't see how the printer is wired")
    comp._bring_tick()
    assert comp._bring_view()["state"] == "scanning"
    got = settle(comp, lambda b: b["state"] == "idle")
    assert got == {"state": "idle", "sources": [SOURCE], "plan": None, "progress": None, "result": None, "why": None,
                   "found": FOUND, "boards": None, "role": None, "cloud": None}
    assert comp._current()["detail"] == "It found these. It can't see how they're wired, so it needs a config, once."
    comp._bring_tick()
    comp._bring_tick()
    assert asked.read_text() == "--json bring scan\n"                    # once, not every tick
    assert ("printer_intent:bring", (got,)) in server.sent
    assert run(comp._handle_bring(FakeWebRequest())) == got


def test_plan_then_bring_it_over(rig):
    server, comp, asked = rig
    act(comp, "bring_scan")
    settle(comp, lambda b: b["state"] == "idle")
    with pytest.raises(Exception, match="That isn't one it found"):
        act(comp, "bring_plan", id="card-sdz9")
    got = act(comp, "bring_plan", id="card-sda2")
    assert got["bring"]["state"] == "planning"
    assert settle(comp, lambda b: b["state"] == "idle")["plan"] == PLAN
    act(comp, "bring_apply", id="card-sda2", gcodes=True)
    assert comp._bring_view()["state"] == "bringing"
    with pytest.raises(Exception, match="It's bringing a setup over now"):
        act(comp, "bring_scan")
    done = settle(comp, lambda b: b["state"] == "done")
    assert done["result"] == {"klipper": "ready", "message": "Klipper started with it."}
    assert done["progress"] == {"step": "Keeping your current config", "done": 1, "of": 5}
    assert asked.read_text().splitlines()[-1] == "--json bring apply card-sda2 --gcodes"


def test_a_printer_typed_in_is_added_and_planned(rig):
    server, comp, asked = rig
    with pytest.raises(Exception, match="Which address"):
        act(comp, "bring_address", address="  ")
    act(comp, "bring_address", address="studio.local")
    got = settle(comp, lambda b: b["state"] == "idle" and b["plan"])
    assert [s["id"] for s in got["sources"]] == ["printer-studio-local"] and got["plan"]["id"] == "printer-studio-local"
    assert "--json bring address studio.local" in asked.read_text()


def test_a_failed_bring_says_why_and_one_that_just_stops_too(rig, tmp_path):
    server, comp, _ = rig
    act(comp, "bring_scan")
    settle(comp, lambda b: b["state"] == "idle")
    installer(Path(comp.cli), apply_ends="failed")
    act(comp, "bring_apply", id="card-sda2")
    got = settle(comp, lambda b: b["state"] == "failed")
    assert got["why"] == "Moonraker didn't take its history. Nothing was changed." and got["result"] is None
    installer(Path(comp.cli), apply_ends="nothing")
    act(comp, "bring_apply", id="card-sda2")
    assert settle(comp, lambda b: b["state"] == "failed")["why"] == "It stopped without saying why."


def test_not_while_printing(rig):
    server, comp, _ = rig
    act(comp, "bring_scan")
    settle(comp, lambda b: b["state"] == "idle")
    comp.tracker.status["print_stats"] = {"state": "printing"}
    with pytest.raises(Exception, match="It's printing"):
        act(comp, "bring_apply", id="card-sda2")


def test_a_bring_carries_on_across_a_moonraker_restart(rig):
    server, comp, _ = rig
    folder = Path(comp._bring_folder())
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bring-run.jsonl").write_text(
        json.dumps({"started": "apply", "pid": os.getpid()}) + "\n"     # still running: this test's own process
        + json.dumps({"progress": {"step": "Bringing history and settings", "done": 4, "of": 5}}) + "\n")
    again = type(comp)(FakeConfig(server))                               # Moonraker restarted (the restore does)
    again.installer_state, again.cli = comp.installer_state, comp.cli
    run(again.component_init())
    v = again._bring_view()
    assert v["state"] == "bringing" and v["progress"]["done"] == 4
    with open(folder / "bring-run.jsonl", "a") as f:
        f.write(json.dumps({"result": {"klipper": "error", "message": "Section 'ace' is not a valid config section"}}) + "\n")
    again._bring_tick()
    assert again._bring_view()["state"] == "done" and again._bring_view()["result"]["klipper"] == "error"


class ExportDatabase:
    """Moonraker's database component, as much as the export uses."""
    def __init__(self, folder):
        self.folder = folder

    def get_backup_dir(self):
        return self.folder

    async def backup_database(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
        con.execute("CREATE TABLE namespace_store (namespace TEXT, key TEXT, value record)")
        con.execute("CREATE TABLE authorized_users (username TEXT, password TEXT)")
        con.executemany("INSERT INTO namespace_store VALUES (?,?,?)",
                        [("mainsail", "general", b"{}"), ("elyir-bench", "phones", b"q\x01"), ("elyir-bench", "spool", b"{}")])
        con.execute("INSERT INTO authorized_users VALUES ('_API_KEY_USER_', 'the-key')")
        con.commit()
        con.close()


def test_the_export_sends_the_database_without_its_logins(rig, tmp_path):
    server, comp, _ = rig
    server.components["database"] = ExportDatabase(tmp_path / "backup" / "database")
    got = run(comp._handle_bring_export(FakeWebRequest()))
    data = base64.b64decode(got["database"])
    assert got["bytes"] == len(data) and b"the-key" not in data
    db = tmp_path / "got.db"
    db.write_bytes(data)
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM authorized_users").fetchone()[0] == 0
    assert sorted(con.execute("SELECT namespace, key FROM namespace_store")) == [("elyir-bench", "spool"), ("mainsail", "general")]
    con.close()
    assert not list((tmp_path / "backup" / "database").iterdir())       # the copy is gone
