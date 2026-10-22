"""A pretend printer for the service's tool changes, beside the pretend units (pretend_ace.py).

It answers the few Moonraker calls the service makes over its websocket, runs a little G-code (extruder moves,
heating, PAUSE_BASE/RESUME_BASE, CANCEL_PRINT, ELYIR_TOOL as its macro would, and named macros that do
nothing), and models the filament: each slot's tip, measured from the unit's parking spot, moves with the unit
until it reaches the extruder's gears, which then hold it and move it. The sensor sits sensor_at mm from park;
its edges are pushed at once as the gcode_button would, and reported in status every 250 ms as Klipper does.
"""
import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Set

from aiohttp import web

SENSOR = "filament_switch_sensor extruder_sensor"
TICK = 0.01
ASSIST_MM_S = 20.0
SLACK_MM = 30.0       # the tube takes this much filament pushed back up before it buckles


class PretendPrinter:
    def __init__(self, aces: List[Any], sensor_at: float = 600.0, grip: float = 8.0, nozzle: float = 120.0,
                 loaded: Optional[int] = None, time_scale: float = 1.0, macros=("BEFORE_CHANGE", "AFTER_CHANGE")) -> None:
        self.aces = aces
        self.slots = [(a, k) for a in aces for k in range(len(a.slots))]
        self.sensor_at, self.grip, self.nozzle, self.scale = sensor_at, grip, nozzle, time_scale
        self.x = {g: 0.0 for g in range(len(self.slots))}
        if loaded is not None:
            self.x[loaded] = sensor_at + grip + nozzle
        self.blocked: Set[int] = set()          # a slot whose filament jams before the sensor
        self.macros = set(macros)
        self.state = "standby"
        self.paused = False
        self.purge_next = -1.0              # ELYIR_PURGE, until the next ELYIR_TOOL takes it
        self.target = 0.0
        self.detected = self._detected()
        self.gcode_log: List[str] = []
        self.edges: List[tuple] = []           # (filament there, the unit's filament position then)
        self.agents: Set[web.WebSocketResponse] = set()
        self.subs: Dict[web.WebSocketResponse, Dict[str, Any]] = {}
        self._last_unit = {g: 0.0 for g in self.x}
        self.pulling = False                   # a forward extruder move is running: feed assist helps then
        self.buckled: List[int] = []           # slots whose filament the extruder pulled back while feed assist pushed
        self.before_retract = 0.0              # mm the before-change macro pulls back first, as a tip cut does
        self.head = (70.0, 331.0)              # where the nozzle is (x, y)
        self.pushed_at: List[tuple] = []       # where the nozzle was each time the extruder pushed filament in
        self._dirty = False
        self._tasks: List[asyncio.Task] = []
        self.runner: Optional[web.AppRunner] = None
        self.url = ""

    # ---- the filament path ---------------------------------------------------------------

    def _detected(self) -> bool:
        return any(x >= self.sensor_at for x in self.x.values())

    def gripped(self, g: int) -> bool:
        return self.x[g] >= self.sensor_at + self.grip - 1e-6

    def _follow_units(self) -> None:
        for g, (ace, k) in enumerate(self.slots):
            now = ace.filament_at(k)
            du, self._last_unit[g] = now - self._last_unit[g], now
            if self.gripped(g):
                continue                       # the gears hold it: the unit slips
            if ace.assist == k and self.x[g] >= self.sensor_at - 20:
                du += ASSIST_MM_S * TICK * self.scale   # feed assist pushes on by itself, into the gears (Workshop)
            if du == 0:
                continue
            limit = self.sensor_at - 50 if g in self.blocked else self.sensor_at + self.grip
            self.x[g] = max(-1000.0, min(self.x[g] + du, limit))
        self._edge()

    def _edge(self) -> None:
        d = self._detected()
        if d != self.detected:
            self.detected = d
            g = max(self.x, key=lambda i: self.x[i])
            ace, k = self.slots[g]
            self.edges.append((d, ace.filament_at(k)))
            self._push("elyir_sensor", {"state": "pressed" if d else "released"})
            self._dirty = True

    async def _extrude(self, mm: float, feed: float) -> None:
        seconds = abs(mm) / (feed / 60.0) / self.scale
        steps = max(1, int(seconds / TICK))
        self.pulling = mm > 0
        if mm < 0:
            for g, (ace, k) in enumerate(self.slots):
                if not self.gripped(g):
                    continue
                pulling = bool(ace.motion and ace.motion["slot"] == k and ace.motion["dir"] < 0)
                if ace.assist == k or (not pulling and -mm > SLACK_MM):
                    self.buckled.append(g)     # pushed back up a tube the unit holds still: it buckles in the splitter
        try:
            for _ in range(steps):
                g = next((i for i in self.x if self.gripped(i)), None)
                if g is not None:
                    self.x[g] += mm / steps
                self._edge()
                await asyncio.sleep(seconds / steps)
        finally:
            self.pulling = False

    async def _tick(self) -> None:
        last = 0.0
        loop = asyncio.get_running_loop()
        while True:
            self._follow_units()
            if self._dirty and loop.time() - last >= 0.25 / self.scale:
                last, self._dirty = loop.time(), False
                await self._notify()
            await asyncio.sleep(TICK)

    # ---- what a print does ---------------------------------------------------------------

    def start_print(self) -> None:
        self.state, self.paused, self.target = "printing", False, 240.0
        self._dirty = True

    def status(self) -> Dict[str, Any]:
        return {SENSOR: {"filament_detected": self.detected}, "print_stats": {"state": self.state},
                "pause_resume": {"is_paused": self.paused}, "extruder": {"target": self.target, "temperature": self.target}}

    async def run_gcode(self, script: str) -> None:
        for line in script.splitlines():
            line = line.strip()
            if not line:
                continue
            self.gcode_log.append(line)
            word = line.split()[0].upper()
            if word in ("M83", "M400", "G90", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE", "SET_PIN"):
                pass             # moves here run to their end before the next line, as M400 makes them
            elif word == "G1":
                e = re.search(r"E(-?[\d.]+)", line)
                f = re.search(r"F([\d.]+)", line)
                x, y = re.search(r"X(-?[\d.]+)", line), re.search(r"Y(-?[\d.]+)", line)
                if x or y:
                    self.head = (float(x.group(1)) if x else self.head[0], float(y.group(1)) if y else self.head[1])
                if e:
                    if float(e.group(1)) > 0:
                        self.pushed_at.append(self.head)
                    await self._extrude(float(e.group(1)), float(f.group(1)) if f else 300.0)
            elif word in ("M109", "M104"):
                self.target = float(re.search(r"S([\d.]+)", line).group(1))
                self._dirty = True
            elif word == "PAUSE_BASE":
                if self.state == "printing":
                    self.state, self.paused, self._dirty = "paused", True, True
            elif word == "RESUME_BASE":
                if self.paused:
                    self.state, self.paused, self._dirty = "printing", False, True
            elif word == "CANCEL_PRINT":
                self.state, self.paused, self._dirty = "cancelled", False, True
            elif word == "ELYIR_PURGE":
                m = re.search(r"LENGTH=(-?[\d.]+)", line)
                self.purge_next = float(m.group(1)) if m else -1.0
            elif word == "ELYIR_TOOL":
                tool = int(re.search(r"T=(-?\d+)", line).group(1))
                printing = self.state == "printing"
                self._push("elyir_tool", {"tool": tool, "in_print": printing, "purge": self.purge_next})   # rendered first, as Klipper does
                self.purge_next = -1.0
                if printing:
                    self.state, self.paused, self._dirty = "paused", True, True
            elif word in self.macros:
                if word == "BEFORE_CHANGE" and self.before_retract and "FROM=-1" not in line:
                    await self._extrude(-self.before_retract, 1500)
                await asyncio.sleep(0.05 / self.scale)
            else:
                raise ValueError(f"Unknown command: {word}")

    # ---- Moonraker's websocket -----------------------------------------------------------

    def _push(self, method: str, params: Dict[str, Any]) -> None:
        for ws in list(self.agents):
            asyncio.ensure_future(ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params})))

    async def _notify(self) -> None:
        st = self.status()
        for ws, objs in list(self.subs.items()):
            part = {k: v for k, v in st.items() if k in objs}
            try:
                await ws.send_str(json.dumps({"jsonrpc": "2.0", "method": "notify_status_update", "params": [part, 0.0]}))
            except ConnectionError:
                self.subs.pop(ws, None)

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            m = json.loads(msg.data)
            asyncio.ensure_future(self._answer(ws, m))
        self.agents.discard(ws)
        self.subs.pop(ws, None)
        return ws

    async def _answer(self, ws: web.WebSocketResponse, m: Dict[str, Any]) -> None:
        method, params, rid = m.get("method"), m.get("params") or {}, m.get("id")
        try:
            if method == "server.connection.identify":
                result: Any = {"connection_id": id(ws)}
            elif method == "connection.register_remote_method":
                self.agents.add(ws)
                result = "ok"
            elif method == "printer.objects.subscribe":
                self.subs[ws] = params.get("objects") or {}
                result = {"eventtime": 0.0, "status": {k: v for k, v in self.status().items() if k in self.subs[ws]}}
            elif method == "printer.gcode.script":
                await self.run_gcode(params.get("script", ""))
                result = "ok"
            else:
                raise ValueError(f"Method not found: {method}")
            reply = {"jsonrpc": "2.0", "id": rid, "result": result}
        except ValueError as e:
            reply = {"jsonrpc": "2.0", "id": rid, "error": {"code": 400, "message": str(e)}}
        await ws.send_str(json.dumps(reply))

    async def start(self) -> None:
        for g, (ace, k) in enumerate(self.slots):
            self._last_unit[g] = ace.filament_at(k)
        app = web.Application()
        app.router.add_get("/websocket", self._ws)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/websocket"
        self._tasks.append(asyncio.ensure_future(self._tick()))

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for ws in list(self.agents) + list(self.subs):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()
