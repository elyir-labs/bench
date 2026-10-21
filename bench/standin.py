#!/usr/bin/env python3
"""A printer's stand-in on the Bench Box (design/bench-kobra/, A): what a Voron's Pi runs, run here for a printer
that can't run it itself, such as an Anycubic Kobra on Rinkhals (Moonraker in front of Anycubic's own GoKlipper).

One stand-in per printer, each on its own port, serves what a printer's nginx serves on a Pi:

  /                         the printer app (the release's app/), at that printer's own origin
  /websocket                Moonraker's websocket: the intent here, everything else passed to the printer
  /printer/intent[...]      the intent, its actions and check_print, made here by the real engine
  /(printer|api|access|machine|server)/...   the printer's own Moonraker
  /server/files/list?root=config, /server/files/config/elyir-bench-slicer/...
                            its slicing profile, kept on the box (the printer has no folder for it)
  /slice                    the box's slicer, saying which printer asks (X-Elyir-Bench-Printer)
  /webcam/                  the printer's camera
  /door/frames              the box's addresses, so the app takes the box's frame as its parent; no /door/me

To the printer there is one websocket (Rinkhals allows Moonraker five): every page's subscription is merged
into it, and each page gets only what it asked for. Only objects the printer lists are ever subscribed to:
asking GoKlipper for one it doesn't have can bring it down.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import os
import re
import socket
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, WSMsgType, web

HERE = Path(__file__).resolve().parent
for _p in (HERE.parent / "printer", HERE / "printer"):   # the repo, or a release (bench/ and printer/ side by side)
    if _p.is_dir():
        sys.path.insert(0, str(_p))
        break
import elyir_bench_intent as engine  # noqa: E402
from kobra_lan import LanUpstream, RpcError  # noqa: E402
try:
    import elyir_bench_care as care  # noqa: E402
except ImportError:   # pragma: no cover
    care = None

log = logging.getLogger("standin")

SLICER_HEADER = "X-Elyir-Bench-Printer"
PROFILE_DIR = "elyir-bench-slicer"
TICK = 1.0
CARE_EVERY = 60          # ticks between looks at the printer's history and maintenance records
RECONNECT = 5.0          # seconds before trying the printer again
CALL_TIMEOUT = 15.0
CAMERA_EVERY = 60.0      # seconds a look at whether its camera gives a picture is kept

# What GoKlipper can't do, or can't be asked safely (Rinkhals refuses FIRMWARE_RESTART and RESTART: they deadlock it
# until a power cycle). An action never offered can't be pressed; one asked for anyway is refused.
NOT_HERE: Set[str] = {
    "try_again", "restart_firmware", "rescan_units", "stop_now",
    "squish_more", "squish_less", "keep_first_layer", "just_this_once", "first_layer_back", "first_layer_clear",
    "first_layer_keep_old",
    "power_off", "power_restart", "power_keep", "power_now", "power_retry",
    "change_start", "change_out", "change_in", "change_what", "change_good", "change_more", "change_stop",
    "change_retry", "change_end",
    "swap_slot", "swap_start", "move_filament", "feed_assist", "dry_unit", "stop_drying", "carry_on", "carried_ok",
    "load_spool", "unload_spool", "mark_loaded", "dismiss_swap", "head_ok", "colour_choose", "print_planned",
}
WORKS = [
    {"id": "core", "group": "now", "label": "Ready, printing, history, Care"},
    {"id": "print", "group": "now", "label": "Print a model, set up on the Bench Box"},
    {"id": "camera", "group": "now", "label": "Camera"},
    {"id": "squish", "group": "not_here", "label": "Squish the first layer more or less", "note": "Anycubic's firmware"},
    {"id": "change", "group": "not_here", "label": "Change filament from here", "note": "On the printer's own screen"},
]
MOONRAKER_PATHS = ("printer", "api", "access", "machine", "server")


def strip_actions(node: Any, gone: Set[str]) -> Any:
    """The intent without the actions this printer can't take, wherever they sit (Now, a spool, the first layer)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "actions" and isinstance(v, list):
                out[k] = [strip_actions(a, gone) for a in v if not (isinstance(a, dict) and a.get("id") in gone)]
            else:
                out[k] = strip_actions(v, gone)
        return out
    if isinstance(node, list):
        return [strip_actions(v, gone) for v in node]
    return node


def pick(status: Dict[str, Any], wanted: Dict[str, Any]) -> Dict[str, Any]:
    """The part of a status (or a change to one) a page subscribed to: {object: [fields] | None (all)}."""
    out: Dict[str, Any] = {}
    for name, fields in wanted.items():
        if name not in status:
            continue
        obj = status[name]
        if fields is None or not isinstance(obj, dict):
            out[name] = deepcopy(obj)
        else:
            part = {f: deepcopy(obj[f]) for f in fields if f in obj}
            if part:
                out[name] = part
    return out


def merge(into: Dict[str, Any], change: Dict[str, Any]) -> None:
    for name, obj in change.items():
        if isinstance(obj, dict) and isinstance(into.get(name), dict):
            into[name].update(obj)
        else:
            into[name] = deepcopy(obj)


def union(subs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for s in subs:
        for name, fields in s.items():
            if name in out and out[name] is None:
                continue
            if fields is None:
                out[name] = None
            else:
                out[name] = sorted(set(out.get(name) or []) | set(fields))
    return out


class Upstream:
    """One JSON-RPC websocket to the printer's Moonraker, kept open."""

    def __init__(self, url: str, on_notify: Callable[[str, list], Any], on_up: Callable[[], Any],
                 on_down: Callable[[], Any]):
        self.url, self.on_notify, self.on_up, self.on_down = url, on_notify, on_up, on_down
        self.ws = None
        self.ids = itertools.count(1)
        self.waiting: Dict[int, asyncio.Future] = {}
        # Notices are handled in order, apart from the reading: a handler that asks the printer something
        # (a new file's metadata) needs the reading to go on to hear the answer.
        self.notices: asyncio.Queue = asyncio.Queue()

    @property
    def up(self) -> bool:
        return self.ws is not None and not self.ws.closed

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = CALL_TIMEOUT) -> Any:
        if not self.up:
            raise RpcError(503, "The printer isn't answering")
        rid = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[rid] = fut
        try:
            await self.ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": rid}))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.waiting.pop(rid, None)

    async def _handle_notices(self) -> None:
        while True:
            method, params = await self.notices.get()
            try:
                res = self.on_notify(method, params)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.exception("%s: %s", self.url, method)

    async def run(self, session: ClientSession) -> None:
        handler = asyncio.create_task(self._handle_notices())
        try:
            await self._run(session)
        finally:
            handler.cancel()

    async def _run(self, session: ClientSession) -> None:
        while True:
            try:
                async with session.ws_connect(self.url, heartbeat=30, max_msg_size=0) as ws:
                    self.ws = ws
                    log.info("connected to %s", self.url)
                    asyncio.create_task(self.on_up())
                    async for m in ws:
                        if m.type != WSMsgType.TEXT:
                            continue
                        try:
                            msg = json.loads(m.data)
                        except ValueError:
                            continue
                        if "id" in msg and msg["id"] in self.waiting:
                            fut = self.waiting.pop(msg["id"])
                            if not fut.done():
                                if "error" in msg:
                                    err = msg["error"] or {}
                                    fut.set_exception(RpcError(err.get("code", 500), err.get("message", "error")))
                                else:
                                    fut.set_result(msg.get("result"))
                        elif "method" in msg:
                            self.notices.put_nowait((msg["method"], msg.get("params") or []))
            except (ClientError, OSError, asyncio.TimeoutError) as e:
                log.info("%s: %s", self.url, type(e).__name__)
            finally:
                was_up, self.ws = self.ws is not None, None
                for fut in self.waiting.values():
                    if not fut.done():
                        fut.set_exception(RpcError(503, "The printer stopped answering"))
                self.waiting.clear()
                if was_up:
                    await self.on_down()
            await asyncio.sleep(RECONNECT)


class Page:
    """A page's websocket to this stand-in, and what it subscribed to."""

    def __init__(self, ws: web.WebSocketResponse, n: int):
        self.ws, self.n, self.subs = ws, n, {}

    async def send(self, msg: Dict[str, Any]) -> None:
        if not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(msg, default=str))
            except (ConnectionResetError, RuntimeError):
                pass


class Standin:
    def __init__(self, pid: str, name: str, host: str, moonraker_port: int = 7125, web_port: int = 80,
                 state: Optional[Path] = None, app_dir: Optional[Path] = None, slicer: Optional[str] = None,
                 origins: Callable[[], List[str]] = lambda: [], via: str = "moonraker", lan_mqtt=None, lan_port: int = 18910):
        self.id, self.name, self.host = pid, name, host
        self.lan = via == "lan"       # Anycubic's own LAN mode, nothing installed on it (kobra_lan.py); else Rinkhals' Moonraker
        self.moonraker = f"http://{host}:{moonraker_port}"
        self.web = f"http://{host}:{web_port}" if web_port != 80 else f"http://{host}"
        self.state = state
        self.profile = state / PROFILE_DIR if state else None
        self.app_dir, self.slicer, self.origins = app_dir, slicer, origins
        self.door_house: Callable[[], Optional[int]] = lambda: None   # its door's house listener, when the box opened one
        self.secure_link: Callable[[], str] = lambda: "off"           # its public name: off | waiting | on (bench/doors.py)
        self.dismissed: List[str] = []                                 # setup card rows closed with ×, kept on the printer
        self.renamed: Callable[[str], Any] = lambda name: None         # the box keeps a new name (its list, its door)
        self.tracker = engine.IntentTracker(name)
        self.tracker.has_unit = False     # one spool, until Rinkhals reports an ACE Pro (mmu, read by _unit)
        self.notifier = engine.Notifier(f"{pid}{int(time.time())}")
        self.events: List[Dict[str, Any]] = []
        self.status: Dict[str, Any] = {}
        self.objects: List[str] = []
        self.own_subs: Dict[str, Any] = {}
        self.upstream_subs: Dict[str, Any] = {}
        self.pages: Set[Page] = set()
        self.page_ids = itertools.count(1)
        self.last_published: Optional[str] = None
        self.last_filename: Optional[str] = None
        self.care_entries: Dict[str, Any] = {}
        self.ticks = 0
        self.session: Optional[ClientSession] = None
        if self.lan:
            self.up = LanUpstream(host, state or Path(tempfile.mkdtemp()), self._notify, self._printer_up, self._printer_down,
                                  mqtt=lan_mqtt, info_port=lan_port)
        else:
            self.up = Upstream(self.moonraker.replace("http://", "ws://") + "/websocket",
                               self._notify, self._printer_up, self._printer_down)
        self.tasks: List[asyncio.Task] = []
        self.camera_seen: tuple = (0.0, False)    # (when, whether a snapshot came back)

    # ── the printer ──

    async def start(self) -> None:
        self.session = ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=60))
        self.tasks = [asyncio.create_task(self.up.run(self.session)), asyncio.create_task(self._ticker())]

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        for page in list(self.pages):
            await page.ws.close()
        if getattr(self.up, "ws", None) is not None:
            await self.up.ws.close()
        if self.session:
            await self.session.close()

    async def _printer_up(self) -> None:
        try:
            info = await self.up.call("server.info")
        except RpcError:
            return
        state = str((info or {}).get("klippy_state") or "disconnected")
        await self._restore_spool()
        await self._restore_setup()
        if state == "ready":
            await self._klippy_ready()
        else:
            self.tracker.set_klippy_state(state)
            self._publish(force=True)

    async def _printer_down(self) -> None:
        self.tracker.set_klippy_state("disconnected")
        self.upstream_subs = {}
        for page in list(self.pages):        # as when a printer turns off: its pages lose it
            await page.ws.close()

    async def _klippy_ready(self) -> None:
        try:
            listed = await self.up.call("printer.objects.list")
            self.objects = list((listed or {}).get("objects") or [])
        except RpcError:
            self.objects = []
        subs = {k: v for k, v in self.tracker.SUBSCRIBE.items() if k in self.objects}
        chamber = self.tracker.chamber_sensor_name(self.objects)
        if chamber:
            subs[chamber] = ["temperature"]
        if "exclude_object" in self.objects:
            subs["exclude_object"] = None
        head = self.tracker.head_sensor_name(self.objects)
        self.tracker.head_sensor = head
        if head:
            subs[head] = ["filament_detected"]
        self.own_subs = subs
        self.upstream_subs = {}
        await self._subscribe()
        self.tracker.set_klippy_state("ready")
        await self._load_metadata()
        await self._refresh_care()
        self._publish(force=True)

    def _known(self, wanted: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in wanted.items() if k in self.objects}

    async def _subscribe(self) -> None:
        """Ask the printer for everything anyone here wants, when that's grown."""
        want = union([self.own_subs, *[self._known(p.subs) for p in self.pages]])
        if want == self.upstream_subs:
            return
        res = await self.up.call("printer.objects.subscribe", {"objects": want})
        self.upstream_subs = want
        status = (res or {}).get("status") or {}
        merge(self.status, status)
        self.tracker.update_status(deepcopy(status))
        self._unit()

    async def _notify(self, method: str, params: list) -> None:
        if method == "notify_status_update":
            change = params[0] if params and isinstance(params[0], dict) else {}
            merge(self.status, change)
            self.tracker.update_status(deepcopy(change))
            if "mmu" in change or "mmu_machine" in change:
                self._unit()
            for page in list(self.pages):
                part = pick(change, page.subs)
                if part:
                    await page.send({"jsonrpc": "2.0", "method": method, "params": [part, *params[1:]]})
            await self._load_metadata()
            self._drive()
            self._publish()
            return
        if method == "notify_klippy_ready":
            asyncio.create_task(self._klippy_ready())
        elif method == "notify_klippy_shutdown":
            self.tracker.set_klippy_state("shutdown")
            self._publish(force=True)
        elif method == "notify_klippy_disconnected":
            self.tracker.set_klippy_state("disconnected")
            self.upstream_subs = {}
            self._publish(force=True)
        elif method == "notify_gcode_response":
            for line in str(params[0] if params else "").splitlines():
                self.tracker.on_gcode_response(line)
            self._publish()
        for page in list(self.pages):
            await page.send({"jsonrpc": "2.0", "method": method, "params": params})

    def _unit(self) -> None:
        """Rinkhals puts the ACE Pro in every status it sends, as Happy Hare's mmu, asked for or not. The engine
        reads that as it is (filament_units.py) and takes no commands for it."""
        self.tracker.has_unit = engine.filament_units.read(self.status) is not None

    async def _load_metadata(self) -> None:
        filename = (self.status.get("print_stats") or {}).get("filename") or None
        if filename == self.last_filename:
            return
        self.last_filename = filename
        self.tracker.set_metadata(filename, await self._metadata(filename) if filename else None)

    async def _metadata(self, filename: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.up.call("server.files.metadata", {"filename": filename})
        except (RpcError, asyncio.TimeoutError):
            return None

    async def camera_ok(self) -> bool:
        """Rinkhals always lists a webcam; on a Kobra with no camera (or its streamer off) the picture is a 503.
        A printer without a camera lists none, so the bench and the app don't offer one that never shows."""
        when, ok = self.camera_seen
        if self.lan:
            return False                  # its camera is Anycubic's own stream (flv), not a picture the screens show
        if time.monotonic() - when < CAMERA_EVERY:
            return ok
        try:
            async with self.session.get(f"{self.web}/webcam/?action=snapshot", timeout=ClientTimeout(total=5)) as r:
                ok = r.status == 200 and r.content_type.startswith("image/")
        except (ClientError, OSError, asyncio.TimeoutError):
            ok = False
        self.camera_seen = (time.monotonic(), ok)
        return ok

    async def webcams(self, listed: Any) -> Any:
        if isinstance(listed, dict) and listed.get("webcams") and not await self.camera_ok():
            return {**listed, "webcams": []}
        return listed

    # ── records kept in the printer's own Moonraker database, as on a Pi ──

    async def _db_get(self, namespace: str, key: Optional[str], default: Any) -> Any:
        try:
            res = await self.up.call("server.database.get_item", {"namespace": namespace, **({"key": key} if key else {})})
            return (res or {}).get("value", default)
        except (RpcError, asyncio.TimeoutError):
            return default

    async def _db_put(self, namespace: str, key: str, value: Any) -> None:
        await self.up.call("server.database.post_item", {"namespace": namespace, "key": key, "value": value})

    async def _restore_setup(self) -> None:
        kept = await self._db_get("elyir-bench", "setup", {})
        self.dismissed = list((kept or {}).get("dismissed") or []) if isinstance(kept, dict) else []

    async def _restore_spool(self) -> None:
        self.tracker.restore_spool(await self._db_get("elyir-bench", "spool", None))

    async def _save_spool(self) -> None:
        self.tracker.direct_spool_dirty = False
        try:
            await self._db_put("elyir-bench", "spool", self.tracker.direct_spool)
        except (RpcError, asyncio.TimeoutError):
            self.tracker.direct_spool_dirty = True

    async def _totals(self) -> Dict[str, Any]:
        try:
            return dict(((await self.up.call("server.history.totals")) or {}).get("job_totals") or {})
        except (RpcError, asyncio.TimeoutError):
            return {}

    async def _refresh_care(self) -> None:
        """Mainsail's maintenance records and Moonraker's history totals, on the printer, as the component does."""
        if care is None or not self.up.up:
            return
        try:
            totals, now = await self._totals(), time.time()
            if not await self._db_get("elyir-bench", "care_seeded", False):
                for key, entry in care.default_entries(totals, now).items():
                    await self._db_put("maintenance", key, entry)
                await self._db_put("elyir-bench", "care_seeded", True)
            self.care_entries = await self._db_get("maintenance", None, {}) or {}
            snoozes = await self._db_get("elyir-bench", "care_snooze", {}) or {}
            self.tracker.care = care.summary(self.care_entries, totals, now, snoozes)
            self.tracker.phones_notified = bool(int(await self._db_get("elyir-bench", "phones", 0) or 0))
            plates = await self._db_get("elyir-bench", "next_plates", [])
            self.tracker.next_plates = plates if isinstance(plates, list) else []
        except (RpcError, asyncio.TimeoutError):
            log.info("%s: care not read", self.id)

    async def _care_action(self, action: str, eid: str) -> None:
        totals, now = await self._totals(), time.time()
        await self._refresh_care()
        snoozes = await self._db_get("elyir-bench", "care_snooze", {}) or {}
        if action == "care_done":
            for key, entry in care.perform(self.care_entries, eid, totals, now).items():
                await self._db_put("maintenance", key, entry)
            snoozes.pop(eid, None)
        else:
            snoozes[eid] = care.later(eid, totals, now)
        await self._db_put("elyir-bench", "care_snooze", snoozes)
        await self._refresh_care()

    # ── the intent ──

    def intent(self) -> Dict[str, Any]:
        i = strip_actions(self.tracker.intent(), NOT_HERE)
        i["printer"]["advanced_url"] = None if self.lan else self.web + "/"   # LAN mode has no Mainsail on the printer
        i["printer"]["screen_switch"] = False
        i["printer"]["screen_switch_failed"] = None
        i["printer"]["screen_trial"] = None
        i["printer"]["standin"] = "bench"     # spoken for by the Bench Box
        i["setup"] = {"open": self.setup_open()}
        return i

    def _publish(self, force: bool = False) -> None:
        intent = self.intent()
        for event in self.notifier.observe(intent):
            self.events = (self.events + [event])[-50:]
            self._to_pages("notify_elyir_bench_event", [event])
        key = json.dumps({k: v for k, v in intent.items() if k != "now"}, sort_keys=True, default=str)
        if force or key != self.last_published:
            self.last_published = key
            self._to_pages("notify_intent_update", [intent])

    def _to_pages(self, method: str, params: list) -> None:
        for page in list(self.pages):
            asyncio.create_task(page.send({"jsonrpc": "2.0", "method": method, "params": params}))

    def _drive(self) -> None:
        if self.tracker.klippy_state != "ready":
            return
        for kind, script in self.tracker.work():
            if kind == "gcode":
                asyncio.create_task(self._gcode(script))

    async def _gcode(self, script: str) -> None:
        try:
            await self.up.call("printer.gcode.script", {"script": script}, timeout=120)
        except (RpcError, asyncio.TimeoutError) as e:
            log.info("%s: %s: %s", self.id, script, e)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK)
            try:
                if self.ticks % CARE_EVERY == CARE_EVERY - 1:
                    await self._refresh_care()
                if self.tracker.direct_spool_dirty and self.up.up:
                    await self._save_spool()
                self.ticks += 1
                self._drive()
                self._publish()
            except Exception:
                log.exception("%s: tick", self.id)

    async def action(self, action: str, args: Any) -> Dict[str, Any]:
        args = args if isinstance(args, dict) else {}
        log.info("%s: action %s %s", self.id, action, json.dumps(args, default=str))
        if action in ("care_done", "care_later") and care is not None:
            await self._care_action(action, str(args.get("id", "")))
            self._publish(force=True)
            return {"ok": True, "action": action, "ran": [action], "intent": self.intent()}
        if action == "setup_dismiss":
            row = str(args.get("row", ""))
            if row and row not in self.dismissed:
                self.dismissed.append(row)
                await self._db_put("elyir-bench", "setup", {"dismissed": self.dismissed})
            self._publish(force=True)
            return {"ok": True, "action": action, "ran": [action], "intent": self.intent(), "setup": self.setup()}
        if action == "setup_name":
            name = " ".join(str(args.get("name") or "").split())[:40]
            if not name:
                raise RpcError(400, "Give it a name.")
            self.name = self.tracker.printer_name = name
            res = self.renamed(name)
            if asyncio.iscoroutine(res):
                await res
            self._publish(force=True)
            return {"ok": True, "action": action, "ran": [action], "intent": self.intent(), "setup": self.setup()}
        if action in NOT_HERE:
            raise RpcError(400, f"{self.name} can't do that from here.")
        plan = engine.plan_action(action, args, self.tracker)
        if not plan:
            raise RpcError(400, f"Unknown action '{action}'")
        ran = []
        for kind, payload in plan:
            await self._run(kind, payload)
            ran.append(kind)
        self._publish(force=True)
        return {"ok": True, "action": action, "ran": ran, "intent": self.intent()}

    async def _run(self, kind: str, payload: Any) -> None:
        P = engine.ActionPlan
        if kind == P.PAUSE:
            await self.up.call("printer.print.pause")
        elif kind == P.RESUME:
            await self.up.call("printer.print.resume")
        elif kind == P.CANCEL:
            await self.up.call("printer.print.cancel")
        elif kind == P.GCODE:
            if str(payload).lstrip().upper().startswith("ACE_"):
                raise RpcError(400, f"{self.name} can't do that from here.")
            await self.up.call("printer.gcode.script", {"script": str(payload)}, timeout=120)
        elif kind == P.START_LAST:
            filename = (self.status.get("print_stats") or {}).get("filename")
            if filename:
                self.tracker.acknowledge_finished()
                await self.up.call("printer.print.start", {"filename": filename})
        elif kind == P.START_FILE:
            self.tracker.acknowledge_finished()
            await self.up.call("printer.print.start", {"filename": str(payload)})
        elif kind == P.ACK_FINISHED:
            self.tracker.acknowledge_finished()
            if self.lan:
                self.up.ack()             # a free printer after a job says how it ended until this
        elif kind == P.WARM:
            self.tracker.warm_input(payload)
            self._drive()
        elif kind == P.HANDS:   # Move and heat (design/hands-on/): over LAN mode the engine offers heat only
            self.tracker.hands_input(payload)
            self._drive()
        elif kind == P.REMEMBER_SPOOL:
            self.tracker.remember_spool(payload.get("color"), payload.get("material"))
            await self._save_spool()
        elif kind == P.NONE:
            pass
        else:
            raise RpcError(400, f"{self.name} can't do that from here.")

    async def check_print(self, filename: str) -> Dict[str, Any]:
        return engine.check_print(filename, await self._metadata(filename), self.tracker.spools())

    def setup_open(self) -> bool:
        """The phone shows Finish setting up while notifications are there to set up and nobody has (docs/setup-card.md)."""
        return self.secure_link() != "off" and not self.tracker.phones_notified and "notify" not in self.dismissed

    def setup(self) -> Dict[str, Any]:
        return {"name": self.name, "name_from": "you", "secure_link": self.secure_link(),
                "rows": [{"id": "notify"}] if self.secure_link() != "off" else [], "dismissed": self.dismissed,
                "works": {"board": None, "features": WORKS, "include": "off", "include_why": None,
                          "include_text": "", "slicer_lines": None}}

    def profile_view(self) -> Dict[str, Any]:
        return {"state": "yours", "told": True, "using": None, "found": [], "bed_klipper": None}

    # ── a page's websocket ──

    async def answer(self, page: Page, method: str, params: Any) -> Any:
        params = params if isinstance(params, dict) else {}
        if method == "printer.intent":
            return self.intent()
        if method == "printer.intent.action":
            return await self.action(str(params.get("action", "")), params.get("args", {}))
        if method == "printer.intent.check_print":
            return await self.check_print(str(params.get("filename", "")))
        if method == "printer.intent.events":
            boot = self.notifier.boot
            if params.get("boot", boot) != boot:
                return {"boot": boot, "events": []}
            after = int(params.get("after", 0) or 0)
            return {"boot": boot, "events": [e for e in self.events if e["id"] > after]}
        if method == "printer.intent.setup":
            return self.setup()
        if method == "printer.intent.profile":
            return self.profile_view()
        if method == "printer.intent.bring":
            return {"state": "idle", "sources": [], "plan": None, "progress": None, "result": None, "why": None,
                    "found": [], "boards": None, "role": None}
        if method == "server.connection.identify":
            return {"connection_id": page.n}
        if method == "printer.objects.subscribe":
            page.subs = dict(params.get("objects") or {})
            await self._subscribe()
            return {"eventtime": time.monotonic(), "status": pick(self.status, self._known(page.subs))}
        if method == "server.webcams.list":
            return await self.webcams(await self.up.call(method, params))
        if method == "printer.objects.query":
            return await self.up.call(method, {"objects": self._known(dict(params.get("objects") or {}))})
        return await self.up.call(method, params)

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        sock = web.WebSocketResponse(heartbeat=30, protocols=("elyir-bench",))
        await sock.prepare(request)
        if not self.up.up:
            await sock.close()
            return sock
        page = Page(sock, next(self.page_ids))
        self.pages.add(page)
        try:
            async for m in sock:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(m.data)
                except ValueError:
                    continue
                asyncio.create_task(self._reply(page, msg))
        finally:
            self.pages.discard(page)
        return sock

    async def _reply(self, page: Page, msg: Dict[str, Any]) -> None:
        rid = msg.get("id")
        try:
            result = await self.answer(page, str(msg.get("method", "")), msg.get("params"))
            out = {"jsonrpc": "2.0", "result": result, "id": rid}
        except RpcError as e:
            out = {"jsonrpc": "2.0", "error": {"code": e.code, "message": e.message}, "id": rid}
        except asyncio.TimeoutError:
            out = {"jsonrpc": "2.0", "error": {"code": 504, "message": "The printer didn't answer in time"}, "id": rid}
        except Exception as e:
            log.exception("%s: %s", self.id, msg.get("method"))
            out = {"jsonrpc": "2.0", "error": {"code": 500, "message": f"{type(e).__name__}: {e}"}, "id": rid}
        if rid is not None:
            await page.send(out)

    # ── http ──

    def app(self) -> web.Application:
        app = web.Application(client_max_size=1024 * 1024 * 1024)
        app.router.add_get("/websocket", self.ws)
        app.router.add_get("/printer/intent", self.http_intent)
        app.router.add_post("/printer/intent/action", self.http_action)
        app.router.add_get("/printer/intent/check_print", self.http_check)
        app.router.add_get("/door/frames", self.http_frames)
        app.router.add_route("*", "/door/{tail:.*}", self.http_no_door)
        app.router.add_get("/server/files/list", self.http_files_list)
        app.router.add_get("/server/webcams/list", self.http_webcams)
        app.router.add_get("/server/files/config/" + PROFILE_DIR + "/{path:.*}", self.http_profile_file)
        app.router.add_route("*", "/slice{tail:.*}", self.http_slice)
        app.router.add_route("*", "/webcam{tail:.*}", self.http_webcam)
        for p in MOONRAKER_PATHS:
            app.router.add_route("*", f"/{p}/{{tail:.*}}", self.http_moonraker)
        app.router.add_get("/{tail:.*}", self.http_app)
        return app

    def _json(self, result: Any) -> web.Response:
        return web.json_response({"result": result}, dumps=lambda o: json.dumps(o, default=str))

    async def http_intent(self, request: web.Request) -> web.Response:
        if not self.up.up:
            raise web.HTTPServiceUnavailable(text="The printer isn't answering")
        return self._json(self.intent())

    async def http_action(self, request: web.Request) -> web.Response:
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        body = {**dict(request.query), **(body if isinstance(body, dict) else {})}
        args = body.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        try:
            return self._json(await self.action(str(body.get("action", "")), args))
        except RpcError as e:
            return web.json_response({"error": {"code": e.code, "message": e.message}}, status=e.code)

    async def http_check(self, request: web.Request) -> web.Response:
        return self._json(await self.check_print(request.query.get("filename", "")))

    async def http_frames(self, request: web.Request) -> web.Response:
        return web.json_response({"frames": self.origins()})

    async def http_webcams(self, request: web.Request) -> web.Response:
        if self.lan:
            return self._json({"webcams": []})
        try:
            async with self.session.get(f"{self.moonraker}/server/webcams/list") as r:
                listed = (await r.json()).get("result") if r.status == 200 else None
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            listed = None
        if listed is None:
            raise web.HTTPBadGateway(text=f"{self.name} isn't answering")
        return self._json(await self.webcams(listed))

    async def http_no_door(self, request: web.Request) -> web.StreamResponse:
        """Its door's house listener (pairing codes, its phones), as a printer's nginx passes /door/; none: no door here."""
        house = self.door_house()
        if not house:
            raise web.HTTPNotFound(text="no door here: the Bench Box speaks for this printer")
        return await self._proxy(request, f"http://127.0.0.1:{house}{request.rel_url.raw_path_qs}")

    def _profile_files(self) -> List[Dict[str, Any]]:
        if not self.profile or not self.profile.is_dir():
            return []
        out = []
        for f in sorted(self.profile.rglob("*")):
            if f.is_file():
                st = f.stat()
                out.append({"path": f"{PROFILE_DIR}/{f.relative_to(self.profile).as_posix()}", "modified": st.st_mtime,
                            "size": st.st_size, "permissions": "r"})
        return out

    async def http_files_list(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("root", "gcodes") != "config":
            return await self.http_moonraker(request)
        listed: List[Dict[str, Any]] = []
        if self.lan:
            return self._json(self._profile_files())
        try:
            async with self.session.get(f"{self.moonraker}/server/files/list", params={"root": "config"}) as r:
                if r.status == 200:
                    listed = [f for f in ((await r.json()).get("result") or [])
                              if not str(f.get("path", "")).startswith(PROFILE_DIR + "/")]
        except (ClientError, OSError, asyncio.TimeoutError):
            pass
        return self._json(listed + self._profile_files())

    async def http_profile_file(self, request: web.Request) -> web.StreamResponse:
        if not self.profile:
            raise web.HTTPNotFound()
        path = (self.profile / request.match_info["path"]).resolve()
        if not path.is_file() or self.profile.resolve() not in path.parents:
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def _proxy(self, request: web.Request, target: str, headers: Optional[Dict[str, str]] = None,
                     timeout: Optional[ClientTimeout] = None) -> web.StreamResponse:
        hop = {"host", "connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"}
        send = {k: v for k, v in request.headers.items() if k.lower() not in hop}
        send.update(headers or {})
        try:
            async with self.session.request(request.method, target, headers=send, allow_redirects=False,
                                            data=request.content if request.can_read_body else None,
                                            timeout=timeout or ClientTimeout(total=None, sock_connect=5, sock_read=300)) as r:
                resp = web.StreamResponse(status=r.status, headers={k: v for k, v in r.headers.items()
                                                                    if k.lower() not in hop | {"content-encoding"}})
                await resp.prepare(request)
                async for chunk in r.content.iter_any():
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
        except (ClientError, OSError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text=f"{self.name} isn't answering")

    async def http_moonraker(self, request: web.Request) -> web.StreamResponse:
        if self.lan:
            return await self.http_lan(request)
        return await self._proxy(request, self.moonraker + request.rel_url.raw_path_qs)

    async def http_lan(self, request: web.Request) -> web.StreamResponse:
        """Moonraker's HTTP routes over LAN mode: a file sent here is kept on the box and goes to the printer when it starts,
        its pictures are the box's copy, and the rest is the same call as over the websocket."""
        path = request.path.strip("/")
        if path == "server/files/upload" and request.method == "POST":
            return await self.http_lan_upload(request)
        if path.startswith("server/files/gcodes/"):
            pic = (self.up.thumbs / Path(path).name).resolve()
            if path.split("/")[3:4] == [".thumbs"] and pic.is_file() and self.up.thumbs.resolve() in pic.parents:
                return web.FileResponse(pic)
            raise web.HTTPNotFound()
        params: Dict[str, Any] = dict(request.query)
        if request.can_read_body and request.content_type == "application/json":
            try:
                params.update(await request.json())
            except ValueError:
                pass
        if path == "server/database/item":
            method = {"GET": "server.database.get_item", "POST": "server.database.post_item",
                      "DELETE": "server.database.delete_item"}.get(request.method)
        elif path == "printer/objects/query":
            method, params = "printer.objects.query", {"objects": {k: (v.split(",") if v else None) for k, v in request.query.items()}}
        else:
            method = path.replace("/", ".")
        try:
            return self._json(await self.up.call(method or "", params))
        except RpcError as e:
            return web.json_response({"error": {"code": e.code, "message": e.message}}, status=e.code if 400 <= e.code < 600 else 500)

    async def http_lan_upload(self, request: web.Request) -> web.Response:
        name, start, tmp = None, False, None
        reader = await request.multipart()
        async for part in reader:
            if part.name == "file" and part.filename:
                name = Path(part.filename).name
                fd, tmp = tempfile.mkstemp(suffix=".gcode")
                with os.fdopen(fd, "wb") as f:
                    while chunk := await part.read_chunk(1 << 20):
                        f.write(chunk)
            elif part.name == "print":
                start = (await part.text()).strip().lower() == "true"
        if not name or not tmp:
            return web.json_response({"error": {"code": 400, "message": "No file"}}, status=400)
        try:
            kept = self.up.keep(name, Path(tmp))
            if start:
                await self.up.start(kept)
        except RpcError as e:
            return web.json_response({"error": {"code": e.code, "message": e.message}}, status=502)
        finally:
            os.unlink(tmp)
        return web.json_response({"item": {"path": kept, "root": "gcodes"}, "print_started": start, "print_queued": False,
                                  "action": "create_file"}, status=201)

    async def http_webcam(self, request: web.Request) -> web.StreamResponse:
        return await self._proxy(request, self.web + request.rel_url.raw_path_qs)

    async def http_slice(self, request: web.Request) -> web.StreamResponse:
        if not self.slicer:
            return web.json_response({"error": "No slicer here."}, status=503)
        try:
            return await self._proxy(request, self.slicer.rstrip("/") + request.rel_url.raw_path_qs,
                                     headers={SLICER_HEADER: self.id})
        except web.HTTPBadGateway:
            return web.json_response({"error": f"The Bench Box's slicer isn't answering, so it can't slice for {self.name}.",
                                      "slicer": "Bench Box", "off": True}, status=503)

    async def http_app(self, request: web.Request) -> web.StreamResponse:
        if not self.app_dir or not self.app_dir.is_dir():
            raise web.HTTPNotFound(text="No printer app on this box")
        rel = request.match_info["tail"]
        if rel in ("config.json", "elyir-bench.yaml"):
            return app_config(self.app_dir, rel)
        path = (self.app_dir / rel).resolve() if rel else None
        if path and path.is_file() and self.app_dir.resolve() in path.parents:
            immutable = rel.startswith("assets/")
            return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"} if immutable else {})
        return web.FileResponse(self.app_dir / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


def app_config(app_dir: Path, rel: str) -> web.Response:
    """The app's own settings, with no fixed printer in them: it talks to whoever served it (a stand-in, or the box
    from away)."""
    try:
        text = (app_dir / rel).read_text()
    except OSError:
        raise web.HTTPNotFound()
    if rel == "config.json":
        try:
            c = json.loads(text)
            c.setdefault("moonraker", {})["host"] = ""
            return web.json_response(c, headers={"Cache-Control": "no-store"})
        except ValueError:
            raise web.HTTPNotFound()
    return web.Response(text=re.sub(r"(?m)^(  host:).*$", r"\1 ''", text, count=1), content_type="text/yaml",
                        headers={"Cache-Control": "no-store"})


async def serve(standins: List[tuple]) -> List[web.AppRunner]:
    """Start each (Standin, host, port) and its site."""
    runners = []
    for s, host, port in standins:
        await s.start()
        runner = web.AppRunner(s.app())
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        runners.append(runner)
        log.info("%s (%s) speaks for %s on :%d", s.id, s.name, f"{s.host} over LAN mode" if s.lan else s.moonraker, port)
    return runners


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--printer", required=True, help="the printer's address (its Moonraker answers on --moonraker-port)")
    ap.add_argument("--moonraker-port", type=int, default=7125)
    ap.add_argument("--web-port", type=int, default=80, help="where its camera is (Rinkhals: port 80)")
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--state", help="this printer's folder on the box: elyir-bench-slicer/ is its slicing profile")
    ap.add_argument("--app", help="the printer app to serve (a release's app/, or app/dist)")
    ap.add_argument("--slicer", help="the box's slicer, e.g. http://127.0.0.1:8095")
    ap.add_argument("--origin", action="append", default=[], help="an address of the box's screen (repeatable)")
    ap.add_argument("--via", choices=("moonraker", "lan"), default="moonraker", help="Rinkhals' Moonraker, or Anycubic's own LAN mode")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8101)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = Standin(a.id, a.name, a.printer, a.moonraker_port, a.web_port, Path(a.state) if a.state else None,
                Path(a.app) if a.app else None, a.slicer, lambda: a.origin, via=a.via)

    async def run() -> None:
        await serve([(s, a.host, a.port)])
        await asyncio.Event().wait()
    asyncio.run(run())


if __name__ == "__main__":
    main()
