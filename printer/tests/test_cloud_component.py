"""Bench Cloud, the component's side (docs/cloud.md): a new card asking the owner for its backup (bring_cloud_*, asked
again by itself while it waits), and the nightly backup started for a printer in a house. Against the stand-in
Moonraker of test_component.py and a stand-in `elyir-bench`."""

import json
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bring_component import NO_CONFIG, act, settle  # noqa: E402
from test_component import KlippyState, load, run  # noqa: E402

CLOUD = {"id": "cloud-p-workshop", "name": "Workshop", "owner_phone": "Alex's iPhone", "owner_email": "a•••x@example.net",
         "emailed": None}
SOURCE = {"id": "cloud-p-workshop", "kind": "cloud", "name": "Workshop", "detail": "Your Bench Cloud backup", "when": 1791700000}
FILE = {"id": "file-workshop-bench-cloud-tar-gz", "kind": "file", "name": "Workshop", "detail": "A backup file"}


def installer(path: Path) -> Path:
    """`elyir-bench --json bring cloud-*` and `elyir-bench --json cloud backup`: the owner says yes once `allowed` exists."""
    asked, allowed = path.parent / "asked", path.parent / "allowed"
    waiting = json.dumps({"cloud": dict(CLOUD, state="waiting")})
    done = json.dumps({"sources": [SOURCE, FILE], "found": [], "cloud": dict(CLOUD, state="allowed", file=FILE["id"])})
    path.write_text("#!/bin/sh\n"
                    f"echo \"$@\" >> {asked}\n"
                    "echo \"{\\\"started\\\": \\\"$3\\\", \\\"pid\\\": $$}\"\n"
                    "case \"$3\" in\n"
                    f"  scan) echo {shlex.quote(json.dumps({'sources': [SOURCE], 'found': []}))} ;;\n"
                    f"  cloud-ask|cloud-email) echo {shlex.quote(waiting)} ;;\n"
                    f"  cloud-check|cloud-code) if [ -e {allowed} ]; then echo {shlex.quote(done)}; "
                    f"else echo {shlex.quote(waiting)}; fi ;;\n"
                    "esac\n")
    path.chmod(0o755)
    return asked


@pytest.fixture
def rig(tmp_path, monkeypatch):
    server, comp = load(tmp_path, monkeypatch)
    comp.installer_state = str(tmp_path / "elyir-bench" / "state.json")
    comp.cli = str(tmp_path / "elyir-bench-cli")
    asked = installer(Path(comp.cli))
    server.kc.state, server.kc.state_message = KlippyState.ERROR, NO_CONFIG
    run(comp.component_init())
    act(comp, "bring_scan")
    settle(comp, lambda b: b["state"] == "idle" and b["sources"])
    return server, comp, asked, tmp_path


def lines(asked):
    return asked.read_text().splitlines() if asked.exists() else []


def test_a_new_card_asks_the_owner_and_keeps_asking_until_allowed(rig):
    server, comp, asked, tmp = rig
    act(comp, "bring_cloud_ask", id="cloud-p-workshop")
    got = settle(comp, lambda b: (b["cloud"] or {}).get("state") == "waiting")
    assert got["cloud"]["owner_phone"] == "Alex's iPhone"
    assert "--json bring cloud-ask cloud-p-workshop" in lines(asked)
    settle(comp, lambda b: any("cloud-check" in l for l in lines(asked)))
    (tmp / "allowed").touch()
    got = settle(comp, lambda b: (b["cloud"] or {}).get("state") == "allowed")
    assert got["cloud"]["file"] == FILE["id"] and FILE in got["sources"]
    n = len(lines(asked))
    comp._bring_tick()
    time.sleep(0.1)
    comp._bring_tick()
    assert len(lines(asked)) == n


def test_the_email_code_is_six_digits(rig):
    server, comp, asked, tmp = rig
    act(comp, "bring_cloud_ask", id="cloud-p-workshop")
    settle(comp, lambda b: (b["cloud"] or {}).get("state") == "waiting")
    with pytest.raises(Exception, match="six digits"):
        act(comp, "bring_cloud_code", code="123")
    (tmp / "allowed").touch()
    act(comp, "bring_cloud_code", code="482 913")
    settle(comp, lambda b: (b["cloud"] or {}).get("state") == "allowed")
    assert "--json bring cloud-code 482913" in lines(asked)


def test_the_nightly_backup_starts_for_a_printer_in_a_house(rig, monkeypatch):
    server, comp, asked, tmp = rig
    folder = Path(comp._bring_folder())
    folder.mkdir(parents=True, exist_ok=True)
    comp._cloud_tick()
    time.sleep(0.2)
    assert not any("cloud backup" in l for l in lines(asked))
    (folder / "cloud.json").write_text('{"token": "d_x"}')
    (folder / "cloud-last.json").write_text(json.dumps({"at": time.time() - 3600}))
    comp._cloud_tick()
    time.sleep(0.2)
    assert not any("cloud backup" in l for l in lines(asked))
    (folder / "cloud-last.json").write_text(json.dumps({"at": time.time() - 3 * 86400}))
    comp._cloud_tick()
    time.sleep(0.3)
    assert lines(asked).count("--json cloud backup") == 1
    comp._cloud_tick()
    time.sleep(0.2)
    assert lines(asked).count("--json cloud backup") == 1


class Said:
    def __init__(self):
        self.posts = []

    def has_error(self):
        return False

    @property
    def status_code(self):
        return 200


def test_a_printer_in_a_house_says_what_its_doing_every_few_minutes(rig, monkeypatch):
    server, comp, asked, tmp = rig
    posts = []

    class Http:
        async def post(self, url, body="", headers=None, **kw):
            posts.append((url, body, headers))
            return Said()

    server.components["http_client"] = Http()
    pending = []
    monkeypatch.setattr(comp.eventloop, "create_task", lambda coro: pending.append(coro))

    def drain():
        while pending:
            run(pending.pop(0))

    folder = Path(comp._bring_folder())
    folder.mkdir(parents=True, exist_ok=True)
    comp._cloud_say_tick()
    assert posts == []
    (folder / "cloud.json").write_text('{"api": "https://cloud.example", "token": "d_workshop"}')
    (folder / "relay.json").write_text('{"address": "workshop.elyir.app", "secret": "never sent"}')
    comp._cloud_me = None
    clock = [1_800_000_000.0]
    monkeypatch.setattr("time.time", lambda: clock[0])
    comp._cloud_say_tick()
    drain()
    url, body, headers = posts[-1]
    assert url == "https://cloud.example/v1/status" and headers == {"Authorization": "Bearer d_workshop"}
    assert body["address"] == "workshop.elyir.app" and "secret" not in json.dumps(body)
    assert set(body) == {"state", "phase", "headline", "detail", "job", "progress", "done_at", "address"}
    clock[0] += 60
    comp._cloud_say_tick()
    drain()
    assert len(posts) == 1                         # nothing new, and five minutes haven't passed
    clock[0] += 300
    comp._cloud_say_tick()
    drain()
    assert len(posts) == 2
