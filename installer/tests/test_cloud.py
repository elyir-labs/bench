"""Bench Cloud, the printer's side (docs/cloud.md, design/cloud/ C): joining a house, the nightly backup, and a new card
bringing a backup back through Bring it over once the owner allows it, against a stand-in Bench Cloud over HTTP."""

import http.server
import io
import json
import stat
import sys
import tarfile
import threading
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import elyir_bench as a  # noqa: E402
from test_bring_it_over import PRINTER_CFG, FakeMoonraker, rig  # noqa: E402,F401


class FakeCloud:
    """Bench Cloud as much as a printer uses it."""

    def __init__(self):
        self.backups, self.state, self.code, self.emailed = [], "waiting", "482913", False
        self.offers = [{"device": "p_workshop", "name": "Workshop", "kind": "printer", "at": 1791700000.0,
                        "owner_phone": "Alex's iPhone", "owner_email": "a•••x@example.net"}]
        self.archive, self.token_given, self.asked, self.homes = b"", False, [], []
        self.plan, self.tickets = True, []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body=None, raw=None):
                b = raw if raw is not None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/gzip" if raw is not None else "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/v1/restore/offers":
                    outer.homes.append(self.headers.get("X-Bench-Home"))
                    return self._send(200, {"offers": outer.offers})
                if u.path == "/v1/restore/asks/a_1" and q.get("secret") == "s_card":
                    out = {"state": outer.state}
                    if outer.state == "allowed" and not outer.token_given:
                        out["device_token"], outer.token_given = "d_new", True
                    return self._send(200, out)
                if u.path == "/v1/restore/asks/a_1/backup" and outer.state == "allowed":
                    return self._send(200, raw=outer.archive)
                self._send(404, {"error": "There's no such request."})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                path = urllib.parse.urlparse(self.path).path
                if path == "/v1/backups":
                    outer.homes.append(self.headers.get("X-Bench-Home"))
                    if self.headers.get("Authorization") != "Bearer d_workshop":
                        return self._send(401, {"error": "This printer isn't part of a Bench Cloud house."})
                    outer.backups.append(raw)
                    return self._send(200, {"backup": "b_1", "size": len(raw), "at": 1791700000.0})
                body = json.loads(raw or b"{}")
                if path == "/v1/carry-ticket":
                    if self.headers.get("Authorization") != "Bearer d_workshop":
                        return self._send(401, {"error": "This printer isn't part of a Bench Cloud house."})
                    if not outer.plan:
                        return self._send(403, {"error": "This house's Bench Cloud plan doesn't include reaching printers from away."})
                    outer.tickets.append(body["name"])
                    return self._send(200, {"ticket": f"t_{body['name']}", "until": 1794000000.0, "expires": 1791703600.0})
                if path == "/v1/devices":
                    if body.get("join_token") != "j_good":
                        return self._send(403, {"error": "That join code has been used or has run out."})
                    return self._send(200, {"device": "p_workshop", "device_token": "d_workshop", "house": "h_1", "name": "Workshop"})
                if path == "/v1/restore/asks":
                    outer.asked.append(body)
                    return self._send(200, {"ask": "a_1", "secret": "s_card", "name": "Workshop", "at": 1791700000.0})
                if path == "/v1/restore/asks/a_1/email":
                    outer.emailed = True
                    return self._send(200, {"pending": "c_1", "sent_to": ["a•••x@example.net"]})
                if path == "/v1/restore/asks/a_1/code":
                    if body.get("code") != outer.code or body.get("pending") != "c_1":
                        return self._send(403, {"error": "That code isn't right, or it has run out. Ask for a new one."})
                    outer.state = "allowed"
                    return self._send(200, {"state": "allowed"})
                self._send(404, {"error": "no"})

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


ROUTE = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
         "wlan0\t00000000\t0156A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
         "wlan0\t0056A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0\n")
ARP = ("IP address       HW type     Flags       HW address            Mask     Device\n"
       "192.0.2.1     0x1         0x2         7C:D9:5C:AA:BB:CC     *        wlan0\n"
       "192.0.2.73    0x1         0x2         d8:3a:dd:11:22:33     *        wlan0\n")


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    (tmp_path / "route").write_text(ROUTE)
    (tmp_path / "arp").write_text(ARP)
    monkeypatch.setattr(a, "PROC_ROUTE", tmp_path / "route")
    monkeypatch.setattr(a, "PROC_ARP", tmp_path / "arp")
    state = tmp_path / "state"
    (state / "door").mkdir(parents=True)
    monkeypatch.setattr(a, "DOOR_STATE", state)
    monkeypatch.setattr(a, "CLOUD_STATE", state / "cloud.json")
    monkeypatch.setattr(a, "CLOUD_LAST", state / "cloud-last.json")
    monkeypatch.setattr(a, "RELAY_STATE", state / "relay.json")
    fake = FakeCloud()
    return fake, {"cloud_api": fake.url}, state


def a_printer(tmp_path) -> dict:
    pdata = tmp_path / "workshop" / "printer_data"
    (pdata / "config" / "macros").mkdir(parents=True)
    (pdata / "config" / "printer.cfg").write_text(PRINTER_CFG)
    (pdata / "config" / "macros" / "start.cfg").write_text("[gcode_macro PRINT_START]\ngcode:\n")
    (pdata / "config" / a.BRING_FOLDER).mkdir()
    (pdata / "config" / a.BRING_FOLDER / "old.zip").write_bytes(b"not this")
    local = FakeMoonraker(pdata, bench=True)
    return {"host": "workshop", "printer_data": str(pdata), "moonraker": {"url": local.url}}


def test_the_home_mark_is_the_routers_address_hashed(cloud, tmp_path, monkeypatch):
    mark = a.home_mark()
    assert mark == a.hashlib.sha256(b"elyir-bench-home:7c:d9:5c:aa:bb:cc").hexdigest()[:32]
    (tmp_path / "arp").write_text(ARP.splitlines()[0] + "\n")
    assert a.home_mark() is None
    monkeypatch.setattr(a, "PROC_ROUTE", tmp_path / "nothing")
    assert a.home_mark() is None


def test_joining_keeps_the_token_private_and_says_nothing_of_it(cloud, tmp_path):
    fake, s, state = cloud
    with pytest.raises(a.StepFailed, match="used or has run out"):
        a.cloud_join(s, "j_bad")
    got = a.cloud_join(s, "j_good")
    assert got["name"] == "Workshop" and "token" not in got
    saved = json.loads((state / "cloud.json").read_text())
    assert saved["token"] == "d_workshop" and saved["api"] == fake.url
    assert stat.S_IMODE((state / "cloud.json").stat().st_mode) == 0o600


def test_the_backup_is_what_bring_it_over_reads_plus_the_doors_files(cloud, tmp_path):
    fake, s, state = cloud
    facts = a_printer(tmp_path)
    (state / "relay.json").write_text('{"name": "workshop", "secret": "x"}')
    (state / "door" / "phones.json").write_text("[]")
    assert a.cloud_backup(facts) == {"off": True} and not fake.backups
    a.cloud_join(s, "j_good")
    last = a.cloud_backup(facts)
    assert last["size"] == len(fake.backups[0]) and json.loads((state / "cloud-last.json").read_text()) == last
    with tarfile.open(fileobj=io.BytesIO(fake.backups[0])) as t:
        names = set(t.getnames())
    assert {"printer_data/config/printer.cfg", "printer_data/config/macros/start.cfg", a.CLOUD_DB,
            "elyir-bench-state/relay.json", "elyir-bench-state/door/phones.json"} <= names
    assert not any(a.BRING_FOLDER in n for n in names)
    src = a.ArchiveSource(_saved(tmp_path, fake.backups[0]))
    try:
        assert src.facts()["history"] == 7
    finally:
        src.close()


def _saved(tmp_path, data, name="night.tar.gz"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_a_backup_that_cant_reach_the_cloud_says_why(cloud, tmp_path):
    fake, s, state = cloud
    facts = a_printer(tmp_path)
    a.cloud_join(s, "j_good")
    me = json.loads((state / "cloud.json").read_text())
    a.save_private(state / "cloud.json", json.dumps({**me, "api": "http://127.0.0.1:1"}))
    assert a.cloud_backup(facts)["why"] == "Bench Cloud can't be reached right now."


def backup_of_workshop() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, text in (("printer_data/config/printer.cfg", PRINTER_CFG),
                           ("printer_data/config/macros/start.cfg", "[gcode_macro PRINT_START]\ngcode:\n"),
                           ("elyir-bench-state/relay.json", '{"name": "workshop", "secret": "x"}'),
                           ("elyir-bench-state/door/phones.json", '[{"id": "p1"}]')):
            info = tarfile.TarInfo(name)
            info.size = len(text.encode())
            t.addfile(info, io.BytesIO(text.encode()))
    return buf.getvalue()


def test_a_fresh_card_finds_its_backup_and_brings_it_back_once_the_owner_allows(rig, cloud, monkeypatch):
    facts, _, _ = rig
    fake, s, state = cloud
    fake.archive = backup_of_workshop()
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    got = {x["id"]: x for x in a.bring_scan(facts, s)["sources"]}
    c = got["cloud-p-workshop"]
    assert (c["kind"], c["name"], c["detail"], c["owner_phone"]) == ("cloud", "Workshop", "Your Bench Cloud backup", "Alex's iPhone")
    with pytest.raises(a.StepFailed, match="owner allows"):
        a.bring_plan(facts, "cloud-p-workshop")
    asked = a.bring_cloud_ask("cloud-p-workshop")
    assert asked["cloud"]["state"] == "waiting" and fake.asked == [{"device": "p_workshop", "home": a.home_mark()}]
    assert fake.homes == [a.home_mark()]
    assert a.bring_cloud_check(facts, s)["cloud"]["state"] == "waiting"
    fake.state = "allowed"
    done = a.bring_cloud_check(facts, s)
    assert done["cloud"]["state"] == "allowed"
    fid = done["cloud"]["file"]
    assert fid in [x["id"] for x in done["sources"]] and "cloud_ask" not in a.load_bring()
    assert json.loads((state / "cloud.json").read_text())["token"] == "d_new"
    assert json.loads((state / "relay.json").read_text())["name"] == "workshop"
    assert (state / "door" / "phones.json").read_text() == '[{"id": "p1"}]'
    assert a.bring_plan(facts, fid)["config"] == 2


def test_the_owners_email_code_typed_on_the_card(rig, cloud, monkeypatch):
    facts, _, _ = rig
    fake, s, state = cloud
    fake.archive = backup_of_workshop()
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    a.bring_scan(facts, s)
    a.bring_cloud_ask("cloud-p-workshop")
    with pytest.raises(a.StepFailed, match="email first"):
        a.bring_cloud_code(facts, s, "482913")
    assert a.bring_cloud_email()["cloud"]["emailed"] == "a•••x@example.net"
    with pytest.raises(a.StepFailed, match="isn't right"):
        a.bring_cloud_code(facts, s, "000000")
    assert a.bring_cloud_code(facts, s, "482913")["cloud"]["state"] == "allowed"


def test_a_refused_ask_is_forgotten_and_a_printer_in_a_house_isnt_offered_backups(rig, cloud, monkeypatch):
    facts, _, _ = rig
    fake, s, state = cloud
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    a.bring_scan(facts, s)
    a.bring_cloud_ask("cloud-p-workshop")
    fake.state = "refused"
    assert a.bring_cloud_check(facts, s)["cloud"]["state"] == "refused"
    with pytest.raises(a.StepFailed, match="Nothing is being asked"):
        a.bring_cloud_check(facts, s)
    a.cloud_join(s, "j_good")
    assert a.cloud_entries(s) == []


def test_an_unreachable_cloud_hides_nothing_else(rig, cloud, monkeypatch):
    facts, _, _ = rig
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    assert a.cloud_entries({"cloud_api": "http://127.0.0.1:1"}) == []


class FakeRelay:
    """The relay's /houses/<name> and /houses/<name>/carry, as a printer calls them (relay_call)."""

    def __init__(self, carried=False):
        self.carried, self.calls = carried, []

    def __call__(self, api, method, path, body=None, secret=None):
        self.calls.append((method, path, body, secret))
        if secret != "x":
            return 404, {"detail": "No house by that name holds that key."}
        if method == "POST" and path.endswith("/carry"):
            if body["ticket"] != "t_workshop":
                return 403, {"detail": {"why": "ticket", "message": "That ticket is for another name."}}
            self.carried = True
            return 200, {"carried": True, "entitled_until": 1794000000.0}
        return 200, {"carried": self.carried}


def test_the_plan_carries_the_printers_name_from_away_on_joining_and_every_night(cloud, tmp_path, monkeypatch):
    fake, s, state = cloud
    relay, restarted = FakeRelay(), []
    monkeypatch.setattr(a, "relay_call", relay)
    monkeypatch.setattr(a, "is_active", lambda unit: True)
    monkeypatch.setattr(a, "sudo", lambda *cmd, **k: restarted.append(cmd[-1]))
    (state / "relay.json").write_text('{"name": "workshop", "secret": "x"}')
    s = {**s, "remote": "relay"}
    got = a.cloud_join(s, "j_good")
    assert got["carry"] == {"until": 1794000000.0} and fake.tickets == ["workshop"]
    assert ("POST", "/houses/workshop/carry", {"ticket": "t_workshop"}, "x") in relay.calls
    assert restarted == ["elyir-bench-caddy.service", "elyir-bench-frpc.service"]
    restarted.clear()
    assert a.cloud_carry(s) == {"until": 1794000000.0} and not restarted   # carried already: nothing restarts
    fake.plan = False
    assert "from away" in a.cloud_carry(s)["why"]
    assert a.cloud_carry({**s, "remote": "off"}) == {"skipped": True}
    (state / "relay.json").write_text('{"name": "workshop", "secret": "wrong"}')
    fake.plan = True
    assert a.cloud_carry(s) == {"why": "the relay doesn't know this printer's name any more"}


def test_the_nightly_backup_carries_the_name_too_and_never_fails_for_it(cloud, tmp_path, monkeypatch):
    fake, s, state = cloud
    facts = a_printer(tmp_path)
    monkeypatch.setattr(a, "relay_call", lambda *x, **k: (0, {}))
    (state / "relay.json").write_text('{"name": "workshop", "secret": "x"}')
    a.cloud_join(s, "j_good")
    last = a.cloud_backup(facts, {**s, "remote": "relay"})
    assert last["backup"] == "b_1" and last["carry"] == {"why": "no answer from the relay"}


def test_a_staging_printer_tells_its_door_about_stagings_printers_app():
    facts = {"user": "pi"}
    unit = a.render_door_units(facts, {"remote_name": "studio", "printer_name": "Studio"}, "studio.elyir.app")["elyir-bench-door.service"]
    assert "--printers-app" not in unit
    s = {"remote_name": "studio", "printer_name": "Studio", "printers_app": "https://printers-staging.elyir.app"}
    unit = a.render_door_units(facts, s, "studio.elyir.app")["elyir-bench-door.service"]
    assert '--printer-name "Studio" --printers-app https://printers-staging.elyir.app\n' in unit
