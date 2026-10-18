"""Bring it over, the installer's side (docs/bring-it-over.md, design/printer-setup/ A): `elyir-bench bring scan|plan|
apply|address` against an old card as a folder tree (mounted by a stand-in that records what it was asked), lsblk's
JSON, backup files, and stand-in Moonrakers over HTTP: this printer's own, and another printer's on the Wi-Fi."""

import contextlib
import http.server
import io
import json
import os
import sqlite3
import struct
import sys
import tarfile
import threading
import urllib.parse
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402

MAIN = "usb-Klipper_stm32f446xx_2B0035000F51313236343430-if00"
MAIN_NEW = "usb-Klipper_stm32f446xx_44003A000851323530363620-if00"
ACE = "usb-ANYCUBIC_ACE_1-if00"
EBB = "6cc850bbec73"

PRINTER_CFG = f"""[include macros/*.cfg]
[include KAMP/KAMP_Settings.cfg]

[mcu]
serial: /dev/serial/by-id/{MAIN}   # the Octopus
restart_method: command

[mcu EBBCan]
canbus_uuid: {EBB}

[ace]
serial: /dev/serial/by-id/{ACE}

[printer]
kinematics: corexy

#*# <---------------------- SAVE_CONFIG ---------------------->
#*# [mcu]
#*# serial: /dev/serial/by-id/old
"""


def make_db(path: Path, prints: int = 3, phones: bool = True) -> None:
    """A Moonraker database as Moonraker writes it (moonraker/components/database.py, history.py)."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE namespace_store (namespace TEXT NOT NULL, key TEXT NOT NULL, value record NOT NULL, "
                "PRIMARY KEY (namespace, key))")
    con.execute("CREATE TABLE job_history (job_id INTEGER PRIMARY KEY ASC, user TEXT NOT NULL, filename TEXT, "
                "status TEXT NOT NULL, start_time REAL NOT NULL)")
    con.execute("CREATE TABLE authorized_users (username TEXT PRIMARY KEY NOT NULL, password TEXT NOT NULL)")
    rows = [("mainsail", "general", b'{"printername":"Voron 2.4 350"}'), ("elyir-bench", "spool", b'{"color":"#e5534b"}'),
            ("moonraker", "instance_id", b"sabc")]
    if phones:
        rows.append(("elyir-bench", "phones", b"q\x02\x00\x00\x00\x00\x00\x00\x00"))
    con.executemany("INSERT INTO namespace_store VALUES (?,?,?)", rows)
    con.executemany("INSERT INTO job_history VALUES (?,?,?,?,?)",
                    [(i, "pi", f"part{i}.gcode", "completed", 1.0 + i) for i in range(prints)])
    con.execute("INSERT INTO authorized_users VALUES ('_API_KEY_USER_', 'secret')")
    con.commit()
    con.close()


def old_card(root: Path, name_section: str = "[printer_intent]\nprinter_name: Voron\n") -> Path:
    """An old card's root partition: Pi OS, /home/pi/printer_data and a macro collection linked in absolutely."""
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "hostname").write_text("voron\n")
    pdata = root / "home" / "pi" / "printer_data"
    cfg = pdata / "config"
    (cfg / "macros").mkdir(parents=True)
    (cfg / "printer.cfg").write_text(PRINTER_CFG)
    (cfg / "macros" / "start.cfg").write_text("[gcode_macro PRINT_START]\ngcode:\n  G28\n")
    (cfg / "moonraker.conf").write_text("[server]\nhost: 0.0.0.0\n\n# Elyir Bench (managed by elyir-bench)\n"
                                        f"{name_section}advanced_url: http://voron.local/\n\n[spoolman]\nserver: x\n")
    (cfg / "elyir-bench.conf").write_text("[elyir-bench]\nprinter_name: Voron\nrelay_api: https://relay.example\n")
    (cfg / "printer-20260901_101010.cfg").write_text("[mcu]\nserial: /dev/serial/by-id/usb-Klipper_rp2040_X-if00\n")
    kamp = root / "home" / "pi" / "Klipper-Adaptive-Meshing-Purging" / "Configuration"
    kamp.mkdir(parents=True)
    (kamp / "KAMP_Settings.cfg").write_text("[gcode_macro _KAMP_Settings]\ngcode:\n")
    (cfg / "KAMP").symlink_to("/home/pi/Klipper-Adaptive-Meshing-Purging/Configuration")   # absolute, as KIAUH links it
    (root.parent / "outside").mkdir(exist_ok=True)
    (root.parent / "outside" / "x.cfg").write_text("[printer]\n")
    (cfg / "elsewhere").symlink_to("../../../../../outside")                                 # off the card: left out
    (cfg / ".theme").mkdir()
    (cfg / ".theme" / "custom.css").write_text("body{}")
    (pdata / "gcodes" / ".thumbs").mkdir(parents=True)
    (pdata / "gcodes" / "cube.gcode").write_text("G1 X1\n" * 100)
    (pdata / "gcodes" / "benchy.gcode").write_text("G1 X2\n" * 10)
    (pdata / "gcodes" / ".thumbs" / "cube.png").write_bytes(b"png")
    (pdata / "database").mkdir()
    make_db(pdata / "database" / a.DB_FILE)
    return pdata


def fresh_card(tmp_path: Path) -> dict:
    """This printer: a fresh card's printer_data, no printer.cfg, named Workshop at its first Wi-Fi."""
    pdata = tmp_path / "printer_data"
    (pdata / "config").mkdir(parents=True)
    (pdata / "config" / "moonraker.conf").write_text(
        "[server]\nhost: 0.0.0.0\n\n# Elyir Bench: human-readable printer state for the consumer UI (managed by elyir-bench)\n"
        "[printer_intent]\nprinter_name: Workshop\nadvanced_url: http://workshop.local/\n")
    (pdata / "config" / "elyir-bench.conf").write_text("[elyir-bench]\nprinter_name: Workshop\npanel: elyir-bench\n")
    (pdata / "gcodes").mkdir()
    (pdata / "gcodes" / "cube.gcode").write_text("mine\n")
    return {"host": "workshop", "printer_data": str(pdata), "print_state": None, "can": [], "ace_units": 1,
            "klipper": {"state": "error"}, "moonraker": {"url": "http://127.0.0.1:1"}, "kiosk": {"enabled": True},
            "klipperscreen": {"installed": False}, "panel_output": "DSI-1"}


HERE = {"serial": [MAIN, ACE], "can_ifaces": ["can0"], "can": [EBB], "klipper": "error", "host_mcu": False, "ace": 1,
        "camera": True}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """An old card in a USB reader (sda2), this fresh card, nothing on the Wi-Fi."""
    # this card's Klipper: the same as FakeMoonraker's unless a test says otherwise (never the test machine's own)
    monkeypatch.setattr(a, "local_klipper_version", lambda: "v0.13.0-268-gf52a6f94")
    card = tmp_path / "card"
    old_card(card)
    facts = fresh_card(tmp_path)
    mounts = []

    @contextlib.contextmanager
    def mounted(part):
        mounts.append(("mount", part["dev"]))
        try:
            yield card
        finally:
            mounts.append(("umount", part["dev"]))

    monkeypatch.setattr(a, "BRING_CACHE", tmp_path / "state" / "bring.json")
    monkeypatch.setattr(a, "usb_partitions", lambda: [{"dev": "sda2", "fstype": "ext4", "label": "rootfs", "mountpoint": None}])
    monkeypatch.setattr(a, "mounted", mounted)
    monkeypatch.setattr(a, "mdns_ask", lambda service, timeout=2.0: [])
    monkeypatch.setattr(a, "bring_here", lambda facts: dict(HERE))
    monkeypatch.setattr(a.time, "sleep", lambda s: None)
    return facts, card, mounts


# ── finding an old card ──────────────────────────────────────────────────────

LSBLK = {"blockdevices": [
    {"name": "mmcblk0", "tran": None, "type": "disk", "fstype": None, "label": None, "mountpoint": None, "children": [
        {"name": "mmcblk0p1", "tran": None, "type": "part", "fstype": "vfat", "label": "bootfs", "mountpoint": "/boot/firmware"},
        {"name": "mmcblk0p2", "tran": None, "type": "part", "fstype": "ext4", "label": "rootfs", "mountpoint": "/"}]},
    {"name": "sda", "tran": "usb", "type": "disk", "fstype": None, "label": None, "mountpoint": None, "children": [
        {"name": "sda1", "tran": None, "type": "part", "fstype": "vfat", "label": "bootfs", "mountpoint": None},
        {"name": "sda2", "tran": None, "type": "part", "fstype": "ext4", "label": "rootfs", "mountpoint": None},
        {"name": "sda3", "tran": None, "type": "part", "fstype": "swap", "label": None, "mountpoint": None}]},
    {"name": "sdb", "tran": "usb", "type": "disk", "fstype": None, "label": None, "mountpoint": None, "children": [
        {"name": "sdb1", "tran": None, "type": "part", "fstype": "vfat", "label": "bootfs", "mountpoint": "/boot/firmware"},
        {"name": "sdb2", "tran": None, "type": "part", "fstype": "ext4", "label": "rootfs", "mountpoint": "/"}]},
    {"name": "sdc", "tran": "usb", "type": "disk", "fstype": "vfat", "label": "STICK", "mountpoint": "/media/pi/STICK"},
]}


def test_an_old_card_is_found_on_usb_and_never_the_disk_this_pi_runs_from(monkeypatch):
    class P:
        stdout = json.dumps(LSBLK)
    monkeypatch.setattr(a, "run", lambda cmd, **kw: P())
    got = a.usb_partitions()
    assert [(p["dev"], p["fstype"], p["mountpoint"]) for p in got] == [
        ("sda1", "vfat", None), ("sda2", "ext4", None), ("sdc", "vfat", "/media/pi/STICK")]


def test_a_card_is_mounted_read_only_and_unmounted_after(monkeypatch):
    seen = []
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: seen.append(cmd))
    with a.mounted({"dev": "sda2", "fstype": "ext4", "mountpoint": None}) as mp:
        assert mp == Path("/run/elyir-bench-bring/sda2")
        assert seen == [("mkdir", "-p", "/run/elyir-bench-bring/sda2"),
                        ("mount", "-t", "ext4", "-o", "ro,noload", "/dev/sda2", "/run/elyir-bench-bring/sda2")]
    assert seen[-1] == ("umount", "/run/elyir-bench-bring/sda2")
    seen.clear()
    with a.mounted({"dev": "sda1", "fstype": "vfat", "mountpoint": None}):
        pass
    assert seen[1] == ("mount", "-t", "vfat", "-o", "ro", "/dev/sda1", "/run/elyir-bench-bring/sda1")
    seen.clear()
    with a.mounted({"dev": "sdc", "fstype": "vfat", "mountpoint": "/media/pi/STICK"}) as mp:   # someone else's mount
        assert mp == Path("/media/pi/STICK")
    assert seen == []


def test_the_sudo_rule_mounts_a_card_only_read_only_where_bring_reads_it():
    rule = a.render_sudoers("pi")
    mounts = [ln for ln in rule.replace(", \\\n    ", "\n").splitlines() if "/mount " in ln]
    assert mounts and all(" -o ro" in ln and "/run/elyir-bench-bring/sd[a-z]" in ln for ln in mounts)
    assert "ro\\,noload" in rule                     # a comma in a sudoers command is escaped
    assert "umount /run/elyir-bench-bring/sd[a-z][0-9]" in rule and "rw" not in " ".join(mounts)


# ── scan ─────────────────────────────────────────────────────────────────────

def test_scan_lists_the_old_card_by_its_own_name_and_unmounts_it(rig):
    facts, card, mounts = rig
    got = a.bring_scan(facts, {"printer_name": "Workshop"})
    src = got["sources"][0]
    when = int((card / "home/pi/printer_data/config/printer.cfg").stat().st_mtime)
    # printer.cfg, macros/start.cfg, moonraker.conf, the SAVE_CONFIG backup, KAMP/KAMP_Settings.cfg: not elyir-bench.conf,
    # not the link off the card, not .theme (hidden, still copied)
    assert src == {"id": "card-sda2", "kind": "card", "name": "Voron", "detail": "In a USB reader", "when": when,
                   "files": 5, "gcodes": 2, "history": 3, "boards": ["stm32f446xx", f"can {EBB}", ACE]}
    assert got["found"] == ["Main board · STM32F446 on USB", "Toolhead board · on CAN", "ACE Pro", "Camera"]
    assert mounts == [("mount", "sda2"), ("umount", "sda2")]
    cached = json.loads(a.BRING_CACHE.read_text())["sources"][0]
    assert cached["where"] == {"dev": "sda2", "dir": "home/pi/printer_data"}


def test_without_its_own_name_a_card_is_named_by_mainsail_then_its_hostname(rig, tmp_path):
    facts, card, _ = rig
    (card / "home/pi/printer_data/config/moonraker.conf").write_text("[server]\n")
    (card / "home/pi/printer_data/config/elyir-bench.conf").unlink()
    assert a.bring_scan(facts, {})["sources"][0]["name"] == "Voron 2.4 350"
    (card / "home/pi/printer_data/database" / a.DB_FILE).unlink()
    assert a.bring_scan(facts, {})["sources"][0]["name"] == "voron"


def test_links_on_a_card_read_as_the_cards_own_and_never_this_pis(tmp_path):
    card = tmp_path / "card"
    pdata = old_card(card)
    files = a.walk_files(card, pdata / "config", hidden=True, skip=a.bring_skip)
    assert files["KAMP/KAMP_Settings.cfg"] == card / "home/pi/Klipper-Adaptive-Meshing-Purging/Configuration/KAMP_Settings.cfg"
    assert not any(r.startswith("elsewhere") for r in files) and "elyir-bench.conf" not in files
    assert ".theme/custom.css" in files and ".theme/custom.css" not in a.walk_files(card, pdata / "config", False)


# ── plan: what comes over, and the boards ────────────────────────────────────

def test_plan_says_what_comes_over_and_that_the_boards_match(rig):
    facts, _, mounts = rig
    a.bring_scan(facts, {})
    plan = a.bring_plan(facts, "card-sda2")
    assert {k: plan[k] for k in ("id", "config", "history", "spools", "mainsail", "gcodes")} == {
        "id": "card-sda2", "config": 5, "history": 3, "spools": True, "mainsail": True,
        "gcodes": {"count": 2, "bytes": 660}}
    assert plan["boards"] == [
        {"name": "Main board", "chip": "stm32f446xx", "match": "same", "words": "STM32F446, same serial"},
        {"name": "Toolhead board", "can": EBB, "match": "same", "words": "Same CAN ID"},
        {"name": "ACE Pro", "match": "same", "words": "Found"}]
    assert mounts[-2:] == [("mount", "sda2"), ("umount", "sda2")]


def test_a_new_main_board_of_the_same_kind_is_changed_and_anything_else_isnt_found():
    boards = a.cfg_boards({"printer.cfg": PRINTER_CFG})
    here = dict(HERE, serial=[MAIN_NEW, ACE], can=[])
    got = {b["name"]: b for b in a.match_boards(boards, here)}
    assert got["Main board"]["match"] == "changed" and got["Main board"]["to"] == f"/dev/serial/by-id/{MAIN_NEW}"
    assert got["Main board"]["words"] == "The main board's serial differs: it will be set to the one plugged in"
    assert got["Toolhead board"] == {"name": "Toolhead board", "section": "mcu EBBCan", "file": "printer.cfg", "can": EBB,
                                     "match": "missing", "words": "Not found: plug it in, or it can be changed after"}
    # two of that kind plugged in: it can't tell which, so it changes nothing
    two = dict(here, serial=[MAIN_NEW, MAIN_NEW.replace("4400", "5500"), ACE])
    assert {b["name"]: b["match"] for b in a.match_boards(boards, two)}["Main board"] == "missing"


def test_can_that_cant_be_asked_is_not_checked_rather_than_missing():
    boards = a.cfg_boards({"printer.cfg": PRINTER_CFG})
    words = {b["name"]: (b["match"], b["words"]) for b in a.match_boards(boards, dict(HERE, can=None, can_ifaces=[]))}
    assert words["Toolhead board"] == ("unchecked", "Not checked: CAN isn't set up on this card yet")
    ready = {b["name"]: b["match"] for b in a.match_boards(boards, dict(HERE, can=[], klipper="ready"))}
    assert ready["Toolhead board"] == "unchecked"     # Klipper holds its boards: they don't answer the query


def test_klippers_can_query_is_read_when_can_is_up(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "HOME", tmp_path)
    (tmp_path / "klipper" / "scripts").mkdir(parents=True)
    (tmp_path / "klipper" / "scripts" / "canbus_query.py").write_text("")
    (tmp_path / "klippy-env" / "bin").mkdir(parents=True)
    (tmp_path / "klippy-env" / "bin" / "python").write_text("")
    monkeypatch.setattr(a, "read", lambda p, default="": "up\n" if str(p).endswith("can0/operstate") else "down\n")

    class P:
        returncode = 0
        stdout = f"Found canbus_uuid={EBB}, Application: Klipper\nTotal 1 uuids found\n"
    monkeypatch.setattr(a, "run", lambda cmd, **kw: P())
    assert a.can_query(["can0"]) == [EBB]
    assert a.can_query(["can1"]) is None


def test_sections_klipper_here_has_no_module_for_are_named(tmp_path):
    extras = tmp_path / "klippy" / "extras"
    extras.mkdir(parents=True)
    for m in ("gcode_macro.py", "heater_bed.py"):
        (extras / m).write_text("")
    texts = {"printer.cfg": PRINTER_CFG.replace("[printer]", "[heater_bed]\n[led_effect sb]\n[printer]"),
             "macros/start.cfg": "[gcode_macro A]\n",
             "unused.cfg": "[beacon]\n"}
    assert a.cfg_needs(texts, tmp_path / "klippy") == ["ace", "led_effect"]   # unused.cfg isn't included


def test_a_serial_is_changed_in_its_own_section_only():
    text = PRINTER_CFG
    new = a.render_serial(text, "mcu", f"/dev/serial/by-id/{MAIN_NEW}")
    assert f"serial: /dev/serial/by-id/{MAIN_NEW}   # the Octopus\n" in new
    assert new.replace(MAIN_NEW, MAIN) == text        # nothing else, and not the SAVE_CONFIG block


# ── this printer's Moonraker, and another's ──────────────────────────────────

class FakeMoonraker:
    """A Moonraker over HTTP, as much as bring uses: this printer's own (backup, restore, restart, Klipper's state)
    or another printer's (its files, history and database, and Elyir Bench's export when `bench`)."""

    def __init__(self, pdata: Path | None = None, files: dict | None = None, gcodes: dict | None = None,
                 bench: bool = False, refuse_restore: bool = False, history: int = 7, namespaces=None,
                 old_release: bool = False, klipper_version: str = "v0.13.0-268-gf52a6f94"):
        self.pdata, self.files, self.gcodes, self.bench = pdata, files or {}, gcodes or {}, bench
        # an Elyir Bench printer on a release from before Bring it over (Studio on 6 October 2026): its component
        # answers, but it has neither /printer/intent/bring nor the export
        self.old_release, self.klipper_version = old_release, klipper_version
        self.refuse_restore, self.history = refuse_restore, history
        self.namespaces = namespaces if namespaces is not None else {"mainsail": {"general": {"printername": "Studio"}},
                                                                     "spoolman": {"x": 1}, "moonraker": {"a": 1}}
        self.posts, self.restored, self.klipper = [], None, ["error", "startup", "ready"]
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, raw=None):
                b = raw if raw is not None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                path = urllib.parse.unquote(u.path)
                if path == "/server/info":
                    return self._send(200, {"result": {"klippy_state": "ready"}})
                if path == "/printer/info":
                    state = outer.klipper.pop(0) if len(outer.klipper) > 1 else outer.klipper[0]
                    msg = "Section 'ace' is not a valid config section\nOnce the underlying issue is corrected..." \
                        if state == "error" else ""
                    return self._send(200, {"result": {"state": state, "state_message": msg, "hostname": "studio",
                                                       "software_version": outer.klipper_version}})
                if path == "/server/files/list":
                    src = outer.files if q.get("root") == "config" else outer.gcodes
                    return self._send(200, {"result": [{"path": p, "modified": 1791000000.0, "size": len(v)}
                                                       for p, v in src.items()]})
                for root, src in (("config", outer.files), ("gcodes", outer.gcodes)):
                    if path.startswith(f"/server/files/{root}/"):
                        rel = path[len(f"/server/files/{root}/"):]
                        return self._send(200, None, raw=src[rel].encode()) if rel in src else self._send(404, {})
                if path == "/server/history/list":                       # a page: count is how many it holds
                    return self._send(200, {"result": {"count": min(outer.history, int(q.get("limit", 50))), "jobs": []}})
                if path == "/server/history/totals":
                    return self._send(200, {"result": {"job_totals": {"total_jobs": float(outer.history)}}})
                if path == "/server/database/list":
                    return self._send(200, {"result": {"namespaces": list(outer.namespaces), "backups": []}})
                if path == "/server/database/item":
                    return self._send(200, {"result": {"namespace": q["namespace"], "key": None,
                                                       "value": outer.namespaces.get(q["namespace"], {})}})
                if path == "/printer/intent" and (outer.bench or outer.old_release):
                    return self._send(200, {"result": {"printer": {"name": "Studio"}}})
                if path == "/printer/intent/bring" and outer.bench:
                    return self._send(200, {"result": {"state": "idle", "sources": []}})
                if path == "/printer/intent/bring/export" and outer.bench:
                    import base64, tempfile
                    with tempfile.TemporaryDirectory() as d:
                        make_db(Path(d) / "x.db", prints=outer.history)
                        data = (Path(d) / "x.db").read_bytes()
                    return self._send(200, {"result": {"database": base64.b64encode(data).decode()}})
                self._send(404, {"error": {"message": "Not Found"}})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                args = json.loads(body or b"{}")
                path = urllib.parse.urlparse(self.path).path
                outer.posts.append((self.path, args))
                if path == "/server/database/backup":
                    folder = outer.pdata / "backup" / "database"
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / args["filename"]).write_bytes(b"this card's database")
                    return self._send(200, {"result": {"backup_path": str(folder / args["filename"])}})
                if path == "/server/database/restore":
                    f = outer.pdata / "backup" / "database" / args["filename"]
                    if outer.refuse_restore or not f.is_file():
                        return self._send(400, {"error": {"message": "Invalid database for restoration"}})
                    outer.restored = f.read_bytes()
                    return self._send(200, {"result": {"restored_tables": [], "restored_namespaces": []}})
                self._send(200, {"result": "ok"})

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"


def posted(fake, path):
    return [args for p, args in fake.posts if p.split("?")[0] == path]


def apply(facts, sid, gcodes=False):
    return a.bring_apply(facts, a.default_settings(facts), sid, gcodes, True)


# ── apply ────────────────────────────────────────────────────────────────────

def test_apply_brings_the_card_over_and_keeps_what_was_here(rig, tmp_path, capsys, monkeypatch):
    facts, card, mounts = rig
    pdata = Path(facts["printer_data"])
    local = FakeMoonraker(pdata)
    local.klipper = ["error", "startup", "error"]
    facts["moonraker"]["url"] = local.url
    a.bring_scan(facts, {})
    monkeypatch.setattr(a, "bring_here", lambda f: dict(HERE, serial=[MAIN_NEW, ACE]))   # a new main board
    capsys.readouterr()
    got = apply(facts, "card-sda2", gcodes=True)
    assert got == {"klipper": "error", "message": "Section 'ace' is not a valid config section"}
    kept = next(pdata.glob("config-before-bring-*"))
    assert sorted(p.name for p in kept.iterdir()) == ["elyir-bench.conf", "moonraker.conf"]
    cfg = pdata / "config"
    assert (cfg / "elyir-bench.conf").read_text() == (kept / "elyir-bench.conf").read_text()      # never the old one's
    assert "relay.example" not in "".join(p.read_text() for p in cfg.rglob("*") if p.is_file())
    mr = (cfg / "moonraker.conf").read_text()
    assert "printer_name: Workshop" in mr and "printer_name: Voron" not in mr and "[spoolman]" in mr
    assert mr.count("[printer_intent]") == 1
    printer = (cfg / "printer.cfg").read_text()
    assert f"serial: /dev/serial/by-id/{MAIN_NEW}   # the Octopus" in printer and f"canbus_uuid: {EBB}" in printer
    assert (cfg / "KAMP" / "KAMP_Settings.cfg").is_file() and not (cfg / "KAMP").is_symlink()   # copied as files
    assert (cfg / ".theme" / "custom.css").is_file() and not (cfg / "elsewhere").exists()
    assert (pdata / "gcodes" / "cube.gcode").read_text() == "mine\n"          # what's here is never overwritten
    assert (pdata / "gcodes" / "benchy.gcode").is_file()
    # the database: this one backed up first, then the card's restored through Moonraker, cleaned of its logins
    assert posted(local, "/server/database/backup")[0]["filename"].startswith("elyir-bench-before-bring-")
    restore = posted(local, "/server/database/restore")[0]["filename"]
    assert restore.startswith("elyir-bench-bring-") and not (pdata / "backup" / "database" / restore).exists()
    db = tmp_path / "restored.db"
    db.write_bytes(local.restored)
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM job_history").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM authorized_users").fetchone()[0] == 0
    assert ("elyir-bench", "phones") not in set(con.execute("SELECT namespace, key FROM namespace_store"))
    con.close()
    assert posted(local, "/machine/services/restart") and mounts[-1] == ("umount", "sda2")
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert [ln["progress"]["step"] for ln in lines] == [
        "Reading Voron's setup", "Copying your files", "Keeping your current config", "Matching the boards",
        "Bringing history and settings", "Starting Klipper"]
    assert [ln["progress"]["done"] for ln in lines] == [0, 1, 2, 3, 4, 5] and lines[0]["progress"]["of"] == 6


def test_gcodes_come_only_when_asked_and_a_ready_klipper_is_said(rig):
    facts, _, _ = rig
    pdata = Path(facts["printer_data"])
    local = FakeMoonraker(pdata)
    local.klipper = ["error", "startup", "ready"]
    facts["moonraker"]["url"] = local.url
    a.bring_scan(facts, {})
    assert apply(facts, "card-sda2") == {"klipper": "ready", "message": "Klipper started with it."}
    assert not (pdata / "gcodes" / "benchy.gcode").exists()


def test_a_failure_puts_the_config_that_was_here_back(rig):
    facts, _, _ = rig
    pdata = Path(facts["printer_data"])
    before = {p.relative_to(pdata): p.read_bytes() for p in pdata.rglob("*") if p.is_file()}
    local = FakeMoonraker(pdata, refuse_restore=True)
    facts["moonraker"]["url"] = local.url
    a.bring_scan(facts, {})
    with pytest.raises(a.StepFailed) as e:
        apply(facts, "card-sda2", gcodes=True)
    assert str(e.value) == ("Moonraker didn't take its history: Invalid database for restoration. "
                            "Nothing was changed: the config that was here is back.")
    after = {p.relative_to(pdata): p.read_bytes() for p in pdata.rglob("*") if p.is_file()
             if not str(p.relative_to(pdata)).startswith("backup")}
    assert after == before and not list(pdata.glob("config-before-bring-*"))
    assert not list((pdata / "backup" / "database").glob("elyir-bench-bring-*"))
    assert posted(local, "/server/restart")                  # Moonraker reads its own moonraker.conf again


def test_apply_is_refused_while_printing(rig, monkeypatch):
    facts, _, mounts = rig
    a.bring_scan(facts, {})
    facts["print_state"] = "printing"
    monkeypatch.setattr(a, "printing_now", lambda f: "cube.gcode, 42 %")
    with pytest.raises(a.StepFailed, match="Printing: cube.gcode, 42 %. Nothing was changed"):
        apply(facts, "card-sda2")
    assert not list(Path(facts["printer_data"]).glob("config-before-bring-*"))


def test_the_start_macro_comes_with_its_include(rig):
    facts, card, _ = rig
    cfg = card / "home/pi/printer_data/config/printer.cfg"
    cfg.write_text("[include elyir-bench.cfg]\n" + cfg.read_text())
    local = FakeMoonraker(Path(facts["printer_data"]))
    facts["moonraker"]["url"] = local.url
    a.bring_scan(facts, {})
    apply(facts, "card-sda2")
    conf = (Path(facts["printer_data"]) / "config" / "elyir-bench.conf").read_text()
    assert "start_macro: on" in conf and "printer_name: Workshop" in conf


# ── another printer on the Wi-Fi ─────────────────────────────────────────────

STUDIO_FILES = {"printer.cfg": f"[mcu]\nserial: /dev/serial/by-id/{MAIN}\n", "moonraker.conf": "[server]\n",
                "macros.cfg": "[gcode_macro X]\n", "elyir-bench.conf": "[elyir-bench]\nrelay_api: https://secret\n"}


def mdns_printer(port: int, name: str = "Studio", host: str = "studio.local") -> list:
    """What _dns_records reads from avahi's answer for _elyir-printer._tcp (installer Announce)."""
    inst = f"{name}._elyir-printer._tcp.local"
    return [("_elyir-printer._tcp.local", 12, inst), (inst, 33, (host, 8088)),
            (inst, 16, {"name": name, "id": name.lower(), "door": "1", "moonraker": str(port), "v": "1"}),
            (host, 1, "127.0.0.1")]


def test_another_elyir_bench_printer_on_the_wifi_is_listed_and_brought(rig, monkeypatch, tmp_path):
    facts, _, _ = rig
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    studio = FakeMoonraker(files=STUDIO_FILES, gcodes={"a.gcode": "G1\n", ".thumbs/a.png": "x"}, bench=True, history=12)
    me = FakeMoonraker(files={})   # this printer announces itself too, and is never listed
    monkeypatch.setattr(a, "mdns_ask", lambda service, timeout=2.0:
                        mdns_printer(studio.port) + mdns_printer(me.port, "Workshop", "workshop.local"))
    got = a.bring_scan(facts, {"printer_name": "Workshop"})
    sid = f"printer-studio-local-{studio.port}"
    assert got["sources"] == [{"id": sid, "kind": "printer", "name": "Studio",
                               "detail": "Elyir Bench, on your Wi-Fi", "when": 1791000000, "files": 3, "gcodes": 1,
                               "history": 12, "boards": ["stm32f446xx"]}]
    plan = a.bring_plan(facts, sid)
    assert (plan["config"], plan["history"], plan["spools"], plan["mainsail"], plan["notes"]) == (3, 12, True, True, [])
    local = FakeMoonraker(Path(facts["printer_data"]))
    facts["moonraker"]["url"] = local.url
    apply(facts, sid)
    cfg = Path(facts["printer_data"]) / "config"
    assert sorted(p.name for p in cfg.iterdir()) == ["elyir-bench.conf", "macros.cfg", "moonraker.conf", "printer.cfg"]
    assert "secret" not in (cfg / "elyir-bench.conf").read_text() and local.restored
    assert not any(p.startswith("/server/database/") and p != "/server/database/item" for p, _ in studio.posts)


def test_any_moonraker_by_address_brings_its_settings_but_not_its_history(rig, monkeypatch):
    facts, _, _ = rig
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    other = FakeMoonraker(files=STUDIO_FILES, history=40)
    got = a.bring_address(facts, f"http://127.0.0.1:{other.port}/")
    assert got["source"]["id"] == f"printer-127-0-0-1-{other.port}" and got["source"]["name"] == "studio"
    assert got["plan"]["history"] is None and got["plan"]["mainsail"] is True
    assert got["plan"]["notes"] == ["Its history stays there: only a printer with Elyir Bench can send it."]
    # remembered: the next scan reads it again
    assert [s["id"] for s in a.bring_scan(facts, {})["sources"]] == [got["source"]["id"]]
    local = FakeMoonraker(Path(facts["printer_data"]))
    facts["moonraker"]["url"] = local.url
    apply(facts, got["source"]["id"])
    items = posted(local, "/server/database/item")
    assert {(i["namespace"], i["key"]) for i in items} == {("mainsail", "general"), ("spoolman", "x")}
    assert not posted(local, "/server/database/restore") and posted(local, "/server/restart")


def test_an_address_where_nothing_answers_is_said_in_words(rig):
    facts, _, _ = rig
    with pytest.raises(a.StepFailed, match="Nothing answers at 127.0.0.1:9. Is that printer on"):
        a.bring_address(facts, "127.0.0.1:9")
    with pytest.raises(a.StepFailed, match="isn't an address"):
        a.bring_address(facts, "not an address!")


# ── a backup file ────────────────────────────────────────────────────────────

def test_a_backup_file_from_a_phone_is_listed_and_brought(rig, monkeypatch, tmp_path):
    facts, card, _ = rig
    monkeypatch.setattr(a, "usb_partitions", lambda: [])
    folder = Path(facts["printer_data"]) / "config" / a.BRING_FOLDER
    folder.mkdir()
    pdata = card / "home/pi/printer_data"
    with zipfile.ZipFile(folder / "voron-backup.zip", "w") as z:
        for p in sorted(pdata.rglob("*")):
            if p.is_file() and not p.is_symlink() and "KAMP" not in str(p) and "elsewhere" not in str(p):
                z.write(p, f"printer_data/{p.relative_to(pdata)}")
    with tarfile.open(folder / "kiauh-config.tar.gz", "w:gz") as t:
        t.add(pdata / "config" / "printer.cfg", "klipper_config/printer.cfg")
        t.add(pdata / "config" / "macros", "klipper_config/macros")
    got = {s["id"]: s for s in a.bring_scan(facts, {})["sources"]}
    z = got["file-voron-backup-zip"]
    assert (z["kind"], z["name"], z["detail"], z["files"], z["gcodes"], z["history"]) == (
        "file", "Voron", "A backup file", 4, 2, 3)
    t = got["file-kiauh-config-tar-gz"]
    assert (t["name"], t["files"], t["gcodes"], t["history"]) == ("kiauh-config", 2, 0, None)
    local = FakeMoonraker(Path(facts["printer_data"]))
    facts["moonraker"]["url"] = local.url
    apply(facts, "file-voron-backup-zip", gcodes=True)
    new = Path(facts["printer_data"])
    assert (new / "config" / "macros" / "start.cfg").is_file() and (new / "gcodes" / "benchy.gcode").is_file()
    assert local.restored and not (new / "config" / a.BRING_FOLDER).exists()
    assert (next(new.glob("config-before-bring-*")) / a.BRING_FOLDER / "voron-backup.zip").is_file()


def test_a_backup_never_unpacks_outside_its_own_folder(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as t:
        for name, data in (("config/printer.cfg", b"[printer]\n"), ("../../evil.cfg", b"x"), ("config/../../evil2", b"x")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("config/passwd")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(link)
    src = a.ArchiveSource(bad)
    try:
        assert sorted(src.config_files()) == ["printer.cfg"]
        assert not list(tmp_path.glob("**/evil*"))
    finally:
        src.close()
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("notes.txt", "x")
    with pytest.raises(a.StepFailed, match="has no printer.cfg in it"):
        a.ArchiveSource(empty)


# ── the command ──────────────────────────────────────────────────────────────

def test_the_command_says_each_step_and_ends_on_one_answer(rig, capsys, monkeypatch):
    facts, _, _ = rig
    args = a.argparse.Namespace(json=True, what="scan")
    assert a.bring_main(args, facts, {}) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["sources"][0]["id"] == "card-sda2"
    args = a.argparse.Namespace(json=True, what="plan", id="card-nope")
    assert a.bring_main(args, facts, {}) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == {"failed": "That isn't one it found. Look again first."}
    monkeypatch.setattr(a, "bring_apply", lambda *x: {"klipper": "ready", "message": "Klipper started with it."})
    args = a.argparse.Namespace(json=True, what="apply", id="card-sda2", gcodes=False)
    assert a.bring_main(args, facts, {}) == 0
    out = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert out[0] == {"started": "apply", "pid": os.getpid()}
    assert out[-1] == {"result": {"klipper": "ready", "message": "Klipper started with it."}}


def test_an_older_elyir_bench_printer_brings_its_settings_and_says_its_history_stays(rig, monkeypatch):
    # desk.local, 6 October 2026: Studio (a release from before Bring it over) answered /printer/intent but had no
    # export, so nothing of its database came over and the plan said history: 1
    old = FakeMoonraker(files={"printer.cfg": "[printer]\nkinematics: corexy\n"}, old_release=True, history=463,
                        klipper_version="v0.13.0-310-g461c4e37")
    src = a.PrinterSource(old.url, "studio.local")
    assert not src.bench()
    assert src.items() and "mainsail" in src.items()               # the settings, key by key
    monkeypatch.setattr(a, "local_klipper_version", lambda: "v0.13.0-268-gf52a6f94")
    plan = a.plan_of(src, "printer-studio-local", {"serial": [], "can": None})
    assert plan["history"] is None and plan["mainsail"] is True
    assert any("history stays there" in n for n in plan["notes"])
    assert any("runs Klipper v0.13.0-310-g461c4e37" in n and "v0.13.0-268-gf52a6f94" in n for n in plan["notes"])
    old.server.shutdown()


def test_a_printer_with_bring_it_over_counts_all_its_prints(rig):
    new = FakeMoonraker(files={"printer.cfg": "[printer]\n"}, bench=True, history=463)
    src = a.PrinterSource(new.url, "studio.local")
    assert src.bench() and src.facts()["history"] == 463               # the total, not one page of the list
    new.server.shutdown()
