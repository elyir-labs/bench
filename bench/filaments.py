"""Your filaments, on the Bench Box (design/bench-material/, B): the ones you have, each an Orca filament preset with
its color, named once and picked in one tap on any printer.
  GET    /bench/filaments                      {mine: [{id, preset, name, brand, material, color}]}
  POST   /bench/filaments                      {preset, name, brand, material, color}: add one (the same twice is one)
  DELETE /bench/filaments/{id}
  GET    /bench/filaments/library?q=&material=  Orca's library, searched by the box's slicer
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import ClientError, ClientSession, web


class Filaments:
    def __init__(self, state: Path, slicer: str, session: Callable[[], Optional[ClientSession]]):
        self.path, self.slicer, self.session = state / "filaments.json", slicer.rstrip("/"), session

    def mine(self) -> List[Dict[str, Any]]:
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, mine: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(mine, indent=1))
        tmp.replace(self.path)

    def routes(self, app: web.Application) -> None:
        app.router.add_get("/bench/filaments", self.get)
        app.router.add_get("/bench/filaments/library", self.library)
        app.router.add_post("/bench/filaments", self.add)
        app.router.add_delete("/bench/filaments/{id}", self.delete)

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response({"mine": self.mine()})

    async def add(self, request: web.Request) -> web.Response:
        try:
            b = await request.json()
            f = {k: str(b[k]).strip() for k in ("preset", "name", "material")}
            f["brand"] = str(b.get("brand") or "").strip()
            f["material"] = f["material"].upper()
            color = str(b.get("color") or "")
            if not all(f[k] for k in ("preset", "name", "material")) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "Send {preset, name, brand, material, color: #RRGGBB}."}, status=400)
        f["color"] = color.upper()
        mine = self.mine()
        same = next((x for x in mine if x["preset"] == f["preset"] and x["color"] == f["color"]), None)
        if same:
            return web.json_response(same)
        f = {"id": uuid.uuid4().hex[:8], **f}
        self._save([*mine, f])
        return web.json_response(f, status=201)

    async def delete(self, request: web.Request) -> web.Response:
        mine = self.mine()
        left = [x for x in mine if x["id"] != request.match_info["id"]]
        if len(left) == len(mine):
            return web.json_response({"error": "Not one of yours."}, status=404)
        self._save(left)
        return web.json_response({"ok": True})

    async def library(self, request: web.Request) -> web.Response:
        s = self.session()
        if s is None:
            return web.json_response({"error": "The box's slicer isn't up yet."}, status=503)
        try:
            async with s.get(f"{self.slicer}/slice/filaments", params={k: request.query[k] for k in ("q", "material") if k in request.query}) as r:
                return web.json_response(await r.json(), status=r.status)
        except (ClientError, ValueError):
            return web.json_response({"error": "The box's slicer didn't answer."}, status=502)
