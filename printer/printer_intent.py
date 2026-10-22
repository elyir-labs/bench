# Elyir Bench intent layer: Moonraker component
#
# Publishes one human-readable object describing what the printer is doing
# and what a person can do about it. See elyir_bench_intent.py for the logic.
#
# Install: copy this file and elyir_bench_intent.py into
#   ~/moonraker/moonraker/components/
# and add to moonraker.conf:
#   [printer_intent]
#   printer_name: Workshop
#   advanced_url: http://workshop.local/
#
# API:
#   GET  /printer/intent           (ws: printer.intent)         -> intent object
#   POST /printer/intent/action    (ws: printer.intent.action)  {action, args}
#   GET  /printer/intent/check_print?filename=  (ws: printer.intent.check_print)  can it print as loaded?
#   notification: notify_intent_update [intent]
#
# A printer without a filament unit has one spool. What someone said is on it (or the
# guess from the last print) is kept in Moonraker's database at elyir-bench/spool; with
# Spoolman set up, its active spool is shown instead.
#
# Colour changes on a printer with a unit (design/colour-change/): each M600 in a file and the layer it's on
# (and its colour, when a COLOR_CHANGE marker says) are read from the file itself, cached per file, and
# given to check_print and the running job as metadata["colour_changes"]. The plan the Print sheet makes
# is kept at elyir-bench/colour_plan, for the print of that file started right after.
#
# The first layer (Further / Closer while it goes down, kept for next time) is saved in Klipper's
# [save_variables] as first_layer_*, where the shared PRINT_START reads it; nothing here stores it.
#
# Finish setting up (design/getting-started/, C; the contract is docs/setup-card.md):
#   GET  /printer/intent/setup     (ws: printer.intent.setup)   -> the card's rows and the What works sheet
#   actions setup_dismiss {row}, screen_try, screen_keep, screen_back, include_add, include_remove
#   the intent carries setup.open (the phone shows the card) and printer.screen_trial ({seconds_left} or null,
#   the panel's Keep / Back bar). Rows closed with × and how the screen row ended are kept at elyir-bench/setup.
#
# Slicing like their own prints (design/getting-started/; the contract is docs/slicer-profile.md):
#   GET  /printer/intent/profile   (ws: printer.intent.profile) -> state, told, using, found, bed_klipper, newer
#   actions profile_use {id}, profile_told, profile_keep
#   The profile every Orca file carries at its end is read (orca_profile.py) at start and when the gcodes folder
#   changes; what the files agree on is written to config/elyir-bench-slicer/printer.json and presets/0-learned/,
#   marked "learned". A printer.json without that mark is the person's own and never touched. told and keep are
#   kept at elyir-bench/profile.
#
# Bring it over (design/printer-setup/, A; the contract is docs/bring-it-over.md):
#   GET  /printer/intent/bring     (ws: printer.intent.bring)   -> state, sources, plan, progress, result, why, found
#   actions bring_scan, bring_plan {id}, bring_address {address}, bring_apply {id, gcodes}
#   notification: notify_bring_update [the same]
#   Each runs `elyir-bench --json bring …` in the background, its JSON lines going to state/bring-run.jsonl, read every
#   tick: the installer restarts Moonraker while it brings a setup over, and the run (and this) carry on after it.
#   A fresh card (state setup) is scanned once by itself, so the first screen knows what's there.
#   Printer or Bench Box (design/role/, B): the view also has boards (printer boards plugged in, from the scan) and
#   role (null, or {state: switching|failed, progress, why, url}); actions role_box (`elyir-bench --json role controller`,
#   followed like a bring run; it stops Moonraker last) and role_back (after a failure).
#   GET  /printer/intent/bring/export -> {database}: this printer's Moonraker database for another printer bringing
#   it over (Moonraker writes its own backups where its file API can't serve them), without its logins.
#
# Turning off (design/power/, A): actions power_off, power_restart (heaters off, then wait for the nozzle to drop
# below the hot-end fan's 50°), power_keep, power_now, power_retry; the intent carries power {allowed, why, kind, going,
# progress, nozzle}. Once it's cool this asks Moonraker's machine component to shut the Pi down or reboot it.
#
# Phone notification events (the door turns these into Web Push):
#   GET  /printer/intent/events    (ws: printer.intent.events)  {boot?, after?}
#        -> {boot, events}; events newer than `after` in this boot. When `boot`
#           isn't this boot, events is empty: resync from here, don't replay.
#   notification: notify_elyir_bench_event [event]
#   event: {boot, id, ts, printer, job, kind, urgency, title, body, tag, url}
# Whoever sends them records how many phones listen, in Moonraker's database
# (elyir-bench/phones); the screens only promise a phone message when it's > 0.
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from collections import deque
from typing import Any, Dict, Optional, TYPE_CHECKING

from ..common import RequestType, TransportType

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from ..common import WebRequest
    from .klippy_apis import KlippyAPI
    from .file_manager.file_manager import FileManager


def _load_engine(name: str = "elyir_bench_intent"):
    """Import one of our modules from this directory without touching sys.path."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{name}.py not found next to {__file__}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


engine = _load_engine()
try:
    care = _load_engine("elyir_bench_care")
except Exception:   # an install that predates it: everything but maintenance still works
    logging.exception("intent: elyir_bench_care.py missing; Care won't count maintenance")
    care = None
try:
    orca = _load_engine("orca_profile")
except Exception:   # an install that predates it: no slicing like their prints
    logging.exception("intent: orca_profile.py missing; nothing is learned from the printer's files")
    orca = None

PUBLISH_INTERVAL = 1.0   # seconds between pushes while numbers tick
EVENTS_KEPT = 50         # recent notification events, for consumers catching up
PHONES_CHECK_TICKS = 30  # re-read the subscribed-phone count every 30 s
UNITS_CHECK_TICKS = 5    # count filament units on USB every 5 s
CHANGE_TIMEOUT = 900     # s: a tool change by the filament-unit service, heating and purging included
SETUP_FILES_TICKS = 5    # re-read what the installer says about the board and the screen every 5 s
RESYNC_TICKS = 30        # re-read everything subscribed every 30 s
RESYNC_AFTER_READY = 5.0  # ...and once the other components have subscribed after a restart
ACE_USB_IDS = {("28e9", "018a")}   # Anycubic ACE Pro
COLOUR_CACHE_KEPT = 50   # files whose colour changes are remembered
UPS_CHECK_TICKS = 5      # ask NUT about the UPS every 5 s (design/power-loss/)

# Care > Printer screen: which app the printer's own screen shows. The installer does the switch
# (services, elyir-bench.conf), and KlipperScreen's menu gets an Elyir Bench entry to come back.
SCREEN_ACTIONS = {"use_klipperscreen": "klipperscreen", "use_elyir_bench": "elyir-bench"}
ELYIR_BENCH_CLI = os.path.expanduser("~/.local/bin/elyir-bench")
KLIPPERSCREEN_UNIT = "/etc/systemd/system/KlipperScreen.service"
# The installer's state, where each apply leaves what works on this board (`elyir-bench --json check`)
def set_conf_name(text: str, section: str, name: str) -> str:
    """A config file with printer_name set in one section, everything else as it was. Adds the line when the
    section has none; leaves a file without the section alone (the next apply writes it)."""
    import re
    m = re.search(rf"^\[{re.escape(section)}\][^\[]*", text, re.M)
    if not m:
        return text
    body = m.group(0)
    if re.search(r"^printer_name:.*$", body, re.M):
        new = re.sub(r"^printer_name:.*$", f"printer_name: {name}", body, count=1, flags=re.M)
    else:
        new = body.replace(f"[{section}]\n", f"[{section}]\nprinter_name: {name}\n", 1)
    return text[:m.start()] + new + text[m.end():]


RELAY_API = "https://api.elyir.app"        # the installer's DEFAULT_RELAY_API
SECURE_LINK_TTL = 300                      # seconds a relay answer is trusted before asking again


def secure_link_state(relay: Dict[str, Any], ask) -> str:
    """off: no public name (remote off, or not claimed yet); waiting: claimed, not yet carried (approved on the
    relay); on: carried. `ask(api, name, secret)` answers the relay's GET /houses/<name>, or None."""
    if not relay.get("name") or not relay.get("secret"):
        return "off"
    got = ask(RELAY_API, relay["name"], relay["secret"])
    return "on" if got and got.get("carried") else "waiting"


def ask_relay(api: str, name: str, secret: str) -> Optional[Dict[str, Any]]:
    import urllib.request
    req = urllib.request.Request(f"{api}/houses/{name}", headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return None


INSTALLER_STATE = os.path.join(os.environ.get("ELYIR_BENCH_HOME", os.path.expanduser("~/elyir-bench")), "state.json")

# Finish setting up (docs/setup-card.md)
SETUP_ROWS = ("notify", "screen", "works")
SCREEN_TRIAL_SECONDS = 120     # Elyir Bench on the printer's screen, until someone keeps it; nobody answers: back
START_MACRO_COMMAND = "gcode_macro ELYIR_BENCH_PRINT_START"   # in Klipper's objects once elyir-bench.cfg is included
INCLUDE_TEXT = "[include elyir-bench.cfg]"
# The two lines around the start G-code, the same as slicer/elyir_bench_slice.py puts in
SLICER_LINES = {"before": "ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] "
                          "EXTRUDER=[nozzle_temperature_initial_layer]",
                "after": "ELYIR_BENCH_PRINT_START_DONE"}
NO_SCREEN_APP = "The screen stays on KlipperScreen"   # how expectations() says this system can't run the panel
SETUP_ACTIONS = ("setup_dismiss", "setup_name", "screen_try", "screen_keep", "screen_back", "include_add", "include_remove")

# Slicing like their own prints (docs/slicer-profile.md)
PROFILE_ACTIONS = ("profile_use", "profile_told", "profile_keep")
PROFILE_FILES = 50          # the newest G-code files read for their profile
PROFILE_SCAN_DELAY = 3.0    # seconds after the gcodes folder changes: an upload is several events
SLICER_HOME = "elyir-bench-slicer"   # in the config folder: printer.json and presets/ (docs/slicer.md)
LEARNED = "0-learned"       # sorts before 0-resolved and the person's own folders, so it wins on a name both have
BRING_ACTIONS = ("bring_scan", "bring_plan", "bring_address", "bring_apply", "bring_cloud_ask", "bring_cloud_check",
                 "bring_cloud_email", "bring_cloud_code")
BRING_STATES = {"scan": "scanning", "plan": "planning", "address": "planning", "apply": "bringing", "cloud-ask": "asking",
                "cloud-check": "asking", "cloud-email": "asking", "cloud-code": "asking"}
CLOUD_POLL_TICKS = 3                # while a new card waits for the owner: ask Bench Cloud every 3 s
CLOUD_TICKS = 300                   # look whether tonight's backup is due every 5 minutes
CLOUD_NIGHT = range(2, 6)           # a backup starts in the small hours ...
CLOUD_AGAIN = 20 * 3600             # ... once a day ...
CLOUD_OVERDUE = 48 * 3600           # ... or at any hour once it's two days late (the printer was off at night)
CLOUD_SAY_S = 300                   # what it's doing, for the owner's page (design/cloud-home/, B): every 5 minutes ...
CLOUD_SAY_SOON_S = 30               # ... or within 30 s of saying something new (started, needs you, done)
BRING_RUN = "bring-run.jsonl"   # in the installer's state folder: what the running `elyir-bench bring` says
BRING_CACHE = "bring.json"      # ...and what its last scan found (installer BRING_CACHE)
BRING_RESUME = 1800             # seconds a run that ended while Moonraker restarted is still worth saying
BRING_QUIET = 30                # seconds a run may take to say who it is before it counts as gone
# Printer or Bench Box (design/role/, B): `elyir-bench --json role controller`, followed like a bring run. It turns
# Moonraker off last, which ends this component too: the screens then say where the box is (docs/bring-it-over.md).
ROLE_ACTIONS = ("role_box", "role_back")
ROLE_RUN = "role-run.jsonl"
BOX_PORT = 8088                 # the Bench app's port on a box (installer: the controller's serve port)
# Setting a filament unit up (design/unit-setup/, B): `elyir-bench --json unit scan|install|putback`, followed like a
# bring run; each line it says goes to the tracker's setup routine (unit_setup.py)
UNIT_RUN = "unit-run.jsonl"
UNIT_JOBS = {"unit_scan": ["scan"], "unit_putback": ["putback"]}


def switch_failure(report: str) -> Optional[str]:
    """Why `elyir-bench --json panel <mode>` failed, from its report: the health check's reason if
    there is one, otherwise the failing step's."""
    try:
        lines = json.loads(report.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    fails = [ln for ln in lines if isinstance(ln, dict) and ln.get("status") == "fail"]
    health = [ln for ln in fails if ln.get("step") == "health"]
    for ln in health or fails:
        return str(ln.get("detail", "")).removeprefix("health check failed: ") or None
    return None


def units_on_usb(root: str = "/sys/bus/usb/devices") -> Optional[Dict[str, int]]:
    """Filament units the USB bus reports, as {port: kernel device number}, whether or not
    the printer picked them up. The number changes every time a unit re-enumerates."""
    try:
        names = os.listdir(root)
    except OSError:
        return None
    out: Dict[str, int] = {}
    for name in names:
        d = os.path.join(root, name)
        try:
            with open(os.path.join(d, "idVendor")) as v, open(os.path.join(d, "idProduct")) as p:
                if (v.read().strip().lower(), p.read().strip().lower()) not in ACE_USB_IDS:
                    continue
            with open(os.path.join(d, "devnum")) as n:
                out[name] = int(n.read().strip())
        except (OSError, ValueError):
            continue
    return out


def parse_upsc(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """`upsc <ups>` as {on_battery, low, charge, runtime_s}; None when it didn't answer."""
    if not text:
        return None
    v = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
    status = v.get("ups.status", "").split()
    if not status:
        return None
    num = lambda k: float(v[k]) if re.fullmatch(r"[\d.]+", v.get(k, "")) else None
    return {"on_battery": "OB" in status, "low": "LB" in status, "charge": num("battery.charge"), "runtime_s": num("battery.runtime")}


def who_sent(web_request, source: str) -> str:
    """'panel (elyir-bench, 127.0.0.1, Chrome on CrOS)': the screen the app says it is, then what Moonraker
    knows about the connection. Never raises: a log line must not stop an action."""
    try:
        conn = web_request.get_client_connection()
        ip = web_request.get_ip_address()
        name = (getattr(conn, "client_data", None) or {}).get("name") if conn is not None else None
        req = getattr(conn, "request", None)
        agent = req.headers.get("User-Agent", "") if req is not None else ""
        return f"{source or 'an unnamed client'} ({name or 'http'}, {ip or '?'}, {browser_of(agent)})"
    except Exception:
        return source or "an unnamed client"


def browser_of(agent: str) -> str:
    """A user agent in a few words: 'Chrome on Mac', 'Safari on iPhone', 'Chrome on CrOS' (the panel's kiosk)."""
    if not agent:
        return "no browser"
    os_name = next((o for k, o in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("CrOS", "CrOS"),
                                   ("Mac OS X", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")) if k in agent), "?")
    browser = next((b for k, b in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if k in agent), agent.split("/")[0][:20])
    return f"{browser} on {os_name}"


class PrinterIntent:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        self.eventloop = self.server.get_event_loop()
        self.klippy_apis: KlippyAPI = self.server.lookup_component("klippy_apis")
        default_name = socket.gethostname().split(".")[0].upper() or "Printer"
        self.printer_name: str = config.get("printer_name", default_name)
        self.advanced_url: str = config.get("advanced_url", "/")

        self.tracker = engine.IntentTracker(self.printer_name)
        self._unit_in_klipper: Optional[bool] = None   # KlipperACE or Happy Hare among Klipper's objects
        self._units_state: Optional[Dict[str, Any]] = None
        self.units_link = engine.filament_units.UnitsLink(config.get("units_socket", os.path.expanduser("~/printer_data/comms/elyir-units.sock")),
                                    self._on_units)
        self._last_published: Optional[str] = None
        self._last_filename: Optional[str] = None
        self._timer_running = False
        self.notifier = engine.Notifier(uuid.uuid4().hex[:12])
        self.events: deque = deque(maxlen=EVENTS_KEPT)
        self._ticks = 0
        self._subscribed = False   # status subscription made since Klipper last became ready
        self._subs: Dict[str, Any] = {}   # what that subscription asked for
        self._care_entries: Dict[str, Any] = {}
        self._colour_cache: Dict[str, Any] = {}   # filename -> (mtime, size, colour changes)
        self.cli, self.klipperscreen_unit = ELYIR_BENCH_CLI, KLIPPERSCREEN_UNIT
        self._screen_switching = False
        self._screen_switch_failed: Optional[str] = None   # what the last switch ran into, for Care
        # Finish setting up: rows closed with ×, how the screen row ended (done | kept_klipperscreen), both kept
        # at elyir-bench/setup; the trial and the include while they run
        self.installer_state = INSTALLER_STATE
        self._unit_run: Optional[Dict[str, Any]] = None   # the installer command a unit setup is running
        self._objects: list = []                  # Klipper's objects, read at each ready
        self._setup_dismissed: list = []
        self._screen_outcome: Optional[str] = None
        self._screen_fetching = False
        self._screen_cant: Optional[str] = None   # why the screen's parts couldn't be had
        self._trial_until: Optional[float] = None
        self._include_busy: Optional[str] = None  # adding | removing
        self._include_why: Optional[str] = None   # the last add or remove failed: why
        self._board_seen: Optional[Dict[str, Any]] = None   # the installer's files, read every few seconds
        self._panel_seen: Optional[str] = None
        # Slicing like their own prints: the files read (path -> (mtime, size, what read() gave)), the profiles
        # found in them, what Klipper's limits are, and what's kept at elyir-bench/profile ({told, keep})
        self.orca_keys: Optional[str] = None     # slicer/orca_keys.json; found beside the release when None
        self._profile_cache: Dict[str, Any] = {}
        self._profile_files: list = []
        self._profiles: list = []
        self._profile_saved: Dict[str, Any] = {"told": False, "keep": []}
        self._profile_scan_due = False
        self._profile_scanning = False
        self._axis_max: Optional[list] = None
        # Bring it over: what the app is told, and the run that's going (its kind, its pid once it says, when)
        self._bring: Dict[str, Any] = {"state": "idle", "sources": [], "plan": None, "progress": None, "result": None,
                                       "why": None, "found": [], "boards": None, "role": None, "cloud": None}
        self._bring_run: Optional[Dict[str, Any]] = None
        self._role_run: Optional[Dict[str, Any]] = None
        self._bring_scanned = False   # a fresh card is looked at once by itself
        self._cloud_started = 0.0     # the last nightly backup this component started
        self._cloud_me: Optional[Dict[str, Any]] = None   # cloud.json while this printer is in a house
        self._cloud_said: Optional[tuple] = None          # what it last told Bench Cloud, and when
        self._cloud_said_at = 0.0
        self._cloud_saying = False
        self._bring_sent: Optional[str] = None
        # A UPS, through NUT (design/power-loss/): its name in NUT ("" finds the first); None once upsc turns out
        # not to be installed, so it isn't asked again
        self.ups_name: Optional[str] = config.get("ups", "")
        # The chamber light (design/chamber-light/, A): `light: output_pin case_light` names it; without, the one
        # found, or the one picked when Bench asked (elyir-bench/light)
        self.light_setting: str = config.get("light", "").strip()
        self._ups_reading = False

        self.server.register_notification("printer_intent:update", "intent_update")
        self.server.register_notification("printer_intent:event", "elyir_bench_event")
        self.server.register_notification("printer_intent:bring", "bring_update")
        self.server.register_endpoint(
            "/printer/intent", RequestType.GET, self._handle_get_intent,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/action", RequestType.POST, self._handle_action,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/events", RequestType.GET, self._handle_events,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/check_print", RequestType.GET, self._handle_check_print,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/setup", RequestType.GET, self._handle_setup,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/profile", RequestType.GET, self._handle_profile,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/bring", RequestType.GET, self._handle_bring,
            transports=TransportType.HTTP | TransportType.WEBSOCKET,
        )
        self.server.register_endpoint(
            "/printer/intent/bring/export", RequestType.GET, self._handle_bring_export,
            transports=TransportType.HTTP,
        )

        self.server.register_event_handler("server:klippy_started", self._on_klippy_started)
        self.server.register_event_handler("server:klippy_ready", self._on_klippy_ready)
        self.server.register_event_handler("server:klippy_shutdown", self._on_klippy_shutdown)
        self.server.register_event_handler("server:klippy_disconnect", self._on_klippy_disconnect)
        self.server.register_event_handler("server:gcode_response", self._on_gcode_response)
        self.server.register_event_handler("spoolman:active_spool_set", self._on_spoolman_spool)
        self.server.register_event_handler("file_manager:filelist_changed", self._on_files_changed)
        logging.info("Elyir Bench intent layer loaded for %s", self.printer_name)

    async def component_init(self) -> None:
        # Tick from the start, not only once Klipper is ready: a long startup or an
        # error before ready still has to reach the screens.
        await self._restore_spool()
        await self._restore_colour_plan()
        await self._restore_checkpoint()
        await self._restore_setup()
        await self._restore_profile()
        self._restore_bring()
        self._read_setup_files()
        self.eventloop.delay_callback(PROFILE_SCAN_DELAY, self._scan_profiles)   # not ahead of Klipper's own start
        self._start_timer()

    # ---- Klipper lifecycle ------------------------------------------------

    def _sync_klippy_state(self) -> None:
        """Mirror Moonraker's live view of Klipper on every intent build. Its events miss
        a long startup (a board that won't answer), and while the klippy_started handlers
        run it still reports STARTUP, which would otherwise mask an error that follows."""
        try:
            kc = self.server.lookup_component("klippy_connection")
            live = kc.state.name.lower()
        except Exception:
            return
        if live == "ready" and not self._subscribed:
            live = "startup"   # ready, but our status subscription isn't in place yet
        if live != self.tracker.klippy_state:
            self.tracker.set_klippy_state(live, "" if live in ("ready", "disconnected") else kc.state_message)

    async def _on_klippy_started(self, state: Any) -> None:
        name = getattr(state, "name", str(state)).lower()
        self.tracker.set_klippy_state("startup" if name in ("startup", "ready") else name)
        await self._refresh_klippy_message()
        self._publish(force=True)

    async def _on_klippy_ready(self) -> None:
        self.tracker.set_klippy_state("ready")
        subs = dict(self.tracker.SUBSCRIBE)
        try:
            objects = await self.klippy_apis.get_object_list()
            self._objects = list(objects or [])
            self._unit_in_klipper = any(o in (objects or []) for o in ("ace", "mmu", "AFC"))
            if "AFC" in (objects or []):
                subs["AFC"] = ["lanes", "current_load", "current_state", "error_state"]
                for o in engine.filament_units.afc_lane_objects(list(objects or [])):
                    subs[o] = None
            for o in engine.filament_units.check_objects(list(objects or [])):
                subs[o] = ["filament_detected"] if o.startswith("filament_switch_sensor ") else None
            self.tracker.has_unit = self._unit_present()
            chamber = self.tracker.chamber_sensor_name(list(objects or []))
            if chamber:
                subs[chamber] = ["temperature"]
            if "exclude_object" in (objects or []):
                subs["exclude_object"] = None     # parts that can be skipped (design/skip-objects/)
            head = self.tracker.head_sensor_name(list(objects or []))
            self.tracker.head_sensor = head
            if head:
                subs[head] = ["filament_detected"]
            lights = engine.light_candidates(list(objects or []))
            self.tracker.light_objects = lights
            for o in lights:
                if o.startswith("output_pin "):
                    subs[o] = ["value"]
            if any(not o.startswith("output_pin ") for o in lights):
                for o in objects or []:
                    if o.startswith("led_effect "):
                        subs[o] = ["enabled"]   # the status effects a strip gets back when its light goes off
            await self._restore_light()
        except Exception:
            pass
        try:
            status = await self.klippy_apis.subscribe_objects(subs, self._on_status_update)
            self.tracker.update_status(status or {})
        except Exception:
            logging.exception("intent: subscription failed")
        self._subs = subs
        self._subscribed = True
        self.eventloop.delay_callback(RESYNC_AFTER_READY, self._resync)
        await self._read_dryer_max()
        await self._read_idle_timeout()
        await self._read_axis_max()
        await self._maybe_load_metadata()
        await self._refresh_spoolman()
        self._start_timer()
        self._publish(force=True)

    def _unit_present(self) -> Optional[bool]:
        if self._units_state and self._units_state.get("units"):
            return True
        return self._unit_in_klipper

    def _on_units(self, state: Optional[Dict[str, Any]]) -> None:
        """The filament-unit service's state, or None when it's gone: read through filament_units.py."""
        self._units_state = state
        self.tracker.update_status({"elyir_units": state if state else {"units": [], "slots": []}})
        self.tracker.has_unit = self._unit_present()
        if state and isinstance(state.get("dryer_max"), (int, float)):
            self.tracker.dryer_max = float(state["dryer_max"])
        self._publish()

    async def _run_unit(self, payload: Dict[str, Any]) -> None:
        try:
            await self.units_link.call(payload)
        except Exception as e:
            logging.info("intent: filament unit %s failed: %s", payload.get("op"), e)

    async def _run_unit_step(self, payload: Dict[str, Any]) -> None:
        """A step of the change routine that takes a while, run on the service until the unit is still."""
        try:
            await self.units_link.call(dict(payload, wait=True) if payload.get("op") == "move" else payload,
                                       timeout=CHANGE_TIMEOUT)
            self.tracker.change_done(None)
        except Exception as e:
            logging.info("intent: changing filament stopped: %s", e)
            self.tracker.change_done(str(e) or e.__class__.__name__)
        self._drive()
        self._publish(force=True)

    async def _read_dryer_max(self) -> None:
        """How warm the unit's dryer may go: [ace] max_dryer_temperature, read once per start."""
        if not self.tracker.has_unit:
            return
        try:
            res = await self.klippy_apis.query_objects({"configfile": ["settings"]})
            ace = ((res.get("configfile") or {}).get("settings") or {}).get("ace") or {}
            if isinstance(ace.get("max_dryer_temperature"), (int, float)):
                self.tracker.dryer_max = float(ace["max_dryer_temperature"])
        except Exception:
            logging.exception("intent: reading the dryer limit failed")

    async def _read_idle_timeout(self) -> None:
        """[idle_timeout] timeout: what a held print's idle timeout goes back to (design/power-loss/)."""
        try:
            res = await self.klippy_apis.query_objects({"configfile": ["settings"]})
            idle = ((res.get("configfile") or {}).get("settings") or {}).get("idle_timeout") or {}
            if isinstance(idle.get("timeout"), (int, float)):
                self.tracker.idle_timeout_s = float(idle["timeout"])
        except Exception:
            logging.exception("intent: reading the idle timeout failed")

    async def _read_ups(self) -> None:
        try:
            if not self.ups_name:
                found = await self._upsc("-l")
                self.ups_name = found.split()[0] if found and found.split() else ""
            self.tracker.set_ups(parse_upsc(await self._upsc(self.ups_name)) if self.ups_name else None)
        except FileNotFoundError:
            self.ups_name = None
            self.tracker.set_ups(None)
        except Exception:
            self.tracker.set_ups(None)
        finally:
            self._ups_reading = False

    async def _upsc(self, arg: str) -> Optional[str]:
        proc = await asyncio.create_subprocess_exec("upsc", arg, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
        return out.decode(errors="replace") if proc.returncode == 0 else None

    async def _restore_light(self) -> None:
        if self.light_setting:
            self.tracker.light_choice = self.light_setting
            return
        try:
            db = self.server.lookup_component("database")
            self.tracker.light_choice = await db.get_item("elyir-bench", "light", None)
        except Exception:
            logging.exception("intent: reading the light failed")

    async def _save_light(self) -> None:
        self.tracker.light_choice_dirty = False
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "light", self.tracker.light_choice)
        except Exception:
            logging.exception("intent: saving the light failed")

    async def _restore_checkpoint(self) -> None:
        try:
            db = self.server.lookup_component("database")
            self.tracker.restore_checkpoint(await db.get_item("elyir-bench", "checkpoint", None))
        except Exception:
            logging.exception("intent: reading the checkpoint failed")

    async def _save_checkpoint(self) -> None:
        self.tracker.checkpoint_dirty = False
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "checkpoint", self.tracker.checkpoint_record())
        except Exception:
            self.tracker.checkpoint_dirty = True
            logging.exception("intent: saving the checkpoint failed")

    async def _resync(self) -> None:
        """Read the subscribed objects afresh. Moonraker shares one subscription among its
        components, and each one that subscribes later gets the current values for itself
        alone: a change in between never reaches us (the head sensor flipping just after a
        restart, say). Without this the printer's memory can stay wrong for good."""
        if not self._subscribed or not self._subs:
            return
        try:
            status = await self.klippy_apis.query_objects(self._subs)
        except Exception:
            return
        if isinstance(status, dict):
            self.tracker.update_status(status)
            self._publish()

    async def _on_klippy_shutdown(self) -> None:
        self.tracker.set_klippy_state("shutdown")
        await self._refresh_klippy_message()
        self._publish(force=True)

    async def _on_klippy_disconnect(self) -> None:
        self._subscribed = False
        self.tracker.set_klippy_state("disconnected")
        self._publish(force=True)

    async def _refresh_klippy_message(self) -> None:
        try:
            info = await self.klippy_apis.get_klippy_info()
            self.tracker.set_klippy_state(info.get("state", self.tracker.klippy_state), info.get("state_message", ""))
        except Exception:
            pass

    async def _on_status_update(self, status: Dict[str, Any], eventtime: float) -> None:
        self.tracker.update_status(status)
        await self._maybe_load_metadata()
        self._drive()
        self._publish()

    async def _on_gcode_response(self, response: str) -> None:
        for line in str(response).splitlines():
            self.tracker.on_gcode_response(line)
        self._publish()

    async def _maybe_load_metadata(self) -> None:
        filename = (self.tracker.status.get("print_stats") or {}).get("filename") or None
        if filename == self._last_filename:
            return
        self._last_filename = filename
        if not filename:
            self.tracker.set_metadata(None, None)
            return
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            meta = fm.get_file_metadata(filename)
            changes = await self._colour_changes(filename)
            self.tracker.set_metadata(filename, dict(meta or {}, colour_changes=changes) if changes else meta)
        except Exception:
            self.tracker.set_metadata(filename, None)

    async def _colour_changes(self, filename: str) -> list:
        """Each M600 in a G-code file and the layer it's on, read from the file once per version of it.
        Nothing on a printer without a unit: there, a colour change is the change routine."""
        if self.tracker.direct or not filename:
            return []
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            path = os.path.join(fm.get_directory("gcodes"), filename)
            st = os.stat(path)
        except Exception:
            return []
        hit = self._colour_cache.get(filename)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
        try:
            run = getattr(self.eventloop, "run_in_thread", None)
            changes = (await run(engine.colour_changes_from_file, path)) if run else engine.colour_changes_from_file(path)
        except Exception:
            logging.exception("intent: reading the colour changes in %s failed", filename)
            return []
        self._colour_cache.pop(filename, None)
        self._colour_cache[filename] = (st.st_mtime, st.st_size, changes)
        while len(self._colour_cache) > COLOUR_CACHE_KEPT:
            self._colour_cache.pop(next(iter(self._colour_cache)))
        return changes

    async def _restore_colour_plan(self) -> None:
        try:
            db = self.server.lookup_component("database")
            self.tracker.restore_colour_plan(await db.get_item("elyir-bench", "colour_plan", None))
        except Exception:
            logging.exception("intent: reading the colour plan failed")

    async def _save_colour_plan(self) -> None:
        self.tracker.colour_plan_dirty = False
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "colour_plan", self.tracker.colour_plan)
        except Exception:
            self.tracker.colour_plan_dirty = True
            logging.exception("intent: saving the colour plan failed")

    # ---- publishing ----------------------------------------------------------

    def _start_timer(self) -> None:
        if self._timer_running:
            return
        self._timer_running = True
        self.eventloop.delay_callback(PUBLISH_INTERVAL, self._tick)

    def _tick(self) -> None:
        try:
            if self._ticks % PHONES_CHECK_TICKS == 0:
                self.eventloop.create_task(self._refresh_phones())
                self.eventloop.create_task(self._refresh_next_plates())
                self.eventloop.create_task(self._refresh_care())
                self.eventloop.create_task(self._refresh_spoolman())
            if self._ticks % RESYNC_TICKS == RESYNC_TICKS // 2:
                self.eventloop.create_task(self._resync())
            if self.tracker.direct_spool_dirty:
                self.eventloop.create_task(self._save_spool())
            if self.tracker.colour_plan_dirty:
                self.eventloop.create_task(self._save_colour_plan())
            if self.tracker.checkpoint_dirty:
                self.eventloop.create_task(self._save_checkpoint())
            if self._ticks % UPS_CHECK_TICKS == 0 and self.ups_name is not None and not self._ups_reading:
                self._ups_reading = True
                self.eventloop.create_task(self._read_ups())
            if self._ticks % UNITS_CHECK_TICKS == 0:
                self.tracker.observe_usb_units(units_on_usb())
                if self.units_link.due():
                    self.units_link.running = True
                    self.eventloop.create_task(self.units_link.run())
            if self._ticks % SETUP_FILES_TICKS == 0:
                self._read_setup_files()
            self._check_trial()
            self._bring_tick()
            self._role_tick()
            self._unit_tick()
            if self._ticks % CLOUD_TICKS == CLOUD_TICKS // 3:
                self._cloud_tick()
            self._cloud_say_tick()
            self._check_power()
            self._ticks += 1
            self._drive()
            self._publish()
        finally:
            self.eventloop.delay_callback(PUBLISH_INTERVAL, self._tick)

    # ---- care: maintenance counted from print history ---------------------------

    def _totals(self) -> Dict[str, Any]:
        try:
            return dict(self.server.lookup_component("history").job_totals)
        except Exception:
            return {}

    async def _refresh_care(self) -> None:
        """Tasks are Mainsail's `maintenance` records; usage is Moonraker's history totals.
        The starting set is made once per printer (elyir-bench/care_seeded), so a task
        deleted in Mainsail stays deleted."""
        if care is None:
            return
        try:
            db = self.server.lookup_component("database")
            totals, now = self._totals(), time.time()
            if not await db.get_item("elyir-bench", "care_seeded", False):
                for key, entry in care.default_entries(totals, now).items():
                    await db.insert_item("maintenance", key, entry)
                await db.insert_item("elyir-bench", "care_seeded", True)
            entries = await db.get_item("maintenance", None, {})
            snoozes = await db.get_item("elyir-bench", "care_snooze", {})
            self._care_entries = entries or {}
            self.tracker.care = care.summary(self._care_entries, totals, now, snoozes or {})
        except Exception:
            logging.exception("intent: reading maintenance failed")

    async def _care_action(self, action: str, eid: str) -> None:
        db = self.server.lookup_component("database")
        totals, now = self._totals(), time.time()
        await self._refresh_care()
        snoozes = await db.get_item("elyir-bench", "care_snooze", {}) or {}
        if action == "care_done":
            for key, entry in care.perform(self._care_entries, eid, totals, now).items():
                await db.insert_item("maintenance", key, entry)
            snoozes.pop(eid, None)
        else:
            snoozes[eid] = care.later(eid, totals, now)
        await db.insert_item("elyir-bench", "care_snooze", snoozes)
        await self._refresh_care()

    # ---- the one spool on a printer without a filament unit -----------------

    async def _restore_spool(self) -> None:
        try:
            db = self.server.lookup_component("database")
            self.tracker.restore_spool(await db.get_item("elyir-bench", "spool", None))
        except Exception:
            logging.exception("intent: reading the spool failed")

    async def _save_spool(self) -> None:
        self.tracker.direct_spool_dirty = False
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "spool", self.tracker.direct_spool)
        except Exception:
            self.tracker.direct_spool_dirty = True
            logging.exception("intent: saving the spool failed")

    async def _on_spoolman_spool(self, *_: Any) -> None:
        await self._refresh_spoolman()
        self._publish()

    async def _refresh_spoolman(self) -> None:
        """Spoolman's active spool, when Moonraker is set up with it. A failed request keeps
        what was there; no active spool clears it."""
        if not self.tracker.direct:
            return
        try:
            sm = self.server.lookup_component("spoolman")
        except Exception:
            sm = None
        spool_id = getattr(sm, "spool_id", None) if sm is not None else None
        if spool_id is None:
            self.tracker.spoolman_spool = None
            return
        try:
            resp = await self.server.lookup_component("http_client").get(f"{sm.spoolman_url}/v1/spool/{spool_id}")
            if resp.has_error():
                return
            data = resp.json()
        except Exception:
            logging.exception("intent: reading the Spoolman spool failed")
            return
        fil = data.get("filament") or {}
        self.tracker.spoolman_spool = {"color": fil.get("color_hex"), "material": fil.get("material"),
                                       "grams": data.get("remaining_weight")}

    async def _refresh_phones(self) -> None:
        try:
            db = self.server.lookup_component("database")
            phones = await db.get_item("elyir-bench", "phones", 0)
            self.tracker.phones_notified = bool(int(phones or 0))
        except Exception:
            self.tracker.phones_notified = False

    async def _refresh_next_plates(self) -> None:
        """What the slicer said comes after each plate it sent (design/plate/, A)."""
        try:
            db = self.server.lookup_component("database")
            plates = await db.get_item("elyir-bench", "next_plates", [])
            self.tracker.next_plates = plates if isinstance(plates, list) else []
        except Exception:
            self.tracker.next_plates = []

    def _current(self) -> Dict[str, Any]:
        self._sync_klippy_state()
        self.tracker.setup_found = list(self._bring.get("found") or [])
        intent = self.tracker.intent()
        intent["printer"]["advanced_url"] = self.advanced_url
        intent["printer"]["screen_switch"] = self._can_switch_screen()
        intent["printer"]["screen_switch_failed"] = self._screen_switch_failed
        intent["printer"]["screen_trial"] = self._screen_trial()
        intent["setup"] = {"open": self._setup_open()}
        return intent

    def _can_switch_screen(self) -> bool:
        return os.access(self.cli, os.X_OK) and os.path.exists(self.klipperscreen_unit)

    async def _run_cli(self, *args: str, failed: str = "it didn't come up") -> Optional[str]:
        """`elyir-bench --json <args>`, without holding anything up. None when it worked, otherwise why,
        from the installer's report."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli, "--json", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            if proc.returncode:
                why = switch_failure(out.decode(errors="replace")) or failed
                logging.info("intent: elyir-bench %s failed: %s %s", " ".join(args), why, err.decode(errors="replace")[-400:])
                return why
        except Exception as e:
            logging.info("intent: elyir-bench %s failed: %s", " ".join(args), e)
            return failed
        return None

    async def _switch_screen(self, mode: str) -> None:
        """`elyir-bench panel <mode>`: stops one app, starts the other, and remembers it across
        reboots. The screen goes dark for a few seconds in between. A switch that doesn't come up
        is undone by the installer; Care then says what happened."""
        self._screen_switching = True
        try:
            why = await self._run_cli("panel", mode)
        finally:
            self._screen_switching = False
        if why:
            self._screen_switch_failed = (f"Couldn't show KlipperScreen ({why}), so the screen went back to Elyir Bench."
                                          if mode == "klipperscreen" else f"Couldn't switch the screen back to Elyir Bench ({why}).")
        else:
            self._screen_switch_failed = None
        self._publish(force=True)

    # ---- Finish setting up (docs/setup-card.md) ---------------------------------

    async def _restore_setup(self) -> None:
        try:
            db = self.server.lookup_component("database")
            saved = await db.get_item("elyir-bench", "setup", None) or {}
        except Exception:
            logging.exception("intent: reading the setup card failed")
            return
        if isinstance(saved, dict):
            self._setup_dismissed = [r for r in saved.get("dismissed") or [] if isinstance(r, str)]
            self._screen_outcome = saved.get("screen") if saved.get("screen") in ("done", "kept_klipperscreen") else None

    async def _save_setup(self) -> None:
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "setup", {"dismissed": self._setup_dismissed, "screen": self._screen_outcome})
        except Exception:
            logging.exception("intent: saving the setup card failed")

    def _read_setup_files(self) -> None:
        """What the installer found this board can do (state.json, as its last apply saved it), and what
        elyir-bench.conf says the printer's screen shows: elyir-bench | klipperscreen | none."""
        self.tracker.unit_installer = os.access(self.cli, os.X_OK)
        try:
            with open(self.installer_state) as f:
                st = json.load(f)
            exp = st.get("expectations")
            self._board_seen = exp if isinstance(exp, dict) else None
            kept = st.get("unit_kept")
            if self._unit_run is None:
                self.tracker.unit_kept = ({k: kept.get(k) for k in ("unit", "board", "slots", "program", "when")}
                                          if isinstance(kept, dict) else None)
        except (OSError, ValueError, AttributeError):
            self._board_seen = None
        self._panel_seen = None
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            with open(os.path.join(fm.get_directory("config"), "elyir-bench.conf")) as f:
                text = f.read()
        except Exception:
            return
        for line in text.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "panel":
                self._panel_seen = value.split("#")[0].strip()

    def _board(self) -> Optional[Dict[str, Any]]:
        return self._board_seen

    def _panel_setting(self) -> Optional[str]:
        return self._panel_seen

    def _screen_trial(self) -> Optional[Dict[str, int]]:
        if self._trial_until is None:
            return None
        return {"seconds_left": max(0, int(-(-(self._trial_until - time.time()) // 1)))}

    def _check_trial(self) -> None:
        """Nobody answered the panel's Keep / Back in time: back, exactly like screen_back."""
        if self._trial_until is not None and time.time() >= self._trial_until:
            self._screen_back()

    def _screen_back(self) -> None:
        self._trial_until = None
        self._screen_outcome = "kept_klipperscreen"
        self.eventloop.create_task(self._save_setup())
        if not self._screen_switching:
            self.eventloop.create_task(self._switch_screen("klipperscreen"))
        self._publish(force=True)

    def _screen_cant_run(self) -> Optional[str]:
        """Why this system can't show Elyir Bench on its screen, when the installer found it can't."""
        board = self._board() or {}
        if any(str(d).startswith(NO_SCREEN_APP) for d in board.get("differences") or []):
            return "This system can't run Elyir Bench on its screen. Nothing changed."
        return None

    def _screen_row(self) -> Optional[Dict[str, Any]]:
        """The screen row's state, or None when there's no screen to offer: none at all, no KlipperScreen to
        come back to, or it already shows Elyir Bench from the install."""
        if self._trial_until is not None:
            return {"id": "screen", "state": "trial"}
        if self._screen_fetching:
            return {"id": "screen", "state": "fetching"}
        if self._screen_cant:
            return {"id": "screen", "state": "cant", "why": self._screen_cant}
        if self._screen_outcome:
            return {"id": "screen", "state": self._screen_outcome}
        if not self._can_switch_screen() or self._panel_setting() != "klipperscreen":
            return None
        cant = self._screen_cant_run()
        if cant:
            return {"id": "screen", "state": "cant", "why": cant}
        return {"id": "screen", "state": "offer"}

    def _include_state(self) -> str:
        if self._include_busy:
            return self._include_busy
        if self._include_why:
            return "failed"
        return "on" if START_MACRO_COMMAND in self._objects else "off"

    def _features(self, webcams: int = 0) -> list:
        """What works on this printer, from what Klipper and Moonraker have: now, with the start macro
        (elyir-bench.cfg), or not here. Our own PRINT_START already does what the start macro would."""
        objects = self._objects
        macro = self._include_state() == "on" or "gcode_macro _PRINT_START" in objects
        later = "now" if macro else "with_macro"
        sensor = any(o.startswith(("filament_switch_sensor ", "filament_motion_sensor ")) for o in objects)
        unit = bool(self.tracker.has_unit)
        out = [{"id": "core", "group": "now", "label": "Ready, printing, history, Care"}]
        if sensor or unit:
            out.append({"id": "runout", "group": "now", "label": "Filament runs out",
                        "note": "Your runout sensor" if sensor else "The filament unit"})
        else:
            out.append({"id": "runout", "group": "not_here", "label": "Filament runs out", "note": "No runout sensor found"})
        out.append({"id": "camera", "group": "now", "label": "Camera"} if webcams else
                   {"id": "camera", "group": "not_here", "label": "Camera", "note": "No camera found"})
        steps = {"id": "steps", "group": later, "label": "The steps while it gets ready"}
        if not macro:
            steps["note"] = "Rough today, from your messages"
        out += [steps, {"id": "cancel", "group": later, "label": "Cancel while it warms up"},
                {"id": "squish", "group": later, "label": "Squish the first layer more or less"}]
        if self.tracker.chamber_sensor_name(objects):
            out.append({"id": "chamber", "group": later, "label": "Wait for the chamber to warm"})
        out.append({"id": "unit", "group": "now", "label": "Filament unit slots"} if unit else
                   {"id": "unit", "group": "not_here", "label": "Filament unit slots", "note": "No ACE Pro found"})
        return out

    def _setup_rows(self, webcams: int = 0) -> list:
        features = self._features(webcams)
        rows: list = [{"id": "notify"}]
        screen = self._screen_row()
        if screen:
            rows.append(screen)
        rows.append({"id": "works", "now": sum(f["group"] == "now" for f in features),
                     "with_macro": sum(f["group"] == "with_macro" for f in features)})
        return rows

    def _setup_open(self) -> bool:
        """The phone shows the card while any row is neither done nor closed. A phone that hears from the
        printer stands for notify done (which phone that is, only the app knows)."""
        for row in self._setup_rows():
            if row["id"] in self._setup_dismissed:
                continue
            if row["id"] == "notify" and not self.tracker.phones_notified:
                return True
            if row["id"] == "screen" and row["state"] not in ("done", "kept_klipperscreen"):
                return True
            if row["id"] == "works" and row["with_macro"]:
                return True
        return False

    async def _webcam_count(self) -> int:
        try:
            return len(self.server.lookup_component("webcam").get_webcams())
        except Exception:
            pass
        try:
            db = self.server.lookup_component("database")
            return len(await db.get_item("webcams", None, {}) or {})
        except Exception:
            return 0

    async def _name_from(self) -> str:
        """Where the printer's name came from: Mainsail's own name for it, the host's, or the person."""
        try:
            db = self.server.lookup_component("database")
            general = await db.get_item("mainsail", "general", {}) or {}
            if str(general.get("printername") or "").strip().lower() == self.printer_name.lower():
                return "mainsail"
        except Exception:
            pass
        return "hostname" if socket.gethostname().split(".")[0].lower() == self.printer_name.lower() else "you"

    async def _secure_link(self) -> str:
        """The printer's secure link (its public name on the relay), for the notifications row: notifications need
        it, and during the test a name waits for Elyir to approve it. Asked at most every SECURE_LINK_TTL s."""
        now = time.monotonic()
        cached = getattr(self, "_secure_cache", None)
        if cached and now - cached[0] < SECURE_LINK_TTL:
            return cached[1]
        try:
            with open(os.path.join(os.path.dirname(self.installer_state), "state", "relay.json")) as f:
                relay = json.load(f)
        except (OSError, ValueError):
            relay = {}
        run = getattr(self.eventloop, "run_in_thread", None)
        try:
            state = (await run(secure_link_state, relay, ask_relay)) if run else secure_link_state(relay, ask_relay)
        except Exception:
            state = "waiting" if relay.get("name") else "off"
        self._secure_cache = (now, state)
        return state

    async def _setup(self) -> Dict[str, Any]:
        self._read_setup_files()
        webcams = await self._webcam_count()
        return {
            "name": self.printer_name, "name_from": await self._name_from(),
            "secure_link": await self._secure_link(),       # off | waiting | on (docs/setup-card.md)
            "rows": self._setup_rows(webcams),
            "dismissed": list(self._setup_dismissed),
            "works": {
                "board": self._board(),
                "features": self._features(webcams),
                "include": self._include_state(),
                "include_why": self._include_why if self._include_state() == "failed" else None,
                "include_text": INCLUDE_TEXT,
                "slicer_lines": dict(SLICER_LINES),
            },
        }

    async def _try_screen(self) -> None:
        """`elyir-bench panel elyir-bench`: fetches the screen's parts when they're missing (KlipperScreen stays on
        until they're in), switches, and the trial starts. Parts that can't be had: said on the card."""
        self._screen_fetching, self._screen_switching = True, True
        self._publish(force=True)
        try:
            why = await self._run_cli("panel", "elyir-bench")
        finally:
            self._screen_fetching, self._screen_switching = False, False
        self._read_setup_files()
        if why:
            first = why.split(". ")[0].rstrip(".")
            self._screen_cant = f"{first[:1].upper()}{first[1:]}. Nothing changed."
        else:
            self._trial_until = time.time() + SCREEN_TRIAL_SECONDS
        self._publish(force=True)

    async def _set_include(self, on: bool) -> None:
        """`elyir-bench startmacro on|off`: elyir-bench.cfg and its include line, and Klipper restarted to read them."""
        self._include_busy, self._include_why = ("adding" if on else "removing"), None
        self._publish(force=True)
        try:
            why = await self._run_cli("startmacro", "on" if on else "off", failed="Klipper didn't restart")
        finally:
            self._include_busy = None
        self._include_why = why
        try:
            self._objects = list(await self.klippy_apis.get_object_list() or [])
        except Exception:
            pass
        self._publish(force=True)

    async def _set_name(self, name: str) -> None:
        """The card's Change: the name Elyir Bench shows, at once, and in both config files so a restart keeps
        it. Only the shown name: the printer's name on the network stays (on a printer someone already runs,
        Mainsail, their slicer and SSH know it by that). The Wi-Fi announcement and the slicer catch up at
        the next apply."""
        name = " ".join(name.split())
        if not name or len(name) > 32:
            raise self.server.error("A name is 1 to 32 characters.", 400)
        self.printer_name = self.tracker.printer_name = name
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            folder = fm.get_directory("config")
        except Exception:
            return
        for file, section in (("elyir-bench.conf", "elyir-bench"), ("moonraker.conf", "printer_intent")):
            path = os.path.join(folder, file)
            try:
                with open(path) as f:
                    text = f.read()
                new = set_conf_name(text, section, name)
                if new != text:
                    with open(path + ".tmp", "w") as f:
                        f.write(new)
                    os.replace(path + ".tmp", path)
            except OSError as e:
                logging.info("intent: couldn't keep the name %r in %s: %s", name, file, e)

    async def _setup_action(self, action: str, args: Dict[str, Any]) -> None:
        if action == "setup_name":
            await self._set_name(str(args.get("name") or ""))
        elif action == "setup_dismiss":
            row = str(args.get("row") or "")
            if row in SETUP_ROWS and row not in self._setup_dismissed:
                self._setup_dismissed.append(row)
                await self._save_setup()
        elif action == "screen_try":
            if not self._can_switch_screen():
                raise self.server.error("This printer has no screen Elyir Bench can switch to.", 400)
            cant = self._screen_cant_run()
            if cant:
                raise self.server.error(cant, 400)
            if self._trial_until is None and not self._screen_switching:
                self._screen_cant, self._screen_outcome = None, None
                if "screen" in self._setup_dismissed:
                    self._setup_dismissed.remove("screen")
                self.eventloop.create_task(self._try_screen())
        elif action in ("screen_keep", "screen_back"):
            if self._trial_until is None:
                raise self.server.error("The screen isn't on trial.", 400)
            if action == "screen_keep":
                self._trial_until, self._screen_outcome = None, "done"
                await self._save_setup()
            else:
                self._screen_back()
        elif action in ("include_add", "include_remove"):
            if (self.tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
                raise self.server.error("Klipper restarts to read it, so that waits until the print is done.", 400)
            if not self._include_busy:
                self.eventloop.create_task(self._set_include(action == "include_add"))

    # ---- Slicing like their own prints (docs/slicer-profile.md) ------------------------

    async def _restore_profile(self) -> None:
        try:
            db = self.server.lookup_component("database")
            saved = await db.get_item("elyir-bench", "profile", None) or {}
        except Exception:
            logging.exception("intent: reading the slicing profile state failed")
            return
        if isinstance(saved, dict):
            self._profile_saved = {"told": bool(saved.get("told")), "keep": [str(k) for k in saved.get("keep") or []]}

    async def _save_profile(self) -> None:
        try:
            db = self.server.lookup_component("database")
            await db.insert_item("elyir-bench", "profile", dict(self._profile_saved))
        except Exception:
            logging.exception("intent: saving the slicing profile state failed")

    async def _read_axis_max(self) -> None:
        """Klipper's limits for the bed check (toolhead.axis_maximum), read at each ready; then the profile the
        files agree on can be checked, and used."""
        try:
            res = await self.klippy_apis.query_objects({"toolhead": ["axis_maximum"]})
            axis = ((res or {}).get("toolhead") or {}).get("axis_maximum")
            if isinstance(axis, (list, tuple)) and len(axis) >= 2:
                self._axis_max = [float(x) for x in axis]
        except Exception:
            logging.exception("intent: reading Klipper's axis limits failed")
        await self._profile_settle()

    def _folder(self, root: str) -> Optional[str]:
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            return fm.get_directory(root) or None
        except Exception:
            return None

    def _slicer_home(self) -> Optional[str]:
        config = self._folder("config")
        return os.path.join(config, SLICER_HOME) if config else None

    async def _on_files_changed(self, response: Any) -> None:
        """Moonraker's file events: a change in the gcodes folder means another look, a few seconds later."""
        if not isinstance(response, dict):
            return
        roots = {(response.get(k) or {}).get("root") for k in ("item", "source_item")}
        if "gcodes" in roots and not self._profile_scan_due:
            self._profile_scan_due = True
            self.eventloop.delay_callback(PROFILE_SCAN_DELAY, self._scan_profiles)

    def _read_gcodes(self, folder: str) -> list:
        """The newest G-code files' profiles, each read once per version of the file (in a thread)."""
        found = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]          # .thumbs
            for name in names:
                if name.lower().endswith(".gcode") and not name.startswith("."):
                    path = os.path.join(root, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    found.append((st.st_mtime, st.st_size, path))
        cache, files = {}, []
        for mtime, size, path in sorted(found, reverse=True)[:PROFILE_FILES]:
            hit = self._profile_cache.get(path)
            f = hit[2] if hit and hit[0] == mtime and hit[1] == size else orca.read(path)
            cache[path] = (mtime, size, f)
            files.append(f)
        self._profile_cache = cache
        return files

    async def _scan_profiles(self) -> None:
        if self._profile_scanning:                   # one at a time; the files changed again meanwhile: once more after
            self._profile_scan_due = True
            self.eventloop.delay_callback(PROFILE_SCAN_DELAY, self._scan_profiles)
            return
        self._profile_scan_due = False
        folder = self._folder("gcodes")
        if orca is None or not folder:
            return
        self._profile_scanning = True
        run = getattr(self.eventloop, "run_in_thread", None)
        try:
            files = (await run(self._read_gcodes, folder)) if run else self._read_gcodes(folder)
        except Exception:
            logging.exception("intent: reading the G-code files' slicing profiles failed")
            return
        finally:
            self._profile_scanning = False
        self._profile_files = files
        self._profiles = orca.group(files)
        await self._profile_settle()

    def _printer_json(self) -> Optional[Dict[str, Any]]:
        """elyir-bench-slicer/printer.json as it is; None when it isn't there. One that can't be read counts as the
        person's own (someone is editing it): it's never written over."""
        home = self._slicer_home()
        if not home:
            return None
        try:
            with open(os.path.join(home, "printer.json")) as f:
                d = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return {"unreadable": True}
        return d if isinstance(d, dict) else {"unreadable": True}

    def _profile_answer(self) -> Dict[str, Any]:
        klipper = {"axis_maximum": self._axis_max,
                   "macros": orca.macros_of(self._objects) if self._objects else None}
        return orca.answer(self._profiles, self._profile_files, self._printer_json(), self._profile_saved, klipper)

    def _profile_view(self) -> Dict[str, Any]:
        if orca is None:
            return {"state": "none", "told": False, "using": None, "found": [], "bed_klipper": None, "newer": None}
        out = self._profile_answer()
        out.pop("auto", None)
        return out

    async def _profile_settle(self) -> None:
        """Nothing in use yet and the recent files agree on a profile that fits this printer: use it, by itself."""
        if orca is None:
            return
        pick = self._profile_answer().get("auto")
        if pick:
            try:
                await self._use_profile(pick)
            except Exception:
                logging.exception("intent: using the slicing profile %s by itself failed", pick)

    def _slots(self) -> int:
        """How many filaments the slicer may use: one, or every slot of the printer's filament units."""
        if self.tracker.has_unit:
            return len(self.tracker.spools()) or 4
        return 1

    def _cached_read(self, path: str) -> Optional[Dict[str, Any]]:
        hit = self._profile_cache.get(path)
        return hit[2] if hit else orca.read(path)

    async def _use_profile(self, pid: str) -> None:
        """printer.json and presets/0-learned/ from one profile: the slicer uses them from its next slice."""
        profile = next((p for p in self._profiles if p["id"] == pid), None)
        if profile is None:
            raise self.server.error("Those settings aren't in the printer's files any more.", 400)
        current = self._printer_json()
        if current is not None and "learned" not in current:
            raise self.server.error("This printer's slicing settings were set by hand (elyir-bench-slicer/printer.json), "
                                    "so Elyir Bench leaves them as they are.", 400)
        home = self._slicer_home()
        if not home:
            raise self.server.error("The printer's config folder can't be found.", 400)
        keys = orca.load_keys(self.orca_keys)
        presets = orca.learned(profile, self._cached_read, keys)
        start_macro = START_MACRO_COMMAND in self._objects or bool((current or {}).get("start_macro"))
        pj = orca.printer_json(profile, self._slots(), time.time(), self._folder("gcodes") or "", start_macro)
        run = getattr(self.eventloop, "run_in_thread", None)
        if run:
            await run(write_profile, home, pj, presets)
        else:
            write_profile(home, pj, presets)
        logging.info("intent: slicing like the printer's files now: %s / %s, from %d files",
                     profile["machine"], profile["process"], profile["files"])

    async def _profile_action(self, action: str, args: Dict[str, Any]) -> None:
        if orca is None:
            raise self.server.error("This release can't learn slicing settings yet.", 400)
        if action == "profile_use":
            await self._use_profile(str(args.get("id") or ""))
        elif action == "profile_told":
            if not self._profile_saved.get("told"):
                self._profile_saved["told"] = True
                await self._save_profile()
        elif action == "profile_keep":
            pid = str(args.get("id") or "") or self._profile_answer().get("newer")
            if pid and pid not in self._profile_saved["keep"]:
                self._profile_saved["keep"].append(pid)
                await self._save_profile()

    async def _handle_profile(self, web_request: WebRequest) -> Dict[str, Any]:
        return self._profile_view()

    # ---- Bring it over (docs/bring-it-over.md) ------------------------------------------

    def _bring_folder(self) -> str:
        return os.path.join(os.path.dirname(self.installer_state), "state")

    def _bring_view(self) -> Dict[str, Any]:
        return dict(self._bring)

    def _restore_bring(self) -> None:
        """What the last scan found, and a run that Moonraker restarted under (bringing a setup over restarts it):
        followed on, or its answer said, when it ended recently."""
        try:
            with open(os.path.join(self._bring_folder(), BRING_CACHE)) as f:
                cache = json.load(f)
            self._bring["sources"] = [e["source"] for e in cache.get("sources") or [] if isinstance(e, dict) and "source" in e]
            self._bring["found"] = [str(w) for w in cache.get("found") or []]
            self._bring["boards"] = cache.get("boards") if isinstance(cache.get("boards"), int) else None
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        path = os.path.join(self._bring_folder(), BRING_RUN)
        try:
            if time.time() - os.path.getmtime(path) > BRING_RESUME or not os.path.getsize(path):
                return
        except OSError:
            return
        self._bring_run = {"kind": None, "pid": None, "since": time.time(), "seen": 0, "resumed": True}
        self._bring_tick()

    def _bring_start(self, kind: str, *args: str) -> None:
        """`elyir-bench --json bring <kind> …`, apart from Moonraker: through a shell that leaves it running on its own,
        so a Moonraker restart neither stops it nor leaves it unreaped. Its lines go to the run file."""
        folder = self._bring_folder()
        os.makedirs(folder, exist_ok=True)
        run, log = os.path.join(folder, BRING_RUN), os.path.join(folder, "bring-run.log")
        try:
            with open(run, "w"):
                pass
            subprocess.run(["/bin/sh", "-c", 'exec "$0" "$@" >"$RUN" 2>>"$LOG" </dev/null &', self.cli, "--json", "bring",
                            kind, *args], env=dict(os.environ, RUN=run, LOG=log), timeout=10, check=True)
        except Exception as e:
            logging.info("intent: elyir-bench bring %s didn't start: %s", kind, e)
            self._bring.update(state="failed" if kind == "apply" else "idle", why="Elyir Bench's installer didn't start.")
            self._publish_bring()
            return
        self._bring_run = {"kind": kind, "pid": None, "since": time.time(), "seen": 0}
        self._bring_scanned = True    # someone's looking: no need to look by itself
        self._bring.update(state=BRING_STATES[kind], why=None)
        if kind == "apply":
            self._bring.update(progress=None, result=None)
        self._publish_bring()

    def _bring_tick(self) -> None:
        """Read what the running `elyir-bench bring` said since the last tick; its last line is the answer."""
        r = self._bring_run
        if r is None:
            self._maybe_scan_fresh_card()
            if (self._bring.get("cloud") or {}).get("state") == "waiting" and self._ticks % CLOUD_POLL_TICKS == 0:
                self._bring_start("cloud-check")
            return
        try:
            with open(os.path.join(self._bring_folder(), BRING_RUN)) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        final = None
        for line in lines[r["seen"]:]:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "started" in msg:
                r["kind"], r["pid"] = msg["started"], msg.get("pid")
                if r.get("resumed"):
                    self._bring["state"] = BRING_STATES.get(r["kind"], "idle")
            elif "progress" in msg:
                self._bring["progress"] = msg["progress"]
            else:
                final = msg
        r["seen"] = len(lines)
        if final is None and not self._bring_alive(r):
            final = {"failed": "It stopped without saying why."}
        if final is None:
            self._publish_bring()
            return
        self._bring_run = None
        kind = r.get("kind")
        if "failed" in final:
            self._bring.update(state="failed" if kind == "apply" else "idle", why=str(final["failed"]))
        elif "result" in final:
            self._bring.update(state="done", result=final["result"], why=None)
        else:
            if "cloud" in final:
                self._bring["cloud"] = final["cloud"]
            if "sources" in final:
                self._bring["sources"] = list(final["sources"])
                self._bring["found"] = list(final.get("found") or [])
                self._bring["boards"] = final.get("boards") if isinstance(final.get("boards"), int) else None
            if "source" in final:
                sid = final["source"].get("id")
                self._bring["sources"] = [s for s in self._bring["sources"] if s.get("id") != sid] + [final["source"]]
            if "plan" in final:
                self._bring["plan"] = final["plan"]
            self._bring.update(state="idle", why=None)
        self._publish_bring()
        self._publish(force=True)

    @staticmethod
    def _bring_alive(r: Dict[str, Any]) -> bool:
        if r.get("pid"):
            try:
                os.kill(int(r["pid"]), 0)
                return True
            except ProcessLookupError:
                return False
            except (PermissionError, ValueError, TypeError):
                return True
        return time.time() - r["since"] < BRING_QUIET   # hasn't said who it is yet

    # ---- setting a filament unit up (design/unit-setup/, B, stage 2) -------------------------------------------

    def _unit_start(self, job: str, args: Optional[Dict[str, Any]]) -> None:
        """`elyir-bench --json unit …` apart from Moonraker, like a bring run; its lines go to the run file."""
        cmd = UNIT_JOBS.get(job) or ["install", "--unit", str(args["unit"]), "--board", str(args["board"]),
                                     "--slots", str(args["slots"]), "--mcu", str(args["mcu"]), "--kind", str(args["kind"])]
        folder = self._bring_folder()
        run, log = os.path.join(folder, UNIT_RUN), os.path.join(folder, "unit-run.log")
        try:
            os.makedirs(folder, exist_ok=True)
            with open(run, "w"):
                pass
            subprocess.run(["/bin/sh", "-c", 'exec "$0" "$@" >"$RUN" 2>>"$LOG" </dev/null &', self.cli, "--json", "unit",
                            *cmd], env=dict(os.environ, RUN=run, LOG=log), timeout=10, check=True)
        except Exception as e:
            logging.info("intent: elyir-bench unit %s didn't start: %s", cmd[0], e)
            self.tracker.unit_setup_heard({"failed": "Bench's installer didn't start."})
            self._publish(force=True)
            return
        self._unit_run = {"pid": None, "since": time.time(), "seen": 0}

    def _unit_tick(self) -> None:
        r = self._unit_run
        if r is None:
            return
        try:
            with open(os.path.join(self._bring_folder(), UNIT_RUN)) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        final = None
        for line in lines[r["seen"]:]:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "started" in msg:
                r["pid"] = msg.get("pid")
            elif "progress" not in msg:
                final = msg
            self.tracker.unit_setup_heard(msg)
        r["seen"] = len(lines)
        if final is None and not self._bring_alive(r):
            self.tracker.unit_setup_heard({"failed": "It stopped without saying why."})
            final = {}
        if final is not None:
            self._unit_run = None
            self._read_setup_files()
            self._drive()
        self._publish(force=True)

    # ---- printer or Bench Box (design/role/, B) ----------------------------------------------

    def _role_action(self, action: str) -> None:
        role = self._bring.get("role") or {}
        if action == "role_back":
            if self._role_run is None:
                self._bring["role"] = None
                self._publish_bring()
            return
        if self._role_run is not None or role.get("state") == "switching":
            raise self.server.error("It's becoming a Bench Box now.", 400)
        if (self._bring_run or {}).get("kind") == "apply" or self._bring["state"] == "bringing":
            raise self.server.error("It's bringing a setup over now.", 400)
        if (self.tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            raise self.server.error("It's printing. A printer that's printing isn't becoming a Bench Box.", 400)
        folder = self._bring_folder()
        os.makedirs(folder, exist_ok=True)
        run, log = os.path.join(folder, ROLE_RUN), os.path.join(folder, "role-run.log")
        try:
            with open(run, "w"):
                pass
            subprocess.run(["/bin/sh", "-c", 'exec "$0" "$@" >"$RUN" 2>>"$LOG" </dev/null &', self.cli, "--json", "role",
                            "controller"], env=dict(os.environ, RUN=run, LOG=log), timeout=10, check=True)
        except Exception as e:
            logging.info("intent: elyir-bench role controller didn't start: %s", e)
            self._bring["role"] = {"state": "failed", "progress": None, "why": "Elyir Bench's installer didn't start.", "url": None}
            self._publish_bring()
            return
        self._role_run = {"pid": None, "since": time.time(), "seen": 0}
        self._bring["role"] = {"state": "switching", "progress": None, "why": None,
                               "url": f"http://{socket.gethostname()}.local:{BOX_PORT}/"}
        self._publish_bring()

    def _role_tick(self) -> None:
        """Read what `elyir-bench role controller` said since the last tick. Its last step stops Moonraker, so the end is
        usually this component going away; a failure before that is said."""
        r, role = self._role_run, self._bring.get("role")
        if r is None or role is None:
            return
        folder = self._bring_folder()
        try:
            with open(os.path.join(folder, ROLE_RUN)) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        final = None
        for line in lines[r["seen"]:]:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "started" in msg:
                r["pid"] = msg.get("pid")
            elif "progress" in msg:
                role["progress"] = msg["progress"]
            else:
                final = msg
        r["seen"] = len(lines)
        if final is None and not self._bring_alive(r):
            # it ended without its answer: what it last said on stderr, if anything (an installer without `role` yet)
            try:
                with open(os.path.join(folder, "role-run.log")) as f:
                    tail = [l.strip() for l in f.read().splitlines() if l.strip()]
            except OSError:
                tail = []
            final = {"failed": tail[-1] if tail else "It stopped without saying why."}
        if final is not None:
            self._role_run = None
            if "failed" in final:
                role.update(state="failed", why=str(final["failed"]))
        self._publish_bring()

    def _cloud_tick(self) -> None:
        """The nightly Bench Cloud backup (docs/cloud.md), for a printer in a house: `elyir-bench cloud backup` on its own,
        apart from Moonraker, like Bring it over's runs. It reads this printer's database through this component."""
        folder, now = self._bring_folder(), time.time()
        if not os.path.exists(os.path.join(folder, "cloud.json")) or now - self._cloud_started < 3600:
            return
        try:
            with open(os.path.join(folder, "cloud-last.json")) as f:
                last = float(json.load(f).get("at") or 0)
        except (OSError, ValueError, AttributeError, TypeError):
            last = 0.0
        due = now - last > CLOUD_OVERDUE or (now - last > CLOUD_AGAIN and time.localtime(now).tm_hour in CLOUD_NIGHT)
        if not due or not os.access(self.cli, os.X_OK):
            return
        self._cloud_started = now
        try:
            subprocess.run(["/bin/sh", "-c", 'exec nice -n 10 "$0" "$@" >/dev/null 2>>"$LOG" </dev/null &', self.cli,
                            "--json", "cloud", "backup"], env=dict(os.environ, LOG=os.path.join(folder, "cloud-run.log")),
                           timeout=10, check=True)
        except Exception as e:
            logging.info("intent: elyir-bench cloud backup didn't start: %s", e)

    def _cloud_file(self, name: str) -> Dict[str, Any]:
        try:
            with open(os.path.join(self._bring_folder(), name)) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _cloud_say_tick(self) -> None:
        """A few words for the owner's page at Bench Cloud: its state, the job, how far and when it's done, and its
        address from away for Open. Never files or the camera. Only for a printer in a house."""
        if self._ticks % 60 == 0 or self._cloud_me is None:
            me = self._cloud_file("cloud.json")
            self._cloud_me = me if me.get("token") and me.get("api") else {}
        if not self._cloud_me or self._cloud_saying:
            return
        now = time.time()
        say = self._cloud_words(now)
        said = (say["state"], say["headline"])
        if now - self._cloud_said_at >= CLOUD_SAY_S or (said != self._cloud_said and now - self._cloud_said_at >= CLOUD_SAY_SOON_S):
            self._cloud_saying = True
            self.eventloop.create_task(self._cloud_say(dict(self._cloud_me), say, said, now))

    def _cloud_words(self, now: float) -> Dict[str, Any]:
        i = self._current()
        job = i.get("job") or {}
        left = job.get("remaining_s")
        address = self._cloud_file("relay.json").get("address")
        return {"state": i.get("state"), "phase": i.get("phase"), "headline": i.get("headline"), "detail": i.get("detail"),
                "job": job.get("name"), "progress": job.get("progress"),
                "done_at": now + left if isinstance(left, (int, float)) and left > 0 else None,
                "address": address if isinstance(address, str) else None}

    async def _cloud_say(self, me: Dict[str, Any], say: Dict[str, Any], said: tuple, now: float) -> None:
        try:
            resp = await self.server.lookup_component("http_client").post(
                f"{me['api'].rstrip('/')}/v1/status", body=say, headers={"Authorization": f"Bearer {me['token']}"},
                request_timeout=15.)
            if resp.has_error():
                logging.info("intent: Bench Cloud didn't take what the printer is doing: %s", resp.status_code)
        except Exception as e:
            logging.info("intent: Bench Cloud can't be reached: %s", e)
        finally:   # tried: the next try waits its turn either way, so a cloud that's down isn't asked every second
            self._cloud_said, self._cloud_said_at, self._cloud_saying = said, now, False

    def _maybe_scan_fresh_card(self) -> None:
        """A fresh card (no printer.cfg) is looked at once by itself: the first screen offers what's there."""
        if self._bring_scanned or not os.access(self.cli, os.X_OK):
            return
        if self.tracker.klippy_state == "error" and engine.NO_CONFIG.search(self.tracker.klippy_message or ""):
            self._bring_scanned = True
            self._bring_start("scan")

    def _publish_bring(self) -> None:
        view = self._bring_view()
        key = json.dumps(view, sort_keys=True, default=str)
        if key != self._bring_sent:
            self._bring_sent = key
            self.server.send_event("printer_intent:bring", view)

    def _bring_action(self, action: str, args: Dict[str, Any]) -> None:
        running = self._bring_run.get("kind") if self._bring_run else None
        if running == "apply" or self._bring["state"] == "bringing":
            raise self.server.error("It's bringing a setup over now.", 400)
        if action == "bring_scan":
            if not running:
                self._bring_start("scan")
            return
        if running:
            raise self.server.error("It's still looking. Try again in a moment.", 400)
        if action == "bring_address":
            address = " ".join(str(args.get("address") or "").split())
            if not address:
                raise self.server.error("Which address? Its name, like studio.local, or its number.", 400)
            self._bring_start("address", address)
            return
        if action in ("bring_cloud_check", "bring_cloud_email"):
            self._bring_start(action[6:].replace("_", "-"))
            return
        if action == "bring_cloud_code":
            code = "".join(ch for ch in str(args.get("code") or "") if ch.isdigit())
            if len(code) != 6:
                raise self.server.error("Type the six digits from the email.", 400)
            self._bring_start("cloud-code", code)
            return
        sid = str(args.get("id") or "")
        if sid not in [s.get("id") for s in self._bring["sources"]]:
            raise self.server.error("That isn't one it found. Look again first.", 400)
        if action == "bring_plan":
            self._bring_start("plan", sid)
            return
        if action == "bring_cloud_ask":
            self._bring_start("cloud-ask", sid)
            return
        if (self.tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            raise self.server.error("It's printing. Bring it over when the print is done.", 400)
        self._bring_start("apply", sid, *(["--gcodes"] if args.get("gcodes") else []))

    async def _handle_bring(self, web_request: WebRequest) -> Dict[str, Any]:
        return self._bring_view()

    async def _handle_bring_export(self, web_request: WebRequest) -> Dict[str, Any]:
        """This printer's Moonraker database, for another printer bringing it over: made with Moonraker's own backup,
        cleaned of its logins and API key, sent, and the copy deleted."""
        import base64
        import pathlib
        db = self.server.lookup_component("database")
        path = pathlib.Path(db.get_backup_dir()) / f"elyir-bench-export-{uuid.uuid4().hex[:8]}.db"
        try:
            await db.backup_database(path)
            run = getattr(self.eventloop, "run_in_thread", None)
            data = (await run(export_database, str(path))) if run else export_database(str(path))
        except Exception as e:
            logging.exception("intent: exporting the database failed")
            raise self.server.error(f"This printer couldn't send its history: {e}", 500)
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        return {"name": self.printer_name, "bytes": len(data), "database": base64.b64encode(data).decode()}

    def _publish(self, force: bool = False) -> None:
        intent = self._current()
        for event in self.notifier.observe(intent):
            self.events.append(event)
            logging.info("intent: notify %s: %s", event["kind"], event["title"])
            self.server.send_event("printer_intent:event", event)
        # Ignore the clock so a quiet printer doesn't push once a second.
        key = json.dumps({k: v for k, v in intent.items() if k != "now"}, sort_keys=True, default=str)
        if force or key != self._last_published:
            self._last_published = key
            self.server.send_event("printer_intent:update", intent)

    # ---- API ----------------------------------------------------------------

    async def _handle_get_intent(self, web_request: WebRequest) -> Dict[str, Any]:
        return self._current()

    async def _handle_events(self, web_request: WebRequest) -> Dict[str, Any]:
        boot = self.notifier.boot
        if web_request.get_str("boot", boot) != boot:
            return {"boot": boot, "events": []}
        after = web_request.get_int("after", 0)
        return {"boot": boot, "events": [e for e in self.events if e["id"] > after]}

    async def _handle_setup(self, web_request: WebRequest) -> Dict[str, Any]:
        return await self._setup()

    async def _handle_check_print(self, web_request: WebRequest) -> Dict[str, Any]:
        """Before starting a file: is what it needs loaded? Never starts anything."""
        filename = web_request.get_str("filename")
        try:
            fm: FileManager = self.server.lookup_component("file_manager")
            meta = fm.get_file_metadata(filename)
        except Exception:
            meta = None
        changes = await self._colour_changes(filename)
        if changes:
            meta = dict(meta or {}, colour_changes=changes)
            self.tracker.note_check(filename, meta)
        return engine.check_print(filename, meta, self.tracker.spools())

    async def _handle_action(self, web_request: WebRequest) -> Dict[str, Any]:
        action = web_request.get_str("action")
        args = web_request.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        # Who pressed it, so a stop can always be traced (an untraceable Stop now on workshop, 3 October 2026)
        logging.info("intent: action %s %s from %s", action, json.dumps(args or {}, default=str),
                     who_sent(web_request, web_request.get_str("source", "")))
        if action in SCREEN_ACTIONS:
            if not self._can_switch_screen():
                raise self.server.error("This printer's screen can only show Elyir Bench.", 400)
            if not self._screen_switching:
                self._trial_until = None   # Care's choice ends a trial
                self.eventloop.create_task(self._switch_screen(SCREEN_ACTIONS[action]))
            return {"ok": True, "action": action, "ran": [action], "intent": self._current()}
        if action in SETUP_ACTIONS:
            await self._setup_action(action, args if isinstance(args, dict) else {})
            self._publish(force=True)
            return {"ok": True, "action": action, "ran": [action], "intent": self._current(), "setup": await self._setup()}
        if action in ROLE_ACTIONS:
            self._role_action(action)
            return {"ok": True, "action": action, "ran": [action], "intent": self._current(), "bring": self._bring_view()}
        if action in BRING_ACTIONS:
            self._bring_action(action, args if isinstance(args, dict) else {})
            return {"ok": True, "action": action, "ran": [action], "intent": self._current(), "bring": self._bring_view()}
        if action in PROFILE_ACTIONS:
            await self._profile_action(action, args if isinstance(args, dict) else {})
            return {"ok": True, "action": action, "ran": [action], "intent": self._current(), "profile": self._profile_view()}
        if action in ("care_done", "care_later") and care is not None:   # records, not printer commands
            await self._care_action(action, str((args or {}).get("id", "")))
            self._publish(force=True)
            return {"ok": True, "action": action, "ran": [action], "intent": self._current()}
        plan = engine.plan_action(action, args, self.tracker)
        if not plan:
            raise self.server.error(f"Unknown action '{action}'", 400)
        ran = []
        for kind, payload in plan:
            await self._run(kind, payload)
            ran.append(kind)
        self._publish(force=True)
        return {"ok": True, "action": action, "ran": ran, "intent": self._current()}

    # ---- changing filament by hand: the engine says what to send, this sends it ----

    def _drive(self) -> None:
        if self.tracker.klippy_state != "ready":
            return
        for kind, script in self.tracker.work():
            if kind == "macro":
                self.eventloop.create_task(self._run_change_macro(script))
            elif kind == "unit_macro":
                self.eventloop.create_task(self._run_unit_step(script))
            elif kind == "unit":
                self.eventloop.create_task(self._run_unit(script))
            elif kind in ("unit_scan", "unit_install", "unit_putback"):
                self._unit_start(kind, script)
            else:
                self.eventloop.create_task(self._run_gcode_logged(script))

    async def _run_gcode_logged(self, script: str) -> None:
        try:
            await self.klippy_apis.run_gcode(script)
        except Exception:
            logging.exception("intent: %s failed", script.splitlines()[0])

    async def _run_change_macro(self, script: str) -> None:
        """A step of the change routine that takes a while (unload, load, purge)."""
        try:
            await self.klippy_apis.run_gcode(script)
            self.tracker.change_done(None)
        except Exception as e:
            logging.info("intent: changing filament stopped: %s", e)
            self.tracker.change_done(str(e) or e.__class__.__name__)
        self._drive()
        self._publish(force=True)

    async def _run_swap(self, payload: Dict[str, Any]) -> None:
        try:
            cmds = self.tracker.unit_commands()
            step = engine.swap_gcode(payload, cmds)
            if cmds is not None and cmds.kind == "unit":
                await self.units_link.call(step, timeout=CHANGE_TIMEOUT)
            else:
                await self.klippy_apis.run_gcode(step)
            await _swap_done(self, None)
        except Exception as e:
            logging.info("intent: spool change failed: %s", e)
            await _swap_done(self, str(e) or e.__class__.__name__)

    def _check_power(self) -> None:
        """Turn off or Restart (design/power/): once the nozzle is cool enough, go."""
        kind = self.tracker.power_due()
        if kind:
            self.tracker.power_going()
            self._publish(force=True)
            self.eventloop.create_task(self._power_go(kind))

    async def _power_go(self, kind: str) -> None:
        # the screens see "Now" before the socket closes; the panel's last frame is the boot screen's
        await asyncio.sleep(2.)
        try:
            provider = self.server.lookup_component("machine").get_system_provider()
            logging.info("intent: %s the Pi", "turning off" if kind == "off" else "restarting")
            if kind == "off":
                await provider.shutdown()
            else:
                await provider.reboot()
        except Exception as e:
            # e.g. a card without Moonraker's polkit rules: "DBusError: Permission denied"
            logging.exception("intent: %s failed", "turning off" if kind == "off" else "restarting")
            self.tracker.power_failed(str(e) or e.__class__.__name__)
            self._publish(force=True)

    async def _restart_after_stop(self) -> None:
        """Bring Klipper back after Stop now. A command that was running when the emergency
        stop landed can keep holding Klipper's gcode lock (an eddy probe in the middle of QGL
        does), and FIRMWARE_RESTART then waits behind it for ever. Restarting the service
        ends that command; the boards are still stopped, so a FIRMWARE_RESTART follows."""
        try:
            await asyncio.sleep(1.)
            await self.server.lookup_component("machine").do_service_action("restart", "klipper")
            kc = self.server.lookup_component("klippy_connection")
            seen_down = False
            for _ in range(60):
                await asyncio.sleep(1.)
                state = kc.state.name.lower()
                if state in ("disconnected", "startup"):
                    seen_down = True
                elif seen_down:
                    break
            if kc.state.name.lower() != "ready":
                await self.klippy_apis.do_restart("FIRMWARE_RESTART")
        except Exception:
            logging.exception("intent: restarting Klipper after Stop now failed")
        self._publish(force=True)

    async def _run(self, kind: str, payload: Any) -> None:
        P = engine.ActionPlan
        if kind == P.PAUSE:
            await self.klippy_apis.pause_print()
        elif kind == P.RESUME:
            await self.klippy_apis.resume_print()
        elif kind == P.CANCEL:
            await self.klippy_apis.cancel_print()
        elif kind == P.GCODE:
            await self.klippy_apis.run_gcode(str(payload))
        elif kind == P.UNIT:
            await self.units_link.call(payload, timeout=CHANGE_TIMEOUT if payload.get("op") == "change_tool" else 150)
        elif kind == P.EMERGENCY_STOP:
            self.tracker.begin_stop()
            self._publish(force=True)
            await self.klippy_apis.emergency_stop()
            self.eventloop.create_task(self._restart_after_stop())
        elif kind == P.FIRMWARE_RESTART:
            await self.klippy_apis.do_restart("FIRMWARE_RESTART")
        elif kind == P.START_LAST:
            filename = (self.tracker.status.get("print_stats") or {}).get("filename")
            if filename:
                self.tracker.acknowledge_finished()
                await self.klippy_apis.start_print(filename)
        elif kind == P.SWAP:
            # A tool change takes minutes: start it and let the intent show its progress
            self.tracker.begin_swap(payload["to"], payload["from"], payload["purge"])
            self.eventloop.create_task(self._run_swap(payload))
        elif kind == P.ACK_SWAP:
            self.tracker.ack_swap()
        elif kind == P.ACK_HEAD:
            await self._resync()   # if it was only our copy that was wrong, that settles it
            self.tracker.ack_head()
        elif kind == P.KLIPPY_RESTART:
            await self.klippy_apis.do_restart("RESTART")
        elif kind == P.START_FILE:
            self.tracker.acknowledge_finished()
            await self.klippy_apis.start_print(str(payload))
        elif kind == P.ACK_FINISHED:
            self.tracker.acknowledge_finished()
        elif kind == P.CHANGE:
            self.tracker.change_input(payload)
            self._drive()
        elif kind == P.OUTAGE:
            self.tracker.outage_input(payload)
        elif kind == P.LOST:
            self.tracker.lost_input(payload)
        elif kind == P.POWER:
            self.tracker.power_input(payload)
        elif kind == P.WARM:
            self.tracker.warm_input(payload)
            self._drive()
        elif kind == P.HANDS:
            self.tracker.hands_input(payload)
            self._drive()
        elif kind == P.LIGHT:
            self.tracker.light_input(payload)
            if self.tracker.light_choice_dirty:
                await self._save_light()
            self._drive()
        elif kind == P.FIRST_LAYER:
            self.tracker.first_layer_input(payload)
            self._drive()
        elif kind == P.SLOT:
            self.tracker.slot_input(payload)
            self._drive()
        elif kind == P.UNIT_CHECK:
            self.tracker.unit_check_input(payload)
            self._drive()
        elif kind == P.UNIT_SETUP:
            self.tracker.unit_setup_input(payload)
            self._drive()
        elif kind == P.COLOUR:
            self.tracker.colour_input(payload)
            if self.tracker.colour_plan_dirty:
                await self._save_colour_plan()   # stored before the print it's for starts
            self._drive()
        elif kind == P.REMEMBER_SPOOL:
            self.tracker.remember_spool(payload.get("color"), payload.get("material"))
            await self._save_spool()
        elif kind == P.NONE:
            pass


def export_database(path: str) -> bytes:
    """A copy of Moonraker's database without what's this printer's alone: logins and the API key (a table, or a
    namespace in older Moonrakers), and how many phones listen. Vacuumed, so none of it stays in free pages."""
    import sqlite3
    con = sqlite3.connect(path)
    try:
        with con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "authorized_users" in tables:
                con.execute("DELETE FROM authorized_users")
            if "namespace_store" in tables:
                con.execute("DELETE FROM namespace_store WHERE namespace='authorized_users' "
                            "OR (namespace='elyir-bench' AND key='phones')")
        con.execute("VACUUM")
    finally:
        con.close()
    with open(path, "rb") as f:
        return f.read()


def write_profile(home: str, printer: Dict[str, Any], presets: Dict[str, Dict[str, Any]]) -> None:
    """A learned profile into the slicer's folder: presets/0-learned/ replaced whole (a profile used before leaves
    nothing behind), then printer.json, each swapped in at once."""
    folder = os.path.join(home, "presets")
    os.makedirs(folder, exist_ok=True)
    new = os.path.join(folder, f".{LEARNED}-new")
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    for name, preset in presets.items():
        with open(os.path.join(new, name), "w") as f:
            json.dump(preset, f, indent=1, sort_keys=True)
    old = os.path.join(folder, LEARNED)
    shutil.rmtree(old, ignore_errors=True)
    os.replace(new, old)
    tmp = os.path.join(home, "printer.json.tmp")
    with open(tmp, "w") as f:
        json.dump(printer, f, indent=2)
        f.write("\n")
    os.replace(tmp, os.path.join(home, "printer.json"))


async def _swap_done(component: "PrinterIntent", error: Optional[str]) -> None:
    component.tracker.end_swap(error)
    component._drive()
    component._publish(force=True)


def load_component(config: ConfigHelper) -> PrinterIntent:
    return PrinterIntent(config)
