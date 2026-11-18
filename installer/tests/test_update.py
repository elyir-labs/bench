"""`elyir-bench update` (design/updates/, A + A): a newer signed release is installed by its own installer, never an older
one, never during a print, and a failed one leaves the printer on the version it had."""
import functools
import hashlib
import http.server
import io
import json
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# the release's own installer, as the updater runs it: --json apply <tarball>; switches current unless told to fail
STUB = '''import os, sys, tarfile
from pathlib import Path
base = Path(os.environ["ELYIR_BENCH_HOME"])
tarball = Path(sys.argv[-1])
if os.environ.get("STUB_FAIL"):
    sys.exit(1)
ver = tarfile.open(tarball).extractfile("VERSION").read().decode().strip()
dest = base / "releases" / ver
dest.mkdir(parents=True, exist_ok=True)
(dest / "VERSION").write_text(ver + "\\n")
tmp = base / ".current.tmp"
tmp.symlink_to(dest)
os.replace(tmp, base / "current")
print("[]")
'''


def test_the_installer_trusts_the_same_key_as_install_sh():
    pem = (ROOT / "install" / "release-key.pem").read_text().strip()
    assert a.RELEASE_KEY.strip() == pem
    assert pem in (ROOT / "install" / "install.sh").read_text()


@pytest.mark.parametrize("latest, have, built, newer", [
    ({"version": "2026.11.08-bbb"}, "2026.11.07-aaa", None, True),
    ({"version": "2026.11.06-bbb"}, "2026.11.07-aaa", None, False),
    ({"version": "2026.11.07-bbb"}, "2026.11.07-aaa", None, False),          # the same day, order unknown: stays
    ({"version": "2026.11.07-bbb", "built": 200}, "2026.11.07-aaa", 100, True),
    ({"version": "2026.11.07-bbb", "built": 100}, "2026.11.07-aaa", 200, False),
    ({"version": "2026.11.07-aaa"}, "2026.11.07-aaa", None, False),
    ({"version": "2026.11.08-bbb"}, None, None, True),
])
def test_never_older(latest, have, built, newer):
    assert a.is_newer(latest, have, built) is newer


@pytest.fixture
def rig(tmp_path, monkeypatch):
    base = tmp_path / "elyir-bench"
    (base / "releases" / "2026.11.07-aaa").mkdir(parents=True)
    (base / "releases" / "2026.11.07-aaa" / "VERSION").write_text("2026.11.07-aaa\n")
    (base / "current").symlink_to(base / "releases" / "2026.11.07-aaa")
    for name, value in (("BASE", base), ("CURRENT", base / "current"), ("RELEASES", base / "releases"),
                        ("STATE", base / "state.json"), ("UPDATE_FILE", base / "update.json"),
                        ("UPDATE_ASKED", base / "update-now"), ("INCOMING", base / "incoming")):
        monkeypatch.setattr(a, name, value)
    monkeypatch.setenv("ELYIR_BENCH_HOME", str(base))

    key, pub = tmp_path / "key.pem", tmp_path / "pub.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)], check=True)
    subprocess.run(["openssl", "ec", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    monkeypatch.setattr(a, "RELEASE_KEY", pub.read_text())

    site = tmp_path / "site"
    site.mkdir()

    def publish(version, built=None, signed_by=key, installer=None):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            mine = Path(a.__file__).stem
            for name, text in (("VERSION", version + "\n"), (f"installer/{installer or mine}.py", STUB), (f"installer/{mine}_os.py", "")):
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        file = f"elyir-bench-{version}.tar.gz"
        (site / file).write_bytes(buf.getvalue())
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(signed_by), "-out", str(site / (file + ".sig")),
                        str(site / file)], check=True)
        (site / "latest.json").write_text(json.dumps({"version": version, "file": file, "signature": file + ".sig",
                                                      "sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "built": built}))

    class Like(http.server.SimpleHTTPRequestHandler):
        """Like releases.elyir.dev behind Cloudflare: Python's own User-Agent is refused."""
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.headers.get("User-Agent", "").startswith("Python-urllib"):
                self.send_error(403)
                return
            super().do_GET()

    handler = functools.partial(Like, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(a, "RELEASES_URL", f"http://127.0.0.1:{server.server_address[1]}")
    yield base, publish, tmp_path
    server.shutdown()


FACTS = {"print_state": "standby", "moonraker": {"service": True, "url": "http://127.0.0.1:9"}}
S = {"role": "printer", "port": 80}


def update(base):
    return json.loads((base / "update.json").read_text())


def test_a_newer_release_is_installed_by_its_own_installer(rig):
    base, publish, _ = rig
    publish("2026.11.08-bbb")
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 0
    assert a.current_version() == "2026.11.08-bbb"
    u = update(base)
    assert u["state"] == "done" and u["previous"] == "2026.11.07-aaa" and u["latest"]["version"] == "2026.11.08-bbb"
    assert u["newer"] is False


def test_nothing_newer_says_so(rig):
    base, publish, _ = rig
    publish("2026.11.07-aaa")
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 0
    assert update(base)["state"] == "idle" and update(base)["newer"] is False


def test_not_during_a_print(rig):
    base, publish, _ = rig
    publish("2026.11.08-bbb")
    assert a.update_main({**FACTS, "print_state": "printing"}, S, nightly=False, as_json=True) == 3
    u = update(base)
    assert u["state"] == "waiting" and u["why"] == "It's printing." and u["newer"] is True
    assert a.current_version() == "2026.11.07-aaa"


def test_one_not_signed_by_elyir_is_never_installed(rig):
    base, publish, tmp = rig
    other = tmp / "other.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(other)], check=True)
    publish("2026.11.08-bbb", signed_by=other)
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 1
    u = update(base)
    assert u["state"] == "failed" and "isn't signed by Elyir" in u["why"]
    assert a.current_version() == "2026.11.07-aaa" and not list((base / "incoming").glob("*.tar.gz"))


def test_a_failed_install_stays_on_the_version_it_had(rig, monkeypatch):
    base, publish, _ = rig
    publish("2026.11.08-bbb")
    monkeypatch.setenv("STUB_FAIL", "1")
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 1
    u = update(base)
    assert u["state"] == "failed" and u["went_back"] is True and a.current_version() == "2026.11.07-aaa"


def test_update_now_is_not_the_nightly_run(rig, monkeypatch):
    base, publish, _ = rig
    publish("2026.11.08-bbb")
    (base / "update-now").touch()
    seen = []
    monkeypatch.setattr(a, "update_busy", lambda f, s, nightly: seen.append(nightly) or None)
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 0
    assert seen == [False] and not (base / "update-now").exists()


def test_the_box_waits_for_a_kobra_it_speaks_for(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "DOOR_STATE", tmp_path)
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "printers.json").write_text(json.dumps({
        "obi": {"name": "Workshop"}, "anycubic-1": {"name": "Kobra 3", "standin": {"printer": "10.0.0.2"}}}))
    intents = {"obi": {"state": "printing"}, "anycubic-1": {"state": "ready"}}
    monkeypatch.setattr(a, "http_json", lambda url, timeout=4: intents)
    box = ({"moonraker": {"service": False}}, {"role": "auto", "port": 8088})
    assert a.update_busy(*box, nightly=True) is None, "a printer with its own screens isn't the box's to wait for"
    intents["anycubic-1"] = {"state": "printing"}
    assert a.update_busy(*box, nightly=False) == "Kobra 3 is printing."


def test_the_units_run_the_current_installer_at_night():
    units = a.render_update_units({"user": "pi"})
    assert "update --nightly" in units["elyir-bench-update.service"] and "User=pi" in units["elyir-bench-update.service"]
    assert "OnCalendar=*-*-* 03:00:00" in units["elyir-bench-update.timer"]


def test_a_developer_build_never_takes_a_public_release(rig):
    base, publish, _ = rig
    publish("2026.11.08-bbb", installer="someone_else")
    assert a.update_main(FACTS, S, nightly=True, as_json=True) == 0
    u = update(base)
    assert u["state"] == "idle" and u["newer"] is False and "developer build" in u["why"]
    assert a.current_version() == "2026.11.07-aaa"
