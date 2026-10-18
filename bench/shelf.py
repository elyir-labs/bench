"""The Bench Box's shelf (design/bench-print/, A): the models it keeps, and each one set up for whichever printer
it goes to, on the box's own slicer, with that printer's own profile.

  GET    /bench/shelf                       the models, the last printed first
  POST   /bench/shelf                       add one (multipart: model): .stl .obj .3mf .step
  GET    /bench/shelf/{id}/parts/{n}        part n as an STL, to draw (a 3MF is read as its parts)
  PUT    /bench/shelf/{id}/picture          its picture, drawn by the page that added it (the PNG as the body)
  GET    /bench/shelf/{id}/picture
  DELETE /bench/shelf/{id}
  GET    /bench/printable                   per printer on the bench: whether the box can set a model up for it
  PUT    /bench/shelf/{id}/how              {purpose?, supports?, brim?, settings?}: how it prints, kept with it
  GET    /bench/shelf/{id}/sides            each part's sides it can rest on (the slicer's `lying`) and which is down
  PUT    /bench/shelf/{id}/side             {part, lay: auto | file | side, down?}: which side down, kept with it
  POST   /bench/shelf/{id}/slice            {printer, copies, material, filament?, color, slot, how?}: set it up for that printer
                                            (how: laid over the model's own for this slice only, never kept)
  GET    /bench/slice-options               the box slicer's options: purposes, editable settings
  GET    /bench/usual/{printer}             that printer's own usual {supports, purposes}, from its Moonraker
  GET    /bench/slice/{job}                 how setting it up stands (the slicer's own answer)
  POST   /bench/slice/{job}/send            put it on the printer; nothing starts (the page asks about the bed)
  DELETE /bench/slice/{job}

The slicer keeps a model for a day and a printer keeps only G-code, which fits that printer alone; the shelf keeps
the model itself, so "that again, on Desk this time" always has something to start from.

Models printed from a printer's own Print land here too (design/bench-shelf/, A): every few minutes the box reads each
printer's record of what it printed (elyir-bench/sliced in its Moonraker, written by the slicer when a plate is sent) and
fetches those models through the printer while its slicer still keeps them (a day), with the G-code's own picture. What
the box has seen is kept (gathered.json), so a model taken off the shelf doesn't come back, and the box's own prints,
which the printer records the same way, aren't added twice. A file sent from a slicer on a computer has no model. The box's slicer is asked
directly (no X-Elyir-Bench-Printer header: the box isn't a printer), naming the printer each time; each printer on the
bench is joined to it first, which copies its profile from its own Moonraker (docs/slicer.md).

How a model prints (design/bench-how/, A; docs/bench-how.md) is kept with it on the shelf: its purpose, supports,
brim and changed settings. Printing it again, queuing it and Whichever is free first all print it that way, on any
printer, over that printer's own usual and kept settings for the purpose (elyir-bench/slice_usual in its Moonraker).

Which side down (design/orientation/, the printer's own, on the box 11 October 2026) is kept with it too, per part: the
side picked, else the part's own, which is how a printer's plate had it (gathered) or, as on a printer's Print, laid flat
for you when its flattest side isn't down.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData, web

LOOK_KEEP = 24 * 3600   # a model only looked at is let go after this

MODEL_TYPES = (".stl", ".obj", ".3mf", ".step", ".stp")
SLICER_KEEPS = 20 * 3600     # the slicer drops a model after a day: upload it again before then
JOIN_EVERY = 600             # a printer's profile, looked at again (the slicer copies it when it changes)
GATHER_EVERY = 180           # each printer's record of what it printed, looked at again
USUAL_EVERY = 60             # a printer's usual (elyir-bench/slice_usual), looked at again
PNG = b"\x89PNG\r\n\x1a\n"
# how a model prints: the printer app's words (app/src/slice/plan.ts), the slicer's ids
PURPOSES = ("draft", "everyday", "display", "strong")
KINDS = ("normal", "tree", "off")
BRIMS = ("auto", "none", "ears", "all")
HOW = {"purpose": "everyday", "supports": None, "brim": None, "settings": {}}
log = logging.getLogger("bench.shelf")


def how_of(it: dict) -> dict:
    """The model's how, the defaults filled in: a model kept before there was a how prints as everyday, as usual."""
    kept = it.get("how_it_prints") or {}    # on disk beside "how", a gathered plate's per-file scale and lay
    return {**HOW, **{k: kept[k] for k in HOW if k in kept}, "settings": dict(kept.get("settings") or {})}


def lay_how(how: dict, change: Any) -> dict:
    """A how with a change laid over it: only what's given changes, settings merge (a setting set to null goes back
    to the printer's own). Raises ValueError in words when something can't be kept."""
    if not isinstance(change, dict):
        raise ValueError("Send how it prints as {purpose, supports, brim, settings}.")
    out = {**how, "settings": dict(how.get("settings") or {})}
    for k, v in change.items():
        if k == "purpose":
            if v not in PURPOSES:
                raise ValueError(f"{v!r} isn't something a model can be for: it's draft, everyday, display or strong.")
            out["purpose"] = v
        elif k == "supports":
            if v is not None and v not in KINDS:
                raise ValueError(f"{v!r} isn't a kind of support: it's normal, tree, off, or null for the printer's usual.")
            out["supports"] = v
        elif k == "brim":
            if v is not None and v not in BRIMS:
                raise ValueError(f"{v!r} isn't a brim: it's auto, none, ears, all, or null for each part's own.")
            out["brim"] = v
        elif k == "settings":
            if not isinstance(v, dict):
                raise ValueError("Settings are {key: value}, each value a string (null takes the change away).")
            for key, value in v.items():
                if not re.fullmatch(r"[a-z0-9_]+", str(key)):
                    raise ValueError(f"{key!r} isn't a setting's key: those are lowercase letters, digits and _.")
                if value is None:
                    out["settings"].pop(key, None)
                elif isinstance(value, str):
                    out["settings"][key] = value
                else:
                    raise ValueError(f"The value for {key} must be a string, like \"4\" or \"15%\".")
        else:
            raise ValueError(f"{k!r} isn't part of how a model prints: that's purpose, supports, brim and settings.")
    return out


def model_name(filename: str) -> str:
    """What a person calls a file: phone_stand_v2.3mf → Phone stand v2."""
    stem = re.sub(r"\.(stl|obj|3mf|step|stp)$", "", Path(filename).name, flags=re.I)
    words = re.sub(r"[_]+|(?<=[a-z])-(?=[a-z])", " ", stem).strip() or "Model"
    return words[0].upper() + words[1:]


class Shelf:
    def __init__(self, root: Path, slicer: str, printers: Callable[[], Dict[str, dict]], now=time.time):
        self.root, self.slicer, self.printers, self.now = root, slicer.rstrip("/"), printers, now
        self.root.mkdir(parents=True, exist_ok=True)
        self.session: Optional[ClientSession] = None
        self.jobs: Dict[str, dict] = {}            # slicer job → {shelf, printer, copies, material, color, how}
        self.usuals: Dict[str, dict] = {}          # printer → {at, value}: its elyir-bench/slice_usual, a minute
        self.joined: Dict[str, dict] = {}          # printer → {at, entry | error}
        self.joining: Dict[str, asyncio.Lock] = {}  # one join per printer at a time: the slicer copies a profile in one place
        try:
            self.seen = json.loads((root / "gathered.json").read_text())
        except (OSError, ValueError):
            self.seen = {}
        self.seen.setdefault("plates", [])           # "<printer>/<file>/<when>": looked at, gathered or not
        self.seen.setdefault("models", [])           # the box's slicer's model ids: its own prints, recorded on a printer too

    # ── kept on disk: <root>/<id>/{model file, item.json, picture.png} ──

    def _dir(self, sid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", sid) or not (self.root / sid / "item.json").is_file():
            raise web.HTTPNotFound(text="not on the shelf")
        return self.root / sid

    def item(self, sid: str) -> dict:
        return json.loads((self._dir(sid) / "item.json").read_text())

    def save(self, it: dict) -> None:
        d = self.root / it["id"]
        (d / "item.tmp").write_text(json.dumps(it, indent=1))
        os.replace(d / "item.tmp", d / "item.json")

    def items(self) -> List[dict]:
        out = []
        for d in self.root.iterdir():
            try:
                out.append(json.loads((d / "item.json").read_text()))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda it: -max(it["added"], (it.get("last") or {}).get("at", 0)))

    def public(self, it: dict) -> dict:
        return {"id": it["id"], "name": it["name"], "file": it["file"], "added": it["added"], "last": it.get("last"), "from": it.get("from"),
                "look": bool(it.get("look")),
                "prints": it.get("prints", 0), "parts": len(it.get("parts") or []) or 1, "how": how_of(it),
                "picture": f"/bench/shelf/{it['id']}/picture" if (self.root / it["id"] / "picture.png").exists() else None}

    # ── http ──

    def routes(self, app: web.Application) -> None:
        app.router.add_get("/bench/shelf", self.get_shelf)
        app.router.add_post("/bench/shelf", self.post_model)
        app.router.add_post("/bench/look", self.post_look)
        app.router.add_put("/bench/shelf/{id}/keep", self.put_keep)
        app.router.add_get("/bench/shelf/{id}/parts/{n}", self.get_part)
        app.router.add_put("/bench/shelf/{id}/picture", self.put_picture)
        app.router.add_get("/bench/shelf/{id}/picture", self.get_picture)
        app.router.add_delete("/bench/shelf/{id}", self.delete_model)
        app.router.add_get("/bench/printable", self.get_printable)
        app.router.add_put("/bench/shelf/{id}/how", self.put_how)
        app.router.add_get("/bench/shelf/{id}/sides", self.get_sides)
        app.router.add_put("/bench/shelf/{id}/side", self.put_side)
        app.router.add_post("/bench/shelf/{id}/slice", self.post_slice)
        app.router.add_get("/bench/slice-options", self.get_options)
        app.router.add_get("/bench/usual/{printer}", self.get_usual)
        app.router.add_get("/bench/slice/{job}", self.get_job)
        app.router.add_get("/bench/slice/{job}/layers", self.get_layers)
        app.router.add_get("/bench/slice/{job}/layers/{n}", self.get_layers)
        app.router.add_post("/bench/slice/{job}/send", self.send)
        app.router.add_delete("/bench/slice/{job}", self.cancel)

    async def get_shelf(self, request: web.Request) -> web.Response:
        return web.json_response([self.public(it) for it in await asyncio.to_thread(self.items) if not it.get("look")])

    # A model sent only to look at (design/bench-look/, C: How would it print? from a phone): set up like any, kept off the
    # shelf, and let go after a day unless someone keeps it.
    async def post_look(self, request: web.Request) -> web.Response:
        await asyncio.to_thread(self.drop_old_looks)
        return await self.post_model(request, look=True)

    def drop_old_looks(self) -> None:
        for it in self.items():
            if it.get("look") and self.now() - it["added"] > LOOK_KEEP:
                shutil.rmtree(self.root / it["id"], ignore_errors=True)

    async def put_keep(self, request: web.Request) -> web.Response:
        """Keep it on the shelf: a model sent to look at becomes one of the shelf's."""
        it = self.item(request.match_info["id"])
        if it.pop("look", None):
            it["added"] = self.now()
            self.save(it)
        return web.json_response(self.public(it))

    async def post_model(self, request: web.Request, look: bool = False) -> web.Response:
        sid = secrets.token_hex(6)
        d = self.root / sid
        try:
            reader = await request.multipart()
            async for part in reader:
                if part.name != "model" or not part.filename:
                    continue
                name = Path(part.filename).name
                if not name.lower().endswith(MODEL_TYPES):
                    return _err(400, f"{name} isn't a model the box can print: an STL, OBJ, 3MF or STEP file.")
                d.mkdir(parents=True)
                with open(d / name, "wb") as f:
                    while chunk := await part.read_chunk(1 << 20):
                        f.write(chunk)
                it = {"id": sid, "name": model_name(name), "file": name, "added": self.now(), "prints": 0, "last": None, **({"look": True} if look else {})}
                self.save(it)
                try:
                    await self._upload(it)          # the slicer reads it now: a file it can't read is said now
                except SlicerSaid as e:
                    shutil.rmtree(d, ignore_errors=True)
                    return _err(e.status, e.words)
                return web.json_response(self.public(it), status=201)
            return _err(400, "Send the model as 'model'.")
        except ValueError as e:
            shutil.rmtree(d, ignore_errors=True)
            return _err(400, str(e))

    async def get_part(self, request: web.Request) -> web.StreamResponse:
        it = self.item(request.match_info["id"])
        parts = (await self._models(it))["parts"]
        n = int(request.match_info["n"]) if request.match_info["n"].isdigit() else -1
        if not 0 <= n < len(parts):
            raise web.HTTPNotFound(text="no such part")
        async with self.session.get(f"{self.slicer}/slice/models/{parts[n]['model']}/file") as r:
            if r.status != 200:
                raise web.HTTPBadGateway(text=f"the slicer said {r.status}")
            return web.Response(body=await r.read(), content_type="application/octet-stream")

    async def put_picture(self, request: web.Request) -> web.Response:
        d = self._dir(request.match_info["id"])
        body = await request.read()
        if not body.startswith(PNG) or len(body) > 2 << 20:
            return _err(400, "A picture is a PNG, at most 2 MB.")
        (d / "picture.png").write_bytes(body)
        return web.json_response(self.public(self.item(d.name)))

    async def get_picture(self, request: web.Request) -> web.StreamResponse:
        p = self._dir(request.match_info["id"]) / "picture.png"
        if not p.exists():
            raise web.HTTPNotFound(text="no picture")
        return web.FileResponse(p, headers={"Cache-Control": "max-age=60"})

    async def put_how(self, request: web.Request) -> web.Response:
        it = self.item(request.match_info["id"])
        try:
            how = lay_how(how_of(it), await request.json())
        except ValueError as e:                        # a body that isn't JSON: plain words, not the parser's
            return _err(400, str(e) if not isinstance(e, json.JSONDecodeError) else "Send how it prints as JSON.")
        it["how_it_prints"] = how
        self.save(it)
        return web.json_response(self.public(it))

    async def get_sides(self, request: web.Request) -> web.Response:
        it = self.item(request.match_info["id"])
        try:
            it = await self._models(it)
        except SlicerSaid as e:
            return _err(e.status, e.words)
        return web.json_response(sides_view(it))

    async def put_side(self, request: web.Request) -> web.Response:
        it = self.item(request.match_info["id"])
        try:
            want = await request.json()
            if not isinstance(want, dict):
                raise ValueError
        except ValueError:
            return _err(400, "Send which side down as {part, lay: auto, file or side, down}.")
        try:
            it = await self._models(it)
        except SlicerSaid as e:
            return _err(e.status, e.words)
        try:
            it["sides"] = pick_side(it, want)
        except ValueError as e:
            return _err(400, str(e))
        self.save(it)
        return web.json_response(sides_view(it))

    async def delete_model(self, request: web.Request) -> web.Response:
        d = self._dir(request.match_info["id"])
        shutil.rmtree(d, ignore_errors=True)
        return web.json_response({"gone": d.name})

    # ── the box's slicer ──

    async def _upload(self, it: dict) -> dict:
        """The model to the slicer, kept there a day: its ids (a 3MF: one per part, with that part's copies). A model
        gathered from a printer's plate is several files, each with how that plate had it (scale, which side down)."""
        parts: List[dict] = []
        for n, name in enumerate(it.get("files") or [it["file"]]):
            form = FormData()
            form.add_field("model", open(self.root / it["id"] / name, "rb"), filename=name)
            try:
                async with self.session.post(f"{self.slicer}/slice/models", data=form) as r:
                    body = await r.json(content_type=None)
                    if r.status != 201:
                        raise SlicerSaid(400 if r.status == 400 else 502, body.get("error") or f"The slicer said {r.status}.")
            except (ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
                if isinstance(e, SlicerSaid):
                    raise
                raise SlicerSaid(503, "The box's slicer isn't answering. It may be starting.")
            got = body["models"] if "models" in body else [{"model": body["model"], "name": body["name"], "copies": 1, "lying": body.get("lying")}]
            how = (it.get("how") or [])[n] if n < len(it.get("how") or []) else {}
            parts += [{"model": p["model"], "name": p["name"], "copies": max(1, int(p.get("copies") or 1)), **how, "lying": p.get("lying")}
                      for p in got]
        it["parts"] = parts
        it["uploaded"] = self.now()
        self.save(it)
        self._own([p["model"] for p in parts])
        return it

    def _own(self, ids: List[str]) -> None:
        self.seen["models"] = (self.seen["models"] + [i for i in ids if i not in self.seen["models"]])[-500:]
        self._save_seen()

    def _save_seen(self) -> None:
        (self.root / "gathered.tmp").write_text(json.dumps(self.seen))
        os.replace(self.root / "gathered.tmp", self.root / "gathered.json")

    async def _models(self, it: dict) -> dict:
        # kept before the box knew a part's sides: read again for them
        if not it.get("parts") or self.now() - it.get("uploaded", 0) > SLICER_KEEPS or any("lying" not in p for p in it["parts"]):
            it = await self._upload(it)
        return it

    async def _join(self, pid: str, fresh: bool = False) -> dict:
        """The printer joined to the box's slicer (its profile copied from its own Moonraker): what it can print."""
        async with self.joining.setdefault(pid, asyncio.Lock()):
            return await self._join_now(pid, fresh)

    async def _join_now(self, pid: str, fresh: bool) -> dict:
        known = self.joined.get(pid)
        if known and not fresh and self.now() - known["at"] < JOIN_EVERY:
            return known
        p = self.printers().get(pid)
        if p is None:
            raise web.HTTPNotFound(text="not on this bench")
        body = {"name": p["name"], "moonraker": f"http://{p['host']}:{p.get('moonraker_port', 7125)}"}
        try:
            async with self.session.put(f"{self.slicer}/slice/printers/{pid}", json=body) as r:
                got = await r.json(content_type=None)
                # a profile that doesn't slice is asked about again in a minute, not ten: it may be fixed by then
                known = {"at": self.now(), "entry": got} if r.status == 200 else \
                    {"at": self.now() - JOIN_EVERY + 60, "error": got.get("error") or f"The slicer said {r.status}."}
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            known = {"at": self.now() - JOIN_EVERY + 30, "error": "The box's slicer isn't answering. It may be starting."}
        self.joined[pid] = known
        return known

    async def get_printable(self, request: web.Request) -> web.Response:
        out = {}
        for pid in list(self.printers()):
            j = await self._join(pid)
            out[pid] = {"materials": j["entry"].get("materials", []), "slots": j["entry"].get("slots")} if "entry" in j else {"error": j["error"]}
        return web.json_response(out)

    async def post_slice(self, request: web.Request) -> web.Response:
        it = self.item(request.match_info["id"])
        try:
            want = await request.json()
            pid, copies = str(want["printer"]), int(want.get("copies") or 1)
            if not 1 <= copies <= 200:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return _err(400, "Send {printer, copies (1 to 200), material, color, slot, how}.")
        try:
            # the purpose sheet prices the other purposes: laid over the model's how for this slice, never kept
            how = lay_how(how_of(it), want["how"]) if want.get("how") is not None else how_of(it)
        except ValueError as e:
            return _err(400, str(e))
        j = await self._join(pid)
        if "error" in j:
            return _err(409, j["error"])
        try:
            it = await self._models(it)
            job = await self._slice(it, pid, copies, want, how)
            if job.get("missing"):                           # kept less than a day after all: read it again
                it = await self._upload(it)
                job = await self._slice(it, pid, copies, want, how)
        except SlicerSaid as e:
            return _err(e.status, e.words)
        if "id" not in job:
            return _err(400, job.get("error") or "The slicer couldn't set it up.")
        self.jobs[job["id"]] = {"shelf": it["id"], "printer": pid, "copies": copies,
                                "material": want.get("material"), "color": want.get("color"), "how": how,
                                "filament": want.get("filament"), "filament_name": want.get("filament_name")}
        return web.json_response(job, status=202)

    async def _slice(self, it: dict, pid: str, copies: int, want: dict, how: Optional[dict] = None) -> dict:
        """Set the model up for printer pid, the way its how says (the model's own unless given), over that printer's
        usual supports and its kept settings for the purpose; the model's own settings win, as on a printer's Print."""
        how = how or how_of(it)
        return await self._slice_many([(it, copies, how)], pid, want, how)

    async def _slice_many(self, entries: List[tuple], pid: str, want: dict, how: dict) -> dict:
        """Several shelf models as one plate (design/bench-several/, C): entries are (model, copies, its how). The plate
        prints the way `how` says; each model keeps its own brim."""
        usual = await self._usual(pid)
        it = entries[0][0]
        req: Dict[str, Any] = {"printer": pid, "parts": [p for m, n, h in entries for p in plate_parts(m, n, h)],
                               "material": str(want.get("material") or "PLA").upper(),
                               "purpose": how["purpose"], "supports": how.get("supports") or usual["supports"],
                               "kept": usual["purposes"].get(how["purpose"]) or {}, "settings": dict(how.get("settings") or {})}
        if want.get("color"):
            req["color"] = want["color"]
        if want.get("filament"):                                   # one of your filaments (filaments.py): its own preset
            req["filament"] = str(want["filament"])
        if want.get("slot") not in (None, ""):
            req["slot"] = int(want["slot"])
        pic = self.root / it["id"] / "picture.png"
        if pic.exists():
            req["thumbnail"] = base64.b64encode(pic.read_bytes()).decode()
        try:
            async with self.session.post(f"{self.slicer}/slice", json=req) as r:
                body = await r.json(content_type=None)
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            raise SlicerSaid(503, "The box's slicer isn't answering. It may be starting.")
        if r.status == 400 and "no such model" in str(body.get("error")):
            return {"missing": True}
        return body

    async def _usual(self, pid: str) -> dict:
        """The printer's own usual: {supports, purposes: {purpose: {key: value}}} (its "Yours"), from its Moonraker
        (elyir-bench/slice_usual, kept by its Print), looked at again after a minute. Supports falls back to the kind
        its process preset prints (the slicer's entry for it), else normal. Off or never kept: nothing kept."""
        known = self.usuals.get(pid)
        if not known or self.now() - known["at"] >= USUAL_EVERY:
            value: Any = None
            p = self.printers().get(pid)
            if p is not None:
                moon = f"http://{p['host']}:{p.get('moonraker_port', 7125)}"
                try:
                    # a printer that's off must not hold a slice up for the session's five minutes
                    async with self.session.get(f"{moon}/server/database/item", params={"namespace": "elyir-bench", "key": "slice_usual"},
                                                timeout=ClientTimeout(total=5)) as r:
                        value = (await r.json(content_type=None)).get("result", {}).get("value") if r.status == 200 else None
                except (ClientError, OSError, asyncio.TimeoutError, ValueError, AttributeError):
                    value = None
            known = self.usuals[pid] = {"at": self.now(), "value": value if isinstance(value, dict) else {}}
        value = known["value"]
        given = value.get("purposes") if isinstance(value.get("purposes"), dict) else {}
        purposes = {k: {str(key): str(v) for key, v in kept.items() if v is not None}
                    for k, kept in given.items() if k in PURPOSES and isinstance(kept, dict)}
        kind = value.get("supports")
        if kind not in KINDS:
            kind = ((self.joined.get(pid) or {}).get("entry") or {}).get("supports")
        return {"supports": kind if kind in KINDS else "normal", "purposes": purposes}

    async def get_usual(self, request: web.Request) -> web.Response:
        pid = request.match_info["printer"]
        if pid not in self.printers():
            return _err(404, "That printer isn't on this bench.")
        await self._join(pid)                          # the slicer's entry for it: the kind its preset prints
        return web.json_response(await self._usual(pid))

    async def get_options(self, request: web.Request) -> web.Response:
        """The box slicer's options as it says them: the purposes with their labels and summaries, editable settings."""
        try:
            async with self.session.get(f"{self.slicer}/slice/options") as r:
                return web.Response(status=r.status, body=await r.read(), content_type="application/json")
        except (ClientError, OSError, asyncio.TimeoutError):
            return _err(503, "The box's slicer isn't answering. It may be starting.")

    # ── models printed from a printer's own Print (design/bench-shelf/, A) ──

    async def gather_forever(self) -> None:
        while True:
            try:
                await self.gather()
            except Exception:                         # one printer's odd answer never stops the shelf
                log.exception("gathering")
            await asyncio.sleep(GATHER_EVERY)

    async def gather(self) -> List[dict]:
        """Every printer's recent plates, the ones not seen yet: each one's models onto the shelf, while still kept."""
        added = []
        for pid, p in list(self.printers().items()):
            moon = f"http://{p['host']}:{p.get('moonraker_port', 7125)}"
            try:
                async with self.session.get(f"{moon}/server/database/item", params={"namespace": "elyir-bench", "key": "sliced"}) as r:
                    sliced = (await r.json(content_type=None)).get("result", {}).get("value") if r.status == 200 else None
            except (ClientError, OSError, asyncio.TimeoutError, ValueError):
                continue                               # off: looked at again next time, while its slicer still keeps them
            if not isinstance(sliced, dict):
                continue
            for gcode, rec in sorted(sliced.items(), key=lambda kv: float((kv[1] or {}).get("at") or 0)):
                key = f"{pid}/{gcode}/{(rec or {}).get('at')}"
                if key in self.seen["plates"] or not isinstance(rec, dict) or not rec.get("parts"):
                    continue
                ids = [str(x.get("model")) for x in rec["parts"]]
                if any(i in self.seen["models"] for i in ids):
                    self._seen(key)                    # the box's own print, recorded on the printer too
                    continue
                it = await self._fetch(pid, p, moon, gcode, rec)
                if it is not False:                    # fetched, or gone for good (kept less than a day): done with it
                    self._seen(key)
                if it:
                    added.append(it)
        return added

    def _seen(self, key: str) -> None:
        self.seen["plates"] = (self.seen["plates"] + [key])[-1000:]
        self._save_seen()

    async def _fetch(self, pid: str, p: dict, moon: str, gcode: str, rec: dict):
        """One plate's models, through the printer's own address (its nginx says which printer asks, so its slicer,
        here or elsewhere, hands over that printer's models). None when they're gone, False when it didn't answer."""
        sid = secrets.token_hex(6)
        d = self.root / sid
        files, how = [], []
        try:
            for n, part in enumerate(rec["parts"]):
                async with self.session.get(f"http://{p['host']}:{p['port']}/slice/models/{part['model']}/file") as r:
                    if r.status == 404:
                        shutil.rmtree(d, ignore_errors=True)
                        return None
                    if r.status != 200:
                        raise ClientError(f"{r.status}")
                    body = await r.read()
                d.mkdir(parents=True, exist_ok=True)
                name = f"{n}-{re.sub(r'[^A-Za-z0-9._ -]+', '_', Path(str(part.get('name') or 'part.stl')).name)}"
                (d / name).write_bytes(body)
                files.append(name)
                how.append({k: part[k] for k in ("scale", "lay", "down", "brim") if part.get(k) is not None})
            picture = await self._thumbnail(moon, gcode)
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            shutil.rmtree(d, ignore_errors=True)
            return False
        at = float(rec.get("at") or self.now())
        names = [str(x.get("name") or "") for x in rec["parts"]]
        it = {"id": sid, "name": plate_name(names, gcode), "file": files[0], "files": files, "how": how, "added": at, "prints": 1,
              "from": {"printer": pid, "printer_name": p["name"], "file": gcode, "at": at},
              "last": {"printer": pid, "printer_name": p["name"], "copies": 1, "material": rec.get("material"), "color": rec.get("color"), "at": at}}
        if picture:
            (d / "picture.png").write_bytes(picture)
        self.save(it)
        log.info("gathered %s from %s (%s)", it["name"], pid, gcode)
        return it

    async def _thumbnail(self, moon: str, gcode: str) -> Optional[bytes]:
        """The picture in the G-code, the biggest one (Moonraker's file metadata says where it is)."""
        try:
            async with self.session.get(f"{moon}/server/files/metadata", params={"filename": gcode}) as r:
                thumbs = (await r.json(content_type=None)).get("result", {}).get("thumbnails") or [] if r.status == 200 else []
            if not thumbs:
                return None
            best = max(thumbs, key=lambda t: int(t.get("width") or 0))
            folder = str(Path(gcode).parent).strip(".")
            async with self.session.get(f"{moon}/server/files/gcodes/{folder + '/' if folder else ''}{best['relative_path']}") as r:
                body = await r.read() if r.status == 200 else b""
            return body if body.startswith(PNG) else None
        except (ClientError, OSError, asyncio.TimeoutError, ValueError, KeyError):
            return None

    async def get_job(self, request: web.Request) -> web.Response:
        return await self._pass("GET", request.match_info["job"])

    async def cancel(self, request: web.Request) -> web.Response:
        self.jobs.pop(request.match_info["job"], None)
        return await self._pass("DELETE", request.match_info["job"])

    async def send(self, request: web.Request) -> web.Response:
        return await self.send_job(request.match_info["job"])

    async def send_job(self, jid: str) -> web.Response:
        """Put a slice set up here on its printer (nothing starts), and note on the shelf where it went."""
        mine = self.jobs.get(jid)
        if mine is None:
            return _err(404, "That wasn't set up here, or the box restarted since.")
        resp = await self._pass("POST", f"{jid}/send", {})
        if resp.status != 200:
            return resp
        models = mine.get("models") or [{"shelf": mine["shelf"], "copies": mine["copies"]}]
        each = None
        if len(models) == 1:              # one model's time and grams per copy: the plan's rough guess next time (plan.py)
            try:
                async with self.session.get(f"{self.slicer}/slice/{jid}") as r:
                    job = await r.json(content_type=None) if r.status == 200 else {}
                est = job.get("estimate") or {} if len(job.get("plates") or []) < 2 else {}    # one plate: every copy in it
                if est.get("seconds"):
                    each = {"seconds": est["seconds"] / models[0]["copies"], "grams": (est.get("grams") or 0) / models[0]["copies"] or None}
            except (ClientError, OSError, asyncio.TimeoutError, ValueError):
                pass
        p = self.printers().get(mine["printer"], {})
        for m in models:
            try:
                it = self.item(m["shelf"])
            except web.HTTPNotFound:
                continue
            it["last"] = {"printer": mine["printer"], "printer_name": p.get("name", mine["printer"]), "copies": m["copies"],
                          "material": mine["material"], "color": mine["color"], "at": self.now(),
                          "filament": mine.get("filament"), "filament_name": mine.get("filament_name"),
                          "how": m.get("how") or mine.get("how") or how_of(it),
                          "sides": sides_key(it),
                          "each": each or (it.get("last") or {}).get("each")}
            it["prints"] = it.get("prints", 0) + 1
            self.save(it)
        return resp

    async def get_layers(self, request: web.Request) -> web.Response:
        """A setup's layers, to show its slice cut at a layer (design/bench-look/, C): the heights and every wall, or
        one layer's paths."""
        n = request.match_info.get("n")
        return await self._pass("GET", f"{request.match_info['job']}/layers" + (f"/{n}" if n is not None else ""))

    async def _pass(self, method: str, path: str, body: Any = None) -> web.Response:
        if not re.fullmatch(r"[0-9a-f]{12}(/send|/layers(/\d+)?)?", path):
            raise web.HTTPNotFound()
        try:
            async with self.session.request(method, f"{self.slicer}/slice/{path}", json=body) as r:
                return web.Response(status=r.status, body=await r.read(), content_type="application/json")
        except (ClientError, OSError, asyncio.TimeoutError):
            return _err(503, "The box's slicer isn't answering. It may be starting.")


def plate_parts(it: dict, copies: int, how: dict) -> List[dict]:
    """A model's parts as the slicer takes them, copies times over, each on the side it goes down on."""
    brim = {"brim": how["brim"]} if how.get("brim") else {}      # null: each part's own, as it last printed
    return [{**{k: p[k] for k in ("scale", "brim") if p.get(k) is not None}, **lay_of(it, n), **brim,
             "model": p["model"], "copies": min(200, p["copies"] * copies)} for n, p in enumerate(it["parts"])]


# ── which side down (design/orientation/): per part, the slicer's lay and down ──

def _same(a: Any, b: Any) -> bool:
    return isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 3 and sum(x * y for x, y in zip(a, b)) > 0.996


def own_lay(p: dict) -> dict:
    """The part's own way down: as a printer's plate had it (gathered), else laid flat for you when its flattest side
    isn't down (the printer's Print does the same), else as in the file."""
    if p.get("lay") in ("flat", "side", "file"):
        return {"lay": p["lay"], **({"down": p["down"]} if p["lay"] == "side" and p.get("down") else {})}
    return {"lay": "flat"} if (p.get("lying") or {}).get("flat_better") else {"lay": "file"}


def lay_of(it: dict, n: int) -> dict:
    """{lay, down?} for part n: the side picked on the box, else the part's own."""
    picked = (it.get("sides") or {}).get(str(n))
    return dict(picked) if picked else own_lay(it["parts"][n])


def _normal_of(p: dict, lay: dict) -> Optional[list]:
    if lay["lay"] == "side":
        return lay.get("down")
    return (p.get("lying") or {}).get("flat_normal") if lay["lay"] == "flat" else None


def sides_key(it: dict) -> str:
    """What the sides change: a plan's fit check is asked again when it does."""
    return json.dumps(it.get("sides") or {}, sort_keys=True)


def pick_side(it: dict, want: dict) -> dict:
    """The sides kept after a pick: {part, lay: auto | file | flat | side, down}. A pick the same as the part's own way
    hands it back to it (auto), so it follows that way again. Raises ValueError in words."""
    parts = it.get("parts") or []
    n = want.get("part", 0)
    if not isinstance(n, int) or not 0 <= n < len(parts):
        raise ValueError(f"It has {len(parts)} part{'s' if len(parts) != 1 else ''}: send part 0{f' to {len(parts) - 1}' if len(parts) > 1 else ''}.")
    p, lay, down = parts[n], want.get("lay"), want.get("down")
    sides = dict(it.get("sides") or {})
    if lay == "auto":
        sides.pop(str(n), None)
        return sides
    if lay not in ("file", "flat", "side"):
        raise ValueError(f"{lay!r} isn't a way down: it's auto (the part's own), file, flat or side (with down).")
    lying = p.get("lying") or {}
    if lay == "side":
        if not (isinstance(down, list) and len(down) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in down)):
            raise ValueError("A side is its outward normal, down: [x, y, z].")
        length = math.sqrt(sum(x * x for x in down))
        if length < 1e-6:
            raise ValueError("A side is its outward normal, down: [x, y, z].")
        down = [x / length for x in down]
        if lying.get("sides") and not any(_same(down, s["normal"]) for s in lying["sides"]) and down[2] > -0.996:
            raise ValueError("It can't rest on that side.")
        if down[2] < -0.996:
            lay = "file"
        elif _same(down, lying.get("flat_normal")):
            lay = "flat"
    if lay == "flat" and not lying.get("flat_normal"):
        raise ValueError("The box can't tell its flattest side: it couldn't read the model's shape.")
    pick = {"lay": lay, **({"down": down} if lay == "side" else {})}
    own = own_lay(p)
    if pick["lay"] == own["lay"] and (pick["lay"] != "side" or _same(pick["down"], own.get("down"))):
        sides.pop(str(n), None)
    else:
        sides[str(n)] = pick
    return sides


def sides_view(it: dict) -> dict:
    """Each part's sides, as the slicer measured them, and which is down: picked here, or its own (and what that is)."""
    gathered = it.get("from") or None
    out = []
    for n, p in enumerate(it.get("parts") or []):
        lay, own = lay_of(it, n), own_lay(p)
        out.append({"n": n, "name": p.get("name"), "lying": p.get("lying"), **lay, "normal": _normal_of(p, lay),
                    "picked": str(n) in (it.get("sides") or {}),
                    "own": {**own, "normal": _normal_of(p, own),
                            "why": "plate" if gathered and p.get("lay") else "flat" if own["lay"] == "flat" else "file"}})
    return {"id": it["id"], "parts": out, "from": (gathered or {}).get("printer_name")}


class SlicerSaid(Exception):
    def __init__(self, status: int, words: str):
        super().__init__(words)
        self.status, self.words = status, words


def plate_name(parts: List[str], gcode: str) -> str:
    """A gathered plate's name: its one part's (bracket.stl → Bracket), or the G-code's as Orca named it, without
    the copies, plate, material and time (bushing_x25_1of2_PETG_2h26m.gcode → Bushing)."""
    if len(parts) == 1 and parts[0]:
        return model_name(parts[0])
    stem = re.sub(r"\.(gcode|gco|g)$", "", Path(gcode).name, flags=re.I)
    stem = re.sub(r"(_x\d+)?(_\d+of\d+)?(_[A-Z]+)?(_[\dhms]+)?$", "", stem)
    return model_name(stem or (parts[0] if parts else "Model"))


def _err(status: int, words: str) -> web.Response:
    return web.json_response({"error": words}, status=status)
