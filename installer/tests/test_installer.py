import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402


def out(connector, connected=True, touch=False):
    return {"connector": connector, "connected": connected, "panel_touch": touch, "mode": "800x480"}


def test_single_connected_output_wins():
    assert a.choose_output([out("DSI-1"), out("HDMI-A-1", connected=False)], [])[0] == "DSI-1"


def test_phantom_dsi_is_skipped_by_touch_bus():
    # workshop: display_auto_detect plus an explicit 7inch overlay gives two "connected" DSI panels
    touch = [{"name": "ft5x06", "i2c_buses": [10], "usb": False}]
    got, why = a.choose_output([out("DSI-1", touch=True), out("DSI-2")], touch)
    assert got == "DSI-1" and "i2c" in why


def test_hdmi_with_usb_touch():
    touch = [{"name": "usb touch", "i2c_buses": [], "usb": True}]
    assert a.choose_output([out("HDMI-A-1"), out("DSI-1")], touch)[0] == "HDMI-A-1"


def test_ambiguous_returns_none():
    got, why = a.choose_output([out("DSI-1"), out("DSI-2")], [])
    assert got is None and "2 outputs" in why


def test_no_display():
    assert a.choose_output([out("HDMI-A-1", connected=False)], [])[0] is None


def test_kiosk_installable_flags_missing_candidates(monkeypatch):
    policy = (
        "cage:\n  Installed: (none)\n  Candidate: (none)\n"
        "chromium:\n  Installed: (none)\n  Candidate: 106.0-1\n"
    )

    class P:
        stdout = policy

    monkeypatch.setattr(a, "run", lambda *args, **kw: P())
    # wlr-randr isn't mentioned at all: apt doesn't know it
    assert a.kiosk_installable(["cage", "chromium", "wlr-randr"]) == ["cage", "wlr-randr"]


def test_sudoers_rule_is_narrow():
    rule = a.render_sudoers("pi")
    assert rule.count("NOPASSWD") == 1 and "ALL=(root) NOPASSWD: ALL" not in rule
    assert "restart moonraker" in rule and "elyir-bench-kiosk.service" in rule


def test_intent_section_uses_settings_name():
    facts = {"host": "studio"}
    text = a.render_intent_section(facts, {"printer_name": "Studio"})
    assert "[printer_intent]" in text and "printer_name: Studio" in text and "http://studio.local/" in text


def test_rotation_from_inverted_touch(monkeypatch, tmp_path):
    cfg = tmp_path / "config.txt"
    cfg.write_text("[all]\n# dtoverlay=vc4-kms-dsi-7inch\ndtoverlay=vc4-kms-dsi-7inch,invx,invy\n")
    monkeypatch.setattr(a, "read", lambda p, default="": cfg.read_text() if p.endswith("firmware/config.txt") else "")
    assert a.detect_rotation()[0] == 180


def test_no_rotation_without_overlay(monkeypatch):
    monkeypatch.setattr(a, "read", lambda p, default="": "display_auto_detect=1\n")
    assert a.detect_rotation()[0] == 0


def test_kiosk_unit_carries_rotation():
    facts = {"user": "pi", "uid": 1000, "panel_rotation": 180, "printer_data": None}
    unit = a.render_kiosk_unit(facts, {"port": "8088", "panel_rotation": "auto"}, "DSI-1")
    assert "ELYIR_BENCH_ROTATION=180" in unit and "ELYIR_BENCH_OUTPUT=DSI-1" in unit
    unit = a.render_kiosk_unit(facts, {"port": "8088", "panel_rotation": "0"}, "DSI-1")
    assert "ELYIR_BENCH_ROTATION=0" in unit


def test_kiosk_unit_takes_over_from_the_boot_eye():
    # With the boot eye on, cage starts on Plymouth's VT and quits Plymouth itself, leaving its frame,
    # instead of waiting for Plymouth to quit and switching to an empty VT (a black panel for seconds)
    facts = {"user": "pi", "uid": 1000, "panel_rotation": 0, "printer_data": None, "model": "Raspberry Pi 5 Model B Rev 1.0"}
    unit = a.render_kiosk_unit(facts, {"port": "8088", "panel": "elyir-bench"}, "DSI-1")
    assert "ExecStartPre=+-/usr/bin/plymouth quit --retain-splash" in unit
    assert unit.index("plymouth quit") < unit.index("chvt 1")
    assert "TTYPath=/dev/tty1" in unit and "Conflicts=getty@tty1.service" in unit
    assert "plymouth-quit-wait" not in unit
    assert "TTYReset=no" in unit and "TTYVTDisallocate=no" in unit
    assert "After=elyir-bench-kiosk.service" in a.PLYMOUTH_QUIT_CONF
    # boot_screen: off, or not a Pi: the Pi's own boot text, and the kiosk on tty7 after Plymouth as before
    for f, s in ((facts, {"port": "8088", "panel": "elyir-bench", "boot_screen": "off"}),
                 ({**facts, "model": "BTT CB1"}, {"port": "8088", "panel": "elyir-bench"})):
        unit = a.render_kiosk_unit(f, s, "DSI-1")
        assert "plymouth quit" not in unit and "plymouth-quit-wait.service" in unit
        assert "TTYPath=/dev/tty7" in unit and "chvt 7" in unit and "TTYReset=yes" in unit


def test_nginx_site_proxies_the_cameras():
    # The app on its own port must reach /webcam/ like Mainsail does, or Now can't show the camera.
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}, "printer_data": None}
    site = a.render_nginx(facts, {"port": "8088"})
    assert "location /webcam/ {" in site and "proxy_pass http://127.0.0.1:8080/;" in site
    assert "location /webcam4/ {" in site and "proxy_pass http://127.0.0.1:8083/;" in site
    assert "proxy_buffering off;" in site          # MJPEG must stream, not buffer
    assert site.count("{") == site.count("}")      # still a well-formed block
# ── boot screen ──────────────────────────────────────────────────────────────

WORKSHOP_CMDLINE = ("console=serial0,115200 console=tty1 root=PARTUUID=834258bb-02 rootfstype=ext4 "
                "fsck.repair=yes rootwait cfg80211.ieee80211_regdom=US")


def test_cmdline_on_keeps_every_token_in_place():
    on = a.render_cmdline(WORKSHOP_CMDLINE, True)
    assert on.endswith("\n") and on.count("\n") == 1          # the firmware reads one line
    toks = on.split()
    assert toks[:7] == ["console=serial0,115200", "console=tty3", "root=PARTUUID=834258bb-02",
                        "rootfstype=ext4", "fsck.repair=yes", "rootwait", "cfg80211.ieee80211_regdom=US"]
    assert "console=tty1" not in toks and "quiet" in toks and "splash" in toks


def test_cmdline_on_is_idempotent():
    once = a.render_cmdline(WORKSHOP_CMDLINE, True)
    assert a.render_cmdline(once, True) == once


def test_cmdline_off_gives_back_the_original():
    on = a.render_cmdline(WORKSHOP_CMDLINE, True)
    assert a.render_cmdline(on, False, WORKSHOP_CMDLINE + "\n") == WORKSHOP_CMDLINE + "\n"


def test_cmdline_tells_the_kernel_an_upside_down_panel_so_plymouth_draws_upright():
    flip = a.orientation_arg("DSI-1", 180)
    assert flip == "video=DSI-1:panel_orientation=upside_down"
    assert a.orientation_arg("DSI-1", 0) is None and a.orientation_arg("DSI-1", 90) is None
    assert a.orientation_arg("auto", 180) is None and a.orientation_arg(None, 180) is None
    on = a.render_cmdline(WORKSHOP_CMDLINE, True, None, flip)
    assert on.split().count(flip) == 1 and on.count("\n") == 1
    assert a.render_cmdline(on, True, WORKSHOP_CMDLINE, flip) == on                       # idempotent
    assert flip not in a.render_cmdline(on, True, WORKSHOP_CMDLINE).split()               # turned back to 0
    assert a.render_cmdline(on, False, WORKSHOP_CMDLINE + "\n") == WORKSHOP_CMDLINE + "\n"   # boot screen off
    # an orientation the person set for that output stays theirs, and ours isn't added beside it
    theirs = WORKSHOP_CMDLINE + " video=DSI-1:panel_orientation=right_side_up"
    on = a.render_cmdline(theirs, True, theirs, flip)
    assert "video=DSI-1:panel_orientation=right_side_up" in on.split() and flip not in on.split()
    assert a.render_cmdline(on, False, theirs).split() == theirs.split()


def test_cmdline_off_keeps_what_the_person_had_before():
    theirs = WORKSHOP_CMDLINE.replace("console=tty1", "console=tty3") + " quiet"
    on = a.render_cmdline(theirs, True)
    off = a.render_cmdline(on, False, theirs)
    assert off.split() == theirs.split()


def test_config_txt_block_round_trips():
    cfg = "dtparam=audio=on\n\n[all]\nenable_uart=1\n"
    on = a.render_config_txt(cfg, True)
    assert on.endswith(a.SPLASH_BLOCK) and a.render_config_txt(on, True) == on
    assert a.render_config_txt(on, False).rstrip("\n") == cfg.rstrip("\n")


def test_config_txt_left_alone_when_splash_already_off():
    cfg = "disable_splash=1\n"
    assert a.render_config_txt(cfg, True) == cfg


def test_sudoers_covers_the_boot_screen():
    rule = a.render_sudoers("pi")
    for needle in ("update-initramfs -u", "plymouth-set-default-theme elyir-bench", "/boot/firmware/cmdline.txt",
                   "getty@tty1.service", a.PLYMOUTH_QUIT_DROPIN):
        assert needle in rule


def test_boot_screen_needs_the_elyir_bench_panel():
    step = a.BootScreen()
    c = a.Ctx({}, {"panel": "klipperscreen", "boot_screen": "elyir-bench"})
    assert not step._on(c)
    c = a.Ctx({}, {"panel": "elyir-bench", "boot_screen": "off"})
    assert not step._on(c)
    c = a.Ctx({}, {"panel": "elyir-bench"})
    assert step._on(c)


def test_default_theme_is_read_from_sbin(monkeypatch):
    # The printer user's PATH has no /usr/sbin; a bare name fails there (found on workshop).
    seen = []
    monkeypatch.setattr(a, "run", lambda cmd, check=True, timeout=600: seen.append(cmd) or
                        type("P", (), {"stdout": "elyir-bench\n", "returncode": 0})())
    monkeypatch.setattr(a.os, "access", lambda p, m: p == "/usr/sbin/plymouth-set-default-theme")
    assert a.BootScreen._default_theme() == "elyir-bench"
    assert seen[0][0] == "/usr/sbin/plymouth-set-default-theme"


def test_a_new_release_restarts_the_door(monkeypatch, tmp_path):
    # Found on workshop and studio: after a release switch nothing on disk differed, so the door kept
    # running the previous release's code until something else restarted it.
    calls = []
    monkeypatch.setattr(a, "door_address", lambda s: "workshop.elyir.app")
    monkeypatch.setattr(a.DoorServices, "_want", lambda self, c: {})
    monkeypatch.setattr(a, "is_enabled", lambda u: True)
    monkeypatch.setattr(a, "is_active", lambda u: True)
    monkeypatch.setattr(a, "door_has_certificate", lambda addr: True)
    monkeypatch.setattr(a, "current_home", lambda: "192-0-2-73.workshop.home.elyir.app")
    monkeypatch.setattr(a, "sudo", lambda *args, **kw: calls.append(args))
    monkeypatch.setattr(a, "DOOR_CONF", tmp_path / "conf")
    step, c = a.DoorServices(), a.Ctx({}, {"remote": "relay", "remote_name": "workshop"})
    assert step.check(c)[0], "same release: nothing to do"
    c.switched_from = "2026.10.02-old"
    ok, why = step.check(c)
    assert not ok and "new release" in why
    step.apply(c)
    assert ("systemctl", "restart", "elyir-bench-door.service") in calls
    assert ("systemctl", "start", "elyir-bench-caddy.service") in calls, "Caddy and the tunnel keep running"
    assert step.check(c)[0], "restarted once, then satisfied"


DESK_INPUTS = """I: Bus=0003 Vendor=04d9 Product=8030 Version=0110
N: Name="BIQU BTT-HDMI5"
S: Sysfs=/devices/platform/soc/5311400.usb/usb8/8-1/8-1:1.0/0003:04D9:8030.0001/input/input1
B: ABS=261800000000003

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="vc4-hdmi-0"
S: Sysfs=/devices/platform/soc/fef00700.hdmi/rc/rc0/input0
B: ABS=1
"""


def test_hdmi_touchscreen_counts_as_touch(monkeypatch):
    # found on desk: the name says HDMI, which used to drop it with the Pi's CEC inputs
    monkeypatch.setattr(a, "read", lambda p, default="": DESK_INPUTS if p == "/proc/bus/input/devices" else default)
    monkeypatch.setattr(a, "_i2c_buses_of", lambda dev: set())
    assert a.detect_touch() == [{"name": "BIQU BTT-HDMI5", "i2c_buses": [], "usb": True}]


def test_kiosk_backend_prefers_cage_and_honours_the_setting():
    assert a.kiosk_backend({"kiosk_backends": ["cage", "x11"]}, {}) == "cage"
    assert a.kiosk_backend({"kiosk_backends": ["x11"]}, {"panel_backend": "auto"}) == "x11"
    assert a.kiosk_backend({"kiosk_backends": ["cage", "x11"]}, {"panel_backend": "x11"}) == "x11"
    assert a.kiosk_backend({"kiosk_backends": []}, {}) is None


def test_x11_kiosk_unit_skips_the_tty_session():
    facts = {"user": "biqu", "uid": 1000, "panel_rotation": 0, "printer_data": None, "kiosk_backends": ["x11"]}
    unit = a.render_kiosk_unit(facts, {"port": "8088", "panel_rotation": "auto"}, "HDMI-A-1")
    assert "ELYIR_BENCH_BACKEND=x11" in unit and "ELYIR_BENCH_OUTPUT=HDMI-A-1" in unit and "User=biqu" in unit
    assert "chvt" not in unit and "TTYPath" not in unit
    assert "Conflicts=KlipperScreen.service" in unit


def test_sudoers_covers_the_x_wrapper():
    assert f"tee {a.XWRAPPER}" in a.render_sudoers("biqu")


def test_boot_screen_is_raspberry_pi_only():
    step = a.BootScreen()
    assert not step._on(a.Ctx({"model": "BQ-H616"}, {"panel": "elyir-bench"}))
    assert step._on(a.Ctx({"model": "Raspberry Pi 5 Model B Rev 1.0"}, {"panel": "elyir-bench"}))


def test_apt_install_refreshes_the_lists_first(monkeypatch):
    calls = []
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: calls.append(cmd))
    a.apt_install("chromium")
    assert calls == [("apt-get", "update", "-q"), ("apt-get", "install", "-y", "-q", "--no-install-recommends", "chromium")]
    assert "apt-get update -q" in a.render_sudoers("biqu")


def test_render_is_cpu_off_a_raspberry_pi():
    assert a.kiosk_render({"model": "BQ-H616"}, {}) == "cpu"
    assert a.kiosk_render({"model": "Raspberry Pi 4 Model B Rev 1.5"}, {}) == "gpu"
    assert a.kiosk_render({"model": "BQ-H616"}, {"panel_render": "gpu"}) == "gpu"
    facts = {"user": "biqu", "uid": 1000, "panel_rotation": 0, "printer_data": None,
             "kiosk_backends": ["x11"], "model": "BQ-H616"}
    assert "ELYIR_BENCH_RENDER=cpu" in a.render_kiosk_unit(facts, {"port": "8088"}, "HDMI-A-1")


# ── Print a model: the slicing service (docs/slicer.md) ──────────────────────

def slicer_rig(tmp_path, monkeypatch, printer=True):
    pdata = tmp_path / "printer_data"
    home = pdata / "config" / "elyir-bench-slicer"
    (home / "presets").mkdir(parents=True)
    if printer:
        (home / "printer.json").write_text('{"machine": "Workshop", "process": "0.20mm Standard @Voron", '
                                           '"plate": "High Temp Plate", "tools": 8, "materials": {"PLA": "PLA @Voron"}}')
    monkeypatch.setattr(a, "SLICER_DIR", tmp_path / "elyir-bench" / "slicer")
    facts = {"user": "pi", "printer_data": str(pdata), "moonraker": {"url": "http://127.0.0.1:7125"}}
    return facts, {"printer_name": "Workshop", "port": "8088", "slicer": "on"}


def test_nginx_sends_slice_to_the_service_only_when_on():
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}, "printer_data": None}
    assert "location /slice" not in a.render_nginx(facts, {"port": "8088", "printer_name": "Workshop"})
    site = a.render_nginx(facts, {"port": "8088", "slicer": "on", "printer_name": "Workshop"})
    assert "location /slice {" in site and f"proxy_pass http://127.0.0.1:{a.SLICER_PORT};" in site
    assert "proxy_set_header X-Elyir-Bench-Printer workshop;" in site          # it sees only Workshop, even when lending
    assert "error_page 502 504 = @slicer_down;" in site                  # words for the app, not nginx's page


def test_slicer_config_comes_from_printer_json_and_the_pinned_orca(tmp_path, monkeypatch):
    facts, s = slicer_rig(tmp_path, monkeypatch)
    conf = json.loads(a.render_slicer_config(facts, s))
    p = conf["printers"]["workshop"]
    assert p["name"] == "Workshop" and p["machine"] == "Workshop" and p["moonraker"] == "http://127.0.0.1:7125"
    assert conf["orca"].endswith(f"orca-{a.ORCA['version']}/bin/orca-slicer")
    assert p["presets"] == [str(Path(facts["printer_data"]) / "config" / "elyir-bench-slicer" / "presets")]  # theirs win
    assert p["home"] == str(Path(facts["printer_data"]) / "config" / "elyir-bench-slicer")   # read again when it changes
    assert conf["profiles"] == [str(a.orca_root() / "resources" / "profiles")]     # Orca's own, shared
    assert conf["lend"] is False
    assert "LD_LIBRARY_PATH" in conf["orca_env"]


def test_slicer_runs_before_printer_json_and_reads_it_itself(tmp_path, monkeypatch):
    """On a printer someone else set up, the intent layer writes printer.json from their own files later
    (docs/slicer-profile.md): the service runs without it and reads it from the printer's folder when it appears."""
    facts, s = slicer_rig(tmp_path, monkeypatch, printer=False)
    conf = json.loads(a.render_slicer_config(facts, s))
    home = Path(facts["printer_data"]) / "config" / "elyir-bench-slicer"
    assert conf["printers"]["workshop"] == {"name": "Workshop", "moonraker": "http://127.0.0.1:7125",
                                        "presets": [str(home / "presets")], "home": str(home)}
    (home / "printer.json").write_text("{ half written")   # someone editing it in Mainsail
    assert "machine" not in json.loads(a.render_slicer_config(facts, s))["printers"]["workshop"]


def test_slicer_unit_slices_on_idle_cpu_only():
    unit = a.render_slicer_unit({"user": "pi"})
    assert "CPUSchedulingPolicy=idle" in unit and "IOSchedulingClass=idle" in unit
    assert f"--port {a.SLICER_PORT}" in unit and "User=pi" in unit
    assert f"ConditionPathExists={a.CURRENT}/slicer/slice_service.py" in unit   # no restart loop after a rollback


def test_slicer_off_leaves_nothing_running(monkeypatch):
    monkeypatch.setattr(a, "is_enabled", lambda u: False)
    monkeypatch.setattr(a, "is_active", lambda u: False)
    c = a.Ctx({"printer_data": None}, {"slicer": "off"})
    assert a.SlicerEngine().check(c) == (True, "slicer off")
    assert a.SlicerService().check(c)[0]


def test_missing_packages_reads_dpkg(monkeypatch):
    class P:
        stdout = "libopengl0 install ok installed\nlibglu1-mesa unknown ok not-installed\n"
    monkeypatch.setattr(a, "run", lambda *args, **kw: P())
    assert a.missing_packages(["libopengl0", "libglu1-mesa", "libsecret-1-0"]) == ["libglu1-mesa", "libsecret-1-0"]


def test_sudoers_covers_the_slicer_unit():
    rule = a.render_sudoers("pi")
    assert f"/etc/systemd/system/{a.SLICER_UNIT}" in rule and f"* {a.SLICER_UNIT}" in rule


# ── slicing for other printers: a slicer elsewhere, lending, a controller (docs/slicer.md) ──

def test_a_printer_that_slices_elsewhere_sends_slice_there_and_says_who_it_is(monkeypatch):
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}, "printer_data": None}
    monkeypatch.setattr(a, "resolve4", lambda host: "192.0.2.73" if host == "workshop.local" else None)
    site = a.render_nginx(facts, {"port": "8088", "slicer": "workshop.local", "printer_name": "Desk"})
    assert f"proxy_pass http://192.0.2.73:{a.SLICER_PORT};" in site
    assert "proxy_set_header X-Elyir-Bench-Printer desk;" in site
    off = site.split("location @slicer_down")[1].split("}")[0]
    assert '"slicer": "workshop.local", "off": true' in off and "can\\'t slice for Desk" in off
    site = a.render_nginx(facts, {"port": "8088", "slicer": "workshop.local", "printer_name": "Desk", "slicer_name": "Workshop"})
    assert "Workshop isn\\'t answering" in site and '"slicer": "Workshop"' in site     # the printer's name, not its address
    # a name that can't be found must never stop nginx starting (the whole app would be gone)
    site = a.render_nginx(facts, {"port": "8088", "slicer": "nowhere.local:9000", "printer_name": "Desk"})
    assert "proxy_pass" not in site.split("location /slice")[1].split("}")[0]
    assert "return 503" in site and "nowhere" in site


def test_lending_listens_on_the_network_and_says_so_in_the_config(tmp_path, monkeypatch):
    facts, s = slicer_rig(tmp_path, monkeypatch)
    assert "--host 127.0.0.1" in a.render_slicer_unit(facts)
    s["slice_for_others"] = "on"
    assert json.loads(a.render_slicer_config(facts, s))["lend"] is True
    assert "--host 0.0.0.0" in a.render_slicer_unit(facts, a.slicer_lends(facts, s))


def test_a_machine_without_a_printer_is_a_controller_that_only_slices(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "SLICER_DIR", tmp_path / "elyir-bench" / "slicer")
    facts = {"moonraker": {"service": False, "url": "http://127.0.0.1:7125"}, "printer_data": None,
             "user": "pi", "sudo": "nopasswd"}
    s = {"printer_name": "NUC", "port": "8088", "role": "auto", "slicer": "off"}
    assert a.role(facts, s) == "controller" and a.slices_here(facts, s) and a.slicer_lends(facts, s)
    conf = json.loads(a.render_slicer_config(facts, s))
    assert conf["printers"] == {} and conf["lend"] is True              # only the printers that join
    names = [st.name for st in a.steps_for(a.Ctx(facts, s))]
    # door binaries: the doors it opens for the printers it speaks for (bench/doors.py); a box powers off from its button too
    assert names == ["preflight", "release", "web app", "panel", "door runtime", "door binaries", "slicer engine", "slicer service",
                     "bench service", "power button", "network wait"]
    assert a.role({"moonraker": {"service": True}}, s) == "printer"
    assert a.role(facts, {**s, "role": "printer"}) == "printer"


def test_orca_is_pinned_for_both_kinds_of_machine_and_refused_on_an_old_os(monkeypatch):
    assert set(a.ORCA["urls"]) == set(a.ORCA["sha256"]) == {"arm64", "amd64"}
    monkeypatch.setattr(a, "glibc", lambda: (2, 31))
    c = a.Ctx({"printer_data": None, "moonraker": {"service": True}}, {"slicer": "on"})
    ok, why = a.SlicerEngine().check(c)
    assert ok and why.startswith("off: Orca 2.4.2 needs glibc 2.39") and "slicer: <its address>" in why
    c = a.Ctx({"printer_data": None}, {"slicer": "workshop.local"})
    assert a.SlicerEngine().check(c) == (True, "slices on workshop.local")


class FakeSlicer:
    """A slicer elsewhere, as the installer sees it: GET and PUT /slice/printers/<id>."""
    def __init__(self, answer=200):
        import http.server, threading
        self.joined, self.puts, outer = {}, [], self
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def _send(self, code, body):
                b = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            def do_GET(self):
                pid = self.path.rsplit("/", 1)[-1]
                if pid in outer.joined:
                    self._send(200, outer.joined[pid])
                else:
                    self._send(404, {"error": f"{pid} hasn't joined this slicer"})
            def do_PUT(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.puts.append(body)
                if answer != 200:
                    return self._send(answer, {"error": "Desk can't slice here yet: its presets don't resolve: no preset called 'X'."})
                outer.joined[self.path.rsplit("/", 1)[-1]] = body
                self._send(200, body)
        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]


def join_rig(tmp_path, monkeypatch, answer=200):
    facts, _ = slicer_rig(tmp_path, monkeypatch)
    facts["host"] = "desk"
    monkeypatch.setattr(a, "unit_exists", lambda u: False)
    fake = FakeSlicer(answer)
    s = {"printer_name": "Desk", "port": "8088", "slicer": f"127.0.0.1:{fake.port}"}
    return a.Ctx(facts, s), fake


def test_a_printer_joins_the_slicer_it_names(tmp_path, monkeypatch):
    c, fake = join_rig(tmp_path, monkeypatch)
    ok, why = a.SlicerService().check(c)
    assert not ok and why.startswith("not joined")
    a.SlicerService().apply(c)
    assert fake.puts == [{"name": "Desk", "moonraker": "http://desk.local:7125"}] and not c.notes
    assert a.SlicerService().check(c) == (True, f"slicing on 127.0.0.1:{fake.port}")
    c.s["printer_name"] = "Garage"                                  # renamed: it joins again
    assert not a.SlicerService().check(c)[0]


def test_a_slicer_that_says_no_or_is_off_never_fails_an_apply(tmp_path, monkeypatch):
    c, fake = join_rig(tmp_path, monkeypatch, answer=422)
    a.SlicerService().apply(c)                                     # no exception: a release isn't rolled back
    assert "presets don't resolve" in c.notes[0]
    fake.server.shutdown()
    fake.server.server_close()
    ok, why = a.SlicerService().check(c)
    assert ok and "isn't answering" in why


# ── finding a slicer on the Wi-Fi, and asking it (design/slicing-elsewhere/, A) ──

def _mdns_answer() -> bytes:
    """An answer shaped like avahi's to a legacy unicast question for _elyir-slicer._tcp.local."""
    import struct
    def name(n):
        return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"
    def rr(n, t, data):
        return name(n) + struct.pack("!HHIH", t, 1, 120, len(data)) + data
    inst, host = "Workshop._elyir-slicer._tcp.local", "workshop.local"
    txt = b"".join(bytes([len(x)]) + x for x in (b"name=Workshop", b"kind=printer", b"machine=Raspberry Pi 5 Model B Rev 1.0", b"v=1"))
    body = (rr("_elyir-slicer._tcp.local", 12, name(inst)) + rr(inst, 33, struct.pack("!HHH", 0, 0, 8095) + name(host))
            + rr(inst, 16, txt) + rr(host, 1, bytes([192, 0, 2, 73])))
    q = name("_elyir-slicer._tcp.local") + struct.pack("!HH", 12, 1)
    return struct.pack("!HHHHHH", 0x5c1e, 0x8400, 1, 1, 0, 3) + q + body


def test_a_slicer_on_the_wifi_is_read_from_its_mdns_answer():
    found = a.slicers_from(a._dns_records(_mdns_answer()))
    assert found == [{"name": "Workshop", "kind": "printer", "machine": "Raspberry Pi 5 Model B Rev 1.0",
                      "host": "workshop.local", "port": 8095, "ip": "192.0.2.73"}]


def test_the_best_slicer_is_a_bench_then_the_quickest_and_never_itself():
    pi5 = {"name": "Workshop", "kind": "printer", "machine": "Raspberry Pi 5 Model B", "host": "workshop.local", "port": 8095}
    pi4 = {"name": "Studio", "kind": "printer", "machine": "Raspberry Pi 4 Model B", "host": "studio.local", "port": 8095}
    bench = {"name": "Bench Box", "kind": "controller", "machine": "", "host": "benchbox.local", "port": 8095}
    assert a.best_slicer([pi4, pi5], "Desk") is pi5
    assert a.best_slicer([pi4, pi5, bench], "Desk") is bench
    assert a.best_slicer([pi5], "Workshop") is None


def test_auto_slices_here_when_it_can_and_elsewhere_when_it_cant(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(a, "BASE", tmp_path)
    facts = {"moonraker": {"service": True}}
    monkeypatch.setattr(a, "orca_cant_run", lambda: None)
    s = a.resolve_slicer(facts, {"printer_name": "Workshop", "slicer": "auto"})
    assert s["slicer"] == "on" and s["slicer_auto"]
    monkeypatch.setattr(a, "orca_cant_run", lambda: "glibc 2.31")
    monkeypatch.setattr(a, "mdns_slicers", lambda: a.slicers_from(a._dns_records(_mdns_answer())))
    s = a.resolve_slicer(facts, {"printer_name": "Desk", "slicer": "auto"})
    assert s["slicer"] == "workshop.local" and s["slicer_name"] == "Workshop"
    # Workshop off later: nothing answers, so the one found before, with its name remembered
    monkeypatch.setattr(a, "mdns_slicers", lambda: [])
    monkeypatch.setattr(a, "http_json", lambda *x, **k: (_ for _ in ()).throw(OSError("off")))
    s = a.resolve_slicer(facts, {"printer_name": "Desk", "slicer": "auto"})
    assert s["slicer"] == "workshop.local" and s["slicer_name"] == "Workshop"
    assert "slicer: auto" in _saved(a, facts, s, tmp_path)               # the setting stays auto


def _saved(a, facts, s, tmp_path):
    full = {**a.default_settings({**facts, "host": "desk", "kiosk": {"enabled": False}, "klipperscreen": {"installed": False},
                                  "panel_output": None, "printer_data": str(tmp_path)}), **s}
    (tmp_path / "config").mkdir(exist_ok=True)
    return a.save_settings({"printer_data": str(tmp_path)}, full).read_text()


def test_a_lending_slicer_says_so_on_the_wifi(tmp_path, monkeypatch):
    facts, s = slicer_rig(tmp_path, monkeypatch)
    facts["model"] = "Raspberry Pi 5 Model B Rev 1.0"
    xml = a.render_avahi(facts, {**s, "slice_for_others": "on"})
    assert "<type>_elyir-slicer._tcp</type>" in xml and f"<port>{a.SLICER_PORT}</port>" in xml
    assert "<txt-record>name=Workshop</txt-record>" in xml and "machine=Raspberry Pi 5" in xml
    conf = json.loads(a.render_slicer_config(facts, s))
    assert conf["name"] == "Workshop" and conf["allow"] == "ask"             # a printer's owner says yes on its screen


def test_a_printer_waiting_for_a_yes_is_said_and_not_failed(tmp_path, monkeypatch):
    c, fake = join_rig(tmp_path, monkeypatch)
    fake.joined["desk"] = {"id": "desk", "name": "Desk", "waiting": True, "slicer": "Workshop"}
    c.s["slicer_name"] = "Workshop"
    assert a.SlicerService().check(c) == (True, "asked Workshop; waiting for a yes on its screen")


def test_a_printer_says_so_on_the_wifi_for_a_bench_box():
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}}
    xml = a.render_printer_avahi(facts, {"printer_name": "Desk", "port": "8088", "remote": "relay"})
    assert "<type>_elyir-printer._tcp</type>" in xml and "<port>8088</port>" in xml
    assert all(f"<txt-record>{t}</txt-record>" in xml for t in ("name=Desk", "id=desk", "door=1", "moonraker=7125"))
    assert "door=0" in a.render_printer_avahi(facts, {"printer_name": "Desk", "port": "8088", "remote": "off"})
    assert a.Announce in [type(st) for st in a.STEPS] and "printer" in a.Announce.roles and "controller" not in a.Announce.roles


def test_a_bench_box_serves_its_screen_and_its_service_behind_it():
    facts = {"moonraker": {"service": False, "url": "http://127.0.0.1:7125"}, "printer_data": None, "user": "pi", "host": "bench"}
    s = {"printer_name": "Bench Box", "port": "8088", "slicer": "on"}
    site = a.render_bench_nginx(facts, s)
    assert f"root {a.CURRENT}/bench-app;" in site and f"proxy_pass http://127.0.0.1:{a.BENCH_PORT};" in site
    assert "proxy_set_header Upgrade $http_upgrade;" in site            # the printers' websockets come through it
    assert "location /slice {" in site                                  # and its own slicer
    unit = a.render_bench_unit(facts, s)
    assert '--name "Bench Box"' in unit and "--serve-port 8088" in unit and f"--port {a.BENCH_PORT}" in unit
    assert f"--relay-api {a.DEFAULT_RELAY_API}" in unit and f"--door-bin {a.DOOR_BIN}" in unit   # doors for the Kobras
    assert "--remote off --home-port 443" in unit and "AmbientCapabilities=CAP_NET_BIND_SERVICE" in unit
    assert "--remote relay" in a.render_bench_unit(facts, {**s, "remote": "relay"})
    assert f"--remote-name {a.public_name()}" in unit and "--remote-name desk" in a.render_bench_unit(facts, {**s, "remote_name": "desk"})
    assert a.default_settings({**facts, "kiosk": {"enabled": False}, "klipperscreen": {"installed": False},
                               "panel_output": None})["printer_name"] == "Bench Box"


# ── getting started: the check, the pairing code, remove (design/getting-started) ─────────────────────

def board_facts(**over):
    f = {"host": "voron", "user": "pi", "arch": "aarch64", "model": "Raspberry Pi 5 Model B Rev 1.0",
         "os": "Debian GNU/Linux 13 (trixie)", "os_id": "debian", "os_version": "13", "board_release": None,
         "memory_mb": 3950, "panel_output": None, "kiosk_backends": ["cage", "x11"], "sudo": "full",
         "moonraker": {"reachable": True, "components": "/home/pi/moonraker/moonraker/components", "url": "http://127.0.0.1:7125"},
         "web_ui": {"name": "Mainsail", "port": 80}, "print_state": "standby", "installed": {},
         "klipperscreen": {"installed": False, "enabled": False, "active": False}}
    f.update(over)
    return f


S = {"port": "8088", "slicer": "on", "remote": "off"}


def test_a_pi_5_on_debian_13_gets_everything(monkeypatch):
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a, "mem_mb", lambda: 3950)
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    e = a.expectations(board_facts(), S)
    assert e["verdict"] == "everything" and e["board"] == "Raspberry Pi 5, 4 GB, Debian 13" and not e["differences"]


def test_a_btt_pi_on_debian_11_works_with_two_differences_and_names_who_slices(monkeypatch):
    # Desk: BQ-H616, 1 GB, Debian 11, KlipperScreen on an HDMI screen, Workshop lends its slicer
    monkeypatch.setattr(a, "glibc", lambda: (2, 31))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    f = board_facts(model="BQ-H616", board_release="BTT-CB1", memory_mb=987, os_version="11",
                    os="Debian GNU/Linux 11 (bullseye)", panel_output="HDMI-A-1", kiosk_backends=["x11"],
                    klipperscreen={"installed": True, "enabled": True, "active": True})
    e = a.expectations(f, {**S, "slicer": "workshop.local", "slicer_name": "Workshop"})
    assert e["verdict"] == "differences" and e["board"] == "BTT Pi or CB1, 1 GB, Debian 11"
    assert e["differences"] == ["The screen has simpler animations (no graphics driver).",
                                "It can't slice by itself. Workshop, on your Wi-Fi, slices for it."]
    assert e["note"].startswith("Debian 11 stopped getting updates")
    lines, code = a.check_report(f, {**S, "slicer": "workshop.local", "slicer_name": "Workshop"})
    assert code == 0 and "  ✓ A touchscreen, running KlipperScreen" in lines
    assert lines[-1] == "It leaves printer.cfg, Mainsail and KlipperScreen as they are"
    assert "Everything works on this board, with 2 differences:" in lines


def test_a_1_gb_board_cant_slice_even_on_a_new_system(monkeypatch):
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a, "mem_mb", lambda: 987)
    assert "1 GB free" in a.orca_cant_run()


def test_not_yet_for_32_bit_and_unknown_boards(monkeypatch):
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "armv7l"})())
    e = a.expectations(board_facts(arch="armv7l", model="Raspberry Pi 4 Model B Rev 1.4"), S)
    assert e["verdict"] == "not_yet" and "32-bit" in e["why_not"]
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    e = a.expectations(board_facts(model="Raspberry Pi 3 Model B Plus Rev 1.3"), S)
    assert e["verdict"] == "not_yet" and "Raspberry Pi 3" in e["why_not"]
    lines, code = a.check_report(board_facts(model="Raspberry Pi 3 Model B Plus Rev 1.3"), S)
    assert code == 4 and lines[-1] == "Nothing was changed."


def test_the_site_table_is_what_the_check_says(monkeypatch):
    # bench.elyir.com/install's table is install/boards.json; `elyir-bench boards > install/boards.json` after a change
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))          # this machine's own probes play no part
    monkeypatch.setattr(a, "mem_mb", lambda: 8000)
    monkeypatch.setenv("ELYIR_BENCH_ANY_BOARD", "1")
    rows = a.site_table()
    assert json.loads((Path(__file__).resolve().parents[2] / "install/boards.json").read_text()) == rows
    by = {(r["board"], r["system"]): r for r in rows}
    assert by[("Raspberry Pi 5", "Debian 13")]["get"] == "Everything"
    assert by[("Raspberry Pi 4 or 5", "Debian 12")]["slicing"].startswith("Another printer")
    assert by[("Raspberry Pi 4", "Debian 11")]["screen"] == "Yes, the way KlipperScreen runs"
    assert by[("Raspberry Pi 4", "Debian 11")]["note"]
    assert by[("BTT Pi, BTT CB1", "BTT's own system, 1 GB")]["screen"] == "Yes, simpler animations"
    assert [r["verdict"] for r in rows if r["get"].startswith("Not yet")] == ["not_yet", "not_yet"]


def test_the_check_says_which_kind_each_difference_is(monkeypatch):
    monkeypatch.setattr(a, "glibc", lambda: (2, 31))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    e = a.expectations(board_facts(model="BQ-H616", memory_mb=987, panel_output="HDMI-A-1", kiosk_backends=["x11"]), S)
    assert (e["screen"], e["slicing"]) == ("simpler", "elsewhere")
    e = a.expectations(board_facts(panel_output="HDMI-A-1", kiosk_backends=[]), S)
    assert (e["screen"], e["slicing"]) == ("klipperscreen", "elsewhere")


def test_the_check_stops_for_a_print_and_changes_nothing(monkeypatch):
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    monkeypatch.setattr(a, "printing_now", lambda f: "phone-stand.gcode, 42 %")
    lines, code = a.check_report(board_facts(print_state="printing"), S)
    assert code == 3 and "  ✗ Printing: phone-stand.gcode, 42 %" in lines
    assert lines[-1].startswith("Nothing was changed. Run the same command again")


def test_the_check_on_a_printer_that_has_it_says_it_updates(monkeypatch):
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    lines, code = a.check_report(board_facts(installed={"version": "2026.10.04-847e963"}), S)
    assert code == 0 and lines[-1] == "Elyir Bench 2026.10.04-847e963 is already here; this updates it."


def test_without_the_door_the_code_is_the_printers_own_address():
    assert a.pair_target(board_facts(), S) == ("http://voron.local:8088/", None)


def test_remove_takes_only_our_section_out_of_moonraker_conf():
    conf = ("[server]\nhost: 0.0.0.0\n\n# Elyir Bench: the intent layer\n[printer_intent]\nprinter_name: Voron\n"
            "advanced_url: http://voron.local/\n\n[update_manager]\nrefresh_interval: 168\n")
    assert a.strip_intent_section(conf) == "[server]\nhost: 0.0.0.0\n\n[update_manager]\nrefresh_interval: 168\n"
    assert a.strip_intent_section("[server]\n") == "[server]\n"
    at_end = "[server]\nhost: 0.0.0.0\n\n[printer_intent]\nprinter_name: Voron\n"
    assert a.strip_intent_section(at_end) == "[server]\nhost: 0.0.0.0\n"


def test_web_ui_is_found_with_its_port(tmp_path):
    (tmp_path / "fluidd").write_text("server {\n    listen 80 default_server;\n}\n")
    assert a.detect_web_ui(tmp_path) == {"name": "Fluidd", "port": 80}
    assert a.detect_web_ui(tmp_path / "none") == {"name": None, "port": None}


def test_the_install_script_carries_the_release_key_and_parses():
    import re, subprocess
    root = Path(__file__).resolve().parents[2]
    script = (root / "install" / "install.sh").read_text()
    key = re.search(r"RELEASE_KEY='(-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----)'", script, re.S).group(1)
    assert key.strip() == (root / "install" / "release-key.pem").read_text().strip()
    assert subprocess.run(["sh", "-n", str(root / "install" / "install.sh")]).returncode == 0
    assert script.rstrip().endswith('main "$@"')      # nothing runs until the whole script has arrived


KS_CONF = """[preheat PLA]
bed = 90

#~# --- Do not edit below this line. This section is auto generated --- #~#
#~#
#~# [main]
#~# screen_blanking = off
"""


def test_klipperscreen_menu_goes_above_the_saved_section():
    out = a.render_klipperscreen_conf(KS_CONF)
    assert out.index("[menu __main elyir-bench]") < out.index("#~# --- Do not edit below")
    assert out.startswith("[preheat PLA]\nbed = 90\n\n# elyir-bench: begin")
    assert out.endswith("#~# screen_blanking = off\n")
    assert a.render_klipperscreen_conf(out) == out, "a second run changes nothing"


def test_klipperscreen_menu_in_a_file_without_a_saved_section():
    assert a.render_klipperscreen_conf("") == a.KS_MENU
    out = a.render_klipperscreen_conf("[preheat PLA]\nbed = 90\n")
    assert out == "[preheat PLA]\nbed = 90\n\n" + a.KS_MENU
    assert a.render_klipperscreen_conf(out) == out


def test_switching_the_screen_touches_only_the_screen():
    assert [s.name for s in a.SCREEN_STEPS] == ["panel", "klipperscreen menu", "boot screen"]


# ── switching to KlipperScreen never ends on a dark screen ───────────────────

def screen_rig(monkeypatch, installed, units):
    """units: the systemd units that are enabled and running; sudo flips them like systemctl."""
    calls = []
    def sudo(*cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ("systemctl", "disable"):
            units.discard(cmd[-1])
        elif cmd[:2] == ("systemctl", "enable") and "--now" in cmd:
            units.add(cmd[-1])
    monkeypatch.setattr(a, "sudo", sudo)
    monkeypatch.setattr(a, "is_active", lambda u: u in units)
    monkeypatch.setattr(a, "is_enabled", lambda u: u in units)
    monkeypatch.setattr(a, "unit_exists", lambda u: u == a.KIOSK_UNIT or (installed and u == "KlipperScreen.service"))
    facts = {"klipperscreen": {"installed": installed}, "printer_data": None}
    return a.Ctx(facts, {"panel": "klipperscreen", "port": "8088"}), calls


def test_no_switch_to_a_klipperscreen_that_isnt_there(monkeypatch):
    units = {a.KIOSK_UNIT}
    c, calls = screen_rig(monkeypatch, False, units)
    assert a.Panel().check(c) == (False, a.NO_KLIPPERSCREEN)
    try:
        a.Panel().apply(c)
        assert False, "should refuse"
    except a.StepFailed as e:
        assert "isn't installed" in str(e)
    assert units == {a.KIOSK_UNIT} and calls == [], "the Elyir Bench panel is never turned off"


def test_the_panel_command_refuses_before_saving_anything(monkeypatch, capsys):
    monkeypatch.setattr(a.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(a, "detect", lambda: {"klipperscreen": {"installed": False}})
    monkeypatch.setattr(a, "load_settings", lambda f: {"panel": "elyir-bench"})
    saved = []
    monkeypatch.setattr(a, "save_settings", lambda f, s: saved.append(dict(s)))
    assert a.main(["panel", "klipperscreen"]) == 1
    assert saved == [] and "stays on elyir-bench" in capsys.readouterr().out


def test_a_switch_that_doesnt_come_up_puts_elyir_bench_back(monkeypatch):
    units = {a.KIOSK_UNIT}
    c, _ = screen_rig(monkeypatch, True, units)
    a.Panel().apply(c)
    assert units == {"KlipperScreen.service"}
    for _, undo in reversed(c.undo):   # what apply() runs when health fails
        undo()
    assert units == {a.KIOSK_UNIT}


def test_klipperscreen_counts_only_once_it_stays_up(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "is_active", lambda u: True)
    uptime = tmp_path / "uptime"
    monkeypatch.setattr(a, "Path", lambda p: uptime if p == "/proc/uptime" else Path(p))
    monkeypatch.setattr(a, "systemd", lambda u, prop: "100000000")   # active since 100 s after boot
    uptime.write_text("103.0 1.0\n")
    assert not a.klipperscreen_steady(), "3 s up: might be between crashes"
    uptime.write_text(f"{100 + a.KS_STEADY}.5 1.0\n")
    assert a.klipperscreen_steady()
    monkeypatch.setattr(a, "is_active", lambda u: False)
    assert not a.klipperscreen_steady()


def test_remove_takes_our_entry_out_of_klipperscreens_menu_and_nothing_else():
    theirs = "[main]\nlanguage: en\n\n#~# --- Do not edit below this line. This section is auto generated --- #~#\n#~#\n#~# [main]\n"
    with_ours = a.render_klipperscreen_conf(theirs)
    assert "# elyir-bench: begin" in with_ours
    assert a.strip_klipperscreen_menu(with_ours) == theirs
    assert a.strip_klipperscreen_menu(a.render_klipperscreen_conf("")) == ""


# ── a new printer's first Wi-Fi (docs/setup.md) ─────────────────────────────

def test_the_setup_site_never_takes_port_80_from_the_house(tmp_path):
    sites = tmp_path / "sites-enabled"
    sites.mkdir()
    (sites / "mainsail").write_text("server {\n    listen 80;\n    # listen [::]:80;\n}\n")
    (sites / "elyir-bench").write_text("server {\n    listen 8088;\n}\n")
    assert a.other_port80(sites)
    # Mainsail's plain `listen 80` sorts after elyir-bench-setup: a plain one here would become the house's default
    assert "listen 10.42.0.1:80;" in a.render_wifi_site({"web": {"port80": True}})
    (sites / "mainsail").write_text("server {\n    listen 8080;\n}\n")
    assert not a.other_port80(sites)
    assert "listen 80;" in a.render_wifi_site({"web": {"port80": False}})


def test_the_panel_reaches_the_first_wifi_only_where_networkmanager_runs():
    facts = {"moonraker": {"url": "http://127.0.0.1:7125"}, "printer_data": None}
    assert "location /wifi/" not in a.render_nginx(facts, {"port": "8088"})
    site = a.render_nginx({**facts, "network_manager": True}, {"port": "8088"})
    assert "location /wifi/ {" in site and f"proxy_pass http://127.0.0.1:{a.WIFI_PORT};" in site


def test_the_first_wifi_service_runs_from_the_release_as_the_printer_user():
    unit = a.render_wifi_unit({"user": "pi"}, {"port": "8088"})
    assert "User=pi" in unit and "After=NetworkManager.service" in unit
    assert "/current/setup/wifi_setup.py" in unit and "--app-port 8088" in unit and "/current/installer/elyir_bench.py" in unit


def test_every_name_on_the_setup_wifi_is_the_printer():
    assert a.WIFI_DNS_CONF.strip().endswith("address=/#/10.42.0.1")


def test_the_sudo_rule_covers_the_first_wifi_without_passwords_on_command_lines():
    rule = a.render_sudoers("pi")
    assert "elyir-bench-wifi.service" in rule and "nmcli *" in rule and "hostnamectl set-hostname *" in rule
    assert "/dev/stdin /etc/NetworkManager/system-connections/elyir-bench-*.nmconnection" in rule


@pytest.mark.parametrize("name,host", [("Workshop", "workshop"), ("Mia's Desk", "mia-s-desk"), ("  ", "printer"),
                                       ("Garage 2", "garage-2"), ("Ünïcode", "n-code")])
def test_a_printer_name_becomes_its_name_on_the_network(name, host):
    assert a.hostname_for(name) == host


def test_hosts_keeps_everything_but_this_machines_line():
    before = "127.0.0.1\tlocalhost\n::1\tlocalhost\n\n127.0.1.1\traspberrypi\n"
    assert a.render_hosts(before, "workshop") == "127.0.0.1\tlocalhost\n::1\tlocalhost\n\n127.0.1.1\tworkshop\n"
    assert a.render_hosts("127.0.0.1\tlocalhost\n", "workshop") == "127.0.0.1\tlocalhost\n127.0.1.1\tworkshop\n"


def test_rename_saves_the_name_and_sets_the_network_name_once(monkeypatch):
    calls, wrote = [], {}
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(a, "sudo_write", lambda path, text: wrote.update({path: text}))
    monkeypatch.setattr(a, "read", lambda path, default="": "127.0.1.1\traspberrypi\n")
    facts, s = {"host": "raspberrypi"}, {"printer_name": "RASPBERRYPI"}
    a.rename(facts, s, "Workshop")
    assert s["printer_name"] == "Workshop" and facts["host"] == "workshop"
    assert ("hostnamectl", "set-hostname", "workshop") in calls and wrote["/etc/hosts"] == "127.0.1.1\tworkshop\n"
    calls.clear()
    a.rename(facts, s, "WORKSHOP")          # the same name on the network: nothing to change there
    assert calls == [] and s["printer_name"] == "WORKSHOP"


# ── a new printer's first boot has no network (docs/image.md) ──────────────

class _C:
    def __init__(self, defer):
        self.defer_downloads, self.s, self.facts, self.switched_from = defer, {"slicer": "on", "remote": "off"}, {"moonraker": {"service": True}}, None


def test_downloads_wait_for_the_network_instead_of_holding_up_the_first_boot(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "DOOR_VENV", tmp_path / "venv")
    monkeypatch.setattr(a, "missing_packages", lambda pk: ["libopengl0"])
    monkeypatch.setattr(a, "orca_cant_run", lambda: None)
    monkeypatch.setattr(a, "orca_binary", lambda: tmp_path / "no-orca")
    ok, why = a.DoorRuntime().check(_C(True))
    assert ok and "waits for the network" in why
    ok, why = a.SlicerEngine().check(_C(True))
    assert ok and "waits for the network" in why
    assert a.SlicerService().check(_C(True)) == (True, "waits for the slicer engine")
    assert not a.DoorRuntime().check(_C(False))[0] and not a.SlicerEngine().check(_C(False))[0]


def test_asked_to_wait_is_enough_without_looking_at_the_network(monkeypatch):
    monkeypatch.setenv("ELYIR_BENCH_DEFER_DOWNLOADS", "1")
    monkeypatch.setattr(a, "internet", lambda: (_ for _ in ()).throw(AssertionError("looked")))
    assert a.Ctx({}, {}).defer_downloads


def test_the_first_wifi_comes_right_after_the_panel():
    names = [s.name for s in a.STEPS]
    assert names.index("first wi-fi") == names.index("panel") + 1


def test_remove_keeps_the_home_wifi_and_takes_only_ours(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(a, "sudo", lambda *cmd, **kw: calls.append(cmd) or type("P", (), {"returncode": 0})())
    monkeypatch.setattr(a, "run", lambda *args, **kw: type("P", (), {"returncode": 0, "stdout": ""})())
    monkeypatch.setattr(a, "unit_exists", lambda u: True)
    monkeypatch.setattr(a, "restart_moonraker", lambda f: None)
    monkeypatch.setattr(a, "printing_now", lambda f: None)
    monkeypatch.setattr(a.shutil, "which", lambda name: "/usr/bin/" + name)
    for step in (a.Panel, a.BootScreen, a.DoorServices, a.SlicerService):
        monkeypatch.setattr(step, "check", lambda self, c: (True, "off"))
    monkeypatch.setattr(a, "BASE", tmp_path / "elyir-bench")
    monkeypatch.setattr(a, "HOME", tmp_path)
    (tmp_path / "elyir-bench" / "state").mkdir(parents=True)
    (tmp_path / "printer_data" / "config").mkdir(parents=True)
    facts = {"klipperscreen": {"installed": True}, "printer_data": str(tmp_path / "printer_data"),
             "moonraker": {"components": None, "conf": None, "service": True}, "print_state": "standby"}
    c = a.Ctx(facts, {"port": "8088", "panel": "elyir-bench"})
    assert a.remove(c)
    said = [" ".join(map(str, cmd)) for cmd in calls]
    # the printer's own Wi-Fi (system-connections/elyir-bench-wifi-<ssid>) stays: only the setup hotspot goes
    assert [line for line in said if line.startswith("nmcli connection delete")] == ["nmcli connection delete elyir-bench-setup"]
    assert not any("system-connections" in line or "elyir-bench-wifi-" in line for line in said)
    assert not (tmp_path / "elyir-bench").exists()
    assert "systemctl disable elyir-bench-firstboot.service" in said   # a flashed card never installs itself again


# ── Elyir Bench's start macro (docs/start-macro.md, docs/setup-card.md) ─────────

REPO = Path(__file__).resolve().parents[2]

PRINTER_CFG = """[include mainsail.cfg]
[include macros/*.cfg]

[printer]
kinematics: corexy

#*# <---------------------- SAVE_CONFIG ---------------------->
#*# [include old.cfg]
#*# [bed_mesh default]
"""


def macro_rig(tmp_path, monkeypatch, printing=None, slicer_profile=True, restarts=None):
    """A config folder, a release carrying elyir-bench.cfg, and a Klipper that restarts when told (recorded)."""
    config = tmp_path / "printer_data" / "config"
    (config / "macros").mkdir(parents=True)
    (config / "printer.cfg").write_text(PRINTER_CFG)
    (config / "macros" / "start.cfg").write_text("[gcode_macro PRINT_START]\ngcode:\n  G28\n")
    if slicer_profile:
        (config / "elyir-bench-slicer").mkdir()
        (config / "elyir-bench-slicer" / "printer.json").write_text('{"machine": "Voron", "process": "p", "materials": {}}')
    release = tmp_path / "current"
    (release / "printer" / "klipper").mkdir(parents=True)
    shutil.copy(REPO / "printer" / "klipper" / "elyir-bench.cfg", release / "printer" / "klipper" / "elyir-bench.cfg")
    monkeypatch.setattr(a, "CURRENT", release)
    restarts = [] if restarts is None else restarts
    monkeypatch.setattr(a, "klipper_restart", lambda facts, wait=90: restarts.append("FIRMWARE_RESTART"))
    monkeypatch.setattr(a, "klipper_has", lambda facts, name: name == a.START_MACRO_COMMAND)
    facts = {"printer_data": str(tmp_path / "printer_data"), "print_state": printing,
             "moonraker": {"url": "http://127.0.0.1:7125"}}
    return a.Ctx(facts, {"start_macro": "on", "printer_name": "Voron"}), config, restarts


def test_on_writes_the_macro_adds_one_include_line_and_restarts_klipper_once(tmp_path, monkeypatch):
    c, config, restarts = macro_rig(tmp_path, monkeypatch)
    step = a.StartMacro()
    ok, why = step.check(c)
    assert not ok and why == "to add: elyir-bench.cfg, the include line in printer.cfg, the slicer's start_macro flag"
    step.apply(c)
    assert restarts == ["FIRMWARE_RESTART"]
    assert (config / "elyir-bench.cfg").read_text() == (REPO / "printer" / "klipper" / "elyir-bench.cfg").read_text()
    assert (config / "printer.cfg").read_text() == PRINTER_CFG.replace(
        "[include macros/*.cfg]\n", "[include macros/*.cfg]\n[include elyir-bench.cfg]\n")
    assert json.loads((config / "elyir-bench-slicer" / "printer.json").read_text())["start_macro"] is True
    assert step.check(c) == (True, "[include elyir-bench.cfg] in printer.cfg")
    step.apply(c)
    assert restarts == ["FIRMWARE_RESTART"], "nothing changed: no second restart"


def test_their_own_m600_in_any_case_leaves_ours_out(tmp_path, monkeypatch):
    c, config, _ = macro_rig(tmp_path, monkeypatch)
    (config / "macros" / "filament.cfg").write_text("[gcode_macro m600]\ngcode:\n  PAUSE\n")
    a.StartMacro().apply(c)
    ours = (config / "elyir-bench.cfg").read_text()
    assert "[gcode_macro M600]" not in ours and "M600 is left out here" in ours
    assert "[gcode_macro ELYIR_BENCH_PRINT_START]" in ours and ours.rstrip().endswith("it stays as it is.")
    assert a.StartMacro().check(c) == (True, "[include elyir-bench.cfg] in printer.cfg, without its M600 (this printer has its own)")
    (config / "macros" / "filament.cfg").unlink()
    shutil.copy(REPO / "printer" / "klipper" / "elyir-bench.cfg", config / "elyir-bench.cfg")
    assert not a.has_own_m600(config), "elyir-bench.cfg's own M600 isn't theirs"
    a.StartMacro().apply(c)
    assert "[gcode_macro M600]" in (config / "elyir-bench.cfg").read_text(), "theirs gone: ours comes back"


def test_without_includes_the_line_goes_at_the_top_and_off_takes_only_it_out():
    text = "[printer]\nkinematics: corexy\n"
    on = a.render_printer_cfg(text, True)
    assert on == "[include elyir-bench.cfg]\n" + text
    assert a.render_printer_cfg(on, True) == on
    assert a.render_printer_cfg(on, False) == text
    no_newline = "[include mainsail.cfg]"
    assert a.render_printer_cfg(no_newline, True) == "[include mainsail.cfg]\n[include elyir-bench.cfg]\n"


def test_off_takes_the_file_the_line_and_the_flag_out(tmp_path, monkeypatch):
    c, config, restarts = macro_rig(tmp_path, monkeypatch)
    a.StartMacro().apply(c)
    c.s["start_macro"] = "off"
    ok, why = a.StartMacro().check(c)
    assert not ok and why.startswith("to take out: elyir-bench.cfg")
    a.StartMacro().apply(c)
    assert not (config / "elyir-bench.cfg").exists() and (config / "printer.cfg").read_text() == PRINTER_CFG
    assert "start_macro" not in json.loads((config / "elyir-bench-slicer" / "printer.json").read_text())
    assert restarts == ["FIRMWARE_RESTART", "FIRMWARE_RESTART"]
    assert a.StartMacro().check(c) == (True, "off")


def test_never_while_printing_unless_forced_and_then_no_restart(tmp_path, monkeypatch):
    c, config, restarts = macro_rig(tmp_path, monkeypatch, printing="printing")
    try:
        a.StartMacro().apply(c)
        assert False, "should refuse"
    except a.StepFailed as e:
        assert "the printer is printing" in str(e)
    assert not (config / "elyir-bench.cfg").exists() and (config / "printer.cfg").read_text() == PRINTER_CFG
    c.force = True
    a.StartMacro().apply(c)
    assert (config / "elyir-bench.cfg").exists() and restarts == []
    assert c.notes == ["Klipper reads the start macro change at its next restart; it's printing now"]


def test_only_the_slicer_flag_changing_doesnt_restart_klipper(tmp_path, monkeypatch):
    c, config, restarts = macro_rig(tmp_path, monkeypatch)
    a.StartMacro().apply(c)
    (config / "elyir-bench-slicer" / "printer.json").write_text('{"machine": "Voron"}')
    a.StartMacro().apply(c)
    assert json.loads((config / "elyir-bench-slicer" / "printer.json").read_text())["start_macro"] is True
    assert restarts == ["FIRMWARE_RESTART"]


def test_without_a_slicing_profile_there_is_no_flag_to_set(tmp_path, monkeypatch):
    c, config, _ = macro_rig(tmp_path, monkeypatch, slicer_profile=False)
    a.StartMacro().apply(c)
    assert a.StartMacro().check(c)[0] and not (config / "elyir-bench-slicer").exists()


def test_a_klipper_that_doesnt_come_back_puts_everything_back(tmp_path, monkeypatch):
    restarts = []
    c, config, _ = macro_rig(tmp_path, monkeypatch, restarts=restarts)
    def restart(facts, wait=90):
        restarts.append("FIRMWARE_RESTART")
        if (config / "elyir-bench.cfg").exists():
            raise a.StepFailed("Klipper didn't start again: Option 'x' is not valid in section 'printer'")
    monkeypatch.setattr(a, "klipper_restart", restart)
    try:
        a.StartMacro().apply(c)
        assert False, "should fail"
    except a.StepFailed as e:
        assert "didn't start again" in str(e)
    for _, undo in reversed(c.undo):   # what apply() runs when a step fails
        undo()
    assert not (config / "elyir-bench.cfg").exists() and (config / "printer.cfg").read_text() == PRINTER_CFG
    assert "start_macro" not in json.loads((config / "elyir-bench-slicer" / "printer.json").read_text())
    assert restarts == ["FIRMWARE_RESTART", "FIRMWARE_RESTART"], "restarted again without it"


def test_the_start_macro_setting_is_saved_off_by_default(tmp_path):
    facts = {"host": "voron", "moonraker": {"service": True, "conf": None}, "kiosk": {"enabled": False},
             "klipperscreen": {"installed": False}, "panel_output": None, "printer_data": str(tmp_path)}
    s = a.default_settings(facts)
    assert s["start_macro"] == "off"
    (tmp_path / "config").mkdir()
    text = a.save_settings(facts, s).read_text()
    assert "start_macro: off\n" in text and "# on: Elyir Bench's start macro" in text
    assert a.load_settings(facts)["start_macro"] == "off"


def test_the_startmacro_command_applies_only_that_and_says_so_in_the_settings(monkeypatch):
    monkeypatch.setattr(a.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(a, "detect", lambda: {"klipperscreen": {"installed": False}})
    monkeypatch.setattr(a, "resolve_slicer", lambda f, s: s)
    monkeypatch.setattr(a, "load_settings", lambda f: {"panel": "klipperscreen", "start_macro": "off"})
    saved, ran = [], []
    monkeypatch.setattr(a, "save_settings", lambda f, s: saved.append(dict(s)))
    monkeypatch.setattr(a, "apply", lambda c, as_json=False, steps=None: ran.append((steps, c.force)) or False)
    assert a.main(["--json", "startmacro", "on", "--force"]) == 1
    assert ran == [(a.START_MACRO_STEPS, True)]
    assert [s["start_macro"] for s in saved] == ["on", "off"], "undone: the setting goes back"
    assert [st.name for st in a.START_MACRO_STEPS] == ["start macro", "slicer service"]


def test_the_start_macro_comes_after_moonraker_conf_and_goes_first_on_remove():
    names = [st.name for st in a.STEPS]
    assert names.index("start macro") == names.index("moonraker.conf") + 1
    assert a.REMOVE_STEPS[0].name == "start macro"


def test_each_apply_saves_what_works_on_this_board(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(a, "BASE", tmp_path)
    monkeypatch.setattr(a, "health", lambda c, wait=30: (True, "app up"))
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    class Fine(a.Step):
        name = "fine"
        def check(self, c):
            return (True, "nothing to do")
    c = a.Ctx(board_facts(), dict(S, panel="none"))
    assert a.apply(c, as_json=True, steps=[Fine()])
    assert json.loads((tmp_path / "state.json").read_text())["expectations"]["board"] == "Raspberry Pi 5, 4 GB, Debian 13"


def test_klipper_restart_waits_for_ready_and_says_what_klipper_said(monkeypatch):
    posted, states = [], iter([("ready", ""), ("startup", ""), ("error", "Option 'x' is not valid in section 'printer'\nmore")])
    class R:
        def close(self):
            pass
    monkeypatch.setattr(a.urllib.request, "urlopen", lambda req, timeout=0: posted.append(req.full_url) or R())
    monkeypatch.setattr(a.time, "sleep", lambda s: None)
    def info(url, timeout=0):
        st, msg = next(states)
        return {"result": {"state": st, "state_message": msg}}
    monkeypatch.setattr(a, "http_json", info)
    try:
        a.klipper_restart({"moonraker": {"url": "http://127.0.0.1:7125"}})
        assert False, "should fail"
    except a.StepFailed as e:
        assert str(e) == "Klipper didn't start again: Option 'x' is not valid in section 'printer'"
    assert posted == ["http://127.0.0.1:7125/printer/firmware_restart"]
    states = iter([("ready", ""), ("startup", ""), ("ready", "")])
    a.klipper_restart({"moonraker": {"url": "http://127.0.0.1:7125"}})


def test_taking_the_start_macro_out_comments_out_their_settings_copy_that_cant_stand_alone():
    # desk.local, 5 October 2026: a settings copy below the include, as elyir-bench.cfg said, stopped Klipper once the include went
    cfg = ("[include mainsail.cfg]\n\n[extruder]\nmax_temp: 300\n\n"
           "[gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS]\nvariable_nozzle_warm: 40\n\n"
           "[gcode_macro MY_MACRO]\ngcode:\n  M117 hi\n#*# <---------------------- SAVE_CONFIG ---------------------->\n")
    out = a.render_orphan_settings(cfg)
    assert "#[gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS]\n#variable_nozzle_warm: 40\n" in out
    assert "start macro was taken out" in out
    assert "[extruder]\nmax_temp: 300" in out and "[gcode_macro MY_MACRO]\ngcode:\n  M117 hi\n" in out and "#*# <---" in out
    with_gcode = "[gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS]\ngcode:\nvariable_nozzle_warm: 40\n"
    assert a.render_orphan_settings(with_gcode) == with_gcode          # stands alone: left as it is
    assert a.render_orphan_settings(out) == out                        # once is enough


@pytest.mark.parametrize("host,name", [("voron", "Voron"), ("voron-24", "Voron 24"), ("desk.local", "Desk"), ("my_printer", "My Printer")])
def test_a_strangers_printer_is_named_for_people_from_its_network_name(host, name):
    facts = {"host": host, "moonraker": {"service": True, "conf": None}, "kiosk": {"enabled": False},
             "klipperscreen": {"installed": False}, "panel_output": None}
    assert a.default_settings(facts)["printer_name"] == name


# ── relay names for printers set up by the install command (testers get names, 5 October 2026) ─────────

class FakeRelay:
    """The hosted relay's claim API: POST /houses {name, invite?} -> 201, 409 with suggestions, or 403 for a code
    that is no good; GET /houses/<name>; POST /houses/<name>/invite {code}."""
    def __init__(self, taken=(), suggest=None, carried=False, invites=(), forgotten=(), reserved=("bench", "bench-box", "printers")):
        import http.server, threading
        self.taken, self.claims, outer = set(taken), [], self
        self.invites, self.forgotten, self.carried, self.brought = set(invites), set(forgotten), {}, []
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def _send(self, code, body):
                b = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            def _use(self, code):
                if code not in outer.invites:
                    return False
                outer.invites.discard(code)
                return True
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("/invite"):
                    name = self.path.split("/")[2]
                    outer.brought.append((name, body["code"]))
                    if name in outer.forgotten:
                        return self._send(404, {"detail": "No house by that name holds that key."})
                    if not self._use(body["code"]):
                        return self._send(403, {"detail": {"why": "invite", "message": "That invite code was used already."}})
                    outer.carried[name] = True
                    return self._send(200, {"name": name, "carried": True})
                name = body["name"]
                outer.claims.append((name, body["invite"]) if "invite" in body else name)
                if "invite" in body and body["invite"] not in outer.invites:
                    return self._send(403, {"detail": {"why": "invite", "message": "That invite code isn't one of ours. Check it for a typo."}})
                if name in reserved:
                    return self._send(422, {"detail": "That one is kept for the service itself."})
                if name in outer.taken:
                    return self._send(409, {"detail": {"why": "taken", "suggestions": (suggest or {}).get(name, [])}})
                outer.taken.add(name)
                outer.carried[name] = "invite" in body and self._use(body["invite"])
                self._send(201, {"name": name, "address": f"{name}.elyir.app", "secret": "s3cret", "relay": {},
                                 "carried": outer.carried[name]})
            def do_GET(self):
                name = self.path.split("/")[2]
                if name in outer.forgotten:
                    return self._send(404, {"detail": "No house by that name holds that key."})
                self._send(200, {"carried": carried or outer.carried.get(name, False)})
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
    def close(self):
        self.server.shutdown()


@pytest.fixture
def relay_rig(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "DOOR_STATE", tmp_path / "state")
    monkeypatch.setattr(a, "RELAY_STATE", tmp_path / "state" / "relay.json")
    monkeypatch.setattr(a, "RELAY_NEXT", tmp_path / "state" / "relay-next.json")
    monkeypatch.setattr(a, "RELAY_FORMER", tmp_path / "state" / "relay-former.json")
    monkeypatch.setattr(a, "load_cloud", lambda: {})
    monkeypatch.setattr(a, "machine_tag", lambda: "4f2a")
    saved = []
    monkeypatch.setattr(a, "save_settings", lambda facts, s: saved.append(dict(s)))
    return saved


def test_a_name_someone_has_gets_the_relays_suggestion_and_is_kept(relay_rig):
    relay = FakeRelay(taken={"voron"}, suggest={"voron": ["voron-2"]})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "voron", "relay_api": relay.url})
    a.RemoteName().apply(c)
    relay.close()
    assert relay.claims == ["voron", "voron-2"]
    assert c.s["remote_name"] == "voron-2" and relay_rig[-1]["remote_name"] == "voron-2"
    assert a.door_address(c.s) == "voron-2.elyir.app"
    assert any("voron was taken" in n for n in c.notes)


def test_without_suggestions_the_machine_tells_two_vorons_apart(relay_rig):
    relay = FakeRelay(taken={"voron"})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "voron", "relay_api": relay.url})
    a.RemoteName().apply(c)
    relay.close()
    assert relay.claims == ["voron", "voron-4f2a"] and c.s["remote_name"] == "voron-4f2a"


def test_a_name_the_relay_keeps_for_itself_becomes_this_machines_own(relay_rig):
    relay = FakeRelay()
    c = a.Ctx({}, {"remote": "relay", "remote_name": "printers", "relay_api": relay.url})
    a.RemoteName().apply(c)
    relay.close()
    assert relay.claims == ["printers", "printers-4f2a"] and c.s["remote_name"] == "printers-4f2a"


def test_no_relay_never_fails_the_install_and_the_door_waits(relay_rig):
    c = a.Ctx({}, {"remote": "relay", "remote_name": "voron", "relay_api": "http://127.0.0.1:9"})
    a.RemoteName().apply(c)                                          # nothing listens on port 9: no answer
    assert any("no public name yet (no answer from the relay)" in n for n in c.notes)
    assert a.door_address(c.s) is None
    assert a.DoorServices().check(c) == (True, "waits for its public name")


def test_the_terminal_pairs_a_phone_only_once_the_name_is_carried(relay_rig, monkeypatch):
    relay = FakeRelay(carried=False)
    s = {"remote": "relay", "remote_name": "desk", "relay_api": relay.url, "port": "8088"}
    a.RemoteName().apply(a.Ctx({}, s))
    lines = a.pair_lines({"host": "desk"}, s)
    relay.close()
    assert lines[0] == "Scan this with your phone, or open http://desk.local:8088/"
    assert "once Elyir approves this printer's name" in lines[-1]


def test_an_invite_at_install_is_carried_at_once(relay_rig):
    relay = FakeRelay(invites={"K7QX-M2PD-9HTF"})
    a.save_relay({"invite": "K7QX-M2PD-9HTF"})                   # elyir-bench apply --invite (install.sh --invite)
    c = a.Ctx({}, {"remote": "relay", "remote_name": "desk", "relay_api": relay.url})
    assert a.RemoteName().check(c) == (False, "desk not claimed yet")
    a.RemoteName().apply(c)
    assert relay.claims == [("desk", "K7QX-M2PD-9HTF")]
    assert "invite" not in a.load_relay() and a.door_address(c.s) == "desk.elyir.app"
    assert a.RemoteName().check(c) == (True, "desk.elyir.app, carried by the relay")
    relay.close()
    assert any("with the invite code" in n for n in c.notes)


def test_a_mistyped_code_at_install_still_claims_the_name_and_says_why(relay_rig):
    relay = FakeRelay()
    a.save_relay({"invite": "AAAA-BBBB-CCCC"})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "desk", "relay_api": relay.url})
    a.RemoteName().apply(c)
    relay.close()
    assert relay.claims == [("desk", "AAAA-BBBB-CCCC"), "desk"]
    assert a.door_address(c.s) == "desk.elyir.app" and "invite" not in a.load_relay()
    assert any("invite code wasn't used: That invite code isn't one of ours" in n for n in c.notes)
    assert any("elyir-bench remote invite <code>" in n for n in c.notes)


def test_set_up_without_a_code_and_bring_one_later(relay_rig, monkeypatch):
    restarted = []
    monkeypatch.setattr(a, "is_active", lambda u: True)
    monkeypatch.setattr(a, "sudo", lambda *args, **kw: restarted.append(args[-1]))
    relay = FakeRelay(invites={"K7QX-M2PD-9HTF"})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "desk", "relay_api": relay.url})
    a.RemoteName().apply(c)                                          # the install, no code
    assert a.RemoteName().check(c) == (True, "desk.elyir.app, claimed; waiting for the relay to carry it")
    a.save_relay({**a.load_relay(), "invite": "K7QX-M2PD-9HTF"})   # elyir-bench remote invite k7qx-m2pd-9htf
    assert a.RemoteName().check(c) == (False, "desk.elyir.app, claimed; an invite code waits to be used")
    a.RemoteName().apply(c)
    assert relay.claims == ["desk"] and relay.brought == [("desk", "K7QX-M2PD-9HTF")]   # same name, same secret
    assert a.RemoteName().check(c) == (True, "desk.elyir.app, carried by the relay")
    relay.close()
    assert "invite" not in a.load_relay() and a.load_relay()["secret"] == "s3cret"
    assert restarted == ["elyir-bench-caddy.service", "elyir-bench-frpc.service"]


def test_a_code_brought_after_the_relay_let_the_name_go_claims_it_again(relay_rig):
    relay = FakeRelay(invites={"K7QX-M2PD-9HTF"}, forgotten={"desk"})   # a day unapproved: let go, free again
    a.save_relay({"name": "desk", "address": "desk.elyir.app", "secret": "old", "invite": "K7QX-M2PD-9HTF"})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "desk", "relay_api": relay.url})
    assert a.RemoteName().check(c) == (False, "the relay doesn't know desk any more")
    a.RemoteName().apply(c)
    relay.close()
    assert relay.brought == [("desk", "K7QX-M2PD-9HTF")] and relay.claims == [("desk", "K7QX-M2PD-9HTF")]
    assert a.load_relay()["secret"] == "s3cret" and "invite" not in a.load_relay()


def test_a_code_waits_when_the_relay_doesnt_answer(relay_rig):
    a.save_relay({"name": "desk", "address": "desk.elyir.app", "secret": "s", "invite": "K7QX-M2PD-9HTF"})
    c = a.Ctx({}, {"remote": "relay", "remote_name": "desk", "relay_api": "http://127.0.0.1:9"})
    a.RemoteName().apply(c)
    assert a.load_relay()["invite"] == "K7QX-M2PD-9HTF"
    assert any("the invite code waits: no answer from the relay" in n for n in c.notes)


def test_an_invite_code_however_it_was_typed():
    assert a.invite_code("k7qx m2pd 9htf") == a.invite_code("K7QX-M2PD-9HTF") == "K7QX-M2PD-9HTF"
    assert a.invite_code("K7QX-M2PD") is None and a.invite_code("") is None


def test_the_waiting_terminal_says_how_to_use_a_code(relay_rig):
    relay = FakeRelay()
    s = {"remote": "relay", "remote_name": "desk", "relay_api": relay.url, "port": "8088"}
    a.RemoteName().apply(a.Ctx({}, s))
    lines = a.pair_lines({"host": "desk"}, s)
    relay.close()
    assert "`elyir-bench remote invite <code>` does it now." in lines[-1]


def test_new_printers_ask_for_a_name_and_the_check_says_so_first(monkeypatch):
    facts = {"host": "voron", "moonraker": {"service": True, "conf": None}, "kiosk": {"enabled": False},
             "klipperscreen": {"installed": False}, "panel_output": None}
    s = a.default_settings({**facts, "public_name": "p-k7qx2mna"})
    assert s["remote"] == "relay" and s["remote_name"] == "p-k7qx2mna"      # never the hostname: it would be public
    monkeypatch.setattr(a, "glibc", lambda: (2, 41))
    monkeypatch.setattr(a.os, "uname", lambda: type("U", (), {"machine": "aarch64"})())
    lines, code = a.check_report(board_facts(host="voron"), {**s, "port": "8088"})
    assert "It asks Elyir's relay for p-k7qx2mna.elyir.app, for notifications and your phone away from home" in lines


def test_the_public_name_is_the_same_every_time_and_says_nothing_about_the_printer(monkeypatch):
    files = {"/etc/machine-id": "4f2a9c\n", "/sys/firmware/devicetree/base/serial-number": "10000000abcdef\0"}
    monkeypatch.setattr(a, "read", lambda path, default="": files.get(str(path), default))
    name = a.public_name()
    assert name == a.public_name() and a.re.fullmatch(r"p-[a-z2-7]{8}", name)
    files["/sys/firmware/devicetree/base/serial-number"] = "10000000fedcba\0"
    assert a.public_name() != name                                        # two cards from one image differ


def test_a_printer_that_holds_a_name_keeps_it_when_its_settings_never_said(tmp_path, monkeypatch, relay_rig):
    facts = {"host": "voron", "home": str(tmp_path), "public_name": "p-k7qx2mna", "moonraker": {"service": True, "conf": None},
             "kiosk": {"enabled": False}, "klipperscreen": {"installed": False}, "panel_output": None}
    monkeypatch.setattr(a, "settings_path", lambda f: tmp_path / "elyir-bench.conf")
    (tmp_path / "elyir-bench.conf").write_text("[elyir-bench]\nprinter_name: Voron\n")
    a.save_relay({"name": "voron", "address": "voron.elyir.app", "secret": "s"})
    assert a.load_settings(facts)["remote_name"] == "voron"


def test_a_fresh_card_in_setup_counts_as_up():
    # docs/bring-it-over.md: with no printer.cfg the intent layer says setup, and an apply or an OS slot's trial is healthy
    import elyir_bench_os
    assert "setup" in a.STATES and "setup" in elyir_bench_os.INTENT_STATES


def test_network_wait_off_and_back(monkeypatch, tmp_path):
    # network_wait: off (the default) stops every boot waiting ~6 s for the Wi-Fi; on puts back only a wait
    # this step turned off, never one the person had turned off themselves
    state, enabled, calls = {}, {"on": True}, []
    monkeypatch.setattr(a, "unit_exists", lambda u: u == a.NM_WAIT_UNIT)
    monkeypatch.setattr(a, "is_enabled", lambda u: enabled["on"])
    monkeypatch.setattr(a, "load_state", lambda: dict(state))
    monkeypatch.setattr(a, "save_state", lambda st: state.update(st))
    def sudo(*cmd, **kw):
        calls.append(cmd)
        enabled["on"] = cmd[1] == "enable"
    monkeypatch.setattr(a, "sudo", sudo)
    step = a.NetworkWait()
    c = a.Ctx({}, {})
    assert step.check(c) == (False, "every boot waits for the Wi-Fi")
    step.apply(c)
    assert calls[-1] == ("systemctl", "disable", a.NM_WAIT_UNIT) and state["network_wait_disabled"]
    assert step.check(c)[0]
    c = a.Ctx({}, {"network_wait": "on"})
    assert not step.check(c)[0]
    step.apply(c)
    assert calls[-1] == ("systemctl", "enable", a.NM_WAIT_UNIT) and step.check(c)[0]
    # turned off by hand, not by us: on leaves it alone
    state.clear(); enabled["on"] = False
    assert step.check(a.Ctx({}, {"network_wait": "on"})) == (True, "on: waits for the Wi-Fi")
    assert f"systemctl * {a.NM_WAIT_UNIT}" in a.render_sudoers("pi").replace(a.sudo_bin("systemctl"), "systemctl")


def test_saving_the_settings_keeps_a_staging_printers_own_lines(tmp_path):
    """cloud_api and printers_app are set by hand (docs/cloud.md, A staging printer); an apply once dropped them."""
    s = {"printer_name": "Studio", "cloud_api": "https://cloud-staging.elyir.app", "printers_app": "https://printers-staging.elyir.app"}
    text = _saved(a, {"moonraker": {}}, s, tmp_path)
    assert "cloud_api: https://cloud-staging.elyir.app\n" in text and "printers_app: https://printers-staging.elyir.app\n" in text
    back = a.load_settings({"printer_data": str(tmp_path), "host": "studio", "kiosk": {"enabled": False},
                            "klipperscreen": {"installed": False}, "panel_output": None, "moonraker": {}})
    assert back["cloud_api"] == "https://cloud-staging.elyir.app" and back["printers_app"] == "https://printers-staging.elyir.app"
    assert "cloud_api" not in _saved(a, {"moonraker": {}}, {"printer_name": "Workshop"}, tmp_path)


# ---- a new public name (docs/door.md, *A new name*) ---------------------------------------------------------------

OBI = {"name": "voron", "address": "voron.elyir.app", "secret": "old", "addr": "relay.elyir.app", "token": "t"}


def test_a_new_name_waits_until_the_relay_carries_it_and_the_printer_answers_its_old_one_meanwhile(relay_rig):
    relay = FakeRelay(taken={"voron"})
    a.save_relay(OBI)
    s = {"remote": "relay", "remote_name": "p-k7qx2mna", "relay_api": relay.url}
    c = a.Ctx({}, s)
    a.RemoteName().apply(c)
    assert relay.claims == ["p-k7qx2mna"] and a.load_relay()["name"] == "voron"          # not switched: not carried
    assert a.load_claim(a.RELAY_NEXT)["name"] == "p-k7qx2mna"
    assert a.door_address(s) == "voron.elyir.app" and any("stays voron.elyir.app" in n for n in c.notes)
    assert a.printer_id(s) == "voron"                                                      # the id doesn't move early
    ok, words = a.RemoteName().check(c)
    assert not ok and "waits for the relay to carry it" in words
    a.RemoteName().apply(c)
    assert relay.claims == ["p-k7qx2mna"]                                                 # asked once, kept aside
    relay.close()


def test_once_carried_the_printer_moves_and_keeps_its_old_name_its_id_and_a_tunnel_for_phones_that_knew_it(relay_rig, tmp_path):
    relay = FakeRelay(taken={"voron"})
    a.save_relay(OBI)
    s = {"remote": "relay", "remote_name": "p-k7qx2mna", "relay_api": relay.url, "printer_name": "Workshop", "port": "8088"}
    c = a.Ctx({"user": "pi"}, s)
    a.RemoteName().apply(c)
    relay.carried["p-k7qx2mna"] = True
    a.RemoteName().apply(c)
    relay.close()
    assert a.load_relay()["name"] == "p-k7qx2mna" and not a.RELAY_NEXT.exists()
    assert a.load_claim(a.RELAY_FORMER)["secret"] == "old"                                 # never thrown away
    assert relay_rig[-1]["remote_former"] == "voron" and relay_rig[-1]["printer_id"] == "voron"
    assert a.door_address(s) == "p-k7qx2mna.elyir.app"
    want = a.DoorServices()._want(c)
    former = want[str(a.DOOR_CONF / "frpc-former.toml")][0]
    assert 'user = "voron"' in former and 'customDomains = ["voron.elyir.app"]' in former and 'secret = "old"' in former
    assert 'customDomains = ["p-k7qx2mna.elyir.app"]' in want[str(a.DOOR_CONF / "frpc.toml")][0]
    caddy = want[str(a.DOOR_CONF / "Caddyfile")][0]
    assert "p-k7qx2mna.elyir.app:9443 {" in caddy and "voron.elyir.app:9443 {" in caddy
    assert "--printer-id voron " in want[f"/etc/systemd/system/elyir-bench-door.service"][0]   # phones know it as before
    assert f"/etc/systemd/system/{a.FORMER_UNIT}" in want
    s["remote_former"] = ""                                                               # every phone moved
    assert str(a.DOOR_CONF / "frpc-former.toml") not in a.DoorServices()._want(c)
    assert "voron.elyir.app:9443" not in a.render_caddyfile(s, "p-k7qx2mna.elyir.app")


def test_remote_phones_says_who_still_uses_the_old_name(relay_rig, capsys):
    a.save_relay(OBI, a.RELAY_FORMER)
    (a.DOOR_STATE / "door").mkdir(parents=True)
    (a.DOOR_STATE / "door" / "phones.json").write_text(json.dumps([
        {"id": "1", "name": "Sam's iPhone", "last_seen": 1800000000, "via": "voron.elyir.app"},
        {"id": "2", "name": "Alex's iPad", "last_seen": 1800000000, "via": "192-168-1-20.voron.home.elyir.app"},
        {"id": "3", "name": "Jo's phone", "last_seen": 1800000000, "via": "p-k7qx2mna.elyir.app"}]))
    a.remote_phones({"remote_former": "voron"})
    out = capsys.readouterr().out
    assert out.count("still on the old name") == 2 and "2 of 3 not on the new name yet" in out


def test_a_phone_not_seen_since_the_move_is_not_counted_as_moved(relay_rig, capsys):
    a.save_relay({**OBI, "since": 1800000000}, a.RELAY_FORMER)
    (a.DOOR_STATE / "door").mkdir(parents=True)
    (a.DOOR_STATE / "door" / "phones.json").write_text(json.dumps([
        {"id": "1", "name": "Sam's iPhone", "last_seen": 1700000000},
        {"id": "2", "name": "Jo's phone", "last_seen": 1800000100, "via": "p-k7qx2mna.elyir.app"}]))
    a.remote_phones({"remote_former": "voron"})
    out = capsys.readouterr().out
    assert "not seen since the move" in out and "1 of 2 not on the new name yet" in out


# ---- a report to Elyir (design/report/, B) -------------------------------------------------------------------------

def test_a_report_never_carries_a_password_a_key_or_a_token():
    text = "\n".join(["[wifi]", "psk = hunter2hunter2", "api_key: 1234567890abcdef", "password=letmein",
                      "Authorization: Bearer abcdefghijklmnop", "GET /websocket?access_token=sekret123 200",
                      "jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "sub elyir-bench-token.k7qx2mna9",
                      "relay secret: s3cretvalue-from-relay", "Klipper state: Ready"])
    out = a.scrub_report(text, known=["s3cretvalue-from-relay"])
    for gone in ("hunter2", "1234567890abcdef", "letmein", "abcdefghijklmnop", "sekret123", "eyJhbGci", "k7qx2mna9", "s3cretvalue"):
        assert gone not in out, gone
    assert "Klipper state: Ready" in out and out.count(a.REPORT_REMOVED) >= 8


def test_a_report_gathers_scrubbed_files_and_comes_back_as_a_code(tmp_path, monkeypatch, relay_rig):
    import http.server, threading, io as _io, tarfile as _tar
    pdata = tmp_path / "printer_data"
    (pdata / "logs").mkdir(parents=True)
    (pdata / "config").mkdir()
    (pdata / "logs" / "klippy.log").write_text("MCU 'mcu' shutdown: Heater extruder not heating at expected rate\n")
    (pdata / "config" / "printer.cfg").write_text("[mcu]\nserial: /dev/serial/by-id/x\n")
    (pdata / "config" / "elyir-bench.conf").write_text("[elyir-bench]\nprinter_name: Workshop\n")
    a.save_relay({"name": "p-k7qx2mna", "address": "p-k7qx2mna.elyir.app", "secret": "relay-secret-value", "addr": "", "token": ""})
    monkeypatch.setattr(a, "run", lambda *args, **kw: type("R", (), {"stdout": "door: token=relay-secret-value seen\n"})())
    monkeypatch.setattr(a, "plan", lambda c: [("ok", "release", "2026.10.18-abc")])
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            got["type"] = self.headers["Content-Type"]
            b = json.dumps({"code": "R-7K2Q"}).encode()
            self.send_response(201); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    facts = {"printer_data": str(pdata), "host": "workshop", "model": "Raspberry Pi 5", "os": "Debian 13", "arch": "aarch64",
             "moonraker": {"url": "http://127.0.0.1:9"}}
    s = {"printer_name": "Workshop", "cloud_api": f"http://127.0.0.1:{server.server_address[1]}"}
    meta, bundle = a.gather_report(facts, s, "wrong", {"headline": "The nozzle or bed isn't heating properly."})
    with _tar.open(fileobj=_io.BytesIO(bundle), mode="r:gz") as t:
        names = t.getnames()
        everything = b"".join(t.extractfile(n).read() for n in names)
    assert {"logs/klippy.log", "config/printer.cfg", "state/install-check.txt", "report.json"} <= set(names)
    assert b"relay-secret-value" not in everything and b"not heating at expected rate" in everything
    meta["note"] = "It stopped mid-print"
    assert a.send_report(s, meta, bundle) == "R-7K2Q"
    server.shutdown()
    assert got["type"].startswith("multipart/form-data") and b'"kind": "wrong"' in got["body"] and bundle in got["body"]
    meta2, none = a.gather_report(facts, s, "idea", details=False)
    assert none is None and "files" not in meta2                       # an idea sends only words
