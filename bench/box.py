"""The box itself, on its own Care (design/power/, A; design/role/, B's way back): turn it off or restart it, and make
it a printer again.
  GET  /bench/box            {power: true, role: null | {state: switching|failed, progress, why}}
  POST /bench/box/power      {kind: off|restart}: there's no nozzle to wait for, so it goes in two seconds
  POST /bench/box/role       `elyir-bench --json role printer`: Klipper and Moonraker back on, the printer app, its
                             screen (the panel then shows a fresh card's setup); its lines are followed from a file
  POST /bench/box/update     `elyir-bench-os update`, now rather than overnight (a card's OS only: GET says os: null
                             elsewhere); the box restarts into the new OS, and goes back by itself if it doesn't start
  POST /bench/box/ssh        {key}: a public key that may sign in as this user (a card's user has no password)
  DELETE /bench/box/ssh/{id}
Home only: the away listener never routes these. Dry (the simulator rig, docker/bench-box): nothing is turned off,
switched or updated, it only says so, and the keys are a file in the rig's state.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import web

log = logging.getLogger("bench.box")
ROLE_RUN = "role-run.jsonl"
OS_VERSION = Path("/usr/local/share/elyir-bench/os-version")     # a card's own release (installer/elyir_bench_os.py)
OS_FEED = "https://releases.elyir.dev/bench/os/latest-{board}.json"
OS_TOOL = "/usr/local/sbin/elyir-bench-os"
KEY_KINDS = ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
             "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")


def parse_key(line: str) -> Optional[Dict[str, str]]:
    """One authorized_keys line as Care lists it ({id, kind, name, line}), or None for anything else (options
    before the key, a comment): those lines stay in the file as they are."""
    f = line.strip().split(None, 2)
    if len(f) < 2 or f[0] not in KEY_KINDS:
        return None
    try:
        blob = base64.b64decode(f[1], validate=True)
    except ValueError:
        return None
    # the blob starts with its own kind, length first: a key pasted under another kind's name isn't one
    n = int.from_bytes(blob[:4], "big")
    if blob[4:4 + n].decode("ascii", "replace") != f[0]:
        return None
    return {"id": hashlib.sha256(blob).hexdigest()[:12], "kind": f[0].split("@")[0], "name": f[2].strip() if len(f) > 2 else "",
            "line": " ".join(f)}


def update_state(lines: List[str], code: Optional[int]) -> Optional[Dict[str, Any]]:
    """An update started from Care, as the page is told: updating with its last line, failed with why, or None
    when it ended well (it restarts the box) or never ran."""
    last = next((l.strip() for l in reversed(lines) if l.strip()), "")
    if code is None:
        return {"state": "updating", "line": last}
    if code != 0:
        return {"state": "failed", "why": last.removeprefix("elyir-bench-os: ") or "It stopped without saying why."}
    return None


def role_state(lines: List[str], alive: bool) -> Optional[Dict[str, Any]]:
    """What the role run said, as the page is told: switching with its step, failed with why, or None once it ended
    well (the screen is the printer's by then)."""
    state: Dict[str, Any] = {"state": "switching", "progress": None, "why": None}
    seen = False
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        seen = True
        if "progress" in msg:
            state["progress"] = msg["progress"]
        elif "failed" in msg:
            return {"state": "failed", "progress": state["progress"], "why": str(msg["failed"])}
        elif "result" in msg:
            return None
    if not alive and seen:
        return {"state": "failed", "progress": state["progress"], "why": "It stopped without saying why."}
    return state if (seen or alive) else None


class Box:
    def __init__(self, state: Path, installer: Path, dry: bool = False, keys: Optional[Path] = None,
                 os_version: Path = OS_VERSION, feed: Optional[str] = OS_FEED):
        self.state, self.installer, self.dry = state, installer, dry
        self.pid: Optional[int] = None
        self.started: Optional[float] = None
        self.keys = keys or (state / "authorized_keys" if dry else Path.home() / ".ssh" / "authorized_keys")
        self.os_version, self.feed = os_version, None if dry else feed
        self.latest: tuple = (0.0, None)          # (when it was read, the feed's version)
        self.updater: Optional[subprocess.Popen] = None

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/bench/box", self.get)
        app.router.add_post("/bench/box/power", self.power)
        app.router.add_post("/bench/box/role", self.role)
        app.router.add_post("/bench/box/update", self.update)
        app.router.add_post("/bench/box/ssh", self.add_key)
        app.router.add_delete("/bench/box/ssh/{id}", self.remove_key)

    def _alive(self) -> bool:
        if self.pid is None:
            return False
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _role(self) -> Optional[Dict[str, Any]]:
        if self.started is None:
            return None
        try:
            lines = (self.state / ROLE_RUN).read_text().splitlines()
        except OSError:
            lines = []
        # a run that hasn't said anything yet counts as alive for half a minute
        alive = self._alive() or (not lines and time.time() - self.started < 30)
        return role_state(lines, alive)

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response({"power": True, "role": self._role(), "os": await self._os(),
                                  "ssh": {"user": os.environ.get("USER") or Path.home().name,
                                          "keys": [{k: v for k, v in key.items() if k != "line"} for key in self._keys()]}})

    # ── its OS, on a card ──

    def _read_latest(self, board: str) -> Optional[str]:
        with urllib.request.urlopen(self.feed.format(board=board), timeout=8) as r:
            return json.loads(r.read()).get("version")

    async def _os(self) -> Optional[Dict[str, Any]]:
        try:
            have = self.os_version.read_text().strip()
        except OSError:
            return None                         # installed onto its own OS: that's updated as any Debian is
        when, latest = self.latest
        if self.feed and time.time() - when > 600:
            try:
                model = Path("/proc/device-tree/model").read_text(errors="replace")
                m = re.search(r"Raspberry Pi (\d+)", model)
                if m:
                    latest = await asyncio.get_running_loop().run_in_executor(None, self._read_latest, f"pi{m.group(1)}")
            except Exception as e:              # offline: say nothing new, look again later
                log.info("box: can't read the OS feed (%s)", e.__class__.__name__)
            self.latest = (time.time(), latest)
        return {"version": have, "latest": latest, "update": self._update()}

    def _update(self) -> Optional[Dict[str, Any]]:
        if self.updater is None:
            return None
        try:
            lines = (self.state / "update-run.log").read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        return update_state(lines, self.updater.poll())

    async def update(self, request: web.Request) -> web.Response:
        u = self._update()
        if u and u["state"] == "updating":
            raise web.HTTPConflict(text="It's updating now.")
        if not self.os_version.exists():
            raise web.HTTPConflict(text="This box's OS wasn't flashed from an Elyir Bench card: update it as any Debian.")
        log.info("box: updating its OS%s", " (dry)" if self.dry else "")
        self.state.mkdir(parents=True, exist_ok=True)
        cmd = ["true"] if self.dry else ["sudo", "-n", OS_TOOL, "update"]
        with open(self.state / "update-run.log", "w") as out:
            self.updater = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            start_new_session=True)
        return web.json_response({"ok": True, "dry": self.dry, "update": self._update()})

    # ── SSH keys: a card's user has no password, so a key is the way in from a computer ──

    def _lines(self) -> List[str]:
        try:
            return self.keys.read_text().splitlines()
        except OSError:
            return []

    def _keys(self) -> List[Dict[str, str]]:
        return [k for k in map(parse_key, self._lines()) if k]

    def _write(self, lines: List[str]) -> None:
        self.keys.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.keys.with_name(self.keys.name + ".tmp")
        tmp.write_text("".join(l + "\n" for l in lines))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.keys)

    async def add_key(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        text = str((body or {}).get("key") or "")
        if len(text) > 16384:
            raise web.HTTPBadRequest(text="That's too long for a public key.")
        new = [k for k in map(parse_key, text.splitlines()) if k]
        if not new:
            raise web.HTTPBadRequest(text="That isn't a public key. It's one line starting with ssh-ed25519, ssh-rsa or ecdsa-sha2, often in a .pub file.")
        have = {k["id"] for k in self._keys()}
        added = [k for k in new if k["id"] not in have]
        if added:
            self._write(self._lines() + [k["line"] for k in added])
            log.info("box: %d SSH key(s) added", len(added))
        return web.json_response({"ok": True, "added": len(added)})

    async def remove_key(self, request: web.Request) -> web.Response:
        kid = request.match_info["id"]
        lines = self._lines()
        left = [l for l in lines if (parse_key(l) or {}).get("id") != kid]
        if len(left) == len(lines):
            raise web.HTTPNotFound(text="No such key.")
        self._write(left)
        log.info("box: an SSH key taken off")
        return web.json_response({"ok": True})

    async def power(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        kind = "restart" if (body or {}).get("kind") == "restart" else "off"
        log.info("box: %s%s", "restarting" if kind == "restart" else "turning off", " (dry)" if self.dry else "")
        if not self.dry:
            async def go() -> None:
                await asyncio.sleep(2)   # the page hears the answer first
                subprocess.run(["sudo", "-n", "systemctl", "reboot" if kind == "restart" else "poweroff"], check=False)
            asyncio.ensure_future(go())
        return web.json_response({"ok": True, "kind": kind, "dry": self.dry})

    async def role(self, request: web.Request) -> web.Response:
        r = self._role()
        if r and r["state"] == "switching":
            raise web.HTTPConflict(text="It's becoming a printer now.")
        self.state.mkdir(parents=True, exist_ok=True)
        run, logf = self.state / ROLE_RUN, self.state / "role-run.log"
        self.started = time.time()
        if self.dry:
            run.write_text(json.dumps({"started": "role", "pid": 0}) + "\n"
                           + json.dumps({"progress": {"step": "Klipper and Moonraker on", "done": 0, "of": 3}}) + "\n")
            self.pid = os.getpid()   # "alive" for as long as this rig runs
            log.info("box: becoming a printer (dry)")
            return web.json_response({"ok": True, "dry": True, "role": self._role()})
        run.write_text("")
        with open(run, "w") as out, open(logf, "a") as err:
            p = subprocess.Popen(["/usr/bin/python3", str(self.installer), "--json", "role", "printer"],
                                 stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True)
        self.pid = p.pid
        log.info("box: becoming a printer (pid %s)", p.pid)
        return web.json_response({"ok": True, "role": self._role()})
