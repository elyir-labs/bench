"""A Kobra new to the Wi-Fi joins the bench by itself (design/new-kobra/, B): no tap, its door follows its siblings',
the phones that have its siblings are carried to it, a carried sibling vouches for its name, and Not mine is remembered."""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench_service as B  # noqa: E402
import doors as D  # noqa: E402
import standin as S  # noqa: E402
from test_doors import FakeProc  # noqa: E402

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}


def phone(pid, name, token, push=None, **kw):
    return {"id": pid, "name": name, "token": token, "joined": 1, "last_seen": 1, "push": push, **kw}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def free_ports(n):
    out, socks = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        out.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return out


def relay(carried=("p-sibling",)):
    seen = {"claims": [], "vouches": []}
    carried = set(carried)

    async def claim(request):
        body = await request.json()
        seen["claims"].append(body)
        return web.json_response({"name": body["name"], "address": f"{body['name']}.elyir.app", "secret": f"secret-{body['name']}",
                                  "relay": {"addr": "relay.elyir.app", "token": "t"}, "carried": False}, status=201)

    async def house(request):
        return web.json_response({"carried": request.match_info["name"] in carried})

    async def vouch(request):
        body = await request.json()
        seen["vouches"].append((request.match_info["name"], body, request.headers.get("Authorization")))
        if body["by"] not in carried:
            return web.json_response({"detail": {"why": "vouch", "message": "not carried"}}, status=403)
        carried.add(request.match_info["name"])
        return web.json_response({"carried": True})
    app = web.Application()
    app.router.add_post("/houses", claim)
    app.router.add_get("/houses/{name}", house)
    app.router.add_post("/houses/{name}/vouch", vouch)
    return app, seen


async def rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, kobras, remote="off"):
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    app, seen = relay()
    r = await aiohttp_server(app)
    started = []

    async def spawn(*argv, **kw):
        started.append(list(argv))
        return FakeProc(list(argv))
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("")
        os.chmod(bins / n, 0o755)
    (tmp_path / "door.py").write_text("")
    old_port, new_port = free_ports(2)
    monkeypatch.setattr(B, "STANDIN_PORTS", range(new_port, new_port + 1))
    state = tmp_path / "bench"
    doors = D.Doors(state, api=str(r.make_url("")), bin_dir=bins, python="python3", door_py=tmp_path / "door.py", spawn=spawn)
    doors.bench_url = "http://127.0.0.1:8096"
    doors.relay("anycubic-old").save({"name": "p-sibling", "address": "p-sibling.elyir.app", "secret": "secret-p-sibling",
                                      "addr": "a", "token": "t"})
    write(state / "standins" / "anycubic-old" / "door" / "phones.json", [
        phone("a1", "Phone A", "hash-a-old", push={"subscription": SUB, "kinds": None, "vapid": {"publicKey": "P", "privateKey": "K"}}),
        phone("g1", "A guest", "hash-g", kind="guest", reach="watch"),
        phone("b1", "Bench Box", "hash-b", kind="bench", origins=[]),
        phone("h1", "House hub", "hash-h"),
    ])
    write(state / "standins" / "anycubic-other" / "door" / "phones.json", [
        phone("a2", "Phone A on the other", "hash-a-other", push={"subscription": SUB, "kinds": None}),
    ])

    async def finder():
        return kobras
    bench = B.Bench(state, "Bench Box", [], scanner=lambda: [], finder=finder, standin_host="127.0.0.1", doors=doors, remote=remote)
    bench.printers = {
        "anycubic-old": {"name": "Kobra 3", "host": "127.0.0.1", "port": old_port, "moonraker_port": old_port, "home": None,
                         "token": None, "remote": True, "standin": {"printer": "127.0.0.8", "moonraker_port": 1}},
        # a sibling the box speaks for that isn't running right now still lends its phones
        "anycubic-other": {"name": "Kobra 3 Max", "host": "127.0.0.1", "port": 1, "moonraker_port": 1, "home": None,
                           "token": None, "remote": False, "standin": {"printer": "127.0.0.7", "moonraker_port": 1}},
    }
    client = await aiohttp_client(bench.app())
    return bench, client, seen, started


NEW = {"id": "anycubic-e9e9e9", "name": "Kobra 3", "host": "127.0.0.9", "model": "kobra-3", "rinkhals": True, "via": "moonraker",
       "why": None}


async def opened(bench, pid):
    for _ in range(200):
        if bench.doors.house(pid) and bench.printers.get(pid, {}).get("carried") is not None:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{pid}'s door never opened")


async def test_a_new_kobra_joins_by_itself_with_its_door_its_phones_and_its_name_vouched_for(tmp_path, aiohttp_server,
                                                                                         aiohttp_client, monkeypatch):
    bench, client, seen, started = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [NEW])
    await bench._join_new()
    pid = NEW["id"]
    p = bench.printers[pid]
    assert p["joined_by"] == "itself" and p["name"] == "Kobra 3 #2"
    assert p["remote"] is True, "a door like its siblings', though the box's own setting is off"
    await opened(bench, pid)
    name = B.public_name(pid)
    assert seen["claims"][-1]["name"] == name
    door = [a for a in started if "--printer-id" in a and name in a][-1]
    assert door[door.index("--not-mine-url") + 1] == f"http://127.0.0.1:8096/bench/printers/{pid}/not-mine"

    carried = json.loads((tmp_path / "bench" / "standins" / pid / "door" / "phones.json").read_text())
    assert [c["name"] for c in carried] == ["Phone A", "House hub"], "no guests, no box"
    a = carried[0]
    assert a["token"] == "hash-a-old" and a["also"] == ["hash-a-other"], "one record for one phone, every token it holds"
    assert a["carried_from"] == ["anycubic-old", "anycubic-other"] and a["push"]["vapid"]["privateKey"] == "K"

    joined = json.loads((tmp_path / "bench" / "standins" / "anycubic-old" / "door" / "joined.json").read_text())
    assert joined == [{"box_id": pid, "id": name, "name": "Kobra 3 #2", "phones": ["a1", "h1"], "at": p["joined"],
                       "addresses": {"away": f"https://{name}.elyir.app", "home": None}}]
    other = json.loads((tmp_path / "bench" / "standins" / "anycubic-other" / "door" / "joined.json").read_text())
    assert other[0]["phones"] == ["a2"]

    assert seen["vouches"] == [(name, {"by": "p-sibling", "secret": "secret-p-sibling"}, f"Bearer secret-{name}")]
    assert bench.doors.link(pid) == "on"

    found = {f["id"]: f for f in await (await client.get("/bench/found")).json()}
    assert found[pid]["on"] and found[pid]["new"] and not found[pid]["hidden"]


async def test_not_mine_takes_it_off_and_it_never_joins_again_until_brought_back(tmp_path, aiohttp_server, aiohttp_client,
                                                                                monkeypatch):
    bench, client, _, _ = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [NEW])
    pid = NEW["id"]
    await bench._join_new()
    await opened(bench, pid)
    r = await client.post(f"/bench/printers/{pid}/not-mine", json={"phone": "Phone A"})
    assert r.status == 202
    assert pid not in bench.printers and bench.hidden == [pid]
    assert json.loads((tmp_path / "bench" / "standins" / "anycubic-old" / "door" / "joined.json").read_text()) == []
    await asyncio.sleep(1.2)
    assert pid not in bench.standins and bench.doors.house(pid) is None
    left = tmp_path / "bench" / "standins" / "anycubic-old" / "door" / "left.json"
    assert json.loads(left.read_text()) == [bench.doors.relay(pid).load()["name"]], "phones drop the record they picked up"

    await bench._join_new()
    assert pid not in bench.printers
    found = {f["id"]: f for f in await (await client.get("/bench/found")).json()}
    assert found[pid]["hidden"] and not found[pid]["on"]
    assert json.loads((tmp_path / "bench" / "hidden.json").read_text()) == [pid]

    assert (await client.delete(f"/bench/hidden/{pid}")).status == 200
    assert json.loads(left.read_text()) == []
    await bench._join_new()
    assert bench.printers[pid]["joined_by"] == "itself"


async def test_a_kobra_on_its_cloud_waits_and_add_from_setup_brings_a_hidden_one_back(tmp_path, aiohttp_server,
                                                                                      aiohttp_client, monkeypatch):
    cloud = {**NEW, "id": "anycubic-c1c1c1", "rinkhals": False, "via": None, "why": "On Anycubic's cloud: turn on LAN mode"}
    bench, client, _, _ = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [cloud, NEW])
    bench.hidden = [NEW["id"]]
    await bench._join_new()
    assert cloud["id"] not in bench.printers and NEW["id"] not in bench.printers
    assert (await client.post(f"/bench/add/{NEW['id']}")).status == 201
    assert bench.printers[NEW["id"]]["joined_by"] == "setup" and bench.hidden == []


async def test_turning_a_door_on_by_hand_asks_for_the_same_random_name(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    bench, client, seen, _ = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [NEW])
    assert (await client.post(f"/bench/add/{NEW['id']}")).status == 201
    await opened(bench, NEW["id"])
    assert (await client.delete(f"/bench/p/{NEW['id']}/remote")).status == 200
    (tmp_path / "bench" / "standins" / NEW["id"] / "relay.json").unlink()
    assert (await client.post(f"/bench/p/{NEW['id']}/remote", json={})).status in (200, 202)
    assert seen["claims"][-1]["name"] == B.public_name(NEW["id"]) != "kobra-3-2"


def test_a_phone_already_paired_with_the_new_kobra_gets_the_siblings_tokens_not_a_second_record(tmp_path):
    state = tmp_path / "bench"
    write(state / "standins" / "new" / "door" / "phones.json", [phone("own1", "Phone A", "hash-a-new", push={"subscription": SUB})])
    write(state / "standins" / "old" / "door" / "phones.json", [
        phone("a1", "Phone A", "hash-a-old", push={"subscription": SUB}), phone("b1", "Phone B", "hash-b")])
    bench = B.Bench(state, "Bench Box", [], scanner=lambda: [])
    bench.printers = {"new": {"name": "Kobra 3 #2", "standin": {"printer": "10.0.0.2"}}, "old": {"name": "Kobra 3", "standin": {"printer": "10.0.0.1"}}}
    bench._carry_phones("new")
    got = json.loads((state / "standins" / "new" / "door" / "phones.json").read_text())
    assert [(g["name"], g["token"], g.get("also")) for g in got] == [("Phone A", "hash-a-new", ["hash-a-old"]), ("Phone B", "hash-b", [])]
    assert bench.printers["new"]["carried"] == {"old": ["a1", "b1"]}


async def test_a_kobra_on_the_bench_is_joined_to_the_box_slicer_so_its_own_page_can_slice(tmp_path, aiohttp_server,
                                                                                          aiohttp_client, monkeypatch):
    bench, _, _, _ = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [NEW])
    asked = []

    async def join(pid, fresh=False):
        asked.append(pid)
        return {"at": 0, "entry": {}}
    monkeypatch.setattr(bench.shelf, "_join", join)
    bench.printers["obi-like"] = {"name": "A Voron", "host": "127.0.0.1", "port": 1, "moonraker_port": 1, "home": None, "token": None}
    await bench._join_new()
    await asyncio.sleep(0)
    assert asked == [NEW["id"]], "joined as it's added"
    asked.clear()
    await bench._join_slicer()
    assert sorted(asked) == sorted(["anycubic-old", "anycubic-other", NEW["id"]]), "a printer with its own slicer isn't joined here"


async def test_a_kobra_already_on_the_bench_never_joins_again_under_its_address(tmp_path, aiohttp_server, aiohttp_client,
                                                                                monkeypatch):
    # the scan missed the MACs once: the Kobras already here came back named by address, at the addresses they have
    again = {**NEW, "id": "anycubic-127-0-0-8", "host": "127.0.0.8"}
    unknown = {**NEW, "id": "anycubic-127-0-0-9", "host": "127.0.0.9"}
    bench, _, _, _ = await rig(tmp_path, aiohttp_server, aiohttp_client, monkeypatch, [again, unknown])
    await bench._join_new()
    assert set(bench.printers) == {"anycubic-old", "anycubic-other"}, "neither by itself: one is here, one has no MAC"
