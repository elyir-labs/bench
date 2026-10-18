#!/usr/bin/env python3
"""
Stand-in for the door's push sender, for testing phone notifications on a laptop.

The real door (pairing, the gate, HTTPS on the printer's public name, Web Push) is
built separately. This script implements the same four routes the app calls, with
no pairing or auth (a cookie only tells browsers apart), and sends real Web Push
messages for the printer's notification events:

    GET    /door/push/key        -> {publicKey}
    POST   /door/push/subscribe  {subscription, kinds?}  -> 204
    DELETE /door/push/subscribe  {endpoint}              -> 204
    GET    /door/push/me         -> {subscribed, kinds}
    POST   /door/push/test       dev only: push a sample notification to everyone

It follows `notify_elyir_bench_event` on Moonraker's websocket (the simulator or a real
printer) and, after a reconnect, catches up through `printer.intent.events` without
replaying anything from an earlier Moonraker boot.

    ~/.venvs/elyir-bench-dev/bin/python tools/push-dev.py                     # simulator on :7126
    ~/.venvs/elyir-bench-dev/bin/python tools/push-dev.py --moonraker ws://workshop.local:7125/websocket

Needs `pip install pywebpush aiohttp`. Browsers only subscribe from a secure context,
and http://localhost counts, so use `npm run dev:sim` (Vite proxies /door here).
Keys and subscriptions live in ~/.cache/elyir-bench-push-dev/.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession, WSMsgType, web
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

DATA = Path.home() / ".cache" / "elyir-bench-push-dev"
KEY_FILE = DATA / "vapid.pem"
SUBS_FILE = DATA / "subscriptions.json"
KINDS = ["needs_you", "problem", "finished", "ready_to_lift", "care_due"]
TTL = {"needs_you": 3600, "problem": 3600, "finished": 6 * 3600, "ready_to_lift": 12 * 3600, "care_due": 24 * 3600}
COOKIE = "door_dev"

log = logging.getLogger("push-dev")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_vapid() -> Vapid:
    DATA.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(KEY_FILE))
    return Vapid.from_file(str(KEY_FILE))


class Door:
    def __init__(self, moonraker: str, subject: str):
        self.vapid = load_vapid()
        self.public_key = b64url(self.vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.moonraker = moonraker
        self.subject = subject
        self.subs: Dict[str, Dict[str, Any]] = json.loads(SUBS_FILE.read_text()) if SUBS_FILE.exists() else {}
        self.boot: Optional[str] = None
        self.last_id = 0

    def save(self) -> None:
        SUBS_FILE.write_text(json.dumps(self.subs, indent=2))
        asyncio.get_event_loop().create_task(self.record_phones())

    async def record_phones(self) -> None:
        """Tell the printer how many phones listen, so its screens only promise
        a phone message when one will arrive (Moonraker database elyir-bench/phones)."""
        url = re.sub(r"^ws", "http", self.moonraker).replace("/websocket", "/server/database/item")
        try:
            async with ClientSession() as session:
                await session.post(url, json={"namespace": "elyir-bench", "key": "phones", "value": len(self.subs)})
        except Exception as e:
            log.info("couldn't record the phone count on the printer (%s)", e)

    # ---- sending ------------------------------------------------------------

    async def push(self, event: Dict[str, Any]) -> None:
        payload = json.dumps({k: event.get(k) for k in ("title", "body", "tag", "url", "urgency")})
        kind = event.get("kind", "")
        urgency = event.get("urgency")
        headers = {"Urgency": urgency if urgency in ("very-low", "low", "normal", "high") else "normal"}
        tag = event.get("tag") or ""
        if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", tag):
            headers["Topic"] = tag   # the push service keeps only the newest per topic
        for endpoint, sub in list(self.subs.items()):
            if kind and sub.get("kinds") and kind not in sub["kinds"]:   # no list = every kind, new ones too
                continue
            try:
                await asyncio.to_thread(
                    webpush, sub["subscription"], data=payload, vapid_private_key=str(KEY_FILE),
                    vapid_claims={"sub": self.subject}, ttl=TTL.get(kind, 3600), headers=headers)
                log.info("pushed %s to %s…", kind or "test", endpoint[:60])
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                log.warning("push failed (%s) for %s…: %s", status, endpoint[:60], e)
                if status in (404, 410):   # the browser dropped this subscription
                    self.subs.pop(endpoint, None)
                    self.save()

    # ---- following the printer ------------------------------------------------

    async def follow(self) -> None:
        delay = 1.0
        while True:
            try:
                async with ClientSession() as session, session.ws_connect(self.moonraker, heartbeat=20) as ws:
                    log.info("following %s", self.moonraker)
                    delay = 1.0
                    await self.record_phones()
                    await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "printer.intent.events",
                                        "params": {"boot": self.boot or "", "after": self.last_id}})
                    async for msg in ws:
                        if msg.type != WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        if data.get("id") == 1:
                            await self.catch_up(data.get("result") or {})
                        elif data.get("method") == "notify_elyir_bench_event":
                            for event in data.get("params") or []:
                                await self.handle(event)
            except Exception as e:  # keep following through restarts
                log.info("moonraker not reachable (%s); retrying", e)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    async def catch_up(self, result: Dict[str, Any]) -> None:
        boot = result.get("boot")
        if boot != self.boot:
            # first contact or Moonraker restarted: start from now, never replay
            self.boot, self.last_id = boot, 0
            log.info("printer boot %s", boot)
            return
        for event in result.get("events") or []:
            await self.handle(event)

    async def handle(self, event: Dict[str, Any]) -> None:
        if event.get("boot") == self.boot and event.get("id", 0) <= self.last_id:
            return
        self.boot, self.last_id = event.get("boot"), event.get("id", 0)
        log.info("event %s: %s | %s", event.get("kind"), event.get("title"), event.get("body"))
        await self.push(event)

    # ---- the routes the app calls ----------------------------------------------

    def browser(self, request: web.Request) -> str:
        return request.cookies.get(COOKIE) or ""

    def respond(self, request: web.Request, resp: web.StreamResponse) -> web.StreamResponse:
        if not request.cookies.get(COOKIE):
            resp.set_cookie(COOKIE, request.get(COOKIE) or secrets.token_hex(8), httponly=True, samesite="Strict",
                            max_age=365 * 24 * 3600)
        return resp

    async def key(self, request: web.Request) -> web.StreamResponse:
        return self.respond(request, web.json_response({"publicKey": self.public_key}))

    async def subscribe(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        who = self.browser(request) or secrets.token_hex(8)
        request[COOKIE] = who
        if request.method == "DELETE":
            self.subs.pop(body.get("endpoint", ""), None)
        else:
            sub = body.get("subscription") or {}
            if not sub.get("endpoint"):
                raise web.HTTPBadRequest(text="subscription.endpoint missing")
            kinds = [k for k in body["kinds"] if k in KINDS] if body.get("kinds") else None
            self.subs[sub["endpoint"]] = {"subscription": sub, "kinds": kinds, "browser": who}
        self.save()
        return self.respond(request, web.Response(status=204))

    async def me(self, request: web.Request) -> web.StreamResponse:
        who = self.browser(request)
        mine = [s for s in self.subs.values() if who and s.get("browser") == who]
        kinds = sorted({k for s in mine for k in (s.get("kinds") or KINDS)})
        return self.respond(request, web.json_response({"subscribed": bool(mine), "kinds": kinds}))

    async def test(self, request: web.Request) -> web.StreamResponse:
        await self.push({"title": "Test from the printer", "body": "If you can read this, notifications work.",
                         "tag": "test", "url": "/", "urgency": "normal"})
        return web.json_response({"sent_to": len(self.subs)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--moonraker", default="ws://localhost:7126/websocket")
    ap.add_argument("--port", type=int, default=7180)
    ap.add_argument("--subject", default="mailto:elyir-bench-dev@example.net", help="VAPID contact")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    door = Door(a.moonraker, a.subject)
    app = web.Application()
    app.router.add_get("/door/push/key", door.key)
    app.router.add_post("/door/push/subscribe", door.subscribe)
    app.router.add_delete("/door/push/subscribe", door.subscribe)
    app.router.add_get("/door/push/me", door.me)
    app.router.add_post("/door/push/test", door.test)

    async def start_following(_: web.Application) -> None:
        app["follow"] = asyncio.create_task(door.follow())

    app.on_startup.append(start_following)
    log.info("push-dev on http://127.0.0.1:%d  (%d saved subscriptions)", a.port, len(door.subs))
    web.run_app(app, host="127.0.0.1", port=a.port, print=None)


if __name__ == "__main__":
    os.umask(0o077)   # the private key and subscriptions stay readable only by you
    main()
