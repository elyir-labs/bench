import pathlib
import subprocess

FIT = pathlib.Path(__file__).resolve().parents[2] / "kiosk" / "fit.sh"

WLR = """DSI-1 "Unknown"
  Physical size: 87x154 mm
  Enabled: yes
  Modes:
    720x1280 px, 60.000000 Hz (preferred, current)
  Position: 0,0
  Transform: {turn}
  Scale: 1.000000
HDMI-A-1 "Other"
  Physical size: 600x340 mm
  Modes:
    1920x1080 px, 60.000000 Hz (current)
  Transform: normal
"""
XRANDR = """Screen 0: minimum 320 x 200, current 800 x 480, maximum 8192 x 8192
HDMI-1 connected primary 800x480+0+0 (normal left inverted right x axis y axis) 108mm x 65mm
   800x480       60.00*+
DSI-1 disconnected (normal left inverted right x axis y axis)
"""


def run(call: str, stdin: str = "") -> str:
    r = subprocess.run(["bash", "-c", f'. "{FIT}"; {call}'], input=stdin, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_reads_the_panel_not_the_other_output():
    assert run("panel_geometry_wlr DSI-1", WLR.format(turn="normal")) == "720 1280 87 154"


def test_a_turned_panel_swaps_its_pixels_only():
    assert run("panel_geometry_wlr DSI-1", WLR.format(turn="90")) == "1280 720 87 154"
    assert run("panel_geometry_wlr DSI-1", WLR.format(turn="270")) == "1280 720 87 154"
    assert run("panel_geometry_wlr DSI-1", WLR.format(turn="180")) == "720 1280 87 154"


def test_reads_xrandr():
    assert run("panel_geometry_x HDMI-1", XRANDR) == "800 480 108 65"


def test_size_comes_from_the_display():
    assert run("panel_fit 800 480 154 86") == "6.9 1"
    assert run("panel_fit 800 480 76 46") == "3.5 1"


def test_nothing_reported_stays_unknown():
    assert run("panel_fit 800 480 0 0") == "0.0 1"
    assert run("panel_fit 800 480 16 9") == "0.0 1"


def test_the_setting_beats_the_display():
    assert run("panel_fit 800 480 154 86 3.5") == "3.5 1"
    assert run("panel_fit 800 480 0 0 5") == "5.0 1"


def test_a_tall_panel_scales_to_the_phone_layout():
    assert run("panel_fit 720 1280 87 154") == "7.0 1.5"
    assert run("panel_fit 480 800 65 109") == "5.0 1"
    assert run("panel_fit 1280 720 87 154") == "7.0 1"


def test_the_release_carries_it():
    build = (FIT.parents[1] / "scripts" / "build-release.sh").read_text()
    assert '"$SRC/kiosk/fit.sh"' in build


def launch(tmp_path, wlr: str, **env) -> str:
    """The real start.sh inside cage, with Chromium and wlr-randr stood in: the command line it would run."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "wlr-randr").write_text(f"#!/bin/bash\n[ $# -eq 0 ] && cat <<'OUT'\n{wlr}OUT\nexit 0\n")
    (stubs / "chromium").write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
    for f in stubs.iterdir():
        f.chmod(0o755)
    r = subprocess.run(
        ["bash", str(FIT.parent / "start.sh"), "--in-cage"], capture_output=True, text=True, check=True,
        env={"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(tmp_path), "ELYIR_BENCH_OUTPUT": "DSI-1",
             "ELYIR_BENCH_URL": "http://localhost:8088/", **env},
    )
    return r.stdout


def test_launch_tall_panel(tmp_path):
    args = launch(tmp_path, WLR.format(turn="normal"))
    assert "http://localhost:8088/?panel_in=7.0\n" in args
    assert "--force-device-scale-factor=1.5\n" in args


def test_launch_turned_to_landscape(tmp_path):
    args = launch(tmp_path, WLR.format(turn="90"), ELYIR_BENCH_ROTATION="90")
    assert "?panel_in=7.0\n" in args and "--force-device-scale-factor" not in args


def test_launch_size_by_hand_on_a_silent_panel(tmp_path):
    silent = WLR.format(turn="normal").replace("87x154", "0x0")
    assert "?panel_in" not in launch(tmp_path, silent)
    assert "?panel_in=3.5\n" in launch(tmp_path, silent, ELYIR_BENCH_PANEL_SIZE="3.5")


def test_launch_keeps_lite_beside_the_size(tmp_path):
    assert "?lite=1&panel_in=7.0\n" in launch(tmp_path, WLR.format(turn="normal"), ELYIR_BENCH_RENDER="cpu")
