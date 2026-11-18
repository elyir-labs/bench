"""Spots the printer goes to (design/spots/): a cutter's screw now, and later a purge spot, a brush, a dock.

Set from Care by being walked through it (B): a few steps made for the kind of spot, each with only the arrows that
matter, and a real test before anything is saved. Numbers can be typed under Advanced (C). Kept in Klipper's
[save_variables] as spot_<kind>_<value> (pick 2, B), which the printer's own macro reads before its own numbers.
"""
import time
from typing import Any, Callable, Dict, List, Optional

SAFE_Z = 10.0            # the head is at least this high while a spot is set
START_CLEAR = 30.0       # mm short of the spot the guide starts, so the first nudges can't hit anything
XY_SPEED = 6000          # mm/min to the start
NUDGE_SPEED = 1200
PRESS_SPEED = 300        # once it touches, slowly
STEPS = (10, 1, 0.1)
PRESS_STEPS = (1, 0.1)
MIN_PRESS = 1.0          # pressed must be at least this much further toward the screw than where it touched

CUTTER = {
    "id": "cutter", "name": "Cutter", "about": "Where the lever meets its screw",
    "macro": "gcode_macro CUT_TIP",
    # value, its label under Advanced, the macro's own variable it stands in for
    "values": [("x_touch", "Touches at X", "pin_loc_x"), ("x_pressed", "Pressed at X", "pin_loc_x_compressed"),
               ("y", "Y", "pin_loc_y")],
    "steps": [
        {"id": "touch", "title": "Bring the lever to the screw", "keeps": {"x": "x_touch", "y": "y"}, "axis": "xy",
         "steps": STEPS,
         "detail": "Line it up front to back, then nudge sideways until the lever just touches the screw.",
         "done": "It touches"},
        {"id": "press", "title": "Press until it stops", "keeps": {"x": "x_pressed"}, "axis": "x", "steps": PRESS_STEPS,
         "detail": "Keep going toward the screw until the lever is pushed all the way in. Small steps from here.",
         "done": "It's all the way in"},
        {"id": "try", "title": "Try a cut", "test": True,
         "detail": "It heats if it needs to, cuts, then backs the filament up out of the head so you can look at the end.",
         "done": "Cut once"},
    ],
    "asked": {"title": "Did it cut clean?",
              "detail": "Pull the filament out at the top of the head and look at the end: a clean slant is a clean cut.",
              "yes": "Clean, save it", "no": "Not all the way"},
    "done_line": "Touches at X {x_touch:g}, Y {y:g}; pressed at X {x_pressed:g}.",
}
KINDS = {"cutter": CUTTER}


def var(kind: str, value: str) -> str:
    return f"spot_{kind}_{value}"


class Spots:
    """The guide's state and what it sends. The tracker gives it the printer's status and its safe-move helpers."""

    def __init__(self, status: Callable[[], Dict[str, Any]], queue: Callable[[str], None],
                 why_not: Callable[[], Optional[str]], limits: Callable[[], tuple],
                 position: Callable[[float], List[float]], homed: Callable[[], bool]) -> None:
        self._status, self._queue, self._why_not = status, queue, why_not
        self._limits, self._position, self._homed = limits, position, homed
        self.guide: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self._aim: Optional[tuple] = None      # (x, y, z, when): taps add up before live_position catches up

    # ---- what the printer has ----------------------------------------------------------------

    def kinds(self) -> List[Dict[str, Any]]:
        st = self._status()
        return [k for k in KINDS.values() if k["macro"] in st]

    def values(self, kind: Dict[str, Any]) -> Dict[str, Any]:
        """Each value: saved here (set), else the macro's own number (a guess nobody measured), else None."""
        st = self._status()
        saved = ((st.get("save_variables") or {}).get("variables") or {})
        macro = st.get(kind["macro"]) or {}
        out: Dict[str, Any] = {}
        for value, _, theirs in kind["values"]:
            v = saved.get(var(kind["id"], value))
            out[value] = {"value": float(v) if isinstance(v, (int, float)) else _num(macro.get(theirs)),
                          "set": isinstance(v, (int, float))}
        return out

    # ---- the view ----------------------------------------------------------------------------

    def view(self, now: float) -> Optional[Dict[str, Any]]:
        kinds = self.kinds()
        if not kinds:
            return None
        rows = []
        for k in kinds:
            vals = self.values(k)
            is_set = all(v["set"] for v in vals.values())
            flat = {n: v["value"] for n, v in vals.items()}
            line = k["done_line"].format(**flat) if is_set else f"{k['about']}. Not set yet."
            rows.append({"kind": k["id"], "name": k["name"], "set": is_set, "line": line,
                         "values": [{"id": n, "label": label, "value": vals[n]["value"], "set": vals[n]["set"]}
                                    for n, label, _ in k["values"]]})
        return {"rows": rows, "why_not": self._why_not(), "guide": self._guide_view(now), "error": self.error}

    def _guide_view(self, now: float) -> Optional[Dict[str, Any]]:
        g = self.guide
        if g is None:
            return None
        kind = KINDS[g["kind"]]
        step = kind["steps"][g["step"]]
        pos = self._here(now)
        out = {"kind": kind["id"], "name": kind["name"], "n": g["step"] + 1, "of": len(kind["steps"]),
               "step": step["id"], "title": step["title"], "detail": step["detail"], "done": step["done"],
               "axis": step.get("axis"), "steps": list(step.get("steps") or []), "test": bool(step.get("test")),
               "position": {"x": round(pos[0], 2), "y": round(pos[1], 2), "z": round(pos[2], 2)},
               "kept": dict(g["kept"]), "trying": g["trying"], "asked": None, "error": g.get("error")}
        if g["trying"] is False and g.get("tried"):
            out["asked"] = dict(kind["asked"])
        if step["id"] == "press" and "x_touch" in g["kept"]:
            out["pressed"] = round(abs(pos[0] - g["kept"]["x_touch"]), 2)
        return out

    # ---- what a tap does ---------------------------------------------------------------------

    def input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        op = payload.get("op")
        self.error = None
        if op == "cancel":
            return self._cancel(now)
        why = self._why_not()
        if why:
            self.error = why
            return False
        if op == "start":
            return self._start(str(payload.get("kind") or ""), now)
        if op == "set":
            return self._set_numbers(str(payload.get("kind") or ""), payload.get("values") or {})
        if op == "go":
            return self._go_to(str(payload.get("kind") or ""), now)
        g = self.guide
        if g is None:
            return False
        kind = KINDS[g["kind"]]
        step = kind["steps"][g["step"]]
        if op == "move":
            return self._nudge(step, payload, now)
        if op == "next":
            return self._next(kind, step, now)
        if op == "back":
            if g["step"] == 0:
                return False
            g["step"], g["tried"], g["error"] = g["step"] - 1, False, None
            return True
        if op == "try" and step.get("test"):
            return self._try(kind, g)
        if op == "answer" and g.get("tried") and not g["trying"]:
            if payload.get("clean"):
                return self._save(kind, g["kept"], now)
            g["step"], g["tried"] = next(i for i, s in enumerate(kind["steps"]) if s["id"] == "press"), False
            return True
        return False

    def on_console(self, line: str) -> None:
        """The test's end, from the macro's own words; a Klipper error ends it too."""
        g = self.guide
        if g is None or not g["trying"]:
            return
        low = (line or "").lower()
        if "tip cut complete" in low:
            g["trying"], g["tried"] = False, True
        elif low.startswith("!!") or low.startswith("// error"):
            g["trying"], g["error"] = False, (line or "").lstrip("!/ ").strip() or "The cut stopped."

    # ---- the steps ---------------------------------------------------------------------------

    def _start(self, kind_id: str, now: float) -> bool:
        kind = KINDS.get(kind_id)
        if kind is None or kind not in self.kinds():
            return False
        vals = {n: v["value"] for n, v in self.values(kind).items()}
        if vals.get("x_touch") is None or vals.get("y") is None:
            self.error = "The cutter's macro doesn't say roughly where its screw is."
            return False
        lo, hi = self._limits()
        away = 1.0 if (vals.get("x_pressed") is None or vals["x_pressed"] <= vals["x_touch"]) else -1.0
        start_x = min(hi[0], max(lo[0], vals["x_touch"] + away * START_CLEAR))
        self.guide = {"kind": kind_id, "step": 0, "kept": {"y": vals["y"]}, "trying": False, "tried": False,
                      "error": None, "away": away, "start_x": start_x}
        self._travel(start_x, vals["y"], now)
        return True

    def _travel(self, x: float, y: float, now: float) -> None:
        lo, hi = self._limits()
        pos = self._here(now)
        z = min(hi[2] - 1, max(SAFE_Z, pos[2] if self._homed() else 0))
        x, y = min(hi[0], max(lo[0], x)), min(hi[1], max(lo[1], y))
        home = [] if self._homed() else ["G28"]
        self._queue("\n".join(home + ["G90", f"G1 Z{z:.2f} F900", f"G1 X{x:.2f} Y{y:.2f} F{XY_SPEED}"]))
        self._aim = (x, y, z, now)

    def _nudge(self, step: Dict[str, Any], payload: Dict[str, Any], now: float) -> bool:
        axis = str(payload.get("axis") or "x").lower()
        try:
            mm = float(payload.get("mm") or 0)
        except (TypeError, ValueError):
            return False
        if axis not in ("x", "y") or axis not in (step.get("axis") or "") or not mm or abs(mm) > max(step["steps"]) + 1e-9:
            return False
        i = "xy".index(axis)
        lo, hi = self._limits()
        pos = self._here(now)
        to = list(pos)
        to[i] = min(hi[i], max(lo[i], pos[i] + mm))
        if abs(to[i] - pos[i]) < 0.005:
            return False
        speed = PRESS_SPEED if step["id"] == "press" else NUDGE_SPEED
        self._queue(f"G90\nG1 {axis.upper()}{to[i]:.2f} F{speed}")
        self._aim = (to[0], to[1], to[2], now)
        return True

    def _next(self, kind: Dict[str, Any], step: Dict[str, Any], now: float) -> bool:
        g = self.guide
        if step.get("test"):
            return False
        here = self._here(now)
        x = round(here[0], 2)
        if step["id"] == "press":
            touch = g["kept"].get("x_touch")
            if touch is None or (touch - x) * g["away"] < MIN_PRESS:
                g["error"] = "Press it further toward the screw than where it touched."
                return False
        for axis, value in step["keeps"].items():
            g["kept"][value] = round(here["xy".index(axis)], 2)
        g["step"], g["error"] = g["step"] + 1, None
        return True

    def _try(self, kind: Dict[str, Any], g: Dict[str, Any]) -> bool:
        k = g["kept"]
        if k.get("x_touch") is None or k.get("x_pressed") is None:
            return False
        g["trying"], g["tried"], g["error"] = True, False, None
        self._queue(f"CUT_TIP FINAL_EJECT=1 PIN_X={k['x_touch']:g} PIN_X_PRESSED={k['x_pressed']:g} PIN_Y={k['y']:g}")
        self._aim = None
        return True

    def _save(self, kind: Dict[str, Any], kept: Dict[str, float], now: float) -> bool:
        self._queue("\n".join(f"SAVE_VARIABLE VARIABLE={var(kind['id'], n)} VALUE={kept[n]:g}"
                              for n, _, _ in kind["values"] if kept.get(n) is not None))
        self.guide = None
        return True

    def _cancel(self, now: float) -> bool:
        g, self.guide = self.guide, None
        if g is None:
            return False
        if not g["trying"] and self._homed():
            pos = self._here(now)
            self._queue(f"G90\nG1 X{g['start_x']:.2f} F{NUDGE_SPEED}")   # off the screw before anything else moves
            self._aim = (g["start_x"], pos[1], pos[2], now)
        return True

    # ---- Advanced: the numbers ---------------------------------------------------------------

    def _set_numbers(self, kind_id: str, values: Dict[str, Any]) -> bool:
        kind = KINDS.get(kind_id)
        if kind is None or kind not in self.kinds():
            return False
        lo, hi = self._limits()
        got: Dict[str, float] = {}
        for n, label, _ in kind["values"]:
            try:
                got[n] = float(values[n])
            except (KeyError, TypeError, ValueError):
                self.error = f"{label} needs a number."
                return False
            axis = 1 if n == "y" else 0
            if not lo[axis] <= got[n] <= hi[axis]:
                self.error = f"{label} is outside where the head can go ({lo[axis]:g} to {hi[axis]:g})."
                return False
        if abs(got["x_touch"] - got["x_pressed"]) < MIN_PRESS:
            self.error = "Pressed at X has to be further toward the screw than Touches at X."
            return False
        return self._save(kind, got, time.time())

    def _go_to(self, kind_id: str, now: float) -> bool:
        kind = KINDS.get(kind_id)
        if kind is None or kind not in self.kinds():
            return False
        vals = {n: v["value"] for n, v in self.values(kind).items()}
        if vals.get("x_touch") is None or vals.get("y") is None:
            return False
        self._travel(vals["x_touch"], vals["y"], now)
        return True

    def _here(self, now: float) -> List[float]:
        if self._aim is not None and now - self._aim[3] < 5:
            return list(self._aim[:3])
        return self._position(now)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
