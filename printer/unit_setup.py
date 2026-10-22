"""Setting up a Happy Hare or AFC unit from the screen (design/unit-setup/, B, stage 2).

Which unit, by its picture; which board it's wired to (the one on USB or CAN that Klipper doesn't use yet is
"Probably"), and how many slots; then the installer sets it up (`elyir-bench unit install`, installer/elyir_bench.py),
restarting Klipper once; then stage 1's Check and measure (unit_check.py) takes over, and its Ready says the old
settings are kept. Put it back (`elyir-bench unit putback`) is the way back, from a failure or from Care.

IntentTracker holds one of these at a time. Its jobs go out through work() as ("unit_scan" | "unit_install" |
"unit_putback", args); the component runs the installer command and hands each JSON line it says to heard().
"""
import time
from typing import Any, Dict, List, Optional

# rough seconds per installer step, for the progress bar (fetching is a git clone on a Pi)
STEP_SECONDS = {"fetch": 45, "settings": 45, "restart": 25, "answers": 5}
STEP_WORDS = {   # (while it runs, once done)
    "fetch": ("Fetching {program}", "Fetched {program}"),
    "settings": ("Writing its settings", "Wrote its settings"),
    "restart": ("Restarting Klipper, once", "Restarted Klipper, once"),
    "answers": ("Checking the unit answers", "The unit answers"),
}
HANDOVER_SECONDS = 60   # after the installer is done, how long the unit has to show up in Klipper's status
TITLE = "Set up a filament unit"


def _action(aid: str, label: str, primary: bool = False, **args) -> Dict[str, Any]:
    a: Dict[str, Any] = {"id": aid, "label": label, "primary": primary, "style": "default"}
    if args:
        a["args"] = args
    return a


def _versions_words(versions: List[str]) -> str:
    if len(versions) == 1:
        return versions[0]
    return ", ".join(versions[:-1]) + " or " + versions[-1]


class UnitSetup:
    """From the unit's picture to the hand-over to the check, or the way back (Put it back)."""

    def __init__(self, printer: str, now: float, step: str = "unit"):
        self.printer = printer or "The printer"
        self.step = step            # unit, board, installing, failed, installed, putting_back, put_back
        self.scan: Optional[Dict[str, Any]] = None
        self.unit: Optional[str] = None
        self.board: Optional[str] = None
        self.slots: Optional[int] = None
        self.mcu: Optional[str] = None
        self.jobs: List[tuple] = [] if step == "putting_back" else [("unit_scan", None)]
        if step == "putting_back":
            self.jobs = [("unit_putback", None)]
        self.running: Optional[str] = self.jobs[0][0] if self.jobs else None
        self.progress: Optional[Dict[str, Any]] = None   # the installer's last progress line
        self.progress_at = now
        self.started_at = now
        self.why: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self.done_at: Optional[float] = None
        self.handed_over = False

    # ---- what the catalog says ---------------------------------------------------------------

    def catalog(self) -> Dict[str, Any]:
        return (self.scan or {}).get("catalog") or {"programs": {}, "units": [], "boards": {}, "pairs": []}

    def pairs(self, unit: Optional[str] = None) -> List[Dict[str, Any]]:
        return [p for p in self.catalog()["pairs"] if p["unit"] == (unit or self.unit)]

    def pair(self) -> Optional[Dict[str, Any]]:
        return next((p for p in self.pairs() if p["board"] == self.board), None)

    def unit_info(self, unit: Optional[str] = None) -> Dict[str, Any]:
        return next((u for u in self.catalog()["units"] if u["id"] == (unit or self.unit)), {})

    def program(self) -> Dict[str, Any]:
        return self.catalog()["programs"].get(self.unit_info().get("kind"), {})

    def program_label(self) -> str:
        p = self.program()
        return f"{p['name']} {p['version']}" if p else "Its software"

    def board_info(self, board: Optional[str] = None) -> Dict[str, Any]:
        return self.catalog()["boards"].get(board or self.board or "", {})

    def found(self) -> List[Dict[str, Any]]:
        return (self.scan or {}).get("found") or []

    def probably(self) -> Optional[Dict[str, Any]]:
        return ((self.scan or {}).get("probably") or {}).get(self.unit or "")

    # ---- inputs ------------------------------------------------------------------------------

    def heard(self, msg: Dict[str, Any], now: float) -> None:
        """One line from the installer command running now."""
        if "progress" in msg:
            self.progress, self.progress_at = msg["progress"], now
            return
        if "started" in msg:
            return
        job, self.running = self.running, None
        if job == "unit_scan":
            if "catalog" in msg:
                self.scan = msg
                if self.unit:
                    self._pick_unit(self.unit)
            elif self.step in ("unit", "board"):
                self.why = msg.get("failed") or "Bench couldn't look for the unit's board."
            return
        if job == "unit_install":
            if "failed" in msg:
                self.step, self.why = "failed", str(msg["failed"])
            else:
                self.result, self.step, self.done_at = msg.get("result") or {}, "installed", now
            return
        if job == "unit_putback":
            if "failed" in msg:
                self.step, self.why = "failed", str(msg["failed"])
            else:
                self.step, self.why = "put_back", None
                r = msg.get("result") or {}
                if r.get("klipper") not in (None, "ready"):
                    self.why = f"Klipper didn't start again with them: {r.get('message') or ''}".strip()

    def answer(self, op: str, args: Dict[str, Any], kept: bool) -> bool:
        """A tap. False when it doesn't apply right now."""
        if self.running in ("unit_install", "unit_putback"):
            return False
        if op == "unit" and self.step == "unit":
            if not self.pairs(str(args.get("unit"))):
                return False
            self._pick_unit(str(args["unit"]))
            return True
        if op == "next" and self.step == "unit" and self.unit:
            self.step = "board"
            return True
        if op == "board" and self.step == "board":
            board = str(args.get("board"))
            pair = next((p for p in self.pairs() if p["board"] == board), None)
            if pair is None:
                return False
            self.board = board
            if self.slots not in pair["slots"]:
                self.slots = pair["default"]
            return True
        if op == "slots" and self.step == "board" and self.pair():
            n = args.get("slots")
            if n not in self.pair()["slots"]:
                return False
            self.slots = n
            return True
        if op == "port" and self.step == "board":
            mcu = args.get("mcu")
            if mcu not in [f["mcu"] for f in self.found()]:
                return False
            self.mcu = mcu
            return True
        if op == "scan" and self.step in ("unit", "board") and self.running is None:
            self.jobs.append(("unit_scan", None))
            self.running, self.why = "unit_scan", None
            return True
        if op == "back":
            if self.step == "board":
                self.step = "unit"
                return True
            return False
        if op in ("install", "retry") and self.step in ("board", "failed") and self._ready_to_install():
            self._install()
            return True
        if op == "putback" and self.step == "failed" and kept:
            self.step, self.why, self.progress = "putting_back", None, None
            self.jobs.append(("unit_putback", None))
            self.running = "unit_putback"
            return True
        return False

    def _pick_unit(self, unit: str) -> None:
        if unit != self.unit:
            self.board, self.slots = None, None
        self.unit = unit
        pairs = self.pairs()
        prob = self.probably()
        if prob and self.board is None:
            fam = [p for p in pairs if self.board_info(p["board"]).get("family") == prob["family"]]
            if fam:
                self.board, self.slots = fam[0]["board"], fam[0]["default"]
        if self.board is None and len(pairs) == 1:
            self.board, self.slots = pairs[0]["board"], pairs[0]["default"]
        if prob:
            self.mcu = prob["mcu"]
        elif len(self.found()) == 1:
            self.mcu = self.found()[0]["mcu"]

    def _ready_to_install(self) -> bool:
        return bool(self.pair() and self.slots and self.mcu)

    def _install(self) -> None:
        self.step, self.why, self.progress, self.result = "installing", None, None, None
        self.started_at = self.progress_at = time.time()
        self.jobs.append(("unit_install", {"unit": self.unit, "board": self.board, "slots": self.slots,
                                           "mcu": self.mcu, "kind": self.unit_info().get("kind")}))
        self.running = "unit_install"

    def take_jobs(self) -> List[tuple]:
        out, self.jobs = self.jobs, []
        return out

    # ---- what the screens draw ---------------------------------------------------------------------

    def _unit_line(self, unit: Dict[str, Any]) -> str:
        slots = sorted({n for p in self.pairs(unit["id"]) for n in p["slots"]})
        prog = self.catalog()["programs"].get(unit["kind"], {}).get("name", "")
        n = f"{slots[0]} slots" if len(slots) == 1 else f"{slots[0]} to {slots[-1]} slots"
        return f"{n} · {prog}"

    def _boards(self) -> List[Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        prob = (self.probably() or {}).get("family")
        for p in self.pairs():
            b = self.board_info(p["board"])
            fam = out.setdefault(b["family"], {"family": b["family"], "name": b["name"], "versions": [],
                                               "probably": b["family"] == prob})
            if b.get("version"):
                fam["versions"].append({"board": p["board"], "label": b["version"]})
            fam.setdefault("board", p["board"])
        for fam in out.values():
            labels = [v["label"] for v in fam["versions"]]
            pair = next(p for p in self.pairs() if p["board"] == fam["board"])
            fam["line"] = _versions_words(labels) if labels else f"{pair['slots'][0]} slots"
        return sorted(out.values(), key=lambda f: not f["probably"])

    def _found_words(self) -> str:
        found = self.found()
        prob = self.probably()
        if self.scan is None:
            return "Bench looks for the unit's board…"
        if not found:
            return ("Bench doesn't see a board on USB or CAN that Klipper doesn't use yet. "
                    "Plug the unit's board into the printer's computer, then look again.")
        if len(found) > 1:
            return f"Bench sees {len(found)} boards that Klipper doesn't use yet. Pick the unit's below."
        where = "on CAN" if found[0]["mcu"].startswith("can:") else "on USB"
        words = f"Bench sees one board {where} that Klipper doesn't use yet."
        if prob:
            name = next((b["name"] for b in self.catalog()["boards"].values() if b["family"] == prob["family"]), None)
            if name:
                words += f" It looks like a{'n' if name[:1] in 'AEIOU' else ''} {name}."
        return words

    def _where(self) -> str:
        u = self.unit_info().get("name")
        b = self.board_info().get("name")
        if self.step == "board" and u:
            return f"{TITLE} · {u}"
        if self.step in ("installing", "failed", "installed") and u and b:
            return f"{TITLE} · {u} on a{'n' if b[:1] in 'AEIOU' else ''} {b}"
        return TITLE

    def _progress(self, now: float) -> Dict[str, Any]:
        cur = (self.progress or {}).get("id") or "fetch"
        done_n = (self.progress or {}).get("done", 0)
        order = list(STEP_WORDS)
        prog = self.program_label()
        pair, board = self.pair() or {}, self.board_info()
        subs = {"fetch": "The version Bench tested.",
                "settings": f"{self.slots} slots on the {board.get('name', 'board')}, with a copy of the old ones.",
                "restart": None, "answers": None}
        steps = []
        failed = self.step == "failed"
        for i, sid in enumerate(order):
            if done_n >= len(order) or i < order.index(cur):
                state = "done"
            elif sid == cur:
                state = "failed" if failed else "now"
            else:
                state = "next"
            words = STEP_WORDS[sid][1 if state == "done" else 0].format(program=prog)
            steps.append({"id": sid, "label": words, "sub": subs[sid] if state == "done" else None, "state": state})
        total = sum(STEP_SECONDS.values())
        before = sum(STEP_SECONDS[s] for s in order[:order.index(cur)])
        within = min(STEP_SECONDS[cur] * 0.9, max(0.0, now - self.progress_at))
        spent = before + within
        left = max(0, total - spent)
        words = "Almost done" if left < 10 else ("About 2 minutes" if left > 90 else
                                                  "About a minute" if left > 45 else f"About {int(5 * round(left / 5))} seconds")
        return {"steps": steps, "pct": round(min(0.95, spent / total), 3), "words": words, "of": len(order)}

    def view(self, now: Optional[float] = None, kept: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        unit = self.unit_info()
        prog = self.program()
        step_n = {"unit": 1, "board": 2}.get(self.step, 3)
        v: Dict[str, Any] = {
            "step": self.step, "n": step_n, "of": 5, "where": self._where(),
            "looking": self.running == "unit_scan",
            "unit": self.unit, "board": self.board, "family": self.board_info().get("family"),
            "units": [{**u, "line": self._unit_line(u)} for u in self.catalog()["units"]],
            "boards": self._boards() if self.unit else [],
            "slots": ({"choices": (self.pair() or {}).get("slots", []), "value": self.slots}
                      if self.pair() and len(self.pair()["slots"]) > 1 else None),
            "found": self._found_words() if self.step in ("unit", "board") else None,
            "ports": ([{"mcu": f["mcu"], "label": f["words"]} for f in self.found()]
                      if len(self.found()) > 1 and self.step == "board" else []),
            "mcu": self.mcu,
            "guides": [{"name": p["name"], "url": p["guide"]} for p in self.catalog()["programs"].values()],
            "program": self.program_label() if prog else None,
            "headline": None, "headline_phone": None, "detail": None, "why": self.why,
            "progress": None, "note": None, "next": None, "actions": [],
        }
        acts: List[Dict[str, Any]] = []
        if self.step == "unit":
            v["headline"] = "Which unit is it?"
            v["detail"] = "An ACE Pro needs no setup: Bench finds it by itself."
            acts = [_action("unit_setup_close", "Close"), _action("unit_setup_next", "Next", primary=True)]
        elif self.step == "board":
            v["headline"] = "Which board is it wired to?"
            v["detail"] = v["found"]
            acts = [_action("unit_setup_back", "Back")]
            if not self.found():
                acts.append(_action("unit_setup_scan", "Look again", primary=True))
            else:
                acts.append(_action("unit_setup_install", "Set it up", primary=True))
        elif self.step in ("installing", "failed"):
            short = (unit.get("name") or "unit").split(" ")[0]
            v["headline"] = f"Setting up {prog.get('name', 'it')} for your {short}…"
            v["headline_phone"] = f"Setting up {prog.get('name', 'it')} on {self.printer}…"
            v["progress"] = self._progress(now)
            v["note"] = {"title": "Klipper restarts once.",
                         "text": f"Nothing is printing, so nothing is lost. {self.printer}'s screen goes quiet for about 20 seconds.",
                         "foot": "Changed your mind later? Care › Filament unit › Put it back."}
            n = self.slots or 0
            v["next"] = {"title": "Next, at the printer",
                         "text": f"Push a little filament into each of the {n} slots. {self.printer}'s screen shows each one, "
                                 "or carry on here while you stand by the unit."}
            if self.step == "failed":
                v["headline"] = f"{prog.get('name', 'Its software')} isn't set up yet."
                v["headline_phone"] = v["headline"]
                acts = [_action("unit_setup_close", "Close")]
                if kept:
                    acts.append(_action("unit_setup_putback", "Put it back"))
                acts.append(_action("unit_setup_retry", "Try again", primary=True))
        elif self.step == "installed":
            v["headline"] = f"{prog.get('name', 'Its software')} is set up."
            v["detail"] = "Bench is waiting for the unit to show up…" if not self.why else self.why
            acts = [_action("unit_setup_close", "Done", primary=True)] if self.why else []
        elif self.step == "putting_back":
            v["headline"] = "Putting your old settings back…"
            v["detail"] = f"Then Klipper restarts once. {self.printer}'s screen goes quiet for about 20 seconds."
            v["progress"] = None
        elif self.step == "put_back":
            v["headline"] = "Your old settings are back."
            v["detail"] = self.why or "Klipper restarted with them. The unit's software is off this printer."
            acts = [_action("unit_setup_close", "Done", primary=True)]
        v["actions"] = acts
        return v

    def check_frame(self, kept: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """What the check shows as part of this setup: the title, the program and the old settings row."""
        return {"title": TITLE, "program": (kept or {}).get("program") or self.program_label(),
                "kept": bool(kept)}
