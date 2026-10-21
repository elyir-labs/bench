#!/usr/bin/env python3
"""The Bench Box's service (docs/bench.md): the printers on the bench, finding more on the Wi-Fi, asking
each one (it says yes on its own screen), and each printer's live intent passed through to the box's page.

  GET    /bench/printers                          the bench: [{id, name, moonraker (through here), app}]
  GET    /bench/found                             printers on the Wi-Fi, and how asking each one stands
  POST   /bench/ask/{id}                          ask one, at its door's home name; the answer is followed here
  POST   /bench/add/{id}                          an Anycubic in LAN mode (or with Rinkhals): the box speaks for it (standin.py)
  DELETE /bench/printers/{id}                     take one off the bench
  GET    /bench/p/{id}/websocket                  its Moonraker websocket, through here
  GET    /bench/p/{id}/server/files/gcodes/{path} its pictures, through here
  GET    /bench/p/{id}/camera                     its camera, if it has one: how it's mounted, and where to see it
  GET    /bench/p/{id}/camera/{stream|snapshot}   the picture itself, through here (the bed question, design/bench-print/)
  /bench/shelf, /bench/printable, /bench/slice/  the models the box keeps, set up for a printer (shelf.py)
  /bench/queue                                   prints waiting for a free printer (bench_queue.py)
  /bench/plan, /bench/plan/print                 several shelf models at once: the plan, then into the queue (plan.py)
  /bench/box                                     the box itself: turn off, restart, make it a printer (box.py)
  /bench/filaments                               your filaments, and Orca's library to add from (filaments.py)
  /bench/phones, /bench/invites, /bench/watching the box's phones and guests from away (away.py)
  GET|POST|DELETE /bench/box/remote              the box's own public name, as a Kobra's (doors.py)

From away the box has its own listener (away.py, --away-port), reached only through Caddy for its public name.

Through here, so a printer's token never reaches a page (a phone at home may open the box), the box's page
works from any of its addresses, and no printer has to trust the page's origin for its live data. The door's
token proves the printer said yes, and keeps the box's addresses current there (they may frame its screens).
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import itertools
import json
import logging
import os
import shutil
import socket
import struct
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from typing import Any, Dict, List, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, WSMsgType, web

import anycubic
from away import AWAY_PORT, Away
from bench_queue import Queue
from box import Box
from filaments import Filaments
from plan import Planner
from doors import BOX, HOME_EVERY, LINK_EVERY, Doors, lan_ip
from shelf import Shelf
from standin import Standin

log = logging.getLogger("bench")

PRINTER_MDNS = "_elyir-printer._tcp.local"   # every printer says so (installer, Announce)
SCAN_EVERY = 10          # seconds a scan of the Wi-Fi is kept
FOLLOW_EVERY = 2         # seconds between looks at an ask
KOBRAS_EVERY = 60        # a Kobra the box speaks for that stopped answering is looked for this often (it may have moved)
ORIGINS_EVERY = 600      # the box's addresses, told to each printer's door again
CAMERAS_FOR = 60         # seconds a printer's camera list is kept
MJPEG = {"mjpegstreamer", "mjpegstreamer-adaptive", "uv4l-mjpeg", ""}   # a stream an <img> can show (app/src/camera)
STANDIN_PORTS = range(8101, 8200)   # a printer the box speaks for has its own port, as a printer's nginx has (8088)
HERE = Path(__file__).resolve().parent
PROFILES = HERE / "profiles"        # the slicing profile for each kind of printer the box speaks for


# ── finding printers: one mDNS question from an ordinary port, which avahi answers straight back ──

def _name(buf: bytes, off: int) -> tuple[str, int]:
    labels, back, hops = [], None, 0
    while True:
        n = buf[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            if back is None:
                back = off + 2
            off, hops = ((n & 0x3F) << 8) | buf[off + 1], hops + 1
            if hops > 30:
                raise ValueError("name loop")
            continue
        labels.append(buf[off + 1:off + 1 + n].decode(errors="replace"))
        off += 1 + n
    return ".".join(labels), back if back is not None else off


def records(buf: bytes) -> list[tuple[str, int, Any]]:
    _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", buf[:12])
    off = 12
    for _ in range(qd):
        _, off = _name(buf, off)
        off += 4
    out: list[tuple[str, int, Any]] = []
    for _ in range(an + ns + ar):
        name, off = _name(buf, off)
        rtype, _, _, size = struct.unpack("!HHIH", buf[off:off + 10])
        off += 10
        data, end = buf[off:off + size], off + size
        if rtype == 12:
            out.append((name, rtype, _name(buf, off)[0]))
        elif rtype == 33:
            out.append((name, rtype, (_name(buf, off + 6)[0], struct.unpack("!HHH", data[:6])[2])))
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


def printers_from(recs: list[tuple[str, int, Any]]) -> list[dict]:
    ptr = [d for n, t, d in recs if t == 12 and n.lower() == PRINTER_MDNS]
    srv = {n: d for n, t, d in recs if t == 33}
    txt = {n: d for n, t, d in recs if t == 16}
    a = {n.lower(): d for n, t, d in recs if t == 1}
    out = {}
    for inst in ptr:
        if inst not in srv:
            continue
        host, port = srv[inst]
        t = txt.get(inst, {})
        pid = t.get("id") or inst.split(".")[0].lower()
        out[pid] = {"id": pid, "name": t.get("name") or inst.split(".")[0], "host": host.rstrip("."), "port": port,
                    "ip": a.get(host.lower()), "door": t.get("door") == "1", "moonraker": int(t.get("moonraker") or 7125)}
    return list(out.values())


def scan(timeout: float = 2.0) -> list[dict]:
    q = struct.pack("!HHHHHH", 0xbe7c, 0, 1, 0, 0, 0) + b"".join(
        bytes([len(p)]) + p.encode() for p in PRINTER_MDNS.split(".")) + b"\0" + struct.pack("!HH", 12, 1)
    recs: list[tuple[str, int, Any]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.25)
        try:
            sock.sendto(q, ("224.0.0.251", 5353))
        except OSError:
            return []
        end = time.time() + timeout
        while time.time() < end:
            try:
                recs += records(sock.recvfrom(9000)[0])
            except (socket.timeout, ValueError, IndexError, struct.error):
                continue
    return printers_from(recs)


def https(address: str) -> str:
    """A door's home name, as a base address (a dev door says http:// itself)."""
    return address.rstrip("/") if "://" in address else f"https://{address.rstrip('/')}"


def own_origins(port: int) -> List[str]:
    """Where the box's screen is served from, as a page's origin: its own display (localhost), its .local
    name, and its address on the Wi-Fi now (asked of the routing table: nothing is sent)."""
    out = [f"http://localhost:{port}", f"http://{socket.gethostname().split('.')[0]}.local:{port}"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            out.append(f"http://{s.getsockname()[0]}:{port}")
    except OSError:
        pass
    return out


class Bench:
    def __init__(self, state: Path, name: str, origins: List[str], scanner=scan, now=time.time, serve_port: int | None = None,
                 slicer: str = "http://127.0.0.1:8095", finder=None, printer_app: Optional[Path] = None,
                 standin_host: str = "0.0.0.0", standin_address: str = "127.0.0.1", doors: Optional[Doors] = None,
                 remote: str = "off", away_port: int = 0, bench_app: Optional[Path] = None, box_name: str = "bench-box"):
        self.state, self.name, self.extra, self.scanner, self.now, self.serve_port = state, name, origins, scanner, now, serve_port
        self.slicer, self.finder, self.printer_app, self.standin_host = slicer, finder, printer_app, standin_host
        self.standin_address = standin_address    # how the box's slicer reaches a stand-in (in containers: this one's name)
        self.standins: Dict[str, tuple] = {}     # id → (Standin, its site's runner)
        self.anycubics: list[dict] = []
        self.doors = doors or Doors(state)
        self.remote = remote          # the box's own `remote`: a Kobra's door opens by itself unless it's off, as a printer's does
        self.anycubic_scanned = 0.0
        self.state.mkdir(parents=True, exist_ok=True)
        self.shelf = Shelf(state / "shelf", slicer, lambda: self.printers, now=now)
        self.queue = Queue(self.shelf, lambda: self.printers, now=now)
        self.plan = Planner(self.shelf, self.queue, lambda: self.printers, now=now)
        self.filaments = Filaments(state, slicer, lambda: self.shelf.session)
        self.away_port, self.box_name = away_port, box_name
        self.away = Away(self, state / "away", bench_app, printer_app, address=lambda: self.doors.relay(BOX).load().get("address"),
                         now=now)
        self.away_runner: Optional[web.AppRunner] = None
        try:
            self.printers: Dict[str, dict] = json.loads((state / "printers.json").read_text())
        except (OSError, ValueError):
            self.printers = {}
        self.found: list[dict] = []
        self.scanned = 0.0
        self.asks: Dict[str, dict] = {}          # id → {state, words, handle, home, at}
        self.cameras: Dict[str, tuple] = {}       # id → (when, the first enabled webcam or None)
        self.session: Optional[ClientSession] = None
        # Every screen on the bench (the box's own, phones at home and away) looks at this every few seconds and reads
        # again when it moves: a change made on one shows on the others. A restart starts a new one.
        self.revs = (int(time.time() * 1000), 0)

    @property
    def rev(self) -> str:
        return "%d-%d" % self.revs

    def changed(self) -> None:
        self.revs = (self.revs[0], self.revs[1] + 1)

    @web.middleware
    async def count_changes(self, request: web.Request, handler):
        resp = await handler(request)
        if request.method in ("POST", "PUT", "DELETE") and request.path.startswith("/bench/") and resp.status < 400:
            self.changed()
        return resp

    async def get_rev(self, request: web.Request) -> web.Response:
        return web.json_response({"rev": self.rev})

    @property
    def origins(self) -> List[str]:
        """The box's addresses now: its own (when it knows the port its screen is on) and any given."""
        own = own_origins(self.serve_port) if self.serve_port else []
        return list(dict.fromkeys([*own, *self.extra]))

    def seed(self, found: List[dict]) -> None:
        """Printers on the bench without asking them (testing, --seed): no door token, so their own screens in the box
        take none, and the box's addresses aren't told to their doors. Their live state and Moonraker are reached directly,
        as on any bench. A printer already on the bench (asked, and said yes) is left as it is."""
        for f in found:
            if f["id"] not in self.printers:
                self.printers[f["id"]] = {"name": f["name"], "host": f.get("ip") or f["host"], "port": f["port"],
                                          "moonraker_port": f.get("moonraker", 7125), "home": None, "token": None, "seeded": True}
                log.info("%s seeded onto the bench (not asked)", f["id"])
        self.save()

    def save(self) -> None:
        tmp = self.state / "printers.tmp"
        tmp.write_text(json.dumps(self.printers, indent=1))
        os.chmod(tmp, 0o600)                      # the doors' tokens
        os.replace(tmp, self.state / "printers.json")
        self.changed()

    # ── http ──

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.count_changes], client_max_size=256 * 1024 * 1024)   # a model, added to the shelf
        app.router.add_get("/bench/rev", self.get_rev)
        app.router.add_get("/bench/printers", self.get_printers)
        app.router.add_get("/bench/intents", self.get_intents)
        app.router.add_get("/bench/found", self.get_found)
        app.router.add_post("/bench/ask/{id}", self.post_ask)
        app.router.add_post("/bench/add/{id}", self.post_add)
        app.router.add_get("/bench/p/{id}/remote", self.get_remote)
        app.router.add_post("/bench/p/{id}/remote", self.post_remote)
        app.router.add_delete("/bench/p/{id}/remote", self.delete_remote)
        app.router.add_delete("/bench/printers/{id}", self.delete_printer)
        app.router.add_get("/bench/p/{id}/websocket", self.ws)
        app.router.add_get("/bench/p/{id}/server/files/gcodes/{path:.*}", self.picture)
        app.router.add_get("/bench/p/{id}/camera", self.camera)
        app.router.add_get("/bench/p/{id}/camera/{kind:stream|snapshot}", self.camera_feed)
        app.router.add_get("/bench/box/remote", self.get_box_remote)
        app.router.add_post("/bench/box/remote", self.post_box_remote)
        app.router.add_delete("/bench/box/remote", self.delete_box_remote)
        self.away.home_routes(app)
        self.shelf.routes(app)
        self.filaments.routes(app)
        self.queue.routes(app)
        self.plan.routes(app)
        app.on_startup.append(self._start)
        app.on_cleanup.append(self._stop)
        return app

    async def _start(self, app: web.Application) -> None:
        self.session = ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=20))
        # the slicer reads a big model, or sends a plate to a printer, for longer than a printer answers
        # a camera's stream runs as long as someone watches it: no total timeout, only a stalled read ends it
        self.feeds = ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=None, sock_connect=5, sock_read=20))
        self.shelf.session = ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=300))
        app["keep"] = asyncio.create_task(self._keep_origins())
        app["kobras"] = asyncio.create_task(self._follow_kobras())
        app["doors"] = asyncio.create_task(self._keep_doors())
        for pid, p in self.printers.items():
            if p.get("standin"):
                await self._speak_for(pid)
        app["gather"] = asyncio.create_task(self.shelf.gather_forever())
        app["queue"] = asyncio.create_task(self.queue.run_forever())
        app["away"] = asyncio.create_task(self.away.run_forever())
        if self.away_port:
            self.away_runner = web.AppRunner(self.away.app(), access_log=None)
            await self.away_runner.setup()
            await web.TCPSite(self.away_runner, "127.0.0.1", self.away_port).start()     # only ever Caddy's, for the box's name
            if self._box_wanted():
                asyncio.create_task(self._open_box())

    async def _stop(self, app: web.Application) -> None:
        for pid in list(self.standins):
            await self._stop_speaking(pid)
        await self.doors.close()
        app["keep"].cancel()
        app["kobras"].cancel()
        app["doors"].cancel()
        app["gather"].cancel()
        app["queue"].cancel()
        app["away"].cancel()
        self.plan.stop()
        if self.away_runner:
            await self.away_runner.cleanup()
        await self.session.close()
        await self.shelf.session.close()
        await self.feeds.close()

    async def get_intents(self, request: web.Request) -> web.Response:
        """Each printer on the bench as it is now, as its own Moonraker says (the queue reads the same): for a page
        that isn't on the box's live connections, a phone asking How would it print? (design/bench-look/, C)."""
        pids = list(self.printers)
        got = await asyncio.gather(*(self.queue._intent(pid, self.printers[pid]) for pid in pids))
        return web.json_response(dict(zip(pids, got)))

    async def get_printers(self, request: web.Request) -> web.Response:
        here = request.host.rsplit(":", 1)[0] if request.host else "localhost"
        return web.json_response([{"id": pid, "name": p["name"], "moonraker": f"/bench/p/{pid}",
                                   # a printer the box speaks for is on the box's own address the page used
                                   "app": f"http://{here if p.get('standin') else p['host']}:{p['port']}"}
                                  for pid, p in self.printers.items()])

    # ── printers the box speaks for (design/bench-kobra/, A) ──

    def _profile(self, pid: str, model: Optional[str]) -> None:
        """Its slicing profile from the box's template for its model: copied when it's added, and again whenever the
        template changes while the profile is still the box's own ("bench": true; one someone wrote is left alone)."""
        template, folder = PROFILES / (model or ""), self.state / "standins" / pid / "elyir-bench-slicer"
        if not model or not (template / "printer.json").is_file():
            return
        try:
            ours = json.loads((folder / "printer.json").read_text()).get("bench") is True
        except (OSError, ValueError):
            ours = not (folder / "printer.json").exists()
        if not ours:
            return
        for src in template.rglob("*"):
            if src.is_file():
                dst = folder / src.relative_to(template)
                if not dst.exists() or dst.read_bytes() != src.read_bytes():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    log.info("%s: slicing profile %s from the box's template", pid, dst.relative_to(folder))

    async def _speak_for(self, pid: str) -> None:
        p = self.printers[pid]
        st = p["standin"]
        self._profile(pid, st.get("model"))
        s = Standin(pid, p["name"], st["printer"], st.get("moonraker_port", 7125), st.get("web_port", 80),
                    self.state / "standins" / pid, self.printer_app, self.slicer, lambda: self.origins,
                    via=st.get("via", "moonraker"), lan_port=st.get("lan_port", 18910))
        runner = web.AppRunner(s.app(), access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, self.standin_host, p["port"]).start()
        except OSError as e:          # its port is taken: that printer is off on the bench, the box carries on
            log.error("%s: can't speak for it on :%d (%s)", pid, p["port"], e)
            await runner.cleanup()
            return
        await s.start()
        s.door_house = lambda: self.doors.house(pid)
        s.secure_link = lambda: self.doors.link(pid)
        s.renamed = lambda name: self._renamed(pid, name)
        self.standins[pid] = (s, runner)
        log.info("%s: the box speaks for it on :%d (%s)", pid, p["port"], st["printer"])
        if self._door_wanted(p):
            why = await self.doors.start(pid, p)
            if why:
                log.warning("%s: no door yet: %s", pid, why)
            else:
                asyncio.create_task(self._home_name(pid))    # now, not at the next 15-minute round: a hub needs it

    async def _home_name(self, pid: str) -> None:
        try:
            why = await self.doors.homecert(pid)
        except Exception:
            log.exception("%s: its name at home", pid)
            return
        if why:
            log.info("%s: no name at home yet: %s", pid, why)

    async def _stop_speaking(self, pid: str) -> None:
        await self.doors.stop(pid)
        s, runner = self.standins.pop(pid, (None, None))
        if s:
            await s.stop()
            await runner.cleanup()

    def _free_port(self) -> Optional[int]:
        used = {p.get("port") for p in self.printers.values() if p.get("standin")}

        def free(port: int) -> bool:
            with socket.socket() as sock:
                try:
                    sock.bind((self.standin_host, port))
                    return True
                except OSError:
                    return False
        return next((port for port in STANDIN_PORTS if port not in used and free(port)), None)

    async def _follow_kobras(self) -> None:
        """No fixed address needed: a Kobra the box can't reach is looked for on the Wi-Fi by its MAC, and spoken
        for at its new address (_scan_anycubic)."""
        while True:
            await asyncio.sleep(KOBRAS_EVERY)
            lost = [pid for pid, (s, _) in self.standins.items() if not s.up.up]
            lost += [pid for pid, p in self.printers.items() if p.get("standin") and pid not in self.standins]
            if lost and self.finder:
                self.anycubic_scanned = 0.0
                try:
                    await self._scan_anycubic()
                except Exception:
                    log.exception("following the Kobras")

    async def _scan_anycubic(self) -> list[dict]:
        if self.finder and self.now() - self.anycubic_scanned > SCAN_EVERY:
            self.anycubic_scanned = self.now()
            try:
                self.anycubics = await self.finder()
            except Exception:
                log.exception("looking for Anycubic printers")
            for f in self.anycubics:              # a Kobra that moved, or had LAN mode turned on or off: speak for it the new way
                p = self.printers.get(f["id"])
                switched = bool(p and p.get("standin") and f.get("via") and p["standin"].get("via", "moonraker") != f["via"])
                if p and p.get("standin") and (p["standin"]["printer"] != f["host"] or switched):
                    p["standin"]["printer"] = f["host"]
                    if switched:
                        p["standin"]["via"] = f["via"]
                    self.save()
                    await self._stop_speaking(f["id"])
                    await self._speak_for(f["id"])
        return self.anycubics

    async def post_add(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        f = next((x for x in await self._scan_anycubic() if x["id"] == pid), None)
        if f is None:
            return web.json_response({"error": f"{pid} isn't on this Wi-Fi right now."}, status=404)
        via = f.get("via") or ("lan" if f.get("lan") else "moonraker" if f.get("rinkhals") else None)
        if not via:
            return web.json_response({"error": f"{f['name']}: {f['why']}."}, status=409)
        if pid not in self.printers:
            taken = {p["name"] for p in self.printers.values()}
            name = f["name"] if f["name"] not in taken else next(f"{f['name']} #{n}" for n in itertools.count(2)
                                                                 if f"{f['name']} #{n}" not in taken)
            port = self._free_port()
            if port is None:
                return web.json_response({"error": f"The box has no free port left to speak for {f['name']} on."}, status=503)
            self.printers[pid] = {"name": name, "host": self.standin_address, "port": port, "moonraker_port": port, "home": None,
                                  "token": None, "joined": self.now(),
                                  "standin": {"printer": f["host"], "moonraker_port": f.get("moonraker_port", 7125),
                                              "web_port": f.get("web_port", 80), "model": f.get("model"), "via": via,
                                              "lan_port": f.get("lan_port", 18910)}}
            self.save()
            await self._speak_for(pid)
            if self._door_wanted(self.printers[pid]):
                asyncio.create_task(self._open_door(pid))
        return web.json_response({"state": "added", "words": f"The box speaks for {self.printers[pid]['name']}."}, status=201)

    async def _scan(self) -> list[dict]:
        if self.now() - self.scanned > SCAN_EVERY:
            self.found = await asyncio.to_thread(self.scanner)
            self.scanned = self.now()
            for f in self.found:                  # a printer that moved: its new address
                p = self.printers.get(f["id"])
                if p and (p["host"], p["port"]) != (f["host"], f["port"]):
                    p.update(host=f["host"], port=f["port"], moonraker_port=f["moonraker"])
                    self.save()
        return self.found

    # ── a door for a printer the box speaks for (bench/doors.py) ──

    def _spoken_for(self, request: web.Request) -> tuple[str, dict]:
        pid = request.match_info["id"]
        p = self.printers.get(pid)
        if not p or not p.get("standin"):
            raise web.HTTPNotFound(text="not a printer this box speaks for")
        return pid, p

    async def _renamed(self, pid: str, name: str) -> None:
        """Called something else on its screen: the bench says so, and its door's notifications do too."""
        p = self.printers.get(pid)
        if not p:
            return
        p["name"] = name
        self.save()
        if self.doors.house(pid) is not None:
            await self.doors.start(pid, p)

    def _door_wanted(self, p: dict) -> bool:
        """Turned on or off for this printer, or the box's own setting (on by default, as a printer's is)."""
        return p["remote"] if isinstance(p.get("remote"), bool) else self.remote != "off"

    async def _open_door(self, pid: str) -> None:
        """Its public name claimed (it stays claimed), its door opened, its name at home got. Never fails: a name it
        can't get yet is asked for again by _keep_doors."""
        p = self.printers.get(pid)
        if not p or pid not in self.standins:
            return
        got, words = await self.doors.claim(pid, public_name(pid), None)
        log.info("%s: %s", pid, words)
        if not got:
            return
        why = await self.doors.start(pid, p)
        if why:
            log.warning("%s: no door yet: %s", pid, why)
            return
        await self.doors.look(pid)
        why = await self.doors.homecert(pid)
        if why:
            log.info("%s: no name at home yet: %s", pid, why)

    async def _keep_doors(self) -> None:
        """Every minute, a door that should be open and isn't is tried again; the relay is asked how each name stands
        every 5 minutes, and the names at home are kept every 15."""
        tick = 0
        while True:
            await asyncio.sleep(60)
            tick += 1
            try:
                if self._box_wanted() and not self.doors.is_open(BOX):
                    await self._open_box()
                elif self.doors.is_open(BOX) and tick % (LINK_EVERY // 60) == 0:
                    await self.doors.look(BOX)
            except Exception:
                log.exception("the box's own door")
            for pid, p in list(self.printers.items()):
                if not p.get("standin") or pid not in self.standins:
                    continue
                try:
                    if self._door_wanted(p) and self.doors.house(pid) is None:
                        await self._open_door(pid)
                    elif self.doors.house(pid) is not None:
                        if tick % (LINK_EVERY // 60) == 0:
                            await self.doors.look(pid)
                        if tick % (HOME_EVERY // 60) == 0:
                            await self.doors.homecert(pid)
                except Exception:
                    log.exception("%s: its door", pid)

    async def get_remote(self, request: web.Request) -> web.Response:
        pid, p = self._spoken_for(request)
        return web.json_response({"on": self._door_wanted(p), **await self.doors.view(pid)})

    async def post_remote(self, request: web.Request) -> web.Response:
        """Turn its door on: {name?, invite?}. Its public name is claimed (or an invite code used on it), then opened."""
        pid, p = self._spoken_for(request)
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        got, words = await self.doors.claim(pid, str(body.get("name") or p["name"]), body.get("invite"))
        if not got:
            return web.json_response({"error": f"{p['name']}: {words}."}, status=502)
        p["remote"] = True
        self.save()
        why = await self.doors.start(pid, p)
        if not why:
            await self.doors.homecert(pid)
        return web.json_response({"on": True, "words": words, "why": why, **await self.doors.view(pid)}, status=200 if not why else 202)

    async def delete_remote(self, request: web.Request) -> web.Response:
        """Close its door; its name stays claimed for when it's turned on again."""
        pid, p = self._spoken_for(request)
        p["remote"] = False
        self.save()
        await self.doors.stop(pid)
        return web.json_response({"on": False})

    # ── the box's own public name (design/bench-remote/, C): claimed and opened as a Kobra's is ──

    def _box_wanted(self) -> bool:
        if not self.away_port:
            return False
        try:
            on = json.loads((self.state / "box" / "remote.json").read_text()).get("on")
        except (OSError, ValueError):
            on = None
        return on if isinstance(on, bool) else self.remote != "off"

    def _box_turned(self, on: bool) -> None:
        d = self.state / "box"
        d.mkdir(parents=True, exist_ok=True)
        (d / "remote.json").write_text(json.dumps({"on": on}))

    async def _open_box(self, invite: Optional[str] = None, name: Optional[str] = None) -> tuple[bool, str, Optional[str]]:
        got, words = await self.doors.claim(BOX, name or self.box_name, invite)
        log.info("the box: %s", words)
        if not got:
            return False, words, None
        why = await self.doors.open_box(self.away_port)
        if why:
            log.warning("the box: no door yet: %s", why)
        else:
            await self.doors.look(BOX)
        return True, words, why

    async def get_box_remote(self, request: web.Request) -> web.Response:
        return web.json_response({"on": self._box_wanted(), **await self.doors.view(BOX)})

    async def post_box_remote(self, request: web.Request) -> web.Response:
        """Turn the box's own door on: {name?, invite?}, as POST /bench/p/{id}/remote does a Kobra's."""
        if not self.away_port:
            return web.json_response({"error": "This box has no away listener (--away-port 0)."}, status=409)
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        got, words, why = await self._open_box(body.get("invite"), str(body.get("name") or "") or None)
        if not got:
            return web.json_response({"error": f"The Bench Box: {words}."}, status=502)
        self._box_turned(True)
        return web.json_response({"on": True, "words": words, "why": why, **await self.doors.view(BOX)}, status=200 if not why else 202)

    async def delete_box_remote(self, request: web.Request) -> web.Response:
        """Close it: the name stays claimed, and every connection from away ends now."""
        self._box_turned(False)
        await self.doors.stop(BOX)
        for pid in list(self.away.sockets) + list(self.away.requests):
            await self.away._cut(pid)
        return web.json_response({"on": False})

    async def get_found(self, request: web.Request) -> web.Response:
        found, kobras = await asyncio.gather(self._scan(), self._scan_anycubic())
        return web.json_response([{**{k: f[k] for k in ("id", "name", "host", "door")}, "on": f["id"] in self.printers,
                                   "ask": {k: v for k, v in self.asks.get(f["id"], {}).items() if k in ("state", "words")} or None}
                                  for f in found] +
                                 [{"id": f["id"], "name": self.printers.get(f["id"], {}).get("name", f["name"]), "host": f["host"],
                                   "door": False, "kind": "anycubic", "on": f["id"] in self.printers, "ask": None,
                                   "why": f["why"], "via": (self.printers.get(f["id"], {}).get("standin") or {}).get("via") or f.get("via"),
                                   "version": f.get("version")} for f in kobras])

    async def post_ask(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        f = next((x for x in await self._scan() if x["id"] == pid), None)
        if f is None:
            return web.json_response({"error": f"{pid} isn't on this Wi-Fi right now."}, status=404)
        if not f["door"]:
            self.asks[pid] = {"state": "no-door", "words": f"{f['name']} has nothing to ask yet: its door is off (remote: off)."}
            return web.json_response(self.asks[pid], status=409)
        try:
            async with self.session.get(f"http://{f['host']}:{f['port']}/door/status") as r:
                home = (await r.json()).get("home_address") if r.status == 200 else None
            if not home:
                raise ValueError("no home name")
            async with self.session.post(f"{https(home)}/door/ask", json={"name": self.name, "kind": "bench", "origins": self.origins}) as r:
                body = await r.json()
                if r.status != 201:
                    raise ValueError(body.get("message") or r.status)
        except (ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
            self.asks[pid] = {"state": "unreachable", "words": f"{f['name']} couldn't be asked ({e})."}
            return web.json_response(self.asks[pid], status=502)
        self.asks[pid] = {"state": "waiting", "words": f"Waiting for a yes on {f['name']}'s screen.", "handle": body["handle"],
                          "home": https(home), "found": f, "at": self.now()}
        asyncio.create_task(self._follow(pid))
        return web.json_response({"state": "waiting", "words": self.asks[pid]["words"]}, status=202)

    async def _follow(self, pid: str) -> None:
        a = self.asks[pid]
        while a.get("state") == "waiting":
            await asyncio.sleep(FOLLOW_EVERY)
            try:
                async with self.session.get(f"{a['home']}/door/ask/{a['handle']}") as r:
                    got = await r.json()
            except (ClientError, OSError, asyncio.TimeoutError, ValueError):
                continue
            state = got.get("state")
            if state == "allowed" and got.get("token"):
                f = a["found"]
                self.printers[pid] = {"name": f["name"], "host": f["host"], "port": f["port"], "moonraker_port": f["moonraker"],
                                      "home": a["home"], "token": got["token"], "joined": self.now()}
                self.save()
                a.update(state="allowed", words=f"{f['name']} said yes.")
                log.info("%s joined the bench", pid)
            elif state in ("refused", "expired"):
                a.update(state=state, words=f"{a['found']['name']} {'said no' if state == 'refused' else 'did not answer'}.")

    async def delete_printer(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        await self._stop_speaking(pid)
        self.printers.pop(pid, None)
        self.asks.pop(pid, None)
        self.save()
        return web.json_response({"gone": pid})

    async def _keep_origins(self) -> None:
        """Tell each printer's door where the box's screen is now (a new address from the router)."""
        while True:
            for pid, p in list(self.printers.items()):
                if not p.get("token"):
                    continue                              # seeded, not asked (--seed): its door doesn't know the box
                for attempt in (1, 2):
                    try:
                        async with self.session.put(f"{p['home']}/door/me/origins", json={"origins": self.origins},
                                                    headers={"Authorization": f"Bearer {p['token']}"}) as r:
                            if r.status == 401:
                                log.warning("%s no longer knows the box (removed on the printer)", pid)
                        break
                    except (ClientError, OSError, asyncio.TimeoutError):
                        # its name at home moved (a new LAN address, or a new public name): ask it, over the Wi-Fi
                        if attempt == 2 or not await self._refresh_home(pid, p):
                            break
            await asyncio.sleep(ORIGINS_EVERY)

    async def _refresh_home(self, pid: str, p: dict) -> bool:
        """The printer's current name at home, from its door over plain http; True when it changed."""
        try:
            async with self.session.get(f"http://{p['host']}:{p['port']}/door/status") as r:
                home = https((await r.json()).get("home_address")) if r.status == 200 else None
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            return False
        if not home or home == p.get("home"):
            return False
        log.info("%s is at %s now", pid, home)
        p["home"] = home
        self.save()
        return True

    # ── a printer's live intent and pictures, through here ──

    def _upstream(self, request: web.Request) -> str:
        p = self.printers.get(request.match_info["id"])
        if not p:
            raise web.HTTPNotFound(text="not on this bench")
        return f"http://{p['host']}:{p.get('moonraker_port', 7125)}"

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        up = self._upstream(request).replace("http://", "ws://") + "/websocket"
        page = web.WebSocketResponse(heartbeat=30)
        await page.prepare(request)
        try:
            async with self.session.ws_connect(up, heartbeat=30) as printer:
                async def to_printer():
                    async for m in page:
                        if m.type == WSMsgType.TEXT:
                            await printer.send_str(m.data)
                    await printer.close()
                pump = asyncio.create_task(to_printer())
                async for m in printer:
                    if m.type == WSMsgType.TEXT:
                        await page.send_str(m.data)
                pump.cancel()
        except (ClientError, OSError, asyncio.TimeoutError):
            pass
        await page.close()
        return page

    async def picture(self, request: web.Request) -> web.StreamResponse:
        url = f"{self._upstream(request)}/server/files/gcodes/{request.match_info['path']}"
        try:
            async with self.session.get(url) as r:
                return web.Response(status=r.status, body=await r.read(), content_type=r.content_type,
                                    headers={"Cache-Control": "max-age=3600"})
        except (ClientError, OSError, asyncio.TimeoutError):
            raise web.HTTPBadGateway()

    # ── a printer's camera, through here: the bed question asks with it (design/bench-print/, A-clear) ──

    async def _webcam(self, pid: str) -> Optional[dict]:
        when, cam = self.cameras.get(pid, (0.0, None))
        if self.now() - when < CAMERAS_FOR:
            return cam
        p = self.printers[pid]
        try:
            async with self.session.get(f"http://{p['host']}:{p.get('moonraker_port', 7125)}/server/webcams/list") as r:
                cams = (await r.json()).get("result", {}).get("webcams", []) if r.status == 200 else []
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            cams = []
        cam = next((c for c in cams if c.get("enabled", True)), None)
        self.cameras[pid] = (self.now(), cam)
        return cam

    def _camera_url(self, pid: str, url: Optional[str]) -> Optional[str]:
        """Where a camera's picture is, from the box: a relative address is the printer's own web server's (it serves
        /webcam/ as Mainsail's does), and localhost in an absolute one means the printer, not the box."""
        if not url:
            return None
        p = self.printers[pid]
        if "://" not in url:
            return urljoin(f"http://{p['host']}:{p['port']}/", url)
        u = urlsplit(url)
        if u.hostname in ("localhost", "127.0.0.1", "::1"):
            u = u._replace(netloc=f"{p['host']}:{u.port}" if u.port else p["host"])
        return urlunsplit(u)

    async def camera(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        if pid not in self.printers:
            raise web.HTTPNotFound(text="not on this bench")
        c = await self._webcam(pid)
        if not c:
            return web.json_response(None)
        live = c.get("stream_url") and (c.get("service") or "") in MJPEG
        return web.json_response({"name": c.get("name"), "rotation": c.get("rotation", 0), "aspect_ratio": c.get("aspect_ratio"),
                                  "flip_horizontal": c.get("flip_horizontal", False), "flip_vertical": c.get("flip_vertical", False),
                                  "stream": f"/bench/p/{pid}/camera/stream" if live else None,
                                  "snapshot": f"/bench/p/{pid}/camera/snapshot" if c.get("snapshot_url") else None})

    async def camera_feed(self, request: web.Request) -> web.StreamResponse:
        pid, kind = request.match_info["id"], request.match_info["kind"]
        if pid not in self.printers:
            raise web.HTTPNotFound(text="not on this bench")
        url = self._camera_url(pid, ((await self._webcam(pid)) or {}).get(f"{kind}_url"))
        if not url:
            raise web.HTTPNotFound(text="no camera")
        try:
            async with self.feeds.get(url) as r:
                if kind == "snapshot" or r.status != 200:
                    return web.Response(status=r.status, body=await r.read(), content_type=r.content_type,
                                        headers={"Cache-Control": "no-store"})
                out = web.StreamResponse(headers={"Content-Type": r.headers.get("Content-Type", "multipart/x-mixed-replace"),
                                                  "Cache-Control": "no-store"})
                await out.prepare(request)
                async for chunk in r.content.iter_any():      # until the page lets go of the picture
                    await out.write(chunk)
                return out
        except (ClientError, OSError, asyncio.TimeoutError, ConnectionResetError):
            raise web.HTTPBadGateway(text="the camera stopped answering")


def public_name(what: str) -> str:
    """A name to ask the relay for, for the box or a printer it speaks for: random-looking and the same every time on
    this box, so nothing anyone called a printer goes into public DNS and the certificate logs (as the installer's)."""
    import base64
    import hashlib
    seed = ""
    for f in ("/etc/machine-id", "/sys/firmware/devicetree/base/serial-number"):
        try:
            seed += Path(f).read_text().strip("\0\n ")
        except OSError:
            pass
    digest = hashlib.sha256(f"elyir-bench name {seed or socket.gethostname()} {what}".encode()).digest()
    return "p-" + base64.b32encode(digest).decode()[:8].lower()


def machine_tag() -> str:
    """Four characters that stay the same on this box, for a name someone else has (as the installer does)."""
    import hashlib
    try:
        mid = Path("/etc/machine-id").read_text().strip()
    except OSError:
        mid = socket.gethostname()
    return hashlib.sha256(mid.encode()).hexdigest()[:4]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=str(Path.home() / "elyir-bench" / "state" / "bench"))
    ap.add_argument("--name", default="Bench Box", help="what a printer's Allow card calls it")
    ap.add_argument("--origin", action="append", default=[], help="an address the box's screen is served from (repeatable)")
    ap.add_argument("--serve-port", type=int, help="the port the box's screen is served on: its own addresses follow from it")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--slicer", default="http://127.0.0.1:8095", help="the box's own slicer (docs/slicer.md)")
    ap.add_argument("--found", help="dev: a JSON list of printers instead of asking the Wi-Fi (the simulator)")
    ap.add_argument("--anycubic", help="dev: a JSON list of Anycubic printers (anycubic.py's form) instead of looking on the Wi-Fi")
    ap.add_argument("--anycubic-net", default=os.environ.get("BENCH_ANYCUBIC_NET") or None,
                    help="where to look for Anycubic printers, e.g. 192.168.1.0/24 (default: the box's own /24; a container's isn't the Wi-Fi)")
    ap.add_argument("--standin-address", default="127.0.0.1",
                    help="how the box's slicer reaches a printer the box speaks for (in containers: this container's name)")
    ap.add_argument("--relay-api", default="https://api.elyir.app", help="the relay a printer the box speaks for claims its name on")
    ap.add_argument("--remote", default=os.environ.get("BENCH_REMOTE") or "off",
                    help="the box's own remote setting: relay opens its own door and one for each Kobra by itself")
    ap.add_argument("--remote-name", default=os.environ.get("BENCH_REMOTE_NAME") or public_name("box"),
                    help="the public name the box asks the relay for (the relay's suggestion when it's taken)")
    ap.add_argument("--away-port", type=int, default=AWAY_PORT, help="the box's away listener, on loopback behind Caddy (0: none)")
    ap.add_argument("--bench-app", help="the Bench app's files, served from away (default: the release's bench-app/)")
    ap.add_argument("--home-port", type=int, default=int(os.environ.get("BENCH_HOME_PORT") or 0),
                    help="where the Kobras' names at home are served (443 on a box; 0: none)")
    ap.add_argument("--home-address", default=os.environ.get("BENCH_HOME_ADDRESS") or None,
                    help="the box's address on the Wi-Fi, which their names at home spell (default: its own; a container's isn't the Wi-Fi)")
    ap.add_argument("--door-bin", default=str(Path.home() / "elyir-bench" / "bin"), help="where the installer keeps caddy and frpc")
    ap.add_argument("--printer-app", help="the printer app a printer the box speaks for is served (default: the release's app/)")
    ap.add_argument("--installer", default=str(Path(__file__).resolve().parents[1] / "installer" / "elyir_bench.py"),
                    help="the installer, for making the box a printer again (box.py)")
    ap.add_argument("--seed", help="testing: put these printers (the --found format) on the bench without asking them, for a "
                    "box whose printers' doors can't take a Bench Box's ask yet (docker/bench-box/)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    scanner = (lambda: json.loads(Path(a.found).read_text())) if a.found else scan
    if a.anycubic:
        async def finder():
            return json.loads(Path(a.anycubic).read_text())
    elif a.anycubic_net:
        net = ipaddress.ip_network(a.anycubic_net, strict=False)

        async def finder():
            return await anycubic.find(network=net)
    else:
        finder = anycubic.find
    app_dir = Path(a.printer_app) if a.printer_app else next((d for d in (HERE.parent / "app", HERE.parent / "app" / "dist")
                                                              if (d / "index.html").is_file()), None)
    bench_dir = Path(a.bench_app) if a.bench_app else next((d for d in (HERE.parent / "bench-app", HERE.parent / "app" / "dist-bench")
                                                           if (d / "index.html").is_file()), None)
    bench = Bench(Path(a.state), a.name, a.origin, scanner=scanner, serve_port=a.serve_port, slicer=a.slicer,
                  finder=finder, printer_app=app_dir, standin_address=a.standin_address,
                  doors=Doors(Path(a.state), a.relay_api, Path(a.door_bin), tag=machine_tag(), home_port=a.home_port,
                              ip=(lambda: a.home_address) if a.home_address else lan_ip),
                  remote=a.remote, away_port=a.away_port, bench_app=bench_dir, box_name=a.remote_name)
    if a.seed:
        bench.seed(json.loads(Path(a.seed).read_text()))
    app = bench.app()
    # the box itself (box.py); a rig (--found, --seed) never turns anything off
    Box(Path(a.state), Path(a.installer), dry=bool(a.found or a.seed)).add_routes(app)
    web.run_app(app, host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
