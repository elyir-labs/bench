"""Several models from the Bench Box's shelf at once (design/bench-several/, C, picked 10 October 2026): the plan.

  POST /bench/plan          {models: [{shelf, copies, printer?, bed?: "own", out?}], wait?}: the plan, a bed per printer
  POST /bench/plan/print    {beds} (as the plan gave them) or {models}: each bed into Up next, at the end; nothing starts

The rules, as drawn: models in the same filament, purpose, supports and settings share a bed when it fits. What doesn't
fit goes to another free printer with that filament loaded, else a second bed on the same printer, after. Another
filament goes to another printer: the soonest free with it loaded first (busy ones in the order they finish), then one
that asks what's loaded (a Kobra), then a second bed on a printer that has it. Nothing has it loaded: it waits. Each
model prints in the filament it was last printed in; one never printed takes the filament loaded on the most printers,
as the model page does (on a printer asked for, the most widely loaded one it has). The box never adds copies.

The printer order is the app's printOn() (shelf.ts: soonest free with it loaded, then one that asks) over the same
intents the queue reads (bench_queue.py), so the plan and the queue pick alike; the plan's rules live here only.

Whether a group fits one bed is the slicer's arrange, without slicing (POST /slice/fit, part null), one check per
group, kept for a quarter of an hour. A plan asked for answers at once with what's known (`checking`: true while any
check runs; such a bed has fits null) and the screens ask again; `wait` answers once every check is in.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any, Callable, Dict, List, Optional

from aiohttp import ClientError, web

from bench_queue import FREE, asks_whats_loaded, color_name, near
from shelf import SlicerSaid, how_of, plate_parts, sides_key

FIT_KEEP = 900           # seconds a group's fit is kept: a re-plan after a move asks again only for what changed
FIT_RETRY = 30           # a check that failed is asked again after this
MOST_BEDS = 12           # beds for one group, at most: a plan never runs away
WAIT_AT_MOST = 60        # seconds Print all waits for the checks


# ── the plan itself: pure ──

def printer_rows(printers: Dict[str, dict], intents: Dict[str, Optional[dict]], joined: Dict[str, dict],
                 holding: set) -> List[dict]:
    """Each printer as the plan sees it, soonest free first (shelf.ts whicheverIsFree): ready, done with its bed to clear,
    printing (the soonest done first), then stopped or off. One that holds a queued print is busy with it."""
    rows = []
    for pid, p in printers.items():
        i = intents.get(pid) or {}
        st = i.get("state")
        rank = 0 if st == "ready" else 1 if st in FREE else 2 if st in ("printing", "preparing") else 3
        queued = pid in holding and rank < 3
        spools = [{"material": s["material"].upper(), "color": s.get("color"), "slot": None if s.get("direct") else s["slot"] + 1}
                  for s in i.get("spools") or [] if s.get("status") in ("ready", "low") and s.get("material")]
        j = joined.get(pid) or {}
        rows.append({"id": pid, "name": p.get("name", pid), "rank": 2 if queued else rank, "state": st, "queued": queued,
                     "remaining": (i.get("job") or {}).get("remaining_s"), "eta_clock": (i.get("job") or {}).get("eta_clock"),
                     "spools": sorted(spools, key=lambda s: s["slot"] or 0), "count": len(i.get("spools") or []),
                     "asks": bool(i) and asks_whats_loaded(i), "materials": (j.get("entry") or {}).get("materials"),
                     "error": j.get("error")})
    soon = lambda r: r["remaining"] if r["rank"] == 2 and not r["queued"] and r["remaining"] is not None else 9e9
    return sorted(rows, key=lambda r: (r["rank"], soon(r), r["name"].lower()))


def fil_words(f: dict) -> str:
    return f.get("filament_name") or " ".join(x for x in (color_name(f.get("color")), f["material"]) if x)


def _same(a: dict, b: dict) -> bool:
    """Two models can share a bed: one filament (one of yours, or a material and color) and one way of printing."""
    fa, fb = a["filament"], b["filament"]
    return fa["material"] == fb["material"] and near(fa.get("color"), fb.get("color")) and near(fb.get("color"), fa.get("color")) \
        and (not fa.get("filament") or not fb.get("filament") or fa["filament"] == fb["filament"]) \
        and all(a["how"].get(k) == b["how"].get(k) for k in ("purpose", "supports", "settings"))


def _slot(r: dict, f: dict) -> Optional[dict]:
    return next((s for s in r["spools"] if s["material"] == f["material"] and near(s.get("color"), f.get("color"))), None)


def _can_take(r: dict, f: dict) -> bool:
    return r["materials"] is None or f["material"] in r["materials"] or bool(f.get("filament"))   # a named one brings its own


def _usable(r: dict) -> bool:
    return r["rank"] < 3 and not r["error"]


def _fresh(r: Optional[dict], rows: List[dict]) -> Optional[dict]:
    """What a model never printed prints in, as the model page picks: the filament loaded on the most printers (on the
    printer asked for, the most widely loaded one it has). Ties go to the soonest free."""
    usable = [x for x in rows if _usable(x)]
    on = lambda s: sum(1 for x in usable if _slot(x, s))
    spools = r["spools"] if r else [s for x in usable for s in x["spools"]]
    return max(spools, key=on) if spools else None


def _resolve(m: dict, rows: List[dict], by: Dict[str, dict]) -> Optional[str]:
    """The model's filament, and whether the printer asked for can take it: the words why not, or None."""
    r = by.get(m["printer"]) if m["printer"] else None
    if m["printer"]:
        if r is None:
            return "That printer isn't on the bench any more."
        if r["error"]:
            return f"The box can't set a model up for {r['name']} yet."
        if r["rank"] == 3:
            return f"{r['name']} is stopped or off."
    if not m["filament"]:
        s = _fresh(r, rows)
        if s is None:
            return f"Nothing is loaded on {r['name']}." if r else "No printer has a filament loaded to print it in."
        m["filament"], m["first"] = {"material": s["material"], "color": s.get("color"), "filament": None, "filament_name": None}, True
    if m["printer"]:
        f = m["filament"]
        if not _can_take(r, f):
            return f"{r['name']} has no {f['material']} settings."
        if not _slot(r, f) and not r["asks"]:
            has = list(dict.fromkeys(fil_words(s) for s in r["spools"]))[:2]
            return f"{r['name']} has {' and '.join(has)}, not {fil_words(f)}." if has else f"Nothing is loaded on {r['name']}."
    return None


def _pick(g: dict, rows: List[dict], beds_on: Dict[str, list], overflow: bool = False) -> Optional[dict]:
    f = g["filament"]
    can = [r for r in rows if _usable(r) and _can_take(r, f)]
    loaded = [r for r in can if _slot(r, f)]
    if overflow:
        return next((r for r in loaded if r["id"] not in beds_on and r["rank"] < 2), None)
    return next((r for r in loaded if r["id"] not in beds_on), None) \
        or next((r for r in can if r["asks"] and r["id"] not in beds_on), None) \
        or next(iter(loaded), None)


def plan(models: List[dict], rows: List[dict], fit: Callable[[str, list], Optional[dict]], now: float) -> dict:
    """models: [{shelf, name, copies, picture, filament: {material, color, filament, filament_name} | None (never printed),
    how, printer (asked for) | None, own (its own bed), each: {seconds, grams} per copy | None}], in the order picked.
    fit(printer, [(model, copies)]) → {counts: [copies on one bed, per model]} | {error} | None (not known yet)."""
    by = {r["id"]: r for r in rows}
    cant: List[dict] = []
    groups: List[dict] = []
    for m in models:
        why = _resolve(m, rows, by)
        if why:
            cant.append({"shelf": m["shelf"], "name": m["name"], "copies": m["copies"], "why": why})
            continue
        g = next((g for g in groups if not g["own"] and not m["own"] and g["printer"] == m["printer"] and _same(g["members"][0], m)), None)
        if g:
            g["members"].append(m)
            if not g["filament"].get("filament") and m["filament"].get("filament"):
                g["filament"] = m["filament"]
        else:
            groups.append({"printer": m["printer"], "own": m["own"], "members": [m], "filament": m["filament"]})
    groups.sort(key=lambda g: g["printer"] is None)          # one asked for a printer is placed first

    beds: List[dict] = []
    beds_on: Dict[str, list] = {}
    said: List[str] = []
    for g in groups:
        members = [(m, m["copies"]) for m in g["members"]]
        r = by[g["printer"]] if g["printer"] else _pick(g, rows, beds_on)
        for _ in range(MOST_BEDS):
            if r is None:
                beds.append(_bed(g, None, members, 1, None, now, fits=None))
                break
            got = fit(r["id"], members)
            if got is None or "error" in got:
                b = _bed(g, r, members, len(beds_on.get(r["id"], [])) + 1, beds_on.get(r["id"]), now, fits=None)
                if got:
                    b["why"] = f"{b['why']} The box couldn't check it fits: {got['error']}"
                beds.append(b)
                beds_on.setdefault(r["id"], []).append(b)
                break
            stay = [(m, min(n, c)) for (m, n), c in zip(members, got["counts"]) if c > 0]
            rest = [(m, n - c) for (m, n), c in zip(members, got["counts"]) if n > c]
            if not stay:
                cant += [{"shelf": m["shelf"], "name": m["name"], "copies": n, "why": f"It doesn't fit on {r['name']}'s bed."}
                         for m, n in members]
                break
            b = _bed(g, r, stay, len(beds_on.get(r["id"], [])) + 1, beds_on.get(r["id"]), now, fits=True)
            beds.append(b)
            beds_on.setdefault(r["id"], []).append(b)
            if not rest:
                break
            b["split"] = True
            nxt = None if g["printer"] else _pick(g, rows, beds_on, overflow=True)
            what = ", ".join(f"{m['name']} × {n}" for m, n in rest)
            said.append(f"Not all of it fits one bed on {r['name']}: {what} go on {nxt['name']}, which has {fil_words(g['filament'])} too."
                        if nxt else f"Not all of it fits one bed on {r['name']}: {what} go on a second bed there, after the first.")
            r, members = nxt or r, rest
        else:
            cant += [{"shelf": m["shelf"], "name": m["name"], "copies": n, "why": "More than the box plans at once: print the rest after."}
                     for m, n in members]

    order = list(dict.fromkeys(b["printer"] for b in beds))      # one card per printer, as they were given; waiting last
    beds.sort(key=lambda b: (b["printer"] is None, order.index(b["printer"]), b["order"]))
    ends = [b["done_at"] for b in beds if b["printer"]]
    return {"beds": beds, "cant": cant, "said": said,
            "printers": len([p for p in order if p]),
            "free_left": [{"id": r["id"], "name": r["name"]} for r in rows if _usable(r) and r["rank"] < 2 and r["id"] not in beds_on],
            "done_at": max(ends) if ends and all(e is not None for e in ends) else None}


def _bed(g: dict, r: Optional[dict], members: list, order: int, before: Optional[list], now: float, fits: Optional[bool]) -> dict:
    f, how = g["filament"], g["members"][0]["how"]
    brims = {m["how"].get("brim") for m, _ in members}
    s = _slot(r, f) if r else None
    words = fil_words(f)
    if r is None:
        when, start = {"kind": "waits"}, None
        why = f"{words} isn't loaded on any printer. It waits in Up next until one has it."
    elif order > 1:
        when, start = {"kind": "after"}, (before[-1]["done_at"] if before else None)
        why = f"Bed {order} on {r['name']}, after the one before it: {r['name']} asks about its bed again."
    elif r["queued"]:
        when, start = {"kind": "queued"}, None
        why = f"After the print already waiting for {r['name']} in Up next."
    elif r["rank"] == 2:
        start = now + r["remaining"] if r["remaining"] is not None else None
        when = {"kind": "next", "clock": r["eta_clock"], "at": start}
        why = f"Waits in Up next until {r['name']} is done and its bed is clear."
    else:
        when, start = {"kind": "now" if r["rank"] == 0 else "clear"}, now
        why = (f"{words} in slot {s['slot']}." if s and s["slot"] and r["count"] > 1 else f"It has {words}.") if s else \
            f"It asks what's loaded when it starts: put {words} on."
        if r["rank"] == 1:
            why = f"Free once its bed is cleared. {why}"
    each = [m.get("each") for m, _ in members]
    secs = sum(e["seconds"] * n for e, (_, n) in zip(each, members)) if all(e and e.get("seconds") for e in each) else None
    grams = sum(e["grams"] * n for e, (_, n) in zip(each, members)) if all(e and e.get("grams") for e in each) else None
    return {"id": f"{r['id'] if r else 'waits'}:{order}:{members[0][0]['shelf']}",
            "printer": r["id"] if r else None, "printer_name": r["name"] if r else None, "order": order,
            "material": f["material"], "color": f.get("color"), "slot": s["slot"] if s else None,
            "filament": f.get("filament"), "filament_name": f.get("filament_name"), "words": words,
            "asks": bool(r and not s and r["asks"]),
            "purpose": how["purpose"], "supports": how.get("supports"), "settings": how.get("settings") or {},
            "brim": brims.pop() if len(brims) == 1 else "mixed",
            "models": [{"shelf": m["shelf"], "name": m["name"], "copies": n, "of": m["copies"], "picture": m.get("picture"),
                        "first": bool(m.get("first")), "chosen": bool(m.get("chosen"))} for m, n in members],
            "fits": fits, "split": False, "seconds": round(secs) if secs else None, "grams": round(grams, 1) if grams else None,
            "rough": True, "when": when, "start_at": start,
            "done_at": start + secs if start is not None and secs else None, "why": why}


# ── on the box ──

class Planner:
    def __init__(self, shelf, queue, printers: Callable[[], Dict[str, dict]], now=time.time):
        self.shelf, self.queue, self.printers, self.now = shelf, queue, printers, now
        self.fits: Dict[str, dict] = {}            # a group on a printer → {at, counts | error}
        self.checks: Dict[str, asyncio.Task] = {}

    def routes(self, app: web.Application) -> None:
        app.router.add_post("/bench/plan", self.post_plan)
        app.router.add_post("/bench/plan/print", self.post_print)

    def stop(self) -> None:
        for t in self.checks.values():
            t.cancel()

    async def post_plan(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            models, gone, out = self._models(body.get("models"))
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            return _err(400, str(e) if str(e).startswith("Send") else MODELS)
        got = await self.make(models, wait=bool(body.get("wait") or request.query.get("wait")))
        return web.json_response({**got, "cant": gone + got["cant"], "out": out})

    async def post_print(self, request: web.Request) -> web.Response:
        """Print all: each bed in Up next, after what's already waiting. From away, Add to the queue (away.py): the
        start route is only on the box's own service."""
        try:
            body = await request.json()
            if body.get("beds") is not None:
                beds, cant = self._beds(body["beds"]), []
            else:
                models, gone, _ = self._models(body.get("models"))
                got = await self.make(models, wait=True)
                beds, cant = got["beds"], gone + got["cant"]
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            return _err(400, str(e) if str(e).startswith("Send") else "Send {beds} as the plan gave them, or {models}.")
        try:
            for b in beds:
                for m in b["models"]:
                    self.shelf.item(m["shelf"])
        except web.HTTPNotFound:
            return _err(409, "A model in the plan is no longer on the shelf. Plan it again.")
        if not beds:
            return _err(400, "Nothing in the plan can print.")
        items = [self.queue.add_bed(b, request.get("by")) for b in beds]
        self.queue.save()
        self.queue.poke.set()
        return web.json_response({"queued": [self.queue.public(it) for it in items], "cant": cant}, status=201)

    def _models(self, given: Any) -> tuple:
        if not isinstance(given, list) or not given or len(given) > 50:
            raise ValueError(MODELS)
        models, gone, out, seen = [], [], [], set()
        for x in given:
            sid, copies = str(x["shelf"]), int(x.get("copies") or 1)
            if not 1 <= copies <= 200 or sid in seen:
                raise ValueError(MODELS)
            seen.add(sid)
            try:
                it = self.shelf.item(sid)
            except web.HTTPNotFound:
                gone.append({"shelf": sid, "name": None, "copies": copies, "why": "It's no longer on the shelf."})
                continue
            if x.get("out"):
                out.append({"shelf": sid, "name": it["name"]})
                continue
            last, chose = it.get("last") or {}, x.get("in") if isinstance(x.get("in"), dict) and x["in"].get("material") else None
            src = chose or last
            fil = {"material": str(src["material"]).upper(), "color": src.get("color"), "filament": src.get("filament"),
                   "filament_name": src.get("filament_name")} if src.get("material") else None
            models.append({"shelf": sid, "name": it["name"], "copies": copies, "filament": fil, "how": how_of(it), "sides": sides_key(it),
                           "printer": x.get("printer") or None, "own": x.get("bed") == "own", "chosen": bool(chose),
                           # a time per copy only while it lies as it did then: another side can take hours longer
                           "each": last.get("each") if (not chose or fil["material"] == str(last.get("material") or "").upper())
                           and last.get("sides", "{}") == sides_key(it) else None,
                           "picture": f"/bench/shelf/{sid}/picture" if (self.shelf.root / sid / "picture.png").exists() else None})
        return models, gone, out

    def _beds(self, given: Any) -> List[dict]:
        if not isinstance(given, list):
            raise ValueError("Send {beds} as the plan gave them.")
        out = []
        for b in given:
            models = [{"shelf": str(m["shelf"]), "copies": int(m["copies"])} for m in b["models"]]
            if not models or not all(1 <= m["copies"] <= 200 for m in models) or not str(b.get("material") or ""):
                raise ValueError("Send each bed with its models (1 to 200 copies each) and its material.")
            if b.get("printer") and b["printer"] not in self.printers():
                raise ValueError("Send each bed with a printer on the bench, or none.")
            out.append({**{k: b.get(k) for k in ("printer", "material", "color", "filament", "filament_name")}, "models": models})
        return out

    async def make(self, models: List[dict], wait: bool = False) -> dict:
        rows = await self._rows()
        loop = asyncio.get_running_loop()
        until = loop.time() + WAIT_AT_MOST
        while True:
            asked: List[str] = []

            def fit(pid: str, members: list) -> Optional[dict]:
                k = pid + "|" + ",".join(f"{m['shelf']}x{n}:{m['how'].get('brim')}:{m.get('sides', '')}" for m, n in members)
                got = self.fits.get(k)
                if got and self.now() - got["at"] < FIT_KEEP:
                    return got
                asked.append(k)
                if k not in self.checks:
                    self.checks[k] = asyncio.create_task(self._check(k, pid, [(m["shelf"], n) for m, n in members]))
                return None

            got = plan(copy.deepcopy(models), rows, fit, self.now())
            running = [self.checks[k] for k in asked if k in self.checks]
            if not asked or not wait or loop.time() >= until:
                break
            if running:
                await asyncio.wait(running, timeout=until - loop.time())
        return {**got, "checking": bool(asked), "ahead": len(self.queue.items)}

    async def _rows(self) -> List[dict]:
        printers = dict(self.printers())
        missing = [pid for pid in printers if pid not in self.queue.intents]
        await asyncio.gather(*(self.queue._intent(pid, printers[pid]) for pid in missing))
        joined = dict(zip(printers, await asyncio.gather(*(self.shelf._join(pid) for pid in printers))))
        holding = {it["printer"] for it in self.queue.items if it["state"] in ("setting", "ready")} | \
                  {it["on"] for it in self.queue.items if it.get("on")}
        return printer_rows(printers, self.queue.intents, joined, holding)

    async def _check(self, k: str, pid: str, members: List[tuple]) -> None:
        """Arrange the group on pid's bed without slicing: how many copies of each model one bed holds."""
        try:
            j = await self.shelf._join(pid)
            if "error" in j:
                raise SlicerSaid(409, j["error"])
            items = [await self.shelf._models(self.shelf.item(sid)) for sid, _ in members]
            for again in (False, True):
                parts = [p for it, (_, n) in zip(items, members) for p in plate_parts(it, n, how_of(it))]
                async with self.shelf.session.post(f"{self.shelf.slicer}/slice/fit", json={"printer": pid, "parts": parts, "part": None}) as r:
                    body = await r.json(content_type=None)
                if r.status == 400 and "no such model" in str(body.get("error")) and not again:
                    items = [await self.shelf._upload(it) for it in items]
                    continue
                break
            if r.status != 200:
                raise SlicerSaid(r.status, body.get("error") or f"The slicer said {r.status}.")
            counts, i, per = body["counts"], 0, []
            for it in items:
                per.append(min(counts[i + j] // max(1, p["copies"]) for j, p in enumerate(it["parts"])))
                i += len(it["parts"])
            self.fits[k] = {"at": self.now(), "counts": per}
        except web.HTTPNotFound:
            self.fits[k] = {"at": self.now() - FIT_KEEP + FIT_RETRY, "error": "a model is no longer on the shelf"}
        except SlicerSaid as e:
            self.fits[k] = {"at": self.now() - FIT_KEEP + FIT_RETRY, "error": e.words}
        except (ClientError, OSError, asyncio.TimeoutError, ValueError, KeyError):
            self.fits[k] = {"at": self.now() - FIT_KEEP + FIT_RETRY, "error": "the box's slicer isn't answering"}
        finally:
            self.checks.pop(k, None)


MODELS = "Send {models: [{shelf, copies (1 to 200), printer?, bed?: \"own\", out?}]}, each model once."


def _err(status: int, words: str) -> web.Response:
    return web.json_response({"error": words}, status=status)
