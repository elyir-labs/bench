"""A USB stick (design/usb/: 1 A, all of 2, 3 A): what's on it is read when it goes in; a signed newer release is
installed from it as an update from the internet would be; keys and Wi-Fi only when ticked; a report goes onto any
stick, never onto a printer's card; with no screen answering, its update goes by itself."""
import contextlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402
from test_update import STUB  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDncxwALco9tpc9Dr3opbhL8C7xcngsyuMbEajsEMh58 laptop"
FACTS = {"print_state": "standby", "model": "Raspberry Pi 5 Model B Rev 1.0", "network_manager": True,
         "host": "workshop", "moonraker": {"service": True, "url": "http://127.0.0.1:9"}}
S = {"role": "printer", "port": 80, "printer_name": "Workshop"}
PART = {"dev": "sda1", "fstype": "vfat", "label": "BENCH", "uuid": "AB12-CD34", "mountpoint": None, "system": False, "card": False}


def keypair(tmp: Path, name: str) -> tuple[Path, Path]:
    key, pub = tmp / f"{name}.pem", tmp / f"{name}.pub.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)], check=True)
    subprocess.run(["openssl", "ec", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    return key, pub


@pytest.fixture
def rig(tmp_path, monkeypatch):
    base = tmp_path / "elyir-bench"
    (base / "releases" / "2026.11.08-aaa").mkdir(parents=True)
    (base / "releases" / "2026.11.08-aaa" / "VERSION").write_text("2026.11.08-aaa\n")
    (base / "current").symlink_to(base / "releases" / "2026.11.08-aaa")
    for name, value in (("BASE", base), ("CURRENT", base / "current"), ("RELEASES", base / "releases"),
                        ("STATE", base / "state.json"), ("UPDATE_FILE", base / "update.json"),
                        ("INCOMING", base / "incoming"), ("USB_FILE", base / "usb.json"), ("USB_ASK", base / "usb-take.json"),
                        ("USB_LOCK", base / ".usb.lock"), ("HOME", tmp_path / "home"),
                        ("OS_VERSION_FILE", tmp_path / "os-version")):
        monkeypatch.setattr(a, name, value)
    monkeypatch.setenv("ELYIR_BENCH_HOME", str(base))
    (tmp_path / "home").mkdir()
    key, pub = keypair(tmp_path, "elyir")
    monkeypatch.setattr(a, "RELEASE_KEY", pub.read_text())

    stick = tmp_path / "stick"
    (stick / "elyir-bench").mkdir(parents=True)
    part = dict(PART)
    monkeypatch.setattr(a, "usb_block", lambda dev: dict(part) if dev == "sda1" else None)
    mounts = []

    @contextlib.contextmanager
    def mounted(p, rw=False):
        if rw and p.get("card"):
            raise a.StepFailed("That looks like a printer's card, so nothing is written to it.")
        mounts.append("rw" if rw else "ro")
        yield stick
    monkeypatch.setattr(a, "mounted", mounted)
    calls = []
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(a, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(a, "update_busy", lambda f, s, nightly: None)

    def put(version, built=None, signed_by=key, installer=None, sig=True):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            mine = Path(a.__file__).stem
            files = [("VERSION", version + "\n"), (f"installer/{installer or mine}.py", STUB), (f"installer/{mine}_os.py", "")]
            if built:
                files.append(("BUILT", f"{built}\n"))
            for name, text in files:
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        f = stick / "elyir-bench" / f"elyir-bench-{version}.tar.gz"
        f.write_bytes(buf.getvalue())
        if sig:
            subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(signed_by), "-out", str(f) + ".sig", str(f)], check=True)
        return f

    return {"base": base, "stick": stick, "put": put, "calls": calls, "mounts": mounts, "part": part, "tmp": tmp_path}


def usb(base):
    return json.loads((base / "usb.json").read_text())


def test_wifi_txt_by_names_or_two_lines():
    assert a.parse_wifi("name: Home Wi-Fi\npassword: sunny day\n") == ("Home Wi-Fi", "sunny day")
    assert a.parse_wifi("SSID=Shop:2\nPSK = \"x y\"") == ("Shop:2", "x y")
    assert a.parse_wifi("# the shop\nShop\nhunter22\n") == ("Shop", "hunter22")
    assert a.parse_wifi("name: Guest\n") == ("Guest", "")


def test_a_public_key_has_a_fingerprint_like_ssh_keygen_says():
    k = a.parse_ssh_key(KEY)
    assert (k["kind"], k["name"]) == ("ssh-ed25519", "laptop") and k["fp"].startswith("SHA256:") and "=" not in k["fp"]
    assert a.parse_ssh_key(KEY.replace("ssh-ed25519", "ssh-rsa", 1)) is None


def test_reading_a_stick_says_what_it_can_take_and_why_not(rig):
    put, stick = rig["put"], rig["stick"]
    put("2026.11.09-bbb")
    put("2026.11.02-old")
    (stick / "elyir-bench" / "laptop.pub").write_text(KEY + "\n")
    (stick / "elyir-bench" / "WiFi.txt").write_text("name: Home Wi-Fi\npassword: sunny day\n")
    (stick / "elyir-bench" / "os").mkdir()
    (stick / "elyir-bench" / "os" / "elyir-bench-os-2026.11.09-bbb-pi5.tar").write_bytes(b"x")
    got = a.stick_contents(stick, FACTS)
    assert got["app"]["version"] == "2026.11.09-bbb" and got["app"]["why"] is None           # the newest of the two
    assert got["os"]["why"] == "not_card"                                                   # installed, not flashed
    assert [k["name"] for k in got["keys"]] == ["laptop"] and "line" not in got["keys"][0]
    assert got["wifi"] == {"name": "Home Wi-Fi", "can": True} and "sunny" not in json.dumps(got)


def test_older_unsigned_and_another_build_are_not_offered(rig):
    put, stick = rig["put"], rig["stick"]
    put("2026.11.07-old")
    assert a.stick_contents(stick, FACTS)["app"]["why"] == "older"
    for f in (stick / "elyir-bench").glob("*"):
        f.unlink()
    put("2026.11.09-bbb", sig=False)
    assert a.stick_contents(stick, FACTS)["app"]["why"] == "unsigned"
    for f in (stick / "elyir-bench").glob("*"):
        f.unlink()
    put("2026.11.09-bbb", installer="someone_elses")
    assert a.stick_contents(stick, FACTS)["app"]["why"] == "other_build"


def test_a_card_takes_its_whole_os_for_its_own_board_and_not_the_app_beside_it(rig):
    put, stick, tmp = rig["put"], rig["stick"], rig["tmp"]
    (tmp / "os-version").write_text("2026.11.08-aaa\n")
    put("2026.11.09-bbb")
    (stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi4.tar").write_bytes(b"x")
    (stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi4.tar.sig").write_bytes(b"x")
    got = a.stick_contents(stick, FACTS)
    assert got["os"]["why"] == "board" and got["app"]["why"] is None
    (stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi4.tar").rename(stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi5.tar")
    (stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi4.tar.sig").rename(stick / "elyir-bench" / "elyir-bench-os-2026.11.09-bbb-pi5.tar.sig")
    got = a.stick_contents(stick, FACTS)
    assert got["os"]["why"] is None and got["app"]["why"] == "with_os"


def test_a_stick_with_an_update_and_no_screen_answering_updates_by_itself(rig, monkeypatch):
    rig["put"]("2026.11.09-bbb")
    monkeypatch.setattr(a, "USB_FALLBACK", 0)
    started = []
    monkeypatch.setattr(a, "start_usb_unit", lambda: started.append(1))
    assert a.usb_in("sda1", FACTS, S) == 0
    u = usb(rig["base"])
    assert u["present"] and u["id"] == "AB12-CD34" and u["app"]["version"] == "2026.11.09-bbb" and rig["mounts"] == ["ro"]
    assert started and json.loads(rig["base"].joinpath("usb-take.json").read_text()) == \
        {"id": "AB12-CD34", "app": True, "os": False, "auto": "screen"}


def test_a_screen_that_saw_it_asks_and_nothing_goes_by_itself(rig, monkeypatch):
    rig["put"]("2026.11.09-bbb")
    monkeypatch.setattr(a, "USB_FALLBACK", 3)
    started = []
    monkeypatch.setattr(a, "start_usb_unit", lambda: started.append(1))
    real_sleep = a.time.sleep

    def seen(_):
        with a.usb_locked():
            u = a.load_usb()
            u["seen"] = True
            a.save_usb(u)
        real_sleep(0)
    monkeypatch.setattr(a.time, "sleep", seen)
    assert a.usb_in("sda1", FACTS, S) == 0
    assert not started and not rig["base"].joinpath("usb-take.json").exists()


def test_while_printing_its_update_is_copied_now_and_waits_for_the_print(rig, monkeypatch):
    rig["put"]("2026.11.09-bbb")
    monkeypatch.setattr(a, "update_busy", lambda f, s, nightly: "It's printing.")
    started = []
    monkeypatch.setattr(a, "start_usb_unit", lambda: started.append(1))
    a.usb_in("sda1", FACTS, S)
    assert started and json.loads(rig["base"].joinpath("usb-take.json").read_text())["auto"] == "print"


def test_not_now_holds_across_a_restart_with_the_stick_still_in(rig, monkeypatch):
    rig["put"]("2026.11.09-bbb")
    monkeypatch.setattr(a, "USB_FALLBACK", 0)
    monkeypatch.setattr(a, "start_usb_unit", lambda: None)
    a.usb_in("sda1", FACTS, S)
    with a.usb_locked():
        u = a.load_usb()
        a.save_usb({**u, "skipped": True, "skips": [a.skip_key(u)]})
    monkeypatch.setattr(a, "boot_id", lambda: "boot-2")
    assert a.load_usb() == {"skips": [a.skip_key(u)]}
    rig["base"].joinpath("usb-take.json").unlink(missing_ok=True)
    a.usb_in("sda1", FACTS, S)
    assert usb(rig["base"])["skipped"] is True and not rig["base"].joinpath("usb-take.json").exists()


def test_taking_it_copies_then_installs_and_the_stick_can_come_out_first(rig):
    rig["put"]("2026.11.09-bbb")
    (rig["stick"] / "elyir-bench" / "laptop.pub").write_text(KEY + "\n")
    a.save_usb({"dev": "sda1", "id": "AB12-CD34", "present": True, **a.stick_contents(rig["stick"], FACTS)})
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "app": True, "keys": [a.parse_ssh_key(KEY)["id"]]}))
    assert a.usb_run(FACTS, S) == 0
    t = usb(rig["base"])["take"]
    assert (t["state"], t["out"], t["app"], t["keys"], t["result"]) == ("done", True, "2026.11.09-bbb", 1, "done")
    assert a.current_version() == "2026.11.09-bbb"
    assert json.loads(rig["base"].joinpath("update.json").read_text())["state"] == "done"
    assert KEY in (rig["tmp"] / "home" / ".ssh" / "authorized_keys").read_text()
    assert ("systemctl", "enable", "--now", "ssh") in rig["calls"]


def test_nothing_unticked_is_taken(rig):
    rig["put"]("2026.11.09-bbb")
    (rig["stick"] / "elyir-bench" / "laptop.pub").write_text(KEY + "\n")
    (rig["stick"] / "elyir-bench" / "wifi.txt").write_text("Home Wi-Fi\nsunny day\n")
    a.save_usb({"dev": "sda1", "id": "AB12-CD34", "present": True, **a.stick_contents(rig["stick"], FACTS)})
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "app": True}))
    a.usb_run(FACTS, S)
    assert not (rig["tmp"] / "home" / ".ssh" / "authorized_keys").exists()
    assert not any(c[0] in ("install", a.sudo_bin("install")) or c[:2] == ("nmcli", "connection") for c in rig["calls"])


def test_one_not_signed_by_elyir_is_never_installed_from_a_stick(rig):
    other, _ = keypair(rig["tmp"], "other")
    rig["put"]("2026.11.09-bbb", signed_by=other)
    a.save_usb({"dev": "sda1", "id": "AB12-CD34", "present": True, **a.stick_contents(rig["stick"], FACTS)})
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "app": True}))
    assert a.usb_run(FACTS, S) == 1
    t = usb(rig["base"])["take"]
    assert t["state"] == "failed" and "isn't signed by Elyir" in t["why"] and a.current_version() == "2026.11.08-aaa"


def test_a_developer_key_is_trusted_by_a_developer_build_only(rig, monkeypatch, tmp_path):
    dev, dev_pub = keypair(tmp_path, "dev")
    f = rig["put"]("2026.11.09-bbb", signed_by=dev)
    here = Path(a.__file__).resolve().parent / a.DEV_KEY_FILE
    assert not here.exists()
    here.write_text(dev_pub.read_text())
    try:
        monkeypatch.setattr(a, "DEV_KEY_TRUSTED", True)
        a.verify_signature(f, Path(str(f) + ".sig"))
        monkeypatch.setattr(a, "DEV_KEY_TRUSTED", False)
        with pytest.raises(a.StepFailed):
            a.verify_signature(f, Path(str(f) + ".sig"))
    finally:
        here.unlink()


def test_a_report_goes_onto_any_stick_but_never_a_printers_card(rig, monkeypatch):
    monkeypatch.setattr(a, "gather_report", lambda facts, s, kind: ({"kind": kind}, b"bundle"))
    a.save_usb({"dev": "sda1", "id": "AB12-CD34", "present": True, **a.stick_contents(rig["stick"], FACTS)})
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "report": True}))
    assert a.usb_run(FACTS, S) == 0
    t = usb(rig["base"])["take"]
    assert t["state"] == "done" and t["report"].startswith("workshop-report-") and rig["mounts"] == ["ro", "rw"]
    assert (rig["stick"] / "elyir-bench" / "reports" / t["report"]).read_bytes() == b"bundle"
    rig["part"]["card"] = True
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "report": True}))
    assert a.usb_run(FACTS, S) == 1 and "printer's card" in usb(rig["base"])["take"]["why"]


def test_a_stick_that_came_out_before_it_was_read(rig):
    a.save_usb({"dev": "sda1", "id": "AB12-CD34", "present": False})
    rig["base"].joinpath("usb-take.json").write_text(json.dumps({"id": "AB12-CD34", "app": True}))
    assert a.usb_run(FACTS, S) == 1 and "came out" in usb(rig["base"])["take"]["why"]


def test_out_marks_only_its_own_stick(rig):
    a.save_usb({"dev": "sda1", "id": "x", "present": True})
    a.usb_out("sdb1")
    assert usb(rig["base"])["present"] is True
    a.usb_out("sda1")
    assert usb(rig["base"])["present"] is False


def test_the_units_follow_the_stick_and_the_rule_starts_them():
    units = a.render_usb_units({"user": "pi"})
    stick = units["elyir-bench-usb@.service"]
    assert "BindsTo=dev-%i.device" in stick and "usb in %I" in stick and "ExecStopPost=" in stick and "User=pi" in stick
    assert "usb run" in units["elyir-bench-usb.service"] and "TimeoutStartSec=infinity" in units["elyir-bench-usb.service"]
    assert 'ENV{ID_BUS}=="usb"' in a.USB_RULE_TEXT and "elyir-bench-usb@%k.service" in a.USB_RULE_TEXT
