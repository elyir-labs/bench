"""The box itself, on its own Care (design/power/, A; design/role/, B's way back): turn it off or restart it, and make
it a printer again.
  GET  /bench/box            {power: true, role: null | {state: switching|failed, progress, why}}
  POST /bench/box/power      {kind: off|restart}: there's no nozzle to wait for, so it goes in two seconds
  POST /bench/box/role       `elyir-bench --json role printer`: Klipper and Moonraker back on, the printer app, its
                             screen (the panel then shows a fresh card's setup); its lines are followed from a file
Dry (the simulator rig, docker/bench-box): nothing is turned off or switched, it only says so.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import web

log = logging.getLogger("bench.box")
ROLE_RUN = "role-run.jsonl"


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
    def __init__(self, state: Path, installer: Path, dry: bool = False):
        self.state, self.installer, self.dry = state, installer, dry
        self.pid: Optional[int] = None
        self.started: Optional[float] = None

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/bench/box", self.get)
        app.router.add_post("/bench/box/power", self.power)
        app.router.add_post("/bench/box/role", self.role)

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
        return web.json_response({"power": True, "role": self._role()})

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
