"""A door for each Kobra the box speaks for (bench/doors.py): claiming its name on a fake relay, the tunnel's and
Caddy's files, the processes it starts, and pairing through the stand-in's /door/."""
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import doors as D  # noqa: E402


def fake_relay(taken=("kobra-3-max",), suggest="kobra-3-max-2", invites=("K7QX-M2PD-9HTF",), reserved=("bench", "bench-box")):
    seen = {"claims": [], "invites": []}

    async def claim(request):
        body = await request.json()
        seen["claims"].append(body)
        if body.get("invite") and body["invite"] not in invites:
            return web.json_response({"detail": {"message": "that code was used already"}}, status=403)
        if body["name"] in reserved:
            return web.json_response({"detail": "That one is kept for the service itself."}, status=422)
        if body["name"] in taken:
            return web.json_response({"detail": {"suggestions": [suggest]}}, status=409)
        return web.json_response({"name": body["name"], "address": f"{body['name']}.elyir.app", "secret": "s3cret",
                                  "relay": {"addr": "relay.elyir.app", "token": "t0k"}, "carried": bool(body.get("invite"))},
                                 status=201)

    async def house(request):
        assert request.headers.get("Authorization") == "Bearer s3cret"
        return web.json_response({"carried": True})

    async def invite(request):
        seen["invites"].append(await request.json())
        return web.json_response({"carried": True})
    app = web.Application()
    app.router.add_post("/houses", claim)
    app.router.add_get("/houses/{name}", house)
    app.router.add_post("/houses/{name}/invite", invite)
    return app, seen


async def test_a_kobra_claims_its_name_the_relays_suggestion_when_taken(tmp_path, aiohttp_server):
    app, seen = fake_relay()
    relay = await aiohttp_server(app)
    r = D.Relay(tmp_path / "k" / "relay.json", str(relay.make_url("")))
    async with ClientSession() as s:
        ok, words = await r.claim(s, "kobra-3-max", None, "ab12")
        assert ok and "kobra-3-max-2.elyir.app" in words and "approves" in words
        assert [c["name"] for c in seen["claims"]] == ["kobra-3-max", "kobra-3-max-2"]
        kept = json.loads((tmp_path / "k" / "relay.json").read_text())
        assert kept["secret"] == "s3cret" and stat.S_IMODE(os.stat(tmp_path / "k" / "relay.json").st_mode) == 0o600
        assert await r.carried(s) is True
        # an invite code brought later goes to the name it holds
        ok, words = await r.claim(s, "kobra-3-max", "K7QX-M2PD-9HTF", "ab12")
        assert ok and "invite code used" in words and seen["invites"] == [{"code": "K7QX-M2PD-9HTF"}]


async def test_a_name_the_relay_keeps_for_itself_becomes_this_boxs_own(tmp_path, aiohttp_server):
    app, seen = fake_relay(taken=())
    relay = await aiohttp_server(app)
    async with ClientSession() as s:
        ok, words = await D.Relay(tmp_path / "relay.json", str(relay.make_url(""))).claim(s, "bench-box", None, "ab12")
    assert ok and "bench-box-ab12.elyir.app" in words
    assert [c["name"] for c in seen["claims"]] == ["bench-box", "bench-box-ab12"]


async def test_a_bad_invite_code_never_costs_the_name(tmp_path, aiohttp_server):
    app, seen = fake_relay(taken=())
    relay = await aiohttp_server(app)
    async with ClientSession() as s:
        ok, words = await D.Relay(tmp_path / "relay.json", str(relay.make_url(""))).claim(s, "kobra-3", "AAAA-BBBB-CCCC", "ab12")
    assert ok and [c.get("invite") for c in seen["claims"]] == ["AAAA-BBBB-CCCC", None]


def test_the_tunnel_and_caddy_are_the_installers_aimed_at_the_kobras_caddy(tmp_path):
    frpc = D.render_frpc({"name": "kobra-3-max", "address": "kobra-3-max.elyir.app", "secret": "s3cret",
                          "addr": "relay.elyir.app", "token": "t0k"})
    assert 'customDomains = ["kobra-3-max.elyir.app"]' in frpc and "localPort = 9444" in frpc
    assert 'metadatas.secret = "s3cret"' in frpc and "plugin" not in frpc.replace("`plugin`", "")
    caddy = D.render_caddyfile([("kobra-3.elyir.app", 8204), ("kobra-3-max.elyir.app", 8200)], tmp_path / "caddy")
    assert caddy.index("kobra-3-max.elyir.app:9444") < caddy.index("kobra-3.elyir.app:9444")
    assert "reverse_proxy 127.0.0.1:8200" in caddy and "reverse_proxy 127.0.0.1:8204" in caddy
    assert "alt_tlsalpn_port 9444" in caddy and "allow 127.0.0.1/32" in caddy
    assert D.slug("Kobra 3 Max #2") == "kobra-3-max-2" and D.invite_code("k7qx m2pd 9htf") == "K7QX-M2PD-9HTF"
    assert D.Doors.ports(8101) == (8200, 8201, 8202) and D.Doors.ports(8103) == (8208, 8209, 8210)


class FakeProc:
    def __init__(self, argv):
        self.argv, self.returncode = argv, None
        self._done = asyncio.Event()

    async def wait(self):
        await self._done.wait()
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._done.set()

    kill = terminate


async def test_a_door_its_tunnel_and_caddy_start_for_a_kobra_with_a_name(tmp_path):
    started = []

    async def spawn(*argv, **kw):
        p = FakeProc(list(argv))
        started.append(p)
        return p
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("#!/bin/sh\n")
        os.chmod(bins / n, 0o755)
    door_py = tmp_path / "door.py"
    door_py.write_text("")
    doors = D.Doors(tmp_path / "bench", bin_dir=bins, python="python3", door_py=door_py, spawn=spawn)
    printer = {"name": "Kobra 3 Max", "port": 8101}
    assert await doors.start("k", printer) == "no public name yet"
    doors.relay("k").save({"name": "kobra-3-max", "address": "kobra-3-max.elyir.app", "secret": "s", "addr": "a", "token": "t"})
    assert await doors.start("k", printer) is None
    await asyncio.sleep(0.05)
    argv = {p.argv[0].split("/")[-1].split("-")[0]: p.argv for p in started}
    door = argv["python3"]
    assert door[door.index("--moonraker") + 1] == "http://127.0.0.1:8101" and door[door.index("--away-port") + 1] == "8200"
    assert door[door.index("--address") + 1] == "kobra-3-max.elyir.app" and door[door.index("--printer-id") + 1] == "kobra-3-max"
    assert "frpc" in argv and "caddy" in argv and doors.house("k") == 8202
    assert stat.S_IMODE(os.stat(tmp_path / "bench" / "standins" / "k" / "frpc.toml").st_mode) == 0o600
    await doors.stop("k")
    assert doors.house("k") is None and all(p.returncode == 0 for p in started)
    await doors.close()


async def test_pairing_on_the_box_reaches_the_kobras_door_through_its_stand_in(tmp_path, aiohttp_server, aiohttp_client):
    import standin as S
    house = web.Application()

    async def pair_new(request):
        return web.json_response({"code": "ABCD2345", "url": "https://kobra-3-max.elyir.app/pair#ABCD2345"})
    house.router.add_post("/door/pair/new", pair_new)
    h = await aiohttp_server(house)
    s = S.Standin("k", "Kobra 3 Max", "127.0.0.9", 1, 1, origins=lambda: ["http://bench.local:8088"])
    await s.start()
    client = await aiohttp_client(s.app())
    assert (await client.post("/door/pair/new")).status == 404          # no door: none here
    s.door_house = lambda: h.port
    r = await client.post("/door/pair/new")
    assert r.status == 200 and (await r.json())["code"] == "ABCD2345"
    assert (await (await client.get("/door/frames")).json())["frames"] == ["http://bench.local:8088"]
    await s.stop()


def test_its_name_at_home_spells_the_boxs_address_and_caddy_serves_it(tmp_path):
    relay = {"name": "kobra-3-max", "address": "kobra-3-max.elyir.app", "secret": "s"}
    assert D.home_name(relay, "192.0.2.40") == "192-0-2-40.kobra-3-max.home.elyir.app"
    assert D.home_name(relay, "8.8.8.8") is None and D.home_name({}, "192.0.2.40") is None
    caddy = D.render_caddyfile([("kobra-3-max.elyir.app", 8200)], tmp_path / "c",
                               homes=[("192-0-2-40.kobra-3-max.home.elyir.app", tmp_path / "cert", 8201)])
    assert "192-0-2-40.kobra-3-max.home.elyir.app:443 {" in caddy and "reverse_proxy 127.0.0.1:8201" in caddy
    assert f"tls {tmp_path / 'cert'}/cert.pem" in caddy


async def test_its_name_at_home_is_got_through_the_relay_and_the_door_reads_it(tmp_path):
    calls = []

    async def spawn(*argv, **kw):
        calls.append((list(argv), kw.get("env") or {}))
        if argv[0].endswith("lego-4.26.0"):          # a stand-in lego: writes the certificate where lego would
            root = Path(argv[argv.index("--path") + 1]) / "certificates"
            name = argv[argv.index("--domains") + 1]
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{name}.crt").write_text("CERT")
            (root / f"{name}.key").write_text("KEY")

            class Done:
                async def communicate(self):
                    return b"ok", b""
            return Done()
        return FakeProc(list(argv))
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0", "lego-4.26.0"):
        (bins / n).write_text("")
        os.chmod(bins / n, 0o755)
    door_py = tmp_path / "door.py"
    door_py.write_text("")
    doors = D.Doors(tmp_path / "bench", api="https://api.example", bin_dir=bins, python="python3", door_py=door_py,
                    spawn=spawn, home_port=443, ip=lambda: "192.0.2.40")
    doors.relay("k").save({"name": "kobra-3-max", "address": "kobra-3-max.elyir.app", "secret": "s3", "addr": "a", "token": "t"})
    assert await doors.start("k", {"name": "Kobra 3 Max", "port": 8101}) is None
    assert await doors.homecert("k") is None
    lego, env = next(c for c in calls if c[0][0].endswith("lego-4.26.0"))
    assert env["HTTPREQ_ENDPOINT"] == "https://api.example/acme" and env["HTTPREQ_USERNAME"] == "kobra-3-max"
    assert env["HTTPREQ_PASSWORD"] == "s3" and lego[-1] == "run"
    home = json.loads((tmp_path / "bench" / "standins" / "k" / "home.json").read_text())["name"]
    assert home == "192-0-2-40.kobra-3-max.home.elyir.app" == doors.home_of("k")
    # the door finds it beside its own state, as a printer's door does (Door.home_file = state.parent / "home.json")
    assert (tmp_path / "bench" / "standins" / "k" / "door").parent / "home.json" == tmp_path / "bench" / "standins" / "k" / "home.json"
    assert f"{home}:443" in (tmp_path / "bench" / "doors" / "Caddyfile").read_text()
    await doors.close()


async def test_the_secure_link_follows_the_relay(tmp_path, aiohttp_server):
    app, _ = fake_relay(taken=())
    relay = await aiohttp_server(app)
    doors = D.Doors(tmp_path / "bench", api=str(relay.make_url("")))
    assert doors.link("k") == "off"
    ok, _ = await doors.claim("k", "Kobra 3", None)
    assert ok and doors.link("k") == "waiting"
    assert await doors.look("k") == "on"           # the fake relay carries every claimed name
    await doors.close()


async def test_a_kobra_added_with_remote_on_opens_its_door_by_itself(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    import bench_service as B
    import standin as S
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    app, seen = fake_relay(taken=())
    relay = await aiohttp_server(app)
    started = []

    async def spawn(*argv, **kw):
        started.append(list(argv))
        return FakeProc(list(argv))
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("")
        os.chmod(bins / n, 0o755)
    door_py = tmp_path / "door.py"
    door_py.write_text("")
    import socket as so
    with so.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    monkeypatch.setattr(B, "STANDIN_PORTS", range(port, port + 1))

    async def finder():
        return [{"id": "anycubic-1", "name": "Kobra 3", "host": "127.0.0.9", "model": "kobra-3", "rinkhals": True, "why": None}]
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], finder=finder, standin_host="127.0.0.1",
                    doors=D.Doors(tmp_path / "bench", api=str(relay.make_url("")), bin_dir=bins, python="python3",
                                  door_py=door_py, spawn=spawn), remote="relay")
    client = await aiohttp_client(bench.app())
    assert (await client.post("/bench/add/anycubic-1")).status == 201
    for _ in range(100):
        if bench.doors.house("anycubic-1"):
            break
        await asyncio.sleep(0.02)
    assert seen["claims"][0]["name"] == B.public_name("anycubic-1") != "kobra-3" and bench.doors.house("anycubic-1")   # never its name: that would be public
    assert any("--address" in a and f"{B.public_name('anycubic-1')}.elyir.app" in a for a in started)
    s, _ = bench.standins["anycubic-1"]
    assert s.setup()["secure_link"] == "on" and s.setup()["rows"] == [{"id": "notify"}] and s.setup_open()
    # turned off for this printer, it stays off whatever the box says
    assert (await client.delete("/bench/p/anycubic-1/remote")).status == 200
    assert bench.doors.house("anycubic-1") is None and bench._door_wanted(bench.printers["anycubic-1"]) is False


async def test_renamed_on_its_screen_the_box_and_its_door_say_the_new_name(tmp_path, aiohttp_server, aiohttp_client, monkeypatch):
    import bench_service as B
    import standin as S
    monkeypatch.setattr(S, "RECONNECT", 0.05)
    started = []

    async def spawn(*argv, **kw):
        started.append(list(argv))
        return FakeProc(list(argv))
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("")
        os.chmod(bins / n, 0o755)
    door_py = tmp_path / "door.py"
    door_py.write_text("")
    import socket as so
    with so.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    doors = D.Doors(tmp_path / "bench", bin_dir=bins, python="python3", door_py=door_py, spawn=spawn)
    doors.relay("k").save({"name": "kobra-3", "address": "kobra-3.elyir.app", "secret": "s", "addr": "a", "token": "t"})
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], standin_host="127.0.0.1", doors=doors)
    bench.printers = {"k": {"name": "Kobra 3", "host": "127.0.0.1", "port": port, "moonraker_port": port, "home": None,
                            "token": None, "remote": True, "standin": {"printer": "127.0.0.9", "moonraker_port": 1}}}
    await aiohttp_client(bench.app())
    s, _ = bench.standins["k"]
    out = await s.action("setup_name", {"name": "  Garage   Kobra "})
    assert out["intent"]["printer"]["name"] == "Garage Kobra" and bench.printers["k"]["name"] == "Garage Kobra"
    await asyncio.sleep(0.05)                     # the door starts again in the background
    door = [a for a in started if "--printer-name" in a][-1]
    assert door[door.index("--printer-name") + 1] == "Garage Kobra"
    with pytest.raises(S.RpcError):
        await s.action("setup_name", {"name": "   "})



async def test_a_door_opened_when_the_box_starts_gets_its_name_at_home_then(tmp_path, aiohttp_client, monkeypatch):
    """A home hub lists only a printer with a name at home: not left for the 15-minute round (7 October 2026)."""
    import bench_service as B
    import standin as S
    monkeypatch.setattr(S, "RECONNECT", 0.05)

    async def spawn(*argv, **kw):
        return FakeProc(list(argv))
    bins = tmp_path / "bin"
    bins.mkdir()
    for n in ("caddy-2.11.4", "frpc-0.71.0"):
        (bins / n).write_text("")
        os.chmod(bins / n, 0o755)
    door_py = tmp_path / "door.py"
    door_py.write_text("")
    import socket as so
    with so.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    doors = D.Doors(tmp_path / "bench", bin_dir=bins, python="python3", door_py=door_py, spawn=spawn, home_port=443,
                    ip=lambda: "192.0.2.59")
    doors.relay("k").save({"name": "kobra-3", "address": "kobra-3.elyir.app", "secret": "s", "addr": "a", "token": "t"})
    asked = []

    async def homecert(pid):
        asked.append(pid)
    monkeypatch.setattr(doors, "homecert", homecert)
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], standin_host="127.0.0.1", doors=doors)
    bench.printers = {"k": {"name": "Kobra 3", "host": "127.0.0.1", "port": port, "moonraker_port": port, "home": None,
                            "token": None, "remote": True, "standin": {"printer": "127.0.0.9", "moonraker_port": 1}}}
    await aiohttp_client(bench.app())
    for _ in range(100):
        if asked:
            break
        await asyncio.sleep(0.02)
    assert asked == ["k"]


async def test_the_box_finds_a_printers_new_name_at_home_when_the_old_one_stops_answering(tmp_path, aiohttp_server):
    import bench_service as B

    async def status(request):
        return web.json_response({"home_address": "192-168-1-20.p-k7qx2mna.home.elyir.app"})
    app = web.Application()
    app.router.add_get("/door/status", status)
    printer = await aiohttp_server(app)
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [])
    p = {"name": "Studio", "host": "127.0.0.1", "port": printer.port, "home": "https://192-168-1-20.studio.home.elyir.app",
         "token": "t"}
    bench.printers["studio"] = p
    async with ClientSession() as s:
        bench.session = s
        assert await bench._refresh_home("studio", p) is True
        assert p["home"] == "https://192-168-1-20.p-k7qx2mna.home.elyir.app"
        assert await bench._refresh_home("studio", p) is False          # the same name again: nothing changed
