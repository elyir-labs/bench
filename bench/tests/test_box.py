"""The box itself on its own Care (design/power/, A; design/role/'s way back): turn it off or restart it, and make it a
printer again, its run followed from a file. Dry, as in the simulator rig: nothing is turned off or switched."""
import asyncio
import json
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from box import Box, parse_key, role_state, update_state  # noqa: E402

P = lambda step, done: json.dumps({"progress": {"step": step, "done": done, "of": 3}})


def test_the_run_says_its_step_then_fails_or_ends():
    started = json.dumps({"started": "role", "pid": 1})
    assert role_state([started, P("The printer app", 1)], alive=True) == \
        {"state": "switching", "progress": {"step": "The printer app", "done": 1, "of": 3}, "why": None}
    assert role_state([started, P("The printer app", 1), json.dumps({"failed": "the printer app didn't come up"})], alive=False)["why"] == \
        "the printer app didn't come up"
    assert role_state([started, json.dumps({"result": {"role": "printer"}})], alive=False) is None
    assert role_state([started, P("Its screen", 2)], alive=False)["state"] == "failed"   # gone without a word
    assert role_state([], alive=False) is None


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_dry_it_only_says_so(tmp_path):
    async def go():
        app = web.Application()
        Box(tmp_path, tmp_path / "elyir_bench.py", dry=True).add_routes(app)
        async with TestClient(TestServer(app)) as c:
            got = await (await c.get("/bench/box")).json()
            assert (got["power"], got["role"], got["os"], got["ssh"]["keys"]) == (True, None, None, [])   # os: not a card
            r = await (await c.post("/bench/box/power", json={"kind": "restart"})).json()
            assert r == {"ok": True, "kind": "restart", "dry": True}
            r = await (await c.post("/bench/box/role")).json()
            assert r["role"]["state"] == "switching" and r["role"]["progress"]["step"] == "Klipper and Moonraker on"
            assert (await c.post("/bench/box/role")).status == 409          # once at a time
    run(go())


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDncxwALco9tpc9Dr3opbhL8C7xcngsyuMbEajsEMh58 laptop"


def test_a_public_key_is_one_line_whose_blob_names_its_own_kind():
    k = parse_key(KEY + "\r")
    assert (k["kind"], k["name"], len(k["id"])) == ("ssh-ed25519", "laptop", 12)
    assert parse_key(KEY.replace("ssh-ed25519", "ssh-rsa", 1)) is None             # the blob says ed25519
    assert parse_key("ssh-ed25519 not-base64!") is None
    assert parse_key('command="x" ' + KEY) is None and parse_key("# a comment") is None   # left in the file as they are
    assert parse_key("-----BEGIN OPENSSH PRIVATE KEY-----") is None


def test_keys_are_added_once_listed_and_taken_off_and_other_lines_stay(tmp_path):
    async def go():
        keys = tmp_path / "ssh" / "authorized_keys"
        keys.parent.mkdir()
        keys.write_text('command="backup" ssh-ed25519 AAAA other\n')
        app = web.Application()
        Box(tmp_path, tmp_path / "elyir_bench.py", dry=True, keys=keys).add_routes(app)
        async with TestClient(TestServer(app)) as c:
            assert (await c.post("/bench/box/ssh", json={"key": "my private key"})).status == 400
            assert (await (await c.post("/bench/box/ssh", json={"key": KEY + "\n"})).json())["added"] == 1
            assert (await (await c.post("/bench/box/ssh", json={"key": KEY})).json())["added"] == 0     # once
            listed = (await (await c.get("/bench/box")).json())["ssh"]["keys"]
            assert [(k["kind"], k["name"]) for k in listed] == [("ssh-ed25519", "laptop")]
            assert keys.stat().st_mode & 0o077 == 0 and keys.read_text().endswith(KEY + "\n")
            assert (await c.delete(f"/bench/box/ssh/{listed[0]['id']}")).status == 200
            assert keys.read_text() == 'command="backup" ssh-ed25519 AAAA other\n'
            assert (await c.delete(f"/bench/box/ssh/{listed[0]['id']}")).status == 404
    run(go())


def test_an_update_from_care_says_its_last_line_or_why_it_failed():
    assert update_state(["release 2026.10.22-abc is out", "downloading it (875 MB) …", ""], None) == \
        {"state": "updating", "line": "downloading it (875 MB) …"}
    assert update_state(["elyir-bench-os: can't read the feed (URLError)"], 1) == \
        {"state": "failed", "why": "can't read the feed (URLError)"}
    assert update_state([], 2)["why"] == "It stopped without saying why."
    assert update_state(["up to date: slot A runs 2026.10.22-abc"], 0) is None


def test_on_a_card_it_says_its_os_and_updates_once_at_a_time(tmp_path):
    async def go():
        ver = tmp_path / "os-version"; ver.write_text("2026.10.21-4863fd1\n")
        app = web.Application()
        box = Box(tmp_path, tmp_path / "elyir_bench.py", dry=True, os_version=ver)
        box.add_routes(app)
        async with TestClient(TestServer(app)) as c:
            assert (await (await c.get("/bench/box")).json())["os"] == {"version": "2026.10.21-4863fd1", "latest": None, "update": None}
            r = await (await c.post("/bench/box/update")).json()
            assert r["ok"] and r["dry"]
            box.updater.wait()
            assert (await (await c.get("/bench/box")).json())["os"]["update"] is None      # `true`: done, nothing said
    run(go())
