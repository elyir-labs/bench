"""A tool change done by the service (design/ace-driver/, A, the quiet pause).

In a print, the printer's ELYIR_TOOL macro pauses the file without parking (PAUSE_BASE) and calls the service.
The service runs the printer's own before-change macro, takes the old filament out, brings the new one in,
runs the after-change macro (the purge), and resumes. From the screen it's the same without pause and resume.
Cancel works throughout: nothing holds Klipper's queue between steps.

Out:  feed assist goes off and, without waiting, the extruder backs the filament out of the head: stopping feed
      assist makes the unit pull back a little, so both pull the same way (with feed assist still on, the unit
      pushed while the extruder pulled, and the filament buckled and snapped in the splitter; waiting for that
      pull to finish first doesn't work, it can't while the gears hold the filament). If the sensor still sees
      filament, the unit pulls until it clears (its push arrives first); then it unwinds to its parking spot.
In:   the unit feeds until the sensor sees filament, stops, and the extruder pulls it to the nozzle with feed
      assist pushing behind.

A second switch after the gears, just above the hotend (design/filament-units/, A): the extruder carries the filament
until that switch sees it, so a load whose gears didn't grip stops there instead of pushing into nothing, and the push
to the nozzle starts from a known point. Taking it out, a hotend switch that still sees filament after the back-off
means it's stuck in the hotend: the unit stops pulling. A printer without one changes nothing.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

DEFAULTS = {
    "sensor": "filament_switch_sensor extruder_sensor",
    "sensor_to_nozzle": 120,    # mm from the extruder sensor to the nozzle
    "backoff": None,            # mm the extruder backs the filament out while the unit pulls; None: sensor_to_nozzle
                                # + 5. With a cutter: enough to bring the cut end up out of the gears (0 when the cut
                                # is above them)
    "park": 170,                # mm the unit unwinds after the sensor clears, back to its parking spot
    "max_feed": 1600,           # mm the unit may feed before the sensor has to have seen the filament
    "clear_max": 200,           # mm the unit may pull, on top of the back-off's time, for the sensor to clear: a
                                # cutter between the gears and the sensor leaves the tip under it, out of the gears' reach
    "clear_speed": 20,          # mm/s for that pull
    "backoff_speed": 15,        # mm/s for the back-off, under clear_speed so the unit's pull keeps the filament taut
    "extruder_speed": 5,        # mm/s for extruder moves, and the unit's speed while they share the filament
    "feed_speed": 80,
    "unwind_speed": 50,
    "temp": 230,                # nozzle temperature when the printer isn't hot already
    "cool_after": 600,          # s a failed change in a print may wait, nozzle hot, before it cools to standby_temp
    "standby_temp": 150,        # under Klipper's min_extrude_temp, so a plain RESUME stops rather than print cold
    "purge_moves": "",          # "x,y x,y": the way to the purge spot, taken at the current height before anything
                                # pushes filament into the nozzle, so the first ooze lands where it's cleaned off
    "purge_speed": 50,          # mm/s along that way
    "push_start": "",           # G-code before the extruder pushes filament into the nozzle, and push_end after (even
    "push_end": "",             # when the push fails): e.g. a purge belt running so the ooze is carried off, not
                                # pushed back into the nozzle
    "before_macro": "",         # the printer's own, given FROM, TO, TEMP, PURGE (e.g. tip shaping, a move to the bin)
    "after_macro": "",          # the same (e.g. the purge and the way back)
    "hotend_to_nozzle": None,   # mm from the hotend switch to the nozzle; None: sensor_to_nozzle less what the
                                # extruder carried from one switch to the other
    "through_max": 60,          # mm the extruder may carry it from the extruder switch for the hotend switch to see it
    "through_step": 2,          # mm per extruder move while it looks for the hotend switch
}
HOTEND = "gcode_button elyir_units_hotend"
EXTRUDER_BUTTON = "gcode_button elyir_units_sensor"     # on the extruder switch's pin, always in our file
GEARS_HOLD_S = 0.6       # the gears read as turning this long after the last report that they were (between 2 mm moves)
NOT_THROUGH = "The extruder didn't take the filament."
STUCK = "The filament is stuck in the hotend."
# Nozzle temperatures for a change by material; the hotter of the spool going out and the one coming in wins
TEMPS = {"PLA": 210, "PETG": 240, "ABS": 250, "ASA": 255, "TPU": 225, "PA": 260, "PC": 270, "HIPS": 240}
MOVING = ("shifting", "feeding", "unwinding")


class ChangeError(Exception):
    pass


class Changer:
    def __init__(self, svc: Any, settings: Dict[str, Any]) -> None:
        self.svc = svc
        self.s = dict(DEFAULTS, **(settings or {}))
        self.mr: Any = None
        self.detected: Optional[bool] = None
        self.hotend: Optional[bool] = None      # the switch above the hotend; None: this printer has none
        self.gears: Optional[str] = None        # "in" or "out" while the extruder turns, from Klipper's own report
        self._gears_still: Optional[asyncio.TimerHandle] = None
        self.print_state: Optional[str] = None
        self.paused: Optional[bool] = None
        self.target = 0.0
        self.task: Optional[asyncio.Task] = None
        self.step: Optional[str] = None
        self.going: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.failed: Optional[Dict[str, Any]] = None    # the change that ended in error: from, to, in_print
        self.cooled = False
        self.cooling: Optional[asyncio.Task] = None

    # ---- what the printer says -----------------------------------------------------------

    def objects(self) -> Dict[str, Any]:
        return {self.s["sensor"]: ["filament_detected"], EXTRUDER_BUTTON: ["state"], HOTEND: ["state"], "motion_report": ["live_extruder_velocity"],
                "print_stats": ["state"],
                "pause_resume": ["is_paused"], "extruder": ["target", "temperature"]}

    def on_status(self, st: Dict[str, Any]) -> None:
        # Moonraker answers None for an object Klipper doesn't have, which is no reading, never a clear switch: Studio
        # lost its filament_switch_sensor and read an empty head with filament in it (16 November). The button is ours.
        button = (st.get(EXTRUDER_BUTTON) or {}).get("state")
        sensor = (st.get(self.s["sensor"]) or {}).get("filament_detected")
        if button is not None:
            self._sensor(str(button).upper() == "PRESSED")
        elif sensor is not None:
            self._sensor(bool(sensor))
        if "live_extruder_velocity" in (st.get("motion_report") or {}):
            self._turning(float(st["motion_report"]["live_extruder_velocity"] or 0))
        # None: Moonraker's answer for a printer without the switch, which isn't one reading clear
        if (st.get(HOTEND) or {}).get("state") is not None:
            self._hotend(str(st[HOTEND]["state"]).upper() == "PRESSED")
        if "state" in (st.get("print_stats") or {}):
            self.print_state = st["print_stats"]["state"]
            if self.going and self.going["in_print"] and self.print_state in ("cancelled", "standby", "error", "complete"):
                if self.task and not self.task.done():
                    self.task.cancel()
        if "is_paused" in (st.get("pause_resume") or {}):
            self.paused = bool(st["pause_resume"]["is_paused"])
        if "target" in (st.get("extruder") or {}):
            self.target = float(st["extruder"]["target"] or 0)

    def on_sensor_push(self, params: Dict[str, Any]) -> None:
        """The gcode_button on a switch's pin: pressed is filament there."""
        if params.get("switch") == "hotend":
            self._hotend(params.get("state") == "pressed")
        else:
            self._sensor(params.get("state") == "pressed")

    def _turning(self, velocity: float) -> None:
        """Which way the extruder's gears turn, for the screens' drawing. Still only once it has stayed still a moment:
        a load's short moves would flicker it otherwise."""
        way = "in" if velocity > 0.5 else "out" if velocity < -0.5 else None
        if self._gears_still is not None:
            self._gears_still.cancel()
            self._gears_still = None
        if way is None:
            if self.gears is not None:
                self._gears_still = asyncio.get_event_loop().call_later(GEARS_HOLD_S, self._set_gears, None)
            return
        self._set_gears(way)

    def _set_gears(self, way: Optional[str]) -> None:
        if way != self.gears:
            self.gears = way
            self.svc.changed()

    def _hotend(self, detected: bool) -> None:
        if detected != self.hotend:
            logging.getLogger("units").info("hotend switch %s (step %s)", "filament" if detected else "clear", self.step)
            self.hotend = detected
            self.svc.changed()

    def _sensor(self, detected: bool) -> None:
        if detected != self.detected:
            logging.getLogger("units").info("sensor %s (step %s)", "filament" if detected else "clear", self.step)
            self.detected = detected
            self.svc.changed()      # the screens draw the switches

    async def _until(self, cond, timeout: float, unit: Any = None) -> bool:
        """Wait for cond, at most timeout seconds; with a unit, also until it has stopped moving by itself."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        while not cond():
            if loop.time() - start > timeout:
                return False
            if unit is not None and loop.time() - start > 1.0 and unit.status.get("action") not in MOVING:
                return cond()
            await asyncio.sleep(0.01)
        return True

    # ---- the change ------------------------------------------------------------------------

    def state(self) -> Optional[Dict[str, Any]]:
        if self.error:
            return dict(self.failed or {}, error=self.error, cooled=self.cooled)
        if self.going:
            return dict(self.going, step=self.step, error=None)
        return None

    def start(self, to: int, in_print: bool, length: Optional[float] = None) -> None:
        """From the ELYIR_TOOL macro: run in the background, the macro has already returned. length: the purge the
        slicer worked out for this pair of colors (ELYIR_PURGE), handed to the after-change macro."""
        if self.task and not self.task.done():
            logging.info("units: a tool change to %s came while one is going", to)
            return
        self.task = asyncio.ensure_future(self._background(to, in_print, length))

    async def _background(self, to: int, in_print: bool, length: Optional[float] = None) -> None:
        try:
            await self.change(to, in_print, length=length)
        except (ChangeError, asyncio.CancelledError) as e:
            logging.info("units: tool change to %s stopped: %s", to, self.error or e)

    async def change(self, to: int, in_print: bool = False, purge: bool = True, length: Optional[float] = None) -> None:
        if self.going:
            raise ChangeError("A tool change is already going.")
        if self.mr is None or not self.mr.ready.is_set():
            raise ChangeError("The printer isn't connected.")
        frm = self.svc.saved["selected"]
        if self.cooling and not self.cooling.done():
            self.cooling.cancel()
        self.going, self.error, self.failed = {"from": frm, "to": to, "in_print": in_print}, None, None
        self.cooled = False
        self.svc.changed()
        try:
            if self.task is None or self.task.done():
                self.task = asyncio.current_task()
            await self._change(frm, to, in_print, purge, length)
        except asyncio.CancelledError:
            self.error, self.failed = "The print was stopped during the tool change.", dict(self.going)
            await self._halt()
            raise
        except ChangeError as e:
            self.error, self.failed = str(e), dict(self.going)
            await self._halt()
            raise
        except Exception as e:     # the unit or the printer stopped answering: say so, and stop the unit
            self.error, self.failed = str(e) or e.__class__.__name__, dict(self.going)
            await self._halt()
            raise ChangeError(self.error) from e
        finally:
            if self.error:
                logging.getLogger("units").info("change %s -> %s failed at %s: %s", frm, to, self.step, self.error)
                if in_print:
                    self.cooling = asyncio.ensure_future(self._cool_when_nobody_answers())
            self.going, self.step = None, None
            self.svc.changed()

    async def _change(self, frm: Optional[int], to: int, in_print: bool, purge: bool, length: Optional[float] = None) -> None:
        s = self.s
        logging.getLogger("units").info("change %s -> %s (in print: %s)", frm, to, in_print)
        if in_print:
            self.step = "pause"
            if not await self._until(lambda: self.paused is True, 15):
                raise ChangeError("The print didn't pause for the tool change.")
        if frm == to:
            if in_print:
                await self.mr.gcode("RESUME_BASE")
            return
        if to >= self.svc.slot_count():
            raise ChangeError(f"This print wants slot {to + 1}, and there are {self.svc.slot_count()} slots.")
        temp = self._temp(frm, to)
        args = f"FROM={-1 if frm is None else frm} TO={to} TEMP={temp} PURGE={1 if purge else 0}"
        if length is not None:
            args += f" LENGTH={round(length, 1)}"
        if frm is not None:
            # the printer's macro may pull the filament back (a tip cut); feed assist pushing against it buckles it
            # in the splitter, and then the unit can't pull it out (Workshop, 18 and 21 October)
            u, k = self.svc.where(frm)
            self.step = "assist_off"
            await u.call("stop_feed_assist", {"index": k})
            self.svc.saved["assist"] = None     # a restart mid-change, or after one failed, mustn't turn it back on
            self.svc._save()
        if s["before_macro"]:
            self.step = "before"
            await self.mr.gcode(f"{s['before_macro']} {args}")
        if self.target < temp - 5:
            self.step = "heat"
            await self.mr.gcode(f"M109 S{temp}")
        if frm is not None:
            await self._out(frm)
            # the head is empty now: a load that fails next mustn't leave the old slot down as in it
            self.svc.saved["selected"] = None
            self.svc._save()
        if to >= 0:
            await self._in(to)
        self.svc.saved["selected"] = to if to >= 0 else None
        self.svc.saved["assist"] = to if to >= 0 else None
        self.svc._save()
        if s["after_macro"] and to >= 0:
            self.step = "after"
            await self.mr.gcode(f"{s['after_macro']} {args}")
        if in_print:
            self.step = "resume"
            await self.mr.gcode("RESUME_BASE")

    async def _cool_when_nobody_answers(self) -> None:
        """A paused print's nozzle stays hot for as long as nobody comes; PETG left hours at 240 clogged one."""
        await asyncio.sleep(float(self.s["cool_after"]))
        standby = float(self.s["standby_temp"])
        if self.error and self.going is None and self.paused and self.target > standby:
            await self.mr.gcode(f"M104 S{standby:g}")
            self.cooled = True
            logging.getLogger("units").info("cooled the nozzle to %g while the failed change waits", standby)
            self.svc.changed()

    def _temp(self, frm: Optional[int], to: int) -> int:
        materials = {sl["slot"]: (sl.get("material") or "").upper() for sl in self.svc.state()["slots"]}
        known = [TEMPS[m] for m in (materials.get(frm), materials.get(to)) if m in TEMPS]
        return max(known) if known else int(self.s["temp"])

    async def _out(self, slot: int, backoff: Optional[float] = None) -> None:
        """backoff: how far the extruder backs out, when it's known to be less than the whole way from the nozzle (a
        load that stopped short); the stuck check is for filament that reached the hotend, so it's off then."""
        s = self.s
        u, k = self.svc.where(slot)
        self.step = "out"
        short = backoff is not None
        if not short:
            backoff = float(s["sensor_to_nozzle"]) + 5 if s.get("backoff") is None else float(s["backoff"])
        await u.until_ready(60)
        if self.detected is not False:
            # The unit pulls first and the extruder backs out slower than it pulls, so the filament between them
            # stays taut; backed out alone it was pushed up a tube the unit held still and buckled (Workshop, 18 and
            # 21 October). The unit slips while the gears still hold it, so its pull covers the back-off's time too.
            speed = min(float(s["backoff_speed"]), float(s["clear_speed"]) * 0.75)
            pull = float(s["clear_max"]) + (backoff / speed * float(s["clear_speed"]) if backoff > 0 else 0)
            await u.call("unwind_filament", {"index": k, "length": int(pull), "speed": s["clear_speed"]})
            if backoff > 0:
                await self._until(lambda: u.status.get("action") == "unwinding", 5)
                # M400: Klipper answers a G-code once the move is queued, not done (Workshop, 18 October)
                await self.mr.gcode(f"M83\nG1 E-{backoff:g} F{int(speed * 60)}\nM400")
                # only on the back-off made for no cutter: a cutter leaves its cut piece under the switch
                if not short and s.get("backoff") is None and not await self._until(lambda: self.hotend is not True, 0.5):
                    await self._stop(u, k, "stop_unwind_filament")
                    raise ChangeError(STUCK)
            cleared = await self._until(lambda: self.detected is False, pull / s["clear_speed"] + 3, u)
            await self._stop(u, k, "stop_unwind_filament")
            if not cleared:
                raise ChangeError("The filament didn't come out of the toolhead.")
        self.step = "park"
        await u.until_ready()
        await u.call("unwind_filament", {"index": k, "length": int(s["park"]), "speed": s["unwind_speed"]})
        await self._still(u)

    async def _in(self, slot: int) -> None:
        s = self.s
        u, k = self.svc.where(slot)
        self.step = "in"
        await u.until_ready()
        await u.call("feed_filament", {"index": k, "length": int(s["max_feed"]), "speed": s["feed_speed"]})
        reached = await self._until(lambda: self.detected is True, s["max_feed"] / s["feed_speed"] + 5, u)
        await self._stop(u, k, "stop_feed_filament")
        if not reached:
            raise ChangeError("The filament didn't reach the toolhead.")
        await u.until_ready()
        await u.call("start_feed_assist", {"index": k})
        to_nozzle = float(s["sensor_to_nozzle"])
        if self.hotend is False:
            self.step = "through"
            carried = await self._through(slot, u, k)
            to_nozzle = float(s["hotend_to_nozzle"]) if s.get("hotend_to_nozzle") is not None else max(to_nozzle - carried, 0)
        elif self.hotend:
            logging.getLogger("units").info("hotend switch saw filament before this load: pushing the whole %g", to_nozzle)
        self.step = "nozzle"
        await self.to_purge_spot()
        await self._push(f"M83\nG1 E{to_nozzle:g} F{int(s['extruder_speed'] * 60)}\nM400")

    async def _through(self, slot: int, u: Any, k: int) -> float:
        """The extruder carries the filament, a little at a time, until the hotend switch sees it: mm carried."""
        s = self.s
        step, carried = float(s["through_step"]), 0.0
        while not await self._until(lambda: self.hotend is True, 0.05):
            if carried >= float(s["through_max"]):
                await u.call("stop_feed_assist", {"index": k})
                # back to its parking spot, so Try again starts from an empty head
                try:
                    await self._out(slot, backoff=carried + 5)
                except ChangeError:
                    raise ChangeError(NOT_THROUGH + " It didn't come back out either: check the head.")
                raise ChangeError(NOT_THROUGH)
            await self.mr.gcode(f"M83\nG1 E{step:g} F{int(s['extruder_speed'] * 60)}\nM400")
            carried += step
        return carried

    def purge_points(self) -> list:
        points = []
        for pair in str(self.s.get("purge_moves") or "").split():
            x, _, y = pair.partition(",")
            try:
                points.append((float(x), float(y)))
            except ValueError:
                raise ChangeError(f"purge_moves has '{pair}', which isn't x,y.")
        return points

    async def to_purge_spot(self) -> None:
        points = self.purge_points()
        if points:
            feed = int(float(self.s["purge_speed"]) * 60)
            moves = "\n".join(f"G1 X{x:g} Y{y:g} F{feed}" for x, y in points)
            await self.mr.gcode(f"SAVE_GCODE_STATE NAME=elyir_purge\nG90\n{moves}\nM400\nRESTORE_GCODE_STATE NAME=elyir_purge")

    async def purge(self, mm: float, temp: Optional[int] = None) -> None:
        """Push more through, at the purge spot: what Bench's "Push more through" asks of a unit on the service."""
        if self.going:
            raise ChangeError("A tool change is going.")
        if self.mr is None or not self.mr.ready.is_set():
            raise ChangeError("The printer isn't connected.")
        if temp:
            await self.mr.gcode(f"M109 S{int(temp)}")
        await self.to_purge_spot()
        await self._push(f"M83\nG1 E{float(mm):g} F150\nM400")

    async def _push(self, script: str) -> None:
        """Push filament into the nozzle, with the printer's push_start and push_end around it."""
        if self.s.get("push_start"):
            await self.mr.gcode(self.s["push_start"])
        try:
            await self.mr.gcode(script)
        finally:
            if self.s.get("push_end"):
                await self.mr.gcode(self.s["push_end"])

    async def _stop(self, u: Any, k: int, method: str) -> None:
        """A feed stop sent while the unit is still shifting is ignored, so send it until the motor is still."""
        for _ in range(10):
            await u.call(method, {"index": k})
            await asyncio.sleep(0.15)
            if (await u.status_now()).get("action") not in MOVING:
                return

    async def _still(self, u: Any) -> None:
        for _ in range(int(120 / 0.1)):
            st = await u.status_now()
            if st.get("action") not in MOVING and st.get("status") == "ready":
                return
            await asyncio.sleep(0.1)
        raise ChangeError("The filament unit is still moving.")

    async def _halt(self) -> None:
        """Whatever went wrong, the unit stops pulling or pushing: stops are sent until each unit is still,
        since one sent while it's still shifting is ignored."""
        for u in self.svc.units:
            if not u.connected:
                continue
            for _ in range(10):
                for k in range(len(u.status.get("slots") or [None] * 4)):
                    for method in ("stop_feed_filament", "stop_unwind_filament"):
                        try:
                            await u.call(method, {"index": k})
                        except Exception:
                            pass
                await asyncio.sleep(0.15)
                try:
                    st = await u.status_now()
                except Exception:
                    break
                if st.get("action") not in MOVING:
                    break
