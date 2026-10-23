"""Checking and measuring a Happy Hare or AFC unit from the screen (design/unit-setup/, B, stage 1).

Each slot in turn: filament in (its sensor sees it, or the person says so on a unit without one), then a small motor
test with the unit's own command. Then, on Happy Hare when its gear isn't measured, the gear (the section "Gear
calibration", C with B's mark): slot 1 with a ruler, the tube back on, the encoder learns from slot 1 and measures the
other slots. Then measuring: AFC each slot to its hub, then the tube to the head; Happy Hare the tube. Then Ready. IntentTracker holds one of these at a time and sends its commands the way it sends
the change routine's: as "macro" steps that report back through change_done().

Neither Happy Hare nor AFC raise a G-code error for most failures. Their command returns normally and says what went
wrong on the console ("!! ..."), so a step's result is read from the console lines heard while it ran, then from the
status. Those lines are matched narrowly, on the words their source prints (Happy Hare 4.1 and 3, AFC 1.2).
"""
import re
import time
from typing import Any, Callable, Dict, List, Optional

SETTLE_SECONDS = 1.0   # Moonraker's status batch can land after the command returns: judge once it has
SECONDS = {"check": 6, "slot": 12, "tube_happy_hare": 40, "tube_afc": 60, "encoder": 30, "gate": 35}   # rough

GEAR_STUB = 20          # mm out of the outlet to mark (and again for Push a bit more)
GEAR_PUSH = 100         # what MMU_CALIBRATE_GEAR's LENGTH defaults to
GEAR_OK = (90.0, 110.0)       # taken as is
GEAR_NEAR = (80.0, 120.0)     # asks Measure again first; past it, it can't be the gear

HH_UNCALIBRATED = ("Happy Hare says it isn't calibrated yet, but not what's missing. Its console, in Advanced, lists "
                   "the steps. Then try again.")
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
    if len(names) > 2 and slots == list(range(slots[0], slots[-1] + 1)):
        return f"Slots {names[0]} to {names[-1]}"
    return f"Slots {', '.join(names[:-1])} and {names[-1]}"


NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def _count(n: int) -> str:
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def _missing(text: str) -> set:
    """What Happy Hare's "Calibration steps are not complete" lists under Required (3 and 4 word it alike): gear (the
    first gate's), gates (the others'), encoder, selector, tube. Optional ones don't stop anything."""
    at = text.find("required:")
    if at < 0:
        return set()
    seg = text[at:]
    end = seg.find("optional")
    seg = seg[:end] if end > 0 else seg
    out = set()
    for line in seg.splitlines():
        if "mmu_calibrate_gear" in line or "mmu_calibrate_gate" in line:
            out.add("gates" if "appropriate gate" in line or "gate=xx" in line else "gear")
        if "mmu_calibrate_encoder" in line:
            out.add("encoder")
        if "mmu_calibrate_selector" in line:
            out.add("selector")
        if "mmu_calibrate_bowden" in line:
            out.add("tube")
    return out


class Gear:
    """Measuring a Happy Hare unit's gear, inside a check. info is HappyHare.gear_state()."""

    def __init__(self, info: Dict[str, Any]):
        self.info = info
        self.step = "plan"        # plan, free, mark, ruler, pad, back, encoder, gates
        self.pushed = 0           # mm Bench has pushed out of the outlet and not pulled back yet
        self.mm: Optional[float] = None
        self.tries = 0            # pushes of 100 mm, so the pad starts empty after Measure again
        self.sheet: Optional[Dict[str, Any]] = None    # {mm, far}: the number is outside 90-110
        self.error: Optional[Dict[str, Any]] = None    # {what, text, raw, retry, skip}
        self.next: Optional[str] = None                # a command to send on the next work()
        self.outcome: Optional[str] = None             # measured, skipped, failed
        self.why: Optional[str] = None
        self.ruler_done = False
        self.encoder: Optional[Any] = None             # True once calibrated here, "skipped"
        self.gates: Dict[int, str] = {}                # slot -> ok, kept (its design value)
        self.queue: List[int] = []
        self.gates_started = False
        self.back_to: Optional[str] = None             # slots or measure: where Happy Hare refused, to go back to
        self.refusal: Optional[Any] = None
        self.series: Optional[Dict[str, Any]] = None   # the encoder's runs, for one progress bar: {total, done}


class UnitCheck:
    """One unit's check, from the first slot to Ready. status() and cmds() look at the printer as it is now."""

    def __init__(self, unit: Dict[str, Any], name: str, driver: str, status: Callable[[], Dict[str, Any]],
                 cmds: Callable[[], Any], now: float, gear: bool = False, gear_skipped: bool = False):
        self.index, self.name, self.driver = unit["index"], name, driver
        self.unit = unit
        self.slots: List[int] = list(range(unit["offset"], unit["offset"] + unit["n"]))
        self._status, self._cmds = status, cmds
        self.marks: Dict[int, Dict[str, Any]] = {g: {"state": "next", "sensor": None, "motor": None, "why": None,
                                                     "gear": False} for g in self.slots}
        self.phase = "slots"          # slots, gear, measure, ready
        self.cur = 0                  # the slot being checked, as an index into slots
        self.told_in = False          # "It's in", on a unit with no sensor at the gate
        self.busy: Optional[Dict[str, Any]] = None   # {what: home|check|slot|tube|g_*, slot, since, homing}
        self.done_at: Optional[float] = None
        self.done_error: Optional[str] = None
        self.lines: List[str] = []
        self.stop = False
        self.last: Optional[tuple] = None   # (ok, sentence) about the slot before
        self.plan: List[tuple] = []          # measuring: ("slot", g) for each hub, then ("tube", g)
        self.m = 0
        self.m_error: Optional[Dict[str, Any]] = None   # {text, raw, retry, gear}
        self.to_hub: Dict[int, Optional[float]] = {}
        self.tube: Optional[float] = None
        self.tube_why: Optional[str] = None
        self.raw = ""
        self.started = now
        self.frame: Optional[Dict[str, Any]] = None   # part of setting the unit up (unit_setup.py): its title and rows
        self.gear: Optional[Gear] = None
        info = self._gear_info()
        # a gear skipped before isn't asked for again (Care still offers it); Happy Hare refusing without it still is
        if info is not None and (gear or (info["needed"] and not gear_skipped)):
            self.gear = Gear(info)

    # ---- inputs ------------------------------------------------------------------------

    def hear(self, line: str) -> None:
        if self.busy is not None and self.done_at is None:
            self.lines.append(line or "")

    def done(self, error: Optional[str], now: float) -> None:
        self.done_at, self.done_error = now, error

    def answer(self, op: str, args: Optional[Dict[str, Any]] = None) -> bool:
        """A person's tap. Returns False when it doesn't apply right now."""
        args = args or {}
        if op == "stop":
            if self.busy is not None or self._tidy_due():
                self.stop = True
            return True
        if self.busy is not None:
            return False
        if op == "gear_now":
            return self._gear_now()
        if self.phase == "gear":
            return self._gear_answer(op, args)
        if self.phase == "slots" and self.cur < len(self.slots):
            g = self.slots[self.cur]
            mark = self.marks[g]
            if op == "in" and mark["state"] in ("next", "waiting"):
                self.told_in = True
                return True
            if op == "skip" and mark["state"] in ("next", "waiting", "failed"):
                mark.update(state="skipped", why=None, gear=False)
                self.last = (None, f"Slot {g + 1} skipped.")
                self._next_slot()
                return True
            if op == "retry" and mark["state"] == "failed":
                mark.update(state="next", why=None, sensor=None, motor=None, gear=False)
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
            self._after_slots()

    def _after_slots(self) -> None:
        """The slots are done: the gear when it's due, each slot by the encoder, then the tube."""
        gear = self.gear
        if gear is not None and not gear.ruler_done and gear.outcome is None:
            if self.marks[self.slots[0]]["state"] == "ok":
                self.phase, gear.step = "gear", "plan"
                return
            gear.outcome, gear.why = "failed", "Slot 1 didn't pass its check, and the gear is measured with it."
        if gear is not None and self._gates_due():
            gear.gates_started = True
            gear.queue = [g for g in self.ok_slots() if g != self.slots[0]]
            gear.series = {"total": len(gear.queue) * SECONDS["gate"], "done": 0}
            self.phase, gear.step = "gear", "gates"
            return
        if self.plan:   # back to the tube Happy Hare refused
            self.phase, self.m_error = "measure", None
            return
        self._start_measuring()

    def _gates_due(self) -> bool:
        gear = self.gear
        return (gear is not None and gear.outcome == "measured" and gear.encoder is True and gear.info["per_gate"]
                and not gear.gates_started and any(g != self.slots[0] for g in self.ok_slots()))

    def _ruler_done(self) -> None:
        gear = self.gear
        gear.ruler_done = True
        if gear.back_to == "slots":
            gear.back_to = None
            self.phase, self.told_in = "slots", False
            return
        gear.back_to = None
        self._after_slots()

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
            what = self.busy["what"]
            self._judge()
            self.busy = None
            if self.stop and (what == "g_tidy" or not self._tidy_due()):
                return [("end", None)]
        cmds = self._cmds()
        if cmds is None:
            return []
        status = self._status()
        if self.stop and self._tidy_due():
            return self._gear_send("g_tidy", cmds, status, now)
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
        if self.phase == "gear":
            gear = self.gear
            if gear.error or gear.sheet:
                return []
            if gear.next:
                what, gear.next = gear.next, None
                return self._gear_send(what, cmds, status, now)
            if gear.step == "encoder":
                return self._gear_send("g_enc", cmds, status, now)
            if gear.step == "gates" and gear.queue:
                return self._gear_send("g_gate", cmds, status, now)
            return []
        if self.phase == "measure":
            if self.m_error:
                return []
            what, g = self.plan[self.m]
            if what == "slot":
                return self._send("slot", g, cmds.measure_slot(g), now)
            home = cmds.needs_home(status)
            return self._send("tube", g, cmds.measure_tube(g, home=home), now, homing=home)
        return []

    # ---- the gear --------------------------------------------------------------------------

    def _gear_info(self) -> Optional[Dict[str, Any]]:
        cmds = self._cmds()
        if self.driver != "happy_hare" or getattr(cmds, "calibrate_gear", None) is None:
            return None
        return cmds.gear_state(self._status(), self.unit)

    def _tidy_due(self) -> bool:
        return self.gear is not None and self.gear.pushed > 0

    def _gear_send(self, what: str, cmds: Any, status: Dict[str, Any], now: float) -> List[tuple]:
        gear, first = self.gear, self.slots[0]
        v4 = gear.info["v4"]
        if what == "g_out":
            home = cmds.needs_home(status)
            return self._send(what, first, cmds.gear_select(first, home=home) + "\n" + cmds.gear_push(GEAR_STUB, v4),
                              now, homing=home)
        if what == "g_more":
            return self._send(what, first, cmds.gear_push(GEAR_STUB, v4), now)
        if what == "g_push":
            return self._send(what, first, cmds.gear_push(GEAR_PUSH, v4), now)
        if what == "g_again":
            return self._send(what, first, cmds.gear_push(-GEAR_PUSH, v4) + "\n" + cmds.gear_push(GEAR_PUSH, v4), now)
        if what in ("g_back", "g_tidy"):
            # pulled back before the new value is saved, so it comes back by exactly what went out
            return self._send(what, first, cmds.gear_push(-gear.pushed, v4), now)
        if what == "g_cal":
            return self._send(what, first, cmds.calibrate_gear(gear.mm), now)
        if what == "g_enc":
            return self._send(what, first, cmds.gear_select(first) + "\n" + cmds.calibrate_encoder(), now)
        g = gear.queue[0]
        home = cmds.needs_home(status)
        return self._send(what, g, ("MMU_HOME\n" if home else "") + cmds.calibrate_gate(g, v4), now, homing=home)

    def _gear_now(self) -> bool:
        """Measure the gear, from where Happy Hare refused for it."""
        refused = None
        if self.phase == "slots" and self.cur < len(self.slots):
            mark = self.marks[self.slots[self.cur]]
            if mark["state"] == "failed" and mark["gear"]:
                refused, back = mark, "slots"
        elif self.phase == "measure" and self.m_error and self.m_error.get("gear"):
            refused, back = self.m_error, "measure"
        if refused is None:
            return False
        if self.gear is None or self.gear.ruler_done:
            self.gear = Gear(self._gear_info())
        self.gear.back_to, self.gear.refusal = back, dict(refused)
        if back == "slots":
            refused.update(state="next", why=None, sensor=None, motor=None, gear=False)
        else:
            self.m_error = None
        self.phase, self.gear.step = "gear", "plan"
        return True

    def _gear_answer(self, op: str, args: Dict[str, Any]) -> bool:
        gear = self.gear
        if gear.error:
            if op == "retry" and gear.error["retry"]:
                if gear.error["what"] not in ("g_enc", "g_gate"):
                    gear.next = gear.error["what"]
                gear.error = None
                return True
            if op == "skip" and gear.error["skip"]:
                self._gear_skip_error()
                return True
            return False
        step = gear.step
        if step == "plan" and op == "gear_start":
            gear.step = "free"
            return True
        if step == "plan" and op == "gear_skip":
            gear.outcome, gear.ruler_done = "skipped", True
            if gear.back_to:
                self._put_refusal_back()
            else:
                self._after_slots()
            return True
        if step == "free" and op == "gear_off":
            gear.next = "g_out"
            return True
        if step == "mark" and op in ("gear_more", "gear_marked"):
            gear.next = "g_more" if op == "gear_more" else "g_push"
            return True
        if step == "ruler" and op == "gear_type":
            gear.step = "pad"
            return True
        if step == "pad":
            if op == "gear_type":
                gear.sheet = None
                return True
            if op == "gear_again":
                gear.sheet, gear.next = None, "g_again"
                return True
            if op in ("gear_measured", "gear_use"):
                mm = args.get("mm")
                if not isinstance(mm, (int, float)) or not 1 <= mm <= 1000:
                    return False
                mm = round(float(mm), 1)
                far = not GEAR_NEAR[0] <= mm <= GEAR_NEAR[1]
                if op == "gear_measured" and not GEAR_OK[0] <= mm <= GEAR_OK[1]:
                    gear.sheet = {"mm": mm, "far": far}
                    return True
                if far:
                    return False
                gear.mm, gear.sheet, gear.next = mm, None, "g_back"
                return True
        if step == "back" and op == "gear_on":
            if gear.outcome == "measured" and gear.info["encoder"]:
                gear.step = "encoder"
                gear.series = {"total": SECONDS["encoder"], "done": 0}
            else:
                self._ruler_done()
            return True
        return False

    def _gear_skip_error(self) -> None:
        gear = self.gear
        what = gear.error["what"]
        gear.error = None
        if what == "g_enc":
            gear.encoder = "skipped"
            self._ruler_done()
        elif what == "g_gate":
            gear.gates[gear.queue.pop(0)] = "kept"
            self._gate_next()
        else:   # nothing out of the outlet: the tube goes back on, the gear keeps its value
            gear.outcome = gear.outcome or "skipped"
            gear.step = "back"

    def _put_refusal_back(self) -> None:
        """Skipped the gear Happy Hare asked for: its refusal stands, so the person can skip that instead."""
        gear = self.gear
        back, refused = gear.back_to, gear.refusal or {}
        gear.back_to = None
        said = str(refused.get("why") or refused.get("text") or "")
        said = said.split(". ")[0].rstrip(".") + ". The gear can be measured from Care later." if said else HH_UNCALIBRATED
        if back == "slots":
            self.phase = "slots"
            self.marks[self.slots[self.cur]].update(state="failed", why=said, motor=False, gear=False)
        else:
            self.phase = "measure"
            self.m_error = dict(refused, text=said, gear=False, retry=False)

    def _gate_next(self) -> None:
        gear = self.gear
        if gear.series:
            gear.series["done"] = gear.series["total"] - len(gear.queue) * SECONDS["gate"]
        if not gear.queue:
            self._after_slots()

    def _judge_gear(self, what: str, g: int, text: str, alarm: Optional[str]) -> None:
        gear = self.gear
        failed = bool(self.done_error or alarm)
        if what in ("g_out", "g_more", "g_push", "g_again", "g_back", "g_tidy"):
            if failed:
                if what != "g_tidy":
                    gear.error = {"what": what, "text": self._push_failed(text, what), "raw": alarm or "",
                                  "retry": True, "skip": gear.pushed == 0 and what in ("g_out", "g_back")}
                return
            if what == "g_out":
                gear.pushed, gear.step = GEAR_STUB, "mark"
            elif what == "g_more":
                gear.pushed += GEAR_STUB
            elif what == "g_push":
                gear.pushed += GEAR_PUSH
                gear.tries += 1
                gear.step = "ruler"
            elif what == "g_again":
                gear.tries += 1
            elif what == "g_back":
                gear.pushed, gear.next = 0, "g_cal"
            else:
                gear.pushed = 0
            return
        if what == "g_cal":
            took = "calculated to be" in text or "has been saved" in text
            if self.done_error or (alarm and not took):
                why = ("Bench couldn't select slot 1, so the gear wasn't saved. Try again."
                       if "no mmu gate selected" in text else
                       "Happy Hare didn't take the measurement. Try again.")
                gear.error = {"what": "g_cal", "text": why, "raw": alarm or self.done_error or "", "retry": True,
                              "skip": True}
                return
            gear.outcome, gear.step = "measured", "back"
            return
        if what == "g_enc":
            took = "calculated resolution of the encoder" in text or "encoder calibration has been saved" in text
            if self.done_error or (alarm and not took):
                if "filament not detected in encoder" in text:
                    why = ("The encoder didn't feel slot 1's filament. Check the tube is back on and the filament "
                           "is in, then try again.")
                elif "calibration steps are not complete" in text:
                    why = self._uncalibrated(_missing(text), "calibrate the encoder")
                else:
                    why = "The encoder's run stopped partway. Check the tube is back on and clear, then try again."
                gear.error = {"what": "g_enc", "text": why, "raw": alarm or self.done_error or "", "retry": True,
                              "skip": True}
                return
            gear.encoder = True
            if gear.series:
                gear.series["done"] = gear.series["total"]
            self._ruler_done()
            return
        # one slot by the encoder
        n = g + 1
        if "not considered valid" in text or "20% difference" in text:
            why = (f"Slot {n}'s measure came out too far from slot 1's, so Happy Hare kept its design value. Check "
                   "its filament isn't slipping or tangled, then try again.")
        elif self.done_error or alarm:
            why = f"Slot {n}'s run stopped partway. Check its filament is in and isn't tangled, then try again."
        else:
            gear.gates[gear.queue.pop(0)] = "ok"
            self._gate_next()
            return
        gear.error = {"what": "g_gate", "text": why, "raw": alarm or self.done_error or "", "retry": True, "skip": True}

    def _push_failed(self, text: str, what: str) -> str:
        if "no mmu gate selected" in text:
            return "Bench couldn't select slot 1. Try again."
        if "calibration steps are not complete" in text:
            return self._uncalibrated(_missing(text), "move slot 1")
        if "not homed" in text:
            return NOT_HOMED
        if what in ("g_back", "g_tidy"):
            return "The unit didn't pull the filament back in. Check nothing holds it at the outlet, then try again."
        return "Slot 1's gear didn't push. Check its filament is in the unit, then try again."

    # ---- judging what a command did ----------------------------------------------------------------

    def _judge(self) -> None:
        """The command that just finished: what it found, from what it said and the status."""
        b = self.busy
        g, what = b["slot"], b["what"]
        text = "\n".join(self.lines).lower()
        alarm = self.done_error or _alarm(self.lines)
        self.raw = alarm or ""
        status, cmds = self._status(), self._cmds()
        if what.startswith("g_"):
            self._judge_gear(what, g, text, alarm)
            return
        if what == "check":
            mark = self.marks[g]
            why = self._check_failed(g, text, alarm, status, cmds)
            if why:
                gear = "calibration steps are not complete" in text and self._gear_can_help(text) and g == self.slots[0]
                mark.update(state="failed", why=why, motor=False, gear=gear)
                self.last = (False, why)
            else:
                mark.update(state="ok", sensor=True, motor=True, why=None, gear=False)
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
        gear = False
        if self.driver == "happy_hare":
            mm = _mm(text, r"calibrated bowden length is\s*([\d.]+)")
            if "no encoder or extruder entry sensor" in text:
                why, retry = TUBE_NO_SENSOR["happy_hare"], False
            elif "calibration steps are not complete" in text:
                why, retry = self._uncalibrated(self._missing_now(text), "measure the tube"), True
                gear = self._gear_can_help(text)
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
            self.m_error = {"text": why, "raw": alarm or "", "retry": retry, "gear": gear}
            return
        self.tube = float(mm)
        self._measured_one()

    def _missing_now(self, text: str) -> set:
        """What Happy Hare's refusal names; when it names nothing Bench knows, what its saved variables say."""
        missing = _missing(text)
        info = self._gear_info()
        if not missing and info is not None:
            if info["measured"] is False:
                missing.add("gear")
            if info["encoder"] and info["encoder_ok"] is False:
                missing.add("encoder")
        return missing

    def _gear_can_help(self, text: str) -> bool:
        """Measuring the gear here clears the refusal: it names the gear or the encoder, and not the selector."""
        missing = self._missing_now(text)
        return (self._gear_info() is not None and bool(missing & {"gear", "gates", "encoder"})
                and "selector" not in missing and (self.gear is None or not self.gear.ruler_done
                                                   or self.gear.encoder == "skipped"))

    def _uncalibrated(self, missing: set, doing: str, first: bool = True) -> str:
        """Happy Hare's refusal, saying what's actually missing (its Required list, or its saved variables)."""
        names = []
        if "gear" in missing:
            names.append("slot 1's gear")
        elif "gates" in missing:
            names.append("each slot's gear")
        if "encoder" in missing:
            names.append("the unit's encoder")
        if "selector" in missing:
            names.append("the selector")
        if not names:
            return "Happy Hare won't " + doing + " until the tube to the head is measured." if missing == {"tube"} \
                else HH_UNCALIBRATED
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        verb = "is" if len(names) == 1 else "are"
        out = f"Happy Hare won't {doing} until {listed} {verb} measured."
        if "selector" in missing:
            return out + " The selector is set from Advanced (Happy Hare's own steps), then try again."
        if self._gear_info() is None:
            return out + " That's done from Advanced, then try again."
        if not first:
            return out + " Bench measures it with slot 1: check slot 1 first, then try again."
        if "encoder" in missing and "gear" not in missing:
            return out + " The encoder learns from slot 1's gear, so Bench measures that first, with a ruler."
        return out + " Bench measures it next, with a ruler, once."

    def _check_failed(self, g: int, text: str, alarm: Optional[str], status: Dict[str, Any], cmds: Any) -> Optional[str]:
        n = g + 1
        if self.driver == "happy_hare":
            if "calibration steps are not complete" in text:
                return self._uncalibrated(self._missing_now(text), f"check slot {n}", first=g == self.slots[0])
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

    def _others(self) -> List[int]:
        """The slots the encoder measures after slot 1: those that passed, or every one before the slots are checked."""
        checked = self.cur >= len(self.slots)
        return [g for g in (self.ok_slots() if checked else self.slots) if g != self.slots[0]]

    def words(self, now: float) -> Dict[str, Any]:
        """headline, detail, tone of the detail (ok/failed/None), phase and actions."""
        stop = _action("unit_check_stop", "Stop")
        if self.stop:
            detail = ("Bench pulls the filament back into the unit first." if self._tidy_due()
                      else "Bench stops once this step is done.")
            return {"phase": "unit_check_stopping", "headline": "Stopping", "tone": None, "actions": [],
                    "detail": detail}
        if self.phase == "gear":
            return self._gear_words(stop)
        if self.phase == "slots" and self.cur < len(self.slots):
            g = self.slots[self.cur]
            mark, n = self.marks[g], g + 1
            tone, detail = (None, None)
            if self.last:
                tone = None if self.last[0] is None else ("ok" if self.last[0] else "failed")
                detail = self.last[1]
            if mark["state"] == "failed":
                first = ([_action("unit_check_gear_now", "Measure the gear", primary=True)] if mark["gear"]
                         else [_action("unit_check_retry", "Try again", primary=True)])
                return {"phase": "unit_check_failed", "headline": f"Slot {n} didn't pass.", "detail": mark["why"],
                        "tone": "failed",
                        "actions": first + [_action("unit_check_skip", f"Skip slot {n}"), stop]}
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
                if self.m_error.get("gear"):
                    actions = [_action("unit_check_gear_now", "Measure the gear", primary=True)]
                else:
                    actions = ([_action("unit_check_retry", "Try again", primary=True)] if self.m_error["retry"] else [])
                actions += [_action("unit_check_skip", "Skip it", primary=not actions), stop]
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

    def _gear_words(self, stop: Dict[str, Any]) -> Dict[str, Any]:
        gear = self.gear
        busy = self.busy["what"] if self.busy else None
        out = {"phase": "unit_check_gear", "tone": None, "actions": [stop], "detail": None}
        if gear.error:
            what = gear.error["what"]
            if what == "g_gate":
                head = f"Slot {gear.queue[0] + 1} wasn't measured."
            elif what == "g_enc":
                head = "The encoder wasn't calibrated."
            elif what == "g_cal":
                head = "Slot 1's gear wasn't saved."
            else:
                head = "The unit didn't move."
            actions = [_action("unit_check_retry", "Try again", primary=True)] if gear.error["retry"] else []
            if gear.error["skip"]:
                actions.append(_action("unit_check_skip", "Skip it"))
            return dict(out, phase="unit_check_failed", headline=head, detail=gear.error["text"], tone="failed",
                        actions=actions + [stop])
        step = gear.step
        if step == "plan":
            kind = self._gear_kind()
            n = len(self.slots)
            heads = {"per_slot": "One ruler, then the encoder does the rest.",
                     "one_gear": f"One ruler covers all {n} slots.",
                     "no_encoder": "Slot 1, with a ruler."}
            details = {"per_slot": None,
                       "one_gear": (f"{self.name} has no encoder. " if not gear.info["encoder"] else "")
                       + "One gear drives every slot, so measuring slot 1 measures them all.",
                       "no_encoder": f"Each slot of {self.name} has its own gear, and without an encoder Bench can't "
                                     "measure the others. They keep the unit's design value."}
            return dict(out, headline=heads[kind], detail=details[kind],
                        actions=[_action("unit_check_gear_skip", "No ruler? Skip it"),
                                 _action("unit_check_gear_start", "Start", primary=True), stop])
        if step in ("free", "mark"):
            pushing = busy in ("g_out", "g_more")
            if step == "free" and not pushing:
                return dict(out, headline="Take the tube off, then mark the filament.",
                            detail="Bench pushes a little out of the outlet for you to mark.",
                            actions=[_action("unit_check_gear_off", "It's off", primary=True), stop])
            if pushing:
                return dict(out, headline="Take the tube off, then mark the filament.",
                            detail="Bench pushes a little out of the outlet…", actions=[stop])
            return dict(out, headline="Take the tube off, then mark the filament.",
                        actions=[_action("unit_check_gear_more", "Push a bit more"),
                                 _action("unit_check_gear_marked", "It's marked", primary=True), stop])
        if step == "ruler":
            if busy == "g_push":
                return dict(out, headline=f"Pushing exactly {GEAR_PUSH} mm…",
                            detail="Leave the filament alone for a moment. Your mark comes out with it.")
            return dict(out, headline="Measure from the outlet to your mark.",
                        detail=f"Bench pushed exactly {GEAR_PUSH} mm. Put the ruler's 0 against the outlet's edge.",
                        actions=[_action("unit_check_gear_type", "Type it in", primary=True), stop])
        if step == "pad":
            if busy == "g_again":
                return dict(out, headline="Measuring again…",
                            detail=f"Bench pulls it back in, then pushes exactly {GEAR_PUSH} mm again. "
                                   "Your mark comes back out.")
            if busy in ("g_back", "g_cal") or gear.next in ("g_back", "g_cal"):
                return dict(out, headline="Saving slot 1's gear…",
                            detail="Bench pulls the filament back in, and Happy Hare works the gear out.")
            return dict(out, headline="What does it say at your mark?",
                        detail=f"Bench expects {GEAR_OK[0]:g} to {GEAR_OK[1]:g} mm.",
                        actions=[_action("unit_check_gear_again", "Measure again"),
                                 _action("unit_check_gear_measured", "That's it", primary=True), stop])
        if step == "back":
            if gear.outcome == "measured":
                then = ("Then the encoder measures the other slots." if self._gear_kind() == "per_slot" and self._others()
                        else "Then the encoder learns from slot 1." if gear.info["encoder"]
                        else "Then Bench measures the tube to the head.")
                return dict(out, headline="Slot 1's gear is measured. Put the tube back on.",
                            detail=f"Push it into the outlet until it stops. {then}",
                            actions=[_action("unit_check_gear_on", "It's back on", primary=True), stop])
            return dict(out, headline="Put the tube back on.",
                        detail="Push it into the outlet until it stops. The gear keeps the unit's design value.",
                        actions=[_action("unit_check_gear_on", "It's back on", primary=True), stop])
        if step == "encoder":
            return dict(out, headline="The encoder is learning from slot 1…",
                        detail="400 mm up the tube and back, three times. Leave the unit alone.")
        g = gear.queue[0] if gear.queue else self.slots[0]
        return dict(out, headline=f"The encoder is measuring slot {g + 1}…",
                    detail="400 mm up the tube and back, three times. Leave the unit alone.")

    def _gear_kind(self) -> str:
        info = self.gear.info
        if not info["per_gate"]:
            return "one_gear"
        return "per_slot" if info["encoder"] else "no_encoder"

    def _gear_view(self, now: float) -> Optional[Dict[str, Any]]:
        gear = self.gear
        if gear is None or self.phase != "gear":
            return None
        kind, n, others = self._gear_kind(), len(self.slots), self._others()
        plan = [{"title": "Slot 1, with a ruler", "sub": "About 2 minutes, with you at the unit."},
                {"title": "Put the tube back on", "sub": None}]
        side = None
        if kind == "per_slot" and others:
            minutes = max(1, round((SECONDS["encoder"] + SECONDS["gate"] * len(others)) / 60))
            plan.append({"title": f"{_slots_words(others)}, by the unit's encoder",
                         "sub": f"About {minutes} minute{'s' if minutes != 1 else ''}. Bench does it; walk away if you like."})
            side = {"title": "Why a ruler at all?",
                    "text": f"{self.name}'s encoder counts in its gear's own steps, so it learns from slot 1. Once slot 1 "
                            f"is right, it measures the other {_count(len(others))} about as closely as a ruler."}
        elif gear.info["encoder"]:
            plan.append({"title": "The encoder learns from slot 1", "sub": "About a minute. Bench does it."})
        rows = None
        if gear.step == "back" and gear.outcome == "measured":
            rows = [self._gear_slot1_row()]
            if others:
                if kind == "per_slot":
                    rows.append({"title": f"{_slots_words(others)} · next", "tone": None,
                                 "sub": "The encoder measures each one once the tube is back on."})
                elif kind == "one_gear":
                    rows.append({"title": f"{_slots_words(others)} · measured too", "tone": None,
                                 "sub": "They share slot 1's gear."})
                else:
                    rows.append({"title": f"{_slots_words(others)} · not measured", "tone": "amber",
                                 "sub": "Each has its own gear. They keep the unit's design value."})
        sheet = None
        if gear.sheet:
            mm = gear.sheet["mm"]
            if gear.sheet["far"]:
                sheet = {"mm": mm, "far": True, "title": f"{mm:g} mm can't be the gear.",
                         "text": "A gear pushes close to 100. Check the ruler reads from the outlet's edge to your mark, "
                                 "then type it again, or measure again.",
                         "note": None,
                         "actions": [_action("unit_check_gear_type", "Type it again"),
                                     _action("unit_check_gear_again", "Measure again", primary=True)]}
            else:
                more = "more" if mm > GEAR_OK[1] else "less"
                sheet = {"mm": mm, "far": False, "title": f"{mm:g} mm is {more} than Bench expects.",
                         "text": f"Most units push between {GEAR_OK[0]:g} and {GEAR_OK[1]:g}. Check the ruler starts "
                                 "right at the outlet's edge, and the filament lies straight along it.",
                         "note": f"Measure again pulls it back in, then pushes {GEAR_PUSH} mm again.",
                         "actions": [_action("unit_check_gear_again", "Measure again", primary=True),
                                     _action("unit_check_gear_use", f"Use {mm:g} mm", mm=mm)]}
        cards = None
        progress = None
        if gear.step in ("encoder", "gates"):
            cards = []
            for g in self.slots:
                ok = self.marks[g]["state"] == "ok"
                if g == self.slots[0]:
                    state, line, sub = ("now", "Measuring…", None) if gear.step == "encoder" else \
                        ("ok", "By ruler", f"{gear.mm:g} for 100")
                elif gear.step == "gates" and gear.queue and g == gear.queue[0]:
                    state, line, sub = ("failed", "Didn't pass", None) if gear.error else ("now", "Measuring…", None)
                elif gear.gates.get(g) == "ok":
                    state, line, sub = "ok", "By encoder", None
                elif gear.gates.get(g) == "kept":
                    state, line, sub = "kept", "Design value", None
                elif not ok:
                    state, line, sub = "skipped", "Not checked", None
                else:
                    state, line, sub = "next", "Next", None
                cards.append({"slot": g, "label": f"Slot {g + 1}", "state": state, "line": line, "sub": sub})
            if gear.series and self.busy and not gear.error:
                progress = {"seconds": gear.series["total"],
                            "elapsed": round(gear.series["done"] + now - self.busy["since"], 1),
                            "then": "Then the tube to the head."}
            elif gear.series:
                progress = {"seconds": gear.series["total"], "elapsed": None, "then": "Then the tube to the head."}
        return {"step": gear.step, "kind": kind, "slots_n": n, "plan": plan, "side": side,
                "art": "one_gear" if kind == "one_gear" else "outlet",
                "pushed": gear.pushed, "push": GEAR_PUSH, "tries": gear.tries, "mm": gear.mm,
                "range": list(GEAR_OK), "near": list(GEAR_NEAR), "sheet": sheet, "rows": rows,
                "cards": cards, "progress": progress,
                "busy": self.busy is not None or gear.next is not None}

    def _gear_slot1_row(self) -> Dict[str, Any]:
        mm = self.gear.mm or GEAR_PUSH
        off = round(GEAR_PUSH - mm, 1)
        if abs(off) < 0.25:
            sub = "Its gear pushes true."
        else:
            sub = f"Its gear pushed {abs(off) / GEAR_PUSH * 100:g}% {'short' if off > 0 else 'long'}. Bench corrected it."
        return {"title": f"Slot 1 · {mm:g} mm for {GEAR_PUSH}", "sub": sub, "tone": None}

    def _gear_row(self) -> Optional[Dict[str, str]]:
        gear = self.gear
        if gear is None:
            return None
        if gear.outcome == "skipped":
            return {"title": "The gear · design value",
                    "sub": "Skipped. Happy Hare uses the unit's design value until it's measured, from Care."}
        if gear.outcome != "measured":
            return {"title": "The gear · not measured", "sub": gear.why or "Check and measure again to try."}
        mm = f"Slot 1 by ruler, {gear.mm:g} for {GEAR_PUSH}."
        kind = self._gear_kind()
        if kind == "one_gear":
            return {"title": "The gear · measured", "sub": f"{mm} One gear drives all {len(self.slots)} slots."}
        if gear.encoder == "skipped":
            return {"title": "The gear · measured", "sub": f"{mm} The encoder isn't calibrated yet."}
        by = [g for g, v in gear.gates.items() if v == "ok"]
        kept = [g for g, v in gear.gates.items() if v == "kept"]
        subs = [mm]
        if by:
            subs.append(f"{_slots_words(sorted(by))} by the encoder.")
        if kept:
            subs.append(f"{_slots_words(sorted(kept))} kept the design value.")
        if kind == "no_encoder" and len(self.slots) > 1:
            subs.append(f"{_slots_words(self.slots[1:])} keep the design value.")
        return {"title": "The gear · measured", "sub": " ".join(subs)}

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
        done = "set up, checked and measured" if self.frame else "checked and measured"
        return f"{self.name} is {done}. Load spools, and Bench prints in several colors."

    def _rows(self) -> List[Dict[str, str]]:
        rows = []
        cmds = self._cmds()
        version = cmds.version(self._status()) if cmds is not None else None
        if self.frame:
            rows.append({"title": self.frame["program"], "sub": "Bench moves it to a newer version only after testing it."})
        elif version:
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
        gear = self._gear_row()
        if gear:
            rows.append(gear)
        if self.tube is not None:
            rows.append({"title": f"The tube to the head · {round(self.tube)} mm", "sub": "Measured just now."})
        else:
            rows.append({"title": "The tube to the head · not measured", "sub": self.tube_why or "Check and measure again to try."})
        if self.frame and self.frame.get("kept"):
            rows.append({"title": "Your old settings · kept", "sub": "Care › Filament unit › Put it back."})
        return rows

    def _steps(self) -> Dict[str, int]:
        """The step each phase is, and of how many: the check's own, or 4 on after setting the unit up's 3."""
        if self.frame:
            return ({"slots": 4, "gear": 5, "measure": 5, "ready": 6, "of": 6} if self.gear
                    else {"slots": 4, "measure": 4, "ready": 5, "of": 5})
        return ({"slots": 1, "gear": 2, "measure": 3, "ready": 4, "of": 4} if self.gear
                else {"slots": 1, "measure": 2, "ready": 3, "of": 3})

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
        if self.driver == "afc":
            then = "Then Bench measures each slot and the tube to the head."
        elif self.gear is not None and not self.gear.ruler_done:
            then = "Then Bench measures the gear and the tube to the head."
        else:
            then = "Then Bench measures the tube to the head."
        steps = self._steps()
        return {
            "unit": self.name,
            "unit_index": self.index,
            "driver": self.driver,
            "step": step,
            "n": steps[step],
            "of": steps["of"],
            "title": self.frame["title"] if self.frame else None,
            "headline": w["headline"],
            "detail": w["detail"],
            "tone": w["tone"],
            "slots": cards,
            "current": self.slots[self.cur] if step == "slots" and self.cur < len(self.slots) else None,
            "note": f"{decided} of {len(self.slots)} checked. {then}" if step == "slots" else None,
            "measure": measure,
            "gear": self._gear_view(now),
            "ready": {"rows": self._rows()} if step == "ready" else None,
            "stopping": self.stop,
            "actions": w["actions"],
            "raw": self.raw,
        }
