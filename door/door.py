#!/usr/bin/env python3
"""The door: a printer reachable from anywhere, and nothing more than that. See docs/door.md.

Two listeners, and which one a request arrives on is how the door knows where it came from:

  away  127.0.0.1:8089  only ever reached through Caddy, so everything here is from outside
  home  127.0.0.1:8090  only ever reached through nginx (/door/), so everything here is from the house

From away, a stranger gets the app's own files and the pairing route. A paired phone also gets the
camera, thumbnails, push, and Moonraker's websocket with every call checked against a short list.
"""
from __future__ import annotations

import argparse
from urllib.parse import urlencode
import asyncio
import sys
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

log = logging.getLogger("door")

COOKIE = "elyir_bench_phone"
CODE_LIFE = 600                          # a pairing code works for ten minutes, once
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: it gets read off a screen
TRIES, TRIES_WINDOW = 5, 600             # wrong codes per address before it has to wait

# ── what a phone away may do ─────────────────────────────────────────────────

WATCH = {
    "server.connection.identify", "server.info", "printer.info",
    "printer.intent", "printer.intent.events", "printer.intent.check_print",
    "printer.objects.list", "printer.objects.query", "printer.objects.subscribe",
    "server.history.list", "server.files.metadata", "server.webcams.list",
    # The Print tab's library, browsed from away (design/print-library, B): listing only. Removing a
    # file (server.files.delete_file) and starting one stay at home, where they always were.
    "server.files.list", "server.files.get_directory",
}
READ_NAMESPACES = {"elyir-bench", "maintenance"}
# Actions that need nobody at the printer. Starting, heating, moving, spools, and claims about the
# physical printer ("the bed is clear", "I wiped it") wait for the panel. docs/door.md.
# The first layer's Further / Closer (squish_less / squish_more) moves the nozzle mid-print: home only
# (3 October 2026), and so are keeping it and the rest of design/first-layer/.
AWAY_ACTIONS = {"pause", "resume", "cancel", "stop_now", "cool_down", "swap_slot", "dismiss_swap", "care_later", "help",
                "skip_part",   # watching a part fail on the camera is how it's noticed from away (design/skip-objects/)
                # A colour change at the pause (design/colour-change/, A; 3 October 2026): switching to a spool
                # in the unit is allowed from away, confirmed once more, and checked on the camera. Putting a spool in
                # needs hands, so "put_in" and "swap" stay at the printer (see colour_choose_away).
                "colour_choose", "change_good", "change_more",
                # Turn off and Restart (design/power/, A; 5 October 2026): from away too, told that only someone
                # at the printer can switch it on again. It waits for the nozzle to cool either way.
                "power_off", "power_restart", "power_keep", "power_now", "power_retry",
                # The chamber light (design/chamber-light/, A): from away it's how the camera shows anything at night.
                "light_on", "light_off", "light_try", "light_pick"}


def colour_choose_away(args: Any) -> str | None:
    """None if a phone away may make this colour-change choice: carry on with the spool in the head, or a
    switch it confirmed (away_ok, the extra step the app shows away). Anything with hands, never."""
    a = args if isinstance(args, dict) else {}
    if a.get("how") == "keep":
        return None
    if a.get("how") == "switch":
        return None if a.get("away_ok") is True else "Confirm the switch first."
    return "That has to be done at the printer."
NOTIFY = {
    "notify_agent_event",
    "notify_intent_update", "notify_elyir_bench_event", "notify_status_update",
    "notify_klippy_ready", "notify_klippy_shutdown", "notify_klippy_disconnected",
    "notify_history_changed", "notify_webcams_changed",
}
THUMB = re.compile(r"^/server/files/gcodes/(?:[^/]+/)*\.thumbs/[^/]+\.(?:png|jpg|jpeg|webp)$")
API_PREFIXES = ("/server/", "/printer/", "/machine/", "/access/", "/api/", "/websocket", "/door/", "/webcam", "/slice")


def allowed_call(method: str, params: Any, act: bool = True) -> str | None:
    """None if a phone away may make this call; otherwise the words it is refused with. act=False: watching only
    (a Bench Box's guest invited to watch, design/bench-remote/)."""
    p = params if isinstance(params, dict) else {}
    if method in WATCH:
        return None
    if method == "server.database.get_item" and p.get("namespace") in READ_NAMESPACES:
        return None
    if method == "printer.intent.action":
        if not act:
            return "You can watch, not change anything."
        if p.get("action") == "colour_choose":
            return colour_choose_away(p.get("args"))
        return None if p.get("action") in AWAY_ACTIONS else "That has to be done at the printer."
    return "That isn't possible from away."


# ── phones ───────────────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Phones:
    """Who is paired. Each phone holds a random token in a cookie; only its hash is kept here."""

    def __init__(self, path: Path, now=time.time):
        self.path, self.now = path, now
        try:
            self.items: list[dict] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.items = []
        self._seen_saved = 0.0

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def pair(self, name: str, kind: str = "phone", origins: list[str] | None = None, guest: dict | None = None) -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        phone = {"id": secrets.token_hex(6), "name": " ".join(name.split())[:40] or "A phone",
                 "token": _hash(token), "joined": self.now(), "last_seen": self.now(), "push": None}
        if kind == "bench":
            # a Bench Box (design/bench-box/): the addresses its screen is served from, which may frame this
            # printer's screens and talk to it from a page (docs/bench.md)
            phone.update(kind="bench", origins=list(origins or []))
        elif kind == "guest":
            # invited by someone already paired (design/bench-remote/, C): what they may do, and until when
            phone.update(kind="guest", reach=guest["reach"], until=guest.get("until"), invited_by=guest.get("invited_by"))
        self.items.append(phone)
        self.save()
        return phone, token

    def identify(self, token: str | None) -> dict | None:
        if not token:
            return None
        h = _hash(token)
        for p in self.items:
            if hmac.compare_digest(p["token"], h):
                return None if self.ended(p) else p
        return None

    def ended(self, p: dict) -> bool:
        return p.get("kind") == "guest" and p.get("until") is not None and p["until"] <= self.now()

    def get(self, phone_id: str) -> dict | None:
        return next((p for p in self.items if p["id"] == phone_id), None)

    def remove(self, phone_id: str) -> bool:
        before = len(self.items)
        self.items = [p for p in self.items if p["id"] != phone_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def seen(self, phone: dict, via: str | None = None) -> None:
        phone["last_seen"] = self.now()
        moved = bool(via) and phone.get("via") != via
        if via:
            phone["via"] = via                          # the name it came in on: who still uses a former one
        if moved or self.now() - self._seen_saved > 300:   # last seen is a nicety, not worth a write per request
            self._seen_saved = self.now()
            self.save()

    def bench_origins(self) -> set[str]:
        return {o for p in self.items if p.get("kind") == "bench" for o in p.get("origins") or []}

    @staticmethod
    def public(p: dict) -> dict:
        guest = {k: p.get(k) for k in ("kind", "reach", "until", "invited_by")} if p.get("kind") == "guest" else {}
        return {"id": p["id"], "name": p["name"], "joined": p["joined"], "last_seen": p.get("last_seen"), "via": p.get("via"),
                "notifications": bool(p.get("push")), **({"kind": "bench"} if p.get("kind") == "bench" else {}), **guest}


def origins_ok(given) -> list[str] | None:
    """A Bench Box's addresses: plain http(s) origins, a few of them (bench.local, its address, localhost)."""
    if not isinstance(given, list) or len(given) > 8:
        return None
    out = [str(o).rstrip("/") for o in given]
    return out if all(re.fullmatch(r"https?://[A-Za-z0-9.-]{1,80}(:\d{1,5})?", o) for o in out) else None


class Codes:
    """Pairing codes, shown on the panel. Single use, ten minutes, and wrong guesses are counted."""

    def __init__(self, now=time.time):
        self.now = now
        self.live: dict[str, float] = {}
        self.tries: dict[str, deque] = defaultdict(deque)

    def new(self) -> tuple[str, float]:
        self._sweep()
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self.live[code] = self.now() + CODE_LIFE
        return code, self.live[code]

    def _sweep(self) -> None:
        for c, until in list(self.live.items()):
            if until < self.now():
                del self.live[c]

    def wait(self, who: str) -> float:
        q = self.tries[who]
        while q and q[0] < self.now() - TRIES_WINDOW:
            q.popleft()
        return (q[0] + TRIES_WINDOW - self.now()) if len(q) >= TRIES else 0.0

    def take(self, code: str, who: str) -> bool:
        self._sweep()
        code = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
        if code in self.live:
            del self.live[code]
            return True
        self.tries[who].append(self.now())
        return False


ASK_LIFE = 120                           # an ask waits two minutes for somebody to answer it
ASKS_AT_ONCE = 5


class Asks:
    """A device on the printer's Wi-Fi asks to connect; somebody at the printer, or on a phone already
    paired with it, says yes. No code to read or type. The asker holds a long random handle and checks
    back with it; its token is handed over once, to that handle only."""

    def __init__(self, phones: Phones, now=time.time):
        self.phones, self.now = phones, now
        self.items: dict[str, dict] = {}

    def _sweep(self) -> None:
        for h, a in list(self.items.items()):
            if a["expires"] < self.now() and a["state"] == "waiting":
                a["state"] = "expired"
            if a["expires"] + ASK_LIFE < self.now():          # answered or not, forget it a while later
                del self.items[h]

    def ask(self, name: str, kind: str, who: str, origins: list[str] | None = None) -> dict:
        self._sweep()
        # One open ask per address: asking again replaces it rather than piling up on the panel.
        for h, a in list(self.items.items()):
            if a["who"] == who and a["state"] == "waiting":
                del self.items[h]
        waiting = [a for a in self.items.values() if a["state"] == "waiting"]
        if len(waiting) >= ASKS_AT_ONCE:
            raise LookupError("busy")
        handle = secrets.token_urlsafe(24)
        a = {"id": secrets.token_hex(4), "handle": handle, "name": " ".join((name or "").split())[:40] or "A device",
             "kind": kind if kind in ("phone", "tablet", "computer", "hub", "bench") else "device", "who": who,
             "at": self.now(), "expires": self.now() + ASK_LIFE, "state": "waiting", "token": None, "phone": None,
             "origins": list(origins or []) if kind == "bench" else []}
        self.items[handle] = a
        return a

    def waiting(self) -> list[dict]:
        self._sweep()
        return [{k: a[k] for k in ("id", "name", "kind", "at", "expires")}
                for a in sorted(self.items.values(), key=lambda a: a["at"]) if a["state"] == "waiting"]

    def decide(self, ask_id: str, allow: bool) -> dict | None:
        self._sweep()
        a = next((a for a in self.items.values() if a["id"] == ask_id and a["state"] == "waiting"), None)
        if not a:
            return None
        if allow:
            phone, token = self.phones.pair(a["name"], a["kind"], a.get("origins"))
            a.update(state="allowed", token=token, phone=phone["id"])
        else:
            a["state"] = "refused"
        return a

    def check(self, handle: str) -> dict | None:
        self._sweep()
        a = self.items.get(handle)
        if not a:
            return None
        out = {"state": a["state"], "expires": a["expires"]}
        if a["state"] == "allowed" and a["token"]:
            out["token"], a["token"] = a["token"], None           # once
            out["phone"] = Phones.public(self.phones.get(a["phone"]) or {"id": a["phone"], "name": a["name"], "joined": a["at"]})
        return out


# ── push ─────────────────────────────────────────────────────────────────────

TTL = {"problem": 2 * 86400, "needs_you": 2 * 86400, "finished": 6 * 3600,
       "ready_to_lift": 12 * 3600, "care_due": 86400}
QUIET = (22, 8)                          # held overnight, phone's own clock: 22:00 to 08:00
HOLDABLE = {"low", "very-low"}


def quiet_now(tz: str | None, now: float) -> bool:
    try:
        hour = datetime.fromtimestamp(now, ZoneInfo(tz or "UTC")).hour
    except Exception:
        hour = datetime.fromtimestamp(now).hour
    start, end = QUIET
    return hour >= start or hour < end


def vapid_subject(address: str | None) -> str:
    """Who push services may contact about this printer: its public name as an https URL. py_vapid
    refuses a URL with a port in it, and a name without a dot is nobody's, so those fall back to a mailto."""
    host = (address or "").split(":")[0].strip().lower()
    if "." in host and not host.replace(".", "").isdigit():
        return f"https://{host}"
    return "mailto:door@example.net"


class Push:
    """Web Push from the printer itself: its own VAPID key, its phones' subscriptions, and a queue
    for what waits until morning."""

    def __init__(self, state: Path, phones: Phones, subject: str, now=time.time, sender=None, printer: str | None = None):
        from py_vapid import Vapid02
        self.phones, self.subject, self.now, self.printer = phones, subject, now, printer
        self.key_path = state / "vapid.pem"
        if self.key_path.exists():
            self.vapid = Vapid02.from_file(str(self.key_path))
        else:
            self.vapid = Vapid02()
            self.vapid.generate_keys()
            self.vapid.save_key(str(self.key_path))
            os.chmod(self.key_path, 0o600)
        self.held_path = state / "held.json"
        try:
            self.held: list[dict] = json.loads(self.held_path.read_text())
        except (OSError, ValueError):
            self.held = []
        self.sender = sender or self._webpush

    @staticmethod
    def _public_b64(vapid) -> str:
        from cryptography.hazmat.primitives import serialization
        raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @property
    def public_key(self) -> str:
        return self._public_b64(self.vapid)

    @staticmethod
    def vapid_of(private_b64: str):
        """A signing key the shell made on the phone: the raw 32-byte P-256 secret, base64url."""
        from py_vapid import Vapid02
        return Vapid02.from_raw(private_b64.encode())

    @classmethod
    def public_of(cls, private_b64: str) -> str:
        return cls._public_b64(cls.vapid_of(private_b64))

    def listeners(self, kind: str) -> list[dict]:
        out = []
        for p in self.phones.items:
            sub = p.get("push")
            if sub and (sub.get("kinds") is None or kind in sub["kinds"]):
                out.append(p)
        return out

    def _save_held(self) -> None:
        self.held_path.write_text(json.dumps(self.held))

    def _webpush(self, subscription: dict, data: str, headers: dict, ttl: int, key: str | None = None) -> int:
        from pywebpush import WebPushException, webpush
        try:
            r = webpush(subscription_info=subscription, data=data, vapid_private_key=self.vapid_of(key) if key else self.vapid,
                        vapid_claims={"sub": self.subject}, ttl=ttl, headers=headers, timeout=15)
            return r.status_code
        except WebPushException as e:
            return e.response.status_code if e.response is not None else 0

    async def send_event(self, ev: dict) -> int:
        """Send one intent event to every phone that wants its kind. Returns how many went out now."""
        kind, urgency = str(ev.get("kind") or ""), str(ev.get("urgency") or "normal")
        payload = {k: ev.get(k) for k in ("title", "body", "tag", "url", "urgency")}
        payload["printer"] = self.printer          # which printer, for a shell that holds several
        ttl = int(ev.get("ttl") or TTL.get(kind, 12 * 3600))
        sent = 0
        for p in self.listeners(kind):
            item = {"phone": p["id"], "payload": payload, "urgency": urgency, "topic": ev.get("tag"),
                    "expires": self.now() + ttl}
            if urgency in HOLDABLE and quiet_now(p["push"].get("tz"), self.now()):
                self.held = [h for h in self.held if not (h["phone"] == p["id"] and h["topic"] and h["topic"] == item["topic"])]
                self.held.append(item)
                continue
            sent += await self._deliver(p, item)
        self._save_held()
        return sent

    async def flush(self) -> int:
        """Send what was held overnight, now that it is morning where each phone is."""
        sent, keep = 0, []
        for h in self.held:
            p = self.phones.get(h["phone"])
            if not p or not p.get("push") or h["expires"] <= self.now():
                continue
            if quiet_now(p["push"].get("tz"), self.now()):
                keep.append(h)
                continue
            sent += await self._deliver(p, h)
        self.held = keep
        self._save_held()
        return sent

    async def _deliver(self, p: dict, item: dict) -> int:
        headers = {"Urgency": item["urgency"]}
        if item.get("topic"):
            headers["Topic"] = item["topic"]
        ttl = max(0, int(item["expires"] - self.now()))
        key = (p["push"].get("vapid") or {}).get("privateKey")
        status = await asyncio.get_running_loop().run_in_executor(
            None, self.sender, p["push"]["subscription"], json.dumps(item["payload"]), headers, ttl, key)
        if status in (404, 410):                         # the browser threw this subscription away
            log.info("push: %s's subscription is gone, dropping it", p["name"])
            p["push"] = None
            self.phones.save()
            return 0
        if not 200 <= status < 300:
            log.warning("push: %s answered %s", p["name"], status)
            return 0
        return 1


# ── following the printer ────────────────────────────────────────────────────

class Follower:
    """Moonraker's intent events, live and caught up after a reconnect. `boot` is the only resync
    signal: when it changes, the door starts from what is there now and replays nothing."""

    def __init__(self, moonraker: str, state: Path, push: Push, session_factory=ClientSession):
        self.ws_url = moonraker.replace("http", "ws", 1).rstrip("/") + "/websocket"
        self.cursor_path = state / "cursor.json"
        try:
            self.cursor = json.loads(self.cursor_path.read_text())
        except (OSError, ValueError):
            self.cursor = {"boot": None, "id": 0}
        self.push, self.session_factory = push, session_factory
        self.ws = None
        self._waiting: dict[int, asyncio.Future] = {}
        self._ids = iter(range(1, 1 << 62))

    def _save(self) -> None:
        self.cursor_path.write_text(json.dumps(self.cursor))

    async def call(self, method: str, params: dict | None = None) -> Any:
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._waiting[rid] = fut
        await self.ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": rid}))
        return await asyncio.wait_for(fut, 15)

    async def catch_up(self) -> None:
        r = await self.call("printer.intent.events", {"boot": self.cursor["boot"] or "", "after": self.cursor["id"]})
        if r.get("boot") != self.cursor["boot"]:
            everything = await self.call("printer.intent.events", {})
            self.cursor = {"boot": everything.get("boot"), "id": max([e["id"] for e in everything.get("events", [])], default=0)}
            self._save()
            return
        for ev in r.get("events", []):
            await self.handle(ev)

    async def handle(self, ev: dict) -> None:
        if ev.get("boot") != self.cursor["boot"] or int(ev.get("id") or 0) <= self.cursor["id"]:
            return
        self.cursor["id"] = int(ev["id"])
        self._save()
        try:
            n = await self.push.send_event(ev)
            log.info("event %s %s: sent to %d phone(s)", ev.get("kind"), ev.get("tag"), n)
        except Exception:
            log.exception("push failed for %s", ev.get("kind"))

    async def announce(self, event: str, data: dict) -> None:
        """Broadcast to every Moonraker client as notify_agent_event {agent: "elyir-bench-door", event, data}."""
        if self.ws is None or self.ws.closed:
            return
        try:
            await self.call("connection.send_event", {"event": event, "data": data})
        except Exception as e:
            log.info("could not announce %s: %s", event, e)

    async def write_phones(self) -> None:
        """How many phones will hear that a print is done: the Finished screen only promises when > 0."""
        if self.ws is None or self.ws.closed:
            return
        n = len(self.push.listeners("finished"))
        try:
            await self.call("server.database.post_item", {"namespace": "elyir-bench", "key": "phones", "value": n})
        except Exception as e:
            log.info("could not write the phone count: %s", e)

    async def run(self) -> None:
        delay = 1
        while True:
            try:
                async with self.session_factory() as s, s.ws_connect(self.ws_url, heartbeat=30) as ws:
                    self.ws, self._waiting = ws, {}
                    reader = asyncio.create_task(self._read(ws))
                    # An agent, so it may broadcast events to every Moonraker client (the panel hears asks at once).
                    await self.call("server.connection.identify", {"client_name": "elyir-bench-door", "version": "1",
                                                                   "type": "agent", "url": "https://github.com"})
                    await self.catch_up()
                    await self.write_phones()
                    delay = 1
                    await reader
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.info("moonraker: %s; retrying in %ds", e or e.__class__.__name__, delay)
            self.ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _read(self, ws) -> None:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if "id" in data and data["id"] in self._waiting:
                fut = self._waiting.pop(data["id"])
                if not fut.done():
                    fut.set_exception(RuntimeError(data["error"].get("message"))) if "error" in data else fut.set_result(data.get("result"))
            elif data.get("method") == "notify_elyir_bench_event":
                for ev in data.get("params") or []:
                    asyncio.create_task(self.handle(ev))
            elif data.get("method") == "notify_klippy_ready":
                pass


# ── the web side ─────────────────────────────────────────────────────────────

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "content-length", "content-encoding"}


SHELL = "https://printers.elyir.app"
SHELL_ORIGINS = (SHELL, "http://localhost:5173")
CLOUD_API = "https://cloud.elyir.dev"   # Bench Cloud; a phone may name another (docs/cloud.md)
TOKEN_PROTOCOL = "elyir-bench-token."
WS_PROTOCOL = "elyir-bench"


def forward_query(request: web.Request) -> str:
    """The query to pass on, without the phone's token. Moonraker reads `access_token` as its own
    login (refuses the request and writes the token to its log), and the camera has no use for it."""
    kept = [(k, v) for k, v in request.query.items() if k != "access_token"]
    return "?" + urlencode(kept) if kept else ""


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Door:
    """Three listeners, one per way in. Which one a request arrives on is the whole of how the door knows
    where it came from (docs/door.md):

      away   127.0.0.1:8089  Caddy, the public name through the relay: watching and a short list of actions
      home   127.0.0.1:8091  Caddy, the printer's name at home, straight over the Wi-Fi: everything the panel can do
      house  127.0.0.1:8090  nginx /door/: the panel and the Wi-Fi page, which issue codes and list phones

    Away and home both need a paired phone for anything past the app's own files."""

    def __init__(self, state: Path, moonraker: str, app_url: str, camera_url: str, address: str | None,
                 now=time.time, sender=None, home_address: str | None = None, printer_id: str | None = None,
                 printer_name: str | None = None, shell_origins=SHELL_ORIGINS, printers_app: str | None = None):
        state.mkdir(parents=True, exist_ok=True)
        self.state, self.moonraker, self.app_url, self.camera_url = state, moonraker.rstrip("/"), app_url.rstrip("/"), camera_url.rstrip("/")
        self.address, self._home_address, self.now = address, home_address, now
        # The name at home spells the LAN address, so it changes when the router hands out a new one. The
        # installer's certificate job writes the current one here; the door reads it fresh every time.
        self.home_file = state.parent / "home.json"
        self.printer_id = printer_id or (address or "printer").split(".")[0]
        self.printer_name = printer_name or self.printer_id.upper()
        # A staging printer is also reached from staging's Printers app, and its pairing code opens that one
        # (printers_app in elyir-bench.conf; bench-cloud README, Staging).
        self.shell = (printers_app or SHELL).rstrip("/")
        self.shell_origins = set(shell_origins) | {self.shell}
        self.phones = Phones(state / "phones.json", now)
        self.codes = Codes(now)
        self.asks = Asks(self.phones, now)
        self.push = Push(state, self.phones, vapid_subject(address), now, sender, printer=self.printer_id)
        self.follower = Follower(moonraker, state, self.push)
        self.session: ClientSession | None = None

    # ---- shared helpers ----
    @staticmethod
    def token_of(request: web.Request) -> str | None:
        """A phone proves itself with its cookie (the printer's own app), a bearer token (the shell, which
        talks to the same printer under two names and so cannot use a cookie), or, on a websocket, where a
        browser cannot set headers, a subprotocol carrying the token."""
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        for proto in request.headers.get("Sec-WebSocket-Protocol", "").split(","):
            proto = proto.strip()
            if proto.startswith(TOKEN_PROTOCOL):
                return proto[len(TOKEN_PROTOCOL):]
        # An <img> cannot send a header, so the camera and thumbnails -- those two and nothing else -- take
        # the token in the query.
        if request.method in ("GET", "HEAD") and (request.path.startswith("/webcam") or THUMB.match(request.path)):
            if request.query.get("access_token"):
                return request.query["access_token"]
        return request.cookies.get(COOKIE)

    def phone_of(self, request: web.Request) -> dict | None:
        return self.phones.identify(self.token_of(request))

    @staticmethod
    def who(request: web.Request) -> str:
        # Caddy on loopback is the only thing in front of the away and home listeners, and it says who is asking.
        return (request.headers.get("X-Forwarded-For") or request.remote or "").split(",")[0].strip()

    @property
    def home_address(self) -> str | None:
        if self._home_address:
            return self._home_address
        try:
            return json.loads(self.home_file.read_text()).get("name") or None
        except (OSError, ValueError):
            return None

    def addresses(self) -> dict:
        return {"away": f"https://{self.address}" if self.address else None,
                "home": f"https://{self.home_address}" if self.home_address else None}

    async def _proxy(self, request: web.Request, url: str, body: bool = False) -> web.StreamResponse:
        keep = ("Accept", "If-None-Match", "If-Modified-Since", "Range") + (("Content-Type", "Content-Length") if body else ())
        fwd = {k: v for k, v in request.headers.items() if k in keep}
        async with self.session.request(request.method, url, headers=fwd, allow_redirects=False,
                                        data=request.content if body and request.body_exists else None) as up:
            resp = web.StreamResponse(status=up.status)
            for k, v in up.headers.items():
                if k.lower() not in HOP:
                    resp.headers[k] = v
            await resp.prepare(request)
            async for chunk in up.content.iter_any():
                await resp.write(chunk)
            await resp.write_eof()
            return resp

    def _changed(self) -> None:
        asyncio.create_task(self.follower.write_phones())

    # ---- away and home: the two ways in from a phone ----
    def away_app(self) -> web.Application:
        return self._phone_app("away")

    def local_app(self) -> web.Application:
        return self._phone_app("home")

    def _phone_app(self, role: str) -> web.Application:
        app = web.Application(middlewares=[self._preflight, self._gate], client_max_size=1024 ** 3)
        app["role"] = role
        app.on_response_prepare.append(self._headers)
        app.router.add_get("/door/me", self.me)
        app.router.add_delete("/door/me", self.forget_me)
        app.router.add_put("/door/me/origins", self.my_origins)
        app.router.add_get("/door/frames", self.frames)
        app.router.add_post("/door/pair", self.pair)
        app.router.add_get("/door/push/key", self.push_key)
        app.router.add_get("/door/push/me", self.push_me)
        app.router.add_post("/door/push/subscribe", self.push_subscribe)
        app.router.add_delete("/door/push/subscribe", self.push_unsubscribe)
        app.router.add_get("/websocket", self.websocket)
        # Asking to connect, and answering, both happen in the house: asking from the printer's Wi-Fi,
        # answering on the panel or on a device already paired that is at home. A phone away is told where
        # to do it and shown nothing to act on (2 October 2026). Away, the routes exist to say so.
        app.router.add_post("/door/ask", self.ask if role == "home" else self.at_home)
        app.router.add_get("/door/ask/{handle}", self.ask_check)
        app.router.add_get("/door/asks", self.asks_waiting if role == "home" else self.at_home)
        app.router.add_post("/door/asks/{id}/allow", self.ask_allow if role == "home" else self.at_home)
        app.router.add_post("/door/asks/{id}/refuse", self.ask_refuse if role == "home" else self.at_home)
        # Bench Cloud (docs/cloud.md): how it is, from anywhere; joining a house, at home
        app.router.add_get("/door/cloud", self.cloud_status)
        app.router.add_post("/door/cloud/join", self.cloud_join if role == "home" else self.at_home)
        app.router.add_get("/door/report", self.report_preview)
        app.router.add_post("/door/report", self.report_send)
        if role == "home":                     # a paired phone at home may add and remove phones, like the panel
            app.router.add_post("/door/pair/new", self.pair_new)
            app.router.add_get("/door/phones", self.list_phones)
            app.router.add_delete("/door/phones/{id}", self.remove_phone)
        app.router.add_route("*", "/{tail:.*}", self.files)
        return app

    def origins(self) -> set[str]:
        """Pages that may talk to this printer and frame its screens: the Printers app, and each Bench Box
        it said yes to, from the addresses that box serves its screen from."""
        return self.shell_origins | self.phones.bench_origins()

    async def _headers(self, request: web.Request, response: web.StreamResponse) -> None:
        """CORS for the shell and the Bench Boxes, and who may frame the printer's screens."""
        origin = request.headers.get("Origin")
        allowed = self.origins()
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' " + " ".join(sorted(allowed))

    @web.middleware
    async def _preflight(self, request: web.Request, handler):
        if request.method != "OPTIONS":
            return await handler(request)
        if request.headers.get("Origin") not in self.origins():
            return web.Response(status=403)
        h = {"Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
             "Access-Control-Allow-Headers": "Authorization, Content-Type",
             "Access-Control-Max-Age": "600"}
        if request.headers.get("Access-Control-Request-Private-Network"):
            h["Access-Control-Allow-Private-Network"] = "true"   # Chrome, from a public page to a printer at home
        h["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return web.Response(status=204, headers=h)

    @web.middleware
    async def _gate(self, request: web.Request, handler):
        request["phone"] = phone = self.phone_of(request)
        path = request.path
        # A page on another site may not act with this phone's credentials: anything that changes something,
        # and the websocket, must come from the printer's own name or the shell.
        origin = request.headers.get("Origin")
        if origin and (request.method not in ("GET", "HEAD") or path == "/websocket"):
            own = origin.split("://", 1)[-1] == request.headers.get("X-Forwarded-Host", request.host)
            if not own and origin not in self.origins():
                return web.json_response({"detail": "origin"}, status=403)
        if phone:
            self.phones.seen(phone, request.headers.get("X-Forwarded-Host", request.host).split(":")[0])
        elif path not in ("/door/me", "/door/pair", "/door/ask", "/door/frames") and not path.startswith("/door/ask/") and path.startswith(API_PREFIXES):
            return web.json_response({"detail": "phone", "message": "This printer isn't open from here."}, status=401)
        return await handler(request)

    async def me(self, request: web.Request) -> web.Response:
        p, role = request["phone"], request.app["role"]
        return web.json_response({"paired": bool(p), "role": role, "away": role == "away",
                                  "printer": {"id": self.printer_id, "name": self.printer_name},
                                  "addresses": self.addresses(), "phone": Phones.public(p) if p else None,
                                  "actions": sorted(AWAY_ACTIONS) if role == "away" else None,
                                  # not secret: which pages the printer's screens may hand their token to
                                  "frames": sorted(self.origins())})

    async def forget_me(self, request: web.Request) -> web.Response:
        """The Printers app's Remove (design/printers-remove/, A): this phone takes itself off, home or away.
        Only itself: taking other phones off stays at home (DELETE /door/phones/{id})."""
        p = request["phone"]
        if not p:
            return web.json_response({"detail": "phone", "message": "This printer doesn't know this phone."}, status=401)
        self.phones.remove(p["id"])
        self._changed()
        return web.Response(status=204)

    async def my_origins(self, request: web.Request) -> web.Response:
        """A Bench Box keeps its addresses current (a new IP from the router): PUT {origins}."""
        p = request["phone"]
        if not p or p.get("kind") != "bench":
            return web.json_response({"detail": "bench", "message": "Only a Bench Box has addresses here."}, status=403)
        body = await request.json()
        given = origins_ok(body.get("origins") if isinstance(body, dict) else None)
        if given is None:
            return web.json_response({"detail": "origins", "message": "Send up to 8 addresses like http://bench.local:8088."}, status=400)
        p["origins"] = given
        self.phones.save()
        return web.json_response({"origins": given})

    async def pair(self, request: web.Request) -> web.Response:
        who = self.who(request)
        wait = self.codes.wait(who)
        if wait > 0:
            return web.json_response({"detail": "wait", "message": f"Too many tries. Wait {int(wait) + 1} seconds."}, status=429)
        body = await request.json()
        if not self.codes.take(str(body.get("code") or ""), who):
            return web.json_response({"detail": "code", "message": "That code didn't work. Get a new one from the printer."}, status=401)
        phone, token = self.phones.pair(str(body.get("name") or ""))
        log.info("paired %s from %s (%s)", phone["name"], who, request.app["role"])
        r = web.json_response({"paired": True, "phone": Phones.public(phone), "token": token,
                               "printer": {"id": self.printer_id, "name": self.printer_name}, "addresses": self.addresses()})
        r.set_cookie(COOKIE, token, max_age=10 * 365 * 86400, httponly=True, secure=True, samesite="Lax", path="/")
        return r

    async def files(self, request: web.Request) -> web.StreamResponse:
        path, role = request.path, request.app["role"]
        if path.startswith("/webcam") and request.method in ("GET", "HEAD"):
            return await self._proxy(request, self.camera_url + path.removeprefix("/webcam") + forward_query(request))
        if path == "/slice" or path.startswith("/slice/"):
            # Print a model (design/print-a-model/, design/plate/): the slicer sits behind the app's own nginx.
            # At home a paired phone slices like anyone at the printer; from away the app doesn't offer it yet.
            if role != "home":
                return web.json_response({"detail": "away", "error": "Printing a model isn't possible from away yet.",
                                          "message": "Printing a model isn't possible from away yet."}, status=403)
            return await self._proxy(request, self.app_url + path + forward_query(request), body=True)
        if role == "home" and path.startswith(API_PREFIXES):
            # At home, a paired phone is as good as the panel: Moonraker's whole API, uploads included.
            return await self._proxy(request, self.moonraker + path + forward_query(request), body=True)
        if request.method not in ("GET", "HEAD"):
            raise web.HTTPForbidden(text="That isn't possible from away.")
        if THUMB.match(path):
            return await self._proxy(request, self.moonraker + path)
        if path.startswith(API_PREFIXES):
            return web.json_response({"detail": "away", "message": "That isn't possible from away."}, status=403)
        return await self._proxy(request, self.app_url + path)    # the app's own files, open to anyone

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Moonraker's websocket. From away, every call is checked on the way in and only known
        notifications go out; at home it is passed through whole."""
        phone, away = request["phone"], request.app["role"] == "away"
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024, protocols=(WS_PROTOCOL,))
        await ws.prepare(request)
        async with self.session.ws_connect(self.follower.ws_url, max_msg_size=8 * 1024 * 1024) as up:
            async def down():
                async for msg in up:
                    if msg.type != WSMsgType.TEXT:
                        continue
                    if away:
                        try:
                            data = json.loads(msg.data)
                        except ValueError:
                            continue
                        if "method" in data and data["method"] not in NOTIFY:
                            continue
                        if data.get("method") == "notify_agent_event":     # only the door's own, not other agents'
                            p = (data.get("params") or [{}])[0]
                            if not isinstance(p, dict) or p.get("agent") != "elyir-bench-door":
                                continue
                    await ws.send_str(msg.data)
                await ws.close()
            pump = asyncio.create_task(down())
            try:
                async for msg in ws:
                    if msg.type != WSMsgType.TEXT:
                        continue
                    if not away:
                        await up.send_str(msg.data)
                        continue
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        continue
                    if not isinstance(data, dict) or not isinstance(data.get("method"), str):
                        continue
                    why = allowed_call(data["method"], data.get("params"))
                    if why:
                        log.info("refused %s from %s", data["method"], phone["name"])
                        if "id" in data:
                            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": data["id"],
                                                          "error": {"code": 403, "message": why}}))
                        continue
                    if data["method"] == "printer.intent.action" and isinstance(data.get("params"), dict):
                        # The printer logs who pressed it. Away, that's this paired phone, whatever the app says.
                        data["params"]["source"] = f"{phone['name']}, away (paired phone)"
                    await up.send_str(json.dumps(data))
            finally:
                pump.cancel()
        return ws

    # ---- push routes (paired only) ----
    async def push_key(self, request: web.Request) -> web.Response:
        return web.json_response({"publicKey": self.push.public_key})

    async def push_me(self, request: web.Request) -> web.Response:
        sub = request["phone"].get("push")
        return web.json_response({"subscribed": bool(sub), "kinds": sub.get("kinds") if sub else None})

    async def push_subscribe(self, request: web.Request) -> web.Response:
        body = await request.json()
        sub = body.get("subscription") or {}
        if not str(sub.get("endpoint", "")).startswith("https://") or not (sub.get("keys") or {}).get("p256dh"):
            return web.json_response({"detail": "subscription", "message": "That isn't a push subscription."}, status=400)
        vapid = body.get("vapid")
        if vapid is not None:
            # The shell's own key: one subscription on the phone, signed for by every printer it is paired with.
            try:
                if Push.public_of(vapid["privateKey"]) != vapid["publicKey"]:
                    raise ValueError("the keys do not match")
            except Exception as e:
                return web.json_response({"detail": "vapid", "message": f"That signing key isn't usable: {e}"}, status=400)
            vapid = {"publicKey": vapid["publicKey"], "privateKey": vapid["privateKey"]}
        kinds = body.get("kinds")
        request["phone"]["push"] = {"subscription": sub, "kinds": list(kinds) if isinstance(kinds, list) else None,
                                    "tz": str(body.get("tz") or "") or None, "since": self.now(), "vapid": vapid}
        self.phones.save()
        self._changed()
        return web.Response(status=204)

    async def push_unsubscribe(self, request: web.Request) -> web.Response:
        request["phone"]["push"] = None
        self.phones.save()
        self._changed()
        return web.Response(status=204)

    # ---- house (the panel and the Wi-Fi page, through nginx) ----
    def house_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/door/status", self.status)
        app.router.add_get("/door/frames", self.frames)
        app.router.add_post("/door/pair/new", self.pair_new)
        app.router.add_get("/door/phones", self.list_phones)
        app.router.add_delete("/door/phones/{id}", self.remove_phone)
        app.router.add_get("/door/asks", self.asks_waiting)
        app.router.add_post("/door/asks/{id}/allow", self.ask_allow)
        app.router.add_post("/door/asks/{id}/refuse", self.ask_refuse)
        app.router.add_get("/door/cloud", self.cloud_status)       # the panel says whether it's backed up
        app.router.add_get("/door/report", self.report_preview)    # Tell Elyir something (design/report/, B)
        app.router.add_post("/door/report", self.report_send)
        return app

    home_app = house_app

    # ---- asking to connect ----
    async def ask(self, request: web.Request) -> web.Response:
        body = await request.json()
        try:
            kind = str(body.get("kind") or "")
            origins = origins_ok(body.get("origins")) if kind == "bench" else None
            if kind == "bench" and origins is None:
                return web.json_response({"detail": "origins", "message": "A Bench Box says where its screen is: up to 8 addresses."}, status=400)
            a = self.asks.ask(str(body.get("name") or ""), kind, self.who(request), origins)
        except LookupError:
            return web.json_response({"detail": "busy", "message": "The printer has too many devices waiting. Try again in a minute."}, status=429)
        log.info("%s (%s) asks to connect from %s", a["name"], a["kind"], a["who"])
        asyncio.create_task(self._tell_about(a))
        return web.json_response({"handle": a["handle"], "expires": a["expires"],
                                  "printer": {"id": self.printer_id, "name": self.printer_name}}, status=201)

    async def at_home(self, request: web.Request) -> web.Response:
        if request.path == "/door/ask":
            msg = "Ask from the printer's Wi-Fi, where someone can see who is asking."
        elif request.path.startswith("/door/cloud"):
            msg = "Bench Cloud is turned on from your phone at home."
        else:
            msg = "New devices are allowed at home or on the printer's screen."
        return web.json_response({"detail": "at-home", "message": msg}, status=403)

    async def ask_check(self, request: web.Request) -> web.Response:
        out = self.asks.check(request.match_info["handle"])
        if not out:
            return web.json_response({"state": "expired"}, status=404)
        if out.get("token"):
            out |= {"printer": {"id": self.printer_id, "name": self.printer_name}, "addresses": self.addresses()}
        return web.json_response(out)

    async def asks_waiting(self, request: web.Request) -> web.Response:
        return web.json_response({"asks": self.asks.waiting()})

    async def _answer(self, request: web.Request, allow: bool) -> web.Response:
        a = self.asks.decide(request.match_info["id"], allow)
        if not a:
            raise web.HTTPNotFound()
        by = (request.get("phone") or {}).get("name") or "the printer"
        log.info("%s %s by %s", a["name"], "let in" if allow else "turned away", by)
        if allow:
            self._changed()
        asyncio.create_task(self.follower.announce("elyir_bench_asks", {"asks": self.asks.waiting()}))
        return web.json_response({"state": a["state"]})

    async def ask_allow(self, request: web.Request) -> web.Response:
        return await self._answer(request, True)

    async def ask_refuse(self, request: web.Request) -> web.Response:
        return await self._answer(request, False)

    async def _tell_about(self, a: dict) -> None:
        """The panel hears at once (a Moonraker agent event); paired phones get a notification they can act on."""
        await self.follower.announce("elyir_bench_asks", {"asks": self.asks.waiting()})
        try:
            await self.push.send_event({"kind": "ask", "urgency": "high", "ttl": ASK_LIFE,
                                        "title": f"{a['name']} wants to connect to {self.printer_name}",
                                        "body": "Allow it at home or on the printer's screen.",
                                        "tag": f"{self.printer_id}-ask", "url": "/phones"})
        except Exception:
            log.exception("telling phones about an ask")       # the name the first version used

    async def frames(self, request: web.Request) -> web.Response:
        """Which pages may frame this printer's screens and hand them their token: the Printers app and each
        Bench Box it said yes to (docs/bench.md). Not secret. Its own route, not /door/me: there the printer's
        own app (nginx /door/ on its port, the house listener) must keep finding nothing, or it asks to pair."""
        return web.json_response({"frames": sorted(self.origins())})

    async def status(self, request: web.Request) -> web.Response:
        return web.json_response({"address": self.address, "home_address": self.home_address, "phones": len(self.phones.items),
                                  "listening": len(self.push.listeners("finished"))})

    async def pair_new(self, request: web.Request) -> web.Response:
        if not self.address:
            return web.json_response({"detail": "off", "message": "This printer isn't reachable from outside yet."}, status=409)
        code, until = self.codes.new()
        return web.json_response({"code": code, "url": f"https://{self.address}/pair#{code}",
                                  "shell_url": f"{self.shell}/add#p={self.address}&c={code}", "expires": until})

    async def list_phones(self, request: web.Request) -> web.Response:
        return web.json_response({"phones": [Phones.public(p) for p in self.phones.items]})

    async def remove_phone(self, request: web.Request) -> web.Response:
        if not self.phones.remove(request.match_info["id"]):
            raise web.HTTPNotFound()
        self._changed()
        return web.Response(status=204)

    # ---- Bench Cloud (docs/cloud.md): an owner's phone at home puts this printer in its house ----
    def _cloud_file(self, name: str) -> dict:
        try:
            d = json.loads((self.state.parent / name).read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    # ---- a report or a message to Elyir (design/report/, B): the installer's `report` does the work ----
    REPORT_KINDS = ("wrong", "idea", "other")

    async def _report(self, *args: str) -> tuple[int, dict]:
        installer = Path(__file__).resolve().parent.parent / "installer" / "elyir_bench.py"
        proc = await asyncio.create_subprocess_exec(sys.executable, str(installer), "--json", "report", *args,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 180)
        except asyncio.TimeoutError:
            proc.kill()
            return 1, {"error": "Gathering the report took too long."}
        text = out.decode().strip()
        for candidate in (text, text.splitlines()[-1] if text else ""):   # --show prints indented JSON, a send one line
            try:
                return proc.returncode or 0, json.loads(candidate)
            except ValueError:
                continue
        return 1, {"error": "The report couldn't be put together."}

    async def report_preview(self, request: web.Request) -> web.Response:
        """What would go, sending nothing: the person sees it before anything leaves the printer."""
        kind = request.query.get("kind", "wrong")
        if kind not in self.REPORT_KINDS:
            raise web.HTTPBadRequest(text="kind: wrong, idea or other")
        code, got = await self._report("--kind", kind, "--show", *(() if kind == "wrong" else ("--no-details",)))
        return web.json_response(got, status=200 if code == 0 else 502)

    async def report_send(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="Send JSON.")
        kind = body.get("kind")
        if kind not in self.REPORT_KINDS:
            raise web.HTTPBadRequest(text="kind: wrong, idea or other")
        args = ["--kind", kind, "--note", str(body.get("note") or "")[:4000], "--email", str(body.get("email") or "")[:254]]
        if isinstance(body.get("context"), dict):
            args += ["--context", json.dumps(body["context"])[:4000]]
        if kind != "wrong" and not body.get("details"):
            args.append("--no-details")
        code, got = await self._report(*args)
        if code != 0 or not got.get("code"):
            return web.json_response({"detail": "report", "message": got.get("error") or "It wasn't sent."}, status=502)
        return web.json_response({"code": got["code"]}, status=201)

    async def cloud_status(self, request: web.Request) -> web.Response:
        me = self._cloud_file("cloud.json")
        return web.json_response({"joined": bool(me.get("token")), "name": me.get("name"), "house": me.get("house"),
                                  "last": self._cloud_file("cloud-last.json") or None})

    async def cloud_join(self, request: web.Request) -> web.Response:
        body = await request.json()
        token, api = str(body.get("join_token") or ""), str(body.get("api") or CLOUD_API).rstrip("/")
        if not token.startswith("j_") or not re.match(r"^(https://|http://(127\.0\.0\.1|localhost)(:\d+)?$)", api):
            raise web.HTTPBadRequest(text="A join token and an https address, please.")
        try:
            async with self.session.post(f"{api}/v1/devices", json={"join_token": token}) as r:
                got = await r.json(content_type=None)
                if r.status != 200:
                    return web.json_response({"detail": "cloud", "message": got.get("error") or f"Bench Cloud answered {r.status}."},
                                             status=502)
        except (ClientError, asyncio.TimeoutError, ValueError):
            return web.json_response({"detail": "cloud", "message": "Bench Cloud can't be reached right now."}, status=502)
        me = {"api": api, "device": got["device"], "token": got["device_token"], "house": got["house"],
              "name": got["name"], "joined": int(self.now())}
        path = self.state.parent / "cloud.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(me, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return web.json_response({"joined": True, "name": me["name"], "house": me["house"]})

    # ---- running ----
    async def background(self, app: web.Application):
        self.session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10))
        tasks = [asyncio.create_task(self.follower.run()), asyncio.create_task(self._mornings())]
        yield
        for t in tasks:
            t.cancel()
        await self.session.close()

    async def _mornings(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.push.flush()
            except Exception:
                log.exception("flushing held notifications")


async def serve(args) -> None:
    door = Door(Path(args.state), args.moonraker, args.app, args.camera, args.address or None,
                home_address=args.home_address or None, printer_id=args.printer_id or None,
                printer_name=args.printer_name or None, shell_origins=tuple(args.shell_origin or SHELL_ORIGINS),
                printers_app=args.printers_app or None)
    away, local, house = door.away_app(), door.local_app(), door.house_app()
    away.cleanup_ctx.append(door.background)
    runners = []
    for app, port in ((away, args.away_port), (local, args.local_port), (house, args.home_port)):
        r = web.AppRunner(app, access_log=None)
        await r.setup()
        await web.TCPSite(r, "127.0.0.1", port).start()
        runners.append(r)
    log.info("door open: away :%d (%s), home :%d (%s), house :%d", args.away_port, args.address or "no public name",
             args.local_port, args.home_address or "no home name", args.home_port)
    try:
        await asyncio.Event().wait()
    finally:
        for r in runners:
            await r.cleanup()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=str(Path.home() / "elyir-bench" / "state" / "door"))
    ap.add_argument("--moonraker", default="http://127.0.0.1:7125")
    ap.add_argument("--app", default="http://127.0.0.1:8088", help="where the app's own files are served")
    ap.add_argument("--camera", default="http://127.0.0.1/webcam", help="the camera, as /webcam/ on this host")
    ap.add_argument("--address", default=os.environ.get("ELYIR_BENCH_ADDRESS", ""), help="the printer's public name")
    ap.add_argument("--home-address", default="", help="the printer's name at home, 192-168-…-….<name>.home.<zone>")
    ap.add_argument("--printer-id", default="", help="short id the shell knows this printer by (the claimed name)")
    ap.add_argument("--printer-name", default="", help="what people call it, e.g. Workshop")
    ap.add_argument("--shell-origin", action="append", help="an origin allowed to call and frame this printer (repeatable)")
    ap.add_argument("--printers-app", default="", help="the Printers app this printer's pairing code opens (staging's), allowed too")
    ap.add_argument("--away-port", type=int, default=8089)
    ap.add_argument("--local-port", type=int, default=8091)
    ap.add_argument("--home-port", type=int, default=8090)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
