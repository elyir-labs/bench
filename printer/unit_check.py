"""Checking and measuring a Happy Hare or AFC unit from the screen (design/unit-setup/, B, stage 1).

Each slot in turn: filament in (its sensor sees it, or the person says so on a unit without one), then a small motor
test with the unit's own command. Then measuring: AFC each slot to its hub, then the tube to the head; Happy Hare the
tube. Then Ready, with a summary. IntentTracker holds one of these at a time and sends its commands the way it sends
the change routine's: as "macro" steps that report back through change_done().

Neither Happy Hare nor AFC raise a G-code error for most failures. Their command returns normally and says what went
wrong on the console ("!! ..."), so a step's result is read from the console lines heard while it ran, then from the
status. Those lines are matched narrowly, on the words their source prints (Happy Hare 4.1 and 3, AFC 1.2).
"""
import re
import time
from typing import Any, Callable, Dict, List, Optional

SETTLE_SECONDS = 1.0   # Moonraker's status batch can land after the command returns: judge once it has
SECONDS = {"check": 6, "slot": 12, "tube_happy_hare": 40, "tube_afc": 60}   # rough, for the progress bar

HH_UNCALIBRATED = ("Happy Hare isn't calibrated yet. Its gear and selector are measured first, from Advanced, "
                   "then try again.")
FILAMENT_IN_PATH = "Filament is still in the unit's path. Take it out of the head first, then try again."
NOT_HOMED = "The unit couldn't find its home. Check nothing blocks the selector, then try again."
HUB_NOT_CLEAR = "Something is still in the hub. Pull it back a little, then try again."
TUBE_NO_SENSOR = {
    "happy_hare": "Happy Hare can't measure the tube without an encoder or a sensor at the head. Its length is set by hand, from Advanced.",
    "afc": "AFC can't measure the tube without a sensor where the head starts. Its length is set by hand, from Advanced.",
}


def _action(aid: str, label: str, primary: bool = False, style: str = "default", **args) -> Dict[str, Any]:
    a: Dict[str, Any] = {"id": aid, "label": label, "primary": primary, "style": style}
    if args:
        a["args"] = args
    return a


def _alarm(lines: List[str]) -> Optional[str]:
    return next((ln.strip()[2:].strip() for ln in lines if ln.strip().startswith("!!")), None)


def _mm(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def _slots_words(slots: List[int]) -> str:
    names = [str(g + 1) for g in slots]
    if len(names) == 1:
        return f"Slot {names[0]}"
    return f"Slots {', '.join(names[:-1])} and {names[-1]}"


class UnitCheck:
    """One unit's check, from the first slot to Ready. status() and cmds() look at the printer as it is now."""

    def __init__(self, unit: Dict[str, Any], name: str, driver: str, status: Callable[[], Dict[str, Any]],
                 cmds: Callable[[], Any], now: float):
        self.index, self.name, self.driver = unit["index"], name, driver
        self.slots: List[int] = list(range(unit["offset"], unit["offset"] + unit["n"]))
        self._status, self._cmds = status, cmds
        self.marks: Dict[int, Dict[str, Any]] = {g: {"state": "next", "sensor": None, "motor": None, "why": None}
                                                 for g in self.slots}
        self.phase = "slots"          # slots, measure, ready
        self.cur = 0                  # the slot being checked, as an index into slots
        self.told_in = False          # "It's in", on a unit with no sensor at the gate
        self.busy: Optional[Dict[str, Any]] = None   # {what: home|check|slot|tube, slot, since, homing}
        self.done_at: Optional[float] = None
        self.done_error: Optional[str] = None
        self.lines: List[str] = []
        self.stop = False
        self.last: Optional[tuple] = None   # (ok, sentence) about the slot before
        self.plan: List[tuple] = []          # measuring: ("slot", g) for each hub, then ("tube", g)
        self.m = 0
        self.m_error: Optional[Dict[str, Any]] = None   # {text, raw, retry}
        self.to_hub: Dict[int, Optional[float]] = {}
        self.tube: Optional[float] = None
        self.tube_why: Optional[str] = None
        self.raw = ""
        self.started = now

    # ---- inputs ------------------------------------------------------------------------

    def hear(self, line: str) -> None:
        if self.busy is not None and self.done_at is None:
            self.lines.append(line or "")

    def done(self, error: Optional[str], now: float) -> None:
        self.done_at, self.done_error = now, error

    def answer(self, op: str) -> bool:
        """A person's tap. Returns False when it doesn't apply right now."""
        if op == "stop":
            if self.busy is not None:
                self.stop = True
            return True
        if self.busy is not None:
            return False
        if self.phase == "slots" and self.cur < len(self.slots):
            g = self.slots[self.cur]
            mark = self.marks[g]
            if op == "in" and mark["state"] in ("next", "waiting"):
                self.told_in = True
                return True
            if op == "skip" and mark["state"] in ("next", "waiting", "failed"):
                mark.update(state="skipped", why=None)
                self.last = (None, f"Slot {g + 1} skipped.")
                self._next_slot()
                return True
            if op == "retry" and mark["state"] == "failed":
                mark.update(state="next", why=None, sensor=None, motor=None)
                return True
            return False
        if self.phase == "measure" and self.m_error:
            if op == "retry" and self.m_error["retry"]:
                self.m_error = None
                return True
            if op == "skip":
                what, g = self.plan[self.m]
                if what == "tube":
                    self.tube_why = "Skipped."
                self._measured_one()
                return True
        return False

    # ---- the routine ---------------------------------------------------------------------

    def _next_slot(self) -> None:
        self.cur += 1
        self.told_in = False
        while self.cur < len(self.slots) and self.marks[self.slots[self.cur]]["state"] in ("ok", "skipped"):
            self.cur += 1
        if self.cur >= len(self.slots):
            self._start_measuring()

    def _measured_one(self) -> None:
        self.m_error = None
        self.m += 1
        if self.m >= len(self.plan):
            self.phase = "ready"

    def _start_measuring(self) -> None:
        ok = [g for g in self.slots if self.marks[g]["state"] == "ok"]
        self.phase = "measure"
        cmds = self._cmds()
        if not ok:
            self.tube_why = "No slot passed its check."
            self.plan, self.phase = [], "ready"
            return
        self.plan = ([("slot", g) for g in ok] if getattr(cmds, "measure_slot", None) else []) + [("tube", ok[0])]

    def _send(self, what: str, g: int, script: str, now: float, homing: bool = False) -> List[tuple]:
        self.busy = {"what": what, "slot": g, "since": now, "homing": homing}
        self.done_at, self.done_error, self.lines = None, None, []
        return [("macro", script)]

    def work(self, now: float) -> List[tuple]:
        """What to send now; empty while waiting on a person or a command."""
        if self.busy is not None:
            if self.done_at is None or now < self.done_at + SETTLE_SECONDS:
                return []
            self._judge()
            self.busy = None
            if self.stop:
                return [("end", None)]
        cmds = self._cmds()
        if cmds is None:
            return []
        status = self._status()
        if self.phase == "slots":
            if self.cur < len(self.slots):
                g = self.slots[self.cur]
                mark = self.marks[g]
                if mark["state"] == "failed":
                    return []
                seen = cmds.sees(status, g)
                there = seen is True or (seen is None and (self.told_in or cmds.believes(status, g)))
                if not there:
                    mark["state"] = "waiting"
                    return []
                mark.update(state="testing", sensor=True if seen else None)
                home = cmds.needs_home(status)
                return self._send("check", g, cmds.check_slot(g, home=home), now, homing=home)
        if self.phase == "measure":
            if self.m_error:
                return []
            what, g = self.plan[self.m]
            if what == "slot":
                return self._send("slot", g, cmds.measure_slot(g), now)
            home = cmds.needs_home(status)
            return self._send("tube", g, cmds.measure_tube(g, home=home), now, homing=home)
        return []

    def _judge(self) -> None:
        """The command that just finished: what it found, from what it said and the status."""
        b = self.busy
        g, what = b["slot"], b["what"]
        text = "\n".join(self.lines).lower()
        alarm = self.done_error or _alarm(self.lines)
        self.raw = alarm or ""
        status, cmds = self._status(), self._cmds()
        if what == "check":
            mark = self.marks[g]
            why = self._check_failed(g, text, alarm, status, cmds)
            if why:
                mark.update(state="failed", why=why, motor=False)
                self.last = (False, why)
            else:
                mark.update(state="ok", sensor=True, motor=True, why=None)
                self.last = (True, f"Slot {g + 1}'s sensor saw the filament, and its motor turned.")
                self._next_slot()
            return
        if what == "slot":
            mm = _mm(text, r"dist_hub:\s*new:\s*([\d.]+)")
            if mm is None and not alarm and cmds is not None:
                mm = cmds.lane(status, g).get("dist_hub")
            why = self._afc_failed(g, text, alarm)
            if why:
                self.m_error = {"text": why, "raw": alarm or "", "retry": True}
            else:
                self.to_hub[g] = float(mm) if isinstance(mm, (int, float)) else None
                self._measured_one()
            return
        # the tube
        if self.driver == "happy_hare":
            mm = _mm(text, r"calibrated bowden length is\s*([\d.]+)")
            if "no encoder or extruder entry sensor" in text:
                why, retry = TUBE_NO_SENSOR["happy_hare"], False
            elif "calibration steps are not complete" in text:
                why, retry = HH_UNCALIBRATED, True
            elif "not homed" in text:
                why, retry = NOT_HOMED, True
            elif "filament is loaded" in text:
                why, retry = FILAMENT_IN_PATH, True
            elif alarm or mm is None:
                why, retry = "The filament didn't reach the head. Check the tube is clear, then try again.", True
            else:
                why, retry = None, False
        else:
            mm = _mm(text, r"afc_bowden_length:\s*new:\s*([\d.]+)")
            if mm is None and not alarm and cmds is not None:
                hub = cmds.lane(status, g).get("hub")
                mm = (status.get(f"AFC_hub {hub}") or {}).get("afc_bowden_length") if hub else None
            if "without tool start sensor" in text or "only post extruder sensor" in text:
                why, retry = TUBE_NO_SENSOR["afc"], False
            else:
                why, retry = self._afc_failed(g, text, alarm), True
                if not why and not isinstance(mm, (int, float)):
                    why = "AFC didn't say how long the tube is. Try again."
        if why:
            self.m_error = {"text": why, "raw": alarm or "", "retry": retry}
            return
        self.tube = float(mm)
        self._measured_one()

    def _check_failed(self, g: int, text: str, alarm: Optional[str], status: Dict[str, Any], cmds: Any) -> Optional[str]:
        n = g + 1
        if self.driver == "happy_hare":
            if "calibration steps are not complete" in text:
                return HH_UNCALIBRATED
            if "not homed" in text:
                return NOT_HOMED
            if "filament is loaded" in text or "not safely unloaded" in text:
                return FILAMENT_IN_PATH
            if "marked empty" in text:
                return f"Slot {n}'s motor turned, but the unit never felt the filament. Push it in a little further, then try again."
            if alarm:
                return f"Slot {n} stopped partway. Check its filament isn't tangled, then try again."
            if "filament detected" in text or cmds.believes(status, g):
                return None
            return f"Slot {n}'s motor turned, but the unit never felt the filament. Push it in a little further, then try again."
        if alarm:
            return self._afc_failed(g, text, alarm,
                                    f"Slot {n}'s motor didn't turn. Check the unit's power and its cable, then try again.")
        if cmds.sees(status, g) is False:
            return f"Slot {n}'s sensor lost the filament as it moved. Push it in until the unit grabs it, then try again."
        return None

    def _afc_failed(self, g: int, text: str, alarm: Optional[str], otherwise: Optional[str] = None) -> Optional[str]:
        if not alarm:
            return None
        if "hub is not clear" in text:
            return HUB_NOT_CLEAR
        if "tool must be unloaded" in text or "toolhead is loaded" in text:
            return FILAMENT_IN_PATH
        if "not loaded" in text or "not prepped" in text:
            return f"Slot {g + 1}'s sensor doesn't see its filament. Push it in until the unit grabs it, then try again."
        return otherwise or f"The filament from slot {g + 1} didn't get where it should. Check the tube is clear, then try again."

    # ---- what the screens draw --------------------------------------------------------------

    def ok_slots(self) -> List[int]:
        return [g for g in self.slots if self.marks[g]["state"] == "ok"]

    def words(self, now: float) -> Dict[str, Any]:
        """headline, detail, tone of the detail (ok/failed/None), phase and actions."""
        stop = _action("unit_check_stop", "Stop")
        if self.stop:
            return {"phase": "unit_check_stopping", "headline": "Stopping", "tone": None, "actions": [],
                    "detail": "Bench stops once this step is done."}
        if self.phase == "slots" and self.cur < len(self.slots):
            g = self.slots[self.cur]
            mark, n = self.marks[g], g + 1
            tone, detail = (None, None)
            if self.last:
                tone = None if self.last[0] is None else ("ok" if self.last[0] else "failed")
                detail = self.last[1]
            if mark["state"] == "failed":
                return {"phase": "unit_check_failed", "headline": f"Slot {n} didn't pass.", "detail": mark["why"],
                        "tone": "failed",
                        "actions": [_action("unit_check_retry", "Try again", primary=True),
                                    _action("unit_check_skip", f"Skip slot {n}"), stop]}
            if mark["state"] == "testing":
                if self.busy and self.busy.get("homing"):
                    detail, tone = "Bench finds the unit's home first.", None
                return {"phase": "unit_check_testing", "headline": f"Checking slot {n}…",
                        "detail": detail or "Its motor turns a little. Leave the unit alone for a moment.",
                        "tone": tone, "actions": [stop]}
            sensor = self._cmds() is not None and self._cmds().sees(self._status(), g) is not None
            actions = [] if sensor else [_action("unit_check_in", "It's in", primary=True)]
            actions += [_action("unit_check_skip", f"Skip slot {n}"), stop]
            return {"phase": "unit_check_push", "headline": f"Push filament into slot {n}.",
                    "detail": detail or ("Until the unit grabs it. Bench notices." if sensor
                                         else "Until the unit grabs it, then tap It's in."),
                    "tone": tone, "actions": actions}
        if self.phase == "measure" and self.m < len(self.plan):
            what, g = self.plan[self.m]
            headline = "Measuring the tube to the head…" if what == "tube" else f"Measuring slot {g + 1} to the hub…"
            if self.m_error:
                actions = ([_action("unit_check_retry", "Try again", primary=True)] if self.m_error["retry"] else [])
                actions += [_action("unit_check_skip", "Skip it", primary=not self.m_error["retry"]), stop]
                return {"phase": "unit_check_failed",
                        "headline": "The tube wasn't measured." if what == "tube" else f"Slot {g + 1} wasn't measured.",
                        "detail": self.m_error["text"], "tone": "failed", "actions": actions}
            if what == "tube":
                detail = (f"Slot {g + 1}'s filament goes up to the head and back, slowly. "
                          "Leave the unit and the tube alone for a moment.")
            else:
                detail = "Its filament goes up to the hub and back. Leave the unit alone for a moment."
            if self.busy and self.busy.get("homing"):
                detail = "Bench finds the unit's home first. " + detail
            return {"phase": "unit_check_measuring", "headline": headline, "detail": detail, "tone": None,
                    "actions": [stop]}
        return {"phase": "unit_checked", "headline": self._ready_headline(), "detail": self._ready_detail(),
                "tone": None,
                "actions": [_action("unit_check_done", "Done"),
                            _action("unit_check_done", "Load spools", primary=True, then="materials")]}

    def _ready_headline(self) -> str:
        ok, total = len(self.ok_slots()), len(self.slots)
        if not ok:
            return "No slot passed."
        return f"Ready: {ok} slot{'s' if ok != 1 else ''}." if ok == total else f"Ready: {ok} of {total} slots."

    def _ready_detail(self) -> str:
        if not self.ok_slots():
            return f"Check how {self.name} is wired and that each slot has filament, then check it again."
        if self.tube is None:
            return f"{self.name} is checked. The tube to the head still needs measuring."
        return f"{self.name} is checked and measured. Load spools, and Bench prints in several colors."

    def _rows(self) -> List[Dict[str, str]]:
        rows = []
        cmds = self._cmds()
        version = cmds.version(self._status()) if cmds is not None else None
        if version:
            rows.append({"title": version, "sub": f"Bench drives {self.name} through it."})
        ok, total = self.ok_slots(), len(self.slots)
        skipped = [g for g in self.slots if self.marks[g]["state"] == "skipped"]
        failed = [g for g in self.slots if self.marks[g]["state"] == "failed"]
        title = f"{len(ok)} slot{'s' if len(ok) != 1 else ''} · checked" if len(ok) == total else f"{len(ok)} of {total} slots · checked"
        subs = []
        if skipped:
            subs.append(f"{_slots_words(skipped)} skipped.")
        if failed:
            subs.append(f"{_slots_words(failed)} didn't pass.")
        if not subs:
            subs.append("Every sensor and every motor.")
        if self.to_hub and len(self.to_hub) == len(ok):
            subs.append("Each one measured to the hub.")
        rows.append({"title": title, "sub": " ".join(subs)})
        if self.tube is not None:
            rows.append({"title": f"The tube to the head · {round(self.tube)} mm", "sub": "Measured just now."})
        else:
            rows.append({"title": "The tube to the head · not measured", "sub": self.tube_why or "Check and measure again to try."})
        return rows

    def view(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        w = self.words(now)
        step = self.phase
        cards = []
        for g in self.slots:
            mark = self.marks[g]
            state = mark["state"]
            line = {"next": "Next", "waiting": "Waiting…", "testing": "Checking…", "skipped": "Skipped",
                    "failed": "Didn't pass", "ok": None}[state]
            cards.append({"slot": g, "label": f"Slot {g + 1}", "state": state, "sensor": mark["sensor"],
                          "motor": mark["motor"], "line": line})
        decided = len(self.ok_slots())
        measure = None
        if step == "measure" and self.m < len(self.plan):
            what, g = self.plan[self.m]
            seconds = SECONDS["slot"] if what == "slot" else SECONDS[f"tube_{self.driver}"]
            since = self.busy["since"] if self.busy else None
            measure = {"what": what, "slot": g, "seconds": seconds,
                       "elapsed": round(now - since, 1) if since is not None and not self.m_error else None,
                       "of": len(self.plan), "n": self.m + 1,
                       "note": ("Once for the whole unit." + (" Each slot is measured to the hub first." if len(self.plan) > 1 else ""))
                       if what == "tube" else "Each slot once, then the tube to the head."}
        then = ("Then Bench measures each slot and the tube to the head." if self.driver == "afc"
                else "Then Bench measures the tube to the head.")
        return {
            "unit": self.name,
            "unit_index": self.index,
            "driver": self.driver,
            "step": step,
            "n": {"slots": 1, "measure": 2, "ready": 3}[step],
            "of": 3,
            "headline": w["headline"],
            "detail": w["detail"],
            "tone": w["tone"],
            "slots": cards,
            "current": self.slots[self.cur] if step == "slots" and self.cur < len(self.slots) else None,
            "note": f"{decided} of {len(self.slots)} checked. {then}" if step == "slots" else None,
            "measure": measure,
            "ready": {"rows": self._rows()} if step == "ready" else None,
            "stopping": self.stop,
            "actions": w["actions"],
            "raw": self.raw,
        }
