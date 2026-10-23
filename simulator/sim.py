#!/usr/bin/env python3
"""
Elyir Bench printer simulator.

A fake Moonraker that speaks just enough JSON-RPC for the app, drives a
pretend printer through scripted scenarios, and runs the REAL intent engine
over the pretend status. Develop the UI on a laptop; what you see is what the
Pi will publish.

    python3 sim.py                       # http://localhost:7126, scenario "day"
    python3 sim.py --scenario runout     # jump straight to a runout
    python3 sim.py --speed 8             # everything 8x faster

Control page with buttons:  http://localhost:7126/sim
"""

from __future__ import annotations

import argparse
import ast
import base64
import re
import shlex
import asyncio
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aiohttp import web, WSMsgType

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "printer"))
import elyir_bench_intent as engine  # noqa: E402
import elyir_bench_care as care  # noqa: E402
from scenarios import SCENARIOS, FILES, OBJECTS, COLOUR_FILES  # noqa: E402
import library  # noqa: E402
import setup_card  # noqa: E402
import bring  # noqa: E402
import slicer_profile  # noqa: E402
import unit_skins  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "..", "installer"))
try:
    import elyir_bench as installer  # noqa: E402  (the unit setup's catalog and board scan: one table, the installer's)
except ImportError:   # the browser demo ships the simulator and the printer code, not the installer
    installer = None


# --------------------------------------------------------------------------
# Pretend printer
# --------------------------------------------------------------------------

def fresh_status() -> Dict[str, Any]:
    return {
        "webhooks": {"state": "ready", "state_message": "Printer is ready"},
        "print_stats": {"state": "standby", "filename": "", "print_duration": 0.0, "total_duration": 0.0,
                        "message": "", "info": {"current_layer": None, "total_layer": None}},
        "display_status": {"message": "", "progress": 0.0},
        "virtual_sdcard": {"progress": 0.0, "is_active": False, "file_position": 0},
        "pause_resume": {"is_paused": False},
        "idle_timeout": {"state": "Idle"},
        "exclude_object": {"objects": [], "excluded_objects": [], "current_object": None},
        "heater_bed": {"temperature": 23.0, "target": 0.0},
        "extruder": {"temperature": 23.0, "target": 0.0, "can_extrude": False},
        "toolhead": {"homed_axes": "", "axis_minimum": [0.0, 0.0, -5.0, 0.0], "axis_maximum": [350.0, 350.0, 340.0, 0.0]},
        "motion_report": {"live_position": [300.0, 300.0, 30.0, 0.0]},
        "gcode_move": {"homing_origin": [0.0, 0.0, 0.0, 0.0]},
        "temperature_sensor Chamber": {"temperature": 24.5},
        "gcode_macro _PRINT_START_SETTINGS": {"chamber_max": 30.0},   # Workshop's: wait for the chamber, at most 30°
        "filament_switch_sensor extruder_sensor": {"filament_detected": True},
        # KlipperACE's multi-unit shape, as Workshop reports it: two units of four slots, one dryer each.
        "ace": {
            "status": "ready", "total_gates": 8, "num_devices": 2,
            "gate_color": ["D9534F", "F1F1F1", "2B2B2B", "3B82F6", "F5C542", "FFFFFF", "8B5CF6", "FFFFFF"],
            "gate_material": ["PLA", "PLA", "PLA", "PLA", "PETG", "PLA", "", ""],
            "gate_temp": [210, 210, 210, 210, 240, 210, 230, 230],
            "selected_gate": 0, "endless_spool": True, "enable_rfid": 1,
            "gate_feed_assist": [True] + [False] * 7,
            "devices": [sim_unit(0, [{"status": "ready", "rfid": 1, "remain": 610}, {"status": "ready", "rfid": 1, "remain": 120},
                                     {"status": "ready", "rfid": 0, "remain": 40}, {"status": "ready", "rfid": 1, "remain": 900}], 26),
                        sim_unit(1, [{"status": "ready", "rfid": 1, "remain": 700}, {"status": "ready", "rfid": 0, "remain": 1000},
                                     {"status": "empty"}, {"status": "empty"}], 25)],
        },
    }


def sim_unit(i: int, slots: List[Dict[str, Any]], temp: float) -> Dict[str, Any]:
    for k, sl in enumerate(slots):
        sl.setdefault("index", k)
    return {"name": f"ACE_{i + 1}", "alias": "", "gate_offset": i * 4, "gates": [0, 1, 2, 3], "connected": True,
            "status": {"status": "ready", "temp": temp, "slots": slots,
                       "dryer_status": {"status": "stop", "target_temp": 0, "duration": 0, "remain_time": 0}}}


SIM_TUBE_MM = 900   # pulled back this far, the slot's sensor no longer sees the filament


UNIT_BOARD = "usb-Klipper_stm32g0b1xx_4F0034000A50425539393020-if00"        # a BTT MMB, plugged in and not used yet


class SimPrinter:
    def __init__(self, name: str, speed: float, ace: bool = True, light: str = "pin", skin: Optional[str] = None):
        self.name = name
        self.skin = skin   # --units afc / happy_hare: the pretend ACEs shown as AFC's lanes or Happy Hare's gates
        self.skin_start = skin
        # scenario unit_setup (design/unit-setup/, B, stage 2): no unit in Klipper, a bare board on USB; the pretend
        # installer then shows the pretend ACEs as the unit it set up (a skin), and Put it back hides them again
        self.bare = False
        self.bare_board = UNIT_BOARD
        self.fail_unit_install = False   # the next install fails once, at Klipper's restart
        self.unit_kept: Optional[Dict[str, Any]] = None
        self.light = light   # the chamber light (--light): pin (an on/off light), strip (status LEDs), both, none
        self.speed = speed
        self.port = 7126   # main() sets the one it serves on: the Advanced door's stand-in page is there
        self.ace = ace   # False: a printer without a filament unit, one spool (--no-ace)
        self.tap = False   # PRINT_START's tap stage runs (--tap): the printer finds its own first layer
        self.tap_default = False
        # Klipper's [save_variables] file: outlives restarts and scenarios. Workshop has one, Desk (--no-ace) doesn't.
        self.saved_vars: Dict[str, Any] = {}
        self.spool_record: Any = None   # what Moonraker's database would hold at elyir-bench/spool
        self.webcams: List[Dict[str, Any]] = []   # set by main(); empty with --no-camera
        # --units service: pretend ACE Pros behind the real filament-unit service (units/), instead of a pretend
        # KlipperACE. {"aces", "service", "link", "state"} once start_units() ran.
        self.units: Optional[Dict[str, Any]] = None
        self.status = self.fresh()
        self.klippy_state = "ready"
        self.klippy_message = "Printer is ready"
        self.tracker = self.new_tracker()
        self.fail_next_swap = False
        self.fail_check_slot: Optional[int] = None   # this slot's motor test fails once (the unit check, --units afc|happy_hare)
        self.fail_gear_gate: Optional[int] = None    # this gate's encoder run is thrown out once (measuring the gear)
        self.pulled: Dict[int, int] = {}   # mm each slot has been pulled back since it last had filament
        self.tracker.set_klippy_state("ready")
        self.tracker.update_status(self.seen(deepcopy(self.status)))
        self.clients: Set[web.WebSocketResponse] = set()
        # Turned off or restarting (design/power/): nothing answers until then (inf: until the sim restarts)
        self.down_until: Optional[float] = None
        self.extra_print_s = 0.0   # print time scenarios add on top of history (care_due)
        # one notifier for the whole run, like a Moonraker that stays up across prints
        self.notifier = engine.Notifier(f"sim{int(time.time())}")
        self.events: List[Dict[str, Any]] = []
        # What it printed before, newest first: 38 jobs over the files in library.py, and one whose file is gone.
        self.history: List[Dict[str, Any]] = library.history(FILES)
        self._scenario_task: Optional[asyncio.Task] = None
        self._waiting_for: Optional[str] = None
        self._last_intent_key: Optional[str] = None
        self.scenario_name = ""
        self.log: List[str] = []
        # Finish setting up (docs/setup-card.md): closed until a setup scenario opens it
        self.setup = setup_card.SetupCard()
        # Slicing like their prints (docs/slicer-profile.md): "yours" until a profile scenario says otherwise
        self.profile = slicer_profile.SlicerProfile()
        self._setup_tasks: List[asyncio.Task] = []
        # Bring it over (docs/bring-it-over.md): a printer with its config, until setup_printer takes it away
        self.bring = bring.Bring()
        self._bring_task: Optional[asyncio.Task] = None
        self._history_kept: Optional[List[Dict[str, Any]]] = None   # a fresh card has none; it comes over

    def fresh(self) -> Dict[str, Any]:
        status = fresh_status()
        status["gcode_macro _PRINT_START_SETTINGS"]["tap"] = self.tap
        if not self.ace:
            del status["ace"]
            status["gcode_macro _PRINT_START_SETTINGS"]["chamber_max"] = 0.0   # like Desk: a timed soak, no chamber wait
        else:
            status["save_variables"] = {"variables": deepcopy(self.saved_vars)}
        if self.units is not None:
            status.pop("ace", None)
        if self.light in ("pin", "both"):
            status["output_pin caselight"] = {"value": 0.0}
        if self.light in ("strip", "both"):
            status["neopixel caselight"] = {"color_data": [[0.0, 0.0, 0.3, 0.0]] * 16}
            status["led_effect rainbow"] = {"enabled": True}
        return status

    def save_vars(self, values: Dict[str, Any]) -> None:
        """SAVE_VARIABLE, as Klipper reports it: the whole variables dict again."""
        if "save_variables" not in self.status:
            self.gcode_response("!! Unknown command: SAVE_VARIABLE")
            return
        self.saved_vars.update(deepcopy(values))
        self.patch({"save_variables": {"variables": deepcopy(self.saved_vars)}})

    def apply_first_layer(self) -> None:
        """The shared PRINT_START's last step (common/print_start.cfg): the kept first layer."""
        sv = (self.status.get("save_variables") or {}).get("variables") or {}
        if "first_layer_z" not in sv and "first_layer_sheets" not in sv:
            return
        z = float(sv.get("first_layer_z") or 0)
        sheets, sheet = sv.get("first_layer_sheets") or {}, str(sv.get("first_layer_sheet") or "")
        if sheet and sheet in sheets:
            z = float(sheets[sheet]["z"])
        if str(sv.get("first_layer_against", "scan")) != ("tap" if self.tap else "scan") or abs(z) > 0.5:
            z = 0.0
        if z:
            self.gcode_response(f"First layer: {z:+.3f} mm, as kept")
        self.set_offset(z)

    # ---- the filament unit ---------------------------------------------------

    def slot(self, g: int) -> Dict[str, Any]:
        return self.status["ace"]["devices"][g // 4]["status"]["slots"][g % 4]

    def set_slot(self, g: int, replace: bool = False, **fields: Any) -> None:
        """Change one slot, and report the units the way KlipperACE does: the whole devices list."""
        devices = deepcopy(self.status["ace"]["devices"])
        sl = devices[g // 4]["status"]["slots"]
        sl[g % 4] = dict({"index": g % 4}, **fields) if replace else dict(sl[g % 4], **fields)
        self.patch({"ace": {"devices": devices}})

    def set_dryer(self, unit: int, **fields: Any) -> None:
        devices = deepcopy(self.status["ace"]["devices"])
        devices[unit]["status"]["dryer_status"].update(fields)
        self.patch({"ace": {"devices": devices}})

    def insert_spool(self, g: int, tag: Optional[Dict[str, Any]] = None) -> None:
        """A person puts a spool on and pushes its end into slot g; the unit grabs it."""
        self.pulled[g] = 0
        fields = {"status": "ready", "rfid": 1 if tag else 0, "remain": 1000}
        if tag:
            fields.update(type=tag["type"], color=tag["color"], sku=tag.get("sku", "SIM"))
        self.set_slot(g, replace=True, **fields)

    def endless_match(self, g: int) -> Optional[int]:
        """KlipperACE's endless spool: the closest same-colour, same-material slot that isn't empty."""
        ace = self.status["ace"]
        def hexc(c: str) -> List[int]:
            c = str(c).lstrip("#")
            return [int(c[i:i + 2], 16) for i in (0, 2, 4)]
        mats, cols = ace["gate_material"], ace["gate_color"]
        best, best_d = None, 70.0
        for k in range(len(mats)):
            if k == g or self.slot(k).get("status") == "empty" or not mats[k] or mats[k].upper() != (mats[g] or "").upper():
                continue
            d = sum((x - y) ** 2 for x, y in zip(hexc(cols[k]), hexc(cols[g]))) ** 0.5
            if d < best_d:
                best, best_d = k, d
        return best

    def light_gcode(self, script: str) -> None:
        """The chamber light's commands, as Klipper and the LED effects plugin report them."""
        params = {k.upper(): v for k, v in (w.split("=", 1) for w in script.split()[1:] if "=" in w)}
        if script.startswith("SET_PIN ") and f"output_pin {params.get('PIN')}" in self.status:
            self.patch({f"output_pin {params['PIN']}": {"value": float(params.get("VALUE", 0))}})
        elif script.startswith("SET_LED ") and f"neopixel {params.get('LED')}" in self.status:
            color = [float(params.get(k, 0)) for k in ("RED", "GREEN", "BLUE", "WHITE")]
            self.patch({f"neopixel {params['LED']}": {"color_data": [color] * 16}})
        elif script.startswith("STOP_LED_EFFECTS"):
            self.patch({k: {"enabled": False} for k in self.status if k.startswith("led_effect ")})
        elif script.startswith("SET_LED_EFFECT ") and f"led_effect {params.get('EFFECT')}" in self.status:
            self.patch({f"led_effect {params['EFFECT']}": {"enabled": "STOP" not in params}})

    def ace_gcode(self, script: str) -> bool:
        """The filament unit's quick commands. True when it was one."""
        words = script.split()
        if not words or not words[0].startswith("ACE_") or "ace" not in self.status:
            return False
        params = {k.upper(): v for k, v in (w.split("=", 1) for w in words[1:] if "=" in w)}
        cmd = words[0]
        if cmd in ("ACE_ENABLE_FEED_ASSIST", "ACE_DISABLE_FEED_ASSIST"):
            fa = list(self.status["ace"]["gate_feed_assist"])
            fa[int(params["INDEX"])] = cmd == "ACE_ENABLE_FEED_ASSIST"
            self.patch({"ace": {"gate_feed_assist": fa}})
        elif cmd == "ACE_ENDLESS_SPOOL":
            self.patch({"ace": {"endless_spool": params.get("ENABLE") == "1"}})
        elif cmd == "ACE_START_DRYING":
            unit = int(params["GATE"]) // 4
            self.set_dryer(unit, status="drying", target_temp=int(params["TEMP"]),
                           duration=int(params.get("DURATION", 240)), remain_time=int(params.get("DURATION", 240)))
        elif cmd == "ACE_STOP_DRYING":
            self.set_dryer(int(params["GATE"]) // 4, status="stop", target_temp=0, remain_time=0)
        elif cmd in ("ACE_FEED", "ACE_RETRACT"):
            g, mm = int(params["INDEX"]), int(params["LENGTH"])
            if cmd == "ACE_RETRACT":
                self.pulled[g] = self.pulled.get(g, 0) + mm
                if self.pulled[g] >= SIM_TUBE_MM:
                    self.set_slot(g, replace=True, status="empty")
            else:
                self.pulled[g] = max(0, self.pulled.get(g, 0) - mm)
        elif cmd == "ACE_SET_GATE":
            self.patch({"ace": {"selected_gate": int(params["GATE"])}})
        else:
            return False
        return True

    def set_offset(self, z: float) -> None:
        self.patch({"gcode_move": {"homing_origin": [0.0, 0.0, round(z, 4), 0.0]}})

    def new_tracker(self) -> Any:
        t = engine.IntentTracker(self.name)
        t.set_units_on_usb(2 if self.ace and not self.skin and not self.bare else 0)   # two ACE Pros on USB, like workshop
        t.head_sensor = "filament_switch_sensor extruder_sensor"
        t.has_unit = self.ace and not self.bare
        t.unit_installer = True
        t.unit_kept = self.unit_kept
        t.light_objects = engine.light_candidates(list(self.status))
        t.light_choice = DATABASE.get("elyir-bench", {}).get("light")
        if self.units is not None:
            st = self.units["state"]
            t.update_status({"elyir_units": st or {"units": [], "slots": []}})
            t.has_unit = bool(st and st.get("units"))
        t.restore_spool(self.spool_record)
        t.restore_colour_plan(DATABASE.get("elyir-bench", {}).get("colour_plan"))   # like the component, at start
        return t

    def save_spool(self) -> None:
        """Like the component: keep the one spool's record whenever the tracker changes it."""
        if self.tracker.direct_spool_dirty:
            self.tracker.direct_spool_dirty = False
            self.spool_record = deepcopy(self.tracker.direct_spool)

    # ---- status plumbing -------------------------------------------------

    def patch(self, patch: Dict[str, Any]) -> None:
        for obj, fields in patch.items():
            cur = self.status.setdefault(obj, {})
            for k, v in fields.items():
                cur[k] = deepcopy(v)
        self.tracker.update_status(self.seen(deepcopy(patch)))
        self.broadcast("notify_status_update", [self.seen(deepcopy(patch)), time.time()])
        self.publish()

    def set_klippy(self, state: str, message: str = "") -> None:
        self.klippy_state = state
        self.klippy_message = message
        self.status["webhooks"] = {"state": state if state != "disconnected" else "shutdown", "state_message": message}
        self.tracker.set_klippy_state(state, message)
        notif = {"ready": "notify_klippy_ready", "shutdown": "notify_klippy_shutdown",
                 "disconnected": "notify_klippy_disconnected", "startup": None, "error": "notify_klippy_shutdown"}.get(state)
        if notif:
            self.broadcast(notif, [])
        self.publish(force=True)

    def seen(self, status: Dict[str, Any]) -> Dict[str, Any]:
        """Status as Bench and the console get it: with --units afc or happy_hare, the unit's objects in `ace`'s place."""
        if self.bare:
            return {k: v for k, v in status.items() if k != "ace"}
        if not self.skin or "ace" not in status or "ace" not in self.status:
            return status
        return {**{k: v for k, v in status.items() if k != "ace"}, **unit_skins.view(self.skin, self.status["ace"])}

    def unskin(self, script: str) -> Optional[str]:
        """AFC's or Happy Hare's commands as the pretend ACE's; a spool's details go straight into its lists.
        None when nothing is left to run."""
        if not self.skin:
            return script
        left = []
        for line in script.splitlines():
            ace, spool = unit_skins.to_ace(self.skin, line)
            if spool:
                g, fields = spool
                lists = {k: list(self.status["ace"][k]) for k in ("gate_color", "gate_material", "gate_temp")}
                if fields.get("color"):
                    lists["gate_color"][g] = fields["color"].upper()
                if fields.get("material"):
                    lists["gate_material"][g] = fields["material"]
                if fields.get("temp"):
                    lists["gate_temp"][g] = int(fields["temp"])
                self.patch({"ace": lists})
            elif ace:
                left.append(ace)
        return "\n".join(left) or None

    def gcode_response(self, line: str) -> None:
        self.log.append(line)
        self.tracker.on_gcode_response(line)
        self.broadcast("notify_gcode_response", [line])
        self.publish()

    def set_file(self, filename: str) -> None:
        meta = FILES.get(filename, {})
        self.tracker.set_metadata(filename, meta)

    def record_job(self, filename: str, status: str, secs: float) -> None:
        now = time.time()
        self.history.insert(0, {"job_id": f"{int(now) & 0xFFFFFF:06X}", "filename": filename, "status": status,
                                "start_time": now - secs, "end_time": now, "print_duration": secs, "total_duration": secs,
                                "filament_used": 0.0, "metadata": deepcopy(FILES.get(filename, {}))})
        self.broadcast("notify_history_changed", [{"action": "finished", "job": deepcopy(self.history[0])}])

    def totals(self) -> Dict[str, Any]:
        """Moonraker's history totals: the jobs in history plus any hours a scenario added."""
        secs = sum(float(j.get("print_duration") or 0) for j in self.history) + self.extra_print_s
        return {"total_print_time": secs, "total_filament_used": secs * 1.1, "total_jobs": len(self.history)}

    def care_summary(self) -> Dict[str, Any]:
        """Same records and rules as the component: Mainsail's `maintenance` namespace."""
        ast = DATABASE.setdefault("elyir-bench", {})
        if not ast.get("care_seeded"):
            DATABASE.setdefault("maintenance", {}).update(care.default_entries(self.totals(), time.time()))
            ast["care_seeded"] = True
        return care.summary(DATABASE.get("maintenance", {}), self.totals(), time.time(), ast.get("care_snooze", {}))

    def care_action(self, action: str, eid: str) -> Dict[str, Any]:
        ast = DATABASE.setdefault("elyir-bench", {})
        snoozes = ast.setdefault("care_snooze", {})
        if action == "care_done":
            DATABASE["maintenance"].update(care.perform(DATABASE.get("maintenance", {}), eid, self.totals(), time.time()))
            snoozes.pop(eid, None)
        else:
            snoozes[eid] = care.later(eid, self.totals(), time.time())
        self.publish(force=True)
        return {"ok": True, "action": action, "ran": [action], "intent": self.intent()}

    def intent(self) -> Dict[str, Any]:
        self.tracker.phones_notified = bool(DATABASE.get("elyir-bench", {}).get("phones"))
        self.tracker.next_plates = DATABASE.get("elyir-bench", {}).get("next_plates") or []
        self.tracker.care = self.care_summary()
        i = self.tracker.intent()
        i["printer"]["advanced_url"] = f"http://localhost:{self.port}/advanced"
        i["printer"]["screen_switch"] = True
        i["printer"]["simulated"] = True
        i["printer"]["scenario"] = self.scenario_name
        i["printer"]["screen_trial"] = self.setup.trial(time.time())
        i["setup"] = {"open": self.setup.open(self.phones())}
        if self.bring.no_config and self.klippy_state == "error" and i["state"] != "setup":
            # Klipper can't start without printer.cfg: the intent layer says setup, never Problem (docs/bring-it-over.md)
            i.update(state="setup", phase="no_config", headline="Now the printer itself.",
                     detail="It needs a config, once: bring it over from another printer, or write your own.",
                     actions=[], steps=[], safe=True)
        return i

    def publish(self, force: bool = False) -> None:
        i = self.intent()
        self.save_spool()
        if self.tracker.colour_plan_dirty:   # elyir-bench/colour_plan, as the component keeps it
            self.tracker.colour_plan_dirty = False
            DATABASE.setdefault("elyir-bench", {})["colour_plan"] = deepcopy(self.tracker.colour_plan)
        key = json.dumps({k: v for k, v in i.items() if k != "now"}, sort_keys=True, default=str)
        if force or key != self._last_intent_key:
            self._last_intent_key = key
            self.broadcast("notify_intent_update", [i])
        for event in self.notifier.observe(i):
            self.events = (self.events + [event])[-50:]
            print(f"notify {event['kind']}: {event['title']} | {event['body']}", flush=True)
            self.broadcast("notify_elyir_bench_event", [event])

    def broadcast(self, method: str, params: List[Any]) -> None:
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, default=str)
        for ws in list(self.clients):
            if ws.closed:
                self.clients.discard(ws)
                continue
            asyncio.ensure_future(ws.send_str(msg))

    # ---- Finish setting up (docs/setup-card.md) --------------------------

    def phones(self) -> bool:
        """Some phone gets notifications: what the door records at elyir-bench/phones."""
        return bool(DATABASE.get("elyir-bench", {}).get("phones"))

    def setup_facts(self) -> Dict[str, Any]:
        st = self.status
        chamber_max = float((st.get("gcode_macro _PRINT_START_SETTINGS") or {}).get("chamber_max") or 0)
        return {"runout": any(k.startswith("filament_switch_sensor") for k in st), "camera": bool(self.webcams),
                "unit": "ace" in st, "chamber": "temperature_sensor Chamber" in st and chamber_max > 0}

    def setup_info(self) -> Dict[str, Any]:
        return self.setup.info(self.tracker.printer_name, self.setup_facts())

    def _setup_later(self, coro: Any) -> None:
        self._setup_tasks = [t for t in self._setup_tasks if not t.done()] + [asyncio.ensure_future(coro)]

    def start_trial(self, seconds: float = setup_card.TRIAL_S) -> None:
        """The printer's screen shows Elyir Bench and asks there; nobody answering sends it back."""
        self.setup.screen, self.setup.parts = "trial", True
        until = self.setup.trial_until = time.time() + seconds
        self._setup_later(self._trial_runs_out(until))
        self.publish(force=True)

    async def _trial_runs_out(self, until: float) -> None:
        await asyncio.sleep(until - time.time())   # real seconds: the panel counts them down
        if self.setup.trial_until == until:   # not answered, and not a later trial
            self.end_trial(back=True)

    def end_trial(self, back: bool) -> None:
        self.setup.trial_until = None
        self.setup.screen = "kept_klipperscreen" if back else "done"
        if back:
            self.gcode_response("// elyir-bench panel klipperscreen (simulated)")
        self.publish(force=True)

    async def _fetch_screen_parts(self) -> None:
        await asyncio.sleep(setup_card.FETCH_S)
        if self.setup.cant_after_fetch:
            self.setup.screen = "cant"
            self.publish(force=True)
            return
        self.gcode_response("// elyir-bench panel elyir-bench (simulated)")
        self.start_trial()

    async def _start_macro(self, on: bool) -> None:
        await asyncio.sleep(setup_card.INCLUDE_S)
        self.gcode_response(f"// elyir-bench startmacro {'on' if on else 'off'} (simulated)")
        self.gcode_response("// FIRMWARE_RESTART")
        self.set_klippy("startup", "Klipper is starting")
        await asyncio.sleep(2)
        self.setup.include = "on" if on else "off"
        self.set_klippy("ready", "Printer is ready")

    async def setup_action(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        s = self.setup
        why = s.refusal(action, self.status["print_stats"]["state"] in ("printing", "paused"))
        if why:
            raise web.HTTPBadRequest(text=why)
        if action == "setup_dismiss":
            row = str(args.get("row", ""))
            if row not in setup_card.ROW_IDS:
                raise web.HTTPBadRequest(text=f"No row {row}")
            if row not in s.dismissed:
                s.dismissed.append(row)
        elif action == "setup_name":
            name = " ".join(str(args.get("name") or "").split())[:40]
            if not name:
                raise web.HTTPBadRequest(text="A name needs at least one letter.")
            self.name = self.tracker.printer_name = name
            s.name_from = "you"
        elif action == "screen_try":
            if s.parts:
                self.start_trial()
            else:
                s.screen = "fetching"   # KlipperScreen stays on until the parts are in
                self._setup_later(self._fetch_screen_parts())
        elif action in ("screen_keep", "screen_back"):
            self.end_trial(back=action == "screen_back")
        elif action in ("include_add", "include_remove"):
            s.include, s.include_why = ("adding" if action == "include_add" else "removing"), None
            self._setup_later(self._start_macro(action == "include_add"))
        self.publish(force=True)
        return {"ok": True, "action": action, "ran": [action], "intent": self.intent()}

    # ---- Bring it over (docs/bring-it-over.md) ---------------------------

    def fresh_card(self, cloud: bool = False) -> None:
        """No printer.cfg: Klipper stops with the message a fresh card's Klipper gives; nothing printed yet."""
        self.bring.fresh_card(time.time(), cloud)
        if self._history_kept is None:
            self._history_kept, self.history = self.history, []
        self.set_klippy("error", "Unable to open config file /home/pi/printer_data/config/printer.cfg")

    def _bring_later(self, coro: Any) -> None:
        if self._bring_task and not self._bring_task.done():
            self._bring_task.cancel()
        self._bring_task = asyncio.ensure_future(coro)

    async def _bring_scan(self) -> None:
        await asyncio.sleep(bring.SCAN_S)
        self.bring.scanned()
        self.publish(force=True)

    async def _bring_plan(self, sid: str) -> None:
        await asyncio.sleep(bring.PLAN_S)
        self.bring.planned(sid)
        self.publish(force=True)

    async def _bring_address(self, address: str) -> None:
        await asyncio.sleep(bring.SCAN_S)
        src = self.bring.add_address(address, time.time())
        if src is None:
            self.bring.failed(f"Nothing answered at {address.strip()}. Check that it's on, and on the same Wi-Fi.")
        else:
            await asyncio.sleep(bring.PLAN_S)
            self.bring.planned(src["id"])
        self.publish(force=True)

    async def _cloud_owner(self) -> None:
        """The owner taps Allow on their phone a little later (unless the email's code came first)."""
        await asyncio.sleep(bring.CLOUD_ALLOW_S)
        self.bring.cloud_allowed(time.time())
        self.publish(force=True)

    async def bring_apply(self, sid: str, gcodes: bool, start_at: int = 0, hold: float = 0.0) -> None:
        """The copy, a step at a time, then Klipper restarts with it and the printer is Ready.
        start_at/hold: bring_progress starts half way and waits there a while."""
        b = self.bring
        src = b.source(sid) or {}
        steps = b.steps(gcodes)
        for n in range(start_at, len(steps)):
            b.progress = {"step": steps[n], "done": n, "of": len(steps)}
            self.publish(force=True)
            if steps[n] == "Restarting Klipper":
                b.no_config = False
                self.gcode_response("// FIRMWARE_RESTART")
                self.set_klippy("startup", "Klipper is starting")
            await asyncio.sleep(hold if n == start_at and hold else bring.STEP_S)
        if self._history_kept is not None:   # the old card's prints came with it
            self.history, self._history_kept = self._history_kept, None
            self.broadcast("notify_history_changed", [{"action": "added", "job": deepcopy(self.history[0]) if self.history else None}])
        self.set_klippy("ready", "Printer is ready")
        b.done(src.get("kind", "card"))
        self.publish(force=True)

    async def role_action(self, action: str) -> Dict[str, Any]:
        """design/role/, B: role_box steps through what `elyir-bench role controller` says, then goes dark the way a
        printer does when it stops Moonraker (the Bench app would then have the screen). role_back after a failure."""
        b = self.bring
        if action == "role_back":
            b.role = None
        else:
            if (b.role or {}).get("state") == "switching":
                raise web.HTTPBadRequest(text="It's becoming a Bench Box now.")
            b.role = {"state": "switching", "progress": None, "why": None, "url": f"http://{self.name.lower().replace(' ', '-')}.local:8088/"}
            self._bring_later(self._role_run())
        self.publish(force=True)
        return {"ok": True, "action": action, "ran": [action], "intent": self.intent(), "bring": b.info()}

    async def _role_run(self) -> None:
        steps = ["The Bench app", "Its screen", "Klipper and Moonraker off"]
        for i, step in enumerate(steps):   # `done` counts the steps finished; the last one is Moonraker stopping
            self.bring.role["progress"] = {"step": step, "done": i, "of": len(steps)}
            self.publish(force=True)
            await asyncio.sleep(3)
        self.down_until = float("inf")   # Moonraker off: nothing answers any more
        for ws in list(self.clients):
            await ws.close()
        self.clients.clear()

    async def bring_action(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        b = self.bring
        why = b.refusal(action, args, self.status["print_stats"]["state"] in ("printing", "paused"))
        if why:
            raise web.HTTPBadRequest(text=why)
        b.why = None
        if action == "bring_scan":
            b.state = "scanning"
            self._bring_later(self._bring_scan())
        elif action == "bring_plan":
            b.state, b.plan = "planning", None
            self._bring_later(self._bring_plan(str(args["id"])))
        elif action == "bring_address":
            b.state, b.plan = "planning", None
            self._bring_later(self._bring_address(str(args["address"])))
        elif action == "bring_apply":
            b.state, b.result = "bringing", None
            self._bring_later(self.bring_apply(str(args["id"]), bool(args.get("gcodes"))))
        elif action == "bring_cloud_ask":
            b.cloud_ask(str(args["id"]))
            self._bring_later(self._cloud_owner())
        elif action == "bring_cloud_email":
            b.cloud_emailed()
        elif action == "bring_cloud_code":
            b.cloud_allowed(time.time())
        self.publish(force=True)
        return {"ok": True, "action": action, "ran": [action], "intent": self.intent()}

    # ---- pretend physics: called every tick ------------------------------

    def physics(self, dt: float) -> None:
        if self.down_until is not None:
            if time.time() < self.down_until:
                return
            # back from a restart: a new boot knows nothing of the old wait
            self.down_until = None
            self.tracker._power = None
            self.set_klippy("ready")
        kind = self.tracker.power_due()
        if kind:
            self.tracker.power_going()
            self.publish(force=True)
            asyncio.ensure_future(self._power_go(kind))
        self.drive()
        dt *= self.speed
        changed: Dict[str, Any] = {}
        for h in ("heater_bed", "extruder"):
            cur = self.status[h]
            t, target = cur["temperature"], cur["target"]
            rate = (1.2 if h == "heater_bed" else 4.0) * dt
            if target > 0:
                nt = min(target, t + rate) if t < target else max(target, t - rate * 0.3)
            else:
                nt = max(23.0, t - (0.05 if h == "heater_bed" else 0.5) * dt)
            if abs(nt - t) > 0.01:
                cur["temperature"] = round(nt, 1)
                changed[h] = {"temperature": cur["temperature"]}
        ch = self.status["temperature_sensor Chamber"]
        goal = 24.0 + (self.status["heater_bed"]["temperature"] - 23.0) * 0.45
        nch = ch["temperature"] + (goal - ch["temperature"]) * min(1.0, 0.02 * dt)
        if abs(nch - ch["temperature"]) > 0.05:
            ch["temperature"] = round(nch, 1)
            changed["temperature_sensor Chamber"] = {"temperature": ch["temperature"]}
        can = self.status["extruder"]["temperature"] >= 170
        if can != self.status["extruder"]["can_extrude"]:
            self.status["extruder"]["can_extrude"] = can
            changed.setdefault("extruder", {})["can_extrude"] = can

        if "ace" in self.status:
            devices = self.status["ace"]["devices"]
            if any(d["status"]["dryer_status"]["status"] == "drying" for d in devices):
                devices = deepcopy(devices)
                for d in devices:
                    dr, st = d["status"]["dryer_status"], d["status"]
                    if dr["status"] != "drying":
                        st["temp"] = max(25, round(st["temp"] - 0.05 * dt, 1))
                        continue
                    dr["remain_time"] = max(0.0, float(dr["remain_time"]) - dt / 60)
                    st["temp"] = min(dr["target_temp"], round(st["temp"] + 0.2 * dt, 1))
                    if dr["remain_time"] <= 0:
                        dr.update(status="stop", target_temp=0, remain_time=0)
                changed["ace"] = {"devices": devices}
                self.status["ace"]["devices"] = devices

        ps = self.status["print_stats"]
        if ps["state"] == "printing" and self.tracker._print_started and not self.status["pause_resume"]["is_paused"]:
            meta = self.tracker.metadata or {}
            est = float(meta.get("estimated_time") or 3600)
            vsd = self.status["virtual_sdcard"]
            p = min(1.0, vsd["progress"] + dt / est)
            vsd["progress"] = p
            ps["print_duration"] += dt
            ps["total_duration"] += dt
            layers = meta.get("layer_count") or 100
            ps["info"] = {"current_layer": max(1, int(p * layers)), "total_layer": layers}
            changed["virtual_sdcard"] = {"progress": round(p, 4)}
            changed["print_stats"] = {"print_duration": ps["print_duration"], "total_duration": ps["total_duration"], "info": ps["info"]}
            changed["display_status"] = {"progress": round(p, 4)}
            ex = self.status["exclude_object"]
            left = [o["name"] for o in ex["objects"] if o["name"] not in ex["excluded_objects"]]
            if left:   # the head goes round the parts, one after another, layer by layer
                cur = left[int(ps["print_duration"] / 6) % len(left)]
                if cur != ex["current_object"]:
                    ex["current_object"] = cur
                    changed["exclude_object"] = {"current_object": cur}
            if p >= 1.0:
                ps["state"] = "complete"
                self.status["heater_bed"]["target"] = 0.0
                self.status["extruder"]["target"] = 0.0
                changed["print_stats"]["state"] = "complete"
                changed["heater_bed"] = {"target": 0.0, "temperature": self.status["heater_bed"]["temperature"]}
                changed["extruder"] = {"target": 0.0, "temperature": self.status["extruder"]["temperature"]}
                self.gcode_response("Job complete")
                self.record_job(ps["filename"], "completed", ps["print_duration"])
        if changed:
            self.patch(changed)
        else:
            self.publish()

    # ---- actions from the UI, executed the way Moonraker would ------------

    async def _power_go(self, kind: str) -> None:
        """What Moonraker's shutdown or reboot looks like from outside: the socket closes and nothing answers."""
        await asyncio.sleep(2)
        self.down_until = float("inf") if kind == "off" else time.time() + 25 / self.speed
        for ws in list(self.clients):
            await ws.close()
        self.clients.clear()

    async def _restart_after_stop(self) -> None:
        await asyncio.sleep(2 / self.speed)   # the component restarts the Klipper service, then the firmware
        await self.run_action("restart_firmware", {})

    async def run_action(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        plan = engine.plan_action(action, args, self.tracker)
        if not plan:
            raise web.HTTPBadRequest(text=f"Unknown action {action}")
        P = engine.ActionPlan
        for kind, payload in plan:
            if kind == P.PAUSE:
                self.gcode_response("// PAUSE")
                self.patch({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}})
            elif kind == P.RESUME:
                self.gcode_response("// RESUME")
                self.patch({"pause_resume": {"is_paused": False}, "print_stats": {"state": "printing"}})
                self._release("resume")
            elif kind == P.CANCEL:
                self.gcode_response("// CANCEL_PRINT")
                self.patch({"pause_resume": {"is_paused": False},
                            "print_stats": {"state": "cancelled"},
                            "heater_bed": {"target": 0.0}, "extruder": {"target": 0.0}})
                self._release("cancel")
            elif kind == P.UNIT:
                self.gcode_response(f"// unit {json.dumps(payload)}")
                try:
                    await self.units["link"].call(payload)
                except Exception as e:
                    raise web.HTTPBadRequest(text=str(e))
            elif kind == P.GCODE:
                self.gcode_response(f"// {payload}")
                payload = self.unskin(str(payload)) or ""
                if str(payload).startswith("ACE_CHANGE_TOOL"):
                    slot = int(str(payload).split("=")[-1])
                    self.patch({"ace": {"selected_gate": slot}})
                elif str(payload).startswith("EXCLUDE_OBJECT NAME="):
                    name = str(payload).split("=", 1)[1]
                    ex = self.status["exclude_object"]
                    if name not in ex["excluded_objects"]:
                        self.patch({"exclude_object": {"excluded_objects": ex["excluded_objects"] + [name],
                                                       "current_object": None if ex["current_object"] == name else ex["current_object"]}})
                elif payload == "TURN_OFF_HEATERS":
                    self.patch({"heater_bed": {"target": 0.0}, "extruder": {"target": 0.0}})
                elif self.ace_gcode(str(payload)):
                    pass
                elif str(payload).startswith("SAVE_VARIABLE VARIABLE=ace_gate_"):
                    # the filament unit re-reads its saved variables; mirror that into status
                    # parsed like Klipper does: shell-style split (quotes removed), then literal_eval
                    lex = shlex.shlex(str(payload).split(None, 1)[1], posix=True)
                    lex.whitespace_split, lex.commenters = True, "#;"
                    params = {k.upper(): v for k, v in (arg.split("=", 1) for arg in lex)}
                    field = {"ace_gate_color": "gate_color", "ace_gate_type": "gate_material", "ace_gate_temp": "gate_temp"}[params["VARIABLE"]]
                    self.patch({"ace": {field: ast.literal_eval(params["VALUE"])}})
            elif kind == P.EMERGENCY_STOP:
                self.gcode_response("// emergency stop")
                self.tracker.begin_stop()
                self.set_klippy("shutdown", "Shutdown due to webhooks request")
                self._release("cancel")
                asyncio.get_event_loop().create_task(self._restart_after_stop())
            elif kind == P.FIRMWARE_RESTART:
                self.gcode_response("// FIRMWARE_RESTART")
                self.set_klippy("startup", "Klipper is starting")
                await asyncio.sleep(2 / self.speed)
                self.status = self.fresh()
                self.tracker.update_status(self.seen(deepcopy(self.status)))
                self.set_klippy("ready", "Printer is ready")
                self._release("restart")
            elif kind == P.START_LAST:
                filename = self.status["print_stats"]["filename"]
                self.tracker.acknowledge_finished()
                await self.start_scenario("print", filename=filename)
            elif kind == P.SWAP:
                self.tracker.begin_swap(payload["to"], payload["from"], payload["purge"])
                asyncio.get_event_loop().create_task(self._swap(payload))
            elif kind == P.ACK_SWAP:
                self.tracker.ack_swap()
            elif kind == P.ACK_HEAD:
                self.tracker.ack_head()
            elif kind == P.KLIPPY_RESTART:
                # like the real thing: the software restarts and picks up every unit plugged in
                self.gcode_response("// RESTART")
                self.set_klippy("startup", "Klipper is starting")
                await asyncio.sleep(2 / self.speed)
                units = self.tracker.units_on_usb or 2
                status = self.fresh()
                for k in ("gate_color", "gate_material", "gate_temp", "gate_feed_assist") if self.ace else ():
                    status["ace"][k] = (status["ace"][k] * units)[:units * 4] if units > 2 else status["ace"][k][:units * 4]
                if self.ace:
                    devs = status["ace"]["devices"]
                    status["ace"]["devices"] = [dict(deepcopy(devs[i % 2]), name=f"ACE_{i + 1}", gate_offset=i * 4) for i in range(units)]
                    status["ace"]["num_devices"], status["ace"]["total_gates"] = units, units * 4
                self.status = status
                self.tracker.update_status(self.seen(deepcopy(self.status)))
                self.set_klippy("ready", "Printer is ready")
            elif kind == P.START_FILE:
                self.tracker.acknowledge_finished()
                await self.start_scenario("print", filename=payload)
            elif kind == P.ACK_FINISHED:
                self.tracker.acknowledge_finished()
                self.patch({"print_stats": {"state": "standby"}})
            elif kind == P.REMEMBER_SPOOL:
                self.tracker.remember_spool(payload.get("color"), payload.get("material"))
            elif kind == P.CHANGE:
                self.tracker.change_input(payload)
                self.drive()
            elif kind == P.OUTAGE:
                self.tracker.outage_input(payload)
                self.drive()
            elif kind == P.LOST:
                self.tracker.lost_input(payload)
            elif kind == P.POWER:
                self.tracker.power_input(payload)
            elif kind == P.WARM:
                self.tracker.warm_input(payload)
                self.drive()
            elif kind == P.HANDS:
                self.tracker.hands_input(payload)
                self.drive()
            elif kind == P.LIGHT:
                self.tracker.light_input(payload)
                if self.tracker.light_choice_dirty:
                    self.tracker.light_choice_dirty = False
                    DATABASE.setdefault("elyir-bench", {})["light"] = self.tracker.light_choice
                self.drive()
            elif kind == P.FIRST_LAYER:
                self.tracker.first_layer_input(payload)
                self.drive()
            elif kind == P.SLOT:
                self.tracker.slot_input(payload)
                self.drive()
            elif kind == P.UNIT_CHECK:
                self.tracker.unit_check_input(payload)
                self.drive()
            elif kind == P.UNIT_SETUP:
                self.tracker.unit_setup_input(payload)
                self.drive()
            elif kind == P.COLOUR:
                self.tracker.colour_input(payload)
                self.publish()
                self.drive()
        self.publish(force=True)
        return {"ok": True, "action": action, "intent": self.intent()}

    # ---- changing filament by hand: run what the engine asks for, like the component ----

    def drive(self) -> None:
        for kind, script in self.tracker.work():
            if kind == "macro" and unit_skins.is_check(self.skin, script):
                asyncio.get_event_loop().create_task(self._check_macro(script))
                continue
            if kind in ("macro", "gcode"):
                shown, script = script, self.unskin(script)
                if script is None:
                    self.gcode_response(f"// {shown}")
                    continue
            if kind == "macro":
                asyncio.get_event_loop().create_task(self._change_macro(script))
            elif kind in ("unit", "unit_macro"):
                asyncio.get_event_loop().create_task(self._unit_step(script, kind == "unit_macro"))
            elif kind in ("unit_scan", "unit_install", "unit_putback"):
                asyncio.get_event_loop().create_task(self._unit_job(kind, script))
            else:
                self._quick_gcode(script)

    # ---- --units service: the real service on pretend units -------------------------------

    async def start_units(self) -> None:
        here = os.path.join(HERE, "..", "units")
        if here not in sys.path:
            sys.path.insert(0, here)
        import atexit
        import shutil
        import tempfile
        import service as units_service
        from pretend_ace import PretendAce
        from pretend_printer import PretendPrinter
        aces = [PretendAce(time_scale=self.speed) for _ in range(2)]
        for a in aces:
            await a.start()
        aces[0].insert(0, color=(217, 83, 79), kind="PLA", sku="AHPLRD-101")
        aces[0].insert(2, color=(117, 120, 123), kind="PETG", sku="AHPEGY-101")
        aces[1].empty(3)
        # The service's Moonraker for tool changes: the extruder, its sensor and the filament path (units/pretend_printer.py)
        printer = PretendPrinter(aces, time_scale=self.speed, macros=())
        await printer.start()
        work = tempfile.mkdtemp(prefix="sim-units-", dir="/tmp")   # short: macOS caps socket paths at 104
        atexit.register(shutil.rmtree, work, True)
        sock = os.path.join(work, "s")
        svc = units_service.Service(os.path.join(work, "units.json"), scan=lambda: {"1-1.1": aces[0].port, "1-1.2": aces[1].port},
                                    moonraker=printer.url)
        self.units = {"aces": aces, "printer": printer, "service": svc, "state": None,
                      "task": asyncio.ensure_future(svc.run(sock))}
        for _ in range(100):
            if os.path.exists(sock):
                break
            await asyncio.sleep(0.02)
        link = engine.filament_units.UnitsLink(sock, self._on_units)
        self.units["link"] = link
        self.units["link_task"] = asyncio.ensure_future(link.run())

    def _on_units(self, state: Optional[Dict[str, Any]]) -> None:
        sensor = "filament_switch_sensor extruder_sensor"
        seen = self.units["printer"].detected
        if (self.status.get(sensor) or {}).get("filament_detected") != seen:
            self.patch({sensor: {"filament_detected": seen}})
        self.units["state"] = state
        self.tracker.update_status({"elyir_units": state or {"units": [], "slots": []}})
        self.tracker.has_unit = bool(state and state.get("units"))
        self.publish()

    async def _unit_step(self, payload: Dict[str, Any], long: bool) -> None:
        self.gcode_response(f"// unit {json.dumps(payload)}")
        try:
            await self.units["link"].call(dict(payload, wait=True) if long and payload.get("op") == "move" else payload)
            error = None
        except Exception as e:
            error = str(e) or e.__class__.__name__
        if long:
            self.tracker.change_done(error)
            self.drive()
            self.publish()

    def _quick_gcode(self, script: str) -> None:
        if "\n" in script:
            for line in script.splitlines():
                self._quick_gcode(line)
            return
        self.gcode_response(f"// {script}")
        if self.ace_gcode(script):
            return
        if script.startswith("SAVE_VARIABLE VARIABLE=ace_gate_"):
            lex = shlex.shlex(script.split(None, 1)[1], posix=True)
            lex.whitespace_split, lex.commenters = True, "#;"
            params = {k.upper(): v for k, v in (arg.split("=", 1) for arg in lex)}
            field = {"ace_gate_color": "gate_color", "ace_gate_type": "gate_material", "ace_gate_temp": "gate_temp"}[params["VARIABLE"]]
            self.patch({"ace": {field: ast.literal_eval(params["VALUE"])}})
            return
        if script.startswith("SET_GCODE_OFFSET"):
            params = dict(a.split("=", 1) for a in script.split()[1:])
            z = self.status["gcode_move"]["homing_origin"][2]
            self.set_offset(z + float(params["Z_ADJUST"]) if "Z_ADJUST" in params else float(params.get("Z", z)))
        elif script.startswith("SAVE_VARIABLE"):
            # parsed like Klipper does: shell-style split (quotes removed), then literal_eval
            lex = shlex.shlex(script.split(None, 1)[1], posix=True)
            lex.whitespace_split, lex.commenters = True, "#;"
            params = {k.upper(): v for k, v in (arg.split("=", 1) for arg in lex)}
            self.save_vars({params["VARIABLE"].lower(): ast.literal_eval(params["VALUE"])})
        elif script.startswith(("SET_PIN ", "SET_LED ", "SET_LED_EFFECT ", "STOP_LED_EFFECTS")):
            self.light_gcode(script)
        elif script == "G28":   # Move and heat (design/hands-on/): home takes a moment, like the real thing
            th = self.status["toolhead"]
            self.patch({"toolhead": {"homed_axes": ""}, "motion_report": {"live_position": [th["axis_maximum"][0] / 2, th["axis_maximum"][1] / 2, 10.0, 0.0]}})
            asyncio.get_event_loop().call_later(3 / self.speed, lambda: self.patch({"toolhead": {"homed_axes": "xyz"}}))
        elif script == "M84":
            self.patch({"toolhead": {"homed_axes": ""}})
        elif script.startswith(("G1 ", "G0 ")):
            pos = list(self.status["motion_report"]["live_position"])
            for word in script.split()[1:]:
                if word[0] in "XYZ":
                    pos["XYZ".index(word[0])] = float(word[1:])
            self.patch({"motion_report": {"live_position": pos}})
        elif script.startswith("M104 S"):
            self.patch({"extruder": {"target": float(script.split("S")[1])}})
        elif script.startswith("M140 S"):
            self.patch({"heater_bed": {"target": float(script.split("S")[1])}})
        elif script == "TURN_OFF_HEATERS":
            self.patch({"heater_bed": {"target": 0.0}, "extruder": {"target": 0.0}})
        elif script == "PAUSE":   # holding on a battery (design/power-loss/)
            self.patch({"pause_resume": {"is_paused": True}, "print_stats": {"state": "paused"}})
        elif script == "RESUME":   # a planned colour change, done by itself (design/colour-change/, C)
            self.patch({"pause_resume": {"is_paused": False}, "print_stats": {"state": "printing"}})
            self._release("resume")

    # ---- setting a unit up (design/unit-setup/, B, stage 2): the installer's command, as the component runs it ----

    def set_bare(self, on: bool, skin: Optional[str] = None, slots: Optional[int] = None) -> None:
        """No unit in Klipper (on), or the pretend ACEs shown as the unit just set up."""
        self.bare, self.skin = on, (None if on else skin)
        if slots:
            self.status["ace"]["sim_slots"] = slots
        self.tracker.set_units_on_usb(0)
        self.tracker.has_unit = not on
        for k in [k for k in self.tracker.status if k == "ace" or k.split(" ")[0] in ("mmu", "mmu_machine", "AFC", "AFC_stepper", "AFC_hub")
                  or k.startswith("filament_switch_sensor mmu_")]:
            self.tracker.status.pop(k)   # what Klipper had before its restart is gone after it
        self.tracker.update_status(self.seen(deepcopy(self.status)))
        self.broadcast("notify_status_update", [self.seen(deepcopy(self.status)), time.time()])

    def unit_scan(self) -> Dict[str, Any]:
        here = {"serial": [self.bare_board] if self.bare and self.bare_board else [], "can": []}
        found = installer.unit_found({"printer_data": None}, here)   # the printer's own board is in its config: not here
        return {"catalog": installer.unit_catalog(), "found": found,
                "probably": {u: installer.unit_probably(u, found) for u in installer.UNIT_KINDS}, "kept": self.unit_kept}

    async def _unit_job(self, job: str, args: Optional[Dict[str, Any]]) -> None:
        tracker = self.tracker
        say = lambda msg: (tracker.unit_setup_heard(msg), self.publish(force=True))

        async def wait(s: float) -> None:
            await asyncio.sleep(s / self.speed)

        say({"started": job.replace("_", "-"), "pid": os.getpid()})
        if installer is None:
            say({"failed": "Setting up a unit isn't part of this demo."})
            return
        if job == "unit_scan":
            await wait(1.5)
            say(self.unit_scan())
        elif job == "unit_install":
            kind = args["kind"]
            prog = installer.UNIT_PROGRAMS[kind]
            label = f"{prog['name']} {prog['version']}"
            for i, (sid, words, s) in enumerate([("fetch", f"Fetching {label}", 20), ("settings", "Writing its settings", 14),
                                                  ("restart", "Restarting Klipper, once", 0)]):
                say({"progress": {"id": sid, "step": words, "done": i, "of": 4}})
                await wait(s)
            self.set_klippy("startup", "Klipper is restarting")
            await wait(12)
            if self.fail_unit_install:
                self.fail_unit_install = False
                self.set_klippy("ready")
                say({"failed": "Klipper didn't start with it: mcu 'mmu': Unable to connect. Check the unit's USB cable. "
                               "Your old settings are back."})
                return
            self.unit_kept = {"unit": args["unit"], "board": args["board"], "slots": args["slots"], "program": label,
                              "when": time.time()}
            self.set_bare(False, kind, args["slots"])
            self.set_klippy("ready")
            say({"progress": {"id": "answers", "step": "Checking the unit answers", "done": 3, "of": 4}})
            await wait(2)
            say({"result": {"kind": kind, "unit": args["unit"], "board": args["board"], "slots": args["slots"],
                            "program": label, "kept": "~/printer_data/config-before-unit-2026-10-22"}})
        else:
            say({"progress": {"id": "settings", "step": "Putting your old settings back", "done": 0, "of": 2}})
            await wait(4)
            self.unit_kept = None
            self.set_bare(True)
            say({"progress": {"id": "restart", "step": "Restarting Klipper, once", "done": 1, "of": 2}})
            self.set_klippy("startup", "Klipper is restarting")
            await wait(10)
            self.set_klippy("ready")
            say({"result": {"put_back": True, "klipper": "ready", "message": "Klipper started with it."}})
        if self.tracker is tracker:
            self.drive()
        self.publish(force=True)

    async def _check_macro(self, script: str) -> None:
        """A step of the unit check (printer/unit_check.py), answered the way Happy Hare or AFC would."""
        tracker = self.tracker
        for line in script.splitlines():
            self.gcode_response(f"// {line}")
            seconds, said, measured = unit_skins.check_answer(self.skin, line, unit_skins._slot_states(self.status["ace"]),
                                                              self.fail_check_slot, self.status["ace"], self.saved_vars,
                                                              self.fail_gear_gate)
            await asyncio.sleep(seconds / self.speed)
            if any(x.startswith("!!") for x in said):
                self.fail_check_slot = None   # once: Try again passes
            if "failed_gate" in measured:
                self.fail_gear_gate = None
            if "save" in measured:
                self.save_vars(measured["save"])
            for x in said:
                self.gcode_response(x)
            if "tube" in measured:
                self.patch({"ace": {"sim_bowden": measured["tube"]}})
            if "hub" in measured:
                g, mm = measured["hub"]
                self.patch({"ace": {"sim_dist_hub": dict(self.status["ace"].get("sim_dist_hub") or {}, **{str(g): mm})}})
        if self.tracker is tracker:
            self.tracker.change_done(None)
        self.drive()
        self.publish(force=True)

    async def _heat_to(self, t: float) -> None:
        self.patch({"extruder": {"target": t}})
        while self.status["extruder"]["temperature"] < t - 3:
            await asyncio.sleep(0.2)

    async def _change_macro(self, script: str) -> None:
        """UNLOAD_FILAMENT / LOAD_FILAMENT / a purge, roughly as long as the real macros take."""
        step = lambda s: asyncio.sleep(s / self.speed)
        first = script.splitlines()[0]
        tracker = self.tracker   # a scenario started meanwhile has a tracker of its own: don't report into it
        self.gcode_response(f"// {first}")
        if first.startswith("ACE_"):
            # swapping a spool in a slot (design/slots/): out of the head, then pulled back
            try:
                if first == "ACE_CHANGE_TOOL TOOL=-1":
                    self.gcode_response(f"// ACE: Unloading tool {self.status['ace']['selected_gate']}...")
                    await step(25)
                    self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": False},
                                "ace": {"selected_gate": -1}})
                elif first.startswith("ACE_CHANGE_TOOL TOOL="):
                    # a tool change mid-print, at a colour change: the console lines KlipperACE writes
                    to, frm = int(first.split("=")[1]), self.status["ace"]["selected_gate"]
                    self.gcode_response(f"// ACE: Tool change {frm} => {to}")
                    if frm is not None and frm >= 0:
                        self.gcode_response(f"// ACE: Unloading tool {frm}...")
                        await step(20)
                        self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": False}})
                    if self.slot(to).get("status") == "empty":
                        raise RuntimeError(f"ACE: Slot {to} is not ready")
                    if self.fail_next_swap:
                        self.fail_next_swap = False
                        raise RuntimeError("ACE: Feed timeout - filament did not reach extruder sensor")
                    self.gcode_response(f"// ACE: Loading tool {to}...")
                    self.gcode_response("// ACE: Feeding from gate to extruder")
                    await step(20)
                    self.gcode_response("// ACE: Feeding to nozzle (single sensor mode)")
                    await step(12)
                    self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": True}, "ace": {"selected_gate": to}})
                    self.gcode_response("// ACE: Executing poop macro: _POOP")
                    await step(20)
                    self.gcode_response("// ACE: Load complete")
                else:
                    await step(6)
                    self.ace_gcode(first)
                if self.tracker is tracker:
                    self.tracker.change_done(None)
            except Exception as e:
                self.gcode_response(f"!! {e}")
                if self.tracker is tracker:
                    self.tracker.change_done(str(e))
            self.drive()
            self.publish(force=True)
            return
        temp = float(first.split("TEMP=")[1]) if "TEMP=" in first else float(first.split("S")[1])
        try:
            await self._heat_to(temp)
            if self.fail_next_swap:
                self.fail_next_swap = False
                raise RuntimeError("Extrude below minimum temp")
            if first.startswith("UNLOAD_FILAMENT"):
                self.gcode_response("// Unloading filament...")
                await step(20)
                self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": False}})
                self.gcode_response("// Filament unloaded! Please inspect the tip of the filament before reloading.")
            elif first.startswith("LOAD_FILAMENT"):
                self.gcode_response("// Loading filament...")
                self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": True}})
                await step(30)
                self.gcode_response("// Filament loaded!")
            else:
                await step(12)
            self.tracker.change_done(None)
        except Exception as e:
            self.gcode_response(f"!! {e}")
            self.tracker.change_done(str(e))
        self.drive()
        self.publish(force=True)

    async def _swap(self, payload: Dict[str, Any]) -> None:
        """A tool change the way the filament unit reports it on the console."""
        to, frm = payload["to"], payload["from"]
        step = lambda s: asyncio.sleep(s / self.speed)
        if self.units is not None:
            await self._swap_on_service(payload)
            return
        self.gcode_response(f"// {engine.swap_gcode(payload, self.tracker.unit_commands())}")
        self.gcode_response(f"// ACE: Tool change {frm if frm is not None else -1} => {to}")
        try:
            if frm is not None:
                self.gcode_response(f"// ACE: Unloading tool {frm}...")
                await step(25)
                self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": False}})
            if to >= 0:
                self.gcode_response(f"// ACE: Loading tool {to}...")
                self.gcode_response("// ACE: Feeding from gate to extruder")
                await step(20)
                if self.fail_next_swap:
                    self.fail_next_swap = False
                    raise RuntimeError("ACE: Feed timeout - filament did not reach extruder sensor")
                self.patch({"extruder": {"target": 240.0}})
                for t in (90, 150, 210, 238):
                    self.patch({"extruder": {"temperature": float(t)}})
                    await step(6)
                self.gcode_response("// ACE: Feeding to nozzle (single sensor mode)")
                await step(15)
                self.patch({"filament_switch_sensor extruder_sensor": {"filament_detected": True}})
                if payload["purge"]:
                    self.gcode_response("// ACE: Executing poop macro: _POOP")
                    await step(25)
                else:
                    self.gcode_response("// ACE: Same colour, skipping purge")
                self.gcode_response("// ACE: Load complete")
            self.patch({"ace": {"selected_gate": to}, "extruder": {"target": 0.0}})
            self.tracker.end_swap(None)
            self.drive()
        except Exception as e:
            self.gcode_response(f"!! {e}")
            self.patch({"extruder": {"target": 0.0}})
            self.tracker.end_swap(str(e))
        self.publish(force=True)

    async def _swap_on_service(self, payload: Dict[str, Any]) -> None:
        step = engine.swap_gcode(payload, self.tracker.unit_commands())
        self.gcode_response(f"// unit {json.dumps(step)}")
        try:
            await self.units["link"].call(step, timeout=900)
            error = None
        except Exception as e:
            error = str(e) or e.__class__.__name__
            self.gcode_response(f"!! {error}")
        self._on_units(self.units["state"])
        self.tracker.end_swap(error)
        self.drive()
        self.publish(force=True)

    # ---- scenarios -------------------------------------------------------

    def _release(self, what: str) -> None:
        if self._waiting_for == what:
            self._waiting_for = None

    async def wait_for(self, what: str, timeout: float = 3600) -> None:
        self._waiting_for = what
        t0 = time.time()
        while self._waiting_for == what and time.time() - t0 < timeout:
            await asyncio.sleep(0.2)
        self._waiting_for = None

    def reset(self) -> None:
        """Back to a fresh, ready printer. Every scenario starts here."""
        self.save_spool()   # the spool's record outlives the printer's state, like the database
        plan = DATABASE.get("elyir-bench", {}).get("colour_plan")
        if plan and plan.get("started"):
            DATABASE["elyir-bench"].pop("colour_plan")   # it was for the print that was going on; a plan just made stays
        self.status = self.fresh()
        self.klippy_state = "ready"
        self.klippy_message = "Printer is ready"
        self.tracker = self.new_tracker()
        self.fail_next_swap = False
        self.fail_check_slot = None
        self.skin, self.bare, self.fail_unit_install, self.unit_kept = self.skin_start, False, False, None
        self.tracker = self.new_tracker()
        for task in self._setup_tasks:
            task.cancel()
        self._setup_tasks = []
        self.setup.reset(active=False)
        self.profile.reset()
        if self._bring_task and not self._bring_task.done():
            self._bring_task.cancel()
        self.bring.reset()
        if self._history_kept is not None:
            self.history, self._history_kept = self._history_kept, None
        self.tracker.set_klippy_state("ready")
        self.tracker.update_status(self.seen(deepcopy(self.status)))
        self.broadcast("notify_status_update", [self.seen(deepcopy(self.status)), time.time()])
        self.broadcast("notify_klippy_ready", [])
        self.publish(force=True)

    async def start_scenario(self, name: str, **kw: Any) -> None:
        if name not in SCENARIOS:
            raise web.HTTPNotFound(text=f"No scenario {name}")
        if self._scenario_task and not self._scenario_task.done():
            self._scenario_task.cancel()
            try:
                await self._scenario_task
            except (asyncio.CancelledError, Exception):
                pass
        self._waiting_for = None
        self.tap = self.tap_default
        self.reset()
        self.scenario_name = name
        self._scenario_task = asyncio.ensure_future(self._run_scenario(name, kw))

    async def _run_scenario(self, name: str, kw: Dict[str, Any]) -> None:
        try:
            await SCENARIOS[name](self, **kw)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # keep the sim alive
            self.gcode_response(f"!! simulator scenario error: {e}")

    def scenario_state(self) -> Dict[str, Any]:
        """For the demo's playing line: playing while the script still moves the printer, waiting while it
        waits for a person (waiting_for says for what), done once it has nothing more to do."""
        task = self._scenario_task
        phase = "waiting" if self._waiting_for else "done" if task is None or task.done() else "playing"
        return {"running": self.scenario_name, "phase": phase, "waiting_for": self._waiting_for}

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds / self.speed)


# --------------------------------------------------------------------------
# JSON-RPC over websocket, plus the few REST routes the app uses
# --------------------------------------------------------------------------

def rpc_result(req_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, default=str)


def rpc_error(req_id: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# Finish setting up's actions (docs/setup-card.md); setup_name is the card's "Change"
# Bring it over's are bring.ACTIONS (docs/bring-it-over.md)
SETUP_ACTIONS = ("setup_dismiss", "setup_name", "screen_try", "screen_keep", "screen_back", "include_add", "include_remove")

# Moonraker's key/value database, in memory: the app keeps small settings here (e.g. panel theme)
DATABASE: Dict[str, Dict[str, Any]] = {}


async def dispatch(sim: SimPrinter, method: str, params: Any) -> Any:
    params = params or {}
    if method == "server.info":
        return {"klippy_connected": sim.klippy_state != "disconnected", "klippy_state": sim.klippy_state,
                "components": ["printer_intent", "history", "file_manager"], "moonraker_version": "sim-0.1",
                "api_version": [1, 5, 0], "api_version_string": "1.5.0"}
    if method == "server.connection.identify":
        return {"connection_id": id(sim) & 0xFFFF}
    if method == "printer.info":
        return {"state": sim.klippy_state, "state_message": sim.klippy_message, "hostname": sim.name.lower(),
                "software_version": "sim", "cpu_info": "simulated"}
    if method == "printer.objects.list":
        return {"objects": list(sim.seen(sim.status).keys())}
    if method in ("printer.objects.query", "printer.objects.subscribe"):
        objs = params.get("objects", {})
        out: Dict[str, Any] = {}
        status = sim.seen(sim.status)
        for name, fields in objs.items():
            if name in status:
                out[name] = deepcopy(status[name]) if not fields else {f: deepcopy(status[name].get(f)) for f in fields if f in status[name]}
        return {"eventtime": time.time(), "status": out}
    if method == "printer.intent":
        return sim.intent()
    if method == "printer.intent.setup":
        return sim.setup_info()
    if method == "printer.intent.bring":
        return sim.bring.info()
    if method == "printer.intent.profile":
        return sim.profile.info()
    if method == "printer.intent.action":
        if params.get("action") in slicer_profile.ACTIONS:
            why = sim.profile.act(params["action"], params.get("args") or {})
            if why:
                raise web.HTTPBadRequest(text=why)
            return {"ok": True, "action": params["action"], "ran": [params["action"]], "intent": sim.intent()}
        if params.get("action") in ("role_box", "role_back"):
            return await sim.role_action(params["action"])
        if params.get("action") in bring.ACTIONS:
            return await sim.bring_action(params["action"], params.get("args") or {})
        if params.get("action") in SETUP_ACTIONS:
            return await sim.setup_action(params["action"], params.get("args") or {})
        if params.get("action") in ("care_done", "care_later"):
            return sim.care_action(params["action"], str((params.get("args") or {}).get("id", "")))
        if params.get("action") in ("use_klipperscreen", "use_elyir_bench"):
            # a printer runs `elyir-bench panel <mode>`; here there's no screen to switch
            sim.gcode_response(f"// elyir-bench panel {params['action'][4:]} (simulated)")
            return {"ok": True, "action": params["action"], "ran": [params["action"]], "intent": sim.intent()}
        return await sim.run_action(params.get("action", ""), params.get("args") or {})
    if method == "server.history.totals":
        return {"job_totals": sim.totals(), "auxiliary_totals": []}
    if method == "printer.intent.check_print":
        fn = params.get("filename", "")
        sim.tracker.note_check(fn, FILES.get(fn))   # what the component does when a file has colour changes
        return engine.check_print(fn, FILES.get(fn), sim.tracker.spools())
    if method == "printer.print.pause":
        return await sim.run_action("pause", {})
    if method == "printer.print.resume":
        return await sim.run_action("resume", {})
    if method == "printer.print.cancel":
        return await sim.run_action("cancel", {})
    if method == "printer.print.start":
        await sim.start_scenario("print", filename=params.get("filename"))
        return "ok"
    if method == "printer.gcode.script":
        sim.gcode_response(f"// {params.get('script')}")
        return "ok"
    if method == "printer.firmware_restart":
        await sim.run_action("try_again", {})
        return "ok"
    if method == "server.files.metadata":
        fn = params.get("filename", "")
        meta = FILES.get(fn)
        if not meta:
            raise web.HTTPNotFound(text="no metadata")
        return {"filename": fn, **meta}
    if method == "server.files.list":
        if params.get("root") == "config":
            return config_files()
        if params.get("root", "gcodes") != "gcodes":
            return []
        return [{"path": fn, "modified": meta.get("modified", time.time()), "size": int(meta.get("size") or 1000000),
                 "permissions": "rw"} for fn, meta in FILES.items()]
    if method == "server.files.get_directory":
        return gcode_directory(str(params.get("path", "gcodes")), str(params.get("extended", "")).lower() in ("true", "1"))
    if method == "server.files.delete_file":
        path = str(params.get("path", ""))
        fn = path[len("gcodes/"):] if path.startswith("gcodes/") else path
        if fn not in FILES:
            raise web.HTTPNotFound(text=f"File {path} does not exist")
        del FILES[fn]
        item = {"path": fn, "root": "gcodes"}
        sim.broadcast("notify_filelist_changed", [{"action": "delete_file", "item": item}])
        return {"item": item, "action": "delete_file"}
    if method == "server.history.list":
        jobs = sorted(sim.history, key=lambda j: j["start_time"], reverse=params.get("order", "desc") != "asc")
        start, limit = int(params.get("start", 0) or 0), int(params.get("limit", 50) or 50)
        return {"count": len(jobs), "jobs": [{**j, "exists": j["filename"] in FILES} for j in jobs[start:start + limit]]}
    if method == "printer.intent.events":
        boot = sim.notifier.boot
        if params.get("boot", boot) != boot:
            return {"boot": boot, "events": []}
        after = int(params.get("after", 0) or 0)
        return {"boot": boot, "events": [e for e in sim.events if e["id"] > after]}
    if method == "server.webcams.list":
        return {"webcams": sim.webcams}
    if method == "server.database.get_item":
        ns, key = params.get("namespace", ""), params.get("key", "")
        if key not in DATABASE.get(ns, {}):
            raise web.HTTPNotFound(text=f"Key '{key}' in namespace '{ns}' not found")
        return {"namespace": ns, "key": key, "value": DATABASE[ns][key]}
    if method == "server.database.post_item":
        ns, key = params.get("namespace", ""), params.get("key", "")
        DATABASE.setdefault(ns, {})[key] = params.get("value")
        return {"namespace": ns, "key": key, "value": params.get("value")}
    raise web.HTTPNotFound(text=f"Method not found: {method}")


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    sim: SimPrinter = request.app["sim"]
    if sim.down_until is not None:
        raise web.HTTPServiceUnavailable(text="turned off")
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    sim.clients.add(ws)
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                req = json.loads(msg.data)
            except ValueError:
                continue
            req_id = req.get("id")
            try:
                result = await dispatch(sim, req.get("method", ""), req.get("params"))
                if req_id is not None:
                    await ws.send_str(rpc_result(req_id, result))
            except web.HTTPException as e:
                if req_id is not None:
                    await ws.send_str(rpc_error(req_id, -32601 if e.status == 404 else -32000, e.text or str(e)))
            except Exception as e:
                if req_id is not None:
                    await ws.send_str(rpc_error(req_id, -32000, str(e)))
    finally:
        sim.clients.discard(ws)
    return ws


async def rest(request: web.Request) -> web.Response:
    """Map a few REST paths onto the same dispatcher."""
    sim: SimPrinter = request.app["sim"]
    if sim.down_until is not None:
        raise web.HTTPServiceUnavailable(text="turned off")
    path = request.path.strip("/").replace("/", ".")
    if path == "server.database.item":   # Moonraker's REST form of get_item/post_item
        path = "server.database.post_item" if request.method == "POST" else "server.database.get_item"
    params: Dict[str, Any] = dict(request.query)
    if request.can_read_body:
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except Exception:
            pass
    try:
        return web.json_response({"result": await dispatch(sim, path, params)}, dumps=lambda o: json.dumps(o, default=str))
    except web.HTTPException as e:
        return web.json_response({"error": {"code": e.status, "message": e.text}}, status=e.status)


async def sim_control(request: web.Request) -> web.Response:
    sim: SimPrinter = request.app["sim"]
    name = request.match_info.get("name", "")
    if request.method == "POST":
        await sim.start_scenario(name, **{k: request.query[k] for k in ("filename", "skipped") if request.query.get(k)})
        return web.json_response({"ok": True, "scenario": name})
    return web.json_response({"scenarios": {k: (v.__doc__ or "").strip() for k, v in SCENARIOS.items()},
                             "speed": sim.speed, **sim.scenario_state()})


async def sim_insert(request: web.Request) -> web.Response:
    """A person pushes a spool into a slot: POST /sim/insert/6, or /sim/insert/6?type=PLA&color=FF0000 for a tagged one."""
    sim: SimPrinter = request.app["sim"]
    if not sim.ace:
        raise web.HTTPBadRequest(text="No filament unit (--no-ace)")
    g = int(request.match_info["slot"])
    if sim.units is not None:
        c = request.query.get("color", "000000").lstrip("#")
        kind = request.query.get("type", "").upper()
        sim.units["aces"][g // 4].insert(g % 4, color=tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)), kind=kind,
                                          sku="SIM" if kind else "")
        return web.json_response({"ok": True, "slot": g})
    tag = None
    if request.query.get("type"):
        c = request.query.get("color", "FFFFFF").lstrip("#")
        tag = {"type": request.query["type"].upper(), "color": [int(c[i:i + 2], 16) for i in (0, 2, 4)]}
    sim.insert_spool(g, tag)
    return web.json_response({"ok": True, "slot": g})


CONTROL_PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Elyir Bench simulator</title>
<style>body{font:15px/1.4 -apple-system,system-ui,sans-serif;background:#0b0e13;color:#eee;margin:0;padding:20px;max-width:560px}
h1{font-size:18px;margin:0 0 4px}p{color:#9aa;margin:0 0 16px}button{display:block;width:100%;text-align:left;margin:6px 0;padding:12px 14px;
border-radius:10px;border:1px solid #2a3040;background:#161a23;color:#eee;font-size:15px}button b{display:block}button span{color:#9aa;font-size:13px}
button.on{border-color:#4da3ff}pre{background:#161a23;padding:12px;border-radius:10px;font-size:12px;overflow:auto;max-height:40vh}</style>
<h1>Elyir Bench simulator</h1><p>Tap a scenario. The app reacts as if the printer did it.</p>
<div id=b></div><h1 style="margin-top:20px">Push a spool in</h1><p>As if a person put a spool on and pushed its end into the slot.</p>
<div id=ins style="display:flex;gap:6px;flex-wrap:wrap"></div><h1 style="margin-top:20px">Intent right now</h1><pre id=i>…</pre>
<script>
async function load(){const r=await (await fetch('/sim/scenarios')).json();const b=document.getElementById('b');b.innerHTML='';
for(const [k,v] of Object.entries(r.scenarios)){const x=document.createElement('button');x.className=k===r.running?'on':'';
x.innerHTML='<b>'+k+'</b><span>'+v+'</span>';x.onclick=async()=>{await fetch('/sim/scenario/'+k,{method:'POST'});load()};b.appendChild(x)}}
async function intent(){const r=await (await fetch('/printer/intent')).json();document.getElementById('i').textContent=JSON.stringify(r.result,null,1)}
const ins=document.getElementById('ins');for(let g=0;g<8;g++){const x=document.createElement('button');x.style.width='auto';
x.textContent='Slot '+(g+1);x.onclick=()=>fetch('/sim/insert/'+g,{method:'POST'});ins.appendChild(x)}
load();intent();setInterval(intent,1000);
</script>"""


# ---- the pretend camera: frames drawn by camera/make-frames.mjs, looped -------------------------
CAMERA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera")
CAMERA_FPS = 6


def camera_frames() -> List[bytes]:
    names = sorted(f for f in os.listdir(CAMERA_DIR) if f.endswith(".jpg"))
    return [open(os.path.join(CAMERA_DIR, n), "rb").read() for n in names]


async def webcam(request: web.Request) -> web.StreamResponse:
    """/webcam/?action=stream (MJPEG) or ?action=snapshot (one JPEG), like mjpg-streamer."""
    frames: List[bytes] = request.app["camera_frames"]
    if not frames:
        raise web.HTTPNotFound()
    i = int(time.time() * CAMERA_FPS) % len(frames)
    if request.query.get("action") != "stream":
        return web.Response(body=frames[i], content_type="image/jpeg", headers={"Cache-Control": "no-store"})
    resp = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
    })
    await resp.prepare(request)
    try:
        while True:
            frame = frames[i % len(frames)]
            await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                             + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
            i += 1
            await asyncio.sleep(1 / CAMERA_FPS)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


async def control_page(request: web.Request) -> web.Response:
    return web.Response(text=CONTROL_PAGE, content_type="text/html")


# Pictures pulled out of uploaded files, by the name Moonraker would give them (.thumbs/<stem>-WxH.png).
THUMBS: Dict[str, bytes] = {}
def exclude_objects(text: str) -> List[Dict[str, Any]]:
    out = []
    for line in text.splitlines():
        if line.startswith("EXCLUDE_OBJECT_DEFINE"):
            m = re.search(r"NAME=(\S+)", line)
            c = re.search(r"CENTER=([-\d.]+),([-\d.]+)", line)
            poly = re.search(r"POLYGON=(\[\[.*\]\])", line)
            if m:
                out.append({"name": m.group(1), "center": [float(c.group(1)), float(c.group(2))] if c else None,
                            "polygon": json.loads(poly.group(1)) if poly else []})
    return out


def _seconds(text: str) -> int:
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * mult[u] for n, u in re.findall(r"(\d+)\s*([dhms])", text))


def gcode_metadata(name: str, text: str) -> Dict[str, Any]:
    """What Moonraker's metadata parser takes from an Orca file, enough for the Print tab and
    check_print: time, filaments, weights, layers, temperatures and the embedded picture."""
    meta: Dict[str, Any] = {"slicer": "OrcaSlicer", "size": len(text)}
    stem = os.path.splitext(os.path.basename(name))[0]
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("; estimated printing time (normal mode)") and "estimated_time" not in meta:
            meta["estimated_time"] = _seconds(line.split("=", 1)[1])
        elif line.startswith("; filament_colour ="):
            meta["filament_colors"] = [c.strip() for c in line.split("=", 1)[1].split(";") if c.strip()]
        elif line.startswith("; filament_type ="):
            meta["filament_type"] = line.split("=", 1)[1].strip()
        elif line.startswith("; total filament used [g]"):
            meta["filament_weight_total"] = float(line.split("=", 1)[1])
        elif line.startswith("; filament used [g] ="):
            meta["filament_weights"] = [float(v) for v in line.split("=", 1)[1].split(",") if v.strip()]
        elif line.startswith("; total layer number:"):
            meta["layer_count"] = int(line.split(":", 1)[1])
        elif line.startswith("; layer_height ="):
            meta["layer_height"] = float(line.split("=", 1)[1])
        elif line.startswith("PRINT_START") and "first_layer_bed_temp" not in meta:
            for key, field in (("BED", "first_layer_bed_temp"), ("EXTRUDER", "first_layer_extr_temp")):
                m = re.search(rf"\b{key}=(\d+)", line)
                if m:
                    meta[field] = int(m.group(1))
        elif line.startswith("; thumbnail begin "):
            w, h = line.split()[3].split("x")
            end = lines.index("; thumbnail end", i)
            png = base64.b64decode("".join(l[2:] for l in lines[i + 1:end]))
            rel = f".thumbs/{stem}-{w}x{h}.png"
            THUMBS[os.path.basename(rel)] = png
            meta.setdefault("thumbnails", []).append({"width": int(w), "height": int(h), "size": len(png), "relative_path": rel})
    changes = engine.colour_changes_in(lines)   # the component reads these from the file itself
    if changes:
        meta["colour_changes"] = changes
    return meta


# The files with a colour change (scenarios.COLOUR_FILES), read the way an uploaded file is, plus the picture.
for _k, (_name, _text) in enumerate(COLOUR_FILES.items()):
    FILES[_name] = dict(gcode_metadata(_name, _text), slicer="PrusaSlicer", modified=time.time() - 300 - 60 * _k,
                        thumbnails=[{"width": 400, "height": 300, "size": 9000, "relative_path": ".thumbs/phone_stand-400x300.svg"}])


def gcode_directory(path: str, extended: bool) -> Dict[str, Any]:
    """Moonraker's server.files.get_directory over FILES: one folder's files (with their metadata
    when extended) and the folders directly inside it."""
    rel = path.strip("/")
    rel = rel[len("gcodes"):].strip("/") if rel.startswith("gcodes") else rel
    files, dirs = [], {}
    for fn, meta in FILES.items():
        folder, _, base = fn.rpartition("/")
        if folder == rel:
            files.append({**(deepcopy(meta) if extended else {}), "filename": base, "modified": meta.get("modified", time.time()),
                          "size": int(meta.get("size") or 1000000), "permissions": "rw"})
        elif not rel or folder.startswith(rel + "/"):
            sub = (folder[len(rel) + 1:] if rel else folder).split("/")[0]
            dirs[sub] = max(dirs.get(sub, 0), meta.get("modified", 0))
    if rel and not files and not dirs:
        raise web.HTTPNotFound(text=f"Directory {path} does not exist")
    return {"dirs": [{"dirname": d, "modified": m, "size": 4096, "permissions": "rw"} for d, m in sorted(dirs.items())],
            "files": files, "disk_usage": {"total": 29e9, "used": 9e9, "free": 20e9},
            "root_info": {"name": "gcodes", "permissions": "rw"}}


async def upload(request: web.Request) -> web.Response:
    """Stand-in for Moonraker's /server/files/upload: the file joins FILES, and starts if asked."""
    sim: SimPrinter = request.app["sim"]
    form = await request.post()
    f = form.get("file")
    if f is None or not getattr(f, "filename", None):
        return web.json_response({"error": {"code": 400, "message": "No file"}}, status=400)
    name = os.path.basename(f.filename)
    if str(form.get("root", "gcodes")) == "config":
        # a backup sent from the phone for Bring it over: config/elyir-bench-bring/<name>; the next scan lists it
        folder = str(form.get("path", "")).strip("/")
        size = len(f.file.read())
        if folder == "elyir-bench-bring":
            sim.bring.add_file(name, size, time.time())
        path = f"{folder}/{name}" if folder else name
        sim.broadcast("notify_filelist_changed", [{"action": "create_file", "item": {"path": path, "root": "config"}}])
        return web.json_response({"item": {"path": path, "root": "config"}, "action": "create_file"}, status=201)
    text = f.file.read().decode(errors="replace")
    FILES[name] = gcode_metadata(name, text)
    OBJECTS[name] = exclude_objects(text)
    FILES[name]["modified"] = time.time()
    sim.broadcast("notify_filelist_changed", [{"action": "create_file", "item": {"path": name, "root": "gcodes"}}])
    start = str(form.get("print", "")).lower() == "true"
    if start:
        await sim.start_scenario("print", filename=name)
    return web.json_response({"item": {"path": name, "root": "gcodes"}, "print_started": start,
                              "action": "create_file"}, status=201)


async def gcode_file(request: web.Request) -> web.Response:
    """Stand-in for /server/files/gcodes/...: serves the pretend thumbnails and uploaded ones."""
    name = request.match_info["path"].rsplit("/", 1)[-1]
    if name in THUMBS:
        return web.Response(body=THUMBS[name], content_type="image/png")
    path = os.path.join(HERE, "thumbs", name)
    if not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})


async def advanced_page(request: web.Request) -> web.Response:
    return web.Response(content_type="text/html", text="""<!doctype html><title>Mainsail (stand-in)</title>
<body style="margin:0;background:#1e1e1e;color:#ddd;font:14px system-ui;display:grid;grid-template-columns:56px 1fr;height:100vh">
<div style="background:#181818;border-right:1px solid #333"></div><div style="padding:24px"><h2 style="margin:0 0 12px">Mainsail would be here</h2>
<p>On the printer this frame loads the real Mainsail from the same host. In the simulator it's this stand-in page so the Advanced door can be tried.</p>
<pre style="background:#2a2a2a;padding:12px;border-radius:8px">extruder 214.8 / 215\nheater_bed 60.1 / 60\n// bed_mesh: loaded</pre></div>""")


@web.middleware
async def cors(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


async def ticker(app: web.Application) -> None:
    sim: SimPrinter = app["sim"]
    last = time.time()
    while True:
        await asyncio.sleep(1.0)
        now = time.time()
        sim.physics(now - last)
        last = now


async def on_startup(app: web.Application) -> None:
    app["ticker"] = asyncio.ensure_future(ticker(app))
    if app["units"] == "service":
        await app["sim"].start_units()
    await app["sim"].start_scenario(app["scenario"])


CONFIG_DIR: Optional[Path] = None   # --config: what Moonraker would list under the config root


def config_files() -> list:
    if CONFIG_DIR is None or not CONFIG_DIR.is_dir():
        return []
    return [{"path": str(f.relative_to(CONFIG_DIR)), "modified": f.stat().st_mtime, "size": f.stat().st_size, "permissions": "rw"}
            for f in sorted(CONFIG_DIR.rglob("*")) if f.is_file()]


async def config_file(request: web.Request) -> web.StreamResponse:
    if CONFIG_DIR is None:
        raise web.HTTPNotFound()
    f = (CONFIG_DIR / request.match_info["path"]).resolve()
    if not f.is_file() or CONFIG_DIR.resolve() not in f.parents:
        raise web.HTTPNotFound()
    return web.FileResponse(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7126)
    ap.add_argument("--speed", type=float, default=4.0, help="time multiplier (default 4x)")
    ap.add_argument("--scenario", default="day", choices=list(SCENARIOS.keys()))
    ap.add_argument("--name", default="Workshop")
    ap.add_argument("--no-camera", action="store_true", help="a printer without a camera")
    ap.add_argument("--no-ace", action="store_true", help="a printer without a filament unit: one spool")
    ap.add_argument("--light", choices=["pin", "strip", "both", "none"], default="pin",
                    help="its chamber light: an on/off pin, a status LED strip, both (Bench asks which), or none")
    ap.add_argument("--no-files", action="store_true", help="nothing on the printer and nothing printed yet")
    ap.add_argument("--config", help="a folder served as the printer's config files, like Moonraker's config root "
                    "(a slicer elsewhere copies elyir-bench-slicer/ from it: docs/slicer.md)")
    ap.add_argument("--tap", action="store_true", help="PRINT_START's tap stage runs: the printer finds its own first layer")
    ap.add_argument("--units", choices=["klipperace", "service", *unit_skins.SKINS], default="klipperace",
                    help="service: two pretend ACE Pros behind the real filament-unit service (units/), instead of a "
                    "pretend KlipperACE; scenarios that play with KlipperACE's own status (runout, colour) need klipperace. "
                    "afc, happy_hare: the pretend units shown to Bench as AFC's lanes or Happy Hare's gates")
    a = ap.parse_args()
    if a.no_files:
        FILES.clear()

    global CONFIG_DIR
    CONFIG_DIR = Path(a.config).expanduser() if a.config else None
    app = web.Application(middlewares=[cors], client_max_size=256 * 1024 * 1024)   # G-code uploads
    app["sim"] = SimPrinter(a.name, a.speed, ace=not a.no_ace, light=a.light,
                            skin=a.units if a.units in unit_skins.SKINS and not a.no_ace else None)
    app["sim"].port = a.port
    if a.tap:
        app["sim"].tap = app["sim"].tap_default = True
        app["sim"].reset()
    if a.no_files:
        app["sim"].history = []
    app["scenario"] = a.scenario
    app["units"] = "klipperace" if a.no_ace else a.units
    app["camera_frames"] = [] if a.no_camera else camera_frames()
    # Absolute addresses, which Moonraker allows too: the app's dev server doesn't proxy /webcam/.
    app["sim"].webcams = [] if a.no_camera else [{
        "name": "Main", "enabled": True, "service": "mjpegstreamer-adaptive",
        "stream_url": f"http://localhost:{a.port}/webcam/?action=stream",
        "snapshot_url": f"http://localhost:{a.port}/webcam/?action=snapshot",
        "flip_horizontal": False, "flip_vertical": False, "rotation": 0,
        "aspect_ratio": "4:3", "target_fps": CAMERA_FPS, "location": "printer",
    }]
    app.router.add_get("/websocket", ws_handler)
    app.router.add_get("/sim", control_page)
    app.router.add_get("/sim/scenarios", sim_control)
    app.router.add_post("/sim/scenario/{name}", sim_control)
    app.router.add_post("/sim/insert/{slot}", sim_insert)
    app.router.add_get("/server/files/gcodes/{path:.*}", gcode_file)
    app.router.add_get("/server/files/config/{path:.*}", config_file)
    app.router.add_post("/server/files/upload", upload)
    app.router.add_get("/webcam/", webcam)
    app.router.add_get("/advanced", advanced_page)
    app.router.add_get("/advanced/{tail:.*}", advanced_page)
    app.router.add_route("*", "/{tail:.*}", rest)
    app.on_startup.append(on_startup)
    print(f"Elyir Bench simulator: ws://localhost:{a.port}/websocket   control: http://localhost:{a.port}/sim   speed {a.speed}x")
    web.run_app(app, port=a.port, print=None)


if __name__ == "__main__":
    main()
