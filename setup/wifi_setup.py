#!/usr/bin/env python3
"""A new printer's first Wi-Fi (docs/setup.md; design/setup/, direction C).

With no Wi-Fi it knows and no cable, the printer lists the networks it can hear, then opens its own setup
Wi-Fi, with a random password that only the panel's QR code carries. A phone that joins it gets the phone
page (its "sign in to this network" sheet opens by itself); the panel has the same steps with a keyboard.
Either way the printer then joins the home Wi-Fi, and the panel asks its name and offers the phone code.

  GET  /wifi/state         what the panel and the phone page draw from
  POST /wifi/scan          look again: the setup Wi-Fi closes for a few seconds
  POST /wifi/join          {ssid, password?, hidden?}: the setup Wi-Fi closes while the printer tries it
  POST /wifi/name          {name}: what the printer is called, applied once it's on the Wi-Fi
  POST /wifi/done          the panel is finished: the printer's own screens take over
  GET  /wifi/font/<file>   the app's Figtree, for the phone page (the setup Wi-Fi has no internet)
  GET  anything else       the phone page: that's how a phone's sign-in check finds it

nginx sends the app port's /wifi/ here, and everything on port 80 of the setup Wi-Fi's own address.

Runs as the printer's user, with NetworkManager through `sudo -n nmcli`. A password never goes on a command
line (sudo logs those): it's written straight into the network's NetworkManager keyfile through stdin.
Standard library only. `--fake` swaps NetworkManager for a pretend one, to build the screens on a laptop.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("wifi-setup")

SETUP_ID = "elyir-bench-setup"            # the setup Wi-Fi's NetworkManager connection
SETUP_ADDR = "10.42.0.1"                # its address; the installer's nginx site and DNS line use it too
SETUP_NET = "10.42.0."
KEYFILES = Path("/etc/NetworkManager/system-connections")
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"   # nothing that reads two ways
CABLE_WAIT = 15        # seconds a cable that's coming up gets, before the setup Wi-Fi opens
CHECK_EVERY = 5        # seconds between looks for a cable while the setup Wi-Fi is open
HANDOFF = 1.5          # seconds the phone gets to read "joining" before the setup Wi-Fi closes
PAGE = Path(__file__).with_name("phone.html")


# ── pure parts (tests/test_wifi_setup.py) ─────────────────────────────────────

def setup_password() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def setup_ssid(tail: str) -> str:
    return f"Elyir Bench {tail}"


def machine_tail() -> str:
    """Four characters that tell this printer from the one next to it: the end of its serial number."""
    for p in ("/sys/firmware/devicetree/base/serial-number", "/proc/device-tree/serial-number"):
        try:
            s = re.sub(r"[^0-9A-Fa-f]", "", Path(p).read_text(errors="ignore"))
            if len(s) >= 4:
                return s[-4:].upper()
        except OSError:
            pass
    try:
        m = re.search(r"^Serial\s*:\s*([0-9a-fA-F]+)", Path("/proc/cpuinfo").read_text(), re.M)
        if m and len(m.group(1)) >= 4:
            return m.group(1)[-4:].upper()
    except OSError:
        pass
    for dev in sorted(Path("/sys/class/net").glob("*")) if Path("/sys/class/net").exists() else []:
        mac = re.sub(r"[^0-9a-f]", "", (dev / "address").read_text().lower()) if (dev / "address").exists() else ""
        if mac and mac != "000000000000":
            return mac[-4:].upper()
    return "0000"


def wifi_qr(ssid: str, password: str) -> str:
    """The standard Wi-Fi QR code text, which an iPhone or Android camera offers to join."""
    esc = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def split_terse(line: str) -> list[str]:
    """One line of `nmcli -t`: fields split on ':', where a ':' or '\\' inside a field is escaped."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def security_kind(security: str) -> str:
    """open, wpa (a password), sae (WPA3 only) or enterprise (a username too: not offered here)."""
    s = security.upper()
    if s in ("", "--"):
        return "open"
    if "802.1X" in s:
        return "enterprise"
    if "WPA3" in s and "WPA2" not in s and "WPA1" not in s:
        return "sae"
    return "wpa"


def networks_from(rows: list[tuple[str, int, str]], skip: str = "") -> list[dict]:
    """The networks worth listing: named, not our own, once each at its best signal, strongest first."""
    best: dict[str, dict] = {}
    for ssid, signal, security in rows:
        if not ssid or ssid == skip:
            continue
        if ssid not in best or signal > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": signal, "security": security_kind(security)}
    return sorted(best.values(), key=lambda n: (-n["signal"], n["ssid"].lower()))


def password_problem(password: str, security: str) -> Optional[str]:
    if security == "open":
        return None
    if len(password) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", password):
        return None
    if 8 <= len(password.encode()) <= 63:
        return None
    return "Wi-Fi passwords are 8 to 63 characters."


def name_problem(name: str) -> Optional[str]:
    if not name.strip():
        return "Give it a name."
    if len(name.strip()) > 32:
        return "Keep it to 32 characters."
    if not re.search(r"[A-Za-z0-9]", name):
        return "Use at least one letter or number."
    return None


def _kv(v: str) -> str:
    """A value in a GKeyFile, as NetworkManager's keyfiles are written."""
    v = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return ("\\s" + v[1:]) if v.startswith(" ") else v


def keyfile(ssid: str, password: str, uid: str, *, security: str = "wpa", hidden: bool = False,
            ap: bool = False, ifname: Optional[str] = None) -> str:
    """A NetworkManager keyfile: the setup Wi-Fi (ap) or a home network to join."""
    lines = ["[connection]", f"id={SETUP_ID if ap else _kv(ssid)}", f"uuid={uid}", "type=wifi"]
    if ifname:
        lines.append(f"interface-name={ifname}")
    lines += [f"autoconnect={'false' if ap else 'true'}", "", "[wifi]", f"mode={'ap' if ap else 'infrastructure'}",
              f"ssid={_kv(ssid)}"]
    if ap:
        lines.append("band=bg")
    if hidden:
        lines.append("hidden=true")
    if security != "open":
        lines += ["", "[wifi-security]", f"key-mgmt={'sae' if security == 'sae' else 'wpa-psk'}"]
        if ap:   # phones join an AP on the Pi's chip reliably with WPA2 + CCMP only
            lines += ["proto=rsn", "pairwise=ccmp", "group=ccmp"]
        lines.append(f"psk={_kv(password)}")
    if ap:
        lines += ["", "[ipv4]", "method=shared", f"address1={SETUP_ADDR}/24", "", "[ipv6]", "method=disabled"]
    else:
        lines += ["", "[ipv4]", "method=auto", "", "[ipv6]", "method=auto"]
    return "\n".join(lines) + "\n"


def keyfile_name(ssid: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", ssid.lower()).strip("-")[:40] or "network"
    return f"elyir-bench-wifi-{slug}.nmconnection"


def failure_reason(message: str) -> str:
    m = message.lower()
    if "secrets were required" in m or "no secrets" in m or "802-11-wireless-security" in m or "psk" in m:
        return "password"
    if "no network with ssid" in m or "not found" in m or "no suitable" in m:
        return "not_found"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    return "other"


# ── NetworkManager ────────────────────────────────────────────────────────────

class NetworkManager:
    def _read(self, *args: str, timeout: int = 15) -> list[str]:
        p = subprocess.run(["nmcli", "-t", *args], capture_output=True, text=True, timeout=timeout)
        return [line for line in p.stdout.splitlines() if line]

    def _nm(self, *args: str, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
        p = subprocess.run(["sudo", "-n", "nmcli", *args], capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip())
        return p

    def _devices(self) -> list[tuple[str, str, str]]:
        return [tuple(split_terse(line)[:3]) for line in self._read("-f", "DEVICE,TYPE,STATE", "device")]

    @property
    def ifname(self) -> Optional[str]:
        return next((d for d, t, _ in self._devices() if t == "wifi"), None)

    def cable(self) -> str:
        """connected, coming (a cable is in and it's getting an address) or none."""
        states = [s for _, t, s in self._devices() if t == "ethernet"]
        if any(s.startswith("connected") for s in states):
            return "connected"
        return "coming" if any(s.startswith("connecting") for s in states) else "none"

    def online(self) -> bool:
        """A way out to the network by any route, managed by NetworkManager or not: never close that."""
        p = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True)
        return bool(p.stdout.strip())

    def wifi_state(self) -> str:
        """The Wi-Fi chip as NetworkManager sees it: disconnected (free to use), unavailable (blocked or
        off: unblocked first), unmanaged (someone else's), connected, or none."""
        state = next((s for _, t, s in self._devices() if t == "wifi"), "none")
        if state.startswith("unavailable"):
            subprocess.run(["sudo", "-n", "rfkill", "unblock", "wifi"], capture_output=True)
            self._nm("radio", "wifi", "on")
            time.sleep(2)
            state = next((s for _, t, s in self._devices() if t == "wifi"), "none")
        return state.split(" ")[0]

    def saved_wifi(self) -> list[str]:
        out = []
        for line in self._read("-f", "NAME,TYPE", "connection", "show"):
            name, kind = (split_terse(line) + [""])[:2]
            if kind == "802-11-wireless" and name != SETUP_ID:
                out.append(name)
        return out

    def scan(self) -> list[dict]:
        dev = self.ifname
        if not dev:
            return []
        subprocess.run(["sudo", "-n", "rfkill", "unblock", "wifi"], capture_output=True)
        self._nm("radio", "wifi", "on")
        self._nm("device", "wifi", "rescan", "ifname", dev)
        time.sleep(4)
        rows = []
        for line in self._read("-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", dev, "--rescan", "no"):
            f = split_terse(line)
            if len(f) >= 3:
                rows.append((f[0], int(f[1]) if f[1].isdigit() else 0, f[2]))
        return rows

    def _write(self, name: str, text: str) -> Path:
        path = KEYFILES / name
        p = subprocess.run(["sudo", "-n", "install", "-m", "600", "-o", "root", "-g", "root", "/dev/stdin", str(path)],
                           input=text, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"writing {path}: {p.stderr.strip()}")
        self._nm("connection", "load", str(path), check=True)
        return path

    def open(self, ssid: str, password: str) -> None:
        self._write(f"{SETUP_ID}.nmconnection", keyfile(ssid, password, str(uuid.uuid5(uuid.NAMESPACE_DNS, SETUP_ID)),
                                                        ap=True, ifname=self.ifname))
        self._nm("connection", "up", "id", SETUP_ID, check=True)

    def close(self) -> None:
        self._nm("connection", "down", "id", SETUP_ID)

    def forget_setup(self) -> None:
        self._nm("connection", "delete", "id", SETUP_ID)

    def join(self, ssid: str, password: str, security: str, hidden: bool) -> tuple[bool, str, str]:
        uid = str(uuid.uuid4())
        self._write(keyfile_name(ssid), keyfile(ssid, password, uid, security=security, hidden=hidden))
        dev = self.ifname
        if dev:
            self._nm("device", "wifi", "rescan", "ifname", dev)
            time.sleep(3)
        p = self._nm("--wait", "45", "connection", "up", "uuid", uid, timeout=60)
        if p.returncode == 0:
            return True, "", ""
        message = (p.stderr or p.stdout).strip()
        self._nm("connection", "delete", "uuid", uid)   # a network that didn't work isn't kept
        return False, failure_reason(message), message


class FakeNetworkManager:
    """For a laptop: the same answers, after the same pauses, with nothing touched.
    A password starting "wrong" fails as a wrong password; a network called "Nowhere" isn't found."""
    ifname = "wlan0"

    def __init__(self, speed: float = 1.0):
        self.speed, self.up, self.joined = speed, False, None

    def _wait(self, s: float) -> None:
        time.sleep(s / self.speed)

    def cable(self) -> str:
        return "none"

    def online(self) -> bool:
        return False

    def wifi_state(self) -> str:
        return "disconnected"

    def saved_wifi(self) -> list[str]:
        return [self.joined] if self.joined else []

    def scan(self) -> list[tuple[str, int, str]]:
        self._wait(3)
        return [("Hartley Home", 88, "WPA2"), ("Hartley Home Guest", 80, "WPA2"), ("Garage AP", 52, "WPA1 WPA2"),
                ("DIRECT-roku-829", 21, "WPA2"), ("Corner Cafe", 30, "--"), ("Hartley Home", 61, "WPA2")]

    def open(self, ssid: str, password: str) -> None:
        log.info("pretend: setup Wi-Fi %r open", ssid)
        self.up = True

    def close(self) -> None:
        self.up = False

    def forget_setup(self) -> None:
        self.up = False

    def join(self, ssid: str, password: str, security: str, hidden: bool) -> tuple[bool, str, str]:
        self._wait(6)
        if ssid == "Nowhere":
            return False, "not_found", "Error: No network with SSID 'Nowhere' found."
        if security != "open" and password.startswith("wrong"):
            return False, "password", "Error: Connection activation failed: Secrets were required, but not provided."
        self.joined = ssid
        return True, "", ""


# ── the setup ─────────────────────────────────────────────────────────────────

class Setup:
    """off · looking (listing networks) · open (setup Wi-Fi up) · joining · failed (setup Wi-Fi back) · connected"""

    def __init__(self, nm, state_file: Path, installer: Optional[str], app_port: str, tail: Optional[str] = None,
                 force: bool = False):
        self.nm, self.state_file, self.installer, self.app_port, self.force = nm, state_file, installer, app_port, force
        self.lock = threading.Condition()
        self.saved = self._load()
        self.ssid_setup = setup_ssid(tail or machine_tail())
        if not self.saved.get("password"):
            self.saved["password"] = setup_password()
        self.mode = "off"
        self.networks: list[dict] = []
        self.ssid: Optional[str] = None
        self.reason: Optional[str] = None
        self.via: Optional[str] = None
        self.renaming = False
        self.todo: list[tuple[str, dict]] = []

    # persisted: done, joined (the network it joined), name, renamed, password (the setup Wi-Fi's)
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.saved, indent=1))
        tmp.chmod(0o600)
        tmp.replace(self.state_file)

    def public(self, host: Optional[str] = None) -> dict:
        with self.lock:
            out: dict[str, Any] = {"mode": self.mode, "networks": self.networks, "ssid": self.ssid, "reason": self.reason,
                                   "via": self.via, "name": self.saved.get("name"), "renaming": self.renaming,
                                   "host": host or socket.gethostname(), "port": self.app_port}
            if self.mode in ("looking", "open", "joining", "failed"):
                out["setup"] = {"ssid": self.ssid_setup, "qr": wifi_qr(self.ssid_setup, self.saved["password"])}
            return out

    # the requests: checked here, carried out by the worker
    def ask(self, what: str, body: dict) -> tuple[int, dict]:
        with self.lock:
            if what == "scan":
                if self.mode not in ("open", "failed"):
                    return 409, {"message": "The printer isn't setting up its Wi-Fi now."}
            elif what == "join":
                if self.mode not in ("open", "failed"):
                    return 409, {"message": "The printer isn't setting up its Wi-Fi now. Look at its screen."}
                ssid = str(body.get("ssid", "")).strip()
                if not ssid or len(ssid.encode()) > 32:
                    return 400, {"reason": "ssid", "message": "Type the network's name (up to 32 characters)."}
                known = next((n for n in self.networks if n["ssid"] == ssid), None)
                security = known["security"] if known else ("wpa" if body.get("password") else "open")
                if security == "enterprise":
                    return 400, {"reason": "enterprise", "message": "This network needs a username too, which isn't supported yet."}
                problem = password_problem(str(body.get("password", "")), security)
                if problem:
                    return 400, {"reason": "password", "message": problem}
                body = {"ssid": ssid, "password": str(body.get("password", "")), "security": security,
                        "hidden": bool(body.get("hidden")) or known is None}
                self.mode, self.ssid, self.reason = "joining", ssid, None   # at once, so both screens move on together
            elif what == "name":
                name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()
                problem = name_problem(name)
                if problem:
                    return 400, {"message": problem}
                self.saved["name"] = name
                self._save()
                if self.mode != "connected":
                    return 200, self._public_unlocked()
            elif what == "done":
                if self.mode != "connected":
                    return 409, {"message": "The printer isn't on the Wi-Fi yet."}
                self.saved["done"] = True
                self._save()
                self.mode = "off"
            else:
                return 404, {"message": "No such thing."}
            self.todo.append((what, body))
            self.lock.notify_all()
            return (202 if what in ("scan", "join") else 200), self._public_unlocked()

    def _public_unlocked(self) -> dict:
        return {"mode": self.mode, "ssid": self.ssid, "name": self.saved.get("name")}

    def _set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)
            self.lock.notify_all()

    # the worker: one thing at a time, since it's one Wi-Fi chip
    def run(self) -> None:
        try:
            self._begin()
        except Exception:
            log.exception("setting up the Wi-Fi failed")
        while True:
            with self.lock:
                if not self.todo:
                    self.lock.wait(timeout=CHECK_EVERY)
                job = self.todo.pop(0) if self.todo else None
            try:
                if job:
                    self._do(*job)
                elif self.mode in ("open", "failed") and not self.force and self.nm.cable() == "connected":
                    log.info("a cable came in: closing the setup Wi-Fi")
                    self.nm.close()
                    self.saved["joined"] = "cable"
                    self._save()
                    self._set(mode="connected", via="cable", ssid=None, reason=None)
                    self._rename()
            except Exception:
                log.exception("%s failed", job[0] if job else "checking for a cable")

    def _begin(self) -> None:
        if self.saved.get("done"):
            return
        if self.saved.get("joined"):   # it joined before a restart: the panel still has its name and phone to do
            self._set(mode="connected", via="cable" if self.saved["joined"] == "cable" else "wifi",
                      ssid=None if self.saved["joined"] == "cable" else self.saved["joined"])
            self._rename()
            return
        if self.force:
            log.info("--force: opening the setup Wi-Fi whatever else is connected (testing over a cable)")
            self._look_and_open()
            return
        if self.nm.saved_wifi():
            log.info("a Wi-Fi is already set up (%s): nothing to do", ", ".join(self.nm.saved_wifi()))
            return
        deadline = time.time() + CABLE_WAIT
        while self.nm.cable() == "coming" and time.time() < deadline:
            time.sleep(1)
        if self.nm.cable() == "connected" or self.nm.online():
            log.info("on the network already (a cable, or a Wi-Fi set up some other way): nothing to do")
            return
        state = self.nm.wifi_state()
        if state != "disconnected":
            log.info("the Wi-Fi chip is %s: no setup Wi-Fi", state)
            return
        self._look_and_open()

    def _look_and_open(self) -> None:
        self._set(mode="looking")
        found = self.nm.scan()
        self._set(networks=networks_from(found, skip=self.ssid_setup))
        self.nm.open(self.ssid_setup, self.saved["password"])
        self._save()
        with self.lock:
            if self.mode == "looking":
                self.mode = "open"
            self.lock.notify_all()
        log.info("setup Wi-Fi %r open, %d networks listed", self.ssid_setup, len(self.networks))

    def _do(self, what: str, body: dict) -> None:
        if what == "scan":
            self.nm.close()
            self._look_and_open()
        elif what == "join":
            time.sleep(HANDOFF)
            self.nm.close()
            ok, reason, message = self.nm.join(body["ssid"], body["password"], body["security"], body["hidden"])
            if ok:
                log.info("joined %r", body["ssid"])
                self.saved["joined"] = body["ssid"]
                self._save()
                self.nm.forget_setup()
                self._set(mode="connected", via="wifi", reason=None)
                self._rename()
            else:
                log.info("joining %r failed (%s): %s", body["ssid"], reason, message)
                self.nm.open(self.ssid_setup, self.saved["password"])
                self._set(mode="failed", reason=reason)
        elif what == "name":
            self._rename()
        elif what == "done":
            self.nm.forget_setup()

    def _rename(self) -> None:
        """Once it's on the network, the chosen name is applied the installer's way (its name everywhere)."""
        name = self.saved.get("name")
        if not name or name == self.saved.get("renamed") or not self.installer:
            return
        self._set(renaming=True)
        try:
            # the name only, quickly: the person is looking at "Getting Workshop ready"; downloads wait ...
            env = {**os.environ, "ELYIR_BENCH_DEFER_DOWNLOADS": "1"}
            p = subprocess.run([sys.executable, self.installer, "rename", name], capture_output=True, text=True,
                               timeout=900, env=env)
            log.info("rename to %r: %s", name, (p.stdout + p.stderr).strip()[-800:])
            if p.returncode == 0:
                self.saved["renamed"] = name
                self._save()
        finally:
            self._set(renaming=False)
        self._finish_install()

    def _finish_install(self) -> None:
        """... and then, in the background, whatever the first boot left for the network (docs/image.md)."""
        log_path = self.state_file.with_name("apply-after-setup.log")
        with open(log_path, "a") as out:
            subprocess.Popen([sys.executable, self.installer, "apply"], stdout=out, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        log.info("finishing the install in the background (%s)", log_path)


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    flow: Setup
    fonts: Optional[Path] = None
    server_version = "elyir-bench-wifi"

    def log_message(self, fmt: str, *args) -> None:   # never the bodies: they carry passwords
        log.debug("%s %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, kind: str, extra: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _client(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/wifi/state":
            return self._json(200, self.flow.public())
        if path.startswith("/wifi/font/"):
            name = path.rsplit("/", 1)[-1]
            f = self.fonts / name if self.fonts and re.fullmatch(r"figtree-[a-z-]+\.woff2", name) else None
            if f and f.is_file():
                return self._send(200, f.read_bytes(), "font/woff2", {"Cache-Control": "public, max-age=86400"})
            return self._json(404, {"message": "No such font."})
        # Port 80 can reach here from the house too (when nothing else serves it): once set up, that's the app
        if self.flow.mode in ("off", "connected") and not self._client().startswith(SETUP_NET):
            host = (self.headers.get("Host") or socket.gethostname()).split(":")[0]
            return self._send(302, b"", "text/plain", {"Location": f"http://{host}:{self.flow.app_port}/"})
        return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        m = re.fullmatch(r"/wifi/(scan|join|name|done)", path)
        if not m:
            return self._json(404, {"message": "No such thing."})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4096:
            return self._json(413, {"message": "Too long."})
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"message": "That wasn't understood."})
        code, out = self.flow.ask(m.group(1), body)
        self._json(code, out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", default=str(Path.home() / "elyir-bench" / "state" / "wifi-setup.json"))
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8097)
    ap.add_argument("--app-port", default="8088", help="the app's port, for the printer's address once it's on the Wi-Fi")
    ap.add_argument("--app-dir", help="the release's app, for its Figtree")
    ap.add_argument("--installer", help="the installer, which applies the name (elyir_bench.py rename)")
    ap.add_argument("--fake", action="store_true", help="pretend NetworkManager, for a laptop")
    ap.add_argument("--speed", type=float, default=1.0, help="with --fake: how much faster than life")
    ap.add_argument("--force", action="store_true", help="open the setup Wi-Fi even when online (testing with SSH over a cable)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    nm = FakeNetworkManager(a.speed) if a.fake else NetworkManager()
    setup = Setup(nm, Path(a.state), a.installer, a.app_port, tail="4F2A" if a.fake else None, force=a.force)
    Handler.flow = setup
    Handler.fonts = Path(a.app_dir) / "fonts" if a.app_dir else Path(__file__).resolve().parent.parent / "app" / "public" / "fonts"
    threading.Thread(target=setup.run, daemon=True).start()
    srv = ThreadingHTTPServer((a.listen, a.port), Handler)
    log.info("first Wi-Fi on %s:%d%s", a.listen, a.port, " (pretend)" if a.fake else "")
    srv.serve_forever()


if __name__ == "__main__":
    main()
