"""The Bench Box from away (design/bench-remote/, C; docs/bench.md "From away").

The box has its own public name on the relay, and in front of it this listener, on loopback, reached only through
Caddy for that name: everything on it is from outside (as door.py's away listener). Which listener a request
arrives on is the whole of how the box knows where it came from; no header is trusted for that.

  phones   paired at the box (Care, Phones, Add a phone: a ten-minute code, once). The whole bench, each printer's
           away list (door.py allowed_call), add to the queue (it waits for someone at home), plan several shelf models
           and add the plan to the queue (plan.py), invite someone.
  guests   invited by a paired phone or at the box: a one-use link, unopened it ends after a day. reach "watch"
           (watching calls only) or "step_in" (the away list), until a day or a week from the invite, or removed.

Nobody away starts a print, heats, moves, sends G-code, or touches files, spools or machine.*. The box's own tokens
for each printer stay here: upstream is each printer's Moonraker as the box reaches it at home.

A printer's own screens open through the box at /screens/<id>/: its app (the release's app/), its websocket filtered as
above, its thumbnails and camera, and a /door/me for that printer saying what this caller may do there.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from aiohttp import ClientError, WSCloseCode, WSMsgType, web

HERE = Path(__file__).resolve().parent
for _p in (HERE.parent / "door", HERE / "door"):
    if (_p / "door.py").is_file():
        sys.path.insert(0, str(_p))
        break
import door as D  # noqa: E402
from standin import app_config  # noqa: E402

log = logging.getLogger("bench.away")

AWAY_PORT = 8189
INVITE_LIFE = 86400            # an invite nobody opened stops working after a day
LASTS = {"day": 86400, "week": 7 * 86400, "removed": None}
REACH = ("watch", "step_in")
SWEEP_EVERY = 30               # ended guests are let go, and their open connections closed, this often
OPEN = {"/door/me", "/door/pair", "/door/join", "/door/join/look", "/door/frames"}
PRINTER = re.compile(r"^/screens/([^/]+)(/.*)?$")
NO = "That isn't possible from away."


def no(words: str = NO, status: int = 403, detail: str = "away") -> web.Response:
    return web.json_response({"detail": detail, "message": words, "error": words}, status=status)


def acts(p: dict) -> bool:
    return p.get("kind") != "guest" or p.get("reach") == "step_in"


def is_guest(p: Optional[dict]) -> bool:
    return bool(p) and p.get("kind") == "guest"


class Invites:
    """Links a paired phone (or the box) sends: one use, a day to open it. Only the code's hash is kept."""

    def __init__(self, path: Path, now=time.time):
        self.path, self.now = path, now
        try:
            self.items: List[dict] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.items = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def _sweep(self) -> None:
        left = [i for i in self.items if i["expires"] > self.now()]
        if len(left) != len(self.items):
            self.items = left
            self.save()

    def new(self, reach: str, lasts: str, by: str) -> tuple[dict, str]:
        self._sweep()
        code = secrets.token_urlsafe(18)
        made = self.now()
        inv = {"id": secrets.token_hex(6), "code": D._hash(code), "reach": reach, "lasts": lasts, "invited_by": by,
               "made": made, "expires": made + INVITE_LIFE, "until": None if LASTS[lasts] is None else made + LASTS[lasts]}
        self.items.append(inv)
        self.save()
        return inv, code

    def look(self, code: str) -> Optional[dict]:
        self._sweep()
        h = D._hash(code or "")
        return next((i for i in self.items if hmac.compare_digest(i["code"], h)), None)

    def take(self, code: str) -> Optional[dict]:
        inv = self.look(code)
        if inv:
            self.items.remove(inv)
            self.save()
        return inv

    def cancel(self, inv_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i["id"] != inv_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def live(self) -> List[dict]:
        self._sweep()
        return list(self.items)

    @staticmethod
    def public(i: dict) -> dict:
        return {k: i[k] for k in ("id", "reach", "lasts", "invited_by", "made", "expires", "until")}


class Away:
    def __init__(self, bench, state: Path, bench_app: Optional[Path] = None, printer_app: Optional[Path] = None,
                 address: Callable[[], Optional[str]] = lambda: None, now=time.time):
        state.mkdir(parents=True, exist_ok=True)
        self.bench, self.bench_app, self.printer_app, self.address, self.now = bench, bench_app, printer_app, address, now
        self.phones = D.Phones(state / "phones.json", now)
        self.codes = D.Codes(now)
        self.invites = Invites(state / "invites.json", now)
        self.sockets: Dict[str, Set[web.WebSocketResponse]] = defaultdict(set)
        self.requests: Dict[str, Set[asyncio.BaseTransport]] = defaultdict(set)   # each one's open connections

    # ── who is asking ──

    def origin(self, request: web.Request) -> str:
        host = request.headers.get("X-Forwarded-Host") or request.host
        return f"{request.headers.get('X-Forwarded-Proto') or request.scheme}://{host}"

    def watching(self, pid: str) -> int:
        return len(self.sockets.get(pid) or ())

    def public(self, p: dict) -> dict:
        return {**D.Phones.public(p), "kind": p.get("kind") or "phone", "watching": self.watching(p["id"])}

    def me_of(self, p: Optional[dict]) -> dict:
        if not p:
            return {"paired": False, "role": "away", "away": True, "kind": None, "reach": None, "until": None, "name": None,
                    "actions": [], "may": {"queue": False, "invite": False}}
        guest = is_guest(p)
        return {"paired": True, "role": "away", "away": True, "kind": "guest" if guest else "phone",
                "reach": p.get("reach") if guest else "step_in", "until": p.get("until"), "name": p["name"],
                "invited_by": p.get("invited_by"), "phone": self.public(p),
                "actions": sorted(D.AWAY_ACTIONS) if acts(p) else [], "may": {"queue": not guest, "invite": not guest}}

    # ── the away listener ──

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._gate, self.bench.count_changes], client_max_size=256 * 1024 ** 2)   # a model sent to look at
        app.on_response_prepare.append(self._headers)
        r = app.router
        r.add_get("/door/me", self.me)
        r.add_get("/door/frames", self.frames)
        r.add_post("/door/pair", self.pair)
        r.add_post("/door/join/look", self.join_look)
        r.add_post("/door/join", self.join)
        r.add_get("/door/invites", self.list_invites)
        r.add_post("/door/invites", self.make_invite)
        r.add_delete("/door/invites/{id}", self.cancel_invite)
        r.add_route("*", "/door/{tail:.*}", self.at_box)
        r.add_get("/bench/printers", self.printers)
        b = self.bench
        r.add_get("/bench/rev", b.get_rev)
        # what the box's own screen reads, answered by the same handlers
        for path, handler in (("/bench/shelf", b.shelf.get_shelf), ("/bench/shelf/{id}/picture", b.shelf.get_picture),
                              ("/bench/shelf/{id}/parts/{n}", b.shelf.get_part), ("/bench/printable", b.shelf.get_printable),
                              ("/bench/slice-options", b.shelf.get_options), ("/bench/usual/{printer}", b.shelf.get_usual),
                              ("/bench/queue", b.queue.get_queue), ("/bench/filaments", b.filaments.get),
                              ("/bench/p/{id}/camera", b.camera), ("/bench/p/{id}/camera/{kind:stream|snapshot}", b.camera_feed)):
            r.add_get(path, handler)
        r.add_post("/bench/queue", self.queue_add)
        r.add_post("/bench/plan", self._phones(b.plan.post_plan))
        r.add_post("/bench/plan/print", self.plan_add)
        # How would it print? from the Printers app (design/bench-look/, C): a model sent to look at, set up for each
        # printer and its layers read; nothing is sent to a printer from here. Phones only, never guests.
        for method, path, handler in (("POST", "/bench/look", b.shelf.post_look), ("PUT", "/bench/shelf/{id}/keep", b.shelf.put_keep),
                                      ("POST", "/bench/shelf/{id}/slice", b.shelf.post_slice), ("GET", "/bench/slice/{job}", b.shelf.get_job),
                                      ("DELETE", "/bench/slice/{job}", b.shelf.cancel), ("GET", "/bench/slice/{job}/layers", b.shelf.get_layers),
                                      ("GET", "/bench/slice/{job}/layers/{n}", b.shelf.get_layers), ("GET", "/bench/intents", b.get_intents)):
            r.add_route(method, path, self._phones(handler))
        r.add_get("/bench/p/{id}/websocket", self.websocket)
        r.add_get("/bench/p/{id}/server/files/gcodes/{path:.*}", self.thumb)
        r.add_route("*", "/bench/{tail:.*}", self.refuse)
        r.add_route("*", "/screens/{id}/{tail:.*}", self.printer)
        r.add_route("*", "/screens/{id}", self.printer)
        r.add_route("*", "/{tail:.*}", self.files)
        return app

    def _phones(self, handler):
        async def only(request: web.Request) -> web.StreamResponse:
            return self._phone_only(request, "Only the people the bench belongs to look at models here.") or await handler(request)
        return only

    async def _headers(self, request: web.Request, response: web.StreamResponse) -> None:
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        origin = request.headers.get("Origin")
        if origin in D.SHELL_ORIGINS:          # the Printers app, with a phone's token (design/bench-look/, C)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"

    @web.middleware
    async def _gate(self, request: web.Request, handler):
        path = request.path
        origin = request.headers.get("Origin")
        if request.method == "OPTIONS":
            if origin not in D.SHELL_ORIGINS:
                return web.Response(status=403)
            h = {"Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS", "Access-Control-Allow-Headers": "Authorization, Content-Type",
                 "Access-Control-Max-Age": "600"}
            if request.headers.get("Access-Control-Request-Private-Network"):
                h["Access-Control-Allow-Private-Network"] = "true"
            return web.Response(status=204, headers=h)
        request["phone"] = phone = self.phones.identify(D.Door.token_of(request))
        if origin and (request.method not in ("GET", "HEAD") or path.endswith("/websocket")) and origin not in D.SHELL_ORIGINS:
            if origin.split("://", 1)[-1] != request.headers.get("X-Forwarded-Host", request.host):
                return web.json_response({"detail": "origin"}, status=403)
        m = PRINTER.match(path)
        rest = (m.group(2) or "/") if m else path
        api = path.startswith(("/bench/", "/door/")) or (m and rest.startswith(D.API_PREFIXES))
        if not phone:
            if api and rest not in OPEN:
                return web.json_response({"detail": "phone", "message": "This bench isn't open from here."}, status=401)
            return await handler(request)
        self.phones.seen(phone)
        t = request.transport
        if t:
            self.requests[phone["id"]].add(t)
        try:
            return await handler(request)
        finally:
            self.requests.get(phone["id"], set()).discard(t)

    async def refuse(self, request: web.Request) -> web.Response:
        return no()

    async def at_box(self, request: web.Request) -> web.Response:
        return no("Phones are added on the Bench Box.")

    async def me(self, request: web.Request) -> web.Response:
        return web.json_response({**self.me_of(request["phone"]), "box": {"name": self.bench.name, "address": self.address()}})

    async def frames(self, request: web.Request) -> web.Response:
        return web.json_response({"frames": [self.origin(request)]})

    def _cookie(self, r: web.Response, token: str) -> web.Response:
        r.set_cookie(D.COOKIE, token, max_age=10 * 365 * 86400, httponly=True, secure=True, samesite="Lax", path="/")
        return r

    async def _body(self, request: web.Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    async def pair(self, request: web.Request) -> web.Response:
        who = D.Door.who(request)
        wait = self.codes.wait(who)
        if wait > 0:
            return no(f"Too many tries. Wait {int(wait) + 1} seconds.", 429, "wait")
        body = await self._body(request)
        if not self.codes.take(str(body.get("code") or ""), who):
            return no("That code didn't work. Get a new one from the Bench Box.", 401, "code")
        phone, token = self.phones.pair(str(body.get("name") or ""))
        log.info("paired %s from %s", phone["name"], who)
        return self._cookie(web.json_response({"paired": True, "phone": self.public(phone), "token": token,
                                               "box": {"name": self.bench.name, "address": self.address()}}), token)

    async def _invite_of(self, request: web.Request, body: dict, take: bool) -> tuple[Optional[dict], Optional[web.Response]]:
        who = D.Door.who(request)
        wait = self.codes.wait(who)
        if wait > 0:
            return None, no(f"Too many tries. Wait {int(wait) + 1} seconds.", 429, "wait")
        code = str(body.get("code") or "")
        inv = self.invites.take(code) if take else self.invites.look(code)
        if not inv:
            self.codes.tries[who].append(self.now())
            return None, no("This link doesn't work any more. Ask for a new one.", 401, "code")
        return inv, None

    async def join_look(self, request: web.Request) -> web.Response:
        """What a link offers, before the guest gives a name: who invited them, what they can do, until when."""
        inv, refused = await self._invite_of(request, await self._body(request), take=False)
        if refused:
            return refused
        return web.json_response({"box": {"name": self.bench.name}, **{k: inv[k] for k in ("invited_by", "reach", "until")}})

    async def join(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        name = " ".join(str(body.get("name") or "").split())
        if not name:
            return no("Say your name: the person who invited you sees it.", 400, "name")
        inv, refused = await self._invite_of(request, body, take=True)
        if refused:
            return refused
        guest, token = self.phones.pair(name, "guest", guest={"reach": inv["reach"], "until": inv["until"],
                                                               "invited_by": inv["invited_by"]})
        log.info("%s joined (%s, invited by %s) from %s", guest["name"], inv["reach"], inv["invited_by"], D.Door.who(request))
        return self._cookie(web.json_response({**self.me_of(guest), "token": token,
                                               "box": {"name": self.bench.name, "address": self.address()}}), token)

    def _phone_only(self, request: web.Request, words: str) -> Optional[web.Response]:
        return no(words) if is_guest(request["phone"]) else None

    async def list_invites(self, request: web.Request) -> web.Response:
        refused = self._phone_only(request, "Only the people the bench belongs to see its invites.")
        return refused or web.json_response({"invites": [Invites.public(i) for i in self.invites.live()]})

    async def make_invite(self, request: web.Request) -> web.Response:
        refused = self._phone_only(request, "Guests can't invite anyone.")
        return refused or await self._new_invite(await self._body(request), request["phone"]["name"])

    async def _new_invite(self, body: dict, by: str) -> web.Response:
        reach, lasts = body.get("reach") or "watch", body.get("lasts") or "day"
        if reach not in REACH or lasts not in LASTS:
            return no("Send {reach: watch | step_in, lasts: day | week | removed}.", 400, "invite")
        address = self.address()
        if not address:
            return no("The Bench Box isn't reachable from outside yet.", 409, "off")
        inv, code = self.invites.new(reach, lasts, by)
        log.info("an invite (%s, %s) made by %s", reach, lasts, by)
        return web.json_response({**Invites.public(inv), "code": code, "url": f"https://{address}/join#{code}"}, status=201)

    async def cancel_invite(self, request: web.Request) -> web.Response:
        refused = self._phone_only(request, "Guests can't change invites.")
        if refused:
            return refused
        if not self.invites.cancel(request.match_info["id"]):
            raise web.HTTPNotFound()
        return web.Response(status=204)

    # ── the bench, read from away ──

    async def printers(self, request: web.Request) -> web.Response:
        """The bench without anything secret: no printer's token, address or ports."""
        base = self.origin(request)
        return web.json_response([{"id": pid, "name": p["name"], "moonraker": f"/bench/p/{pid}", "app": f"{base}/screens/{pid}"}
                                  for pid, p in self.bench.printers.items()])

    async def queue_add(self, request: web.Request) -> web.StreamResponse:
        """A paired phone adds to the queue. It is set up for a free printer like any other, and starts only when
        someone at home taps It's clear: the start route isn't on this listener at all."""
        refused = self._phone_only(request, "Only the people the bench belongs to add to its queue.")
        if refused:
            return refused
        request["by"] = request["phone"]["name"]
        return await self.bench.queue.post_queue(request)

    async def plan_add(self, request: web.Request) -> web.StreamResponse:
        """Several shelf models at once from away: Print all becomes Add to the queue. Nothing starts from here."""
        refused = self._phone_only(request, "Only the people the bench belongs to add to its queue.")
        if refused:
            return refused
        request["by"] = request["phone"]["name"]
        return await self.bench.plan.post_print(request)

    async def thumb(self, request: web.Request) -> web.StreamResponse:
        return await self._thumb(self._printer(request.match_info["id"]), "/server/files/gcodes/" + request.match_info["path"])

    async def _thumb(self, p: dict, path: str) -> web.StreamResponse:
        """A job's picture, and nothing else under gcodes: from away no G-code file is handed out."""
        if not D.THUMB.match(path):
            return no()
        try:
            async with self.bench.session.get(f"http://{p['host']}:{p.get('moonraker_port', 7125)}{path}") as r:
                return web.Response(status=r.status, body=await r.read(), content_type=r.content_type,
                                    headers={"Cache-Control": "max-age=3600"})
        except (ClientError, OSError, asyncio.TimeoutError):
            raise web.HTTPBadGateway()

    # ── a printer's websocket, with the away list per caller ──

    def _printer(self, pid: str) -> dict:
        p = self.bench.printers.get(pid)
        if not p:
            raise web.HTTPNotFound(text="not on this bench")
        return p

    async def websocket(self, request: web.Request, pid: Optional[str] = None) -> web.WebSocketResponse:
        pid = pid or request.match_info["id"]
        p, phone = self._printer(pid), request["phone"]
        up_url = f"ws://{p['host']}:{p.get('moonraker_port', 7125)}/websocket"
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024, protocols=(D.WS_PROTOCOL,))
        await ws.prepare(request)
        self.sockets[phone["id"]].add(ws)
        act = acts(phone)
        who = f"{phone['name']}, away ({'guest' if is_guest(phone) else 'paired phone'}, through the Bench Box)"
        try:
            async with self.bench.session.ws_connect(up_url, heartbeat=30, max_msg_size=8 * 1024 * 1024) as up:
                async def down():
                    async for msg in up:
                        if msg.type != WSMsgType.TEXT:
                            continue
                        try:
                            data = json.loads(msg.data)
                        except ValueError:
                            continue
                        if "method" in data and data["method"] not in D.NOTIFY:
                            continue
                        if data.get("method") == "notify_agent_event":
                            ev = (data.get("params") or [{}])[0]
                            if not isinstance(ev, dict) or ev.get("agent") != "elyir-bench-door":
                                continue
                        await ws.send_str(msg.data)
                    await ws.close()
                pump = asyncio.create_task(down())
                try:
                    async for msg in ws:
                        if msg.type != WSMsgType.TEXT:
                            continue
                        try:
                            data = json.loads(msg.data)
                        except ValueError:
                            continue
                        if not isinstance(data, dict) or not isinstance(data.get("method"), str):
                            continue
                        why = D.allowed_call(data["method"], data.get("params"), act)
                        if why:
                            log.info("refused %s on %s from %s", data["method"], pid, phone["name"])
                            if "id" in data:
                                await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": data["id"], "error": {"code": 403, "message": why}}))
                            continue
                        if data["method"] == "printer.intent.action" and isinstance(data.get("params"), dict):
                            data["params"]["source"] = who
                        await up.send_str(json.dumps(data))
                finally:
                    pump.cancel()
        except (ClientError, OSError, asyncio.TimeoutError):
            pass
        finally:
            self.sockets[phone["id"]].discard(ws)
            if not self.sockets[phone["id"]]:
                self.sockets.pop(phone["id"], None)
        await ws.close()
        return ws

    # ── a printer's own screens, through the box (/screens/<id>/) ──

    async def printer(self, request: web.Request) -> web.StreamResponse:
        pid = request.match_info["id"]
        rest = "/" + request.match_info.get("tail", "")
        phone = request["phone"]
        if rest == "/websocket":
            return await self.websocket(request, pid)
        if rest == "/door/me":
            me = self.me_of(phone)
            p = self._printer(pid) if phone else None
            return web.json_response({"paired": me["paired"], "role": "away", "away": True,
                                      "printer": {"id": pid, "name": p["name"]} if p else None,
                                      "addresses": {"away": f"{self.origin(request)}/screens/{pid}", "home": None},
                                      "phone": me.get("phone"), "actions": me["actions"], "kind": me["kind"],
                                      "reach": me["reach"], "frames": [self.origin(request)]})
        if rest == "/door/frames":
            return await self.frames(request)
        if rest == "/door/pair":
            return await self.pair(request)
        if rest.startswith("/door/"):
            return no("Phones are added on the Bench Box.")
        if rest == "/slice" or rest.startswith("/slice/"):
            return no("Printing a model isn't possible from away yet.")
        if request.method not in ("GET", "HEAD"):
            return no()
        if rest.startswith("/webcam"):
            return await self._camera(request, self._printer(pid), rest)
        if D.THUMB.match(rest):
            return await self._thumb(self._printer(pid), rest)
        if rest.startswith(D.API_PREFIXES):
            return no()
        if rest in ("/config.json", "/elyir-bench.yaml") and self.printer_app:
            return app_config(self.printer_app, rest[1:])
        return self._file(self.printer_app, rest, index=lambda: self._printer_index(pid))

    async def _camera(self, request: web.Request, p: dict, rest: str) -> web.StreamResponse:
        """/webcam/ as the printer's own web server serves it (Mainsail's way), as a printer's door passes it on."""
        url = f"http://{p['host']}:{p['port']}{rest}{D.forward_query(request)}"
        try:
            async with self.bench.feeds.get(url) as r:
                out = web.StreamResponse(status=r.status, headers={"Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
                                                                   "Cache-Control": "no-store"})
                await out.prepare(request)
                async for chunk in r.content.iter_any():
                    await out.write(chunk)
                return out
        except (ClientError, OSError, asyncio.TimeoutError, ConnectionResetError):
            raise web.HTTPBadGateway(text="the camera stopped answering")

    def _printer_index(self, pid: str) -> web.Response:
        """The printer app's page, told where it is: its API calls go under /screens/<id>/ (app/src/base.ts)."""
        html = (self.printer_app / "index.html").read_text()
        base = json.dumps(f"/screens/{pid}").replace("<", "\\u003c")
        html = html.replace("<head>", f"<head><script>window.__ELYIR_BENCH_BASE__={base}</script>", 1)
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    # ── the Bench app's own files ──

    async def files(self, request: web.Request) -> web.StreamResponse:
        if request.method not in ("GET", "HEAD"):
            return no()
        rest = request.path
        # a printer's screens (/screens/<id>/) load their chunks, fonts and icons from the root
        shared = self.printer_app if rest.startswith(("/assets/", "/fonts/", "/icons/")) else None
        return self._file(self.bench_app, rest, fallback=shared)

    @staticmethod
    def _find(root: Optional[Path], rest: str) -> Optional[Path]:
        if not root:
            return None
        f = (root / rest.lstrip("/")).resolve()
        try:
            f.relative_to(root.resolve())
        except ValueError:
            return None
        return f if f.is_file() else None

    def _file(self, root: Optional[Path], rest: str, index: Optional[Callable[[], web.Response]] = None,
              fallback: Optional[Path] = None) -> web.StreamResponse:
        f = self._find(root, rest) or self._find(fallback, rest)
        if f and f.name != "index.html":
            immutable = "/assets/" in rest
            return web.FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        if "." in rest.rsplit("/", 1)[-1] and not rest.endswith("index.html"):
            raise web.HTTPNotFound()
        if index:
            return index()
        if not root or not (root / "index.html").is_file():
            raise web.HTTPNotFound(text="the Bench app isn't here")
        return web.FileResponse(root / "index.html", headers={"Cache-Control": "no-store"})

    # ── at home: the box's own screen (Care, Phones) ──

    def home_routes(self, app: web.Application) -> None:
        r = app.router
        r.add_get("/bench/phones", self.home_list)
        r.add_post("/bench/phones/code", self.home_code)
        r.add_delete("/bench/phones/{id}", self.home_remove)
        r.add_post("/bench/invites", self.home_invite)
        r.add_delete("/bench/invites/{id}", self.home_cancel)
        r.add_get("/bench/watching", self.home_watching)

    def guests_watching(self) -> List[str]:
        return [p["name"] for p in self.phones.items if is_guest(p) and self.watching(p["id"]) and not self.phones.ended(p)]

    async def home_list(self, request: web.Request) -> web.Response:
        await self.sweep()
        items = [self.public(p) for p in self.phones.items]
        return web.json_response({"address": self.address(),
                                  "phones": [p for p in items if p["kind"] != "guest"],
                                  "guests": [p for p in items if p["kind"] == "guest"],
                                  "invites": [Invites.public(i) for i in self.invites.live()],
                                  "watching": self.guests_watching()})

    async def home_watching(self, request: web.Request) -> web.Response:
        return web.json_response({"watching": self.guests_watching()})

    async def home_code(self, request: web.Request) -> web.Response:
        address = self.address()
        if not address:
            return no("The Bench Box isn't reachable from outside yet.", 409, "off")
        code, until = self.codes.new()
        return web.json_response({"code": code, "url": f"https://{address}/pair#{code}", "expires": until})

    async def home_remove(self, request: web.Request) -> web.Response:
        if not await self.remove(request.match_info["id"]):
            raise web.HTTPNotFound()
        return web.Response(status=204)

    async def home_invite(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        return await self._new_invite(body, " ".join(str(body.get("by") or "").split())[:40] or self.bench.name)

    async def home_cancel(self, request: web.Request) -> web.Response:
        if not self.invites.cancel(request.match_info["id"]):
            raise web.HTTPNotFound()
        return web.Response(status=204)

    async def remove(self, pid: str) -> bool:
        """Gone at once: their record, and every connection they have open."""
        if not self.phones.remove(pid):
            return False
        await self._cut(pid)
        return True

    async def _cut(self, pid: str) -> None:
        for ws in list(self.sockets.pop(pid, ())):
            await ws.close(code=WSCloseCode.POLICY_VIOLATION, message=b"removed")
        for t in list(self.requests.pop(pid, ())):
            t.close()

    async def sweep(self) -> None:
        """Guests whose time is up: let go, with their connections."""
        for p in [p for p in self.phones.items if self.phones.ended(p)]:
            log.info("%s's time to watch ended", p["name"])
            await self.remove(p["id"])

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY)
            try:
                await self.sweep()
            except Exception:
                log.exception("letting ended guests go")
