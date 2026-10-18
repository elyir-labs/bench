"""The first Wi-Fi's service (setup/wifi_setup.py): the pure parts, then the whole flow against the pretend
NetworkManager, the way the panel and a phone drive it."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import wifi_setup as ws


# ── pure parts ──────────────────────────────────────────────────────────────

def test_the_setup_password_is_three_groups_with_nothing_that_reads_two_ways():
    p = ws.setup_password()
    assert len(p) == 14 and p.count("-") == 2
    assert not set(p.replace("-", "")) & set("0o1l")


def test_the_qr_code_escapes_what_the_wifi_format_reserves():
    assert ws.wifi_qr("Elyir Bench 4F2A", "q7tm-4kzr-x2pd") == "WIFI:T:WPA;S:Elyir Bench 4F2A;P:q7tm-4kzr-x2pd;;"
    assert ws.wifi_qr('a;b,c:d"e\\', "p") == 'WIFI:T:WPA;S:a\\;b\\,c\\:d\\"e\\\\;P:p;;'


def test_nmcli_terse_lines_keep_escaped_colons_inside_a_field():
    assert ws.split_terse(r"Cafe\: upstairs:72:WPA2") == ["Cafe: upstairs", "72", "WPA2"]
    assert ws.split_terse(r"back\\slash:5:--") == ["back\\slash", "5", "--"]


def test_networks_are_listed_once_strongest_first_without_hidden_ones_or_our_own():
    rows = [("Home", 40, "WPA2"), ("", 90, "WPA2"), ("Home", 70, "WPA2"), ("Elyir Bench 4F2A", 99, "WPA2"),
            ("Cafe", 55, "--"), ("Work", 60, "WPA2 802.1X"), ("New", 50, "WPA3")]
    got = ws.networks_from(rows, skip="Elyir Bench 4F2A")
    assert [(n["ssid"], n["signal"], n["security"]) for n in got] == [
        ("Home", 70, "wpa"), ("Work", 60, "enterprise"), ("Cafe", 55, "open"), ("New", 50, "sae")]


@pytest.mark.parametrize("pw,security,ok", [("12345678", "wpa", True), ("1234567", "wpa", False), ("x" * 63, "wpa", True),
                                            ("x" * 64, "wpa", False), ("ab" * 32, "wpa", True), ("", "open", True)])
def test_wifi_passwords_are_8_to_63_characters_or_64_hex(pw, security, ok):
    assert (ws.password_problem(pw, security) is None) == ok


def test_names_need_a_letter_or_number_and_fit():
    assert ws.name_problem("Workshop") is None
    assert ws.name_problem("  ") and ws.name_problem("--") and ws.name_problem("x" * 33)


def test_the_setup_wifi_keyfile_is_wpa2_ccmp_shared_on_its_own_address():
    k = ws.keyfile("Elyir Bench 4F2A", "q7tm-4kzr-x2pd", "u-1", ap=True, ifname="wlan0")
    for line in ("id=elyir-bench-setup", "autoconnect=false", "mode=ap", "band=bg", "ssid=Elyir Bench 4F2A",
                 "key-mgmt=wpa-psk", "proto=rsn", "pairwise=ccmp", "group=ccmp", "psk=q7tm-4kzr-x2pd",
                 "method=shared", "address1=10.42.0.1/24", "interface-name=wlan0"):
        assert line in k.splitlines()


def test_a_home_network_keyfile_connects_by_itself_and_keeps_odd_names_intact():
    k = ws.keyfile(" Home\\Net", "secret 99", "u-2", hidden=True).splitlines()
    assert "id=\\sHome\\\\Net" in k and "ssid=\\sHome\\\\Net" in k and "autoconnect=true" in k and "hidden=true" in k
    assert "psk=secret 99" in k and "method=auto" in k
    assert "[wifi-security]" not in ws.keyfile("Cafe", "", "u-3", security="open")
    assert "key-mgmt=sae" in ws.keyfile("New", "12345678", "u-4", security="sae")


def test_failures_are_told_apart_by_what_nmcli_says():
    assert ws.failure_reason("Error: Connection activation failed: Secrets were required, but not provided.") == "password"
    assert ws.failure_reason("Error: No network with SSID 'Nowhere' found.") == "not_found"
    assert ws.failure_reason("Error: Timeout expired (45 seconds)") == "timeout"
    assert ws.failure_reason("Error: something else") == "other"


# ── the flow, against the pretend NetworkManager ───────────────────────────

@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "HANDOFF", 0.01)
    monkeypatch.setattr(ws, "CHECK_EVERY", 0.05)
    renames = []
    monkeypatch.setattr(ws.Setup, "_rename", lambda self: renames.append(self.saved.get("name")) if self.saved.get("name") else None)
    nm = ws.FakeNetworkManager(speed=200)
    setup = ws.Setup(nm, tmp_path / "wifi-setup.json", None, "8088", tail="4F2A")
    ws.Handler.flow = setup
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ws.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=setup.run, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, setup, nm, renames
    srv.shutdown()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def until(base, mode, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        _, s = call(base, "/wifi/state")
        if s["mode"] == mode:
            return s
        time.sleep(0.02)
    raise AssertionError(f"never {mode}: {s}")


def test_a_new_printer_opens_its_setup_wifi_with_the_networks_it_heard(served):
    base, setup, nm, _ = served
    s = until(base, "open")
    assert nm.up
    assert s["setup"] == {"ssid": "Elyir Bench 4F2A", "qr": ws.wifi_qr("Elyir Bench 4F2A", setup.saved["password"])}
    assert [n["ssid"] for n in s["networks"]][:2] == ["Hartley Home", "Hartley Home Guest"]


def test_a_wrong_password_brings_the_setup_wifi_back_with_the_same_code(served):
    base, setup, nm, _ = served
    qr = until(base, "open")["setup"]["qr"]
    code, body = call(base, "/wifi/join", {"ssid": "Hartley Home", "password": "wrongpass"})
    assert code == 202 and body["mode"] == "joining"
    code, _ = call(base, "/wifi/join", {"ssid": "Hartley Home", "password": "wrong"})   # too short: refused at once
    s = until(base, "failed")
    assert s["reason"] == "password" and s["ssid"] == "Hartley Home" and s["setup"]["qr"] == qr and nm.up


def test_too_short_a_password_is_refused_before_the_setup_wifi_closes(served):
    base, _, nm, _ = served
    until(base, "open")
    code, body = call(base, "/wifi/join", {"ssid": "Hartley Home", "password": "short"})
    assert code == 400 and body["reason"] == "password" and nm.up


def test_joining_then_naming_then_done(served):
    base, setup, nm, renames = served
    until(base, "open")
    assert call(base, "/wifi/join", {"ssid": "Hartley Home", "password": "correct horse"})[0] == 202
    assert call(base, "/wifi/name", {"name": "  Workshop "})[0] == 200        # while it joins
    s = until(base, "connected")
    assert s["via"] == "wifi" and s["name"] == "Workshop" and "setup" not in s and not nm.up
    assert renames == ["Workshop"]                                           # applied once it's on the Wi-Fi
    assert call(base, "/wifi/join", {"ssid": "x", "password": "12345678"})[0] == 409
    assert call(base, "/wifi/done", {})[0] == 200
    assert until(base, "off")
    saved = json.loads(Path(setup.state_file).read_text())
    assert saved["done"] and saved["joined"] == "Hartley Home"


def test_another_network_is_joined_as_a_hidden_one(served):
    base, setup, nm, _ = served
    until(base, "open")
    call(base, "/wifi/join", {"ssid": "Nowhere", "password": "12345678", "hidden": True})
    assert until(base, "failed")["reason"] == "not_found"


def test_a_printer_that_already_has_wifi_does_nothing(tmp_path):
    nm = ws.FakeNetworkManager(speed=200)
    nm.joined = "Imager's network"
    setup = ws.Setup(nm, tmp_path / "s.json", None, "8088", tail="4F2A")
    setup._begin()
    assert setup.mode == "off" and not nm.up


def test_after_a_restart_the_panel_still_has_its_name_and_phone_to_do(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"joined": "Hartley Home", "password": "x"}))
    setup = ws.Setup(ws.FakeNetworkManager(speed=200), tmp_path / "s.json", None, "8088", tail="4F2A")
    setup._begin()
    assert setup.mode == "connected" and setup.public()["ssid"] == "Hartley Home"


def test_the_phone_page_is_what_any_address_gets_and_the_house_is_sent_to_the_app_once_set_up(served):
    base, setup, _, _ = served
    until(base, "open")
    req = urllib.request.Request(base + "/hotspot-detect.html", headers={"X-Real-IP": "10.42.0.23", "Host": "captive.apple.com"})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200 and b"Which Wi-Fi should the printer use?" in r.read()
    setup.mode = "off"

    class NoFollow(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    req = urllib.request.Request(base + "/", headers={"X-Real-IP": "192.168.1.30", "Host": "workshop.local"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.build_opener(NoFollow).open(req, timeout=5)
    assert e.value.code == 302 and e.value.headers["Location"] == "http://workshop.local:8088/"


def test_a_printer_online_some_other_way_is_never_cut_off(tmp_path):
    nm = ws.FakeNetworkManager(speed=200)
    nm.online = lambda: True               # a default route, say a Wi-Fi NetworkManager doesn't manage
    setup = ws.Setup(nm, tmp_path / "s.json", None, "8088", tail="4F2A")
    setup._begin()
    assert setup.mode == "off" and not nm.up


def test_a_wifi_chip_that_isnt_networkmanagers_is_left_alone(tmp_path):
    nm = ws.FakeNetworkManager(speed=200)
    nm.wifi_state = lambda: "unmanaged"
    setup = ws.Setup(nm, tmp_path / "s.json", None, "8088", tail="4F2A")
    setup._begin()
    assert setup.mode == "off" and not nm.up
