"""The Bench Box's queue (design/bench-queue/, Queue A): prints from the shelf that wait for a printer.

  GET    /bench/queue                 what's waiting, in order, each with where it stands in words
  POST   /bench/queue                 {shelf, copies, material, color, filament?, filament_name?}: add one at the end
  PUT    /bench/queue                 [ids]: the new order
  DELETE /bench/queue/{id}            take it out
  POST   /bench/queue/{id}/start      {anyway?, confirm?}: someone said the bed is clear: send it, the printer's check, start

A bed of several shelf models (design/bench-several/, C; plan.py) is one item with `models` [{shelf, name, copies}],
sliced together as one plate, and `on`: the printer the plan gave it. It waits for that printer, and only goes to whichever
is free when that printer can't take it any more (off the bench, or its filament taken off).

Each goes to the first printer that's free (or free once its bed is cleared), isn't holding another queued print, and has
its filament loaded. The box sets it up for that printer, and then it waits for a person: the printer's tile on the bench
and the queue's row ask for the bed ("Desk is next: clear its bed"). Copies that don't fit one bed go back in the queue,
right behind, for the next free printer. A printer that starts something else meanwhile lets its queued print go back to
waiting. Nothing starts without someone saying the bed is clear.

From away (bench/away.py) a paired phone may add one, never start one: the start route is only on the box's own
service, which is only on the Wi-Fi. Such an item carries `by` (the phone's name) and `away: true`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any, Callable, Dict, List, Optional

from aiohttp import ClientError, web

from shelf import how_of

log = logging.getLogger("bench.queue")

LOOK_EVERY = 10          # seconds between looks at the printers
FREE = ("ready", "finished")
SAME = 70                # the intent layer's "same colour" distance


def near(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return a == b or not b
    try:
        x, y = ([int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in (a, b))
    except ValueError:
        return a.lower() == b.lower()
    return sum((p - q) ** 2 for p, q in zip(x, y)) ** 0.5 < SAME


def loaded_slot(intent: dict, material: str, color: Optional[str]) -> Optional[dict]:
    """The loaded spool a print in this filament would use: {slot} (1-based, None for a printer's one spool), or None."""
    spools = [s for s in intent.get("spools") or [] if s.get("status") in ("ready", "low") and s.get("material")]
    for s in spools:
        if s["material"].upper() == material.upper() and near(s.get("color"), color):
            return {"slot": None if s.get("direct") else s["slot"] + 1}
    return None


def asks_whats_loaded(intent: dict) -> bool:
    """One spool nobody has described (a Kobra just added): its own check asks at the start what's on it."""
    spools = intent.get("spools") or []
    return len(spools) == 1 and bool(spools[0].get("direct")) and not (
        spools[0].get("status") in ("ready", "low") and spools[0].get("material"))


class Queue:
    def __init__(self, shelf, printers: Callable[[], Dict[str, dict]], now=time.time):
        self.shelf, self.printers, self.now = shelf, printers, now
        self.file = shelf.root / "queue.json"
        try:
            self.items: List[dict] = json.loads(self.file.read_text())
        except (OSError, ValueError):
            self.items = []
        for it in self.items:                       # a slice in hand when the box stopped is gone with it: set up again
            if it["state"] == "setting":
                it.update(state="waiting", printer=None, job=None)
        self.intents: Dict[str, dict] = {}
        self.poke = asyncio.Event()
        self.looking = asyncio.Lock()               # one look at a time: the box's own loop, and one asked for

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1))
        os.replace(tmp, self.file)

    # ── http ──

    def routes(self, app: web.Application) -> None:
        app.router.add_get("/bench/queue", self.get_queue)
        app.router.add_post("/bench/queue", self.post_queue)
        app.router.add_put("/bench/queue", self.put_order)
        app.router.add_delete("/bench/queue/{id}", self.delete_item)
        app.router.add_post("/bench/queue/{id}/start", self.post_start)

    def public(self, it: dict) -> dict:
        p = self.printers().get(it.get("printer") or "", {})
        return {**{k: it.get(k) for k in ("id", "shelf", "name", "copies", "material", "color", "filament_name", "state", "printer",
                                          "plate", "error", "by", "on", "grams")}, "away": bool(it.get("away")),
                "bed": "models" in it,
                "models": [{k: m[k] for k in ("shelf", "name", "copies")} for m in models_of(it)],
                "on_name": self.printers().get(it.get("on") or "", {}).get("name"),
                "printer_name": p.get("name"), "time": it.get("time"), "line": self.line(it)}

    def line(self, it: dict) -> str:
        """Where it stands, in words, for its row."""
        what = " ".join(x for x in (color_name(it.get("color")), it.get("filament_name") or it["material"].upper()) if x)
        name = self.printers().get(it.get("printer") or "", {}).get("name", "")
        if it["state"] == "setting":
            return f"{what} · setting it up for {name}"
        if it["state"] == "ready":
            return f"{what} · {name} is free: clear its bed"
        if it.get("error"):
            return f"{what} · {it['error']}"
        if it.get("on"):
            on = self.printers().get(it["on"], {}).get("name", "")
            intent = self.intents.get(it["on"]) or {}
            if intent.get("state") in FREE:
                return f"{what} · {on}'s next, after the bed before it"
            if intent.get("state") in ("printing", "preparing", "paused"):
                eta = (intent.get("job") or {}).get("eta_clock")
                return f"{what} · {on}'s next, after its print" + (f", about {eta}" if eta else "")
            return f"{what} · waits for {on}"
        if not any(loaded_slot(i, it["material"], it.get("color")) or asks_whats_loaded(i) for i in self.intents.values() if i):
            return f"{what} · waits: no printer has it loaded"
        return f"{what} · waits for a printer with it to be free"

    async def get_queue(self, request: web.Request) -> web.Response:
        return web.json_response([self.public(it) for it in self.items])

    async def post_queue(self, request: web.Request) -> web.Response:
        try:
            want = await request.json()
            shelf_id, copies = str(want["shelf"]), int(want.get("copies") or 1)
            if not 1 <= copies <= 200:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "Send {shelf, copies (1 to 200), material, color}."}, status=400)
        model = self.shelf.item(shelf_id)
        it = {"id": secrets.token_hex(6), "shelf": shelf_id, "name": model["name"], "copies": copies,
              "material": str(want.get("material") or "PLA").upper(), "color": want.get("color"), "state": "waiting",
              "filament": want.get("filament") or None, "filament_name": want.get("filament_name") or None,
              "printer": None, "job": None, "plate": None, "added": self.now()}
        if request.get("by"):
            it.update(by=request["by"], away=True)
        self.items.append(it)
        self.save()
        self.poke.set()
        return web.json_response(self.public(it), status=201)

    def add_bed(self, bed: dict, by: Optional[str] = None) -> dict:
        """A bed of the plan (plan.py) at the end of the queue: {printer|None, material, color, filament?, filament_name?,
        models: [{shelf, copies}]}. Each shelf id must be on the shelf (HTTPNotFound otherwise)."""
        models = [{"shelf": m["shelf"], "name": self.shelf.item(m["shelf"])["name"], "copies": int(m["copies"])} for m in bed["models"]]
        it = {"id": secrets.token_hex(6), "models": models, "material": str(bed.get("material") or "PLA").upper(),
              "color": bed.get("color"), "state": "waiting", "filament": bed.get("filament") or None,
              "filament_name": bed.get("filament_name") or None, "on": bed.get("printer") or None,
              "printer": None, "job": None, "plate": None, "added": self.now()}
        set_models(it, models)
        if by:
            it.update(by=by, away=True)
        self.items.append(it)
        return it

    async def put_order(self, request: web.Request) -> web.Response:
        try:
            order = [str(x) for x in await request.json()]
        except (ValueError, TypeError):
            return web.json_response({"error": "Send the ids in their new order."}, status=400)
        by = {it["id"]: it for it in self.items}
        if sorted(order) != sorted(by):
            return web.json_response({"error": "The queue changed meanwhile: look again."}, status=409)
        self.items = [by[i] for i in order]
        self.save()
        self.poke.set()
        return web.json_response([self.public(it) for it in self.items])

    async def delete_item(self, request: web.Request) -> web.Response:
        it = self._find(request.match_info["id"])
        await self._let_go(it)
        self.items.remove(it)
        self.save()
        return web.json_response({"gone": it["id"]})

    def _find(self, qid: str) -> dict:
        it = next((x for x in self.items if x["id"] == qid), None)
        if it is None:
            raise web.HTTPNotFound(text="not in the queue")
        return it

    async def _let_go(self, it: dict) -> None:
        if it.get("job") and it["state"] in ("setting", "ready"):
            async with self.shelf.session.delete(f"{self.shelf.slicer}/slice/{it['job']}"):
                pass

    # ── someone said the bed is clear ──

    async def post_start(self, request: web.Request) -> web.Response:
        it = self._find(request.match_info["id"])
        body = await request.json() if request.can_read_body else {}
        if it["state"] != "ready":
            return web.json_response({"error": "It isn't set up for a printer yet."}, status=409)
        pid, p = it["printer"], self.printers().get(it["printer"])
        moon = f"http://{p['host']}:{p.get('moonraker_port', 7125)}"
        intent = await self._intent(pid, p)
        if not intent or intent.get("state") not in FREE:       # it started something else: never on top of it
            await self._back(it, f"{p['name']} isn't free any more")
            return web.json_response({"error": f"{p['name']} isn't free any more. It's back in the queue."}, status=409)
        filename = it.get("sent")                  # already on the printer when its own check said no, and then anyway
        if not filename:
            resp = await self.shelf.send_job(it["job"])
            if resp.status != 200:
                return resp
            filename = json.loads(resp.body)["sent"]
        try:
            action = {"action": "start_file", "args": {"filename": filename}}
            if not body.get("anyway"):
                async with self.shelf.session.get(f"{moon}/printer/intent/check_print", params={"filename": filename}) as r:
                    check = (await r.json()).get("result") if r.status == 200 else None
                yes = next((a for a in (check or {}).get("actions") or [] if a.get("id") == "confirm_spool"), None)
                if body.get("confirm") and check and check.get("ask") and yes:
                    action = {"action": "confirm_spool", "args": yes.get("args") or {}}   # it remembers the spool, then starts
                elif check and (not check.get("ok", True) or check.get("colour")):
                    it["sent"] = filename
                    self.save()
                    return web.json_response({"refused": check}, status=409)
            async with self.shelf.session.post(f"{moon}/printer/intent/action", json=action) as r:
                if r.status >= 300:
                    raise ClientError(f"{r.status}")
        except (ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
            return web.json_response({"error": f"{p['name']} didn't start it ({e}). It's on {p['name']}'s Print."}, status=502)
        self.items.remove(it)
        self.save()
        self.poke.set()
        return web.json_response({"started": filename, "printer": pid})

    # ── the box works through it ──

    async def run_forever(self) -> None:
        while True:
            try:
                await self.look()
            except Exception:
                log.exception("the queue")
            self.poke.clear()
            try:
                await asyncio.wait_for(self.poke.wait(), LOOK_EVERY)
            except asyncio.TimeoutError:
                pass

    async def _intent(self, pid: str, p: dict) -> Optional[dict]:
        try:
            async with self.shelf.session.get(f"http://{p['host']}:{p.get('moonraker_port', 7125)}/printer/intent") as r:
                got = (await r.json()).get("result") if r.status == 200 else None
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            got = None
        got = got.get("intent", got) if isinstance(got, dict) else None
        self.intents[pid] = got
        return got

    async def look(self) -> None:
        async with self.looking:
            await self._look()

    async def _look(self) -> None:
        printers = self.printers()
        for pid, p in printers.items():
            await self._intent(pid, p)
        # a printer holding a queued print that started something else: that print waits again
        for it in self.items:
            if it["state"] in ("setting", "ready") and (self.intents.get(it["printer"]) or {}).get("state") not in FREE:
                await self._back(it, None)
        # a slice finished: one bed's worth stays with that printer, the rest goes back in the queue
        for it in list(self.items):
            if it["state"] == "setting":
                await self._follow(it)
        taken = {it["printer"] for it in self.items if it["state"] in ("setting", "ready")}
        for it in self.items:
            if it["state"] != "waiting":
                continue
            pid = self._printer_for(it, taken)
            if pid:
                taken.add(pid)
                await self._set_up(it, pid)

    def _printer_for(self, it: dict, taken: set) -> Optional[str]:
        """The first free printer with its filament (ready ones before those whose bed still has to be cleared), then one
        whose one spool nobody has described, which asks at the start. A bed the plan gave a printer waits for that one."""
        on = it.get("on")
        if on:
            intent = self.intents.get(on)
            if on in self.printers() and not (intent and not loaded_slot(intent, it["material"], it.get("color"))
                                              and not asks_whats_loaded(intent)):
                return on if on not in taken and intent and intent.get("state") in FREE else None
            it["on"] = None                              # it can't any more: whichever is free takes it
            self.save()
        best: Dict[tuple, str] = {}
        for pid, intent in self.intents.items():
            if pid in taken or not intent or intent.get("state") not in FREE:
                continue
            has = bool(loaded_slot(intent, it["material"], it.get("color")))
            if not has and not asks_whats_loaded(intent):
                continue
            mats = (self.shelf.joined.get(pid) or {}).get("entry", {}).get("materials")
            if mats is not None and it["material"] not in mats and not it.get("filament"):   # a named one brings its own
                continue
            best.setdefault((not has, intent["state"] != "ready"), pid)
        return best[min(best)] if best else None

    async def _set_up(self, it: dict, pid: str) -> None:
        j = await self.shelf._join(pid)
        if "error" in j:
            it["error"] = j["error"]
            return
        slot = loaded_slot(self.intents[pid], it["material"], it.get("color")) or {"slot": None}
        try:
            # each model's how as it stands now (docs/bench-how.md); a bed prints the way its first model does
            models = [await self.shelf._models(self.shelf.item(m["shelf"])) for m in models_of(it)]
            entries = [(model, m["copies"], how_of(model)) for model, m in zip(models, models_of(it))]
            want = {"material": it["material"], "color": it.get("color"), "slot": slot["slot"],
                    "filament": it.get("filament"), "filament_name": it.get("filament_name")}
            how = entries[0][2]
            job = await self.shelf._slice_many(entries, pid, want, how)
            if job.get("missing"):
                entries = [(await self.shelf._upload(model), n, h) for model, n, h in entries]
                job = await self.shelf._slice_many(entries, pid, want, how)
        except (web.HTTPNotFound,):
            it["error"] = "it's no longer on the shelf"
            return
        except Exception as e:                       # the slicer's own words, kept for the row
            it["error"] = getattr(e, "words", None) or "the box's slicer couldn't set it up"
            self.save()
            return
        if "id" not in job:
            it["error"] = job.get("error") or "the box's slicer couldn't set it up"
            self.save()
            return
        self.shelf.jobs[job["id"]] = {"shelf": it["shelf"], "printer": pid, "copies": it["copies"],
                                      "material": it["material"], "color": it.get("color"), "how": how,
                                      "filament": it.get("filament"), "filament_name": it.get("filament_name"),
                                      **({"models": [{"shelf": e[0]["id"], "copies": e[1], "how": e[2]} for e in entries]}
                                         if it.get("models") else {})}
        it.update(state="setting", printer=pid, job=job["id"], error=None, sizes=[len(e[0]["parts"]) for e in entries])
        self.save()

    async def _follow(self, it: dict) -> None:
        async with self.shelf.session.get(f"{self.shelf.slicer}/slice/{it['job']}") as r:
            job = await r.json() if r.status == 200 else {"state": "failed", "error": f"the slicer said {r.status}"}
        if job["state"] in ("queued", "slicing"):
            return
        if job["state"] != "done":
            it.update(state="waiting", printer=None, job=None, error=job.get("error") or "it couldn't be set up")
            self.save()
            return
        models = models_of(it)
        fit = fits_bed(job, it.get("sizes") or [len(job.get("parts") or [])], [m["copies"] for m in models])
        if any(f < m["copies"] for f, m in zip(fit, models)):
            # one bed's worth stays with this printer, set up again for just that; the rest waits right behind it
            pid = it["printer"]
            rest = {**it, "id": secrets.token_hex(6), "state": "waiting", "printer": None, "job": None, "time": None, "grams": None}
            set_models(rest, [{**m, "copies": m["copies"] - f} for f, m in zip(fit, models) if m["copies"] > f])
            self.items.insert(self.items.index(it) + 1, rest)
            await self._let_go(it)
            set_models(it, [{**m, "copies": f} for f, m in zip(fit, models) if f])
            it.update(state="waiting", printer=None, job=None)
            await self._set_up(it, pid)
            return
        est = job.get("estimate") or {}
        it.update(state="ready", time=est.get("seconds"), grams=est.get("grams"))
        self.save()

    async def _back(self, it: dict, why: Optional[str]) -> None:
        await self._let_go(it)
        it.update(state="waiting", printer=None, job=None, error=why)
        self.save()


def models_of(it: dict) -> List[dict]:
    return it.get("models") or [{"shelf": it["shelf"], "name": it["name"], "copies": it["copies"]}]


def set_models(it: dict, models: List[dict]) -> None:
    """A queued print's models changed (a bed split): its shelf, name and copies follow, as its row shows them."""
    if "models" not in it:
        it["copies"] = models[0]["copies"]
        return
    it.update(models=models, shelf=models[0]["shelf"], copies=sum(m["copies"] for m in models),
              name=", ".join(m["name"] + (f" × {m['copies']}" if m["copies"] > 1 else "") for m in models))


def fits_bed(job: dict, sizes: List[int], copies: List[int]) -> List[int]:
    """How many copies of each model on a plate (sizes: each one's count of parts) the first plate holds; all of them
    when there's one plate, or when the slicer's answer can't be read that way."""
    plates = job.get("plates") or []
    parts = job.get("parts") or []
    counts = (plates[0].get("counts") or []) if plates else []
    if len(plates) < 2 or len(counts) != len(parts) or sum(sizes) != len(parts):
        return copies
    out, k = [], 0
    for n, c in zip(sizes, copies):
        out.append(min(counts[k + j] // max(1, int(parts[k + j].get("copies") or c) // c) for j in range(n)))
        k += n
    if len(copies) == 1:
        return [max(1, out[0])]
    return out if any(out) else copies


def fits_first_bed(job: dict, copies: int) -> int:
    """How many copies of the model (one of each of its parts) the first plate holds; all of them on one plate."""
    plates = job.get("plates") or []
    if len(plates) < 2:
        return copies
    parts = job.get("parts") or []
    per = [max(1, int(p.get("copies") or copies) // copies) for p in parts]       # a part's copies in one copy of the model
    counts = plates[0].get("counts") or []
    if len(counts) != len(per):
        return copies
    return max(1, min(c // n for c, n in zip(counts, per)))


COLORS = [("White", "#F4F4F2"), ("Black", "#1C1C1E"), ("Gray", "#8A8D91"), ("Silver", "#C4C7CC"), ("Red", "#D32F2F"),
          ("Orange", "#FF8800"), ("Yellow", "#F5C542"), ("Green", "#2E9E4F"), ("Teal", "#14B8A6"), ("Blue", "#2563EB"),
          ("Navy", "#1E3A8A"), ("Purple", "#7C3AED"), ("Pink", "#EC4899"), ("Brown", "#8B5A2B"), ("Beige", "#E3D3B0")]


def color_name(hex_color: Optional[str]) -> str:
    """The palette's name for a colour (app/src/components/materials/palette.ts), '' when it's none of them."""
    best, d = "", SAME
    for name, h in COLORS:
        try:
            e = sum((int(hex_color[i:i + 2], 16) - int(h[i:i + 2], 16)) ** 2 for i in (1, 3, 5)) ** 0.5
        except (TypeError, ValueError):
            return ""
        if e < d:
            best, d = name, e
    return best
