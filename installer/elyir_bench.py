#!/usr/bin/env python3
"""Elyir Bench installer: works out what this printer has, then makes Elyir Bench true on it.

    elyir-bench detect            facts about this machine, as JSON
    elyir-bench plan              what apply would change
    elyir-bench apply [release]   converge (optionally switching to a new release tarball)
    elyir-bench doctor            check every step without changing anything
    elyir-bench rollback          switch back to the previous release
    elyir-bench panel elyir-bench|klipperscreen|none
    elyir-bench startmacro on|off Elyir Bench's start macro in printer.cfg (docs/start-macro.md)
    elyir-bench check             what the install command says first (this board, what it adds)
    elyir-bench pair              a QR code for your phone
    elyir-bench remove            take it off again and put KlipperScreen back
    elyir-bench bring scan|plan <id>|apply <id> [--gcodes]|address <address>
                                bring an old printer's setup over (docs/bring-it-over.md)

Runs on the printer as the printer's user (never root) and uses `sudo -n` for system
changes. Standard library only. See docs/installer.md.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import contextlib
import datetime as _dt
import fnmatch
import io
import hashlib
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import struct
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

HOME = Path.home()
BASE = Path(os.environ.get("ELYIR_BENCH_HOME", HOME / "elyir-bench"))
RELEASES = BASE / "releases"
CURRENT = BASE / "current"
STATE = BASE / "state.json"
NM_WAIT_UNIT = "NetworkManager-wait-online.service"   # what holds the boot until the Wi-Fi is up (network_wait)
KEEP_RELEASES = 3
KIOSK_UNIT = "elyir-bench-kiosk.service"
# cage (Wayland) where the OS packages it; plain X where it doesn't (Debian 11, BTT CB1 images)
KIOSK_PACKAGES = {
    "cage": ["cage", "chromium", "wlr-randr", "grim"],
    "x11": ["chromium", "xinit", "xserver-xorg-core", "xserver-xorg-input-libinput", "xserver-xorg-legacy",
            "x11-xserver-utils", "x11-apps"],
}
XWRAPPER = "/etc/X11/Xwrapper.config"
# The kiosk service has no console, so X's wrapper must let it start the server anyway
XWRAPPER_CONF = "# Managed by elyir-bench: the panel's X server is started by a service, not a console login\n" \
                "needs_root_rights=yes\nallowed_users=anybody\n"
NGINX_SITE = "elyir-bench"
SUDOERS = "/etc/sudoers.d/elyir-bench"
SECURE_PATH = ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]
DT_BASE = Path("/sys/firmware/devicetree/base")
# The door (docs/door.md): reaching the printer from outside the house.
DOOR_STATE = BASE / "state"
RELAY_STATE = DOOR_STATE / "relay.json"
# Moving to a new public name (docs/door.md, *A new name*): the new claim waits in RELAY_NEXT until the relay carries
# it, then the old one moves to RELAY_FORMER and a second tunnel answers it until remote_former is cleared.
RELAY_NEXT = DOOR_STATE / "relay-next.json"
RELAY_FORMER = DOOR_STATE / "relay-former.json"
FORMER_UNIT = "elyir-bench-frpc-former.service"
DOOR_CONF = BASE / "door"
DOOR_BIN = BASE / "bin"
DOOR_VENV = BASE / "venv"
DOOR_UNITS = ("elyir-bench-door.service", "elyir-bench-caddy.service", "elyir-bench-frpc.service")
# The printer's name at home (docs/door.md, *Home first*): its certificate, kept by a timer.
HOMECERT_UNITS = ("elyir-bench-homecert.service", "elyir-bench-homecert.timer")
HOME_FILE = DOOR_STATE / "home.json"
HOME_CERT = DOOR_STATE / "home-cert"
LEGO_DIR = DOOR_STATE / "lego"
DEFAULT_RELAY_API = "https://api.elyir.app"
DEFAULT_ACME_CA = "https://acme-v02.api.letsencrypt.org/directory"
# Pinned by checksum: what was tested is what runs. Moving a version means checking it again.
DOOR_BINARIES = {
    "caddy": {"version": "2.11.4",
              "url": "https://github.com/caddyserver/caddy/releases/download/v{v}/caddy_{v}_linux_{arch}.tar.gz",
              "member": "caddy",
              "sha256": {"arm64": "52d42ae12b3462097e9868da6dfed3c9648ae12edd3b3638102312af84cb6904",
                         "amd64": "527fbf917c39189a1e3b31d34fa955601680b2d5c8055d2a87b8b9588dec7bb9"}},
    "lego": {"version": "4.26.0",
             "url": "https://github.com/go-acme/lego/releases/download/v{v}/lego_v{v}_linux_{arch}.tar.gz",
             "member": "lego",
             "sha256": {"arm64": "bcc781fe8c01291585e7eafb0a1539a33245cafac448775bdf0d45b6fedb703f",
                        "amd64": "9a5963e0b3961d5d2863c3055ea608340630815829d9a548ca882511b643d948"}},
    "frpc": {"version": "0.71.0",
             "url": "https://github.com/fatedier/frp/releases/download/v{v}/frp_{v}_linux_{arch}.tar.gz",
             "member": "frp_{v}_linux_{arch}/frpc",
             "sha256": {"arm64": "f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266",
                        "amd64": "84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"}},
}
# Print a model (docs/slicer.md): OrcaSlicer's command line, run by the slicing service.
SLICER_DIR = BASE / "slicer"                      # the engine and the service's rendered config
SLICER_WORK = DOOR_STATE / "slicer"               # models and G-code, kept a day
SLICER_UNIT = "elyir-bench-slicer.service"
BENCH_UNIT = "elyir-bench-bench.service"           # a Bench Box's own service (bench/bench_service.py, docs/bench.md)
# Bench's own filament-unit service (units/, design/ace-driver/) in place of KlipperACE, with filament_units: elyir
UNITS_UNIT = "elyir-units.service"
UNITS_CFG = "elyir_units.cfg"
UNITS_INCLUDE = "[include elyir_units.cfg]"
UNITS_STATE = "elyir-units.json"
UNITS_TOOLS = 16                                   # T0..T15, as KlipperACE gives four units
KLIPPERACE_INCLUDES = ("[include ace.cfg]", "[include ace_diagnostics.cfg]")
UNITS_OFF = "# off while Bench's filament-unit service runs: "
# elyir-bench.conf keys -> the service's tool change settings (units/toolchange.py DEFAULTS)
UNITS_SETTINGS = {"units_before_macro": ("before_macro", str), "units_after_macro": ("after_macro", str),
                  "units_sensor_to_nozzle": ("sensor_to_nozzle", float), "units_park": ("park", float),
                  "units_temp": ("temp", int), "units_purge_moves": ("purge_moves", str),
                  "units_push_start": ("push_start", str), "units_push_end": ("push_end", str),
                  "units_backoff": ("backoff", float)}
BENCH_PORT = 8096
SLICER_PORT = 8095
# A new printer's first Wi-Fi (docs/setup.md, setup/wifi_setup.py): with no network, its own setup Wi-Fi
WIFI_PORT = 8097
WIFI_UNIT = "elyir-bench-wifi.service"
WIFI_ADDR = "10.42.0.1"                           # the setup Wi-Fi's own address (wifi_setup.SETUP_ADDR)
WIFI_SITE = "elyir-bench-setup"                     # nginx: port 80 of that address, for a phone's sign-in sheet
WIFI_DNS = Path("/etc/NetworkManager/dnsmasq-shared.d/elyir-bench-setup.conf")
# The power button turns the printer off like Care's Turn off (design/power/): logind leaves a short press to us
POWER_KEY_UNIT = "elyir-bench-power-key.service"
LOGIND_POWER = Path("/etc/systemd/logind.conf.d/elyir-bench-power-key.conf")
LOGIND_POWER_CONF = ("# Managed by elyir-bench (design/power/): a short press of the power button is Elyir Bench's Turn off\n"
                     "# (elyir-bench-power-key.service: the nozzle cools first). A long press still halts at once.\n"
                     "[Login]\nHandlePowerKey=ignore\nHandlePowerKeyLongPress=poweroff\n")
WIFI_DNS_CONF = ("# Managed by elyir-bench (docs/setup.md): on the setup Wi-Fi every name is the printer, so a phone's\n"
                 f"# sign-in check finds the setup page.\naddress=/#/{WIFI_ADDR}\n")
SLICER_HEADER = "X-Elyir-Bench-Printer"             # who's asking, set by the printer's nginx (slicer/slice_service.py)
SLICER_MDNS = "_elyir-slicer._tcp.local"          # a slicer that lends says so on the Wi-Fi (avahi), for slicer: auto
SLICER_AVAHI = Path("/etc/avahi/services/elyir-slicer.service")
PRINTER_MDNS = "_elyir-printer._tcp"             # every printer says so on the Wi-Fi, for a Bench Box to find it
PRINTER_AVAHI = Path("/etc/avahi/services/elyir-printer.service")
ORCA = {"version": "2.4.2",
        "urls": {"arm64": "https://github.com/SoftFever/OrcaSlicer/releases/download/v{v}/OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V{v}.AppImage",
                 "amd64": "https://github.com/SoftFever/OrcaSlicer/releases/download/v{v}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V{v}.AppImage"},
        "sha256": {"arm64": "e1a07275a25f176626c55a5df39e91bc4476d8c28ee4a3192ff758e29dd5c3ba",
                   "amd64": "d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd"},
        "glibc": (2, 39)}     # built on Ubuntu 24.04: Debian 13 or Ubuntu 24.04 and newer
# Orca's Linux build is a desktop build: it links these even when it only slices (found on workshop,
# Pi OS Lite, 2 October 2026). Its own launcher only looks for OpenGL in system folders.
ORCA_PACKAGES = ["libwebkit2gtk-4.1-0", "libjavascriptcoregtk-4.1-0", "libsoup-3.0-0", "libsecret-1-0",
                 "libgstreamer-plugins-base1.0-0", "libopengl0", "libglu1-mesa",
                 # what a Pi OS Lite without a desktop lacks (the Bench Box's Pi 4: exit 127, libSM.so.6 not found)
                 "libsm6", "libice6", "libmspack0t64"]
STATES = {"setup", "ready", "preparing", "printing", "needs_you", "finished", "problem"}   # setup: a fresh card with no printer.cfg
# Elyir Bench's start macro for a printer someone else set up (docs/start-macro.md): the release's
# printer/klipper/elyir-bench.cfg, written into the config folder, and one include line in printer.cfg
START_MACRO_FILE = "elyir-bench.cfg"
START_MACRO_INCLUDE = f"[include {START_MACRO_FILE}]"
START_MACRO_COMMAND = "gcode_macro ELYIR_BENCH_PRINT_START"   # in Klipper's object list once it has read the file


# ── small helpers ─────────────────────────────────────────────────────────────

class StepFailed(Exception):
    pass


def run(cmd: list[str], check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise StepFailed(f"{' '.join(cmd)} failed: {(p.stderr or p.stdout).strip()[-400:]}")
    return p


def sudo(*cmd: str, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    return run(["sudo", "-n", *cmd], check=check, timeout=timeout)


def sudo_write(path: str, content: str) -> None:
    p = subprocess.run(["sudo", "-n", "tee", path], input=content, capture_output=True, text=True)
    if p.returncode != 0:
        raise StepFailed(f"writing {path} failed: {p.stderr.strip()}")


def read(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return default


def http_json(url: str, timeout: float = 4.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_status(url: str, timeout: float = 4.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def systemd(unit: str, prop: str) -> str:
    return run(["systemctl", "show", unit, "-p", prop, "--value"], check=False).stdout.strip()


def unit_exists(unit: str) -> bool:
    return systemd(unit, "LoadState") == "loaded"


def is_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def is_enabled(unit: str) -> bool:
    return run(["systemctl", "is-enabled", "--quiet", unit], check=False).returncode == 0


def internet() -> bool:
    """Whether downloads can work now: a route out, and a name answered (github.com, where they come from).
    A new printer's first boot has neither (docs/image.md), and pip or a download would wait for nothing."""
    try:
        if not run(["ip", "-4", "route", "show", "default"], check=False).stdout.strip():
            return False
        return run(["getent", "hosts", "github.com"], check=False, timeout=6).returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return True      # no ip or getent here (not a Pi): can't tell, so don't hold anything back


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE)


# ── sudo ─────────────────────────────────────────────────────────────────────

def sudo_bin(name: str) -> str:
    """The path sudo will resolve `name` to (it searches secure_path, not $PATH)."""
    for d in SECURE_PATH:
        if os.access(f"{d}/{name}", os.X_OK):
            return f"{d}/{name}"
    return f"/usr/bin/{name}"


def sudo_mode() -> str:
    """full: passwordless sudo. elyir-bench: our narrow rule is installed.
    password: sudo works after a password. none: no sudo at all."""
    if run(["sudo", "-n", "true"], check=False).returncode == 0:
        return "full"
    if run(["sudo", "-n", "-l", sudo_bin("systemctl"), "daemon-reload"], check=False).returncode == 0:
        return "elyir-bench"
    groups = run(["id", "-nG"], check=False).stdout.split()
    return "password" if ("sudo" in groups or "wheel" in groups) else "none"


def render_sudoers(user: str) -> str:
    sc, nginx, tee, ln = sudo_bin("systemctl"), sudo_bin("nginx"), sudo_bin("tee"), sudo_bin("ln")
    apt = sudo_bin("apt-get")
    cmds = [
        f"{sc} restart moonraker", f"{sc} reload nginx", f"{sc} daemon-reload",
        f"{sc} * {KIOSK_UNIT}", f"{sc} * KlipperScreen.service",
        f"{nginx} -t -q",
        f"{tee} /etc/nginx/sites-available/{NGINX_SITE}", f"{tee} /etc/systemd/system/{KIOSK_UNIT}",
        f"{tee} {XWRAPPER}",
        f"{ln} -sf /etc/nginx/sites-available/{NGINX_SITE} /etc/nginx/sites-enabled/{NGINX_SITE}",
        f"{apt} update -q", f"{apt} install -y -q --no-install-recommends *",
        *(f"{tee} /etc/systemd/system/{u}" for u in DOOR_UNITS + HOMECERT_UNITS + (SLICER_UNIT, BENCH_UNIT)),
        *(f"{sc} * {u}" for u in DOOR_UNITS + HOMECERT_UNITS + (SLICER_UNIT, BENCH_UNIT)),
        # a slicer that lends says so on the Wi-Fi (docs/slicer.md, "Slicing for other printers")
        f"{tee} {SLICER_AVAHI}", f"{sudo_bin('mkdir')} -p {SLICER_AVAHI.parent}", f"{sudo_bin('rm')} -f {SLICER_AVAHI}",
        f"{tee} {PRINTER_AVAHI}",   # and every printer says so too, for a Bench Box (docs/bench.md)
        # printer or Bench Box (role): it stops saying so, and Klipper and Moonraker go off (or come back)
        f"{sudo_bin('rm')} -f {PRINTER_AVAHI}", " ".join(role_off_cmd()), f"{sc} enable --now klipper moonraker",
        # a new printer's first Wi-Fi (docs/setup.md): its service, its site and its DNS line ...
        f"{tee} /etc/systemd/system/{WIFI_UNIT}", f"{sc} * {WIFI_UNIT}", f"{tee} /etc/nginx/sites-available/{WIFI_SITE}",
        f"{ln} -sf /etc/nginx/sites-available/{WIFI_SITE} /etc/nginx/sites-enabled/{WIFI_SITE}",
        f"{tee} {WIFI_DNS}", f"{sudo_bin('mkdir')} -p {WIFI_DNS.parent}",
        # ... the setup Wi-Fi itself, with a network's password written into its keyfile through stdin ...
        f"{sudo_bin('nmcli')} *", f"{sudo_bin('rfkill')} unblock wifi",
        f"{sudo_bin('install')} -m 600 -o root -g root /dev/stdin /etc/NetworkManager/system-connections/elyir-bench-*.nmconnection",
        # ... and the name it's given there (elyir-bench rename)
        f"{sudo_bin('hostnamectl')} set-hostname *", f"{tee} /etc/hosts", f"{sc} restart avahi-daemon",
        # the power button (design/power/): its listener, logind leaving it a short press, and power off where there's
        # no printer to cool (a Bench Box)
        f"{tee} /etc/systemd/system/{POWER_KEY_UNIT}", f"{sc} * {POWER_KEY_UNIT}", f"{sudo_bin('mkdir')} -p {LOGIND_POWER.parent}",
        f"{tee} {LOGIND_POWER}", f"{sudo_bin('rm')} -f {LOGIND_POWER}", f"{sc} kill -s HUP systemd-logind", f"{sc} poweroff",
        f"{sc} reboot",   # a Bench Box's Restart (bench/box.py)
        f"{sc} * {NM_WAIT_UNIT}",   # network_wait
    ] + boot_screen_sudo_cmds() + bring_sudo_cmds()
    return ("# Managed by elyir-bench: lets the installer and the setup page manage Elyir Bench's own\n"
            "# services without a password. Remove this file to take that away.\n"
            f"{user} ALL=(root) NOPASSWD: " + ", \\\n    ".join(cmds) + "\n")


def bring_sudo_cmds() -> list[str]:
    """Bring it over (docs/bring-it-over.md): an old card in a USB reader, mounted read-only (ext4 without replaying
    its journal) under /run/elyir-bench-bring/<its name>, and unmounted after. Nothing else, and never read-write."""
    mount, mkdir, umount = sudo_bin("mount"), sudo_bin("mkdir"), sudo_bin("umount")
    out = []
    for g in BRING_DEV_GLOBS:
        mp = f"{BRING_MOUNTS}/{g}"
        out += [f"{mkdir} -p {mp}", f"{mount} -t ext4 -o ro\\,noload /dev/{g} {mp}", f"{mount} -t vfat -o ro /dev/{g} {mp}",
                f"{umount} {mp}"]
    return out


def ensure_sudo(c: "Ctx") -> None:
    """Ask for the password once (interactive runs only) and offer the narrow rule."""
    if not sys.stdin.isatty():
        raise StepFailed(
            f"{c.facts['user']} needs a password for sudo. Run this once from a terminal so it can ask "
            "(e.g. `./deploy.sh <host>` from your own shell, or `elyir-bench apply` on the printer).")
    print("  Elyir Bench needs admin rights to set up its web page and services.")
    if subprocess.run(["sudo", "-v"]).returncode != 0:
        raise StepFailed("sudo password not accepted")
    ans = input("  Let Elyir Bench manage its own services without asking again? "
                f"(adds a narrow rule in {SUDOERS}) [Y/n] ").strip().lower()
    if ans in ("", "y", "yes"):
        rule = render_sudoers(c.facts["user"])
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sudoers") as t:
            t.write(rule)
        try:
            sudo(sudo_bin("visudo"), "-cqf", t.name)
            sudo(sudo_bin("install"), "-m", "0440", "-o", "root", "-g", "root", t.name, SUDOERS)
        finally:
            os.unlink(t.name)
        c.notes.append(f"added {SUDOERS}; later updates and the setup page won't need a password")
    c.facts["sudo"] = "cached"


def apt_install(*packages: str) -> None:
    """Refresh the package lists first: a printer's can be months old, and the mirror has
    dropped the versions they name by then (404s on desk)."""
    sudo("apt-get", "update", "-q", timeout=600, check=False)
    try:
        sudo("apt-get", "install", "-y", "-q", "--no-install-recommends", *packages, timeout=1800)
    except StepFailed as e:
        # An old release whose security updates left the mirror (Debian 11 after its support ended): the lists still
        # name a file that's gone, so take the newest version that's still there.
        if "404" not in str(e):
            raise
        pinned = [older_apt_version(p) or p for p in packages]
        if pinned == list(packages):
            raise
        print(f"apt: {', '.join(packages)} not on the mirror any more; trying {', '.join(pinned)}", file=sys.stderr)
        sudo("apt-get", "install", "-y", "-q", "--no-install-recommends", *pinned, timeout=1800)


def apt_versions(policy: str) -> tuple[str | None, list[str]]:
    """The candidate and every version `apt-cache policy <one package>` lists, newest first."""
    cand = re.search(r"^\s+Candidate:\s*(\S+)", policy, re.M)
    versions = re.findall(r"^\s+(?:\*\*\*\s+)?(\S+)\s+\d+\s*$", policy, re.M)
    return (cand.group(1) if cand and cand.group(1) != "(none)" else None), versions


def older_apt_version(package: str) -> str | None:
    """package=<the newest version after the candidate>, or None when there's no other."""
    cand, versions = apt_versions(run(["apt-cache", "policy", package], check=False).stdout)
    older = [v for v in versions if v != cand]
    return f"{package}={older[0]}" if older else None


def kiosk_installable(packages: list[str]) -> list[str]:
    """Packages from `packages` this OS can't install at all."""
    out = run(["apt-cache", "policy", *packages], check=False).stdout
    missing, cur = [], None
    for line in out.splitlines():
        if line and not line.startswith(" "):
            cur = line.rstrip(":")
            if cur in packages and cur not in missing:
                missing.append(cur)
        elif cur and "Candidate:" in line and "(none)" not in line:
            if cur in missing:
                missing.remove(cur)
    return [p for p in packages if p in missing or p not in out]


def kiosk_backends() -> list[str]:
    """Kiosk backends this OS can run, best first: every package installed or installable."""
    return [b for b, pkgs in KIOSK_PACKAGES.items() if not kiosk_installable(pkgs)]


def kiosk_backend(facts: dict, s: dict) -> str | None:
    """cage or x11, from panel_backend in the settings (auto: the best one this OS can run)."""
    want = s.get("panel_backend", "auto")
    if want in KIOSK_PACKAGES:
        return want
    usable = facts.get("kiosk_backends", [])
    return usable[0] if usable else None


def kiosk_render(facts: dict, s: dict) -> str:
    """gpu or cpu, from panel_render (auto: a Raspberry Pi's GPU is driven everywhere we install;
    other boards, like the BTT Pi on Debian 11, end up emulating one on the CPU)."""
    want = s.get("panel_render", "auto")
    if want in ("gpu", "cpu"):
        return want
    model = facts.get("model") or ""
    return "gpu" if not model or "Raspberry Pi" in model else "cpu"


# ── detection ────────────────────────────────────────────────────────────────

def _u32(path: Path) -> int | None:
    try:
        b = path.read_bytes()
        return int.from_bytes(b[:4], "big") if len(b) >= 4 else None
    except OSError:
        return None


def _dt_phandles() -> dict[int, Path]:
    """phandle -> devicetree node, for following display graph links."""
    out: dict[int, Path] = {}
    for root, _dirs, files in os.walk(DT_BASE):
        if "phandle" in files:
            ph = _u32(Path(root) / "phandle")
            if ph is not None:
                out[ph] = Path(root)
    return out


def _platform_devices_by_of_node() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for dev in Path("/sys/bus/platform/devices").glob("*"):
        node = dev / "of_node"
        if node.exists():
            out[str(node.resolve())] = dev.resolve()
    return out


def _i2c_buses_of(dev: Path) -> set[int]:
    """i2c buses a device sits on or depends on (panel regulators and backlights live there)."""
    buses = {int(m) for m in re.findall(r"/i2c-(\d+)/", str(dev) + "/")}
    for entry in dev.glob("supplier:i2c:*"):
        m = re.match(r"supplier:i2c:(\d+)-", entry.name)
        if m:
            buses.add(int(m.group(1)))
    return buses


def detect_touch() -> list[dict]:
    devices, cur = [], {}
    for line in read("/proc/bus/input/devices").splitlines() + [""]:
        if not line.strip():
            if cur.get("name") and ("ABS" in cur.get("caps", "") or "touch" in cur["name"].lower()):
                devices.append(cur)
            cur = {}
        elif line.startswith("N: Name="):
            cur["name"] = line.split("=", 1)[1].strip('"')
        elif line.startswith("S: Sysfs="):
            cur["sysfs"] = line.split("=", 1)[1]
        elif line.startswith("B: ABS="):
            cur["caps"] = cur.get("caps", "") + " ABS"
    touch = []
    for d in devices:
        usb = "/usb" in d.get("sysfs", "")
        # "hdmi" drops the Pi's HDMI CEC inputs, but HDMI touchscreens (BIQU BTT-HDMI5) say it too
        if "hdmi" in d["name"].lower() and not (usb and "ABS" in d.get("caps", "")):
            continue
        if any(x in d["name"].lower() for x in ("pwr_button", "mouse", "keyboard")):
            continue
        touch.append({"name": d["name"], "i2c_buses": sorted(_i2c_buses_of(Path(d.get("sysfs", "")))),
                      "usb": usb})
    return touch


def detect_displays(touch: list[dict]) -> list[dict]:
    """Every connected output, and whether a touch controller shares its panel's i2c bus.

    Some boot configs add a panel overlay on a DSI port with nothing attached; the driver
    still reports it connected with a mode, and cage would extend the desktop onto it.
    The real panel is the one whose regulator/backlight bus also carries the touch chip."""
    touch_buses = {b for t in touch for b in t["i2c_buses"]}
    phandles = None
    platform = None
    outputs = []
    for conn in sorted(Path("/sys/class/drm").glob("card*-*")):
        card, name = conn.name.split("-", 1)
        if name.startswith("Writeback"):
            continue
        status = read(conn / "status").strip()
        modes = read(conn / "modes").split()
        o = {"connector": name, "card": card, "connected": status == "connected",
             "mode": modes[0] if modes else None, "panel_touch": False}
        if o["connected"] and name.startswith("DSI"):
            if phandles is None:
                phandles, platform = _dt_phandles(), _platform_devices_by_of_node()
            dsi_node = (Path("/sys/class/drm") / card / "device" / "of_node")
            buses: set[int] = set()
            if dsi_node.exists():
                for ep in dsi_node.resolve().rglob("remote-endpoint"):
                    remote = phandles.get(_u32(ep) or -1)
                    node = remote
                    while node is not None and node != DT_BASE and node.name.split("@")[0] in ("endpoint", "port", "ports"):
                        node = node.parent
                    if node is None:
                        continue
                    dev = platform.get(str(node.resolve()))
                    if dev:
                        buses |= _i2c_buses_of(dev)
            o["panel_i2c_buses"] = sorted(buses)
            o["panel_touch"] = bool(buses & touch_buses)
        outputs.append(o)
    return outputs


def choose_output(displays: list[dict], touch: list[dict]) -> tuple[str | None, str]:
    connected = [d for d in displays if d["connected"]]
    if not connected:
        return None, "no display connected"
    if len(connected) == 1:
        return connected[0]["connector"], "only connected output"
    with_touch = [d for d in connected if d["panel_touch"]]
    if len(with_touch) == 1:
        return with_touch[0]["connector"], "touch controller shares the panel's i2c bus"
    hdmi = [d for d in connected if d["connector"].startswith("HDMI")]
    if not with_touch and len(hdmi) == 1 and any(t["usb"] for t in touch):
        return hdmi[0]["connector"], "single HDMI output with USB touch"
    return None, f"{len(connected)} outputs connected and touch doesn't single one out"


def detect_rotation() -> tuple[int, str]:
    """A DSI panel overlay that inverts touch on both axes means the panel is mounted upside
    down; the picture has to be turned to match. Nothing else can be detected."""
    for cfg in ("/boot/firmware/config.txt", "/boot/config.txt"):
        for line in read(cfg).splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("dtoverlay=") and "dsi" in line:
                params = set(line.split(",")[1:])
                if {"invx", "invy"} <= params:
                    return 180, f"{line.split('=', 1)[1]} inverts touch on both axes"
                if "swapxy" in params:
                    return 90, f"{line.split('=', 1)[1]} swaps touch axes"
    return 0, "no rotated panel overlay"


def detect_printer_data() -> Path | None:
    env = Path(os.environ.get("PRINTER_DATA", ""))
    if env.name and (env / "config").is_dir():
        return env
    candidates = [p for p in sorted(HOME.glob("*printer*data")) if (p / "config").is_dir()]
    return candidates[0] if len(candidates) == 1 else (HOME / "printer_data" if (HOME / "printer_data" / "config").is_dir() else (candidates[0] if candidates else None))


def detect() -> dict:
    user = pwd.getpwuid(os.getuid())
    pdata = detect_printer_data()
    moon_dir = HOME / "moonraker"
    os_release = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', read("/etc/os-release"), re.M))
    touch = detect_touch()
    displays = detect_displays(touch)
    output, output_reason = choose_output(displays, touch)
    by_id = sorted(p.name for p in Path("/dev/serial/by-id").glob("*")) if Path("/dev/serial/by-id").exists() else []
    can = sorted(p.name for p in Path("/sys/class/net").glob("can*"))
    moonraker_url = "http://127.0.0.1:7125"
    print_state, klippy = None, None
    try:
        info = http_json(f"{moonraker_url}/server/info")["result"]
        klippy = info.get("klippy_state")
        q = http_json(f"{moonraker_url}/printer/objects/query?print_stats")
        print_state = q["result"]["status"]["print_stats"]["state"]
    except Exception:
        pass
    nginx_sites = Path("/etc/nginx/sites-enabled")
    return {
        "host": socket.gethostname(), "public_name": public_name(),
        "user": user.pw_name, "uid": user.pw_uid, "home": str(HOME),
        "model": read("/proc/device-tree/model").strip("\0\n ") or None,
        "os": os_release.get("PRETTY_NAME"), "arch": os.uname().machine,
        "sudo": sudo_mode(),
        "printer_data": str(pdata) if pdata else None,
        "klipper": {"service": unit_exists("klipper.service"), "state": klippy},
        "moonraker": {
            "service": unit_exists("moonraker.service"),
            "dir": str(moon_dir) if moon_dir.is_dir() else None,
            "components": str(moon_dir / "moonraker" / "components") if (moon_dir / "moonraker" / "components").is_dir() else None,
            "conf": str(pdata / "config" / "moonraker.conf") if pdata and (pdata / "config" / "moonraker.conf").exists() else None,
            "url": moonraker_url, "reachable": klippy is not None,
        },
        "print_state": print_state,
        "web": {
            "nginx": shutil.which("nginx") is not None or Path("/usr/sbin/nginx").exists(),
            "sites": sorted(p.name for p in nginx_sites.glob("*")) if nginx_sites.exists() else [],
            "port80": other_port80(nginx_sites),
        },
        "network_manager": shutil.which("nmcli") is not None and is_active("NetworkManager.service"),
        "klipperscreen": {"installed": unit_exists("KlipperScreen.service"),
                          "enabled": is_enabled("KlipperScreen.service"),
                          "active": is_active("KlipperScreen.service")},
        "kiosk": {"installed": unit_exists(KIOSK_UNIT), "enabled": is_enabled(KIOSK_UNIT),
                  "active": is_active(KIOSK_UNIT)},
        "kiosk_backends": kiosk_backends(),
        "displays": displays, "touch": touch,
        "panel_output": output, "panel_output_reason": output_reason,
        "panel_rotation": detect_rotation()[0], "panel_rotation_reason": detect_rotation()[1],
        "mcus": [n for n in by_id if "klipper" in n.lower() or "katapult" in n.lower()],
        # by-id collapses ACE units that share a serial; count USB devices instead
        "ace_units": sum(1 for d in Path("/sys/bus/usb/devices").glob("*")
                         if read(d / "product").strip() == "ACE" or
                         (read(d / "idVendor").strip(), read(d / "idProduct").strip()) == ("28e9", "018a")),
        "can": can,
        "cameras": unit_exists("crowsnest.service"),
        "installed": load_state(),
        "os_id": os_release.get("ID"), "os_version": os_release.get("VERSION_ID"),
        "board_release": dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', read("/etc/board-release"), re.M)).get("BOARD_NAME"),
        "memory_mb": mem_mb(),
        "web_ui": detect_web_ui(nginx_sites),
    }


def mem_mb() -> int | None:
    m = re.search(r"^MemTotal:\s+(\d+) kB", read("/proc/meminfo"), re.M)
    return int(m.group(1)) // 1024 if m else None


def detect_web_ui(sites: Path) -> dict:
    """Mainsail or Fluidd, and the port it answers on, for "It leaves Mainsail as it is"."""
    for name in ("mainsail", "fluidd"):
        m = re.search(r"^\s*listen\s+(\d+)", read(sites / name), re.M)
        if (sites / name).exists():
            return {"name": name.capitalize(), "port": int(m.group(1)) if m else None}
    return {"name": None, "port": None}


# ── what this board gets: one list for `check`, the phone's What works and bench.elyir.com/install ──────────
# (design/getting-started, "Will it work on my printer?"). Three answers: everything; everything with these
# differences, each said with what happens instead; not yet. The differences are only ever the screen's
# animations, slicing on the board itself, and the system underneath getting updates.

BOARDS = (("Raspberry Pi 400", "Raspberry Pi 400"), ("Raspberry Pi 5", "Raspberry Pi 5"),
          ("Compute Module 5", "Raspberry Pi CM5"), ("Raspberry Pi 4", "Raspberry Pi 4"),
          ("Compute Module 4", "Raspberry Pi CM4"))
SLICE_MIN_MB = 1500      # Orca peaks at about 0.9 GB slicing a 14-hour print on Workshop; a 1 GB board can't


def board_name(facts: dict) -> str | None:
    model = facts.get("model") or ""
    for key, name in BOARDS:
        if key in model:
            return name
    # BTT ship one image for the BTT Pi and the CB1, so the two can't be told apart (Desk says BQ-H616)
    if "H616" in model or facts.get("board_release") == "BTT-CB1":
        return "BTT Pi or CB1"
    return None


def os_short(facts: dict) -> str:
    if facts.get("os_id") in ("debian", "raspbian") and facts.get("os_version"):
        return f"Debian {facts['os_version']}"
    return facts.get("os") or "an unknown system"


def expectations(facts: dict, s: dict, here: bool = True) -> dict:
    """What this board gets. here=False is a board described by its facts alone (arch, glibc, memory_mb),
    for bench.elyir.com's table (site_table), not the machine this runs on."""
    board = board_name(facts)
    mem = facts.get("memory_mb")
    label = ", ".join(x for x in (board or facts.get("model") or facts["arch"],
                                  f"{max(1, round(mem / 1024))} GB" if mem else "", os_short(facts)) if x)
    out = {"board": label, "verdict": "everything", "why_not": None, "differences": [], "note": None,
           "screen": None, "slicing": None}   # screen: simpler | klipperscreen; slicing: elsewhere
    arch = door_arch() if here else door_arch(facts["arch"])
    if arch not in ("arm64", "amd64"):
        out.update(verdict="not_yet", why_not=f"This is a 32-bit system ({facts['arch']}). Elyir Bench needs a 64-bit "
                                              "one, such as 64-bit Raspberry Pi OS.")
        return out
    if not board and not (here and os.environ.get("ELYIR_BENCH_ANY_BOARD")):
        out.update(verdict="not_yet", why_not=f"{facts.get('model') or 'This board'} isn't one Elyir Bench knows yet. "
                                              "It runs on a Raspberry Pi 4 or 5, a BTT Pi or a CB1.")
        return out
    if facts.get("panel_output"):
        if not facts.get("kiosk_backends"):
            out["screen"] = "klipperscreen"
            out["differences"].append("The screen stays on KlipperScreen: this system can't run Elyir Bench there.")
        elif kiosk_render(facts, s) == "cpu":
            out["screen"] = "simpler"
            out["differences"].append("The screen has simpler animations (no graphics driver).")
    if orca_cant_run() if here else orca_why(arch, facts.get("glibc"), mem):
        out["slicing"] = "elsewhere"
        lender = s.get("slicer_name") if slicer_remote(s) else None
        out["differences"].append("It can't slice by itself. " + (
            f"{lender}, on your Wi-Fi, slices for it." if lender else
            "Another printer with Elyir Bench on your Wi-Fi can slice for it; files from your own slicer print as always."))
    if out["differences"]:
        out["verdict"] = "differences"
    if facts.get("os_version") == "11":
        out["note"] = "Debian 11 stopped getting updates in August 2026. Everything here still works on it."
    return out


# bench.elyir.com/install's "Will it work on my printer?": example boards, each put through expectations() above,
# so the page can't promise what the command won't say. `elyir-bench boards` writes install/boards.json from it, and
# a test fails when that file and this list disagree. All of them have a touchscreen.
SITE_BOARDS = (
    ("Raspberry Pi 5", "Debian 13", "Yes, in seconds",
     {"model": "Raspberry Pi 5 Model B Rev 1.0", "os_version": "13", "glibc": (2, 41), "memory_mb": 3950}),
    ("Raspberry Pi 4", "Debian 13, 2 GB or more", "Yes, more slowly",
     {"model": "Raspberry Pi 4 Model B Rev 1.4", "os_version": "13", "glibc": (2, 41), "memory_mb": 1850}),
    ("Raspberry Pi 4 or 5", "Debian 12", "Yes",
     {"model": "Raspberry Pi 4 Model B Rev 1.4", "os_version": "12", "glibc": (2, 36), "memory_mb": 3950}),
    ("Raspberry Pi 4", "Debian 11", "Yes",
     {"model": "Raspberry Pi 4 Model B Rev 1.4", "os_version": "11", "glibc": (2, 31), "memory_mb": 3950,
      "kiosk_backends": ["x11"]}),
    ("BTT Pi, BTT CB1", "BTT's own system, 1 GB", "Yes",
     {"model": "BQ-H616", "board_release": "BTT-CB1", "os_version": "12", "glibc": (2, 36), "memory_mb": 987,
      "kiosk_backends": ["x11"]}),
    ("Raspberry Pi 3 and older, other boards", "", "",
     {"model": "Raspberry Pi 3 Model B Plus Rev 1.3", "os_version": "12", "glibc": (2, 36), "memory_mb": 987}),
    ("Any board on a 32-bit system", "", "",
     {"model": "Raspberry Pi 4 Model B Rev 1.4", "arch": "armv7l", "os_version": "12", "glibc": (2, 36), "memory_mb": 3950}),
)


def site_table() -> list[dict]:
    """The rows of bench.elyir.com's table, in the page's short words; the command says the same in sentences."""
    rows = []
    for board, system, slices, over in SITE_BOARDS:
        facts = {"arch": "aarch64", "os_id": "debian", "panel_output": "HDMI-A-1", "kiosk_backends": ["cage", "x11"], **over}
        s = {"panel_backend": "auto", "panel_render": "auto"}
        e = expectations(facts, s, here=False)
        row = {"board": board, "system": system, "verdict": e["verdict"], "screen": "", "slicing": "", "get": "", "note": ""}
        if e["verdict"] == "not_yet":
            row["get"] = "Not yet. The command checks and changes nothing."
        else:
            row["screen"] = {"simpler": "Yes, simpler animations", "klipperscreen": "Stays on KlipperScreen"}.get(
                e["screen"], "Yes, the way KlipperScreen runs" if kiosk_backend(facts, s) == "x11" else "Yes")
            row["slicing"] = "Another printer running Elyir Bench slices for it" if e["slicing"] else slices
            row["get"] = "Everything else" if e["differences"] else "Everything"
            row["note"] = "Debian 11 itself gets no more updates." if e["note"] else ""
        rows.append(row)
    return rows


def printing_now(facts: dict) -> str | None:
    """"phone-stand.gcode, 42 %" while a print is running or paused, else None."""
    if facts.get("print_state") not in ("printing", "paused"):
        return None
    try:
        st = http_json(f"{facts['moonraker']['url']}/printer/objects/query?print_stats&display_status")["result"]["status"]
        return f"{st['print_stats'].get('filename') or 'a file'}, {round(100 * st['display_status'].get('progress', 0))} %"
    except Exception:
        return facts["print_state"]


def check_report(facts: dict, s: dict) -> tuple[list[str], int]:
    """What the install command says before it asks: 0 go ahead, 3 not now (a print), 4 can't."""
    exp = expectations(facts, s)
    ui, host = facts.get("web_ui") or {}, facts["host"].split(".")[0]
    lines = ["Elyir Bench, checking this printer"]
    mark = lambda ok, text: lines.append(f"  {'✓' if ok else '✗'} {text}")
    mark(exp["verdict"] != "not_yet", exp["board"])
    code = 0 if exp["verdict"] != "not_yet" else 4
    if exp["note"]:
        lines += [f"      {t}" for t in re.split(r"(?<=\.) ", exp["note"], maxsplit=1)]
    if facts["moonraker"]["reachable"] and facts["moonraker"]["components"]:
        mark(True, "Klipper and Moonraker running" + (f", {ui['name']} on port {ui['port']}" if ui.get("name") and ui.get("port") else ""))
    else:
        mark(False, "Moonraker isn't running here. Elyir Bench adds to a printer that already runs Klipper and Moonraker.")
        code = 4
    if facts.get("panel_output"):
        mark(True, "A touchscreen" + (", running KlipperScreen" if facts["klipperscreen"]["active"] else ""))
    if facts["sudo"] == "none":
        mark(False, f"{facts['user']} can't use sudo, which installing needs.")
        code = 4
    busy = printing_now(facts)
    if busy:
        mark(False, f"Printing: {busy}")
        code = code or 3
    elif code == 0:
        mark(True, "Not printing")
    lines.append("")
    if exp["verdict"] == "not_yet":
        lines.append(exp["why_not"])
    elif exp["differences"]:
        n = len(exp["differences"])
        lines.append(f"Everything works on this board, with {'one difference' if n == 1 else f'{n} differences'}:")
        lines += [f"  · {d}" for d in exp["differences"]]
        lines.append("")
    if code == 3:
        lines.append("Nothing was changed. Run the same command again when the print is done.")
    elif code == 4:
        lines.append("Nothing was changed.")
    else:
        have = (facts.get("installed") or {}).get("version")
        if have:
            lines.append(f"Elyir Bench {have} is already here; this updates it.")
        else:
            kept = ["printer.cfg"] + ([ui["name"]] if ui.get("name") else []) + \
                   (["KlipperScreen"] if facts["klipperscreen"]["installed"] else [])
            lines.append(f"It adds Elyir Bench at http://{host}.local:{s['port']}")
            if s.get("remote") == "relay":
                lines.append(f"It asks Elyir's relay for {s.get('remote_name') or host}.elyir.app, for notifications and your phone away from home")
            lines.append(f"It leaves {', '.join(kept[:-1]) + ' and ' + kept[-1] if len(kept) > 1 else kept[0]} as they are")
    return lines, code


def pair_target(facts: dict, s: dict) -> tuple[str, str | None]:
    """What the terminal's QR code holds: with the door on, a one-time pairing code (the panel's Add a phone,
    docs/door.md); without it, the printer's own address on the Wi-Fi, which a phone at home can open as it is."""
    if remote_on(s) and door_address(s) and (s.get("remote") == "own" or relay_carried(s)):
        try:
            req = urllib.request.Request("http://127.0.0.1:8090/door/pair/new", data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                got = json.load(r)
            return got["shell_url"], got["code"]
        except Exception:
            pass
    return f"http://{facts['host'].split('.')[0]}.local:{s['port']}/", None


def pair_lines(facts: dict, s: dict) -> list[str]:
    url, code = pair_target(facts, s)
    lines = ["Scan this with your phone, or open " + (url if not code else f"http://{facts['host'].split('.')[0]}.local:{s['port']}/")]
    if shutil.which("qrencode"):
        qr = run(["qrencode", "-t", "UTF8", "-m", "2", url], check=False).stdout.rstrip("\n")
        lines += qr.splitlines() if qr else []
    if code:
        lines.append(f"(the code works once, for 10 minutes; on a computer, type {code}; `elyir-bench pair` makes another)")
    elif s.get("remote") == "relay":
        lines.append("Notifications and your phone away from home come once Elyir approves this printer's name on its "
                     "relay. Run `elyir-bench pair` then for a code that pairs your phone. Have an invite code? "
                     "`elyir-bench remote invite <code>` does it now.")
    return lines


# ── settings ─────────────────────────────────────────────────────────────────

def settings_path(facts: dict) -> Path:
    pdata = facts.get("printer_data")
    return Path(pdata) / "config" / "elyir-bench.conf" if pdata else BASE / "elyir-bench.conf"


def default_settings(facts: dict) -> dict:
    # a box with no printer of its own is a Bench Box (docs/bench.md), and its Allow card on each printer says so
    # A name for people from the network name: voron -> Voron, voron-24 -> Voron 24 (a name already in
    # moonraker.conf wins, below, so printers set up before keep theirs)
    host = facts["host"].split(".")[0]
    name = " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]+", host) if w) or host
    name = name if facts["moonraker"].get("service", True) else "Bench Box"
    conf = facts["moonraker"].get("conf")
    m = re.search(r"^\[printer_intent\][^\[]*?^printer_name:\s*(\S.*)$", read(conf) if conf else "", re.M)
    if m:
        name = m.group(1).strip()
    if facts["kiosk"]["enabled"]:
        panel = "elyir-bench"
    elif facts["klipperscreen"]["installed"]:
        panel = "klipperscreen"   # leave the screen as it is until the person switches it
    else:
        panel = "elyir-bench" if facts["panel_output"] else "none"
    return {"printer_name": name, "panel": panel, "panel_output": "auto", "panel_rotation": "auto",
            "panel_backend": "auto", "panel_render": "auto", "boot_screen": "elyir-bench", "port": "8088",
            "remote": "relay", "slicer": "auto", "slice_for_others": "off", "role": "auto", "start_macro": "off",
            "network_wait": "off", "filament_units": "klipperace",
            "remote_name": facts.get("public_name") or re.sub(r"[^a-z0-9-]+", "-", facts["host"].split(".")[0].lower()).strip("-")}


def load_settings(facts: dict) -> dict:
    s = default_settings(facts)
    p = settings_path(facts)
    if p.exists():
        cp = configparser.ConfigParser(inline_comment_prefixes=("#",))
        cp.read(p)
        if cp.has_section("elyir-bench"):
            s.update({k: v.strip() for k, v in cp.items("elyir-bench")})
            # a printer that holds a name already keeps it, whatever the default is now
            if not cp.has_option("elyir-bench", "remote_name") and load_relay().get("name"):
                s["remote_name"] = load_relay()["name"]
    return s


def save_settings(facts: dict, s: dict) -> Path:
    p = settings_path(facts)
    text = (
        "# Elyir Bench settings. Edit here or from the setup page, then run `elyir-bench apply`.\n"
        "[elyir-bench]\n"
        f"printer_name: {s['printer_name']}\n"
        "# elyir-bench | klipperscreen | none\n"
        f"panel: {s['panel']}\n"
        "# auto, or a connector such as DSI-1 or HDMI-A-1\n"
        f"panel_output: {s['panel_output']}\n"
        "# auto, or 0 | 90 | 180 | 270 for a panel mounted sideways or upside down\n"
        f"panel_rotation: {s.get('panel_rotation', 'auto')}\n"
        "# auto, cage (Wayland) or x11 (for systems without cage, such as Debian 11)\n"
        f"panel_backend: {s.get('panel_backend', 'auto')}\n"
        "# auto, gpu or cpu (cpu: no motion or blur, for boards whose GPU the OS can't drive)\n"
        f"panel_render: {s.get('panel_render', 'auto')}\n"
        "# elyir-bench: the eye from power-on (needs panel: elyir-bench) | off: the Pi's own boot text\n"
        f"boot_screen: {s.get('boot_screen', 'elyir-bench')}\n"
        f"port: {s['port']}\n"
        "# Reaching the printer from outside the house (docs/door.md): off | relay | own\n"
        f"remote: {s.get('remote', 'off')}\n"
        "# the name to claim; the printer is then reached at <name>.<zone>\n"
        f"remote_name: {s.get('remote_name', '')}\n"
        "# Print a model from a phone (docs/slicer.md): auto (here when this machine can, otherwise a slicer\n"
        "# found on the Wi-Fi) | on (here) | off | another slicer's address, such as workshop.local. Either way its\n"
        "# printer settings and Orca presets live in elyir-bench-slicer/ next to this file.\n"
        f"slicer: {'auto' if s.get('slicer_auto') else s.get('slicer', 'off')}\n"
        "# on: other printers may slice here (slicer: <this machine's address> on theirs)\n"
        f"slice_for_others: {s.get('slice_for_others', 'off')}\n"
        "# auto (a printer when Klipper's Moonraker is here, otherwise a controller) | printer | controller\n"
        f"role: {s.get('role', 'auto')}\n"
        "# on: Elyir Bench's start macro (elyir-bench.cfg, and [include elyir-bench.cfg] in printer.cfg) runs before your\n"
        "# own start G-code, for the steps while it gets ready, Cancel while it warms up and the kept first layer\n"
        "# (docs/start-macro.md) | off. `elyir-bench startmacro on|off` sets it and restarts Klipper.\n"
        f"start_macro: {s.get('start_macro', 'off')}\n"
        "# off: the printer starts without waiting for the Wi-Fi (about 6 s sooner to the screen) | on: it waits\n"
        f"network_wait: {s.get('network_wait', 'off')}\n"
        "# The filament unit's driver (design/ace-driver/): klipperace | elyir (Bench's own service, in KlipperACE's place)\n"
        f"filament_units: {s.get('filament_units', 'klipperace')}\n"
        + "".join(f"{k}: {s[k]}\n" for k in (*UNITS_SETTINGS, "units_sensor_pin") if s.get(k))
        # the ones set only by hand (a staging printer's cloud_api and printers_app, docs/cloud.md): kept when present
        + "".join(f"{k}: {s[k]}\n" for k in ("relay_api", "relay_addr", "relay_zone", "acme_ca", "cloud_api", "printers_app",
                                            "printer_id", "remote_former")
                  if s.get(k))
    )
    if read(p) != text:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return p


# ── templates ────────────────────────────────────────────────────────────────

def other_port80(sites: Path) -> bool:
    """Whether another site (Mainsail, Fluidd) serves port 80 for the house. nginx then shares that socket, and
    the setup Wi-Fi's site must name its address, or it would become the house's default and take port 80 over."""
    for p in sorted(sites.glob("*")) if sites.exists() else []:
        if p.name not in (NGINX_SITE, WIFI_SITE) and re.search(r"^\s*listen\s+(?:\*:|0\.0\.0\.0:)?80[\s;]", read(p), re.M):
            return True
    return False


def wifi_location(facts: dict) -> str:
    """The first Wi-Fi's state and steps, for the panel (docs/setup.md)."""
    if not facts.get("network_manager"):
        return ""
    return f"""    location /wifi/ {{
        proxy_pass http://127.0.0.1:{WIFI_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
"""


def render_wifi_site(facts: dict) -> str:
    shared = facts["web"].get("port80")
    why = ("Another site serves port 80 for the house, so this one answers only the setup Wi-Fi's address."
           if shared else "Nothing else serves port 80 here: once the printer is set up, the page sends the house to the app.")
    return f"""# Managed by elyir-bench (docs/setup.md): a phone on a new printer's setup Wi-Fi asks any name on port 80
# and gets the setup page. {why}
server {{
    listen {WIFI_ADDR + ':80' if shared else '80'};
    server_name _;
    access_log off;

    location / {{
        proxy_pass http://127.0.0.1:{WIFI_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
"""


def render_wifi_unit(facts: dict, s: dict) -> str:
    return f"""# Managed by elyir-bench (docs/setup.md)
[Unit]
Description=Elyir Bench first Wi-Fi: a setup Wi-Fi and page while the printer has no network
After=NetworkManager.service
Wants=NetworkManager.service
ConditionPathExists={CURRENT}/setup/wifi_setup.py

[Service]
User={facts['user']}
ExecStart=/usr/bin/python3 {CURRENT}/setup/wifi_setup.py --state {DOOR_STATE / 'wifi-setup.json'} --port {WIFI_PORT} --app-port {s['port']} --app-dir {CURRENT}/app --installer {CURRENT}/installer/elyir_bench.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def power_button(devices: str = "/proc/bus/input/devices") -> bool:
    """A power button the kernel knows (the Pi 5's pwr_button, a PC's), as printer/power_key.py looks for it."""
    return bool(re.search(r'^N: Name=".*(pwr_button|power button)', read(devices), re.I | re.M))


def render_power_key_unit(facts: dict) -> str:
    return f"""# Managed by elyir-bench (design/power/)
[Unit]
Description=Elyir Bench power button: the nozzle cools first, then it turns off
After=moonraker.service
ConditionPathExists={CURRENT}/printer/power_key.py

[Service]
User={facts['user']}
SupplementaryGroups=input
ExecStart=/usr/bin/python3 {CURRENT}/printer/power_key.py --moonraker {facts['moonraker']['url']}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def hostname_for(name: str) -> str:
    """The printer's name on the network (name.local): Workshop -> workshop, Mia's Desk -> mia-s-desk."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63].strip("-") or "printer"


def render_hosts(current: str, host: str) -> str:
    """/etc/hosts with the 127.0.1.1 line naming this machine, as Debian keeps it (sudo warns without it)."""
    line = f"127.0.1.1\t{host}"
    if re.search(r"^127\.0\.1\.1\s.*$", current, re.M):
        return re.sub(r"^127\.0\.1\.1\s.*$", line, current, count=1, flags=re.M)
    return current.rstrip("\n") + ("\n" if current.strip() else "") + line + "\n"


def door_location(s: dict) -> str:
    """The door's home listener, for the panel and the Wi-Fi: pairing codes and the list of phones."""
    if s.get("remote", "off") == "off":
        return ""
    return """    location /door/ {
        proxy_pass http://127.0.0.1:8090;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
    }
"""


def slicer_location(s: dict) -> str:
    """Print a model: the app reaches the slicing service at /slice on its own origin, here or on another
    machine; either way the printer says who's asking, so the slicer only slices for this printer."""
    remote = slicer_remote(s)
    if slicer_on(s):
        target, where = f"http://127.0.0.1:{SLICER_PORT}", "this printer's own slicer"
    elif remote:
        host, port = slicer_target(remote)
        ip = resolve4(host)
        if ip is None:
            # nginx won't start on a name it can't find, and then nothing of the app would load
            return f"""    location /slice {{
        default_type application/json;
        return 503 '{{"error": "The slicer at {host} couldn\\'t be found on the network when this printer was set up."}}';
    }}
"""
        target, where = f"http://{ip}:{port}", f"{remote}, found at {ip} when this was written"
    else:
        return ""
    who = s.get("slicer_name") or (slicer_target(remote)[0] if remote else s["printer_name"])
    down = (f"{who} isn\\'t answering, so it can\\'t slice for {s['printer_name']}. Turn it on and try again, "
            "or send a file from your slicer on a computer.") if remote else "The slicer isn\\'t answering. It may be starting."
    off = json.dumps({"error": "@", "slicer": who, "off": bool(remote)}).replace('"@"', '"' + down + '"')
    return f"""    # {where}
    location /slice {{
        proxy_pass {target};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header {SLICER_HEADER} {slicer_id(s)};
        proxy_connect_timeout 5s;
        proxy_read_timeout 300;
        error_page 502 504 = @slicer_down;
    }}
    location @slicer_down {{
        default_type application/json;
        return 503 '{off}';
    }}
"""


def render_nginx(facts: dict, s: dict) -> str:
    moon = facts["moonraker"]["url"].replace("http://", "")
    return f"""# Managed by elyir-bench; edit {settings_path(facts).name} instead and run `elyir-bench apply`.
map $http_upgrade $elyir_bench_connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen {s['port']};
    server_name _;
    root {CURRENT}/app;
    index index.html;

    access_log /var/log/nginx/elyir-bench-access.log;
    error_log /var/log/nginx/elyir-bench-error.log;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_types text/plain text/css text/javascript application/javascript application/json image/svg+xml;
    client_max_body_size 0;
    proxy_request_buffering off;

    location / {{
        try_files $uri $uri/ /index.html;
    }}
    location = /index.html {{
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }}
    location /assets/ {{
        add_header Cache-Control "public, max-age=31536000, immutable";
    }}
    location /websocket {{
        proxy_pass http://{moon}/websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $elyir_bench_connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }}
{wifi_location(facts)}{door_location(s)}{slicer_location(s)}    location ~ ^/(printer|api|access|machine|server)/ {{
        proxy_pass http://{moon}$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Scheme $scheme;
    }}
{webcam_locations()}}}
"""


# Cameras, at the same addresses Mainsail's site gives them (/webcam/ .. /webcam4/ on the
# streamer ports 8080..8083), so the stream_url Moonraker lists works from the app's port too.
WEBCAM_PORTS = (8080, 8081, 8082, 8083)


def webcam_locations() -> str:
    out = []
    for i, port in enumerate(WEBCAM_PORTS):
        path = "/webcam/" if i == 0 else f"/webcam{i + 1}/"
        out.append(f"""    location {path} {{
        postpone_output 0;
        proxy_buffering off;
        proxy_ignore_headers X-Accel-Buffering;
        access_log off;
        error_log off;
        proxy_pass http://127.0.0.1:{port}/;
    }}
""")
    return "".join(out)


KS_MENU = """# elyir-bench: begin (managed by elyir-bench: the way back from KlipperScreen to Elyir Bench)
[menu __main elyir-bench]
name: Elyir Bench
icon: arrow-left
method: printer.intent.action
params: {"action": "use_elyir_bench"}
confirm: Switch this screen back to Elyir Bench?
# elyir-bench: end
"""
KS_SAVED = "#~# --- Do not edit below"
NO_KLIPPERSCREEN = "KlipperScreen isn't installed on this printer"
KS_STEADY = 8   # seconds KlipperScreen has to stay up before a switch to it counts (it restarts itself on a crash)


def klipperscreen_steady() -> bool:
    """KlipperScreen running, and for KS_STEADY seconds: a crash loop is 'active' between crashes."""
    if not is_active("KlipperScreen.service"):
        return False
    try:
        since = int(systemd("KlipperScreen.service", "ActiveEnterTimestampMonotonic")) / 1e6
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (ValueError, OSError):
        return False
    return uptime - since >= KS_STEADY


def strip_klipperscreen_menu(current: str) -> str:
    """KlipperScreen.conf without our menu entry (remove), the rest exactly as it was."""
    without = re.sub(r"\n*# elyir-bench: begin.*?# elyir-bench: end\n?", "\n", current, flags=re.S)
    return without.lstrip("\n")


def render_klipperscreen_conf(current: str) -> str:
    """KlipperScreen.conf with our menu entry, above the section KlipperScreen saves itself."""
    without = re.sub(r"# elyir-bench: begin.*?# elyir-bench: end\n?", "", current, flags=re.S)
    i = without.find(KS_SAVED)
    head, tail = (without[:i], without[i:]) if i >= 0 else (without, "")
    head = head.rstrip("\n")
    return (head + "\n\n" if head else "") + KS_MENU + ("\n" + tail if tail else "")


def panel_rotation(facts: dict, s: dict) -> int:
    r = str(s.get("panel_rotation", "auto"))
    return facts.get("panel_rotation", 0) if r == "auto" else int(r)


def render_kiosk_unit(facts: dict, s: dict, output: str) -> str:
    rotation = panel_rotation(facts, s)
    render = kiosk_render(facts, s)
    if kiosk_backend(facts, s) == "x11":
        # X's wrapper (allowed_users=anybody) picks a free VT and takes the display, like KlipperScreen
        return f"""# Managed by elyir-bench; edit {settings_path(facts).name} instead and run `elyir-bench apply`.
[Unit]
Description=Elyir Bench panel (Chromium kiosk on X)
After=systemd-user-sessions.service plymouth-quit-wait.service network-online.target
After=moonraker.service nginx.service
Wants=network-online.target
StartLimitIntervalSec=0
# Never run alongside KlipperScreen: they fight for the display
Conflicts=KlipperScreen.service

[Service]
User={facts['user']}
Environment=XDG_RUNTIME_DIR=/run/user/{facts['uid']}
Environment=ELYIR_BENCH_URL=http://localhost:{s['port']}/
Environment=ELYIR_BENCH_BACKEND=x11
# The connector the touchscreen is on; every other output is switched off
Environment=ELYIR_BENCH_OUTPUT={output}
Environment=ELYIR_BENCH_ROTATION={rotation}
# gpu, or cpu where this OS can't drive the board's GPU (panel_render in the settings)
Environment=ELYIR_BENCH_RENDER={render}
ExecStart={CURRENT}/kiosk/start.sh
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    if boot_screen_wanted(facts, s):
        # The boot eye stays up until here: cage starts on Plymouth's own VT (a switch to an empty one
        # would draw the text console's black), and Plymouth quits keeping its last frame on the
        # panel, which cover.py and then the app carry on from.
        tty, handoff = "tty1", "Conflicts=getty@tty1.service\n"
        plymouth = "# Plymouth lets go of the panel, its last frame left on it\nExecStartPre=+-/usr/bin/plymouth quit --retain-splash\n"
        wait = ""
        # TTYReset puts the console back in text mode and a VT clear draws it: both would wipe that frame
        reset = "# The console as Plymouth left it: text mode or a clear would draw over its last frame\nTTYReset=no\nTTYVTDisallocate=no\n"
    else:
        tty, handoff, plymouth, wait = "tty7", "", "", " plymouth-quit-wait.service"
        reset = "TTYReset=yes\nTTYVTDisallocate=yes\n"
    return f"""# Managed by elyir-bench; edit {settings_path(facts).name} instead and run `elyir-bench apply`.
[Unit]
Description=Elyir Bench panel (Chromium kiosk under cage)
After=systemd-user-sessions.service{wait} network-online.target
After=dbus.socket systemd-logind.service moonraker.service nginx.service
Wants=network-online.target dbus.socket systemd-logind.service
ConditionPathExists=/dev/tty0
StartLimitIntervalSec=0
# Never run alongside KlipperScreen: they fight for the display
Conflicts=KlipperScreen.service
{handoff}
[Service]
User={facts['user']}
Environment=XDG_RUNTIME_DIR=/run/user/{facts['uid']}
Environment=ELYIR_BENCH_URL=http://localhost:{s['port']}/
# The connector the touchscreen is on; every other output is switched off
Environment=ELYIR_BENCH_OUTPUT={output}
Environment=ELYIR_BENCH_ROTATION={rotation}
# gpu, or cpu where this OS can't drive the board's GPU (panel_render in the settings)
Environment=ELYIR_BENCH_RENDER={render}
{plymouth}# cage waits forever unless its VT is the one in front ('+' runs this as root)
ExecStartPre=+/usr/bin/chvt {tty[3:]}
ExecStart={CURRENT}/kiosk/start.sh
Restart=always
RestartSec=3
# A logind session on {tty} gives cage the display
UtmpIdentifier={tty}
UtmpMode=user
PAMName=login
TTYPath=/dev/{tty}
TTYVHangup=yes
{reset}StandardInput=tty
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


# ── boot screen ──────────────────────────────────────────────────────────────
# The eye from power-on (design/boot/, direction A). Plymouth draws it until the kiosk has drawn the
# same frame, so the kernel's text, the firmware's rainbow and tty1's login prompt are kept off the
# panel. Boot messages still exist (journalctl, or tty3 with a keyboard).

PLYMOUTH_THEME = "elyir-bench"
PLYMOUTH_DIR = f"/usr/share/plymouth/themes/{PLYMOUTH_THEME}"
PLYMOUTH_QUIT_DROPIN = "/etc/systemd/system/plymouth-quit.service.d/elyir-bench.conf"
PLYMOUTH_QUIT_CONF = f"""# Managed by elyir-bench: when Plymouth quits, leave the boot eye on screen until the kiosk draws
# the same frame. Without --retain-splash the panel flashes back to the text console in between.
# Not before the kiosk starts: the kiosk quits Plymouth itself when it takes the panel, so the ring
# keeps filling while the network and nginx come up instead of standing still.
[Unit]
After={KIOSK_UNIT}

[Service]
ExecStart=
ExecStart=-/usr/bin/plymouth quit --retain-splash
"""
QUIET_ARGS = ["quiet", "splash", "loglevel=3", "vt.global_cursor_default=0",
              "plymouth.ignore-serial-consoles", "logo.nologo"]
SPLASH_BLOCK = "# elyir-bench: no rainbow square at power-on (boot_screen in elyir-bench.conf)\n[all]\ndisable_splash=1\n"


def boot_screen_wanted(facts: dict, s: dict) -> bool:
    """The boot eye is on: a Raspberry Pi (cmdline.txt, config.txt and the initramfs hook are Raspberry Pi
    OS's) with the Elyir Bench panel, unless boot_screen: off."""
    model = facts.get("model") or ""
    return ((not model or "Raspberry Pi" in model) and s.get("panel") == "elyir-bench"
            and s.get("boot_screen", "elyir-bench") == "elyir-bench")


def boot_dir() -> Path:
    """Raspberry Pi OS keeps cmdline.txt in /boot/firmware since bookworm, in /boot before that."""
    return Path("/boot/firmware") if Path("/boot/firmware/cmdline.txt").exists() else Path("/boot")


def orientation_arg(output: str | None, rotation: int) -> str | None:
    """The kernel's word for a panel turned upside down, so Plymouth draws the right way up from its first frame:
    the kiosk only turns the picture (wlr-randr) once cage is up. 90 and 270 aren't passed: no printer has one
    to check which way round left_side_up and right_side_up land."""
    if rotation == 180 and output and output != "auto":
        return f"video={output}:panel_orientation=upside_down"
    return None


def render_cmdline(current: str, on: bool, original: str | None = None, orientation: str | None = None) -> str:
    """The kernel command line with the boot screen on or off: still one line, and every token that
    isn't ours stays where it was. Off takes away only what on added, judged against the copy saved
    before the first change (cmdline.txt.elyir-bench-orig). orientation is orientation_arg()'s token, kept
    only while on and unless the person already set that output's orientation themselves."""
    tokens = current.split()
    theirs = (original or current).split()
    ours = lambda t: t.startswith("video=") and ":panel_orientation=" in t and t not in theirs
    tokens = [t for t in tokens if not ours(t)]
    if on:
        tokens = ["console=tty3" if t == "console=tty1" else t for t in tokens]
        tokens += [a for a in QUIET_ARGS if a not in tokens]
        if orientation and not any(t.startswith(orientation.split(":")[0] + ":") for t in tokens):
            tokens.append(orientation)
    else:
        before = original.split() if original else []
        tokens = [t for t in tokens if t in before or t not in QUIET_ARGS]
        if not original or "console=tty1" in before:
            tokens = ["console=tty1" if t == "console=tty3" else t for t in tokens]
    return " ".join(tokens) + "\n"


def render_config_txt(current: str, on: bool) -> str:
    """config.txt with our disable_splash block at the end, or without it."""
    without = re.sub(r"\n*" + re.escape(SPLASH_BLOCK), "\n", current)
    if not on or re.search(r"(?m)^\s*disable_splash\s*=\s*1\s*$", without):
        return without
    return without.rstrip("\n") + "\n\n" + SPLASH_BLOCK


def boot_screen_sudo_cmds() -> list[str]:
    sc, tee, cp, mkdir, rm = (sudo_bin(n) for n in ("systemctl", "tee", "cp", "mkdir", "rm"))
    cmds = [f"{sc} * getty@tty1.service",
            f"{mkdir} -p {PLYMOUTH_DIR}", f"{cp} -rT {CURRENT}/kiosk/boot/plymouth {PLYMOUTH_DIR}",
            f"{sudo_bin('plymouth-set-default-theme')} {PLYMOUTH_THEME}", f"{sudo_bin('update-initramfs')} -u",
            f"{mkdir} -p {Path(PLYMOUTH_QUIT_DROPIN).parent}", f"{tee} {PLYMOUTH_QUIT_DROPIN}",
            f"{rm} -f {PLYMOUTH_QUIT_DROPIN}"]
    for b in ("/boot/firmware", "/boot"):
        cmds += [f"{tee} {b}/cmdline.txt", f"{tee} {b}/config.txt",
                 f"{cp} -n {b}/cmdline.txt {b}/cmdline.txt.elyir-bench-orig"]
    return cmds


def tree_hash(d: Path, names: list[str]) -> str | None:
    """A fingerprint of the files `names` in `d`, or None if any is missing."""
    h = hashlib.sha256()
    for n in names:
        f = d / n
        if not f.is_file():
            return None
        h.update(n.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:16]


def render_intent_section(facts: dict, s: dict) -> str:
    host = facts["host"].split(".")[0]
    return (
        "# Elyir Bench: human-readable printer state for the consumer UI (managed by elyir-bench)\n"
        "[printer_intent]\n"
        f"printer_name: {s['printer_name']}\n"
        f"advanced_url: http://{host}.local/\n"
    )


# ── steps ────────────────────────────────────────────────────────────────────

class Ctx:
    def __init__(self, facts: dict, settings: dict, release: Path | None = None, force: bool = False):
        self.facts, self.s, self.release, self.force = facts, settings, release, force
        self.restart_moonraker = False
        self.restart_kiosk = False
        self.switched_from: str | None = None
        self.door_restarted = False   # the door runs from the release: a switch needs it restarted once
        self.notes: list[str] = []
        # what a failed first install has to put back (there's no older release to fall back to)
        self.undo: list[tuple[str, callable]] = []

    @property
    def defer_downloads(self) -> bool:
        """Steps that download (libraries, Orca, the door's binaries) wait for a later apply: offline, or asked
        to (ELYIR_BENCH_DEFER_DOWNLOADS=1: renaming during setup, where the person is waiting on the screen)."""
        if not hasattr(self, "_defer"):
            self._defer = os.environ.get("ELYIR_BENCH_DEFER_DOWNLOADS") == "1" or not internet()
        return self._defer

    @property
    def output(self) -> str | None:
        o = self.s.get("panel_output", "auto")
        return self.facts["panel_output"] if o == "auto" else o


class Step:
    name = ""
    roles: tuple[str, ...] = ("printer",)   # where it runs: a printer, and/or a controller (no printer of its own)
    def check(self, c: Ctx) -> tuple[bool, str]: raise NotImplementedError
    def apply(self, c: Ctx) -> None: raise NotImplementedError


def current_version() -> str | None:
    v = CURRENT / "VERSION"
    return read(v).strip() or None if v.exists() else None


def release_version(tarball: Path) -> str:
    with tarfile.open(tarball) as t:
        f = t.extractfile("VERSION")
        if not f:
            raise StepFailed(f"{tarball} has no VERSION")
        return f.read().decode().strip()


def switch_current(target: Path) -> None:
    tmp = BASE / ".current.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target.relative_to(BASE))
    os.replace(tmp, CURRENT)


class Preflight(Step):
    name = "preflight"
    roles = ("printer", "controller")
    def check(self, c):
        f = c.facts
        problems = []
        if role(f, c.s) == "controller":
            if f["sudo"] == "none":
                problems.append(f"{f['user']} can't use sudo")
            elif f["sudo"] == "password":
                problems.append("sudo needs a password; will ask once")
            if not shutil.which("systemctl"):
                problems.append("no systemd")
            if not has_venv():
                problems.append("python3-venv to install")
            if not f["web"]["nginx"]:
                problems.append("nginx to install")
            return (not problems, "; ".join(problems) or "a controller: no printer here, sudo and systemd present")
        if not f["moonraker"]["service"] or not f["moonraker"]["components"]:
            problems.append("Moonraker not found (phase 1 needs an existing Klipper + Moonraker install)")
        if f["sudo"] == "none":
            problems.append(f"{f['user']} can't use sudo")
        elif f["sudo"] == "password":
            problems.append("sudo needs a password; will ask once")
        if not f["web"]["nginx"]:
            problems.append("nginx not installed")
        if f["print_state"] in ("printing", "paused") and not c.force:
            problems.append(f"printer is {f['print_state']}; try again when it's done (or --force)")
        return (not problems, "; ".join(problems) or "Klipper, Moonraker, nginx and sudo present")
    def apply(self, c):
        if c.facts["sudo"] == "password":
            ensure_sudo(c)
        if role(c.facts, c.s) == "controller":
            # Ubuntu leaves out venv (the door runtime needs it); a box serves its screen with nginx
            need = [p for p, ok in (("python3-venv", has_venv()), ("nginx", c.facts["web"]["nginx"])) if not ok]
            if need:
                apt_install(*need)
                c.facts["web"]["nginx"] = True
        ok, why = self.check(c)
        if not ok:
            raise StepFailed(why)


class Release(Step):
    name = "release"
    roles = ("printer", "controller")
    def check(self, c):
        cur = current_version()
        if c.release:
            want = release_version(c.release)
            return (cur == want, f"{cur or 'nothing'} -> {want}" if cur != want else f"{cur}")
        return (cur is not None, cur or "no release installed; pass a release tarball")
    def apply(self, c):
        if not c.release:
            raise StepFailed("no release installed; run `elyir-bench apply <release.tar.gz>`")
        ver = release_version(c.release)
        dest = RELEASES / ver
        if not (dest / "VERSION").exists():
            RELEASES.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(dir=RELEASES, prefix=".unpack-"))
            with tarfile.open(c.release) as t:
                t.extractall(tmp, filter="data") if sys.version_info >= (3, 12) else t.extractall(tmp)
            for root, dirs, files in os.walk(tmp):
                os.chmod(root, 0o755)
                for f in files:
                    p = Path(root) / f
                    os.chmod(p, 0o755 if p.suffix in (".sh", ".py") else 0o644)
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(tmp, dest)
        prev = current_version()
        if prev != ver:
            switch_current(dest)
            c.switched_from = prev
            c.restart_moonraker = c.restart_kiosk = True
            st = load_state()
            st.update({"version": ver, "previous": prev, "switched_at": _dt.datetime.now().isoformat(timespec="seconds")})
            save_state(st)
        # the `elyir-bench` command always runs the current release's installer
        bin_dir = HOME / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        link = bin_dir / "elyir-bench"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(CURRENT / "installer" / "elyir_bench.py")
        prune_releases()


def prune_releases() -> None:
    st = load_state()
    keep = {st.get("version"), st.get("previous")}
    rels = sorted((p for p in RELEASES.iterdir() if p.is_dir() and not p.name.startswith(".")),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for p in rels[KEEP_RELEASES:]:
        if p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)


class Legacy(Step):
    """Files from the hand-deployed layout (before this installer)."""
    name = "legacy files"
    FILES = ["www", "kiosk", "elyir_bench_intent.py", "printer_intent.py", "install.sh"]
    def check(self, c):
        left = [n for n in self.FILES if (BASE / n).exists() or (BASE / n).is_symlink()]
        return (not left, "none" if not left else "old layout: " + ", ".join(left))
    def apply(self, c):
        dest = BASE / "legacy" / _dt.date.today().isoformat()
        dest.mkdir(parents=True, exist_ok=True)
        for n in self.FILES:
            p = BASE / n
            if p.exists() or p.is_symlink():
                shutil.move(str(p), str(dest / n))
        c.notes.append(f"moved the old hand-deployed files to {dest}")


class Component(Step):
    name = "moonraker component"
    FILES = ["elyir_bench_intent.py", "filament_units.py", "elyir_bench_care.py", "printer_intent.py", "orca_profile.py"]
    def check(self, c):
        comp = Path(c.facts["moonraker"]["components"])
        wrong = [f for f in self.FILES
                 if not (comp / f).is_symlink() or os.readlink(comp / f) != str(CURRENT / "printer" / f)]
        return (not wrong, "linked to current release" if not wrong else "not linked: " + ", ".join(wrong))
    def apply(self, c):
        comp = Path(c.facts["moonraker"]["components"])
        for f in self.FILES:
            p = comp / f
            if p.is_symlink() or p.exists():
                p.unlink()
            p.symlink_to(CURRENT / "printer" / f)
        c.restart_moonraker = True
        c.undo.append(("component links", lambda: [(comp / f).unlink() for f in self.FILES if (comp / f).is_symlink()]))


class MoonrakerConf(Step):
    name = "moonraker.conf"
    def _section(self, text):
        return re.search(r"(?:^#[^\n]*\n)*^\[printer_intent\][^\[]*", text, re.M)
    def check(self, c):
        text = read(c.facts["moonraker"]["conf"])
        m = self._section(text)
        if not m:
            return (False, "no [printer_intent] section")
        name = re.search(r"^printer_name:\s*(.*)$", m.group(0), re.M)
        if not name or name.group(1).strip() != c.s["printer_name"]:
            return (False, f"printer_name should be {c.s['printer_name']}")
        return (True, f"[printer_intent] printer_name {c.s['printer_name']}")
    def apply(self, c):
        path = Path(c.facts["moonraker"]["conf"])
        text = read(path)
        m = self._section(text)
        if m:
            body = m.group(0)
            if re.search(r"^printer_name:.*$", body, re.M):
                new = re.sub(r"^printer_name:.*$", f"printer_name: {c.s['printer_name']}", body, count=1, flags=re.M)
            else:
                new = body.replace("[printer_intent]\n", f"[printer_intent]\nprinter_name: {c.s['printer_name']}\n", 1)
            text = text[:m.start()] + new + text[m.end():]
        else:
            text = text.rstrip("\n") + "\n\n" + render_intent_section(c.facts, c.s)
        backup = path.with_suffix(".conf.elyir-bench-bak")
        shutil.copy2(path, backup)
        path.write_text(text)
        c.restart_moonraker = True
        c.undo.append(("moonraker.conf", lambda: shutil.copy2(backup, path)))


# ── Elyir Bench's start macro (docs/start-macro.md, design/getting-started) ────────────────────────────────

M600_SECTION = re.compile(r"(?ms)^# ---- Only when this printer has no M600 of its own.*?^# ---- end M600[^\n]*\n?")
M600_LEFT_OUT = "# M600 is left out here: your config has its own, and it stays as it is.\n"
THEIR_M600 = re.compile(r"(?mi)^\s*\[\s*gcode_macro\s+m600\s*\]")
INCLUDE_LINE = re.compile(r"^\[include\s+[^\]]*\]\s*$")
OUR_INCLUDE = re.compile(rf"^\[include\s+{re.escape(START_MACRO_FILE)}\s*\]\s*$")


def start_macro_on(s: dict) -> bool:
    return s.get("start_macro", "off") == "on"


def config_dir(facts: dict) -> Path | None:
    pdata = facts.get("printer_data")
    return Path(pdata) / "config" if pdata else None


OUR_MACRO_SECTION = re.compile(r"^\[gcode_macro\s+_?elyir_bench_print_start\w*\]", re.I)


def render_orphan_settings(text: str) -> str:
    """A config file without any section of ours that can't stand alone. elyir-bench.cfg tells people to copy its
    settings section below the include to change one; once the include is gone, a gcode_macro section with no
    gcode: stops Klipper starting (found on desk.local, 5 October 2026). Such a section is commented out, saying
    why, and kept; one with its own gcode: is a working macro and stays as it is."""
    lines, out, i = text.splitlines(keepends=True), [], 0
    while i < len(lines):
        if not OUR_MACRO_SECTION.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].startswith("[") and not lines[j].startswith("#*#"):
            j += 1
        block = lines[i:j]
        if any(re.match(r"^gcode\s*:", ln) for ln in block):
            out += block
        else:
            out.append("# Elyir Bench's start macro was taken out; these were its settings, kept here:\n")
            out += ["#" + ln if ln.strip() else ln for ln in block]
        i = j
    return "".join(out)


def config_files(folder: Path) -> list[Path]:
    """Every .cfg in the config folder and below, following linked folders (macro collections often are), each once."""
    seen, out = set(), []
    for root, dirs, files in os.walk(folder, followlinks=True):
        real = os.path.realpath(root)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        out += [Path(root) / f for f in sorted(files) if f.endswith(".cfg")]
    return out


def has_own_m600(folder: Path) -> bool:
    """Any of their config defines M600, in any letter case. Klipper would merge a second [gcode_macro M600]
    into theirs, or refuse to start over [gcode_macro m600]; ours is left out instead."""
    ours = folder / START_MACRO_FILE
    return any(p != ours and THEIR_M600.search(read(p)) for p in config_files(folder))


def render_start_macro(source: str, own_m600: bool) -> str:
    return M600_SECTION.sub(M600_LEFT_OUT, source) if own_m600 else source


def render_printer_cfg(text: str, on: bool) -> str:
    """printer.cfg with our include after its last [include ...] line (or at the top), above the SAVE_CONFIG
    block; or without it. Nothing else in the file changes."""
    lines = text.splitlines(keepends=True)
    if not on:
        return "".join(ln for ln in lines if not OUR_INCLUDE.match(ln))
    if any(OUR_INCLUDE.match(ln) for ln in lines):
        return text
    saved = next((i for i, ln in enumerate(lines) if ln.startswith("#*#")), len(lines))
    last = max((i for i, ln in enumerate(lines[:saved]) if INCLUDE_LINE.match(ln)), default=None)
    if last is None:
        return START_MACRO_INCLUDE + "\n" + text
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines.insert(last + 1, START_MACRO_INCLUDE + "\n")
    return "".join(lines)


def render_printer_json(text: str, on: bool) -> str | None:
    """The slicing profile with "start_macro": true when on, without it when off, so the slicer puts the two lines
    around the start G-code (slicer/elyir_bench_slice.py). None when it isn't a JSON object: left alone."""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    if (d.get("start_macro") is True) == on and (on or "start_macro" not in d):
        return text
    if on:
        d["start_macro"] = True
    else:
        d.pop("start_macro", None)
    return json.dumps(d, indent=2) + "\n"


def klipper_restart(facts: dict, wait: int = 90) -> None:
    """FIRMWARE_RESTART through Moonraker, then wait for Klipper to be ready again. If it isn't, StepFailed
    with what Klipper said (a config error names the file and the line)."""
    url = facts["moonraker"]["url"]
    try:
        urllib.request.urlopen(urllib.request.Request(f"{url}/printer/firmware_restart", data=b"", method="POST"),
                               timeout=10).close()
    except Exception as e:
        raise StepFailed(f"Klipper couldn't be restarted through Moonraker ({e.__class__.__name__})")
    started = time.time()
    seen_down = False
    while time.time() < started + wait:
        time.sleep(1)
        try:
            info = http_json(f"{url}/printer/info", timeout=3)["result"]
            state, message = info.get("state"), (info.get("state_message") or "").strip()
        except Exception:
            state, message = None, ""     # Moonraker between two connections to Klipper
        settled = seen_down or time.time() > started + 5   # the old state can still show for a moment
        if state == "ready" and settled:
            return
        if state in ("error", "shutdown") and settled:
            raise StepFailed(f"Klipper didn't start again: {message.splitlines()[0] if message else state}")
        if state != "ready":
            seen_down = True
    raise StepFailed(f"Klipper wasn't ready again within {wait} s")


def klipper_has(facts: dict, name: str) -> bool:
    try:
        return name in http_json(f"{facts['moonraker']['url']}/printer/objects/list", timeout=4)["result"]["objects"]
    except Exception:
        return False


class StartMacro(Step):
    """Elyir Bench's start macro, for a printer someone else set up (start_macro: on): elyir-bench.cfg in the config
    folder, [include elyir-bench.cfg] in printer.cfg, and the slicer told to put its two lines around the start
    G-code. It runs before their own start G-code and never replaces any of their macros. Off takes all three out.
    Klipper restarts to read it, only when something changed and never while printing."""
    name = "start macro"
    WORDS = {"cfg": START_MACRO_FILE, "printer.cfg": "the include line in printer.cfg",
             "printer.json": "the slicer's start_macro flag"}

    def _want(self, c) -> dict[Path, str | None] | None:
        """What each file should hold (None: not there). None when this release doesn't carry the macro."""
        folder = config_dir(c.facts)
        on = start_macro_on(c.s)
        want: dict[Path, str | None] = {folder / START_MACRO_FILE: None}
        if on:
            src = CURRENT / "printer" / "klipper" / START_MACRO_FILE
            if not src.is_file():
                return None
            want[folder / START_MACRO_FILE] = render_start_macro(read(src), has_own_m600(folder))
        want[folder / "printer.cfg"] = render_printer_cfg(read(folder / "printer.cfg"), on)
        if not on:
            # their own copies of our settings, which can't stand alone without the include (render_orphan_settings)
            for f in config_files(folder):
                if f.name == START_MACRO_FILE:
                    continue
                before = want.get(f, read(f))
                after = render_orphan_settings(before)
                if after != before or f in want:
                    want[f] = after
        pjson = slicer_home(c.facts) / "printer.json"
        if pjson.is_file():
            text = render_printer_json(read(pjson), on)
            if text is not None:
                want[pjson] = text
        return want

    def _todo(self, want: dict[Path, str | None]) -> list[str]:
        def words(p: Path) -> str:
            if p.name in self.WORDS:
                return self.WORDS[p.name]
            return f"your copy of its settings in {p.name}" if p.name != START_MACRO_FILE else self.WORDS["cfg"]
        changed = [p for p, text in want.items() if (p.exists() if text is None else (not p.exists() or read(p) != text))]
        return list(dict.fromkeys(words(p) for p in changed))

    def check(self, c):
        folder, on = config_dir(c.facts), start_macro_on(c.s)
        if folder is None or not (folder / "printer.cfg").is_file():
            return (not on, "off" if not on else "no printer.cfg found to add the include line to")
        want = self._want(c)
        if want is None:
            return (True, f"on, but this release has no {START_MACRO_FILE}; the next one adds it")
        todo = self._todo(want)
        if todo:
            return (False, ("to add: " if on else "to take out: ") + ", ".join(todo))
        if not on:
            return (True, "off")
        return (True, f"{START_MACRO_INCLUDE} in printer.cfg" +
                (", without its M600 (this printer has its own)" if has_own_m600(folder) else ""))

    def apply(self, c):
        folder = config_dir(c.facts)
        if folder is None or not (folder / "printer.cfg").is_file():
            raise StepFailed(f"no printer.cfg in {folder or 'a printer_data/config folder'}, so there's nowhere to add "
                             f"{START_MACRO_INCLUDE}")
        printing = c.facts.get("print_state") in ("printing", "paused")
        if printing and not c.force:
            raise StepFailed(f"the printer is {c.facts['print_state']}, and Klipper has to restart to read the change. "
                             "Try again when it's done (or --force).")
        want = self._want(c) or {}
        before = {p: (read(p) if p.exists() else None) for p in want}
        changed = []
        for p, text in want.items():
            if text is None:
                if p.exists():
                    p.unlink()
                    changed.append(p)
            elif not p.exists() or read(p) != text:
                p.write_text(text)
                changed.append(p)
        if not changed:
            return
        restart = any(p.parent == folder for p in changed)   # printer.json alone is the slicer's, not Klipper's

        def put_back():
            for p, text in before.items():
                if text is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_text(text)
            if restart and not printing:
                klipper_restart(c.facts)
        c.undo.append(("start macro", put_back))
        if not restart:
            return
        if printing:
            c.notes.append("Klipper reads the start macro change at its next restart; it's printing now")
            return
        klipper_restart(c.facts)
        if start_macro_on(c.s) and not klipper_has(c.facts, START_MACRO_COMMAND):
            raise StepFailed(f"Klipper started again without ELYIR_BENCH_PRINT_START; is {START_MACRO_INCLUDE} "
                             "below a section that stops it being read?")


def units_on(s: dict) -> bool:
    return s.get("filament_units", "klipperace") == "elyir"


def render_units_printer_cfg(text: str, on: bool) -> str:
    """printer.cfg with KlipperACE's includes switched off and ours in (on), or the other way round. The lines are
    commented out with a mark, never deleted, so switching back puts them back as they were."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        bare = line[len(UNITS_OFF):] if line.startswith(UNITS_OFF) else line
        if line.strip() == UNITS_INCLUDE:
            continue
        if bare.strip() in KLIPPERACE_INCLUDES:
            out.append(UNITS_OFF + bare if on else bare)
        else:
            out.append(line)
    if on:
        marked = [i for i, line in enumerate(out) if line.startswith(UNITS_OFF)]
        if marked:
            at = marked[-1] + 1
        else:
            includes = [i for i, line in enumerate(out) if line.startswith("[include ")]
            at = includes[-1] + 1 if includes else 0
        out.insert(at, UNITS_INCLUDE)
    return "\n".join(out)


def render_units_moonraker(text: str, on: bool) -> str:
    """moonraker.conf with KlipperACE's own component ([ace_manager]) switched off and back, the same way."""
    out: list[str] = []
    inside = False
    for line in text.split("\n"):
        bare = line[len(UNITS_OFF):] if line.startswith(UNITS_OFF) else line
        if bare.startswith("["):
            inside = bare.strip() == "[ace_manager]"
        if inside and bare.strip():
            out.append(UNITS_OFF + bare if on else bare)
        else:
            out.append(line)
    return "\n".join(out)


def render_units_cfg(template: str, pin: str, own_sensor: bool) -> str:
    tools = "".join(f"\n[gcode_macro T{i}]\ngcode: ELYIR_TOOL T={i}\n" for i in range(UNITS_TOOLS))
    # KlipperACE makes the head's filament_switch_sensor itself; without it, ours keeps it for the screens
    head = "" if own_sensor else (f"# The head's filament sensor, which KlipperACE made itself; the screens read it.\n"
                                  f"[filament_switch_sensor extruder_sensor]\nswitch_pin: {pin}\npause_on_runout: False\n")
    # [duplicate_pin_override] takes the bare pin; the sections using it carry the pull-up (^) or inversion (!)
    return template.format(sensor_pin=pin, sensor_bare=pin.lstrip("^~! "), tool_macros=tools, head_sensor=head)


def units_own_sensor(facts: dict, folder: Path) -> bool:
    """A filament_switch_sensor among the sections Klipper loaded from the printer's own files. KlipperACE's never
    shows there (it makes its sensor itself), and the one our file adds is left out."""
    try:
        loaded = http_json(f"{facts['moonraker']['url']}/printer/objects/query?configfile=config",
                           timeout=4)["result"]["status"]["configfile"]["config"]
    except Exception:
        return False
    ours = "[filament_switch_sensor extruder_sensor]" in read(folder / UNITS_CFG)
    return any(k.startswith("filament_switch_sensor ") and not (ours and k == "filament_switch_sensor extruder_sensor")
               for k in loaded)


def units_sensor_pin(facts: dict, s: dict | None = None) -> str | None:
    """The extruder's filament sensor pin: units_sensor_pin in elyir-bench.conf (a pull-up a printer needs, such as
    ^EBBCan:PB8, that KlipperACE's reported pin doesn't show), else our own button's once switched, else the sensor
    named for the head in Klipper's config (KlipperACE's own included), else the only one."""
    if s and s.get("units_sensor_pin"):
        return s["units_sensor_pin"]
    try:
        settings = http_json(f"{facts['moonraker']['url']}/printer/objects/query?configfile=settings",
                             timeout=4)["result"]["status"]["configfile"]["settings"]
    except Exception:
        return None
    ours = (settings.get("gcode_button elyir_units_sensor") or {}).get("pin")
    if ours:
        return ours
    sensors = {k: v for k, v in settings.items() if k.startswith("filament_switch_sensor ") and v.get("switch_pin")}
    head = [v for k, v in sensors.items() if any(w in k for w in ("extruder", "toolhead", "head"))]
    pick = head or (list(sensors.values()) if len(sensors) == 1 else [])
    return pick[0]["switch_pin"] if pick else None


def units_settings(s: dict) -> dict:
    """The tool change settings for the service, from elyir_bench.conf's units_* keys."""
    return {name: kind(s[key]) for key, (name, kind) in UNITS_SETTINGS.items() if s.get(key)}


def units_seed(facts: dict, s: dict) -> dict:
    """The service's first state on a printer that ran KlipperACE: the slot in the head and the untagged spools'
    colors and materials (Klipper's saved variables), and the tool change settings from elyir_bench.conf."""
    state: dict = {"settings": units_settings(s)}
    url = facts["moonraker"]["url"]
    try:
        st = http_json(f"{url}/printer/objects/query?ace=selected_gate&save_variables", timeout=4)["result"]["status"]
        sel = (st.get("ace") or {}).get("selected_gate")
        if isinstance(sel, int) and sel >= 0:
            state["selected"] = sel
        var = (st.get("save_variables") or {}).get("variables") or {}
        colors, mats = var.get("ace_gate_color") or [], var.get("ace_gate_type") or []
        spools = {}
        for g in range(max(len(colors), len(mats))):
            color = str(colors[g]).lstrip("#") if g < len(colors) else ""
            mat = str(mats[g]) if g < len(mats) else ""
            if mat:
                spools[str(g)] = {"color": "#" + color.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", color) else None,
                                  "material": mat.upper()}
        if spools:
            state["spools"] = spools
    except Exception:
        pass
    return state


def render_units_unit(facts: dict) -> str:
    data = Path(facts["printer_data"])
    return f"""# Managed by elyir-bench (design/ace-driver/): Bench's filament-unit service, in place of KlipperACE
[Unit]
Description=Bench's filament-unit service: the ACE Pro units, their slots and tool changes
After=moonraker.service
ConditionPathExists={CURRENT}/units/service.py

[Service]
User={facts['user']}
ExecStart={DOOR_VENV / 'bin' / 'python'} {CURRENT}/units/service.py --socket {data / 'comms' / 'elyir-units.sock'} --state {data / 'config' / UNITS_STATE} --moonraker ws://127.0.0.1:{facts['moonraker']['url'].rsplit(':', 1)[-1]}/websocket
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


class FilamentUnits(Step):
    """filament_units: elyir puts Bench's own service in KlipperACE's place (design/ace-driver/, A): its Klipper config
    (the sensor's push, ELYIR_TOOL, T0..T15) in, KlipperACE's includes and Moonraker component switched off, the
    service running, and its first state carried over from KlipperACE. klipperace (the default) puts it all back.
    Klipper restarts to read it, never while printing."""
    name = "filament units"

    def _want(self, c) -> dict[Path, str | None] | None:
        folder, on = config_dir(c.facts), units_on(c.s)
        want: dict[Path, str | None] = {folder / UNITS_CFG: None,
                                        folder / "printer.cfg": render_units_printer_cfg(read(folder / "printer.cfg"), on),
                                        Path(c.facts["moonraker"]["conf"]): render_units_moonraker(read(c.facts["moonraker"]["conf"]), on)}
        if on:
            src = CURRENT / "units" / "klipper" / UNITS_CFG
            pin = units_sensor_pin(c.facts, c.s)
            if not src.is_file() or pin is None:
                return None
            want[folder / UNITS_CFG] = render_units_cfg(read(src), pin, units_own_sensor(c.facts, folder))
        return want

    def _stale_settings(self, c) -> bool:
        try:
            have = json.loads(read(config_dir(c.facts) / UNITS_STATE) or "{}").get("settings") or {}
        except ValueError:
            return True
        return have != units_settings(c.s)

    def _todo(self, want: dict[Path, str | None]) -> list[str]:
        return [p.name for p, text in want.items() if (p.exists() if text is None else (not p.exists() or read(p) != text))]

    def check(self, c):
        folder, on = config_dir(c.facts), units_on(c.s)
        if folder is None or not (folder / "printer.cfg").is_file():
            return (not on, "KlipperACE (no printer.cfg here)" if not on else "no printer.cfg found")
        want = self._want(c)
        if want is None:
            return (False, "no extruder filament sensor found in Klipper's config, or this release has no units/")
        todo = self._todo(want)
        running = is_enabled(UNITS_UNIT) or is_active(UNITS_UNIT)
        if not on:
            if todo or running:
                return (False, "to put KlipperACE back: " + ", ".join(todo + (["the service"] if running else [])))
            return (True, "KlipperACE")
        if todo:
            return (False, "to switch from KlipperACE: " + ", ".join(todo))
        if self._stale_settings(c):
            return (False, "the service's settings changed in elyir-bench.conf")
        if read(f"/etc/systemd/system/{UNITS_UNIT}") != render_units_unit(c.facts):
            return (False, "the service needs writing")
        if c.switched_from:
            return (False, "new release: the service restarts on it")
        if not (is_enabled(UNITS_UNIT) and is_active(UNITS_UNIT)):
            return (False, "the service isn't running")
        return (True, "Bench's own service, KlipperACE off")

    def apply(self, c):
        folder, on = config_dir(c.facts), units_on(c.s)
        if folder is None or not (folder / "printer.cfg").is_file():
            if on:
                raise StepFailed("no printer.cfg, so there's nowhere to switch KlipperACE off")
            return
        printing = c.facts.get("print_state") in ("printing", "paused")
        want = self._want(c)
        if want is None:
            raise StepFailed("there's no extruder filament sensor in Klipper's config for the service to watch")
        todo = self._todo(want)
        if todo and printing and not c.force:
            raise StepFailed(f"the printer is {c.facts['print_state']}, and Klipper has to restart for the switch. "
                             "Try again when it's done (or --force).")
        state = folder / UNITS_STATE
        if on and not state.exists():
            state.write_text(json.dumps(units_seed(c.facts, c.s), indent=1))   # read while KlipperACE still runs
        elif on and self._stale_settings(c):
            kept = json.loads(read(state) or "{}")
            kept["settings"] = units_settings(c.s)
            state.write_text(json.dumps(kept, indent=1))   # the service reads them as it starts, below
        if not on and (is_enabled(UNITS_UNIT) or is_active(UNITS_UNIT)):
            sudo("systemctl", "disable", "--now", UNITS_UNIT, check=False)
        before = {p: (read(p) if p.exists() else None) for p in want}
        for p, text in want.items():
            if text is None:
                p.unlink(missing_ok=True)
            elif not p.exists() or read(p) != text:
                p.write_text(text)
        moon = Path(c.facts["moonraker"]["conf"])
        if moon.name in todo:
            c.restart_moonraker = True
        # Klipper lets go of the unit's port first: two programs on one serial port would talk over each other
        if any(p.parent == folder for p in want if p.name in todo) and not printing:
            klipper_restart(c.facts)
        if on:
            unit = f"/etc/systemd/system/{UNITS_UNIT}"
            if read(unit) != render_units_unit(c.facts):
                sudo_write(unit, render_units_unit(c.facts))
                sudo("systemctl", "daemon-reload")
            sudo("systemctl", "enable", UNITS_UNIT)
            sudo("systemctl", "restart", UNITS_UNIT)

        def put_back():
            for p, text in before.items():
                if text is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_text(text)
            if on:
                sudo("systemctl", "disable", "--now", UNITS_UNIT, check=False)
            if not printing:
                klipper_restart(c.facts)
        if todo:
            c.undo.append(("filament units", put_back))


def render_bench_nginx(facts: dict, s: dict) -> str:
    """A Bench Box's screen: the Bench app, and its service behind /bench/ (the printers' live state comes
    through it, docs/bench.md)."""
    return f"""# Managed by elyir-bench; edit {settings_path(facts).name} instead and run `elyir-bench apply`.
map $http_upgrade $elyir_bench_connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen {s['port']};
    server_name _;
    root {CURRENT}/bench-app;
    index index.html;

    access_log /var/log/nginx/elyir-bench-access.log;
    error_log /var/log/nginx/elyir-bench-error.log;

    gzip on;
    gzip_types text/plain text/css text/javascript application/javascript application/json image/svg+xml;

    location / {{
        try_files $uri $uri/ /index.html;
    }}
    location = /index.html {{
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }}
    location /assets/ {{
        add_header Cache-Control "public, max-age=31536000, immutable";
    }}
    location /bench/ {{
        proxy_pass http://127.0.0.1:{BENCH_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $elyir_bench_connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_read_timeout 86400;
    }}
{slicer_location(s)}}}
"""


class Web(Step):
    name = "web app"
    roles = ("printer", "controller")
    def _site(self, c) -> str:
        return render_bench_nginx(c.facts, c.s) if role(c.facts, c.s) == "controller" else render_nginx(c.facts, c.s)
    def _paths(self):
        return f"/etc/nginx/sites-available/{NGINX_SITE}", f"/etc/nginx/sites-enabled/{NGINX_SITE}"
    def check(self, c):
        avail, enabled = self._paths()
        if read(avail) != self._site(c):
            return (False, f"nginx site needs writing (port {c.s['port']})")
        if not Path(enabled).is_symlink():
            return (False, "nginx site not enabled")
        if not os.stat(HOME).st_mode & 0o001:
            return (False, f"nginx can't reach {HOME}")
        return (True, f"http://{c.facts['host']}.local:{c.s['port']}/")
    def apply(self, c):
        avail, enabled = self._paths()
        if not os.stat(HOME).st_mode & 0o001:
            os.chmod(HOME, os.stat(HOME).st_mode | 0o001)   # traverse only, like Mainsail's install
        os.chmod(BASE, 0o755)
        fresh = not Path(enabled).is_symlink()
        sudo_write(avail, self._site(c))
        sudo("ln", "-sf", avail, enabled)
        sudo("nginx", "-t", "-q")
        sudo("systemctl", "reload", "nginx")
        if fresh:
            # the narrow sudoers rule has no rm; an empty site file is harmless and rewritten next time
            c.undo.append(("web app", lambda: (sudo_write(avail, "# elyir-bench: removed after a failed install\n"),
                                               sudo("systemctl", "reload", "nginx", check=False))))


def render_printer_avahi(facts: dict, s: dict) -> str:
    """How a printer says so on the Wi-Fi, for a Bench Box to find it (docs/bench.md): its name, the port its
    app answers on, and whether it has a door to ask (the box asks there; the printer says yes on its screen)."""
    from xml.sax.saxutils import escape
    txt = {"name": s["printer_name"], "id": slicer_id(s), "door": "1" if remote_on(s) else "0",
           "moonraker": facts["moonraker"]["url"].rsplit(":", 1)[-1], "v": "1"}
    rows = "".join(f"<txt-record>{escape(f'{k}={v}')}</txt-record>" for k, v in txt.items())
    return (f"<?xml version=\"1.0\" standalone='no'?>\n<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n"
            f"<!-- Managed by elyir-bench: a printer, for a Bench Box to find (docs/bench.md) -->\n<service-group><name>{escape(s['printer_name'])}</name>"
            f"<service><type>{PRINTER_MDNS}</type><port>{s['port']}</port>{rows}</service></service-group>\n")


class Announce(Step):
    """The printer on the Wi-Fi, for a Bench Box to find. Avahi reads the file by itself; no avahi, nothing to do."""
    name = "on the wi-fi"
    def check(self, c):
        if not PRINTER_AVAHI.parent.parent.is_dir():
            return (True, "no avahi here")
        if read(PRINTER_AVAHI) != render_printer_avahi(c.facts, c.s):
            return (False, f"to announce as {c.s['printer_name']}")
        return (True, f"announced as {c.s['printer_name']} ({PRINTER_MDNS})")
    def apply(self, c):
        sudo("mkdir", "-p", str(PRINTER_AVAHI.parent))
        sudo_write(str(PRINTER_AVAHI), render_printer_avahi(c.facts, c.s))


class Panel(Step):
    name = "panel"
    roles = ("printer", "controller")   # on a box, the kiosk opens localhost: the Bench app
    UNIT_PATH = f"/etc/systemd/system/{KIOSK_UNIT}"
    def _missing_packages(self, backend):
        return [p for p in KIOSK_PACKAGES[backend]
                if run(["dpkg-query", "-W", "-f=${Status}", p], check=False).stdout.strip() != "install ok installed"]
    @staticmethod
    def _xwrapper_ok():
        return re.search(r"(?m)^\s*allowed_users\s*=\s*anybody\s*$", read(XWRAPPER)) is not None
    def check(self, c):
        want = c.s["panel"]
        if want == "elyir-bench":
            if not c.output:
                return (False, f"can't tell which screen is the panel ({c.facts['panel_output_reason']}); set panel_output")
            backend = kiosk_backend(c.facts, c.s)
            if not backend:
                return (False, f"{c.facts['os']} can't run the Elyir Bench panel: it packages neither cage nor Chromium with X")
            miss = self._missing_packages(backend)
            if miss:
                unavailable = kiosk_installable(miss)
                if unavailable:
                    return (False, f"{c.facts['os']} has no {', '.join(unavailable)} package for the {backend} panel")
                return (False, "packages missing: " + " ".join(miss))
            if backend == "x11" and not self._xwrapper_ok():
                return (False, "X may only be started from a console")
            if read(self.UNIT_PATH) != render_kiosk_unit(c.facts, c.s, c.output):
                return (False, "kiosk service needs writing")
            if not (is_enabled(KIOSK_UNIT) and is_active(KIOSK_UNIT)):
                return (False, "kiosk not running")
            if is_enabled("KlipperScreen.service"):
                return (False, "KlipperScreen still enabled")
            return (True, f"Elyir Bench on {c.output} ({backend})")
        if want == "klipperscreen":
            if not c.facts["klipperscreen"]["installed"]:
                return (False, NO_KLIPPERSCREEN)
            if is_enabled(KIOSK_UNIT) or is_active(KIOSK_UNIT):
                return (False, "kiosk still on")
            if not (is_enabled("KlipperScreen.service") and is_active("KlipperScreen.service")):
                return (False, "KlipperScreen not running")
            return (True, "KlipperScreen")
        if is_enabled(KIOSK_UNIT) or is_active(KIOSK_UNIT):
            return (False, "kiosk still on")
        return (True, "no panel")
    def apply(self, c):
        want = c.s["panel"]
        if want == "elyir-bench":
            if not c.output:
                raise StepFailed(f"can't tell which screen is the panel ({c.facts['panel_output_reason']}). "
                                 "Set panel_output in elyir-bench.conf (see `elyir-bench detect`).")
            backend = kiosk_backend(c.facts, c.s)
            if not backend:
                raise StepFailed(f"{c.facts['os']} packages neither cage nor Chromium with X, so it can't run the "
                                 "Elyir Bench panel. Set panel: klipperscreen to keep the current screen.")
            miss = self._missing_packages(backend)
            if miss and kiosk_installable(miss):
                raise StepFailed(f"{c.facts['os']} has no {', '.join(kiosk_installable(miss))} package for the "
                                 f"{backend} panel. Set panel_backend: auto, or panel: klipperscreen to keep the current screen.")
            if miss:
                apt_install(*miss)
            if backend == "x11" and not self._xwrapper_ok():
                sudo_write(XWRAPPER, XWRAPPER_CONF)
            unit = render_kiosk_unit(c.facts, c.s, c.output)
            if read(self.UNIT_PATH) != unit:
                sudo_write(self.UNIT_PATH, unit)
                sudo("systemctl", "daemon-reload")
                c.restart_kiosk = True
            ks_was_on = c.facts["klipperscreen"]["installed"] and is_enabled("KlipperScreen.service")
            if c.facts["klipperscreen"]["installed"]:
                sudo("systemctl", "disable", "--now", "KlipperScreen.service", check=False)
                # KlipperScreen exits with an error when stopped; clear that so it doesn't show as a failed service
                sudo("systemctl", "reset-failed", "KlipperScreen.service", check=False)
            if ks_was_on:
                c.undo.append(("panel", lambda: (sudo("systemctl", "disable", "--now", KIOSK_UNIT, check=False),
                                                 sudo("systemctl", "enable", "--now", "KlipperScreen.service", check=False))))
            sudo("systemctl", "enable", KIOSK_UNIT)
            sudo("systemctl", "restart" if (c.restart_kiosk or not is_active(KIOSK_UNIT)) else "start", KIOSK_UNIT)
            c.restart_kiosk = False
        else:
            if want == "klipperscreen" and not c.facts["klipperscreen"]["installed"]:
                raise StepFailed(NO_KLIPPERSCREEN + ". Set panel: elyir-bench, or install KlipperScreen first.")
            kiosk_was_on = unit_exists(KIOSK_UNIT) and is_enabled(KIOSK_UNIT)
            if unit_exists(KIOSK_UNIT):
                sudo("systemctl", "disable", "--now", KIOSK_UNIT, check=False)
            if kiosk_was_on:
                # a switch that doesn't come up (health) puts Elyir Bench back, never a dark screen
                c.undo.append(("panel", lambda: (sudo("systemctl", "disable", "--now", "KlipperScreen.service", check=False),
                                                 sudo("systemctl", "enable", "--now", KIOSK_UNIT, check=False))))
            if want == "klipperscreen":
                sudo("systemctl", "enable", "--now", "KlipperScreen.service")


class KlipperScreenMenu(Step):
    """An Elyir Bench entry in KlipperScreen's main menu, so a screen switched to KlipperScreen
    (Care > Printer screen) can come back without a terminal."""
    name = "klipperscreen menu"
    def _path(self, c):
        return settings_path(c.facts).parent / "KlipperScreen.conf"
    def check(self, c):
        if not c.facts["klipperscreen"]["installed"]:
            return (True, "no KlipperScreen")
        p = self._path(c)
        if read(p) != render_klipperscreen_conf(read(p)):
            return (False, "no way back to Elyir Bench in KlipperScreen's menu")
        return (True, "Elyir Bench in KlipperScreen's main menu")
    def apply(self, c):
        p = self._path(c)
        p.write_text(render_klipperscreen_conf(read(p)))
        if is_active("KlipperScreen.service"):
            sudo("systemctl", "restart", "KlipperScreen.service", check=False)


# ── the door: reaching the printer from outside (docs/door.md) ──────────────

def remote_on(s: dict) -> bool:
    return s.get("remote", "off") in ("relay", "own")


def load_relay() -> dict:
    try:
        return json.loads(RELAY_STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_relay(d: dict, path: Path | None = None) -> None:
    path = path or RELAY_STATE
    DOOR_STATE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_claim(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def former_claim(s: dict) -> dict:
    """The old public name still answered while phones move to the new one, or {}."""
    f = load_claim(RELAY_FORMER)
    return f if s.get("remote_former") and f.get("name") == s["remote_former"] and f.get("secret") else {}


def door_address(s: dict) -> str | None:
    """The printer's public name, once it has one."""
    if s.get("remote") == "relay":
        r = load_relay()
        if not r.get("secret"):
            return None
        # while a new name waits to be carried, the printer goes on answering the one it has
        moving = load_claim(RELAY_NEXT).get("name") == s.get("remote_name")
        return r.get("address") if r.get("name") == s.get("remote_name") or moving else None
    if s.get("remote") == "own" and s.get("relay_zone"):
        return f"{s['remote_name']}.{s['relay_zone']}"
    return None


def door_arch(machine: str | None = None) -> str:
    m = machine or os.uname().machine
    return {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(m, m)


def door_binary(name: str) -> Path:
    return DOOR_BIN / f"{name}-{DOOR_BINARIES[name]['version']}"


def door_has_certificate(address: str) -> bool:
    """Whether Caddy holds a certificate for the public name yet."""
    return any((DOOR_STATE / "caddy" / "certificates").glob(f"*/{address}/{address}.crt"))


def lan_ip() -> str | None:
    """The address this printer has on the home network: the source of its route to the internet."""
    m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)", run(["ip", "-4", "route", "get", "1.1.1.1"], check=False).stdout)
    return m.group(1) if m else None


def home_name_for(relay: dict, ip: str) -> str | None:
    """192-0-2-73.workshop.home.elyir.app: the relay's DNS answers it with the printer's LAN address,
    for names it carries and private addresses only. Hosted relay only; an own relay has no home names."""
    if not (relay.get("secret") and relay.get("address") and ip):
        return None
    zone = relay["address"].split(".", 1)[1]
    return f"{ip.replace('.', '-')}.{relay['name']}.home.{zone}"


def current_home() -> str | None:
    """The home name Caddy should serve: the one the certificate job last finished, if its files are there."""
    try:
        name = json.loads(HOME_FILE.read_text()).get("name")
    except (OSError, ValueError):
        return None
    return name if name and (HOME_CERT / "cert.pem").exists() and (HOME_CERT / "key.pem").exists() else None


def render_caddyfile(s: dict, address: str, home: str | None = None) -> str:
    former = former_claim(s).get("address")
    return f"""# Managed by elyir-bench (docs/door.md). The away listener: the printer's public name on its own
# certificate, proved over TLS-ALPN-01 through the relay, in front of the door on loopback.
{{
	admin off
	auto_https disable_redirects
	storage file_system {DOOR_STATE}/caddy
	# frpc opens every connection with a PROXY header naming the phone. Read it only from loopback.
	servers 127.0.0.1:9443 {{
		listener_wrappers {{
			proxy_protocol {{
				timeout 5s
				allow 127.0.0.1/32 ::1/128
			}}
			tls
		}}
	}}
}}

{address}:9443 {{
	bind 127.0.0.1
	tls {{
		issuer acme {{
			dir {s.get('acme_ca') or DEFAULT_ACME_CA}
			disable_http_challenge
			alt_tlsalpn_port 9443
		}}
	}}
	reverse_proxy 127.0.0.1:8089
}}
""" + (f"""
# The name this printer had, answered while phones move to the new one (remote_former): the same door behind it.
{former}:9443 {{
	bind 127.0.0.1
	tls {{
		issuer acme {{
			dir {s.get('acme_ca') or DEFAULT_ACME_CA}
			disable_http_challenge
			alt_tlsalpn_port 9443
		}}
	}}
	reverse_proxy 127.0.0.1:8089
}}
""" if former else "") + (f"""
# The printer's name at home, straight over the Wi-Fi: a phone in the house never goes through the relay.
# Its certificate is proved over DNS-01 by the homecert timer, which rewrites this block when it changes.
{home}:443 {{
	tls {HOME_CERT}/cert.pem {HOME_CERT}/key.pem
	reverse_proxy 127.0.0.1:8091
}}
""" if home else "")


def render_frpc(s: dict, relay: dict, address: str) -> str:
    name = relay.get("name") or s["remote_name"]
    lines = [
        "# Managed by elyir-bench (docs/door.md). Holds the printer's relay secret: mode 0600.",
        "# NOT here, deliberately: any `plugin` line. A plugin that terminates TLS would let the relay read",
        "# what it carries; the raw handshake goes to Caddy, which holds the printer's only key.",
        f'serverAddr = "{relay.get("addr", "")}"',
        "serverPort = 443",
        "loginFailExit = false",
        'auth.method = "token"',
        f'auth.token = "{relay.get("token", "")}"',
    ]
    if relay.get("secret"):
        # The hosted relay checks each login against the name's claim: user and metadata are its protocol.
        lines += [f'user = "{name}"', f'metadatas.house = "{name}"', f'metadatas.secret = "{relay["secret"]}"']
    lines += [
        "# The relay takes printers dialing in and phones arriving on the same port; this first byte tells them apart.",
        "transport.tls.disableCustomTLSFirstByte = false",
        'log.to = "console"',
        'log.level = "info"',
        "",
        "[[proxies]]",
        'name = "away"',
        'type = "https"',
        f'customDomains = ["{address}"]',
        'localIP = "127.0.0.1"',
        "localPort = 9443",
        'transport.proxyProtocolVersion = "v2"',
    ]
    return "\n".join(lines) + "\n"


def render_door_units(facts: dict, s: dict, address: str) -> dict[str, str]:
    user, head = facts["user"], "# Managed by elyir-bench (docs/door.md).\n"
    common = f"[Service]\nUser={user}\nEnvironment=HOME={HOME}\nRestart=always\nRestartSec=3\n"
    install = "\n[Install]\nWantedBy=multi-user.target\n"
    return {
        "elyir-bench-door.service": head + "[Unit]\nDescription=Elyir Bench door: pairing, the gate and push\n"
            "After=network-online.target moonraker.service\nWants=network-online.target\n\n" + common +
            f"ExecStart={DOOR_VENV}/bin/python {CURRENT}/door/door.py --address {address} --state {DOOR_STATE}/door "
            f"--printer-id {printer_id(s)} --printer-name \"{s.get('printer_name', '')}\""
            + (f" --printers-app {s['printers_app']}" if s.get("printers_app") else "") + "\n" + install,
        "elyir-bench-caddy.service": head + "[Unit]\nDescription=Elyir Bench door: the printer's public name and certificate\n"
            "After=network-online.target elyir-bench-door.service\nWants=network-online.target\n\n" + common +
            "# the name at home is served on 443, which an unprivileged user may not open without this\n"
            "AmbientCapabilities=CAP_NET_BIND_SERVICE\n"
            f"ExecStart={door_binary('caddy')} run --config {DOOR_CONF}/Caddyfile --adapter caddyfile\n" + install,
        "elyir-bench-frpc.service": head + "[Unit]\nDescription=Elyir Bench door: the tunnel to the relay\n"
            "After=network-online.target elyir-bench-caddy.service\nWants=network-online.target\n\n" + common +
            f"ExecStart={door_binary('frpc')} -c {DOOR_CONF}/frpc.toml\n" + install,
    }


def printer_id(s: dict) -> str:
    """What phones know the printer by: set once it has moved to a new name, else the name it holds now (not the one
    it waits for), so the id never changes under a phone."""
    held = load_relay().get("name") if s.get("remote") == "relay" else None
    return s.get("printer_id") or held or s.get("remote_name") or "printer"


def render_former_unit(facts: dict) -> str:
    return ("# Managed by elyir-bench (docs/door.md, *A new name*).\n[Unit]\n"
            "Description=Elyir Bench door: the tunnel for the name this printer had, while phones move to the new one\n"
            "After=network-online.target elyir-bench-caddy.service\nWants=network-online.target\n\n"
            f"[Service]\nUser={facts['user']}\nEnvironment=HOME={HOME}\nRestart=always\nRestartSec=3\n"
            f"ExecStart={door_binary('frpc')} -c {DOOR_CONF}/frpc-former.toml\n\n[Install]\nWantedBy=multi-user.target\n")


def render_homecert_units(facts: dict) -> dict[str, str]:
    head = "# Managed by elyir-bench (docs/door.md).\n"
    return {
        "elyir-bench-homecert.service": head + "[Unit]\nDescription=Elyir Bench door: the certificate for the printer's name at home\n"
            "After=network-online.target\nWants=network-online.target\n\n"
            f"[Service]\nType=oneshot\nUser={facts['user']}\nEnvironment=HOME={HOME}\n"
            f"ExecStart={sys.executable} {CURRENT}/installer/elyir_bench.py homecert\n",
        "elyir-bench-homecert.timer": head + "[Unit]\nDescription=Elyir Bench door: keep the name at home current\n\n"
            "[Timer]\nOnBootSec=1min\nOnUnitActiveSec=15min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n",
    }


def homecert() -> int:
    """Keep the printer's name at home and its certificate current. Cheap when nothing changed: the timer
    runs it every 15 minutes, and lego only talks to Let's Encrypt within 30 days of expiry or when the
    LAN address (and with it the name) has moved."""
    relay = load_relay()
    name = home_name_for(relay, lan_ip() or "")
    if not name:
        print("no name at home: the printer has no claimed name on the hosted relay, or no LAN address")
        return 0
    api = DEFAULT_RELAY_API
    conf = Path(detect_printer_data() or BASE) / "config" / "elyir-bench.conf"
    cp = configparser.ConfigParser(inline_comment_prefixes=("#",))
    cp.read(conf)
    s = {k: v.strip() for k, v in cp.items("elyir-bench")} if cp.has_section("elyir-bench") else {}
    api = s.get("relay_api") or api
    zone = relay["address"].split(".", 1)[1]
    env = {**os.environ, "HTTPREQ_ENDPOINT": f"{api}/acme", "HTTPREQ_USERNAME": relay["name"], "HTTPREQ_PASSWORD": relay["secret"]}
    crt, key = LEGO_DIR / "certificates" / f"{name}.crt", LEGO_DIR / "certificates" / f"{name}.key"
    LEGO_DIR.mkdir(parents=True, exist_ok=True)
    base = [str(door_binary("lego")), "--accept-tos", "--email", f"{relay['name']}@{zone}", "--server",
            s.get("acme_ca") or DEFAULT_ACME_CA, "--dns", "httpreq", "--domains", name, "--path", str(LEGO_DIR)]
    cmd = base + (["renew", "--days", "30", "--no-random-sleep"] if crt.exists() else ["run"])
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if not (crt.exists() and key.exists()):
        print(f"no certificate for {name} yet: {(p.stderr or p.stdout).strip()[-300:]}")
        return 1
    changed = False
    HOME_CERT.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME_CERT, 0o700)
    for src, dst in ((crt, HOME_CERT / "cert.pem"), (key, HOME_CERT / "key.pem")):
        if read(dst) != read(src):
            tmp = dst.with_suffix(".tmp")
            tmp.write_text(read(src))
            os.chmod(tmp, 0o600)
            os.replace(tmp, dst)
            changed = True
    if read(HOME_FILE) != json.dumps({"name": name}):
        HOME_FILE.write_text(json.dumps({"name": name}))
        changed = True
    caddyfile = DOOR_CONF / "Caddyfile"
    want = render_caddyfile(s, relay["address"], name)
    if read(caddyfile) != want:
        caddyfile.write_text(want)
        changed = True
    if changed:
        sudo("systemctl", "restart", "elyir-bench-caddy.service", check=False)
        print(f"https://{name} is ready")
    return 0


class DoorRuntime(Step):
    """The door's own Python, with its two libraries pinned in door/requirements.txt. The slicing
    service runs on the same one (it needs only aiohttp)."""
    name = "door runtime"
    roles = ("printer", "controller")
    def _want(self) -> str:
        return read(CURRENT / "door" / "requirements.txt")
    def check(self, c):
        if not remote_on(c.s) and not slices_here(c.facts, c.s):
            return (True, "remote and slicer off")
        if not (DOOR_VENV / "bin" / "python").exists() or read(DOOR_VENV / ".requirements") != self._want():
            if c.defer_downloads:
                return (True, "waits for the network (its libraries download)")
            return (False, "no venv" if not (DOOR_VENV / "bin" / "python").exists() else "libraries out of date")
        return (True, f"{DOOR_VENV}")
    def apply(self, c):
        if not (DOOR_VENV / "bin" / "pip").exists():
            # Debian 11 printer images (BTT CB1) leave venv out, and bullseye-security has left the mirror so
            # apt can't add it; Klipper's own virtualenv is there. A failed attempt leaves python without pip.
            if has_venv():
                run([sys.executable, "-m", "venv", "--clear", str(DOOR_VENV)])
            elif shutil.which("virtualenv"):
                run(["virtualenv", "--clear", "-p", sys.executable, str(DOOR_VENV)])
            else:
                apt_install("python3-venv")
                run([sys.executable, "-m", "venv", "--clear", str(DOOR_VENV)])
        run([str(DOOR_VENV / "bin" / "pip"), "install", "-q", "--disable-pip-version-check",
             "-r", str(CURRENT / "door" / "requirements.txt")], timeout=1800)
        (DOOR_VENV / ".requirements").write_text(self._want())


class DoorBinaries(Step):
    """Caddy and frpc, downloaded at a pinned version and checked against a pinned hash. A Bench Box has them
    always: it opens a door for each printer it speaks for (bench/doors.py, docs/bench.md)."""
    name = "door binaries"
    roles = ("printer", "controller")
    def check(self, c):
        if not remote_on(c.s) and role(c.facts, c.s) != "controller":
            return (True, "remote off")
        missing = [n for n in DOOR_BINARIES if not os.access(door_binary(n), os.X_OK)]
        if missing and c.defer_downloads:
            return (True, "waits for the network (" + ", ".join(missing) + " download)")
        if missing:
            return (False, "missing: " + ", ".join(missing))
        return (True, ", ".join(f"{n} {b['version']}" for n, b in DOOR_BINARIES.items()))
    def apply(self, c):
        import hashlib
        arch = door_arch()
        DOOR_BIN.mkdir(parents=True, exist_ok=True)
        for name, b in DOOR_BINARIES.items():
            if os.access(door_binary(name), os.X_OK):
                continue
            want = b["sha256"].get(arch)
            if not want:
                raise StepFailed(f"no pinned {name} for {arch}")
            url = b["url"].format(v=b["version"], arch=arch)
            with tempfile.TemporaryDirectory() as tmp:
                tgz = Path(tmp) / "pkg.tar.gz"
                with urllib.request.urlopen(url, timeout=120) as r:
                    tgz.write_bytes(r.read())
                got = hashlib.sha256(tgz.read_bytes()).hexdigest()
                if got != want:
                    raise StepFailed(f"{name} download doesn't match its pinned hash ({got[:12]}…)")
                with tarfile.open(tgz) as t:
                    f = t.extractfile(b["member"].format(v=b["version"], arch=arch))
                    if not f:
                        raise StepFailed(f"{name}: {b['member']} not in the download")
                    out = door_binary(name).with_suffix(".tmp")
                    out.write_bytes(f.read())
                os.chmod(out, 0o755)
                os.replace(out, door_binary(name))


def public_name() -> str:
    """The name this printer asks the relay for: random-looking and the same every time on this machine, so neither its
    hostname nor what anyone called it goes into public DNS and the certificate logs. The board's serial keeps two cards
    flashed from one image apart."""
    seed = read("/etc/machine-id").strip() + read("/sys/firmware/devicetree/base/serial-number").strip("\0\n ")
    digest = hashlib.sha256(f"elyir-bench name {seed or socket.gethostname()}".encode()).digest()
    return "p-" + base64.b32encode(digest).decode()[:8].lower()


def machine_tag() -> str:
    """Four characters that stay the same on this machine, to tell apart two printers with one name."""
    mid = read("/etc/machine-id").strip() or socket.gethostname()
    return hashlib.sha256(mid.encode()).hexdigest()[:4]


def relay_carried(s: dict) -> bool:
    """Whether the relay carries this printer's public name now (claimed and approved), so a phone away can reach it."""
    r = load_relay()
    if s.get("remote") != "relay" or not door_address(s):
        return False
    code, st = relay_call(s.get("relay_api") or DEFAULT_RELAY_API, "GET", f"/houses/{r['name']}", secret=r.get("secret"))
    return code == 200 and bool(st.get("carried"))


def relay_call(api: str, method: str, path: str, body: dict | None = None, secret: str | None = None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    req = urllib.request.Request(api.rstrip("/") + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError):
        return 0, {}        # no answer (offline, DNS, a timeout): never an exception that fails an apply


def invite_code(raw: str) -> str | None:
    """An invite code as the relay writes it, from however it was typed: k7qx m2pd 9htf -> K7QX-M2PD-9HTF."""
    t = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    return "-".join(t[i:i + 4] for i in (0, 4, 8)) if len(t) == 12 else None


def invite_refusal(out: dict) -> str:
    d = out.get("detail")
    return (d.get("message") if isinstance(d, dict) else d) or "the relay refused it"


class RemoteName(Step):
    """The printer's public name. With the hosted relay it is claimed once, and the secret that proves
    the claim stays in ~/elyir-bench/state, never in printer_data."""
    name = "public name"
    def check(self, c):
        mode = c.s.get("remote", "off")
        if mode == "off":
            return (True, "remote off")
        if mode == "own":
            r = load_relay()
            if not (c.s.get("relay_addr") and c.s.get("relay_zone")):
                return (False, "own relay needs relay_addr and relay_zone in elyir-bench.conf")
            if not r.get("token"):
                return (False, "own relay needs its token: elyir-bench remote token <token>")
            return (True, door_address(c.s))
        r = load_relay()
        if r.get("name") and r.get("secret") and r["name"] != c.s["remote_name"]:
            nxt = load_claim(RELAY_NEXT)
            if nxt.get("name") == c.s["remote_name"]:
                return (False, f"moving to {nxt['address']}: waits for the relay to carry it; {r['address']} until then")
            return (False, f"moving to {c.s['remote_name']}: not claimed yet; {r['address']} until then")
        address = door_address(c.s)
        if not address:
            return (False, f"{c.s['remote_name']} not claimed yet")
        code, st = relay_call(c.s.get("relay_api") or DEFAULT_RELAY_API, "GET", f"/houses/{r['name']}", secret=r["secret"])
        if code == 200 and st.get("carried"):
            return (True, f"{address}, carried by the relay")
        if code == 200 and r.get("invite"):
            return (False, f"{address}, claimed; an invite code waits to be used")
        if code == 200:
            return (True, f"{address}, claimed; waiting for the relay to carry it")
        if code == 404:
            return (False, f"the relay doesn't know {r['name']} any more")
        return (True, f"{address} (relay not answering: {code or 'offline'})")
    def apply(self, c):
        if c.s.get("remote") != "relay":
            raise StepFailed(self.check(c)[1])
        api = c.s.get("relay_api") or DEFAULT_RELAY_API
        r = load_relay()
        if r.get("name") and r.get("secret") and r["name"] != c.s["remote_name"]:
            return self._move(c, api, r)
        invite = r.get("invite")
        if invite and r.get("name") and r.get("secret"):
            # A name it holds already (set up before it had a code): the code goes to that name. Only a name the
            # relay let go (unapproved for a day) is claimed again below, with the code.
            code, out = relay_call(api, "POST", f"/houses/{r['name']}/invite", {"code": invite}, secret=r["secret"])
            if code == 200:
                save_relay({k: v for k, v in r.items() if k != "invite"})
                # Caddy backs off after the certificate attempts the relay refused while the name waited, and
                # frpc's retries back off too: both start over now rather than in a few minutes
                for unit in ("elyir-bench-caddy.service", "elyir-bench-frpc.service"):
                    if is_active(unit):
                        sudo("systemctl", "restart", unit, check=False)
                c.notes.append(f"invite code used: the relay carries {r['address']}")
                return
            if code == 403:
                save_relay({k: v for k, v in r.items() if k != "invite"})
                c.notes.append(f"the invite code wasn't used: {invite_refusal(out)}")
                return
            if code != 404:
                c.notes.append(f"the invite code waits: {'no answer from the relay' if code == 0 else out.get('detail') or code}; "
                               "the next apply tries it again")
                return
        # A name someone else has (many printers are called voron): the relay's own suggestions, then this name
        # with four characters of this machine's id. A name it can't get never fails the install: everything
        # else works at home, and the next apply asks again.
        tried, todo = [], [c.s["remote_name"]]
        code, out = 0, {}
        while todo and len(tried) < 4:
            name = todo.pop(0)
            if name in tried:
                continue
            tried.append(name)
            code, out = relay_call(api, "POST", "/houses", {"name": name, **({"invite": invite} if invite else {})})
            if code == 403 and invite:
                # a code that is no good holds no name on the relay: say why, and claim without it
                c.notes.append(f"the invite code wasn't used: {invite_refusal(out)}")
                invite = None
                save_relay({k: v for k, v in r.items() if k != "invite"})
                tried.pop()
                todo.insert(0, name)
                continue
            if code == 409:
                detail = out.get("detail") if isinstance(out.get("detail"), dict) else {}
                todo = [n for n in detail.get("suggestions", []) if isinstance(n, str)][:1] + [f"{tried[0]}-{machine_tag()}"] + todo
                continue
            if code == 422 and len(tried) == 1:     # kept for the service itself (bench, printers): this name, made its own
                todo = [f"{tried[0]}-{machine_tag()}"] + todo
                continue
            break
        if code != 201:
            why = "no answer from the relay" if code == 0 else f"{', '.join(tried)} taken" if code == 409 else (out.get("detail") or code)
            c.notes.append(f"no public name yet ({why}); it works at home, and the next apply asks again")
            return
        if name != c.s["remote_name"]:
            c.notes.append(f"{tried[0]} was taken on the relay; this printer is {name}")
            c.s["remote_name"] = name
            save_settings(c.facts, c.s)
        save_relay({"name": out["name"], "address": out["address"], "secret": out["secret"],
                    "addr": (out.get("relay") or {}).get("addr", ""), "token": (out.get("relay") or {}).get("token", ""),
                    "claimed": _dt.datetime.now().isoformat(timespec="seconds")})
        if out.get("carried"):
            c.notes.append(f"claimed {out['address']} with the invite code; the relay carries it")
        else:
            c.notes.append(f"claimed {out['address']}; the relay carries it once Elyir approves it, or with an invite "
                           "code: elyir-bench remote invite <code>")

    def _move(self, c, api: str, r: dict) -> None:
        """A new public name for a printer that has one (docs/door.md, *A new name*). The new name is claimed and kept
        aside until the relay carries it; only then does the printer switch, keeping the old claim, so phones that
        still know the old name reach the printer once more and learn the new one from /door/me."""
        want, nxt = c.s["remote_name"], load_claim(RELAY_NEXT)
        if nxt.get("name") != want:
            name, code, out = claim_free_name(api, want)
            if code != 201:
                why = "no answer from the relay" if code == 0 else "taken" if code == 409 else (out.get("detail") or code)
                c.notes.append(f"no new name yet ({why}); the printer stays {r['address']}")
                return
            nxt = {"name": out["name"], "address": out["address"], "secret": out["secret"],
                   "addr": (out.get("relay") or {}).get("addr", ""), "token": (out.get("relay") or {}).get("token", ""),
                   "claimed": _dt.datetime.now().isoformat(timespec="seconds")}
            save_relay(nxt, RELAY_NEXT)
            if name != want:
                c.s["remote_name"] = name
                save_settings(c.facts, c.s)
        code, st = relay_call(api, "GET", f"/houses/{nxt['name']}", secret=nxt["secret"])
        if not (code == 200 and st.get("carried")) and not cloud_carry(c.s, nxt).get("until"):
            c.notes.append(f"claimed {nxt['address']}; the printer stays {r['address']} until the relay carries the new "
                           "name (a grant, or a Bench Cloud plan)")
            return
        save_relay({**r, "since": int(time.time())}, RELAY_FORMER)
        save_relay(nxt)
        RELAY_NEXT.unlink(missing_ok=True)
        c.s["remote_former"] = r["name"]
        c.s["printer_id"] = c.s.get("printer_id") or r["name"]          # phones know the printer by this: it stays
        save_settings(c.facts, c.s)
        c.notes.append(f"moved to {nxt['address']}; {r['address']} answers too until every phone has moved "
                       "(elyir-bench remote phones), then clear remote_former and apply")


def remote_phones(s: dict) -> int:
    """Each paired phone and the name it last came in on: while a former name is answered, who still uses it."""
    try:
        phones = json.loads((DOOR_STATE / "door" / "phones.json").read_text())
    except (OSError, ValueError):
        phones = []
    phones = phones.get("phones", []) if isinstance(phones, dict) else phones
    f = former_claim(s)
    former = f.get("address")

    def on_former(via: str) -> bool:                   # its public name, or its name at home (<lan>.<name>.home.<zone>)
        return bool(former) and (via == former or via.endswith(f".{f['name']}.home.{former.split('.', 1)[1]}"))
    since = f.get("since") or 0

    def state(p: dict) -> str:
        if former and (not p.get("via") or (p.get("last_seen") or 0) < since):
            return "not seen since the move"                 # no address recorded yet: it may still know the old one
        return "still on the old name" if on_former(p.get("via") or "") else "moved"
    old = [p for p in phones if state(p) != "moved"]
    for p in phones:
        seen = _dt.datetime.fromtimestamp(p["last_seen"]).strftime("%Y-%m-%d %H:%M") if p.get("last_seen") else "never"
        print(f"  {state(p):<24} {p.get('name', '?'):<24} {seen}  {p.get('via') or '-'}")
    if former:
        print(f"\n{len(old)} of {len(phones)} not on the new name yet: each moves the next time it opens the printer." if old else
              f"\nEvery phone has moved: clear remote_former in elyir-bench.conf and apply. {former} stays held on the relay.")
    return 0


def claim_free_name(api: str, first: str) -> tuple[str, int, dict]:
    """Claim first, else the relay's suggestion, else first-<machine tag>: (name, status, answer)."""
    tried, todo, code, out, name = [], [first], 0, {}, first
    while todo and len(tried) < 4:
        name = todo.pop(0)
        if name in tried:
            continue
        tried.append(name)
        code, out = relay_call(api, "POST", "/houses", {"name": name})
        if code == 409:
            detail = out.get("detail") if isinstance(out.get("detail"), dict) else {}
            todo = [n for n in detail.get("suggestions", []) if isinstance(n, str)][:1] + [f"{tried[0]}-{machine_tag()}"] + todo
            continue
        if code == 422 and len(tried) == 1:
            todo = [f"{tried[0]}-{machine_tag()}"] + todo
            continue
        break
    return name, code, out


class DoorServices(Step):
    """The door, Caddy and frpc as services, or none of them when remote is off."""
    name = "door services"
    def _want(self, c) -> dict[str, tuple[Path | str, str, int]]:
        address = door_address(c.s)
        relay = load_relay()
        if c.s.get("remote") == "own":
            relay = {**relay, "addr": c.s["relay_addr"]}
        home = current_home() if c.s.get("remote") == "relay" else None
        files = {str(DOOR_CONF / "Caddyfile"): (render_caddyfile(c.s, address, home), 0o644),
                 str(DOOR_CONF / "frpc.toml"): (render_frpc(c.s, relay, address), 0o600)}
        units = {f"/etc/systemd/system/{u}": (t, 0) for u, t in render_door_units(c.facts, c.s, address).items()}
        former = former_claim(c.s) if c.s.get("remote") == "relay" else {}
        if former:
            files[str(DOOR_CONF / "frpc-former.toml")] = (render_frpc(c.s, former, former["address"]), 0o600)
            units[f"/etc/systemd/system/{FORMER_UNIT}"] = (render_former_unit(c.facts), 0)
        if c.s.get("remote") == "relay":
            units.update({f"/etc/systemd/system/{u}": (t, 0) for u, t in render_homecert_units(c.facts).items()})
        return {**files, **units}
    def check(self, c):
        if not remote_on(c.s):
            on = [u for u in DOOR_UNITS + HOMECERT_UNITS + (FORMER_UNIT,) if is_enabled(u) or is_active(u)]
            return (not on, "remote off" if not on else "still running: " + ", ".join(on))
        if not door_address(c.s):
            # not a failure: the relay hasn't given a name yet (offline, or every name tried was taken)
            return (True, "waits for its public name")
        if c.switched_from and not c.door_restarted:
            # Nothing on disk differs after a release switch, but the running door is still the old
            # release's code until it restarts. Found on workshop and studio, 2 October 2026.
            return (False, "new release: the door restarts on it")
        stale = [Path(p).name for p, (t, _) in self._want(c).items() if read(p) != t]
        if stale:
            return (False, "needs writing: " + ", ".join(stale))
        former = former_claim(c.s) if c.s.get("remote") == "relay" else {}
        down = [u for u in DOOR_UNITS + ((FORMER_UNIT,) if former else ()) if not (is_enabled(u) and is_active(u))]
        if down:
            return (False, "not running: " + ", ".join(down))
        if not former and Path(f"/etc/systemd/system/{FORMER_UNIT}").exists():
            return (False, "the old name's tunnel is still up")
        if not door_has_certificate(door_address(c.s)):
            # Caddy backs off for hours after attempts that failed while the relay wasn't carrying the
            # name yet; a restart makes it try again now. Found on workshop, 2 October 2026.
            return (False, "no certificate yet")
        if c.s.get("remote") == "relay" and not is_enabled("elyir-bench-homecert.timer"):
            return (False, "the name at home isn't being kept")
        home = current_home()
        return (True, f"open at https://{door_address(c.s)}" + (f" and, at home, https://{home}" if home else "; name at home pending"))
    def apply(self, c):
        if not remote_on(c.s):
            for u in DOOR_UNITS + HOMECERT_UNITS + (FORMER_UNIT,):
                if unit_exists(u):
                    sudo("systemctl", "disable", "--now", u, check=False)
            return
        if not door_address(c.s):
            raise StepFailed("no public name yet")
        DOOR_CONF.mkdir(parents=True, exist_ok=True)
        restart, reload_units = set(), False
        for path, (text, mode) in self._want(c).items():
            if read(path) == text:
                continue
            name = Path(path).name
            if path.startswith("/etc/"):
                sudo_write(path, text)
                reload_units = True
                restart.add(name)
            else:
                tmp = Path(path).with_suffix(".tmp")
                tmp.write_text(text)
                os.chmod(tmp, mode)
                os.replace(tmp, path)
                restart.add({"Caddyfile": "elyir-bench-caddy.service", "frpc.toml": "elyir-bench-frpc.service",
                             "frpc-former.toml": FORMER_UNIT}[name])
        if c.switched_from:
            restart.add("elyir-bench-door.service")            # new release, new door code
        if not door_has_certificate(door_address(c.s)):
            restart.add("elyir-bench-caddy.service")
        former = former_claim(c.s) if c.s.get("remote") == "relay" else {}
        if not former and Path(f"/etc/systemd/system/{FORMER_UNIT}").exists():
            # every phone has moved: the old name's tunnel goes; the name itself stays held on the relay, never released
            sudo("systemctl", "disable", "--now", FORMER_UNIT, check=False)
            sudo("rm", "-f", f"/etc/systemd/system/{FORMER_UNIT}")
            (DOOR_CONF / "frpc-former.toml").unlink(missing_ok=True)
            reload_units = True
        if reload_units:
            sudo("systemctl", "daemon-reload")
        for u in DOOR_UNITS + ((FORMER_UNIT,) if former else ()):
            sudo("systemctl", "enable", u)
            sudo("systemctl", "restart" if (u in restart or not is_active(u)) else "start", u)
        c.door_restarted = c.door_restarted or "elyir-bench-door.service" in restart
        if c.s.get("remote") == "relay":
            sudo("systemctl", "enable", "--now", "elyir-bench-homecert.timer")
            # the first certificate now rather than in a minute; it restarts Caddy itself when it has one
            sudo("systemctl", "start", "--no-block", "elyir-bench-homecert.service", check=False)


def slicer_on(s: dict) -> bool:
    """Slices here: Orca and the slicing service run on this machine."""
    return s.get("slicer", "off") == "on"


def slicer_remote(s: dict) -> str | None:
    """Another machine slices for this printer: its address (workshop.local, 192.168.1.20:8095)."""
    v = s.get("slicer", "off").strip()
    return None if v in ("on", "off", "") else v


def _dns_name(buf: bytes, off: int) -> tuple[str, int]:
    labels, back, hops = [], None, 0
    while True:
        n = buf[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:                       # a pointer to a name earlier in the packet
            if back is None:
                back = off + 2
            off, hops = ((n & 0x3F) << 8) | buf[off + 1], hops + 1
            if hops > 30:
                raise ValueError("name loop")
            continue
        labels.append(buf[off + 1:off + 1 + n].decode(errors="replace"))
        off += 1 + n
    return ".".join(labels), back if back is not None else off


def _dns_records(buf: bytes) -> list[tuple[str, int, object]]:
    """(name, type, data) of every answer and additional record: PTR, SRV, TXT and A are read."""
    _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", buf[:12])
    off = 12
    for _ in range(qd):
        _, off = _dns_name(buf, off)
        off += 4
    out = []
    for _ in range(an + ns + ar):
        name, off = _dns_name(buf, off)
        rtype, _, _, size = struct.unpack("!HHIH", buf[off:off + 10])
        off += 10
        data, end = buf[off:off + size], off + size
        if rtype == 12:
            out.append((name, rtype, _dns_name(buf, off)[0]))
        elif rtype == 33:
            prio, weight, port = struct.unpack("!HHH", data[:6])
            out.append((name, rtype, (_dns_name(buf, off + 6)[0], port)))
        elif rtype == 16:
            txt, i = {}, 0
            while i < len(data):
                k, _, v = data[i + 1:i + 1 + data[i]].decode(errors="replace").partition("=")
                txt[k] = v
                i += 1 + data[i]
            out.append((name, rtype, txt))
        elif rtype == 1 and size == 4:
            out.append((name, rtype, socket.inet_ntoa(data)))
        off = end
    return out


def mdns_slicers(timeout: float = 2.0) -> list[dict]:
    """Slicers that lend, on this Wi-Fi."""
    return slicers_from(mdns_ask(SLICER_MDNS, timeout))


def mdns_ask(service: str, timeout: float = 2.0) -> list[tuple[str, int, object]]:
    """Who offers `service` on this Wi-Fi: one mDNS question from an ordinary port (a "legacy unicast" query,
    which avahi answers straight back), so it needs no avahi-utils or Python packages, even on Debian 11."""
    q = struct.pack("!HHHHHH", 0x5c1e, 0, 1, 0, 0, 0) + b"".join(
        bytes([len(p)]) + p.encode() for p in service.split(".")) + b"\0" + struct.pack("!HH", 12, 1)
    records: list[tuple[str, int, object]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.25)
        try:
            sock.sendto(q, ("224.0.0.251", 5353))
        except OSError:
            return []
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(9000)
                records += _dns_records(data)
            except (socket.timeout, ValueError, IndexError, struct.error):
                continue
    return records


def slicers_from(records: list[tuple[str, int, object]]) -> list[dict]:
    ptr = [d for n, t, d in records if t == 12 and n.lower() == SLICER_MDNS]
    srv = {n: d for n, t, d in records if t == 33}
    txt = {n: d for n, t, d in records if t == 16}
    a = {n.lower(): d for n, t, d in records if t == 1}
    out = {}
    for inst in ptr:
        if inst not in srv:
            continue
        host, port = srv[inst]
        t = txt.get(inst, {})
        out[inst] = {"name": t.get("name") or inst.split(".")[0], "kind": t.get("kind", "printer"),
                     "machine": t.get("machine", ""), "host": host.rstrip("."), "port": port, "ip": a.get(host.lower())}
    return list(out.values())


def best_slicer(found: list[dict], me: str) -> dict | None:
    """A Bench Box first (it's there to slice), then the quickest computer: a Pi 5 before a Pi 4. Never itself."""
    def rank(f: dict) -> tuple:
        m = f["machine"].lower()
        return (f["kind"] != "controller", 0 if "pi 5" in m else 2 if "pi 4" in m else 1, f["name"].lower())
    others = [f for f in found if f["name"].lower() != me.lower()]
    return min(others, key=rank) if others else None


def resolve_slicer(facts: dict, s: dict) -> dict:
    """slicer: auto, made concrete for this apply: here when this machine can run Orca, otherwise the best
    slicer found on the Wi-Fi, otherwise off. And the slicer's own name, for the words on the phone ("Workshop
    is off"), remembered so they're right while it's off."""
    st = load_state()
    if s.get("slicer", "auto") == "auto":
        s = {**s, "slicer_auto": True}
        if role(facts, s) == "controller" or not orca_cant_run():
            s["slicer"] = "on"
        else:
            pick = best_slicer(mdns_slicers(), s.get("printer_name", ""))
            if pick:
                s["slicer"] = pick["host"] if pick["port"] == SLICER_PORT else f"{pick['host']}:{pick['port']}"
                s["slicer_name"] = pick["name"]
            else:
                s["slicer"] = st.get("slicer_found") or "off"   # the one found before, when nothing answers now
    remote = slicer_remote(s)
    if remote and not s.get("slicer_name"):
        host, port = slicer_target(remote)
        try:
            s["slicer_name"] = http_json(f"http://{resolve4(host) or host}:{port}/slice/options", timeout=3)["slicer"]["name"]
        except Exception:
            s["slicer_name"] = (st.get("slicer_names") or {}).get(remote)
    if remote and s.get("slicer_name"):
        names = {**(st.get("slicer_names") or {}), remote: s["slicer_name"]}
        if names != st.get("slicer_names") or (s.get("slicer_auto") and st.get("slicer_found") != remote):
            st.update({"slicer_names": names, **({"slicer_found": remote} if s.get("slicer_auto") else {})})
            save_state(st)
    return s


def render_avahi(facts: dict, s: dict) -> str:
    """How a lending slicer says so on the Wi-Fi; avahi picks the file up by itself."""
    from xml.sax.saxutils import escape
    txt = {"name": s["printer_name"], "kind": role(facts, s), "machine": facts.get("model") or facts.get("arch") or "", "v": "1"}
    rows = "".join(f"<txt-record>{escape(f'{k}={v}')}</txt-record>" for k, v in txt.items())
    return (f"<?xml version=\"1.0\" standalone='no'?>\n<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n"
            f"<!-- Managed by elyir-bench: this slicer lends (docs/slicer.md) -->\n<service-group><name>{escape(s['printer_name'])}</name>"
            f"<service><type>{SLICER_MDNS[:-len('.local')]}</type><port>{SLICER_PORT}</port>{rows}</service></service-group>\n")


def slicer_target(addr: str) -> tuple[str, int]:
    host, _, port = addr.partition(":")
    return host, int(port) if port.isdigit() else SLICER_PORT


def resolve4(host: str) -> str | None:
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except (OSError, IndexError):
        return None


def slicer_id(s: dict) -> str:
    """This printer as a slicer knows it: Workshop → workshop."""
    return re.sub(r"[^a-z0-9-]+", "-", s["printer_name"].lower()).strip("-")[:32] or "printer"


def role(facts: dict, s: dict) -> str:
    """printer, or controller: a machine with no printer of its own (a Pi, a NUC) that serves printers.
    Today a controller slices; docs/slicer.md, "Slicing for other printers"."""
    r = s.get("role", "auto")
    if r == "auto":
        return "printer" if facts.get("moonraker", {}).get("service", True) else "controller"
    return r


def slices_here(facts: dict, s: dict) -> bool:
    return role(facts, s) == "controller" or slicer_on(s)


def slicer_lends(facts: dict, s: dict) -> bool:
    """Other printers may join: a controller always, a printer when slice_for_others is on."""
    return role(facts, s) == "controller" or (slicer_on(s) and s.get("slice_for_others", "off") == "on")


def this_moonraker(facts: dict) -> str:
    """Where a slicer elsewhere reaches this printer's Moonraker: by its .local name, which follows it
    when the router hands out another address."""
    host = facts["host"] if "." in facts["host"] else f"{facts['host']}.local"
    port = facts["moonraker"]["url"].rsplit(":", 1)[-1]
    return f"http://{host}:{port}"


def orca_cant_run() -> str | None:
    """Why the pinned Orca can't run on this machine, or None. Not something an apply can fix, so it's
    said rather than failed (a release must not roll back over it): Desk's Debian 11 has glibc 2.31."""
    return orca_why(door_arch(), glibc(), mem_mb())


def orca_why(arch: str, have: tuple[int, ...] | None, mem: int | None) -> str | None:
    """orca_cant_run() for any machine: its arch, glibc and memory."""
    if arch not in ORCA["sha256"]:
        return f"no pinned Orca for {arch}"
    if have and tuple(have) < ORCA["glibc"]:
        return (f"Orca {ORCA['version']} needs glibc {'.'.join(map(str, ORCA['glibc']))} (Debian 13, Ubuntu 24.04), "
                f"this has {'.'.join(map(str, have))}; slice on another machine instead (slicer: <its address>)")
    if mem and mem < SLICE_MIN_MB:
        return f"Orca needs about 1 GB free to slice and this has {mem} MB in all; slice on another machine instead"
    return None


def has_venv() -> bool:
    import importlib.util
    return importlib.util.find_spec("ensurepip") is not None


def glibc() -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in os.confstr("CS_GNU_LIBC_VERSION").split()[1].split(".")[:2])
    except (ValueError, OSError, IndexError, AttributeError):
        return None


def slicer_home(facts: dict) -> Path:
    """The person's side: printer.json and the Orca presets, next to elyir-bench.conf, so they show
    in Mainsail's editor and are backed up with the rest of the config."""
    return settings_path(facts).parent / "elyir-bench-slicer"


def orca_root() -> Path:
    return SLICER_DIR / f"orca-{ORCA['version']}"


def orca_binary() -> Path:
    return orca_root() / "bin" / "orca-slicer"


def missing_packages(packages: list[str]) -> list[str]:
    out = run(["dpkg-query", "-W", "-f", "${Package} ${Status}\n", *packages], check=False).stdout
    have = {l.split()[0] for l in out.splitlines() if l.endswith("install ok installed")}
    return [p for p in packages if p not in have]


def render_slicer_config(facts: dict, s: dict) -> str | None:
    """The service's config: this printer and where Orca and the presets are. The service reads printer.json from
    the printer's folder itself ("home"), when it appears and whenever it changes: on a printer someone else set up,
    the intent layer writes it, learned from their own files (docs/slicer-profile.md), with no apply in between.
    A controller has no printer of its own: only the ones that join."""
    printer: dict = {}
    if role(facts, s) == "printer":
        try:
            printer = json.loads(read(slicer_home(facts) / "printer.json") or "null")
        except ValueError:
            printer = {}
        if not isinstance(printer, dict):
            printer = {}
    root = orca_root()
    config = {
        "orca": str(root / "bin" / "orca-slicer"),
        "orca_env": {"LC_ALL": "C", "APPDIR": str(root),
                     "LD_LIBRARY_PATH": f"{root}/lib/orca-runtime:{root}/bin:{root}/lib"},
        "nice": 0,                                       # the unit already runs it at idle priority
        "profiles": [str(root / "resources" / "profiles")],   # Orca's own, after each printer's presets
        "printers": {},
        "lend": slicer_lends(facts, s),                  # joined printers are kept in the service's work folder
        "name": s["printer_name"],                       # what phones are told ("Sliced on Workshop")
        # a printer asks its owner (the Allow card on this screen); a Bench Box has no screen yet, so anyone joins
        "allow": "anyone" if role(facts, s) == "controller" else "ask",
    }
    if role(facts, s) == "printer":
        config["printers"][slicer_id(s)] = {"name": s["printer_name"], **printer, "moonraker": facts["moonraker"]["url"],
                                            "presets": [str(slicer_home(facts) / "presets")],
                                            "home": str(slicer_home(facts))}
    return json.dumps(config, indent=1, sort_keys=True) + "\n"


def render_slicer_unit(facts: dict, lend: bool = False) -> str:
    py = DOOR_VENV / "bin" / "python"
    # lending: other printers reach it on the network (their nginx in front); otherwise only this one's nginx
    listen = "0.0.0.0" if lend else "127.0.0.1"
    return f"""# Managed by elyir-bench (docs/slicer.md)
[Unit]
Description=Elyir Bench slicing service (Print a model)
After=network-online.target moonraker.service
# A rollback to a release from before the slicer: skip it rather than restart it every five seconds
ConditionPathExists={CURRENT}/slicer/slice_service.py

[Service]
User={facts['user']}
ExecStart={py} {CURRENT}/slicer/slice_service.py --config {SLICER_DIR}/config.json --host {listen} --port {SLICER_PORT} --work {SLICER_WORK}
# Klipper's host timing comes first: slicing only gets the CPU nothing else wants.
CPUSchedulingPolicy=idle
IOSchedulingClass=idle
Nice=19
MemoryMax=2G
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


class SlicerEngine(Step):
    """OrcaSlicer's arm64 build, pinned by checksum and unpacked, and the libraries it links."""
    name = "slicer engine"
    roles = ("printer", "controller")
    def check(self, c):
        if slicer_remote(c.s):
            return (True, f"slices on {slicer_remote(c.s)}")
        if not slices_here(c.facts, c.s):
            return (True, "slicer off")
        why = orca_cant_run()
        if why:
            return (True, f"off: {why}")
        miss = missing_packages(ORCA_PACKAGES)
        have = os.access(orca_binary(), os.X_OK)
        if (miss or not have) and c.defer_downloads:
            return (True, f"waits for the network (Orca {ORCA['version']} downloads)")
        if miss:
            return (False, f"{len(miss)} libraries to install: " + ", ".join(miss))
        if not have:
            return (False, f"Orca {ORCA['version']} to download")
        return (True, f"Orca {ORCA['version']}")
    def apply(self, c):
        import hashlib
        miss = missing_packages(ORCA_PACKAGES)
        if miss:
            apt_install(*miss)
        if os.access(orca_binary(), os.X_OK):
            return
        SLICER_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SLICER_DIR) as tmp:
            img = Path(tmp) / "orca.AppImage"
            with urllib.request.urlopen(ORCA["urls"][door_arch()].format(v=ORCA["version"]), timeout=300) as r, open(img, "wb") as f:
                shutil.copyfileobj(r, f)
            h = hashlib.sha256()
            with open(img, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != ORCA["sha256"][door_arch()]:
                raise StepFailed(f"Orca download doesn't match its pinned hash ({h.hexdigest()[:12]}…)")
            os.chmod(img, 0o755)
            subprocess.run([str(img), "--appimage-extract"], cwd=tmp, capture_output=True, timeout=600, check=True)
            os.replace(Path(tmp) / "squashfs-root", orca_root())
        for old in SLICER_DIR.glob("orca-*"):              # one engine at a time: they're 500 MB each
            if old != orca_root():
                shutil.rmtree(old, ignore_errors=True)


class SlicerService(Step):
    """The slicing service, for this printer, from printer.json and the presets beside it."""
    name = "slicer service"
    roles = ("printer", "controller")
    def _want(self, c) -> dict[str, str] | None:
        conf = render_slicer_config(c.facts, c.s)
        if conf is None:
            return None
        want = {str(SLICER_DIR / "config.json"): conf,
                f"/etc/systemd/system/{SLICER_UNIT}": render_slicer_unit(c.facts, slicer_lends(c.facts, c.s))}
        if slicer_lends(c.facts, c.s) and SLICER_AVAHI.parent.parent.is_dir():
            want[str(SLICER_AVAHI)] = render_avahi(c.facts, c.s)
        return want
    def check(self, c):
        if slicer_remote(c.s):
            return SlicerJoin.check(c)
        if not slices_here(c.facts, c.s) or orca_cant_run():
            on = is_enabled(SLICER_UNIT) or is_active(SLICER_UNIT)
            return (not on, "slicer off" if not on else "still running")
        if not os.access(orca_binary(), os.X_OK) and c.defer_downloads:
            return (True, "waits for the slicer engine")
        want = self._want(c)
        if want is None:
            # Not a failure: a missing settings file mustn't roll a release back. Nothing runs until it's there.
            return (True, f"on, waiting for {slicer_home(c.facts) / 'printer.json'}")
        if c.switched_from:
            return (False, "new release: the service restarts on it")
        stale = [Path(p).name for p, t in want.items() if read(p) != t]
        if stale:
            return (False, "needs writing: " + ", ".join(stale))
        if not (is_enabled(SLICER_UNIT) and is_active(SLICER_UNIT)):
            return (False, "not running")
        return (True, f"slicing on :{SLICER_PORT}, /slice on the app's port")
    def apply(self, c):
        if not slicer_lends(c.facts, c.s) and SLICER_AVAHI.exists():
            sudo("rm", "-f", str(SLICER_AVAHI), check=False)      # it doesn't lend: stop saying so
        if slicer_remote(c.s) or not slices_here(c.facts, c.s) or orca_cant_run():
            if unit_exists(SLICER_UNIT):
                sudo("systemctl", "disable", "--now", SLICER_UNIT, check=False)
            if slicer_remote(c.s):
                SlicerJoin.apply(c)
            return
        want = self._want(c)
        if want is None:
            return
        SLICER_DIR.mkdir(parents=True, exist_ok=True)
        SLICER_WORK.mkdir(parents=True, exist_ok=True)
        changed = False
        for path, text in want.items():
            if read(path) == text:
                continue
            changed = True
            if path.startswith("/etc/avahi/"):
                sudo("mkdir", "-p", str(SLICER_AVAHI.parent))
                sudo_write(path, text)
            elif path.startswith("/etc/"):
                sudo_write(path, text)
                sudo("systemctl", "daemon-reload")
            else:
                Path(path).write_text(text)
        sudo("systemctl", "enable", SLICER_UNIT)
        sudo("systemctl", "restart" if (changed or c.switched_from or not is_active(SLICER_UNIT)) else "start", SLICER_UNIT)


def render_bench_unit(facts: dict, s: dict) -> str:
    py = DOOR_VENV / "bin" / "python"
    return f"""# Managed by elyir-bench (docs/bench.md)
[Unit]
Description=Elyir Bench Bench Box: the printers on the bench, finding and asking more
After=network-online.target
ConditionPathExists={CURRENT}/bench/bench_service.py

[Service]
User={facts['user']}
ExecStart={py} {CURRENT}/bench/bench_service.py --state {DOOR_STATE / 'bench'} --name "{s['printer_name']}" --serve-port {s['port']} --port {BENCH_PORT} --relay-api {s.get('relay_api') or DEFAULT_RELAY_API} --door-bin {DOOR_BIN} --remote {s.get('remote', 'off')} --home-port 443 --remote-name {s.get('remote_name') or public_name()}
# the Kobras' names at home are served on 443 by the Caddy this service starts (bench/doors.py); the same Caddy
# serves the box's own public name in front of its away listener, 127.0.0.1:8189 (bench/away.py)
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


class BenchService(Step):
    """A Bench Box's own service: its printers, finding and asking more, each printer passed through to its screen."""
    name = "bench service"
    roles = ("controller",)
    def check(self, c):
        unit = f"/etc/systemd/system/{BENCH_UNIT}"
        if read(unit) != render_bench_unit(c.facts, c.s):
            return (False, "needs writing")
        if c.switched_from:
            return (False, "new release: the service restarts on it")
        if not (is_enabled(BENCH_UNIT) and is_active(BENCH_UNIT)):
            return (False, "not running")
        return (True, f"the bench on :{BENCH_PORT}, /bench/ on the screen's port")
    def apply(self, c):
        unit = f"/etc/systemd/system/{BENCH_UNIT}"
        if read(unit) != render_bench_unit(c.facts, c.s):
            sudo_write(unit, render_bench_unit(c.facts, c.s))
            sudo("systemctl", "daemon-reload")
        sudo("systemctl", "enable", BENCH_UNIT)
        sudo("systemctl", "restart", BENCH_UNIT)


class WifiSetup(Step):
    """A new printer's first Wi-Fi (docs/setup.md): with no network, a setup Wi-Fi and a page for a phone or the panel."""
    name = "first wi-fi"

    def _want(self, c: Ctx) -> dict[str, str]:
        return {f"/etc/systemd/system/{WIFI_UNIT}": render_wifi_unit(c.facts, c.s), str(WIFI_DNS): WIFI_DNS_CONF,
                f"/etc/nginx/sites-available/{WIFI_SITE}": render_wifi_site(c.facts)}

    def check(self, c):
        if not c.facts.get("network_manager"):
            return (True, "no NetworkManager here: its Wi-Fi is set up some other way")
        if missing_packages(["dnsmasq-base"]):
            why = load_state().get("wifi_setup_unavailable")
            if why:
                return (True, f"not available here: {why}")
            return (False, "dnsmasq-base to install (the setup Wi-Fi's addresses)")
        for path, text in self._want(c).items():
            if read(path) != text:
                return (False, f"{path} needs writing")
        if not Path(f"/etc/nginx/sites-enabled/{WIFI_SITE}").exists():
            return (False, "its nginx site to enable")
        if c.switched_from:
            return (False, "new release: the service restarts on it")
        if not (is_enabled(WIFI_UNIT) and is_active(WIFI_UNIT)):
            return (False, "not running")
        return (True, f"ready: with no network, a setup Wi-Fi at {WIFI_ADDR}")

    def apply(self, c):
        if not c.facts.get("network_manager"):
            return
        if missing_packages(["dnsmasq-base"]):
            try:
                apt_install("dnsmasq-base")
            except StepFailed as e:
                # Only for a printer with no network at all; one being updated has one, so never stop an update for it
                why = "dnsmasq-base can't be installed: " + (str(e).strip().splitlines() or ["apt failed"])[-1][:200]
                st = load_state(); st["wifi_setup_unavailable"] = why; save_state(st)
                c.notes.append(f"the first Wi-Fi isn't available on this printer ({why})")
                return
        for path, text in self._want(c).items():
            if read(path) != text:
                if path == str(WIFI_DNS):
                    sudo("mkdir", "-p", str(WIFI_DNS.parent))
                sudo_write(path, text)
        sudo("ln", "-sf", f"/etc/nginx/sites-available/{WIFI_SITE}", f"/etc/nginx/sites-enabled/{WIFI_SITE}")
        sudo("nginx", "-t", "-q")
        sudo("systemctl", "reload", "nginx")
        sudo("systemctl", "daemon-reload")
        sudo("systemctl", "enable", WIFI_UNIT)
        sudo("systemctl", "restart", WIFI_UNIT)


class PowerKey(Step):
    """The power button turns the printer off like Care's Turn off (design/power/, A): logind ignores a short press (a
    long press still halts at once) and elyir-bench-power-key.service turns it into Turn off, so the nozzle cools first.
    On a Bench Box, with Moonraker off, a press powers off at once. Only where there is such a button (the Pi 5)."""
    name = "power button"
    roles = ("printer", "controller")

    def _want(self, c: Ctx) -> dict[str, str]:
        return {f"/etc/systemd/system/{POWER_KEY_UNIT}": render_power_key_unit(c.facts), str(LOGIND_POWER): LOGIND_POWER_CONF}

    def check(self, c):
        if not power_button():
            return (True, "none on this machine")
        for path, text in self._want(c).items():
            if read(path) != text:
                return (False, f"{path} needs writing")
        if c.switched_from:
            return (False, "new release: the service restarts on it")
        if not (is_enabled(POWER_KEY_UNIT) and is_active(POWER_KEY_UNIT)):
            return (False, "not running")
        return (True, "a press cools the nozzle, then turns off; a long press halts at once")

    def apply(self, c):
        if not power_button():
            return
        logind = read(LOGIND_POWER) != LOGIND_POWER_CONF
        for path, text in self._want(c).items():
            if read(path) != text:
                if path == str(LOGIND_POWER):
                    sudo("mkdir", "-p", str(LOGIND_POWER.parent))
                sudo_write(path, text)
        sudo("systemctl", "daemon-reload")
        sudo("systemctl", "enable", POWER_KEY_UNIT)
        sudo("systemctl", "restart", POWER_KEY_UNIT)
        if logind:   # logind reads its settings again on HUP; restarting it would end the panel's session
            sudo("systemctl", "kill", "-s", "HUP", "systemd-logind")


POWER_WARNINGS = ("The shutdown API will be disabled", "The reboot API will be disabled")


def power_blocked(facts: dict) -> bool | None:
    """Moonraker can't turn the Pi off or restart it (no PolicyKit rules for it: it says so in its warnings), or None
    when it can't be asked. Care's Turn off then ends in "couldn't turn itself off" (design/power/)."""
    try:
        warnings = http_json(f"{facts['moonraker']['url']}/server/info", timeout=4)["result"].get("warnings") or []
    except Exception:
        return None
    return any(w in str(x) for x in warnings for w in POWER_WARNINGS)


class PowerPermission(Step):
    """Moonraker may turn the Pi off and restart it (design/power/: Turn off, Restart, the power button). A printer
    set up by KIAUH or the image already lets it; one set up another way may not. The fix is Moonraker's own
    scripts/set-policykit-rules.sh, which picks the rules for this PolicyKit and gives Moonraker its group."""
    name = "turning off"

    def check(self, c):
        blocked = power_blocked(c.facts)
        if blocked is None:
            return (True, "not checked: Moonraker isn't answering")
        if blocked:
            return (False, "Moonraker isn't allowed to turn the Pi off: its PolicyKit rules to add")
        return (True, "Moonraker can turn the Pi off and restart it")

    def apply(self, c):
        if not power_blocked(c.facts):
            return
        script = HOME / "moonraker" / "scripts" / "set-policykit-rules.sh"
        if sudo_mode() != "full":
            raise StepFailed(f"needs the printer's own sudo once: {script}")
        if not shutil.which("pkaction"):
            try:
                apt_install("polkitd")
            except Exception:
                apt_install("policykit-1")      # Debian 11
        if not script.is_file():
            raise StepFailed(f"{script} isn't there: Moonraker's PolicyKit rules can't be added this way")
        p = run(["/bin/bash", str(script)], check=False, timeout=300)
        if p.returncode != 0:
            said = (p.stderr or p.stdout or "").strip().splitlines()
            raise StepFailed("Moonraker's set-policykit-rules.sh failed" + (f": {said[-1]}" if said else ""))
        sudo("systemctl", "restart", "moonraker")   # it checks its permissions as it starts


def rename(facts: dict, s: dict, name: str) -> None:
    """The printer's name everywhere: its settings now, its name on the network here, the rest by apply."""
    s["printer_name"] = name
    host = hostname_for(name)
    if facts["host"].split(".")[0] != host:
        sudo("hostnamectl", "set-hostname", host)
        sudo_write("/etc/hosts", render_hosts(read("/etc/hosts"), host))
        sudo("systemctl", "restart", "avahi-daemon", check=False)
        facts["host"] = host


class SlicerJoin:
    """This printer slices on another machine (slicer: <address>). It joins that slicer, which copies this
    printer's profile (elyir-bench-slicer/ next to elyir-bench.conf) from its Moonraker and slices only for
    it when asked through this printer's /slice. A slicer that's switched off never fails an apply."""

    @staticmethod
    def _url(c) -> str:
        host, port = slicer_target(slicer_remote(c.s))
        return f"http://{resolve4(host) or host}:{port}/slice/printers/{slicer_id(c.s)}"

    @staticmethod
    def check(c) -> tuple[bool, str]:
        remote = slicer_remote(c.s)
        if not (slicer_home(c.facts) / "printer.json").exists():
            return (True, f"on {remote}, waiting for {slicer_home(c.facts) / 'printer.json'}")
        if unit_exists(SLICER_UNIT) and (is_enabled(SLICER_UNIT) or is_active(SLICER_UNIT)):
            return (False, "this printer's own slicer is still running")
        try:
            got = http_json(SlicerJoin._url(c), timeout=5)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                try:
                    if json.loads(e.read().decode()).get("refused"):
                        return (True, f"{c.s.get('slicer_name') or remote} said no; it can be asked again tomorrow")
                except ValueError:
                    pass
            return (False, f"not joined to {remote} yet" if e.code == 404 else f"{remote} answered {e.code}")
        except Exception:
            return (True, f"on {remote}, which isn't answering; it joins on the next apply")
        who = c.s.get("slicer_name") or remote
        if got.get("waiting"):
            return (True, f"asked {who}; waiting for a yes on its screen")
        if got.get("name") != c.s["printer_name"] or got.get("moonraker") != this_moonraker(c.facts):
            return (False, f"joined {remote} under an old name or address")
        return (True, f"slicing on {who}" + (f" ({remote})" if who != remote else ""))

    @staticmethod
    def apply(c) -> None:
        body = json.dumps({"name": c.s["printer_name"], "moonraker": this_moonraker(c.facts)}).encode()
        req = urllib.request.Request(SlicerJoin._url(c), data=body, method="PUT",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:      # it copies the presets before it answers
                got = json.loads(r.read().decode() or "{}")
            if got.get("waiting"):
                c.notes.append(f"slicer: asked {got.get('slicer') or slicer_remote(c.s)} to slice for {c.s['printer_name']}; "
                               "say yes on its screen")
        except urllib.error.HTTPError as e:
            try:
                why = json.loads(e.read().decode()).get("error") or e.reason
            except ValueError:
                why = e.reason
            c.notes.append(f"slicer: {why}")
        except Exception as e:
            c.notes.append(f"slicer: {slicer_remote(c.s)} couldn't be reached ({e.__class__.__name__}); it joins on the next apply")


class BootScreen(Step):
    """The eye from power-on: Plymouth's theme in the initramfs, a quiet kernel command line, no
    rainbow and no tty1 login prompt, and Plymouth's last frame kept until the kiosk draws. Only
    with the Elyir Bench panel; boot_screen: off puts the Pi's own boot text back."""
    name = "boot screen"
    # a Bench Box too: its panel's kiosk is on tty1 and conflicts with the login prompt this step turns off,
    # so without it the box's screen can come up blank after a restart (render_kiosk_unit)
    roles = ("printer", "controller")
    @staticmethod
    def _pi(c):
        # cmdline.txt, config.txt and the initramfs hook are Raspberry Pi OS's; other boards boot otherwise
        model = c.facts.get("model") or ""
        return not model or "Raspberry Pi" in model
    def _on(self, c):
        return boot_screen_wanted(c.facts, c.s)
    @staticmethod
    def _orientation(c):
        return orientation_arg(c.output, panel_rotation(c.facts, c.s))
    def _theme(self):
        src = CURRENT / "kiosk" / "boot" / "plymouth"
        names = sorted(p.name for p in src.iterdir() if p.is_file()) if src.is_dir() else []
        return src, names, (tree_hash(src, names) if names else None)
    @staticmethod
    def _plymouth():
        return run(["dpkg-query", "-W", "-f=${Status}", "plymouth"], check=False).stdout.strip() == "install ok installed"
    @staticmethod
    def _default_theme():
        # it lives in /usr/sbin, which isn't on the printer user's PATH
        return run([sudo_bin("plymouth-set-default-theme")], check=False).stdout.strip()
    def _todo(self, c) -> list[str]:
        on, b = self._on(c), boot_dir()
        todo = []
        if on:
            src, names, want = self._theme()
            if not want:
                return ["this release has no boot theme (kiosk/boot/plymouth)"]
            if not self._plymouth():
                todo.append("install plymouth")
            elif self._default_theme() != PLYMOUTH_THEME:
                todo.append("make the eye Plymouth's theme")
            if tree_hash(Path(PLYMOUTH_DIR), names) != want:
                todo.append("theme files")
            if load_state().get("boot_initramfs") != want:
                todo.append("initramfs")
            if read(PLYMOUTH_QUIT_DROPIN) != PLYMOUTH_QUIT_CONF:
                todo.append("handoff to the kiosk")
            if is_enabled("getty@tty1.service"):
                todo.append("tty1 login prompt")
        else:
            if Path(PLYMOUTH_QUIT_DROPIN).exists():
                todo.append("handoff drop-in")
            if load_state().get("boot_getty_disabled") and not is_enabled("getty@tty1.service"):
                todo.append("tty1 login prompt")
        cmd = read(b / "cmdline.txt")
        if cmd and cmd != render_cmdline(cmd, on, read(b / "cmdline.txt.elyir-bench-orig") or None, self._orientation(c)):
            todo.append("kernel command line")
        cfg = read(b / "config.txt")
        if cfg and cfg != render_config_txt(cfg, on):
            todo.append("config.txt")
        return todo
    def check(self, c):
        todo = self._todo(c)
        if not todo:
            if not self._pi(c):
                return (True, f"off: Raspberry Pi only, this is {c.facts['model']}")
            return (True, "the eye, from power-on" if self._on(c) else "off: the Pi's own boot text")
        return (False, ", ".join(todo))
    def apply(self, c):
        on, b = self._on(c), boot_dir()
        cmd_p, cfg_p, orig_p = b / "cmdline.txt", b / "config.txt", b / "cmdline.txt.elyir-bench-orig"
        if on:
            src, names, want = self._theme()
            if not want:
                raise StepFailed("this release has no boot theme (kiosk/boot/plymouth); rebuild it")
            if not self._plymouth():
                apt_install("plymouth")
            if tree_hash(Path(PLYMOUTH_DIR), names) != want:
                sudo("mkdir", "-p", PLYMOUTH_DIR)
                sudo("cp", "-rT", f"{CURRENT}/kiosk/boot/plymouth", PLYMOUTH_DIR)
            if self._default_theme() != PLYMOUTH_THEME:
                sudo("plymouth-set-default-theme", PLYMOUTH_THEME)
            # Plymouth starts from the initramfs, so the theme has to be in it to draw early
            if load_state().get("boot_initramfs") != want:
                sudo("update-initramfs", "-u", timeout=900)
                st = load_state(); st["boot_initramfs"] = want; save_state(st)
            if read(PLYMOUTH_QUIT_DROPIN) != PLYMOUTH_QUIT_CONF:
                sudo("mkdir", "-p", str(Path(PLYMOUTH_QUIT_DROPIN).parent))
                sudo_write(PLYMOUTH_QUIT_DROPIN, PLYMOUTH_QUIT_CONF)
                sudo("systemctl", "daemon-reload")
            if is_enabled("getty@tty1.service"):
                sudo("systemctl", "disable", "getty@tty1.service")
                st = load_state(); st["boot_getty_disabled"] = True; save_state(st)
        else:
            if Path(PLYMOUTH_QUIT_DROPIN).exists():
                sudo("rm", "-f", PLYMOUTH_QUIT_DROPIN)
                sudo("systemctl", "daemon-reload")
            if load_state().get("boot_getty_disabled"):
                sudo("systemctl", "enable", "getty@tty1.service")
                st = load_state(); st["boot_getty_disabled"] = False; save_state(st)
        # The boot files last, once everything they switch on is in place. Each is one tee of the
        # whole file; a first install that fails afterwards puts the old text back.
        cmd = read(cmd_p)
        new = render_cmdline(cmd, on, read(orig_p) or None, self._orientation(c))
        if cmd and new != cmd:
            if not orig_p.exists():
                sudo("cp", "-n", str(cmd_p), str(orig_p))
            sudo_write(str(cmd_p), new)
            c.undo.append(("kernel command line", lambda: sudo_write(str(cmd_p), cmd)))
        cfg = read(cfg_p)
        new_cfg = render_config_txt(cfg, on)
        if cfg and new_cfg != cfg:
            sudo_write(str(cfg_p), new_cfg)
            c.undo.append(("config.txt", lambda: sudo_write(str(cfg_p), cfg)))
        c.notes.append("the boot screen changes from the next power-on or restart")


class NetworkWait(Step):
    """Starting without waiting for the Wi-Fi. NetworkManager-wait-online holds network-online.target, and with it
    Klipper, Moonraker, nginx and the panel, until the Wi-Fi has an address: about 6 s of every boot on a Pi 5. Nothing here
    needs the network to start: Moonraker and crowsnest bind locally, Elyir Bench's door, Caddy and frpc restart until
    they reach the relay, the home certificate is retried by its timer, and the first Wi-Fi looks for itself.
    network_wait: on puts the wait back; only a wait this step turned off is turned back on."""
    name = "network wait"
    roles = ("printer", "controller")
    @staticmethod
    def _off(c):
        return c.s.get("network_wait", "off") != "on"
    def check(self, c):
        if not unit_exists(NM_WAIT_UNIT):
            return (True, "no NetworkManager wait here")
        if self._off(c):
            return (False, "every boot waits for the Wi-Fi") if is_enabled(NM_WAIT_UNIT) else \
                   (True, "off: starts without waiting for the Wi-Fi")
        if load_state().get("network_wait_disabled") and not is_enabled(NM_WAIT_UNIT):
            return (False, "put the wait for the Wi-Fi back")
        return (True, "on: waits for the Wi-Fi")
    def apply(self, c):
        if self._off(c):
            sudo("systemctl", "disable", NM_WAIT_UNIT)
            st = load_state(); st["network_wait_disabled"] = True; save_state(st)
            c.notes.append("the printer stops waiting for the Wi-Fi from the next power-on")
        else:
            sudo("systemctl", "enable", NM_WAIT_UNIT)
            st = load_state(); st["network_wait_disabled"] = False; save_state(st)


STEPS: list[Step] = [Preflight(), Release(), Legacy(), Component(), MoonrakerConf(), StartMacro(), FilamentUnits(), Web(),
                     Announce(), Panel(),
                     WifiSetup(),
                     KlipperScreenMenu(),
                     DoorRuntime(), DoorBinaries(), RemoteName(), DoorServices(), SlicerEngine(), SlicerService(), BenchService(),
                     BootScreen(), PowerKey(), PowerPermission(), NetworkWait()]


# `elyir-bench panel <mode>` (also run by the panel itself, Care > Printer screen) only touches the screen
SCREEN_STEPS: list[Step] = [Panel(), KlipperScreenMenu(), BootScreen()]

# `elyir-bench startmacro on|off` (also run by the intent layer, Finish setting up): the macro, and this printer's own
# slicer told about it (a slicer elsewhere reads printer.json again by itself)
START_MACRO_STEPS: list[Step] = [StartMacro(), SlicerService()]

# `elyir-bench remote invite <code>`: the public name and the door, nothing that touches Klipper, so it runs mid-print
REMOTE_STEPS: list[Step] = [DoorRuntime(), DoorBinaries(), RemoteName(), DoorServices()]

# `elyir-bench remove`: the steps that turn themselves off, the start macro first (Klipper restarts without it)
REMOVE_STEPS: list[Step] = [StartMacro(), Panel(), BootScreen(), NetworkWait(), DoorServices(), SlicerService()]


# ── Bring it over (docs/bring-it-over.md, design/printer-setup/ A) ───────────────────────────────────────────
# A fresh card has Klipper and no printer.cfg. Most people flashing one are moving a printer that worked yesterday, so
# its setup is brought over from where it is: an old card in a USB reader (mounted read-only, never written to),
# another printer on the Wi-Fi (its Moonraker), or a backup file sent from a phone (config/elyir-bench-bring/).

BRING_MOUNTS = Path("/run/elyir-bench-bring")        # an old card, mounted read-only while it's read
BRING_CACHE = DOOR_STATE / "bring.json"            # what the last scan found, for plan and apply; addresses typed in
BRING_FOLDER = "elyir-bench-bring"                   # in the config folder: a backup sent from a phone or computer
BRING_DEV_GLOBS = ("sd[a-z]", "sd[a-z][0-9]", "sd[a-z][0-9][0-9]")   # a USB reader's disk or partition (the sudo rule)
BRING_DEV = re.compile(r"sd[a-z][0-9]{0,2}")
BRING_ARCHIVES = (".zip", ".tar.gz", ".tgz")
BRING_KEPT = "config-before-bring-"                # the config folder that was here, kept beside the new one
BRING_KEEP_HERE = ("elyir-bench.conf",)              # this printer's own settings (and the door's), never another's
MOONRAKER_PORT = 7125
DB_FILE = "moonraker-sql.db"
# a plain Moonraker can't send its database: these of its namespaces are its own, or rebuilt here by themselves
BRING_ITEMS_SKIP = {"moonraker", "database", "update_manager", "gcode_metadata", "announcements", "history",
                    "authorized_users", "elyir-bench"}
# Klipper sections that aren't modules in klippy/extras (a section that's in neither needs an add-on)
KLIPPER_CORE = ("printer", "mcu", "include", "stepper", "extruder", "dual_carriage", "carriage", "kinematic")
NOT_FOUND = "Not found: plug it in, or it can be changed after"


def bring_emit(as_json: bool, obj: dict) -> None:
    """One line of what `elyir-bench bring` says: JSON for the component (its last line is the answer), words here."""
    if as_json:
        print(json.dumps(obj), flush=True)
    elif "progress" in obj:
        p = obj["progress"]
        print(f"  … {p['step']} ({p['done']}/{p['of']})", flush=True)
    elif "failed" in obj:
        print(f"  ✗ {obj['failed']}", flush=True)


def http_post(url: str, body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def http_error(e: Exception) -> str:
    """What Moonraker said when it refused, else what went wrong, short."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            err = json.loads(e.read().decode()).get("error") or {}
            return str(err.get("message") or err) if isinstance(err, dict) else str(err)
        except Exception:
            return f"HTTP {e.code}"
    return str(getattr(e, "reason", "") or e) or e.__class__.__name__


def bring_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


# ── reading a config ─────────────────────────────────────────────────────────

def cfg_sections(text: str) -> list[tuple[str, dict[str, str]]]:
    """Klipper's sections in one file and their options (values without comments), above the SAVE_CONFIG block."""
    out: list[tuple[str, dict[str, str]]] = []
    for line in text.splitlines():
        if line.startswith("#*#"):
            break
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            out.append((" ".join(m.group(1).split()), {}))
            continue
        if not out or not line or line[0] in " \t#;":
            continue
        m = re.match(r"^([^:=\s]+)\s*[:=]\s*(.*)$", line)
        if m:
            out[-1][1][m.group(1).lower()] = re.split(r"\s+[#;]", m.group(2), maxsplit=1)[0].strip()
    return out


def cfg_included(texts: dict[str, str], start: str = "printer.cfg") -> list[str]:
    """The files Klipper reads: printer.cfg and what it includes, in order, as paths in the config folder."""
    order, todo = [], [start]
    while todo:
        rel = todo.pop(0)
        if rel in order or rel not in texts:
            continue
        order.append(rel)
        for m in re.finditer(r"(?m)^\[include\s+([^\]]+?)\s*\]", texts[rel]):
            pat = os.path.normpath(os.path.join(os.path.dirname(rel), m.group(1).strip()))
            depth = len(pat.split("/"))
            todo += sorted(r for r in texts if len(r.split("/")) == depth and fnmatch.fnmatchcase(r, pat))
    return order


def cfg_boards(texts: dict[str, str]) -> list[dict]:
    """The boards a config names: every [mcu …] with its serial or CAN id, and other USB devices with a serial
    (a filament unit, a probe), each with the file and section it's in."""
    out = []
    for rel in cfg_included(texts):
        for section, opts in cfg_sections(texts[rel]):
            word = section.split()[0].lower()
            if word == "mcu" and opts.get("canbus_uuid"):
                out.append({"section": section, "file": rel, "can": opts["canbus_uuid"].lower()})
            elif opts.get("serial") and (word == "mcu" or opts["serial"].startswith("/dev/serial/")):
                out.append({"section": section, "file": rel, "serial": opts["serial"]})
    return out


def serial_chip(serial: str) -> str | None:
    """stm32f446xx from /dev/serial/by-id/usb-Klipper_stm32f446xx_2B0035000F51313236343430-if00."""
    m = re.search(r"usb-(?:Klipper|katapult|CanBoot)_([A-Za-z0-9]+)_", serial)
    return m.group(1).lower() if m else None


def chip_words(chip: str) -> str:
    """stm32f446xx -> STM32F446, rp2040 -> RP2040."""
    c = chip.upper()
    return c[:-2] if c.endswith("XX") else c


def serial_family(name: str) -> str:
    """A by-id name with its serial number taken out: two boards of the same kind share it."""
    return re.sub(r"_[^_]+(-if\d+)$", r"_*\1", name)


def board_label(section: str, serial: str = "") -> str:
    if serial == "/tmp/klipper_host_mcu":
        return "The Pi itself"
    word, _, rest = section.partition(" ")
    word, r = word.lower(), rest.lower()
    if word == "mcu":
        if not rest:
            return "Main board"
        if r in ("rpi", "host", "pi", "linux"):
            return "The Pi itself"
        if any(k in r for k in ("ebb", "sb2040", "sht", "tool", "head", "nhk", "nitehawk", "can")):
            return "Toolhead board"
        return f"The {rest} board"
    if word == "ace":
        return "ACE Pro"
    return word.replace("_", " ").capitalize()


def the(name: str) -> str:
    """Main board -> The main board, ACE Pro -> The ACE Pro."""
    if name.startswith("The "):
        return name
    return "The " + (name[0].lower() + name[1:] if name[1:2].islower() else name)


def board_names(boards: list[dict]) -> list[str]:
    """For the source list: stm32f446xx, can 6cc850bbec73, usb-ANYCUBIC_ACE_1-if00."""
    out = []
    for b in boards:
        if b.get("can"):
            out.append(f"can {b['can']}")
        else:
            out.append(serial_chip(b["serial"]) or b["serial"].rsplit("/", 1)[-1])
    return out


def cfg_needs(texts: dict[str, str], klippy: Path | None = None) -> list[str]:
    """Sections Klipper here has no module for (an add-on the old printer had: [ace], [led_effect], [beacon]).
    Empty when there's no Klipper here to ask."""
    extras = (klippy or HOME / "klipper" / "klippy") / "extras"
    if not extras.is_dir():
        return []
    out = []
    for rel in cfg_included(texts):
        for section, _ in cfg_sections(texts[rel]):
            word = section.split()[0].lower()
            if word.startswith(KLIPPER_CORE) or word in out:
                continue
            if not (extras / f"{word}.py").is_file() and not (extras / word).is_dir():
                out.append(word)
    return out


def render_serial(text: str, section: str, serial: str) -> str:
    """One file with the serial of one section set, everything else as it was."""
    lines, inside = text.splitlines(keepends=True), False
    for i, line in enumerate(lines):
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            inside = " ".join(m.group(1).split()) == section
            continue
        if line.startswith("#*#"):
            break
        if inside and re.match(r"^serial\s*[:=]", line):
            lines[i] = re.sub(r"^(serial\s*[:=]\s*)\S*", lambda mm: mm.group(1) + serial, line, count=1)
            break
    return "".join(lines)


def strip_intent(text: str) -> str:
    m = MoonrakerConf()._section(text)
    return text if not m else text[:m.start()] + text[m.end():]


def render_brought_moonraker(brought: str | None, current: str, section: str) -> str:
    """The brought moonraker.conf (none brought: this one) with this printer's own [printer_intent], its name and
    Elyir Bench's component, never the old printer's. `section` is used when this card's has none."""
    m = MoonrakerConf()._section(current)
    text = strip_intent(current if brought is None else brought).rstrip("\n") + "\n"
    return text + "\n" + (m.group(0) if m else section).rstrip("\n") + "\n"


def db_facts(path: Path) -> dict:
    """What a Moonraker database holds: prints in its history, namespaces and keys, Mainsail's name for it."""
    import sqlite3
    out: dict = {"history": 0, "keys": set(), "name": None}
    con = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "namespace_store" in tables:
            out["keys"] = {(ns, k) for ns, k in con.execute("SELECT namespace, key FROM namespace_store")}
            row = con.execute("SELECT value FROM namespace_store WHERE namespace='mainsail' AND key='general'").fetchone()
            try:
                general = json.loads(bytes(row[0])) if row else {}
                out["name"] = (general.get("printername") or "").strip() or None
            except (ValueError, TypeError, AttributeError):
                pass
        if "job_history" in tables:
            out["history"] = con.execute("SELECT COUNT(*) FROM job_history").fetchone()[0]
        else:   # a Moonraker from before its history was a table
            out["history"] = sum(1 for ns, _ in out["keys"] if ns == "history")
    finally:
        con.close()
    return out


def clean_database(path: Path) -> None:
    """Another card's database without what was that printer's alone: Moonraker's logins and API key, and how many
    phones listened to it (this printer's door knows its own)."""
    import sqlite3
    con = sqlite3.connect(str(path))
    try:
        with con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "authorized_users" in tables:
                con.execute("DELETE FROM authorized_users")
            if "namespace_store" in tables:
                con.execute("DELETE FROM namespace_store WHERE namespace='authorized_users' "
                            "OR (namespace='elyir-bench' AND key='phones')")
        con.execute("VACUUM")   # and not left in the file's free pages either
    finally:
        con.close()


# ── where a setup comes from ─────────────────────────────────────────────────

class BringSource:
    """A printer's setup, wherever it is: config files as local paths, its gcodes, its Moonraker database."""
    kind = ""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="elyir-bench-bring-")
        self.tmp = Path(self._tmp.name)
        self._db: Path | None | bool = False      # False: not looked yet

    def close(self) -> None:
        self._tmp.cleanup()

    def config_files(self, hidden: bool = False) -> dict[str, Path]:
        raise NotImplementedError

    def gcode_files(self) -> dict[str, int]:
        """path in the gcodes folder -> bytes"""
        return {}

    def copy_gcode(self, rel: str, dest: Path) -> None:
        raise NotImplementedError

    def fetch_database(self, dest: Path) -> bool:
        return False

    def items(self) -> dict | None:
        """Namespaces to write one by one, for a Moonraker that can't send its database."""
        return None

    def name_hint(self) -> str | None:
        return None

    def texts(self) -> dict[str, str]:
        if not hasattr(self, "_texts"):
            self._texts = {rel: read(p) for rel, p in self.config_files(True).items()
                           if rel.endswith((".cfg", ".conf"))}
        return self._texts

    def database(self) -> Path | None:
        """A copy of its database, made once, cleaned of what was the other printer's alone."""
        if self._db is False:
            dest = self.tmp / DB_FILE
            try:
                self._db = dest if self.fetch_database(dest) else None
                if self._db:
                    clean_database(dest)
            except Exception as e:
                print(f"bring: the database couldn't be read: {e}", file=sys.stderr)
                self._db = None
        return self._db or None

    def facts(self) -> dict:
        """history (prints, None when it can't come), keys, mainsail name, and whether it's an older database."""
        db = self.database()
        if db:
            return db_facts(db)
        items = self.items()
        if items is not None:
            return {"history": None, "keys": {(ns, k) for ns, v in items.items() for k in (v or {})}, "name": None}
        return {"history": None, "keys": set(), "name": None}


def walk_files(root: Path, folder: Path, hidden: bool, skip=lambda rel: False) -> dict[str, Path]:
    """Every file under `folder` as {relative path: path}, following links as they'd read on that card: a link to
    /home/pi/klipper-macros means the card's own /home/pi/klipper-macros, never this Pi's. Links that lead off the
    card, and folders seen already, are left out."""
    out: dict[str, Path] = {}
    real_root = os.path.realpath(root)

    def resolve(link: Path) -> Path | None:
        p = link
        for _ in range(20):
            if not p.is_symlink():
                break
            target = os.readlink(p)
            p = Path(os.path.normpath(root / target.lstrip("/") if target.startswith("/") else p.parent / target))
        real = os.path.realpath(p)
        return p if (real == real_root or real.startswith(real_root + os.sep)) and p.exists() else None

    def walk(d: Path, rel: str, seen: set) -> None:
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            r = rel + e.name
            if (not hidden and e.name.startswith(".")) or skip(r):
                continue
            p = Path(e.path)
            if e.is_symlink():
                p = resolve(p)
                if p is None:
                    continue
            if p.is_dir():
                real = os.path.realpath(p)
                if real not in seen:
                    walk(p, r + "/", seen | {real})
            elif p.is_file():
                out[r] = p

    walk(folder, "", {os.path.realpath(folder)})
    return out


def bring_skip(rel: str) -> bool:
    """Never brought: this printer's own settings, a backup waiting to be brought, an earlier bring's kept folder."""
    top = rel.split("/", 1)[0]
    return top in BRING_KEEP_HERE or top == BRING_FOLDER or top.startswith(BRING_KEPT) or rel.endswith(".elyir-bench-bak")


class FolderSource(BringSource):
    """A printer_data folder: on an old card mounted read-only, or unpacked from a backup file."""
    kind = "card"

    def __init__(self, root: Path, pdata: Path | None, config: Path | None = None):
        super().__init__()
        self.root, self.pdata = root, pdata
        self.config = config or (pdata / "config" if pdata else root)

    def config_files(self, hidden: bool = False) -> dict[str, Path]:
        key = f"_files{hidden}"
        if not hasattr(self, key):
            setattr(self, key, walk_files(self.root, self.config, hidden, bring_skip))
        return getattr(self, key)

    def gcode_files(self) -> dict[str, int]:
        if not self.pdata or not (self.pdata / "gcodes").is_dir():
            return {}
        return {r: p.stat().st_size for r, p in walk_files(self.root, self.pdata / "gcodes", False).items()}

    def copy_gcode(self, rel: str, dest: Path) -> None:
        shutil.copy2(self.pdata / "gcodes" / rel, dest)

    def fetch_database(self, dest: Path) -> bool:
        """The card's database, copied with the files beside it (a write-ahead log not yet folded in), then made one
        file by SQLite itself: the card is read-only, so it's never opened there."""
        import sqlite3
        src = self.pdata / "database" / DB_FILE if self.pdata else None
        if not src or not src.is_file():
            return False
        work = self.tmp / "db-copy"
        work.mkdir(exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            if Path(f"{src}{suffix}").is_file():
                shutil.copy2(f"{src}{suffix}", work / f"{DB_FILE}{suffix}")
        a, b = sqlite3.connect(str(work / DB_FILE)), sqlite3.connect(str(dest))
        try:
            a.backup(b)
        finally:
            a.close()
            b.close()
        return True

    def older_database(self) -> bool:
        """Only an older Moonraker's database (LMDB, before 2024): Moonraker can't restore it."""
        return bool(self.pdata) and not (self.pdata / "database" / DB_FILE).is_file() \
            and (self.pdata / "database" / "data.mdb").is_file()

    def name_hint(self) -> str | None:
        host = read(self.root / "etc" / "hostname").strip()
        return host or None


def unpack_member_ok(name: str) -> bool:
    parts = Path(name).parts
    return bool(parts) and not name.startswith("/") and ".." not in parts


class ArchiveSource(FolderSource):
    """A backup sent from a phone or computer: a .zip or .tar.gz of a printer_data folder or of a config folder
    (KIAUH's look like this). Unpacked into a folder of its own, never with a path or a link that leads out."""
    kind = "file"

    def __init__(self, path: Path):
        BringSource.__init__(self)
        self.path = path
        self._all = self._members()
        cfgs = sorted((m for m in self._all if m.rsplit("/", 1)[-1] == "printer.cfg"), key=lambda m: m.count("/"))
        if not cfgs:
            self.close()
            raise StepFailed(f"{path.name} has no printer.cfg in it")
        cfg_dir = cfgs[0].rpartition("/")[0]
        head, _, last = cfg_dir.rpartition("/")
        pdata = head if last == "config" else None          # a printer_data folder, or only a config folder
        self.cfg_prefix = f"{cfg_dir}/" if cfg_dir else ""
        self.pdata_prefix = None if pdata is None else (f"{pdata}/" if pdata else "")
        root = self.tmp / "unpacked"
        root.mkdir()
        db = f"{self.pdata_prefix}database/" if self.pdata_prefix is not None else None
        self._unpack(root, lambda m: m.startswith(self.cfg_prefix) or bool(db and m.startswith(db)))
        self.root = root
        self.pdata = None if pdata is None else (root / pdata if pdata else root)
        self.config = root / cfg_dir if cfg_dir else root

    def _members(self) -> dict[str, int]:
        if self.path.name.endswith(".zip"):
            with zipfile.ZipFile(self.path) as z:
                return {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}
        with tarfile.open(self.path) as t:
            return {m.name.removeprefix("./"): m.size for m in t.getmembers() if m.isfile()}

    def _unpack(self, root: Path, want) -> None:
        if self.path.name.endswith(".zip"):
            with zipfile.ZipFile(self.path) as z:
                for i in z.infolist():
                    if not i.is_dir() and unpack_member_ok(i.filename) and want(i.filename):
                        dest = root / i.filename
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(i) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
                        t = _dt.datetime(*i.date_time).timestamp()
                        os.utime(dest, (t, t))
            return
        with tarfile.open(self.path) as t:
            for m in t.getmembers():
                name = m.name.removeprefix("./")
                if m.isfile() and unpack_member_ok(name) and want(name):   # files only: no links, no devices
                    dest = root / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with t.extractfile(m) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.utime(dest, (m.mtime, m.mtime))

    def gcode_files(self) -> dict[str, int]:
        if self.pdata_prefix is None:
            return {}
        pre = f"{self.pdata_prefix}gcodes/"
        return {m[len(pre):]: n for m, n in self._all.items()
                if m.startswith(pre) and not any(p.startswith(".") for p in m[len(pre):].split("/"))}

    def copy_gcode(self, rel: str, dest: Path) -> None:
        name = f"{self.pdata_prefix}gcodes/{rel}"
        if not hasattr(self, "_gcodes_out"):
            self._gcodes_out = self.tmp / "gcodes-unpacked"
            self._gcodes_out.mkdir()
            self._unpack(self._gcodes_out, lambda m: m.startswith(f"{self.pdata_prefix}gcodes/"))
        shutil.copy2(self._gcodes_out / name, dest)

    def name_hint(self) -> str | None:
        stem = self.path.name
        for ext in BRING_ARCHIVES:
            stem = stem.removesuffix(ext)
        return stem or None


class PrinterSource(BringSource):
    """Another printer on the Wi-Fi, through its Moonraker: an Elyir Bench printer by mDNS, or any Moonraker by
    address. Only read: files and history through the file and history API, its database from Elyir Bench's component
    there (Moonraker writes its own backups where its file API can't serve them)."""
    kind = "printer"

    def __init__(self, url: str, name: str | None = None):
        super().__init__()
        self.url, self._name = url.rstrip("/"), name

    def get(self, path: str, timeout: float = 6.0):
        return http_json(f"{self.url}{path}", timeout=timeout)["result"]

    def download(self, root: str, rel: str, dest: Path, mtime: float | None = None) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.url}/server/files/{root}/{urllib.parse.quote(rel)}"
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as out:
            shutil.copyfileobj(r, out)
        if mtime:
            os.utime(dest, (mtime, mtime))

    def config_files(self, hidden: bool = False) -> dict[str, Path]:
        if not hasattr(self, "_files"):
            self._files = {}
            for f in self.get("/server/files/list?root=config"):
                rel = f["path"]
                if bring_skip(rel):
                    continue
                dest = self.tmp / "config" / rel
                self.download("config", rel, dest, f.get("modified"))
                self._files[rel] = dest
        return {r: p for r, p in self._files.items()
                if hidden or not any(part.startswith(".") for part in r.split("/"))}

    def gcode_files(self) -> dict[str, int]:
        try:
            return {f["path"]: int(f.get("size") or 0) for f in self.get("/server/files/list?root=gcodes")
                    if not any(part.startswith(".") for part in f["path"].split("/"))}
        except Exception:
            return {}

    def copy_gcode(self, rel: str, dest: Path) -> None:
        self.download("gcodes", rel, dest)

    def bench(self) -> bool:
        """Runs an Elyir Bench that can send its database: Bring it over's own endpoint answers there. A printer on an
        older release answers /printer/intent but has no export (Studio, 6 October 2026), so it's read the way any
        Moonraker is, its settings key by key."""
        if not hasattr(self, "_bench"):
            try:
                self._intent = self.get("/printer/intent")
            except Exception:
                self._intent = None
            try:
                self._bench = self._intent is not None and self.get("/printer/intent/bring") is not None
            except Exception:
                self._bench = False
        return self._bench

    def klipper_version(self) -> str | None:
        try:
            return self.get("/printer/info").get("software_version") or None
        except Exception:
            return None

    def fetch_database(self, dest: Path) -> bool:
        import base64
        if not self.bench():
            return False
        got = self.get("/printer/intent/bring/export", timeout=60)
        dest.write_bytes(base64.b64decode(got["database"]))
        return True

    def items(self) -> dict | None:
        if self.bench():
            return None
        if not hasattr(self, "_items"):
            self._items = {}
            for ns in self.get("/server/database/list").get("namespaces", []):
                if ns not in BRING_ITEMS_SKIP:
                    try:
                        self._items[ns] = self.get(f"/server/database/item?namespace={urllib.parse.quote(ns)}")["value"]
                    except Exception:
                        pass
        return self._items

    def facts(self) -> dict:
        """Without fetching its database: its history's count and its namespaces, from the API."""
        if not self.bench():
            return super().facts()
        keys: set = set()
        try:
            for ns in self.get("/server/database/list").get("namespaces", []):
                keys.add((ns, ""))
                if ns in ("elyir-bench", "moonraker"):
                    keys |= {(ns, k) for k in (self.get(f"/server/database/item?namespace={ns}")["value"] or {})}
        except Exception:
            pass
        try:   # all its prints (the list's count is only how many one page holds)
            history = int(self.get("/server/history/totals")["job_totals"]["total_jobs"])
        except Exception:
            history = None
        return {"history": history, "keys": keys, "name": None}

    def name_hint(self) -> str | None:
        if self._name:
            return self._name
        if self.bench() and (self._intent or {}).get("printer", {}).get("name"):
            return self._intent["printer"]["name"]
        try:
            return self.get("/printer/info").get("hostname")
        except Exception:
            return None


# ── what's here ──────────────────────────────────────────────────────────────

def can_query(ifaces: list[str]) -> list[str] | None:
    """The CAN boards that answer Klipper's own query (scripts/canbus_query.py), which needs no config: boards no
    Klipper has claimed since they powered up, as on a fresh card. None when it can't be asked: no CAN set up here
    yet, or no Klipper to ask with."""
    script, py = HOME / "klipper" / "scripts" / "canbus_query.py", HOME / "klippy-env" / "bin" / "python"
    up = [i for i in ifaces if read(f"/sys/class/net/{i}/operstate").strip() in ("up", "unknown")]
    if not up or not script.is_file() or not py.is_file():
        return None
    found = []
    for iface in up:
        try:
            p = run([str(py), str(script), iface], check=False, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if p.returncode != 0:
            return None
        found += re.findall(r"canbus_uuid=([0-9a-fA-F]{12})", p.stdout)
    return [u.lower() for u in found]


def bring_here(facts: dict) -> dict:
    """What this Pi sees plugged in, to hold a config's boards against."""
    by_id = Path("/dev/serial/by-id")
    serial = sorted(p.name for p in by_id.glob("*")) if by_id.exists() else []
    v4l = Path("/dev/v4l/by-id")
    return {"serial": serial, "can_ifaces": list(facts.get("can") or []), "can": can_query(list(facts.get("can") or [])),
            "klipper": (facts.get("klipper") or {}).get("state"), "host_mcu": unit_exists("klipper-mcu.service"),
            "ace": facts.get("ace_units") or 0, "camera": v4l.exists() and any(v4l.glob("*"))}


def found_words(here: dict) -> list[str]:
    """What the first screen says it found (board a-start): the chips, never the boards they're on."""
    out = []
    klipper = [n for n in here["serial"] if serial_chip(n)]
    for i, n in enumerate(klipper):
        out.append(f"{'Main board' if i == 0 else 'Board'} · {chip_words(serial_chip(n))} on USB")
    can = here.get("can")
    if can:
        out.append("Toolhead board · on CAN" if len(can) == 1 and klipper else
                   "A board on CAN" if len(can) == 1 else f"{len(can)} boards on CAN")
    elif here["can_ifaces"]:
        out.append("A CAN adapter")
    if here["ace"]:
        out.append("ACE Pro" if here["ace"] == 1 else f"{here['ace']} ACE Pro units")
    if here["camera"]:
        out.append("Camera")
    return out


# USB-serial chips printer boards answer on before Klipper is on them (a CH340 on many stock boards, a CP210x, an FTDI)
USB_SERIAL_BRIDGE = re.compile(r"usb-(?:1a86_|QinHeng|Silicon_Labs_CP210|FTDI_)", re.I)


def printer_boards(here: dict) -> int:
    """How many printer boards are plugged in, for the first screen's printer or Bench Box (design/role/, B): Klipper
    serials, USB-serial chips (a board without Klipper yet), CAN boards, or a CAN adapter with none answering. Not a
    camera or a filament unit: a box may have those too."""
    klipper = [n for n in here["serial"] if serial_chip(n)]
    bridges = [n for n in here["serial"] if not serial_chip(n) and USB_SERIAL_BRIDGE.search(n)]
    can = here.get("can") or []
    return len(klipper) + len(bridges) + (len(can) if can else 1 if here.get("can_ifaces") else 0)


def match_boards(boards: list[dict], here: dict) -> list[dict]:
    """Each board a config names against what this Pi sees: same, changed (exactly one board of that kind is plugged
    in, with another serial: it will be set to that one), missing, or unchecked (CAN that can't be asked)."""
    serial_here = {f"/dev/serial/by-id/{n}" for n in here["serial"]}
    claimed = {b["serial"] for b in boards if b.get("serial") in serial_here}
    out = []
    for b in boards:
        name = board_label(b["section"], b.get("serial", ""))
        row: dict = {"name": name, "section": b["section"], "file": b["file"]}
        if b.get("can"):
            row["can"] = b["can"]
            if here["can"] is None:
                row.update(match="unchecked", words="Not checked: CAN isn't set up on this card yet"
                           if not here["can_ifaces"] else "Not checked")
            elif b["can"] in here["can"]:
                row.update(match="same", words="Same CAN ID")
            elif here["klipper"] == "ready":   # Klipper holds its boards: they don't answer the query
                row.update(match="unchecked", words="Not checked")
            else:
                row.update(match="missing", words=NOT_FOUND)
            out.append(row)
            continue
        serial = b["serial"]
        chip = serial_chip(serial)
        if chip:
            row["chip"] = chip
        if serial == "/tmp/klipper_host_mcu":
            row.update(match="same", words="Klipper's program for the Pi is here") if here["host_mcu"] else \
                row.update(match="missing", words="Klipper's program for the Pi isn't on this card yet")
        elif serial in serial_here:
            row.update(match="same", words=f"{chip_words(chip)}, same serial" if chip else "Found")
        elif serial.startswith("/dev/serial/by-id/"):
            family = serial_family(serial.rsplit("/", 1)[-1])
            like = [f"/dev/serial/by-id/{n}" for n in here["serial"]
                    if serial_family(n) == family and f"/dev/serial/by-id/{n}" not in claimed]
            if len(like) == 1:
                claimed.add(like[0])
                row.update(match="changed", to=like[0],
                           words=f"{the(name)}'s serial differs: it will be set to the one plugged in")
            else:
                row.update(match="missing", words=NOT_FOUND)
        else:   # a port by its name (/dev/ttyAMA0, /dev/serial0): there or not
            row.update(match="same", words="Found") if Path(serial).exists() else row.update(match="missing", words=NOT_FOUND)
        out.append(row)
    return out


# ── scan, plan, apply ────────────────────────────────────────────────────────

def load_bring() -> dict:
    try:
        d = json.loads(BRING_CACHE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_bring(d: dict) -> None:
    BRING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRING_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.replace(tmp, BRING_CACHE)


def usb_partitions() -> list[dict]:
    """Partitions on USB disks that could hold an old card's setup (ext4, or FAT for a stick). A USB disk this
    system runs from (a Pi booting from a USB SSD) is never one of them."""
    p = run(["lsblk", "-J", "-o", "NAME,TRAN,TYPE,FSTYPE,LABEL,MOUNTPOINT"], check=False)
    try:
        disks = json.loads(p.stdout or "{}").get("blockdevices") or []
    except ValueError:
        return []
    out = []
    for disk in disks:
        if (disk.get("tran") or "").lower() != "usb":
            continue
        parts = disk.get("children") or [disk]
        mounts = [c.get("mountpoint") or "" for c in parts]
        if any(m and not m.startswith((str(BRING_MOUNTS), "/media/", "/mnt/")) for m in mounts):
            continue
        for c in parts:
            if c.get("fstype") in ("ext4", "vfat") and BRING_DEV.fullmatch(c.get("name") or ""):
                out.append({"dev": c["name"], "fstype": c["fstype"], "label": c.get("label") or "",
                            "mountpoint": c.get("mountpoint") or None})
    return out


@contextlib.contextmanager
def mounted(part: dict):
    """A card's partition, read-only, for as long as it's read: ext4 without replaying its journal (noload), so
    not one byte on the card changes. Already mounted by someone else: read where it is, and left so."""
    mine = not part.get("mountpoint") or part["mountpoint"].startswith(str(BRING_MOUNTS))
    mp = Path(part["mountpoint"]) if part.get("mountpoint") else BRING_MOUNTS / part["dev"]
    if not part.get("mountpoint"):
        sudo("mkdir", "-p", str(mp))
        opts = ["-t", "ext4", "-o", "ro,noload"] if part["fstype"] == "ext4" else ["-t", "vfat", "-o", "ro"]
        sudo("mount", *opts, f"/dev/{part['dev']}", str(mp), timeout=60)
    try:
        yield mp
    finally:
        if mine:
            sudo("umount", str(mp), check=False, timeout=60)


def card_folders(root: Path) -> list[Path]:
    """printer_data folders on a card: home/<user>/<any>_data with config/printer.cfg, or one at its top (a
    stick, or Elyir Bench's own data partition)."""
    out = []
    for d in sorted(root.glob("home/*/*")) + sorted(root.glob("*")) + [root]:
        try:
            if d.is_dir() and not d.is_symlink() and (d / "config" / "printer.cfg").is_file():
                out.append(d)
        except OSError:
            continue
    return out


def source_name(src: BringSource, facts_: dict) -> str:
    """The setup's own name for itself: Elyir Bench's, then Mainsail's, then its hostname."""
    own = read(src.config / "elyir-bench.conf") if isinstance(src, FolderSource) else ""
    for text, section in ((src.texts().get("moonraker.conf", ""), "printer_intent"), (own, "elyir-bench")):
        m = re.search(rf"^\[{section}\][^\[]*?^printer_name:\s*(\S.*)$", text, re.M)
        if m:
            return m.group(1).strip()
    return facts_.get("name") or src.name_hint() or "Printer"


def describe(src: BringSource, sid: str, detail: str) -> dict:
    """One source, as the app lists it."""
    files = src.config_files()
    gcodes = src.gcode_files()
    f = src.facts()
    boards = cfg_boards(src.texts())
    when = max((p.stat().st_mtime for p in files.values()), default=None)
    return {"id": sid, "kind": src.kind, "name": source_name(src, f), "detail": detail,
            "when": int(when) if when else None, "files": len(files), "gcodes": len(gcodes),
            "history": f["history"], "boards": board_names(boards)}


def local_klipper_version() -> str | None:
    """This card's Klipper, as git names it (what Klipper itself reports as its software_version)."""
    if not (HOME / "klipper" / ".git").exists():
        return None
    got = run(["git", "-C", str(HOME / "klipper"), "describe", "--always", "--tags", "--long", "--dirty"], check=False)
    return got.stdout.strip() or None


def plan_of(src: BringSource, sid: str, here: dict) -> dict:
    """What would come over from one source, and whether its boards are the ones plugged in here."""
    f = src.facts()
    keys, texts = f["keys"], src.texts()
    gcodes = src.gcode_files()
    spools = (("elyir-bench", "spool") in keys or ("moonraker", "spoolman") in keys or any(ns == "spoolman" for ns, _ in keys)
              or bool(re.search(r"(?m)^\[spoolman\]", texts.get("moonraker.conf", ""))))
    notes = []
    if isinstance(src, FolderSource) and src.older_database():
        notes.append("Its history and Mainsail settings were kept by an older Moonraker, so they stay on the old card.")
    elif src.kind == "printer" and f["history"] is None:
        notes.append("Its history stays there: only a printer with Elyir Bench can send it.")
    theirs = src.klipper_version() if isinstance(src, PrinterSource) else None
    ours = local_klipper_version()
    if theirs and ours and theirs != ours:
        # a config written for another Klipper can name options this one doesn't know (Studio's eddy probe on
        # desk.local, 6 October 2026: descend_z, renamed from z_offset in a newer Klipper)
        notes.append(f"{source_name(src, f) or 'It'} runs Klipper {theirs}; this card has {ours}. "
                     "If its config needs the other one, Klipper will say so after.")
    needs = cfg_needs(texts)
    if needs:
        names = ", ".join(f"[{n}]" for n in needs)
        notes.append(f"{names} {'needs an add-on' if len(needs) == 1 else 'need add-ons'} this card doesn't have yet. "
                     "Klipper will say so after.")
    return {"id": sid, "config": len(src.config_files()), "history": f["history"], "spools": spools,
            "mainsail": any(ns == "mainsail" for ns, _ in keys),
            "gcodes": {"count": len(gcodes), "bytes": sum(gcodes.values())},
            "boards": [{k: v for k, v in b.items() if k not in ("section", "file")} for b in match_boards(cfg_boards(texts), here)],
            "notes": notes}


@contextlib.contextmanager
def open_source(entry: dict, facts: dict):
    w = entry["where"]
    if entry["kind"] == "card":
        part = next((p for p in usb_partitions() if p["dev"] == w["dev"]), None)
        if part is None:
            raise StepFailed("The old card isn't in the reader any more. Plug it in again.")
        with mounted(part) as mp:
            pdata = mp / w["dir"] if w["dir"] else mp
            if not (pdata / "config" / "printer.cfg").is_file():
                raise StepFailed("That card has no printer config on it any more.")
            src = FolderSource(mp, pdata)
            try:
                yield src
            finally:
                src.close()
        return
    if entry["kind"] == "cloud":
        raise StepFailed("That backup comes back once the house's owner allows it.")
    if entry["kind"] == "file":
        cdir = config_dir(facts)
        path = cdir / BRING_FOLDER / w["path"] if cdir else None
        if not path or not path.is_file():
            raise StepFailed("That backup file isn't there any more.")
        src = ArchiveSource(path)
    else:
        src = PrinterSource(w["url"], w.get("name"))
    try:
        yield src
    finally:
        src.close()


def printers_from(records: list[tuple[str, int, object]]) -> list[dict]:
    """Elyir Bench printers on the Wi-Fi (installer Announce): name, host, address and their Moonraker's port."""
    want = PRINTER_MDNS + ".local"
    ptr = [d for n, t, d in records if t == 12 and n.lower() == want]
    srv = {n: d for n, t, d in records if t == 33}
    txt = {n: d for n, t, d in records if t == 16}
    a = {n.lower(): d for n, t, d in records if t == 1}
    out = {}
    for inst in ptr:
        if inst not in srv:
            continue
        host = srv[inst][0].rstrip(".")
        t = txt.get(inst, {})
        port = int(t["moonraker"]) if str(t.get("moonraker", "")).isdigit() else MOONRAKER_PORT
        out[inst] = {"name": t.get("name") or inst.split(".")[0], "host": host, "ip": a.get(host.lower()), "port": port}
    return list(out.values())


def parse_address(address: str) -> tuple[str, int]:
    """studio.local, 192.168.1.20, 192.168.1.20:7125 or http://studio.local:7125/ -> (host, port)."""
    a = re.sub(r"^\w+://", "", address.strip()).split("/", 1)[0]
    host, _, port = a.rpartition(":") if a.count(":") == 1 else (a, "", "")
    if not host or not re.fullmatch(r"[A-Za-z0-9.\-]+", host):
        raise StepFailed(f"{address!r} isn't an address: try its name, like studio.local, or its number")
    return host, int(port) if port.isdigit() else MOONRAKER_PORT


def printer_entry(host: str, port: int, name: str | None, detail: str, ip: str | None = None) -> dict:
    sid = f"printer-{bring_slug(host)}" + (f"-{port}" if port != MOONRAKER_PORT else "")
    return {"id": sid, "kind": "printer", "detail": detail,
            "where": {"url": f"http://{ip or resolve4(host) or host}:{port}", "host": host, "name": name}}


def bring_scan(facts: dict, s: dict) -> dict:
    """Every source it can see now, each read once and described; cached for plan and apply."""
    cache = load_bring()
    entries: list[dict] = []
    for part in usb_partitions():
        try:
            with mounted(part) as mp:
                folders = card_folders(mp)
                for d in folders:
                    rel = str(d.relative_to(mp)) if d != mp else ""
                    sid = f"card-{part['dev']}" + (f"-{bring_slug(d.name)}" if len(folders) > 1 else "")
                    e = {"id": sid, "kind": "card", "detail": "In a USB reader", "where": {"dev": part["dev"], "dir": rel}}
                    src = FolderSource(mp, d)
                    try:
                        e["source"] = describe(src, sid, e["detail"])
                    finally:
                        src.close()
                    entries.append(e)
        except Exception as e:   # one card that can't be read never hides the rest
            print(f"bring: {part['dev']} couldn't be read: {e}", file=sys.stderr)
    me = {facts["host"].split(".")[0].lower(), s.get("printer_name", "").lower()}
    printers = [p for p in printers_from(mdns_ask(PRINTER_MDNS + ".local"))
                if p["host"].split(".")[0].lower() not in me and p["name"].lower() not in me]
    seen = set()
    for p in printers:
        e = printer_entry(p["host"], p["port"], p["name"], "Elyir Bench, on your Wi-Fi", p["ip"])
        seen.add(e["id"])
        entries.append(e)
    for addr in cache.get("addresses") or []:
        try:
            host, port = parse_address(addr)
        except StepFailed:
            continue
        e = printer_entry(host, port, None, f"At {addr}")
        if e["id"] not in seen:
            entries.append(e)
    cdir = config_dir(facts)
    folder = cdir / BRING_FOLDER if cdir else None
    if folder and folder.is_dir():
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.name.endswith(BRING_ARCHIVES):
                entries.append({"id": f"file-{bring_slug(f.name)}", "kind": "file", "detail": "A backup file",
                                "where": {"path": f.name}})
    entries += cloud_entries(s)
    out = []
    for e in entries:
        if "source" not in e:
            if e["kind"] == "card":    # read while it was mounted, or it couldn't be
                continue
            try:
                with open_source(e, facts) as src:
                    e["source"] = describe(src, e["id"], e["detail"])
            except Exception as ex:
                print(f"bring: {e['id']} couldn't be read: {ex}", file=sys.stderr)
                continue
        out.append(e)
    here = bring_here(facts)
    save_bring({**cache, "sources": [{k: v for k, v in e.items() if not k.startswith("_")} for e in out],
                "found": found_words(here), "boards": printer_boards(here), "when": int(time.time())})
    return {"sources": [e["source"] for e in out], "found": found_words(here), "boards": printer_boards(here)}


def bring_entry(sid: str) -> dict:
    e = next((e for e in load_bring().get("sources") or [] if e["id"] == sid), None)
    if e is None:
        raise StepFailed("That isn't one it found. Look again first.")
    return e


def bring_plan(facts: dict, sid: str) -> dict:
    e = bring_entry(sid)
    with open_source(e, facts) as src:
        return plan_of(src, sid, bring_here(facts))


def bring_address(facts: dict, address: str) -> dict:
    """A printer typed in by address (any Moonraker): read it, remember it for the next scans, and plan it."""
    host, port = parse_address(address)
    e = printer_entry(host, port, None, f"At {address.strip()}")
    try:
        http_json(f"{e['where']['url']}/server/info", timeout=5)
    except Exception:
        raise StepFailed(f"Nothing answers at {address.strip()}. Is that printer on, and on this Wi-Fi?")
    with open_source(e, facts) as src:
        e["source"] = describe(src, e["id"], e["detail"])
        plan = plan_of(src, e["id"], bring_here(facts))
    cache = load_bring()
    addresses = [a for a in cache.get("addresses") or [] if a != address.strip()] + [address.strip()]
    sources = [x for x in cache.get("sources") or [] if x["id"] != e["id"]] + [e]
    save_bring({**cache, "addresses": addresses, "sources": sources})
    return {"source": e["source"], "plan": plan}


def klipper_info(url: str) -> tuple[str | None, str]:
    try:
        info = http_json(f"{url}/printer/info", timeout=3)["result"]
        return info.get("state"), (info.get("state_message") or "").strip()
    except Exception:
        return None, ""     # Moonraker between two connections to Klipper


def klipper_settled(url: str, before: str = "", wait: int = 120) -> dict:
    """Klipper's state once it has started again, in words: ready, or error with what Klipper said. The error from
    before the restart (a fresh card's missing printer.cfg) still shows for a moment, and is never the answer."""
    started, restarted, message = time.time(), False, ""
    while time.time() < started + wait:
        time.sleep(1)
        state, message = klipper_info(url)
        if state in (None, "startup"):
            restarted = True
        t = time.time() - started
        if state == "ready" and (restarted or t > 5):
            return {"klipper": "ready", "message": "Klipper started with it."}
        if state in ("error", "shutdown") and (restarted or (message != before and t > 5) or t > 20):
            said = [ln for ln in message.splitlines() if ln.strip() and not ln.startswith(("Once the underlying",
                    "command to reload", "Printer is halted"))]
            return {"klipper": "error", "message": " ".join(said[:3]) or "Klipper didn't start with it."}
    return {"klipper": "error", "message": f"Klipper is still starting after {wait} s. {message}".strip()}


def moonraker_back(url: str, wait: int = 90) -> None:
    time.sleep(2)   # it restarts itself a moment after answering
    for _ in range(wait):
        try:
            if http_json(f"{url}/server/info", timeout=2)["result"]:
                return
        except Exception:
            pass
        time.sleep(1)
    raise StepFailed(f"Moonraker didn't come back within {wait} s")


def bring_apply(facts: dict, s: dict, sid: str, gcodes: bool, as_json: bool) -> dict:
    """Bring one source over. The config folder that was here is kept as config-before-bring-<date>/ (even empty)
    and put back if anything fails; this printer's elyir-bench.conf stays; a board's serial changes only as the plan
    says; the database is restored through Moonraker; gcodes only when asked; then Klipper restarts, and its state
    is the answer."""
    busy = printing_now(facts)
    if busy:
        raise StepFailed(f"Printing: {busy}. Nothing was changed; bring it over when the print is done.")
    pdata = Path(facts["printer_data"]) if facts.get("printer_data") else None
    if not pdata:
        raise StepFailed("This printer has no printer_data folder to bring it into.")
    url = facts["moonraker"]["url"]
    e = bring_entry(sid)
    config, stage = pdata / "config", pdata / ".elyir-bench-bring-new"
    date = _dt.date.today().isoformat()
    kept = pdata / f"{BRING_KEPT}{date}"
    n = 2
    while kept.exists():
        kept, n = pdata / f"{BRING_KEPT}{date}-{n}", n + 1
    steps = 5 + (1 if gcodes else 0)
    done = [0]

    def step(words: str) -> None:
        bring_emit(as_json, {"progress": {"step": words, "done": done[0], "of": steps}})
        done[0] += 1

    undo: list[tuple[str, callable]] = []
    try:
        with open_source(e, facts) as src:
            step(f"Reading {source_name(src, src.facts())}'s setup")
            shutil.rmtree(stage, ignore_errors=True)
            stage.mkdir()
            for rel, p in src.config_files(True).items():
                (stage / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, stage / rel)
            if not (stage / "printer.cfg").is_file():
                raise StepFailed("It has no printer.cfg to bring")
            db, items = src.database(), (src.items() if src.kind == "printer" else None)
            backups, target = pdata / "backup" / "database", None
            if db:
                backups.mkdir(parents=True, exist_ok=True)
                target = backups / f"elyir-bench-bring-{date}.db"
                shutil.copy2(db, target)
                undo.append(("its database", lambda: target.unlink(missing_ok=True)))
            boards = match_boards(cfg_boards(src.texts()), bring_here(facts))
            if gcodes:   # first: a backup file moves away with the config folder
                step("Copying your files")
                folder = pdata / "gcodes"
                folder.mkdir(exist_ok=True)
                added: list[Path] = []
                undo.append(("gcodes", lambda: [p.unlink() for p in added if p.exists()]))
                for rel in sorted(src.gcode_files()):
                    dest = folder / rel
                    if dest.exists():   # what's here already stays as it is
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    src.copy_gcode(rel, dest)
                    added.append(dest)

            step("Keeping your current config")
            config.mkdir(exist_ok=True)
            config.rename(kept)
            undo.append(("config", lambda: (shutil.rmtree(config, ignore_errors=True), kept.rename(config))))
            stage.rename(config)
            for name in BRING_KEEP_HERE:
                if (kept / name).is_file():
                    shutil.copy2(kept / name, config / name)
            if (kept / "elyir-bench-slicer").is_dir() and not (config / "elyir-bench-slicer").exists():
                shutil.copytree(kept / "elyir-bench-slicer", config / "elyir-bench-slicer", symlinks=True)
            brought = read(config / "moonraker.conf") if (config / "moonraker.conf").is_file() else None
            (config / "moonraker.conf").write_text(
                render_brought_moonraker(brought, read(kept / "moonraker.conf"), render_intent_section(facts, s)))
            if any(OUR_INCLUDE.match(ln) for ln in read(config / "printer.cfg").splitlines()):
                save_settings(facts, {**s, "start_macro": "on"})   # its start macro comes with it, and stays

            step("Matching the boards")
            for b in boards:
                if b["match"] == "changed":
                    f = config / b["file"]
                    f.write_text(render_serial(read(f), b["section"], b["to"]))

        step("Bringing history and settings")
        if target:
            before = f"elyir-bench-before-bring-{date}.db"
            http_post(f"{url}/server/database/backup", {"filename": before}, timeout=120)
            try:
                http_post(f"{url}/server/database/restore", {"filename": target.name}, timeout=120)
            except Exception as ex:
                raise StepFailed(f"Moonraker didn't take its history: {http_error(ex)}")
            undo.append(("database", lambda: (moonraker_back(url, 30),
                                              http_post(f"{url}/server/database/restore", {"filename": before}))))
            moonraker_back(url)
            target.unlink(missing_ok=True)
        else:
            for ns, value in (items or {}).items():
                for key, v in (value or {}).items() if isinstance(value, dict) else ():
                    try:
                        http_post(f"{url}/server/database/item", {"namespace": ns, "key": key, "value": v})
                    except Exception as ex:   # a namespace Moonraker keeps to itself here: left as it is
                        print(f"bring: {ns}.{key} not written: {http_error(ex)}", file=sys.stderr)
            http_post(f"{url}/server/restart")   # reads the brought moonraker.conf, in its own process
            moonraker_back(url)
    except Exception as ex:
        for what, fn in reversed(undo):
            try:
                fn()
            except Exception as ue:
                print(f"bring: putting back {what} failed: {ue}", file=sys.stderr)
        shutil.rmtree(stage, ignore_errors=True)
        if any(what == "config" for what, _ in undo):
            try:
                http_post(f"{url}/server/restart")   # reads moonraker.conf as it was again
            except Exception:
                pass
        why = (str(ex) if isinstance(ex, StepFailed) else f"{ex.__class__.__name__}: {ex}").rstrip(".")
        moved = any(what == "config" for what, _ in undo)
        raise StepFailed(f"{why}. Nothing was changed" + (": the config that was here is back." if moved else "."))

    step("Starting Klipper")
    before = klipper_info(url)[1]
    try:
        http_post(f"{url}/machine/services/restart?service=klipper", timeout=60)
    except Exception:
        sudo("systemctl", "restart", "klipper", check=False)
    return klipper_settled(url, before)


# ── printer or Bench Box (docs/bring-it-over.md, "Printer or Bench Box"; design/role/, B) ────────────────

ROLE_STEPS = {"controller": ["The Bench app", "Its screen", "Klipper and Moonraker off"],
              "printer": ["Klipper and Moonraker on", "The printer app", "Its screen"]}
ROLE_OFF_UNIT = "elyir-bench-role-off"     # the transient unit that stops Klipper and Moonraker, outside Moonraker


def role_off_cmd() -> list[str]:
    """Klipper and Moonraker off, from a transient unit: the run that asks is Moonraker's child, and dies with it."""
    return [sudo_bin("systemd-run"), "--no-block", "--collect", f"--unit={ROLE_OFF_UNIT}",
            sudo_bin("systemctl"), "disable", "--now", "klipper", "moonraker"]


def role_apply() -> bool:
    """apply, as a separate run: its report goes to stderr (the role run's own lines are JSON on stdout)."""
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "apply"], stdin=subprocess.DEVNULL,
                       stdout=sys.stderr, stderr=sys.stderr, timeout=3600)
    return p.returncode == 0


def role_screen(s: dict) -> None:
    """The panel opens localhost, which is the printer app or the Bench app by the role: a restart shows the other."""
    if s.get("panel") == "elyir-bench" and is_enabled(KIOSK_UNIT):
        sudo("systemctl", "restart", KIOSK_UNIT, check=False)


def role_main(args, facts: dict, s: dict) -> int:
    as_json, want = args.json, args.to
    steps = ROLE_STEPS[want]
    if as_json:   # who's running, for the component to follow (it goes away with Moonraker at the end)
        bring_emit(True, {"started": "role", "pid": os.getpid()})
    url = f"http://{facts['host'].split('.')[0]}.local:{s['port']}/"
    try:
        if role(facts, s) == want:
            bring_emit(as_json, {"result": {"role": want, "url": url, "already": True}})
            return 0
        if want == "controller":
            if facts["print_state"] in ("printing", "paused"):
                raise StepFailed(f"the printer is {facts['print_state']}: make it a Bench Box when it's done")
            was = s.get("role", "auto")
            bring_emit(as_json, {"progress": {"step": steps[0], "done": 0, "of": 3}})
            s["role"] = "controller"
            save_settings(facts, s)
            if not role_apply():
                s["role"] = was                      # put back: still a printer card
                save_settings(facts, s)
                role_apply()
                raise StepFailed("the Bench app didn't come up, so this is still a printer. The installer's log says why.")
            sudo("rm", "-f", str(PRINTER_AVAHI), check=False)     # it isn't a printer for a Bench Box to find any more
            bring_emit(as_json, {"progress": {"step": steps[1], "done": 1, "of": 3}})
            role_screen(s)
            bring_emit(as_json, {"progress": {"step": steps[2], "done": 2, "of": 3}})
            bring_emit(as_json, {"result": {"role": "controller", "url": url}})   # the last line anyone can read
            run(["sudo", "-n", *role_off_cmd()])
            return 0
        # the way back: Klipper and Moonraker first, then the printer's own app and screen
        bring_emit(as_json, {"progress": {"step": steps[0], "done": 0, "of": 3}})
        sudo("systemctl", "enable", "--now", "klipper", "moonraker")
        bring_emit(as_json, {"progress": {"step": steps[1], "done": 1, "of": 3}})
        s["role"] = "printer"
        save_settings(facts, s)
        if not role_apply():
            raise StepFailed("the printer app didn't come up; run `elyir-bench apply` to see why")
        bring_emit(as_json, {"progress": {"step": steps[2], "done": 2, "of": 3}})
        role_screen(s)
        bring_emit(as_json, {"result": {"role": "printer", "url": url}})
        return 0
    except StepFailed as e:
        bring_emit(as_json, {"failed": str(e)})
        return 1
    except Exception as e:   # always a last line the component can read
        bring_emit(as_json, {"failed": f"{e.__class__.__name__}: {e}"})
        return 1


def bring_main(args, facts: dict, s: dict) -> int:
    as_json = args.json
    if as_json:   # who's running, for the component to follow across a Moonraker restart
        bring_emit(True, {"started": args.what, "pid": os.getpid()})
    try:
        if args.what == "scan":
            out = bring_scan(facts, s)
        elif args.what == "plan":
            out = {"plan": bring_plan(facts, args.id)}
        elif args.what == "address":
            out = bring_address(facts, args.address)
        elif args.what == "cloud-ask":
            out = bring_cloud_ask(args.id)
        elif args.what == "cloud-check":
            out = bring_cloud_check(facts, s)
        elif args.what == "cloud-email":
            out = bring_cloud_email()
        elif args.what == "cloud-code":
            out = bring_cloud_code(facts, s, args.code)
        else:
            out = {"result": bring_apply(facts, s, args.id, args.gcodes, as_json)}
    except StepFailed as e:
        bring_emit(as_json, {"failed": str(e)})
        return 1
    except Exception as e:   # always a last line the component can read
        bring_emit(as_json, {"failed": f"{e.__class__.__name__}: {e}"})
        return 1
    if as_json:
        bring_emit(True, out)
    else:
        print(json.dumps(out, indent=2))
    return 0


# ── Bench Cloud (docs/cloud.md, design/cloud/ C) ─────────────────────────────────────────────────────────────
# The house's paid service: a backup every night (started by the intent component, so no unit or sudo rule is
# needed), and a new card bringing one back once the house's owner allows it. Nothing here changes what the printer
# does: it prints the same with the cloud off, unreachable or gone.

CLOUD_STATE = DOOR_STATE / "cloud.json"        # this printer in its house: the API, its device id and its token
CLOUD_LAST = DOOR_STATE / "cloud-last.json"    # the last backup: when and how big, or why it didn't happen
CLOUD_API = "https://cloud.elyir.dev"
CLOUD_DB = f"printer_data/database/{DB_FILE}"
# the door's own files, so its name from away and its paired phones come back with the backup
CLOUD_DOOR_FILES = ("relay.json", "door/phones.json", "door/vapid.pem")
PROC_ROUTE, PROC_ARP = Path("/proc/net/route"), Path("/proc/net/arp")


def cloud_api(s: dict) -> str:
    return (s.get("cloud_api") or CLOUD_API).rstrip("/")


def home_mark() -> str | None:
    """This house's network, as the cloud tells houses apart when they share a public address (carrier-grade NAT): a
    hash of the router's hardware address, which a printer and a new card on the same Wi-Fi both see."""
    try:
        gw = next(bytes.fromhex(f[2])[::-1] for f in (l.split() for l in PROC_ROUTE.read_text().splitlines()[1:])
                  if len(f) > 2 and f[1] == "00000000" and f[2] != "00000000")
        ip = ".".join(str(b) for b in gw)
        mac = next(f[3] for f in (l.split() for l in PROC_ARP.read_text().splitlines()[1:])
                   if len(f) > 3 and f[0] == ip and f[3] != "00:00:00:00:00:00")
    except (OSError, StopIteration, ValueError):
        return None
    return hashlib.sha256(f"elyir-bench-home:{mac.lower()}".encode()).hexdigest()[:32]


def cloud_call(method: str, url: str, body: dict | None = None, token: str | None = None, raw: bytes | None = None,
               timeout: float = 30):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/gzip" if raw is not None else "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    mark = home_mark()
    if mark:
        req.add_header("X-Bench-Home", mark)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return json.loads(payload) if r.headers.get_content_type() == "application/json" else payload
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read()).get("error")
        except Exception:
            why = None
        raise StepFailed(why or f"Bench Cloud answered {e.code}.")
    except (urllib.error.URLError, OSError):
        raise StepFailed("Bench Cloud can't be reached right now.")


def load_cloud() -> dict:
    try:
        d = json.loads(CLOUD_STATE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_private(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(text.encode() if isinstance(text, str) else text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cloud_database(facts: dict) -> bytes | None:
    """This printer's Moonraker database as the intent component exports it for Bring it over: its logins and API key
    taken out. None on a card without the component yet."""
    import base64
    try:
        got = http_json(f"{facts['moonraker']['url']}/printer/intent/bring/export", timeout=60)["result"]
        return base64.b64decode(got["database"])
    except Exception as e:
        print(f"cloud: the database wasn't exported: {e}", file=sys.stderr)
        return None


def cloud_archive(facts: dict) -> bytes:
    """A backup in the shape Bring it over reads from a file: printer_data/config and printer_data/database, plus the
    door's files under elyir-bench-state/."""
    import io
    cdir = config_dir(facts)
    if not cdir or not (cdir / "printer.cfg").is_file():
        raise StepFailed("There's no printer config to back up yet.")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for rel, path in sorted(walk_files(cdir, cdir, True, bring_skip).items()):
            t.add(str(path), arcname=f"printer_data/config/{rel}", recursive=False)
        db = cloud_database(facts)
        if db:
            info = tarfile.TarInfo(CLOUD_DB)
            info.size, info.mtime = len(db), int(time.time())
            t.addfile(info, io.BytesIO(db))
        for rel in CLOUD_DOOR_FILES:
            p = DOOR_STATE / rel
            if p.is_file():
                t.add(str(p), arcname=f"elyir-bench-state/{rel}", recursive=False)
    return buf.getvalue()


def cloud_join(s: dict, join_token: str, api: str | None = None) -> dict:
    api = (api or cloud_api(s)).rstrip("/")
    got = cloud_call("POST", f"{api}/v1/devices", {"join_token": join_token})
    me = {"api": api, "device": got["device"], "token": got["device_token"], "house": got["house"], "name": got["name"],
          "joined": int(time.time())}
    save_private(CLOUD_STATE, json.dumps(me, indent=1))
    return {**{k: v for k, v in me.items() if k != "token"}, "carry": cloud_carry(s)}


def cloud_carry(s: dict, claim: dict | None = None) -> dict:
    """The house's Bench Cloud plan carries this printer's name from away (design/one-cloud/): a ticket from the cloud,
    taken to the relay with the printer's own secret. Asked on joining and with every nightly backup; a plan that stops
    simply runs out about a month later. Nothing here ever fails a backup."""
    me, r = load_cloud(), claim or load_relay()
    if not me.get("token") or s.get("remote") != "relay" or not (r.get("name") and r.get("secret")):
        return {"skipped": True}
    try:
        t = cloud_call("POST", f"{me['api']}/v1/carry-ticket", {"name": r["name"]}, token=me["token"])
    except StepFailed as e:
        return {"why": str(e)}
    api = s.get("relay_api") or DEFAULT_RELAY_API
    was, before = relay_call(api, "GET", f"/houses/{r['name']}", secret=r["secret"])
    code, out = relay_call(api, "POST", f"/houses/{r['name']}/carry", {"ticket": t["ticket"]}, secret=r["secret"])
    if code != 200:
        return {"why": invite_refusal(out) if code == 403 else "the relay doesn't know this printer's name any more"
                if code == 404 else "no answer from the relay" if code == 0 else f"the relay answered {code}"}
    if claim is None and out.get("carried") and not (was == 200 and before.get("carried")):
        # carried just now: Caddy and frpc start over rather than waiting out their back-off (as with an invite)
        for unit in ("elyir-bench-caddy.service", "elyir-bench-frpc.service"):
            if is_active(unit):
                sudo("systemctl", "restart", unit, check=False)
    return {"until": out.get("entitled_until")}


# ── a report or a message to Elyir (design/report/, B) ─────────────────────────────────────────────────────────────────

REPORT_KINDS = ("wrong", "idea", "other", "install")
REPORT_LOG_BYTES = 1_500_000        # the end of each log: a day of an ordinary printer's, less of a chatty one's
REPORT_REMOVED = "«removed»"
INSTALL_LOG = DOOR_STATE / "install.log"


class _Tee:
    """What apply prints, on the terminal and in install.log too: a report of a failed install carries exactly what
    the person saw."""
    def __init__(self, out, log):
        self.out, self.log = out, log

    def write(self, text):
        self.log.write(text)
        self.log.flush()
        return self.out.write(text)

    def flush(self):
        self.out.flush()

    def __getattr__(self, name):
        return getattr(self.out, name)


def keep_install_log() -> None:
    try:
        DOOR_STATE.mkdir(parents=True, exist_ok=True)
        sys.stdout = _Tee(sys.stdout, open(INSTALL_LOG, "w", encoding="utf-8"))
    except OSError:
        pass


def report_secrets() -> list[str]:
    """Values that must never leave the printer, wherever they turn up: relay and cloud secrets, door tokens."""
    found = []
    for f in (RELAY_STATE, RELAY_NEXT, RELAY_FORMER, DOOR_STATE / "cloud.json"):
        d = load_claim(f)
        found += [str(d[k]) for k in ("secret", "token") if d.get(k) and len(str(d[k])) >= 8]
    return found


def scrub_report(text: str, known: list[str] | None = None) -> str:
    """Passwords, keys, tokens and Wi-Fi details out of a log or a config file, on the printer, before anything is sent."""
    for value in known if known is not None else report_secrets():
        text = text.replace(value, REPORT_REMOVED)
    text = re.sub(r"(?im)^(\s*[#;]?\s*[\w.-]*(?:password|passwd|psk|secret|token|api_?key|auth|credential)[\w.-]*\s*[:=]\s*).+$",
                  rf"\1{REPORT_REMOVED}", text)
    text = re.sub(r"(?i)(bearer\s+)[\w.~+/=-]{8,}", rf"\1{REPORT_REMOVED}", text)
    text = re.sub(r"(?i)((?:access_token|token|secret|key|psk|password)=)[^&\s\"']+", rf"\1{REPORT_REMOVED}", text)
    text = re.sub(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}", REPORT_REMOVED, text)          # JWTs
    text = re.sub(r"(?i)(elyir-bench-token\.)[\w-]+", rf"\1{REPORT_REMOVED}", text)        # the websocket subprotocol
    return text


def tail_text(path: Path | str, most: int = REPORT_LOG_BYTES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - most))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def gather_report(facts: dict, s: dict, kind: str, context: dict | None = None, details: bool = True) -> tuple[dict, bytes | None]:
    """What a report says (meta, small, shown to the person) and, with details, the bundle: logs, config, the install
    check, as a .tar.gz, every text scrubbed."""
    release = os.path.basename(os.path.realpath(CURRENT)) if CURRENT.exists() else None
    printer = {"name": s.get("printer_name") or facts.get("host"), "release": release,
               "board": facts.get("model") or facts.get("arch"), "os": facts.get("os")}
    meta = {"kind": kind, "printer": {k: v for k, v in printer.items() if v}, "context": context or None}
    if not details:
        return meta, None
    known = report_secrets()
    files: dict[str, str] = {}
    pdata = Path(facts.get("printer_data") or "")
    for name in ("klippy.log", "moonraker.log", "crowsnest.log"):
        text = tail_text(pdata / "logs" / name) if facts.get("printer_data") else ""
        if text:
            files[f"logs/{name}"] = text
    journal = run(["journalctl", "--no-pager", "-o", "short-iso", "--since", "-1 day", "-u", "elyir-bench-*"], check=False).stdout
    if journal:
        files["logs/elyir-bench.journal"] = journal[-REPORT_LOG_BYTES:]
    if INSTALL_LOG.exists():
        files["logs/install.log"] = tail_text(INSTALL_LOG, 300_000)
    for name in ("elyir-bench.conf", "printer.cfg", "moonraker.conf"):
        text = read(pdata / "config" / name) if facts.get("printer_data") else ""
        if text:
            files[f"config/{name}"] = text
    try:
        files["state/intent.json"] = json.dumps(http_json(f"{facts['moonraker']['url']}/printer/intent")["result"], indent=1)
    except Exception:
        pass
    if kind in ("wrong", "install"):
        try:   # the minutes before: Moonraker keeps the last 20 of each heater
            files["state/temperatures.json"] = json.dumps(http_json(f"{facts['moonraker']['url']}/server/temperature_store")["result"])
        except Exception:
            pass
    try:
        lines = plan(Ctx(facts, dict(s)))
        files["state/install-check.txt"] = "\n".join(f"{st:<5} {name:<22} {why}" for st, name, why in lines)
    except Exception as e:
        files["state/install-check.txt"] = f"the check itself failed: {e}"
    files["report.json"] = json.dumps({**meta, "facts": {k: facts.get(k) for k in ("model", "os", "arch", "sudo", "print_state")}}, indent=1)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, text in sorted(files.items()):
            data = scrub_report(text, known).encode()
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(data), int(time.time())
            t.addfile(info, io.BytesIO(data))
    meta["files"] = sorted(files)
    return meta, buf.getvalue()


def send_report(s: dict, meta: dict, bundle: bytes | None) -> str:
    """To Bench Cloud, as a form: meta, and the bundle if there is one. The answer is the code to quote."""
    boundary = "elyir" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="meta"\r\nContent-Type: application/json\r\n\r\n'.encode()
             + json.dumps(meta).encode() + b"\r\n"]
    if bundle:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="bundle"; filename="report.tar.gz"\r\n'
                     f'Content-Type: application/gzip\r\n\r\n'.encode() + bundle + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{(s.get('cloud_api') or CLOUD_API).rstrip('/')}/v1/reports", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["code"]
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read()).get("error")
        except ValueError:
            why = None
        raise StepFailed(why or f"Bench Cloud answered {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise StepFailed(f"couldn't reach Elyir ({getattr(e, 'reason', e)})")


def cloud_backup(facts: dict, s: dict | None = None) -> dict:
    me = load_cloud()
    if not me.get("token"):
        return {"off": True}
    try:
        data = cloud_archive(facts)
        got = cloud_call("POST", f"{me['api']}/v1/backups", token=me["token"], raw=data, timeout=300)
        last = {"at": int(time.time()), "size": got["size"], "backup": got["backup"]}
    except StepFailed as e:
        last = {"at": int(time.time()), "why": str(e)}
    if s is not None:
        last["carry"] = cloud_carry(s)
    save_private(CLOUD_LAST, json.dumps(last))
    return last


def cloud_entries(s: dict) -> list[dict]:
    """Backups this card could bring back: the cloud lists those of printers last seen on this internet connection.
    Asked only on a card that isn't in a house yet; a cloud that can't be reached hides nothing else."""
    if load_cloud().get("token"):
        return []
    api = cloud_api(s)
    try:
        offers = cloud_call("GET", f"{api}/v1/restore/offers", timeout=6)["offers"]
    except (StepFailed, KeyError, TypeError) as e:
        print(f"bring: Bench Cloud wasn't asked: {e}", file=sys.stderr)
        return []
    out = []
    for o in offers:
        sid = f"cloud-{bring_slug(o['device'])}"
        detail = "Your Bench Cloud backup"
        out.append({"id": sid, "kind": "cloud", "detail": detail,
                    "where": {"api": api, "device": o["device"], "name": o["name"]},
                    "source": {"id": sid, "kind": "cloud", "name": o["name"], "detail": detail, "when": int(o["at"]),
                               "files": None, "gcodes": None, "history": None, "boards": [],
                               "owner_phone": o.get("owner_phone"), "owner_email": o.get("owner_email")}})
    return out


def cloud_view(a: dict, state: str, **more) -> dict:
    return {"cloud": {"id": a["id"], "name": a["name"], "state": state, "owner_phone": a.get("owner_phone"),
                      "owner_email": a.get("owner_email"), "emailed": a.get("emailed"), **more}}


def bring_cloud_ask(sid: str) -> dict:
    e = bring_entry(sid)
    if e["kind"] != "cloud":
        raise StepFailed("That isn't a Bench Cloud backup.")
    w = e["where"]
    got = cloud_call("POST", f"{w['api']}/v1/restore/asks", {"device": w["device"], "home": home_mark() or ""})
    a = {"id": sid, "api": w["api"], "device": w["device"], "name": w["name"], "ask": got["ask"], "secret": got["secret"],
         "owner_phone": e["source"].get("owner_phone"), "owner_email": e["source"].get("owner_email")}
    save_bring({**load_bring(), "cloud_ask": a})
    return cloud_view(a, "waiting")


def cloud_ask_now() -> dict:
    a = load_bring().get("cloud_ask")
    if not a:
        raise StepFailed("Nothing is being asked for. Pick the backup again.")
    return a


def bring_cloud_email() -> dict:
    a = cloud_ask_now()
    got = cloud_call("POST", f"{a['api']}/v1/restore/asks/{a['ask']}/email", {"secret": a["secret"]})
    a.update(pending=got["pending"], emailed=", ".join(got["sent_to"]))
    save_bring({**load_bring(), "cloud_ask": a})
    return cloud_view(a, "waiting")


def bring_cloud_code(facts: dict, s: dict, code: str) -> dict:
    a = cloud_ask_now()
    if not a.get("pending"):
        raise StepFailed("Send the code to the email first.")
    cloud_call("POST", f"{a['api']}/v1/restore/asks/{a['ask']}/code", {"secret": a["secret"], "pending": a["pending"],
                                                                        "code": code})
    return bring_cloud_check(facts, s)


def bring_cloud_check(facts: dict, s: dict) -> dict:
    a = cloud_ask_now()
    got = cloud_call("GET", f"{a['api']}/v1/restore/asks/{a['ask']}?secret={urllib.parse.quote(a['secret'])}")
    if got.get("device_token"):    # given once: kept before anything else can fail
        a["token"] = got["device_token"]
        save_bring({**load_bring(), "cloud_ask": a})
    if got["state"] == "waiting":
        return cloud_view(a, "waiting")
    if got["state"] != "allowed":
        cache = load_bring()
        cache.pop("cloud_ask", None)
        save_bring(cache)
        return cloud_view(a, got["state"])
    return cloud_bring_back(facts, s, a)


def cloud_bring_back(facts: dict, s: dict, a: dict) -> dict:
    """Allowed: the backup becomes a backup file here (then planned and brought over like any other), this card takes
    the printer's place in the house, and the door's files come back."""
    cdir = config_dir(facts)
    if not cdir:
        raise StepFailed("This card has no config folder to bring it into.")
    data = cloud_call("GET", f"{a['api']}/v1/restore/asks/{a['ask']}/backup?secret={urllib.parse.quote(a['secret'])}",
                      timeout=300)
    name = f"{bring_slug(a['name'])}-bench-cloud.tar.gz"
    (cdir / BRING_FOLDER).mkdir(parents=True, exist_ok=True)
    (cdir / BRING_FOLDER / name).write_bytes(data)
    if a.get("token"):
        save_private(CLOUD_STATE, json.dumps({"api": a["api"], "device": a["device"], "token": a["token"],
                                              "name": a["name"], "joined": int(time.time())}, indent=1))
    import io
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for rel in CLOUD_DOOR_FILES:
            try:
                f = t.extractfile(f"elyir-bench-state/{rel}")
            except KeyError:
                continue
            if f is not None and not (DOOR_STATE / rel).exists():
                save_private(DOOR_STATE / rel, f.read())
    cache = load_bring()
    cache.pop("cloud_ask", None)
    save_bring(cache)
    scan = bring_scan(facts, s)
    return {**scan, **cloud_view(a, "allowed", file=f"file-{bring_slug(name)}")}


def cloud_main(args, facts: dict, s: dict) -> int:
    try:
        if args.what == "join":
            out = cloud_join(s, args.token, args.api)
        elif args.what == "backup":
            out = cloud_backup(facts, s)
        elif args.what == "leave":
            CLOUD_STATE.unlink(missing_ok=True)
            out = {"off": True}
        else:
            me = load_cloud()
            try:
                last = json.loads(CLOUD_LAST.read_text())
            except (OSError, ValueError):
                last = None
            out = {"joined": bool(me.get("token")), **{k: v for k, v in me.items() if k != "token"}, "last": last}
    except StepFailed as e:
        print(json.dumps({"failed": str(e)}) if args.json else str(e), file=sys.stdout if args.json else sys.stderr)
        return 1
    print(json.dumps(out) if args.json else json.dumps(out, indent=2))
    return 0 if "why" not in out else 1


# ── health and orchestration ─────────────────────────────────────────────────

def restart_moonraker(facts: dict) -> None:
    sudo("systemctl", "restart", "moonraker")
    for _ in range(40):
        time.sleep(1)
        try:
            if http_json(f"{facts['moonraker']['url']}/server/info", timeout=2)["result"]:
                return
        except Exception:
            pass
    raise StepFailed("Moonraker didn't come back within 40s")


def health(c: Ctx, wait: int = 30) -> tuple[bool, str]:
    port = c.s["port"]
    deadline = time.time() + wait
    why = ""
    if role(c.facts, c.s) == "controller":
        while time.time() < deadline:
            if http_status(f"http://127.0.0.1:{port}/") != 200:
                why = f"the box's screen doesn't answer on :{port}"
            elif http_status(f"http://127.0.0.1:{port}/bench/printers") != 200:
                why = "the box's service isn't answering"
            elif http_status(f"http://127.0.0.1:{SLICER_PORT}/slice/options") != 200:
                why = "the slicer isn't answering"
            elif c.s["panel"] == "elyir-bench" and not is_active(KIOSK_UNIT):
                why = "the box's own screen isn't showing yet"
            else:
                return True, f"the bench on :{port}, slicing on :{SLICER_PORT}" + (", on its own screen" if c.s["panel"] == "elyir-bench" else "")
            time.sleep(2)
        return False, why
    while time.time() < deadline:
        if http_status(f"http://127.0.0.1:{port}/") != 200:
            why = f"app doesn't answer on :{port}"
        else:
            try:
                state = http_json(f"http://127.0.0.1:{port}/printer/intent")["result"]["state"]
            except Exception as e:
                state, why = None, f"intent layer not answering ({e.__class__.__name__})"
            if state in STATES and remote_on(c.s) and door_address(c.s) and http_status("http://127.0.0.1:8090/door/status") != 200:
                why = "the door isn't answering"
            elif state in STATES and slicer_on(c.s) and not orca_cant_run() and (slicer_home(c.facts) / "printer.json").is_file() \
                    and http_status(f"http://127.0.0.1:{port}/slice/options") != 200:
                why = "the slicer isn't answering"
            elif state in STATES:
                if c.s["panel"] == "klipperscreen":
                    if klipperscreen_steady():
                        return True, f"app up, printer {state}, KlipperScreen on the panel"
                    why = "KlipperScreen didn't start" if not is_active("KlipperScreen.service") else "KlipperScreen keeps restarting"
                elif c.s["panel"] != "elyir-bench":
                    return True, f"app up, printer {state}"
                elif is_active(KIOSK_UNIT) and run(["pgrep", "-c", "chromium"], check=False).stdout.strip() not in ("", "0"):
                    return True, f"app up, printer {state}, panel showing it"
                else:
                    why = "kiosk not drawing yet"
            elif state:
                why = f"intent layer returned unexpected state {state!r}"
        time.sleep(2)
    return False, why


def report(lines: list[tuple[str, str, str]], as_json: bool) -> None:
    if as_json:
        print(json.dumps([{"step": n, "status": s, "detail": d} for s, n, d in lines]))
        return
    marks = {"ok": "✓", "todo": "→", "fail": "✗", "done": "✓"}
    for status, name, detail in lines:
        print(f"  {marks.get(status, '?')} {name:<20} {detail}")


def steps_for(c: Ctx) -> list[Step]:
    """A controller has no printer or door of its own: only its screen and what it serves printers with."""
    r = role(c.facts, c.s)
    return [st for st in STEPS if r in st.roles]


def plan(c: Ctx) -> list[tuple[str, str, str]]:
    out = []
    for step in steps_for(c):
        try:
            ok, detail = step.check(c)
        except Exception as e:  # a check must never take the installer down
            ok, detail = False, f"check failed: {e}"
        out.append(("ok" if ok else "todo", step.name, detail))
    return out


def apply(c: Ctx, as_json: bool = False, steps: list[Step] | None = None) -> bool:
    lines = []
    try:
        for step in steps or steps_for(c):
            ok, detail = step.check(c)
            if ok:
                lines.append(("ok", step.name, detail))
                continue
            if not as_json:
                print(f"  … {step.name:<20} {detail}", flush=True)
            step.apply(c)
            try:
                _, after = step.check(c)
            except Exception:
                after = "applied"
            lines.append(("done", step.name, after if after != detail else "applied"))
        printer = role(c.facts, c.s) == "printer"      # a controller has no Moonraker or panel to restart
        if c.restart_moonraker and printer:
            restart_moonraker(c.facts)
        if c.restart_kiosk and printer and c.s["panel"] == "elyir-bench":
            sudo("systemctl", "restart", KIOSK_UNIT)
        ok, why = health(c)
        lines.append(("ok" if ok else "fail", "health", why))
        if not ok:
            raise StepFailed(f"health check failed: {why}")
    except Exception as e:  # anything that stops an apply gets the same clean-up
        lines.append(("fail", "apply", str(e) or e.__class__.__name__))
        if c.switched_from and (RELEASES / c.switched_from).exists():
            switch_current(RELEASES / c.switched_from)
            st = load_state()
            st.update({"version": c.switched_from, "previous": None, "last_failure": str(e)})
            save_state(st)
            try:
                if role(c.facts, c.s) == "printer":
                    restart_moonraker(c.facts)
                    if c.s["panel"] == "elyir-bench":
                        sudo("systemctl", "restart", KIOSK_UNIT, check=False)
                elif unit_exists(SLICER_UNIT):
                    sudo("systemctl", "restart", SLICER_UNIT, check=False)
            except StepFailed:
                pass
            lines.append(("done", "rolled back", f"back on {c.switched_from}"))
        elif c.undo:
            for what, fn in reversed(c.undo):
                try:
                    fn()
                    lines.append(("done", "undone", what))
                except Exception as ue:
                    lines.append(("fail", "undo", f"{what}: {ue}"))
            if c.restart_moonraker and role(c.facts, c.s) == "printer":
                try:
                    restart_moonraker(c.facts)
                except StepFailed as re_:
                    lines.append(("fail", "undo", str(re_)))
        report(lines, as_json)
        return False
    for n in c.notes:
        lines.append(("ok", "note", n))
    st = load_state()
    st.update({"last_apply": _dt.datetime.now().isoformat(timespec="seconds"), "last_failure": None})
    try:
        st["expectations"] = expectations(c.facts, c.s)   # the intent layer's What works sheet (works.board)
    except Exception:   # a guess about the board must never fail an apply that worked
        pass
    save_state(st)
    report(lines, as_json)
    return True


def strip_intent_section(text: str) -> str:
    """moonraker.conf without our [printer_intent] section (and the comment lines just above it)."""
    m = MoonrakerConf()._section(text)
    if not m:
        return text
    return (text[:m.start()].rstrip("\n") + "\n" + ("\n" + text[m.end():].lstrip("\n") if text[m.end():].strip() else ""))


def remove(c: Ctx) -> bool:
    """Take Elyir Bench off this printer and put things back (Care › Remove, design/getting-started):
    KlipperScreen on the screen, the Pi's own boot text, Mainsail and printer.cfg untouched. The steps that
    know how to turn themselves off do it; then what's left of ours is deleted. elyir-bench.conf and the
    slicer's presets stay in the config folder, so coming back picks up where it left off."""
    f = c.facts
    busy = printing_now(f)
    if busy:
        print(f"  ✗ Printing: {busy}. Nothing was changed; run this again when the print is done.")
        return False
    if run(["sudo", "-n", "true"], check=False).returncode != 0:
        # the narrow rule (sudo: elyir-bench) has no rm in it, so removing needs the password once
        if not sys.stdin.isatty():
            print("  ✗ Removing needs sudo with your password. Run this from a terminal on the printer.")
            return False
        print("  Removing Elyir Bench needs admin rights once.")
        if subprocess.run(["sudo", "-v"]).returncode != 0:
            print("  ✗ sudo password not accepted. Nothing was changed.")
            return False
    lines = []
    c.s = {**c.s, "panel": "klipperscreen" if f["klipperscreen"]["installed"] else "none", "boot_screen": "off", "network_wait": "on",
           "remote": "off", "slicer": "off", "slice_for_others": "off", "start_macro": "off"}
    for step in REMOVE_STEPS:
        c.undo = []
        try:
            ok, detail = step.check(c)
            if not ok:
                step.apply(c)
                detail = step.check(c)[1]
            lines.append(("done", step.name, detail))
        except Exception as e:
            # A step that fails halfway puts back what it changed, as in apply: a half-taken-out start macro left
            # Klipper unable to start on desk.local (5 October 2026). The rest of remove still runs.
            for _what, fn in reversed(c.undo):
                try:
                    fn()
                except Exception:
                    pass
            lines.append(("fail", step.name, f"{e}; put back as it was" if c.undo else str(e)))
    c.undo = []
    # A flashed card's first boot (docs/image.md) runs until ~/elyir-bench/state/firstboot-done exists, and that goes
    # below: left enabled, the next boot would try to install again. Its job is done for good; the card's grow step
    # keeps its own mark outside ~/elyir-bench and needs nothing. (Found on desk.local, 5 October 2026.)
    if unit_exists("elyir-bench-firstboot.service"):
        sudo("systemctl", "disable", "elyir-bench-firstboot.service", check=False)
        lines.append(("done", "first boot", "the card's first-boot install won't run again"))
    units = [u for u in (KIOSK_UNIT, WIFI_UNIT, *DOOR_UNITS, *HOMECERT_UNITS, SLICER_UNIT, BENCH_UNIT, POWER_KEY_UNIT) if unit_exists(u)]
    for u in units:
        sudo("systemctl", "disable", "--now", u, check=False)
        sudo("rm", "-f", f"/etc/systemd/system/{u}", check=False)
    if units:
        sudo("systemctl", "daemon-reload", check=False)
        lines.append(("done", "services", ", ".join(units) + " removed"))
    site = f"/etc/nginx/sites-enabled/{NGINX_SITE}"
    if Path(site).exists() or Path(site).is_symlink():
        sudo("rm", "-f", site, f"/etc/nginx/sites-available/{NGINX_SITE}", check=False)
        if sudo("nginx", "-t", "-q", check=False).returncode == 0:
            sudo("systemctl", "reload", "nginx", check=False)
        lines.append(("done", "web app", f"port {c.s['port']} is free again"))
    for p in (PRINTER_AVAHI, SLICER_AVAHI):
        if p.exists():
            sudo("rm", "-f", str(p), check=False)
    if LOGIND_POWER.exists():   # the power button halts at once again, as before
        sudo("rm", "-f", str(LOGIND_POWER), check=False)
        sudo("systemctl", "kill", "-s", "HUP", "systemd-logind", check=False)
        lines.append(("done", "power button", "a press halts at once again"))
    # the first Wi-Fi's own pieces (docs/setup.md): its site on the setup address, its DNS answer, its hotspot profile
    setup_site = f"/etc/nginx/sites-enabled/{WIFI_SITE}"
    if Path(setup_site).exists() or Path(setup_site).is_symlink() or WIFI_DNS.exists():
        sudo("rm", "-f", setup_site, f"/etc/nginx/sites-available/{WIFI_SITE}", str(WIFI_DNS), check=False)
        if sudo("nginx", "-t", "-q", check=False).returncode == 0:
            sudo("systemctl", "reload", "nginx", check=False)
    # Only the setup hotspot. The Wi-Fi the printer joined during setup (elyir-bench-wifi-<ssid>) is its real network
    # now and stays, or the printer would drop off the Wi-Fi the moment it's removed. state/wifi-setup.json goes
    # with ~/elyir-bench below, so reinstalling on a printer with no Wi-Fi and no cable opens setup again, on purpose.
    if shutil.which("nmcli"):
        sudo("nmcli", "connection", "delete", "elyir-bench-setup", check=False)
    ks_conf = settings_path(f).parent / "KlipperScreen.conf"
    if "# elyir-bench: begin" in read(ks_conf):
        ks_conf.write_text(strip_klipperscreen_menu(read(ks_conf)))
        lines.append(("done", "klipperscreen menu", "our entry taken out of KlipperScreen.conf"))
    if f["moonraker"]["components"]:
        comp = Path(f["moonraker"]["components"])
        for name in Component.FILES:
            if (comp / name).is_symlink():
                (comp / name).unlink()
    conf = f["moonraker"]["conf"]
    if conf and MoonrakerConf()._section(read(conf)):
        shutil.copy2(conf, Path(conf).with_suffix(".conf.elyir-bench-bak"))
        Path(conf).write_text(strip_intent_section(read(conf)))
    if f["moonraker"]["service"]:
        try:
            restart_moonraker(f)
            lines.append(("done", "moonraker", "restarted without Elyir Bench's part"))
        except StepFailed as e:
            lines.append(("fail", "moonraker", str(e)))
    link = HOME / ".local" / "bin" / "elyir-bench"
    if link.is_symlink():
        link.unlink()
    if Path(SUDOERS).exists():
        sudo("rm", "-f", SUDOERS, check=False)
    if BASE.exists():
        shutil.rmtree(BASE, ignore_errors=True)
        lines.append(("done", "files", f"{BASE} removed, with the paired phones"))
    lines.append(("ok", "kept", f"printer.cfg, Mainsail, files, history; {settings_path(f).name} for coming back"))
    report(lines, False)
    ok = not any(s == "fail" for s, _, _ in lines)
    print("\nElyir Bench is removed." if ok else "\nElyir Bench is mostly removed; the lines marked ✗ above need a look.")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="elyir-bench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    sub.add_parser("plan")
    sub.add_parser("doctor")
    a = sub.add_parser("apply")
    a.add_argument("release", nargs="?", type=Path)
    a.add_argument("--force", action="store_true", help="apply even while printing")
    a.add_argument("--invite", metavar="CODE", help="an invite code for Elyir's relay (install.sh --invite)")
    sub.add_parser("rollback")
    p = sub.add_parser("panel")
    p.add_argument("mode", choices=["elyir-bench", "klipperscreen", "none"])
    sm = sub.add_parser("startmacro", help="Elyir Bench's start macro: elyir-bench.cfg and its include line in printer.cfg")
    sm.add_argument("mode", choices=["on", "off"])
    sm.add_argument("--force", action="store_true", help="change it even while printing (Klipper reads it at its next restart)")
    sub.add_parser("homecert", help="keep the printer's name at home and its certificate current (the timer runs this)")
    r = sub.add_parser("remote", help="an invite code for Elyir's relay, or your own relay's token (kept out of elyir-bench.conf)")
    r.add_argument("what", choices=["invite", "token", "phones"])
    r.add_argument("value", nargs="?", default="")
    sub.add_parser("check", help="what the install command says first: this board, what it adds, what it leaves alone")
    sub.add_parser("pair", help="a QR code for your phone (with remote on, a one-time pairing code)")
    sub.add_parser("boards", help="bench.elyir.com/install's table of boards, as JSON (install/boards.json)")
    sub.add_parser("public-name", help="the relay name this machine would ask for: says nothing about the printer")
    rp = sub.add_parser("report", help="send Elyir a report (logs, release, settings; secrets taken out) or a message")
    rp.add_argument("--kind", choices=REPORT_KINDS, default="wrong")
    rp.add_argument("--note", default="", help="a few words: what happened, or the idea")
    rp.add_argument("--email", default="", help="where Elyir can answer")
    rp.add_argument("--context", default="", help="JSON: what the screen showed (the problem screen sends it)")
    rp.add_argument("--no-details", action="store_true", help="only the words: no logs or settings")
    rp.add_argument("--show", action="store_true", help="say what would go, send nothing")
    rm = sub.add_parser("remove", help="take Elyir Bench off this printer and put KlipperScreen back")
    rm.add_argument("--yes", action="store_true", help="don't ask first")
    rn = sub.add_parser("rename", help="the printer's name everywhere (its screens, name.local), then apply")
    rn.add_argument("name")
    ro = sub.add_parser("role", help="a printer, or a Bench Box (the box for every printer in the house), and back")
    ro.add_argument("to", choices=["controller", "printer"])
    b = sub.add_parser("bring", help="bring an old printer's setup over: an old card, another printer, a backup file")
    bs = b.add_subparsers(dest="what", required=True)
    bs.add_parser("scan", help="the sources it can see now: an old card in a USB reader, printers, backup files")
    bp = bs.add_parser("plan", help="what would come over from one, and whether its boards are the ones here")
    bp.add_argument("id")
    ba = bs.add_parser("apply", help="bring it over (the config that's here is kept beside it)")
    ba.add_argument("id")
    ba.add_argument("--gcodes", action="store_true", help="its print files too")
    bd = bs.add_parser("address", help="add a printer by its address (any Moonraker), then plan it")
    bd.add_argument("address")
    bc = bs.add_parser("cloud-ask", help="ask the house's owner to allow a Bench Cloud backup onto this card")
    bc.add_argument("id")
    bs.add_parser("cloud-check", help="whether the owner allowed it; if so, the backup becomes a backup file here")
    bs.add_parser("cloud-email", help="send the owner's email a code instead")
    bk = bs.add_parser("cloud-code", help="the code from the owner's email")
    bk.add_argument("code")
    cl = sub.add_parser("cloud", help="Bench Cloud (docs/cloud.md): join a house, back up now, status, leave")
    cs = cl.add_subparsers(dest="what", required=True)
    cj = cs.add_parser("join", help="join the house with a one-time join token (from an owner's phone)")
    cj.add_argument("token")
    cj.add_argument("--api", help=f"the cloud's address (default {CLOUD_API})")
    cs.add_parser("backup", help="back up now (the intent component does this every night)")
    cs.add_parser("status", help="joined or not, and the last backup")
    cs.add_parser("leave", help="leave the house: no more backups from this printer")
    args = ap.parse_args(argv)

    if args.cmd == "homecert":
        return homecert()

    if args.cmd == "public-name":
        print(public_name())
        return 0

    if args.cmd == "boards":   # about example boards, not this machine: runs anywhere, the Mac included
        print(json.dumps(site_table(), indent=1))
        return 0

    invite = getattr(args, "invite", None) or (args.value if args.cmd == "remote" and args.what == "invite" else None)
    if invite and not invite_code(invite):
        print("An invite code is twelve letters and numbers, like K7QX-M2PD-9HTF.")
        return 2

    if args.cmd == "remote" and args.what in ("invite", "token") and not args.value:
        print(f"elyir-bench remote {args.what} <{'code' if args.what == 'invite' else 'token'}>")
        return 2

    if args.cmd == "remote" and args.what == "token":
        save_relay({**load_relay(), "token": args.value})
        print(f"  saved in {RELAY_STATE}; run `elyir-bench apply` to use it")
        return 0

    if os.geteuid() == 0:
        print("Run elyir-bench as the printer's user, not root (it uses sudo where it needs to).")
        return 2

    facts = detect()
    if args.cmd == "report":
        s = load_settings(facts)
        try:
            context = json.loads(args.context) if args.context else None
        except ValueError:
            print("--context is JSON")
            return 2
        meta, bundle = gather_report(facts, s, args.kind, context, details=not args.no_details)
        meta.update({k: v for k, v in (("note", args.note.strip()), ("email", args.email.strip())) if v})
        if args.show:
            out = {**meta, "bundle_bytes": len(bundle or b"")}
            print(json.dumps(out, indent=1) if args.json else
                  "\n".join([f"{meta['printer'].get('name')}: {meta['kind']}", *(f"  {f}" for f in meta.get("files", [])),
                             f"  {len(bundle or b'') // 1024} KB, passwords, keys and Wi-Fi details taken out"]))
            return 0
        try:
            code = send_report(s, meta, bundle)
        except StepFailed as e:
            print(json.dumps({"error": str(e)}) if args.json else f"Not sent: {e}")
            return 1
        print(json.dumps({"code": code}) if args.json else f"Sent. If you write to us, give this number: {code}")
        return 0
    if args.cmd == "remote" and args.what == "phones":
        return remote_phones(load_settings(facts))
    if args.cmd == "detect":
        print(json.dumps(facts, indent=2))
        return 0

    settings = resolve_slicer(facts, load_settings(facts))
    release = getattr(args, "release", None)
    c = Ctx(facts, settings, release.resolve() if release else None, getattr(args, "force", False))

    if args.cmd == "check":
        if args.json:
            print(json.dumps(expectations(facts, settings), indent=2))
            return 0
        lines, code = check_report(facts, settings)
        print("\n".join(lines))
        return code

    if args.cmd == "pair":
        print("\n".join(pair_lines(facts, settings)))
        return 0

    if args.cmd == "bring":
        return bring_main(args, facts, settings)

    if args.cmd == "cloud":
        return cloud_main(args, facts, settings)

    if args.cmd == "role":
        return role_main(args, facts, settings)

    if args.cmd == "remove":
        if not args.yes:
            if not sys.stdin.isatty():
                print("Run `elyir-bench remove --yes` to remove without being asked.")
                return 2
            print("This takes Elyir Bench off the printer: KlipperScreen comes back on the screen, and paired phones\n"
                  "stop getting notifications. printer.cfg, Mainsail, your files and history stay.")
            if input("Remove Elyir Bench? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing was changed.")
                return 1
        return 0 if remove(c) else 1

    if args.cmd in ("plan", "doctor"):
        lines = plan(c)
        if args.cmd == "doctor" and c.s["panel"] in ("elyir-bench", "klipperscreen", "none"):
            ok, why = health(c, wait=1)
            lines.append(("ok" if ok else "fail", "health", why))
        if not args.json:
            print(f"Elyir Bench on {facts['host']} ({facts['model'] or facts['arch']}), settings: {settings_path(facts)}")
        report(lines, args.json)
        return 0 if all(s == "ok" for s, _, _ in lines) else 1

    if invite:
        if c.s.get("remote") != "relay":
            print(f"Invite codes are for Elyir's relay, and this printer has remote: {c.s.get('remote', 'off')} in "
                  f"{settings_path(facts)}.")
            return 2
        # kept until the relay has answered: offline now, the next apply uses it
        save_relay({**load_relay(), "invite": invite_code(invite)})

    if args.cmd == "remote":
        ok = apply(c, args.json, REMOTE_STEPS)
        if ok and not args.json and relay_carried(c.s):
            print("")
            print("\n".join(pair_lines(facts, c.s)))
        return 0 if ok else 1

    was, was_macro = c.s["panel"], c.s.get("start_macro", "off")
    if args.cmd == "startmacro":
        c.s["start_macro"] = args.mode
    if args.cmd == "panel":
        if args.mode == "klipperscreen" and not facts["klipperscreen"]["installed"]:
            print(f"{NO_KLIPPERSCREEN}, so the screen stays on {was}.")
            return 1
        c.s["panel"] = args.mode
    if args.cmd == "rename":
        name = re.sub(r"\s+", " ", args.name).strip()
        if not name or len(name) > 32:
            print("A name is 1 to 32 characters.")
            return 2
        rename(facts, c.s, name)
    save_settings(facts, c.s)

    if args.cmd == "rollback":
        prev = load_state().get("previous")
        if not prev or not (RELEASES / prev).exists():
            print("No previous release to go back to.")
            return 1
        c.release = None
        cur = current_version()
        switch_current(RELEASES / prev)
        st = load_state()
        st.update({"version": prev, "previous": cur})
        save_state(st)
        c.restart_moonraker = c.restart_kiosk = True
        print(f"Switched {cur} -> {prev}")

    only = {"panel": SCREEN_STEPS, "startmacro": START_MACRO_STEPS}.get(args.cmd)
    if args.cmd == "apply" and not args.json:
        keep_install_log()
    if apply(c, args.json, only):
        return 0
    if args.cmd == "panel":   # the switch was undone: remember the screen that's showing, for the next boot
        c.s["panel"] = was
        save_settings(facts, c.s)
    if args.cmd == "startmacro":   # undone too: the setting says what's there
        c.s["start_macro"] = was_macro
        save_settings(facts, c.s)
    return 1


if __name__ == "__main__":
    sys.exit(main())
