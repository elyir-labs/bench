"""
Elyir Bench intent engine.

Turns raw Klipper status into one object a person can act on:

    { state, phase, headline, detail, actions, steps, job, spools, ... }

This module has no Moonraker or Klipper imports. It runs unchanged in three
places: unit tests, the laptop simulator, and the Moonraker component on the
printer. Every UI renders this object and contains no printer logic of its own.

States (the only seven a person ever sees):
    setup       a fresh card: Klipper has no printer.cfg yet, so the printer needs a config once
    ready       nothing is happening, printer is available
    preparing   heating, soaking, leveling, or starting up
    printing    laying down plastic
    needs_you   paused for a person: runout, colour change, a check
    finished    print complete, cooling to release temperature
    problem     something stopped the printer; the reason in plain words
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional


def _sibling(name: str):
    """One of our modules from this file's directory. The component loads this file by path, so it isn't on
    sys.path and neither are its neighbors."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"{name}.py not found next to {__file__}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


filament_units = _sibling("filament_units")

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------
# Copy. Every sentence a person reads lives here, nowhere else.
# --------------------------------------------------------------------------

# Klipper / Moonraker error text -> (headline, detail, phase)
# Matched case-insensitively as substrings, first match wins.
ERROR_TRANSLATIONS: List[tuple] = [
    ("not heating at expected rate",
     "The nozzle or bed isn't heating properly.",
     "I stopped the print and switched the heaters off to stay safe. "
     "Check the nozzle for damage or a loose wire, then try again. "
     "If it happens twice, something needs replacing.",
     "heater_fault"),
    ("thermal runaway",
     "A heater got hotter than it should.",
     "Everything is switched off and safe. Let it cool, check the nozzle and "
     "bed wiring, then try again.",
     "heater_fault"),
    ("adc out of range",
     "A temperature sensor stopped reading.",
     "Heaters are off. A sensor wire is probably loose or broken. "
     "Check the hotend and bed wiring, then try again.",
     "sensor_fault"),
    ("move out of range",
     "The print asked me to move somewhere I can't reach.",
     "It was probably sliced for a different printer. Everything is safe. "
     "Re-slice it for this printer and try again.",
     "bad_file"),
    ("must home axis first",
     "I need to find my home position first.",
     "That's an easy one. Try again and I'll home before I move.",
     "not_homed"),
    ("probe triggered prior to movement",
     "The bed sensor thinks something is touching it.",
     "Clear the bed and make sure nothing is under the print head, then try again.",
     "probe"),
    ("probe samples exceed tolerance",
     "I couldn't get a steady reading from the bed.",
     "The bed might be dirty or the nozzle might have plastic on it. "
     "Wipe both and try again.",
     "probe"),
    ("timer too close",
     "The print head lost contact for a moment.",
     "Try again. If it keeps happening, the cable to the head needs a look.",
     "mcu"),
    ("lost communication with mcu",
     "I lost contact with part of the printer.",
     "Usually a loose cable or a power blip. Try again. If it repeats, "
     "check the cable to the print head.",
     "mcu"),
    ("mcu 'ebbcan'",
     "The print head lost contact for a moment.",
     "Try again. If it keeps happening, the cable to the head needs a look.",
     "mcu"),
    ("unable to connect",
     "I can't reach part of the printer's electronics.",
     "Check the cables from the main board, then try again.",
     "mcu"),
    ("shutdown due to",
     "Something stopped the printer.",
     "Everything is safe. Try again, and if it repeats the full details are behind Advanced.",
     "generic"),
    ("emergency stop",
     "Emergency stop was pressed.",
     "Everything is off. When you're ready, try again.",
     "estop"),
    ("ace",
     "The filament unit ran into a problem.",
     "Check that filament is feeding freely from the spool, then try again.",
     "ace"),
]

# A fresh card (design/printer-setup/, A; docs/bring-it-over.md): Klipper starts with no printer.cfg and says
# "Unable to open config file /home/pi/printer_data/config/printer.cfg". That isn't a problem to fix but a printer
# to set up, so it has its own state. The screens show Now the printer itself (board a-start).
NO_CONFIG = re.compile(r"unable to open config file\s+\S*printer\.cfg", re.I)
SETUP_HEADLINE = "Now the printer itself."
SETUP_DETAIL = "It can't see how they're wired, so it needs a config, once."
SETUP_DETAIL_FOUND = "It found these. " + SETUP_DETAIL
SETUP_DETAIL_NOTHING = "It can't see how the printer is wired, so it needs a config, once."

FALLBACK_PROBLEM = (
    "Something stopped the print and I'm not sure why.",
    "Everything is safe. Try again, and the full details are behind Advanced.",
    "generic",
)

# M117 messages from PRINT_START -> preparing step.
# Order matters: a later step marks all earlier steps done.
PREP_STEPS: List[Dict[str, Any]] = [
    {"id": "warming", "label": "Warming the bed", "match": ["pre-heating", "preheating", "heating bed", "warming"]},
    {"id": "soaking", "label": "Letting the bed settle", "match": ["heat-soak", "heat soak", "soaking"]},
    {"id": "leveling", "label": "Leveling", "match": ["homing", "leveling", "levelling", "calibrating mesh", "meshing", "probing"]},
    {"id": "heating", "label": "Heating the nozzle", "match": ["heating toolhead", "heating nozzle", "heating extruder"]},
]
PRINT_STARTED_MARKERS = ["printing, good luck", "printing..."]
# A start routine that names no step (Anycubic's on a Kobra, a slicer's own start G-code) is followed by what the
# printer does: homing or a bed at temperature is leveling, and the nozzle's target reaching the file's first-layer
# temperature (this, when the file doesn't say) is heating it to print. A Kobra heats to 170° to clean the nozzle first.
PRINT_NOZZLE_MIN = 180.0

# The shared PRINT_START (kept with the printer's Klipper config, not in this repository) pauses the file while
# it gets ready, so Cancel works at once, and names its step in
# gcode_macro _PRINT_START.stage. A paused print with a stage is getting ready, not
# waiting for anyone.
PRINT_START_STAGES = {
    "home_first": "warming", "warming": "warming", "soaking": "soaking",
    "home": "leveling", "qgl": "leveling", "tap": "leveling", "mesh": "leveling", "home_again": "leveling",
    "heating": "heating", "prime": "heating", "resume": "heating",
    "own": "leveling",   # Elyir Bench's start macro: the person's own start G-code is running (below)
}

# Elyir Bench's own start macro, for a printer someone else set up (printer/klipper/elyir-bench.cfg,
# docs/start-macro.md). ELYIR_BENCH_PRINT_START runs before the person's own start G-code: it heats while
# the file is paused (warming, soaking, the same as the shared PRINT_START's), then their start G-code
# runs as one block (own), and ELYIR_BENCH_PRINT_START_DONE clears the stage: the print has started. Its
# state has its own name so it never merges with anyone's _PRINT_START.
ELYIR_BENCH_START = "gcode_macro _ELYIR_BENCH_PRINT_START"
ELYIR_BENCH_START_SETTINGS = "gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS"
OWN_START_LABEL = "Your start G-code"   # the leveling step, while their start G-code runs

# The picture in the ring while getting ready (design/now-illustrated/, A) draws one of these.
# The shared PRINT_START's stage, folded to the drawings there are; the second line under the
# step says the same thing in words. Older PRINT_STARTs only say it in M117 messages.
ART_STAGES = {
    "home_first": "home", "warming": "warming", "soaking": "soaking", "home": "home", "qgl": "level",
    "tap": "home", "mesh": "mesh", "home_again": "home", "heating": "heating", "prime": "prime", "resume": "prime",
}
ART_FROM_MESSAGE = [("calibrating mesh", "mesh"), ("meshing", "mesh"), ("bed mesh", "mesh"),
                    ("leveling", "level"), ("levelling", "level"), ("homing", "home"), ("purg", "prime"),
                    ("prim", "prime")]
ART_FROM_STEP = {"warming": "warming", "soaking": "soaking", "leveling": "home", "heating": "heating"}
ART_WORDS = {"home": "Finding home", "level": "Squaring the gantry", "mesh": "Mapping the bed",
             "prime": "Priming the nozzle"}
# Where the head is matters only while it's moving about the bed for a reason; otherwise the
# picture doesn't use it and the intent doesn't change (or get pushed) as it moves.
ART_HEAD_STAGES = ("home", "level", "mesh", "prime")
MESH_CELLS = 5   # the ring draws the bed as 5 x 5; a cell lights when the head has been over it
# Klipper's quad_gantry_level / z_tilt after each pass: "Retries: 1/5 Probed points range: 0.0350 tolerance: 0.0075"
LEVEL_RE = re.compile(r"range:\s*([\d.]+)\s*tolerance:\s*([\d.]+)")

# Bed temperature at which a part lifts off cleanly, by material.
RELEASE_TEMP = {"PLA": 35.0, "PETG": 40.0, "ABS": 50.0, "ASA": 50.0, "TPU": 35.0, "NYLON": 45.0}
DEFAULT_RELEASE_TEMP = 40.0

CANCELLED_NOTE_SECONDS = 300
STOP_RESTART_SECONDS = 120   # Stop now: emergency stop + restart; give up showing "Stopping" after this
# Turning the printer off (design/power/, A): the hot end's fan is a Klipper heater_fan, on above 50° (its
# heater_temp on all three printers), and it stops when the Pi does. So Turn off and Restart wait for the
# nozzle to drop below it, heaters off and fans on, unless someone says now. Past the longest wait, it goes.
POWER_COOL_TEMP = 50.0
POWER_MAX_WAIT_SECONDS = 15 * 60
NEEDS_YOU_HOLD_SECONDS = 20 * 60
OFFLINE_GRACE_SECONDS = 60
STARTUP_SLOW_SECONDS = 90   # a normal Klipper start is well under this; longer usually means a board isn't answering


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _clock(ts: float) -> str:
    """'4:10 pm' style, for headlines."""
    s = time.strftime("%I:%M %p", time.localtime(ts)).lower()
    return s.lstrip("0")


def _pretty_job_name(filename: Optional[str]) -> str:
    if not filename:
        return ""
    name = filename.rsplit("/", 1)[-1]
    name = re.sub(r"\.(gcode|gco|g)$", "", name, flags=re.I)
    name = re.sub(r"^\[[^\]]*\][_ ]*", "", name)          # Orca plate prefix: "[a]_part"
    # Drop slicer suffixes like _0.2mm_PLA_MK4_1h23m, _ASA_41m9s, _PLA_15m
    name = re.sub(r"_(\d+(\.\d+)?mm|PLA|PETG|ABS|ASA|TPU|NYLON|PC|PA|\d+h\d*m?\d*s?|\d+m\d*s?|\d+s|MK3S?|MK4S?|MINI|XL|X1C?|P1[SP]|A1|VORON)(?=_|$)", "", name, flags=re.I)
    # A plate from Elyir Bench's slicer (design/plate/): "_x25" copies, "_1of2" which plate
    name = re.sub(r"_x(\d+)(?=_|$)", r" × \1", name)
    name = re.sub(r"_(\d+)of(\d+)(?=_|$)", r" (plate \1 of \2)", name)
    name = name.replace("_", " ").replace("-", " ").strip()
    return name[:1].upper() + name[1:] if name else filename


def _part_label(name: str) -> str:
    """Klipper's object name, for people: "p0c7__buildplate_bushing_open.stl_id_7_copy_0" (Elyir Bench's slicer)
    or "vent.stl_id_0_copy_0" (Orca's) -> "Buildplate bushing open", "Vent"."""
    n = re.sub(r"_id_\d+_copy_\d+$", "", name)
    n = re.sub(r"^p\d+(?:c\d+)?__", "", n)
    n = re.sub(r"\.(stl|obj|step|stp|3mf)$", "", n, flags=re.I)
    n = re.sub(r"^\[[^\]]*\][_ ]*", "", n)
    n = re.sub(r"[_-]+", " ", n).strip()
    return (n[:1].upper() + n[1:]) if n else name


_ORDINAL = ["", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


def _where_words(row: int, rows: int, col: int, cols: int) -> str:
    """"front row, far left": where a part is, seen from the front of the printer."""
    if rows == 1:
        r = ""
    elif row == 0:
        r = "front row"
    elif row == rows - 1:
        r = "back row"
    elif rows % 2 == 1 and row == rows // 2:
        r = "middle row"
    else:
        r = f"{_ORDINAL[row] if row < len(_ORDINAL) else str(row + 1) + 'th'} row from the front"
    if cols == 1:
        c = "on its own" if rows == 1 else ""
    elif col == 0:
        c = "far left"
    elif col == cols - 1:
        c = "far right"
    elif cols % 2 == 1 and col == cols // 2:
        c = "middle"
    elif col < cols / 2:
        c = f"{_ORDINAL[col]} from left"
    else:
        c = f"{_ORDINAL[cols - 1 - col]} from right"
    return ", ".join(x for x in (r, c) if x) or "on its own"


def _used_extruders(metadata: Dict[str, Any]) -> List[int]:
    """Slicers list every filament in the profile; the weights say which were used."""
    weights = metadata.get("filament_weights")
    if isinstance(weights, list) and any(isinstance(w, (int, float)) and w > 0 for w in weights):
        return [i for i, w in enumerate(weights) if isinstance(w, (int, float)) and w > 0]
    colors = metadata.get("filament_colors") or []
    return list(range(len(colors)))


def job_colors(metadata: Dict[str, Any]) -> List[str]:
    colors = metadata.get("filament_colors") or []
    out = []
    for i in _used_extruders(metadata):
        c = _hex_color(colors[i]) if i < len(colors) else None
        if c:
            out.append(c)
    return out


def job_material(metadata: Dict[str, Any]) -> Optional[str]:
    raw = metadata.get("filament_type")
    if not raw:
        return None
    types = [t.strip() for t in str(raw).split(";")]
    used = _used_extruders(metadata)
    for i in used:
        if i < len(types) and types[i]:
            return types[i].upper()
    return types[0].upper() if types and types[0] else None


def _best_thumbnail(filename: Optional[str], metadata: Dict[str, Any]) -> Optional[str]:
    """Largest slicer preview, as a path under the gcodes root (Moonraker serves it
    at /server/files/gcodes/<path>)."""
    if not filename:
        return None
    thumbs = metadata.get("thumbnails") or []
    best = None
    for t in thumbs:
        if not isinstance(t, dict) or not t.get("relative_path"):
            continue
        area = int(t.get("width") or 0) * int(t.get("height") or 0)
        if best is None or area > best[0]:
            best = (area, t["relative_path"])
    if best is None:
        return None
    folder = filename.rsplit("/", 1)[0] if "/" in filename else ""
    return f"{folder}/{best[1]}" if folder else best[1]


_hex_color = filament_units.hex_color


def _color_distance(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 999.0
    ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def _color_name(hex_color: Optional[str]) -> str:
    """Friendly colour names for headlines, by hue. Good enough for 'the orange one'."""
    if not hex_color:
        return "that"
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    sat = 0 if mx == 0 else (mx - mn) / mx
    if mx < 0.24:
        return "Black"
    if sat < 0.15:
        return "White" if mx > 0.86 else "Gray"
    if mx == r:
        hue = (60 * ((g - b) / (mx - mn))) % 360
    elif mx == g:
        hue = 60 * ((b - r) / (mx - mn)) + 120
    else:
        hue = 60 * ((r - g) / (mx - mn)) + 240
    if 15 <= hue < 40 and mx < 0.6:
        return "Brown"
    for limit, name in ((15, "Red"), (40, "Orange"), (70, "Yellow"), (165, "Green"),
                        (195, "Teal"), (255, "Blue"), (315, "Purple"), (345, "Pink"), (360, "Red")):
        if hue < limit:
            return name
    return "Red"


def _translate_error(text: str) -> tuple:
    low = (text or "").lower()
    for needle, headline, detail, phase in ERROR_TRANSLATIONS:
        if needle in low:
            return headline, detail, phase
    return FALLBACK_PROBLEM


def _action(aid: str, label: str, primary: bool = False, style: str = "default", hold: bool = False,
            **args) -> Dict[str, Any]:
    """hold: the screen makes a person press and hold it, so a brush against the panel can't end a print."""
    a: Dict[str, Any] = {"id": aid, "label": label, "primary": primary, "style": style}
    if hold:
        a["hold"] = True
    if args:
        a["args"] = args
    return a


# --------------------------------------------------------------------------
# Before a print: is what the file needs actually loaded?
# --------------------------------------------------------------------------

# Materials a person picks from when a spool has no tag, in the order they're offered.
MATERIALS = ["PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC"]
# Nozzle temperature the filament unit uses for a material when a spool is entered by hand.
MATERIAL_TEMPS = {"PLA": 210, "PETG": 240, "ABS": 250, "ASA": 255, "TPU": 225, "PA": 270, "PC": 270}
COLOR_MATCH = 70   # RGB distance under which two colours count as the same filament
FLAPPING_WINDOW = 120      # seconds of USB history kept per filament unit
RECENT_SPOOLS = 4          # spools remembered on a printer without a unit, as quick answers
HEAD_MISMATCH_SECONDS = 10    # head sensor and loaded slot must disagree this long before saying so
SWAP_QUIET_SECONDS = 30       # ...and not right after a swap, while filament is still moving
# Console lines from the filament unit's tool change, in order, mapped to steps people see.
SWAP_STEPS = [
    ("unload", ["unloading tool"]),
    ("feed", ["loading tool", "feeding from gate"]),
    ("nozzle", ["feeding to nozzle", "feeding to toolhead"]),
    ("clean", ["poop macro"]),
]
FLAPPING_RECONNECTS = 3    # reconnects within the window that mean a unit won't stay connected

# Changing filament by hand (design/change-filament/, direction B). The printer does the work and
# Now asks only for what a person has to do. Steps a person does are the "you" steps.
CHANGE_LABELS = {"warm": "Warming up", "unload": "Taking out {out}", "pull": "Pull it out",
                 "push": "Push in the new one", "load": "Pushing it through", "check": "Check it"}
CHANGE_YOU = ("pull", "push", "check")
CHANGE_ART = {"warm": "heat", "unload": "out", "pull": "pull", "push": "push", "load": "purge",
              "check": "purge", "resume": "done"}
DEFAULT_CHANGE_TEMP = 220         # nozzle temperature when nothing says what's coming out
KEEP_WARM_SECONDS = 10 * 60       # after a change while idle, in case a print comes next
CHANGE_NOTIFY_SECONDS = 30        # a "your turn" step waits this long before telling the phone

# Everything a slot can do (design/slots/, direction B). Swapping a spool takes it out of the head if
# it's there, pulls it back into its slot until the unit says the slot is empty, then a person swaps
# the spool and pushes the new end in, which the unit's slot sensor notices.
SLOT_LABELS = {"unload": "Taking {out} out of the head", "pullback": "Pulling it back to its spool",
               "swap": "Swap the spool", "what": "Say what it is"}
SLOT_YOU = ("swap", "what")
SLOT_ART = {"unload": "out", "pullback": "back", "swap": "insert", "what": "still"}
PULLBACK_STEP_MM = 300        # one pull; the slot reads empty once the tip is past the unit's sensor
PULLBACK_MAX_MM = 2400        # longer than any tube on these printers; after that a person pulls the rest
MOVE_STEPS_MM = (10, 50, 200)  # Move filament: 1, 5 or 20 cm a tap
PULL_IN_MM = 100              # "It won't catch? Pull it in"
# Drying: one dryer per unit, so the most delicate material inside sets the heat and the slowest the time.
DRY_PRESETS = {"PLA": (45, 2), "PETG": (55, 4), "TPU": (50, 3), "ABS": (60, 4), "ASA": (60, 4),
               "PA": (65, 6), "PC": (70, 6)}
DRY_UNKNOWN = (45, 4)         # nothing says what's inside: gentle, and long enough for anything
DRY_MAX_DEFAULT = 55          # KlipperACE's own default for max_dryer_temperature
DRY_HOURS = (1, 12)           # what the sheet offers
DRY_DONE_MINUTES = 3          # a dryer that stops with this little left finished, rather than being stopped
CARRIED_NOTE_SECONDS = 15 * 60   # "Carried on with slot 6" stays on Now this long unless dismissed
ENDLESS_RE = re.compile(r"endless spool: t(\d+) empty, switching to t(\d+)")

# Colour changes on a printer with a filament unit (design/colour-change/, C first, A as the fallback). An M600
# in a file sliced for one spool is planned at Print onto a loaded spool and the unit switches at that layer
# with nobody there. Only what can't be planned pauses, and the pause says why. One-spool printers keep the
# change routine above.
AUTO_PURGE_MM = 60            # a planned switch pushes this much more through instead of asking for a check
MORE_PURGE_MM = 30            # "Push more through"
# Swap the spool in a FULL slot at the pause (pull it back with another spool in the head). Built, but off until
# the hand test on Workshop passes (AGENTS.md, colour changes): with it off the pause doesn't offer it.
SLOT_SWAP_WHILE_PAUSED = False
COLOUR_MARK_LINES = 5         # a COLOR_CHANGE marker this many lines from an M600 names its colour
COLOUR_PLAN_FRESH_SECONDS = 15 * 60   # a plan is for the print started right after it, not the same file days later
COLOUR_PLAN_MAX = 50          # colour changes in one file, at most
CHECKED_FILES_KEPT = 20       # files whose colour changes the Print sheet has shown, for checking the plan sent back
SWITCH_STEPS = ("unload", "feed", "nozzle", "clean")   # the unit's own tool change, as SWAP_STEPS reports it
_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})(?![0-9A-Fa-f])")
_STATS_LAYER_RE = re.compile(r"CURRENT_LAYER=(\d+)", re.I)

# Warming up before a print (design/warm-up/, direction D). The bed for the material, the chamber
# for the ones that want one (up to the printer's own PRINT_START limit), the nozzle just warm.
WARM_BED = {"PLA": 60, "PETG": 80, "TPU": 50, "ABS": 105, "ASA": 105, "PA": 90, "PC": 110}
WARM_CHAMBER_MATERIALS = ("ABS", "ASA", "PA", "PC")
WARM_NOZZLE = 150                 # warm enough to print soon, cool enough not to ooze
WARM_HOLD_SECONDS = 30 * 60       # warm and nothing printed: heaters off then
WARM_CHAMBER_GIVE_UP = 20 * 60    # the chamber may never get there; PRINT_START gives up after the same
# A printer reached over the network (a Kobra in LAN mode is asked every 3 s) reports the new targets late
WARM_TARGET_GRACE = 30
WARM_BED_RATE = 0.6               # °C/s a heated bed gains, roughly, for "about N minutes"
WARM_CHAMBER_RATE = 1.0 / 60      # °C/s an enclosure gains from the bed, roughly

# Move and heat by hand (design/hands-on/, C): jobs first (Get at the bed, Clean the nozzle, Heat the
# nozzle, Let go of the motors), then the controls. Never while printing, at the printer only (door.py).
HANDS_IDLE_SECONDS = 15 * 60      # heat set by hand, untouched this long: off
HANDS_AIM_SECONDS = 5             # taps closer together than this add up, before live_position catches up
HANDS_CLEAR_Z = 150               # Get at the bed: this high, or the printer's top less a margin
HANDS_CLEAN_Z = 50                # Clean the nozzle: room for a brush under it
HANDS_Z_FLOOR = 5                 # the controls never take Z lower than this
HANDS_XY_SPEED = 6000             # mm/min
HANDS_Z_SPEED = 900
HANDS_STEPS = (1, 10, 50)
HANDS_PRESETS = ("PLA", "PETG", "ABS")
HANDS_NOZZLE_MAX = 300
HANDS_BED_MAX = 120

# First layer: squish more, squish less (design/first-layer/, B). While the first layers go down a
# person nudges the nozzle further from the bed or closer to it; at the end they can keep it. Kept
# means [save_variables]: first_layer_z (mm, + is further), first_layer_against ("scan" or "tap"),
# first_layer_history (the values before, for "Back to how it was") and first_layer_at. The shared
# PRINT_START applies first_layer_z as its last step when it was kept against the same way the
# print found Z. Never written into the probe: tap measures the probe again every print.
SQUISH_STEP = 0.025       # mm per press
SQUISH_LAYERS = 3         # offered on layers 1 to 3; after that a nudge can't save anything
SQUISH_LOW_Z = 1.0        # without layer numbers from the slicer, the first layers are below this (mm)
SQUISH_LIMIT = 0.5        # mm either way from where the printer finds Z; PRINT_START won't apply more
FIRST_LAYER_HISTORY = 5   # kept values remembered for "Back to how it was"


def squish_words(mm: float) -> str:
    """A first-layer adjustment in words, the way it's shown first; the number goes beside it."""
    a = abs(mm)
    if a < SQUISH_STEP / 2:
        return "As the printer finds it"
    way = "further" if mm > 0 else "closer"
    if a <= 0.075:
        return f"A touch {way}"
    if a <= 0.3:
        return f"A little {way}"
    if a <= 0.4:
        return f"Quite a bit {way}"
    return f"A lot {way}"


def squish_mm(mm: float) -> str:
    """+0.300 mm / −0.050 mm (a real minus sign) / 0.000 mm."""
    if abs(mm) < 0.0005:
        return "0.000 mm"
    return ("+" if mm > 0 else "−") + f"{abs(mm):.3f} mm"


def _material_key(m: Optional[str]) -> Optional[str]:
    """PLA+ and PLA are the same thing to a person; PETG-CF is not PETG."""
    if not m:
        return None
    return str(m).replace("+", "").strip().upper() or None


def _spool_name(color: Optional[str], material: Optional[str]) -> Optional[str]:
    """'Black PETG', 'PETG' or 'Black'; None when nothing is known."""
    mat = str(material).upper() if material else None
    if mat:
        return f"{_color_name(color)} {mat}" if color else mat
    return _color_name(color) if color else None


def job_filaments(metadata: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    """What the file will use, one entry per used filament: colour and material."""
    colors = metadata.get("filament_colors") or []
    types = [t.strip() for t in str(metadata.get("filament_type") or "").split(";")]
    out, seen = [], set()
    for i in _used_extruders(metadata):
        color = _hex_color(colors[i]) if i < len(colors) else None
        material = _material_key(types[i] if i < len(types) else (types[0] if len(types) == 1 else None))
        if not color and not material:
            continue
        key = (color, material)
        if key not in seen:
            seen.add(key)
            out.append({"color": color, "material": material})
    return out


def _spool_matches(need: Dict[str, Optional[str]], s: Dict[str, Any]) -> bool:
    if s.get("status") not in ("ready", "low"):
        return False
    if need["color"] and _color_distance(need["color"], s.get("color")) >= COLOR_MATCH:
        return False
    mat = _material_key(s.get("material"))
    return not (need["material"] and mat and need["material"] != mat)


def _filament_words(f: Dict[str, Optional[str]]) -> str:
    color = _color_name(f["color"]) if f["color"] else ""
    return " ".join(w for w in (color, f["material"] or "") if w) or "a different filament"


def _join(words: List[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def check_print(filename: str, metadata: Optional[Dict[str, Any]], spools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Can this file print with the spools that are loaded? If not, say what's missing
    and offer one way forward plus printing anyway. With no filament unit, or a file
    that doesn't say what it needs, there's nothing to check. `uses` says, per filament
    the file uses, where it would come from: the file's sheet on the Print tab shows it."""
    result = _check_print(filename, metadata, spools)
    result["uses"] = _uses(job_filaments(metadata or {}), spools, result)
    colour = colour_sheet(filename, metadata, spools)
    if colour:
        # A file with colour changes on a printer with a unit: the Print sheet plans them (design/colour-change/, C)
        result["colour"] = colour
        result["colour_changes"] = [{"layer": r["layer"], "color": r["color"], "slot": r["slot"], "not_loaded": r["not_loaded"]}
                                    for r in colour["changes"]]
    return result


def _uses(needs: List[Dict[str, Optional[str]]], spools: List[Dict[str, Any]], result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """"Blue PLA is loaded, slot 4", "Black PETG isn't loaded", or "Uses White PLA" when there's
    nothing to tell it by (no filament unit, or one spool the printer isn't sure of)."""
    direct = len(spools) == 1 and bool(spools[0].get("direct"))
    out = []
    for n in needs:
        words = _filament_words(n)
        if not spools or (direct and result.get("ask")):
            loaded, slot, line = None, None, f"Uses {words}"
        else:
            s = next((s for s in spools if _spool_matches(n, s)), None)
            missing = n in (result.get("missing") or [])
            loaded = bool(s) and not missing
            slot = s["slot"] if loaded and not direct else None
            line = (f"{words} is loaded" + (f", slot {slot + 1}" if slot is not None else "")) if loaded else f"{words} isn't loaded"
        out.append({"color": n["color"], "material": n["material"], "loaded": loaded, "slot": slot, "line": line})
    return out


def _check_print(filename: str, metadata: Optional[Dict[str, Any]], spools: List[Dict[str, Any]]) -> Dict[str, Any]:
    needs = job_filaments(metadata or {})
    if not spools or not needs:
        return {"ok": True, "filename": filename, "missing": []}
    if len(spools) == 1 and spools[0].get("direct"):
        return _check_direct(filename, needs, spools[0])
    missing =[n for n in needs if not any(_spool_matches(n, s) for s in spools)]
    if not missing:
        return {"ok": True, "filename": filename, "missing": []}

    names = [_filament_words(m) for m in missing]
    headline = f"This needs {_join(names[:2])}{' and more' if len(names) > 2 else ''}."
    free = [s["slot"] + 1 for s in spools if s.get("status") == "empty"]
    # The same colour loaded as another material is the common near-miss: say so.
    near = None
    if len(missing) == 1 and missing[0]["color"]:
        near = next((s for s in spools if s.get("status") in ("ready", "low")
                     and _color_distance(missing[0]["color"], s.get("color")) < COLOR_MATCH), None)
    if near and near.get("material"):
        detail = (f"{_color_name(near['color'])} is loaded in slot {near['slot'] + 1}, but it's "
                  f"{near['material']}. Load {names[0]}, or print with what's loaded and expect it to behave differently.")
    elif free:
        if len(missing) == 1:
            where = f"slot {free[0]}" if len(free) == 1 else "slot " + " or ".join([", ".join(str(f) for f in free[:-1]), str(free[-1])])
            detail = (f"It isn't loaded right now. Load it into {where}, "
                      "or print with what's loaded and the colors will be different.")
        else:
            detail = ("They aren't loaded right now. Load them into the empty slots, "
                      "or print with what's loaded and the colors will be different.")
    else:
        it = "it" if len(missing) == 1 else "them"
        detail = (f"{'It' if it == 'it' else 'They'} {'isn' if it == 'it' else 'aren'}'t loaded right now, and every slot is full. "
                  f"Swap {it} in for a spool this print won't use, or print with what's loaded and the colors will be different.")
    return {
        "ok": False,
        "filename": filename,
        "missing": missing,
        "headline": headline,
        "short": f"Needs {_join(names[:2])}{' and more' if len(names) > 2 else ''}",
        "detail": detail,
        "actions": [
            _action("open_materials", "Show me the spools", primary=True),
            _action("start_file", "Print anyway", filename=filename),
        ],
    }


def _direct_ready_words(s: Dict[str, Any]) -> str:
    """The Ready line for a printer with one spool. Unsure is said quietly, never as an alert."""
    if s["status"] == "empty":
        return "No filament loaded."
    if s["status"] == "unknown":
        return ""
    if not s.get("name"):
        return "Filament loaded."
    if s.get("source") == "guess":
        return f"Probably {s['name']} loaded."
    return f"{s['name']} loaded{', running low' if s['status'] == 'low' else ''}."


def _check_direct(filename: str, needs: List[Dict[str, Optional[str]]], s: Dict[str, Any]) -> Dict[str, Any]:
    """One spool and no filament unit. When the printer knows what's loaded (someone said,
    or Spoolman), check it like a slot. When it only guesses, or the filament has changed
    since, ask: the answer is how it learns. A file with several filaments on one spool is
    colour changes by hand, with nothing to check them against."""
    if len(needs) != 1:
        return {"ok": True, "filename": filename, "missing": []}
    need = needs[0]
    want = _filament_words(need)

    def loaded_it(label: str) -> Dict[str, Any]:
        return _action("confirm_spool", label, primary=True, filename=filename,
                       color=need["color"], material=need["material"])

    def result(headline: str, short: str, detail: str, actions: List[Dict[str, Any]], ask: bool = False) -> Dict[str, Any]:
        return {"ok": False, "ask": ask, "filename": filename, "missing": [need], "headline": headline,
                "short": short, "detail": detail, "actions": actions}

    anyway = _action("start_file", "Print anyway", filename=filename)
    sure = s.get("source") in ("told", "spoolman") and not s.get("changed")
    if s.get("status") == "empty":
        return result(f"Load {want} first.", f"Load {want}", "The head looks empty.",
                      [loaded_it("It's loaded, print"), anyway])
    if _spool_matches(need, s) and (sure or s.get("source") == "guess"):
        return {"ok": True, "filename": filename, "missing": []}
    if sure:
        same_material = bool(need["material"]) and _material_key(s.get("material")) == need["material"]
        detail = (f"{s.get('name') or 'Something else'} is loaded. Load {want}, or print with what's loaded and "
                  + ("the color will be different." if same_material else "expect it to behave differently."))
        first = (loaded_it("I've loaded it") if s.get("source") == "told"
                 else _action("open_materials", "Show me the spool", primary=True))
        return result(f"This needs {want}.", f"Needs {want}", detail, [first, anyway])
    # A guess that doesn't match, a change since, or nothing known: ask.
    if s.get("changed"):
        was = (s.get("was") or {}).get("name")
        detail = f"The filament has been changed{f' since {was}' if was else ''}."
    elif s.get("source") == "guess" and s.get("name"):
        detail = f"Your last print used {s['name']}."
    else:
        detail = "Tell me once and I'll remember it."
    return result(f"This file uses {want}. Is that what's loaded?", f"Uses {want}", detail,
                  [loaded_it("Yes, print"), _action("open_materials", "No, it's something else")], ask=True)


# --------------------------------------------------------------------------
# Colour changes in a file (design/colour-change/, C): where each M600 is, and its colour when a marker says
# --------------------------------------------------------------------------

def colour_changes_in(lines: Any) -> List[Dict[str, Any]]:
    """Each M600 in a G-code file, in order: {layer, color}. The layer counts the slicer's layer-change
    markers (Orca and PrusaSlicer write ";LAYER_CHANGE", Cura ";LAYER:n" from 0) or takes Klipper's own
    SET_PRINT_STATS_INFO CURRENT_LAYER=, which is the number print_stats shows. The colour comes from a
    COLOR_CHANGE line with a #RRGGBB near the M600 (PrusaSlicer writes ";COLOR_CHANGE,T0,#F4F4F2" just
    before it); without one it's None. Moves, most of a file, are skipped without a look."""
    out: List[Dict[str, Any]] = []
    layer = 0
    mark: Optional[tuple] = None   # (colour, line) of a COLOR_CHANGE marker waiting for its M600
    bare: Optional[tuple] = None   # (index in out, line) of an M600 still without a colour
    for i, raw in enumerate(lines):
        if raw[:1] == "G" and raw[1:2] in ("0", "1", "2", "3") and raw[2:3] in (" ", "\n", "\r", ""):
            continue
        line = raw.strip()
        if not line:
            continue
        if "COLOR_CHANGE" in line.upper():
            m = _HEX_RE.search(line)
            if m:
                col = "#" + m.group(1).upper()
                if bare is not None and i - bare[1] <= COLOUR_MARK_LINES:
                    out[bare[0]]["color"] = col
                    bare = None
                else:
                    mark = (col, i)
            continue
        if line.startswith(";"):
            body = line[1:].lstrip()
            if body.startswith("LAYER_CHANGE"):
                layer += 1
            elif body.startswith("LAYER:"):
                try:
                    layer = int(body[6:].split()[0]) + 1
                except (ValueError, IndexError):
                    pass
            continue
        cmd = line.split(";", 1)[0].strip()
        word = cmd.split(None, 1)[0].upper() if cmd else ""
        if word == "SET_PRINT_STATS_INFO":
            m = _STATS_LAYER_RE.search(cmd)
            if m:
                layer = int(m.group(1))
        elif word == "M600" and len(out) < COLOUR_PLAN_MAX:
            col = mark[0] if mark and i - mark[1] <= COLOUR_MARK_LINES else None
            mark = None
            out.append({"layer": layer or None, "color": col})
            bare = None if col else (len(out) - 1, i)
    return out


def colour_changes_from_file(path: str) -> List[Dict[str, Any]]:
    """colour_changes_in() over a file on disk, read a line at a time (files run to tens of MB)."""
    with open(path, "r", errors="replace") as f:
        return colour_changes_in(f)


def _colour_word(hex_color: Optional[str]) -> str:
    return _color_name(hex_color).lower()


def _closest(want: Dict[str, Optional[str]], spools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The loaded spool nearest a colour that also matches its material; None when nothing does."""
    best, best_d = None, 999.0
    for s in spools:
        if not _spool_matches(want, s):
            continue
        d = _color_distance(want.get("color"), s.get("color")) if want.get("color") else 0.0
        if d < best_d:
            best, best_d = s, d
    return best


def _at_layer(layer: Optional[int]) -> str:
    return f"layer {layer}" if layer else "the color change"


def colour_sheet(filename: str, metadata: Optional[Dict[str, Any]], spools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The Print sheet's plan for a file with colour changes on a printer with a unit (CReady, CAsk): what it
    starts with, and per change the spool that matches the file's colour and the print's material, or a
    question. None on a printer without a unit, or a file without an M600."""
    meta = metadata or {}
    changes = meta.get("colour_changes") or []
    if not changes or not spools or any(s.get("direct") for s in spools):
        return None
    job = _pretty_job_name(filename) or "This print"
    material = _material_key(job_material(meta))
    loaded = [s for s in spools if s.get("status") in ("ready", "low")]
    needs = job_filaments(meta)
    first = needs[0] if needs else {"color": None, "material": material}
    head = next((s for s in loaded if s.get("in_use")), None)
    if head and (_spool_matches(first, head) or not first["color"]):
        start = head
    else:
        start = _closest(first, loaded) if first["color"] or first["material"] else head
    if start:
        n = start["slot"] + 1
        start_row = {"slot": start["slot"], "name": start.get("name") or f"Slot {n}", "color": start.get("color"), "loaded": True,
                     "line": f"Slot {n} · in the head" if start.get("in_use") else f"Slot {n}"}
    else:
        start_row = {"slot": None, "name": _filament_words(first), "color": first["color"], "loaded": False,
                     "line": "Isn't loaded. It starts with what's in the head."}

    choices = []
    for s in loaded:
        n = s["slot"] + 1
        name = s.get("name") or f"Slot {n}"
        differs = bool(material and s.get("material") and _material_key(s["material"]) != material)
        choices.append({"slot": s["slot"], "name": name, "color": s.get("color"), "material": s.get("material"), "line": f"Slot {n}",
                        "differs": differs,
                        "ask": f"{name} on a {material} print may not stick. Use it anyway?" if differs else None})

    rows = []
    for k, ch in enumerate(changes):
        layer, color = ch.get("layer"), _hex_color(ch.get("color"))
        match = _closest({"color": color, "material": material}, loaded) if color else None
        cw = _colour_word(color) if color else None
        rows.append({
            "n": k + 1, "layer": layer, "color": color,
            "label": f"Layer {layer}" if layer else f"Change {k + 1}",
            "slot": match["slot"] if match else None,
            "not_loaded": bool(color) and match is None,
            "named_line": f"Slot {match['slot'] + 1} · the file's {cw}" if match else None,
            "missing_line": f"There's no {cw} in the unit. I'll pause at {_at_layer(layer)}." if color and not match else None,
            "pause_line": f"I'll pause at {_at_layer(layer)} for you to choose.",
        })

    at = _at_layer(rows[0]["layer"])
    if len(rows) == 1:
        r = rows[0]
        cw = _colour_word(r["color"]) if r["color"] else None
        if r["slot"] is not None:
            headline = f"{job} changes color once."
            detail = f"The file asks for {cw} at {at}. The unit can do it, so nobody needs to be here."
        elif r["not_loaded"]:
            headline = f"{job} changes color at {at}."
            detail = f"The file asks for {cw}. Put a {cw} spool in the unit first, or pick another, and nobody needs to be here."
        else:
            headline = f"{job} changes color at {at}."
            detail = "The file doesn't say which color. Which spool? Then the unit does it, and nobody needs to be here."
    else:
        headline = f"{job} changes color {len(rows)} times."
        detail = ("The unit can do them all, so nobody needs to be here." if all(r["slot"] is not None for r in rows)
                  else "Pick a spool for each one. Then the unit does them, and nobody needs to be here.")
    return {"headline": headline, "detail": detail, "material": material, "start": start_row, "changes": rows,
            "choices": choices,
            "labels": {"start": "To start", "pause": "Pause there and let me choose", "print": "Print", "back": "Back",
                       "change": "Change", "yes": "Use it anyway"}}


# --------------------------------------------------------------------------
# The tracker: merges status, remembers what raw status forgets
# --------------------------------------------------------------------------

class IntentTracker:
    """
    Feed it Klipper status updates, gcode responses and Moonraker metadata.
    Ask it for the intent object. Keeps the small amount of memory raw
    status doesn't carry: which preparing step we're on, why we paused,
    whether a finished print has been acknowledged.
    """

    SUBSCRIBE = {
        "webhooks": None,
        "print_stats": None,
        "display_status": None,
        "virtual_sdcard": None,
        "pause_resume": None,
        "idle_timeout": None,
        "heater_bed": ["temperature", "target"],
        "extruder": ["temperature", "target", "can_extrude"],
        "toolhead": ["homed_axes", "axis_minimum", "axis_maximum"],
        "motion_report": ["live_position"],
        "ace": None,
        "mmu": None,              # Happy Hare, read but not driven (filament_units.py)
        "mmu_machine": None,
        "gcode_macro HEAT_SOAK": None,
        "gcode_macro _PRINT_START": ["stage"],
        "gcode_macro _PRINT_START_SETTINGS": ["chamber_max", "tap", "z_moves"],
        ELYIR_BENCH_START: ["stage", "applied_z"],
        ELYIR_BENCH_START_SETTINGS: ["chamber_max", "z_moves"],
        "quad_gantry_level": ["applied"],   # present: the gantry moves in Z (design/hands-on/)
        "z_tilt": ["applied"],              # present: the bed does
        "gcode_move": ["homing_origin"],
        "save_variables": ["variables"],
        # "exclude_object" is added by whoever subscribes, when Klipper has it (design/skip-objects/)
    }

    def __init__(self, printer_name: str = "Printer", now: Optional[float] = None):
        self.printer_name = printer_name
        self.status: Dict[str, Any] = {}
        self.klippy_state = "disconnected"   # disconnected|startup|ready|shutdown|error
        self.klippy_message = ""
        self.units_on_usb: Optional[int] = None   # filament units the USB bus reports, counted by the component
        self._usb_devnum: Dict[str, int] = {}      # USB port -> kernel device number last seen
        self.head_sensor: Optional[str] = None     # Klipper object for the filament sensor at the head
        self._swap: Optional[Dict[str, Any]] = None   # a spool change in progress or just failed
        self._last_swap_end: float = float("-inf")   # never
        self._last_unloaded: Optional[Dict[str, Any]] = None   # colour/material last taken out
        self._mismatch: Optional[tuple] = None        # (kind, since)
        self._head_ok: Optional[int] = None           # slot someone said is in the head though the sensor reads empty
        self._change: Optional[Dict[str, Any]] = None   # changing filament by hand, or checking after a swap
        self._change_queue: List[tuple] = []          # commands for whoever runs work() next
        self._keep_warm_until: Optional[float] = None  # heaters go off then, unless a print started
        self._warm: Optional[Dict[str, Any]] = None   # warming up before a print: material, targets, when warm
        self._hands: Optional[Dict[str, Any]] = None  # a job from Move and heat holding the printer: kind, until
        self._hands_heat: set = set()                 # heaters set by hand, turned off after HANDS_IDLE_SECONDS
        self._hands_until: Optional[float] = None
        self._hands_aim: Optional[tuple] = None       # (position, when) of the last move sent
        self._hands_homing: Optional[float] = None    # G28 sent then, not homed yet
        self._squish: Optional[Dict[str, Any]] = None  # this print's first layer: what PRINT_START applied, nudges since
        self.dryer_max: float = DRY_MAX_DEFAULT        # the unit's max_dryer_temperature, from Klipper's config
        self._slot_seen: Dict[int, str] = {}           # slot -> status last seen, to notice a spool pushed in
        self._dryer_seen: Dict[int, tuple] = {}        # unit -> (remain_time, when it last changed or None)
        self._dryer_seconds: Dict[int, bool] = {}      # unit -> its dryer counts down in seconds
        self._new_spools: Dict[int, Dict[str, Any]] = {}   # untagged spools pushed in, waiting for "What is it?"
        self._carried: Optional[Dict[str, Any]] = None  # the unit carried on with a matching spool mid-print
        self._assist_off: set = set()                   # slots whose feed assist a person turned off
        self._assist_sent: set = set()                  # (job, slot) feed assist was turned back on for
        self._usb_reconnects: Dict[str, List[float]] = {}   # USB port -> times it came back
        self.offline_since: Optional[float] = now if now is not None else time.time()
        self.startup_since: Optional[float] = None
        self.metadata: Dict[str, Any] = {}
        self.metadata_file: Optional[str] = None

        self._job_file: Optional[str] = None
        self._prep_index = -1
        self._seen_step = -1                            # the step a start routine that names none has reached (PREP_STEPS)
        self._homed_at_start: Optional[str] = None      # homed axes when this job began: a change is homing
        self._art_message: Optional[str] = None       # the drawing an M117 named, for older PRINT_STARTs
        self._level: Optional[Dict[str, float]] = None  # the last levelling pass: range and tolerance, mm
        self._mesh_seen = 0                             # bed cells the head has been over while meshing
        self._mesh_at: Optional[List[float]] = None     # where the head was last seen while meshing
        self._art_was: Optional[str] = None
        self._print_started = False
        self._own_start = False                         # this job runs Elyir Bench's start macro (elyir-bench.cfg)
        self._own_stage_was = ""                        # ...and its stage at the last look
        self._pause_reason: Optional[Dict[str, Any]] = None
        self._pause_since: Optional[float] = None
        self._finished_ack = False
        self._cancelled_at: Optional[float] = None
        self._stopping_since: Optional[float] = None   # Stop now pressed; cleared when Klipper is back
        # Turn off / Restart (design/power/): {kind: off|restart, since, from, now, going, error}
        self._power: Optional[Dict[str, Any]] = None
        self._stop_saw_down = False
        self._state_since: Optional[float] = None
        self._last_state: Optional[str] = None
        self._last_material: Optional[str] = None
        # A printer without a filament unit has one spool the printer can't read. Whoever knows
        # Klipper's objects sets has_unit (None until then). The component stores direct_spool
        # in Moonraker's database whenever direct_spool_dirty is set, and restores it at start.
        self.has_unit: Optional[bool] = None
        self.direct_spool: Optional[Dict[str, Any]] = None   # {color, material, source, at, changed, was, from}
        self.direct_spool_dirty = False
        self.spoolman_spool: Optional[Dict[str, Any]] = None  # the active Spoolman spool: {color, material, grams}
        self._head_seen: Optional[bool] = None
        self._head_out_at: Optional[float] = None   # when the head was first seen empty, this time
        self._guessed_file: Optional[str] = None
        # Whether any phone will hear about this printer. Set by whoever runs the
        # integration (the component reads what the door records); copy only
        # promises a phone message when one will actually arrive.
        self.phones_notified = False
        # Maintenance summary from elyir_bench_care.summary(), set by the component.
        self.care: Optional[Dict[str, Any]] = None
        # Plates still to print after this one (design/plate/, A): [{after, file, count, what}], from
        # elyir-bench/next_plates in Moonraker's database, written by the slicer when it sends them.
        self.next_plates: List[Dict[str, Any]] = []
        # Colour changes on a unit printer (design/colour-change/, C and A). The plan the Print sheet made, kept in
        # Moonraker's database at elyir-bench/colour_plan whenever colour_plan_dirty is set: {filename, changes:
        # [{layer, slot | "pause", color}], at, started}. Only for the print of that file started right after it.
        self.colour_plan: Optional[Dict[str, Any]] = None
        self.colour_plan_dirty = False
        self._checked: Dict[str, Dict[str, Any]] = {}   # files the Print sheet planned: {material, changes}
        self._colour_n = 0                     # colour-change pauses seen in this print
        self._colour_tried: set = set()        # ...that the unit was asked to switch by itself
        self._colour_done: set = set()         # ...that it switched, waiting for the print to carry on
        self._colour_attended: Optional[float] = None   # a person's last step at the pause: the 20 minutes restart
        self.setup_found: List[str] = []       # what the Pi sees plugged in, in words, for a fresh card's first screen

    # ---- inputs --------------------------------------------------------

    def set_klippy_state(self, state: str, message: str = "", now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if state == "startup" and self.klippy_state != "startup":
            self.startup_since = now
        self.klippy_state = state
        self.klippy_message = message or ""
        if self._stopping_since is not None:
            if state != "ready":
                self._stop_saw_down = True
            elif self._stop_saw_down:
                self._stopping_since = None
        if state == "disconnected":
            if self.offline_since is None:
                self.offline_since = now
        else:
            self.offline_since = None

    def update_status(self, status: Dict[str, Any], now: Optional[float] = None) -> None:
        """Merge a Klipper status update (same shape as notify_status_update)."""
        now = time.time() if now is None else now
        for obj, fields in (status or {}).items():
            if not isinstance(fields, dict):
                continue
            cur = self.status.setdefault(obj, {})
            for k, v in fields.items():
                cur[k] = deepcopy(v)
        self._observe(now)
        self._observe_art()

    def on_gcode_response(self, line: str, now: Optional[float] = None) -> None:
        """Catch the few console lines that carry meaning raw status doesn't."""
        now = time.time() if now is None else now
        low = (line or "").lower()
        if "spool is empty" in low or "filament runout" in low or "runout detected" in low:
            self._pause_reason = {"phase": "runout", "slot": self._spool_in_head(), "at": now}
        elif "ace sensor error" in low or "feed timeout" in low:
            self._pause_reason = {"phase": "feed_error", "slot": self._spool_in_head(), "at": now}
        elif ("m600" in low or "color change" in low or "colour change" in low
              or "load new filament" in low):   # Workshop's M600 says only "Please load new filament and resume"
            prev = self._pause_reason or {}
            if prev.get("phase") != "color_change":
                self._colour_n += 1   # a new colour change; more lines about the same one don't count again
            self._pause_reason = {"phase": "color_change", "slot": self._spool_in_head(), "at": now, "n": self._colour_n}
            self._maybe_auto_colour(now)
        m = ENDLESS_RE.search(low)
        if m:
            self._observe_carried(int(m.group(1)), int(m.group(2)), now)
        m = LEVEL_RE.search(low)
        if m:
            self._level = {"range": float(m.group(1)), "tolerance": float(m.group(2))}
        self._match_prep_step(low)
        self._match_swap_step(low)

    def set_metadata(self, filename: Optional[str], metadata: Optional[Dict[str, Any]]) -> None:
        self.metadata_file = filename
        self.metadata = metadata or {}
        self._guess_from_print(time.time())

    # ---- the one spool on a printer without a filament unit ---------------

    @property
    def direct(self) -> bool:
        return self.has_unit is False

    def remember_spool(self, color: Optional[str], material: Optional[str], source: str = "told",
                       now: Optional[float] = None, filename: Optional[str] = None) -> None:
        """What's on the printer: said by a person ("told") or taken from a print ("guess").
        The spools before it are kept, newest first, as quick answers to "New filament?"."""
        old = self.direct_spool or {}
        before = old.get("was") if old.get("changed") else old
        recent = [r for r in ([before] if before else []) + list(old.get("recent") or [])
                  if isinstance(r, dict) and r.get("material")]
        color, material = _hex_color(color), _material_key(material)
        kept: List[Dict[str, Any]] = []
        for r in recent:
            same = _material_key(r.get("material")) == material and _color_distance(r.get("color"), color) < COLOR_MATCH
            if not same and not any(_material_key(k["material"]) == _material_key(r.get("material"))
                                    and _color_distance(k["color"], r.get("color")) < COLOR_MATCH for k in kept):
                kept.append({"color": _hex_color(r.get("color")), "material": _material_key(r.get("material"))})
        self.direct_spool = {"color": color, "material": material, "source": source,
                             "at": time.time() if now is None else now, "changed": False, "was": None,
                             "from": filename, "recent": kept[:RECENT_SPOOLS]}
        self.direct_spool_dirty = True

    def restore_spool(self, record: Any) -> None:
        """The stored record, at start. Anything that doesn't look like one is ignored."""
        if isinstance(record, dict) and record.get("source") in ("told", "guess") and isinstance(record.get("at"), (int, float)):
            self.direct_spool = {k: record.get(k) for k in ("color", "material", "source", "at", "changed", "was", "from", "recent")}
            self.direct_spool["changed"] = bool(record.get("changed"))

    def _observe_head(self, now: float) -> None:
        """Filament that leaves the head and comes back may be a different spool: say so until
        someone confirms. Not when they said what it is while the head was empty."""
        loaded = self.head_loaded()
        if loaded is None:
            return
        was, self._head_seen = self._head_seen, loaded
        if loaded is False and was is not False:
            self._head_out_at = now
        if not self.direct or was is not False or loaded is not True:
            return
        rec = self.direct_spool
        if rec and not rec.get("changed") and (self._head_out_at is None or rec["at"] < self._head_out_at):
            name = _spool_name(rec.get("color"), rec.get("material"))
            self.direct_spool = dict(rec, changed=True,
                                     was={"name": name, "color": rec.get("color"), "material": rec.get("material")})
            self.direct_spool_dirty = True

    def _guess_from_print(self, now: float) -> None:
        """A print that started with nothing known (or a guess, or a change since) says what's
        loaded better than nothing: the file's filament, held as a guess. Once per file."""
        if not self.direct:
            return
        ps = self.status.get("print_stats") or {}
        filename = ps.get("filename") or None
        if ps.get("state") != "printing" or not filename or filename == self._guessed_file or self.metadata_file != filename:
            return
        self._guessed_file = filename
        rec = self.direct_spool
        if rec and rec.get("source") == "told" and not rec.get("changed"):
            return
        needs = job_filaments(self.metadata)
        if len(needs) == 1 and needs[0]["material"]:
            self.remember_spool(needs[0]["color"], needs[0]["material"], "guess", now=now, filename=filename)

    def _direct_entry(self) -> Dict[str, Any]:
        """The one spool. Spoolman's active spool wins, then what someone said, then a guess."""
        loaded = self.head_loaded()
        rec = self.direct_spool or {}
        sm = self.spoolman_spool
        color = material = grams = since = was = guess_from = None
        changed = False
        if sm:
            source, color, material = "spoolman", _hex_color(sm.get("color")), _material_key(sm.get("material"))
            g = sm.get("grams")
            grams = int(round(g)) if isinstance(g, (int, float)) and g > 0 else None
        elif rec:
            source, since = rec["source"], _iso(rec["at"])
            if rec.get("changed"):
                changed, was = True, rec.get("was")
            else:
                color, material = rec.get("color"), rec.get("material")
                guess_from = _pretty_job_name(rec.get("from")) if source == "guess" and rec.get("from") else None
        else:
            source = "unknown"
        if loaded is False:
            status = "empty"
        elif loaded is True or color or material:
            status = "low" if grams is not None and grams < 80 else "ready"
        else:
            status = "unknown"
        return {
            "slot": 0,
            "name": _spool_name(color, material),
            "color": color,
            "material": material,
            "grams": grams,
            "status": status,
            "in_use": status in ("ready", "low"),
            "rfid": False,
            "direct": True,
            "source": source,
            "since": since,
            "changed": changed,
            "was": was,
            "guess_from": guess_from,
            # Spools that were on before, newest first, without the one shown or the one it was.
            "recent": [dict(r, name=_spool_name(r.get("color"), r.get("material"))) for r in (rec.get("recent") or [])
                       if not (was and r.get("material") == was.get("material")
                               and _color_distance(r.get("color"), was.get("color")) < COLOR_MATCH)][:3],
        }

    # ---- turning the printer off (design/power/, A) ----------------------------

    def _nozzle_temp(self) -> float:
        return float((self.status.get("extruder") or {}).get("temperature", 0) or 0)

    def power_why_not(self) -> Optional[str]:
        """Why Turn off and Restart aren't offered right now, or None when they are."""
        if self.klippy_state == "ready" and (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            return "Not while it's printing."
        if self._change is not None or self._swap is not None:
            return "Not while it's changing filament."
        return None

    def power_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> None:
        """start {kind}: heaters are already off, wait for the nozzle. keep: never mind. now: don't wait.
        retry: after the system refused, ask it again."""
        now = time.time() if now is None else now
        op = payload.get("op")
        if op == "start":
            self._power = {"kind": "restart" if payload.get("kind") == "restart" else "off", "since": now,
                           "from": self._nozzle_temp(), "now": False, "going": None, "error": None}
        elif op == "keep":
            self._power = None
        elif op in ("now", "retry") and self._power is not None:
            self._power.update(now=True, going=None, error=None)

    def power_due(self, now: Optional[float] = None) -> Optional[str]:
        """'off' or 'restart' once it's time to go: the nozzle is cool enough for its fan to stop, someone said
        now, Klipper isn't running (so isn't running the fan either), or it has waited long enough."""
        p = self._power
        if p is None or p["going"] is not None or p["error"]:
            return None
        now = time.time() if now is None else now
        if (p["now"] or self.klippy_state != "ready" or self._nozzle_temp() <= POWER_COOL_TEMP
                or now - p["since"] >= POWER_MAX_WAIT_SECONDS):
            return p["kind"]
        return None

    def power_going(self, now: Optional[float] = None) -> None:
        if self._power is not None:
            self._power["going"] = time.time() if now is None else now

    def power_failed(self, message: str) -> None:
        if self._power is not None:
            self._power.update(going=None, error=message or "The system said no.")

    def _power_view(self) -> Dict[str, Any]:
        why = self.power_why_not()
        view: Dict[str, Any] = {"allowed": why is None, "why": why, "cool_to": POWER_COOL_TEMP, "kind": None}
        p = self._power
        if p is not None:
            t, start = self._nozzle_temp(), float(p["from"])
            progress = 1.0 if start <= POWER_COOL_TEMP else max(0.0, min(1.0, (start - t) / (start - POWER_COOL_TEMP)))
            view.update(kind=p["kind"], going=p["going"] is not None, failed=bool(p["error"]),
                        progress=round(progress, 3), nozzle=round(t, 1))
        return view

    def begin_stop(self, now: Optional[float] = None) -> None:
        """Stop now: the emergency stop and firmware restart that follow are expected, not a problem."""
        now = time.time() if now is None else now
        self._stopping_since = now
        self._stop_saw_down = False
        self._cancelled_at = now

    def next_plate(self) -> Optional[Dict[str, Any]]:
        """The plate that follows the one just printed, if the slicer sent one with it."""
        name = str((self.status.get("print_stats") or {}).get("filename") or "")
        if not name:
            return None
        for p in self.next_plates or []:
            if isinstance(p, dict) and p.get("file") and p.get("after") in (name, name.rsplit("/", 1)[-1]):
                return p
        return None

    def acknowledge_finished(self) -> None:
        self._finished_ack = True

    # ---- observation of transitions -----------------------------------

    def _observe(self, now: float) -> None:
        ps = self.status.get("print_stats", {})
        state = ps.get("state", "standby")
        filename = ps.get("filename") or None

        # PRINT_START pauses within a second of starting, so a poll can see a new job go
        # straight from standby to paused.
        getting_ready = state == "paused" and bool(self.prep_stage())
        if (state == "printing" or getting_ready) and (filename != self._job_file or self._last_state not in ("printing", "paused")):
            if filename != self._job_file or self._last_state in ("standby", "complete", "cancelled", "error", None):
                self._job_file = filename
                self._prep_index = -1
                self._seen_step = -1
                self._homed_at_start = (self.status.get("toolhead") or {}).get("homed_axes")
                self._art_message = None
                self._level = None
                self._mesh_seen = 0
                self._mesh_at = None
                self._print_started = False
                self._own_start = False
                self._finished_ack = False
                self._pause_reason = None
                self._cancelled_at = None
                self._squish = None
                self._carried = None
                self._colour_n = 0
                self._colour_tried, self._colour_done = set(), set()
                self._colour_attended = None
                self._claim_colour_plan(filename, now)
        # None: the first look after Moonraker started. Klipper keeps saying cancelled long after
        # a cancel, so only a change we watched happen is a print that was just stopped.
        if state == "cancelled" and self._last_state not in ("cancelled", None):
            self._cancelled_at = now
            self._pause_reason = None
        if state in ("standby", "complete", "error") and self._last_state != state:
            self._pause_reason = None
        if state == "complete" and self._last_state != "complete":
            self._finished_ack = False
        if state in ("standby", "complete", "cancelled", "error") and self._last_state in ("printing", "paused"):
            plan = self.colour_plan
            if plan and plan.get("started"):
                self.colour_plan, self.colour_plan_dirty = None, True   # it was for that print, which is over

        paused = bool(self.status.get("pause_resume", {}).get("is_paused"))
        if paused and self._pause_since is None:
            self._pause_since = now
        if not paused:
            self._pause_since = None
            if self._pause_reason and state == "printing":
                self._pause_reason = None
                self._colour_done.clear()
        c = self._change
        if c is not None and c.get("kind") == "colour" and (state not in ("printing", "paused") or not (paused or state == "paused")):
            self._change = None   # the print carried on or ended some other way: nothing left to switch for
        self._maybe_auto_colour(now)

        msg = (self.status.get("display_status", {}).get("message") or "").lower()
        if msg:
            self._match_prep_step(msg)

        info = ps.get("info") or {}
        layer = info.get("current_layer")
        if isinstance(layer, (int, float)) and layer >= 1:
            self._print_started = True
        self._observe_own_start(state)
        if state == "printing" and not self._print_started:
            self._observe_steps()

        self._observe_head(now)
        self._observe_slots()
        self._observe_dryers(now)
        self._guess_from_print(now)
        self._observe_squish(state, getting_ready or bool(self.prep_stage()))
        self._last_state = state

    def _observe_steps(self) -> None:
        """How far a start routine that names no step has got, from what the printer does. Never goes back."""
        bed, ext = self.status.get("heater_bed") or {}, self.status.get("extruder") or {}
        homed = (self.status.get("toolhead") or {}).get("homed_axes")
        step = 0
        bed_target = float(bed.get("target") or 0)
        if (homed is not None and self._homed_at_start is not None and homed != self._homed_at_start) or \
                (bed_target and float(bed.get("temperature") or 0) >= bed_target - 3):
            step = 2
        hot = self.metadata.get("first_layer_extr_temp") if isinstance(self.metadata, dict) else None
        hot = float(hot) - 5 if isinstance(hot, (int, float)) and hot > 0 else PRINT_NOZZLE_MIN
        if float(ext.get("target") or 0) >= hot and self._seen_step >= 2:
            step = 3
        self._seen_step = max(self._seen_step, step)

    def prep_stage(self) -> str:
        """The start macro's stage while getting ready ('' when not): Elyir Bench's own (a printer someone
        else set up) first, then the shared PRINT_START's."""
        for name in (ELYIR_BENCH_START, "gcode_macro _PRINT_START"):
            stage = (self.status.get(name) or {}).get("stage")
            if stage:
                return str(stage)
        return ""

    def _observe_own_start(self, state: str) -> None:
        """Elyir Bench's start macro: remember this job runs it, and count its stage going back to ''
        after `own` (ELYIR_BENCH_PRINT_START_DONE) as the print starting, whatever M117 said."""
        stage = str((self.status.get(ELYIR_BENCH_START) or {}).get("stage") or "")
        if stage and state in ("printing", "paused"):
            self._own_start = True
        if self._own_stage_was == "own" and not stage and state == "printing":
            self._print_started = True
            self._prep_index = len(PREP_STEPS)
        self._own_stage_was = stage

    def _match_prep_step(self, low: str) -> None:
        if not low:
            return
        for marker in PRINT_STARTED_MARKERS:
            if marker in low:
                self._print_started = True
                self._prep_index = len(PREP_STEPS)
                return
        for needle, art in ART_FROM_MESSAGE:
            if needle in low:
                self._art_message = art
                break
        for i, step in enumerate(PREP_STEPS):
            if any(m in low for m in step["match"]):
                if i >= self._prep_index:
                    self._prep_index = i
                return

    def _spool_in_head(self) -> Optional[int]:
        """The slot feeding the head; the one spool on a printer without a unit."""
        return 0 if self.direct else self._selected_slot()

    def _selected_slot(self) -> Optional[int]:
        fu = self.unit_state()
        return fu["selected"] if fu else None

    def unit_state(self) -> Optional[Dict[str, Any]]:
        """The filament units in one shape, whatever drives them (filament_units.py); None without one."""
        return None if self.direct else filament_units.read(self.status)

    def unit_commands(self) -> Optional[Any]:
        """The commands the unit's driver takes, or None when Bench can only watch it."""
        return filament_units.commands(self.unit_state())

    # ---- chamber -------------------------------------------------------

    @staticmethod
    def chamber_sensor_name(object_names: List[str]) -> Optional[str]:
        """Pick the Klipper temperature sensor that measures the chamber, if any."""
        for name in object_names:
            low = name.lower()
            if low.startswith("temperature_sensor ") and ("chamber" in low or "enclosure" in low):
                return name
        return None

    def chamber(self) -> Optional[Dict[str, Any]]:
        for key, val in self.status.items():
            low = key.lower()
            if low.startswith("temperature_sensor ") and ("chamber" in low or "enclosure" in low) and isinstance(val, dict):
                t = val.get("temperature")
                if isinstance(t, (int, float)):
                    return {"temperature": round(float(t), 1)}
        return None

    # ---- filament units ------------------------------------------------

    def set_units_on_usb(self, n: Optional[int]) -> None:
        self.units_on_usb = n

    def observe_usb_units(self, ports: Optional[Dict[str, int]], now: Optional[float] = None) -> None:
        """Filament units on USB as {port: kernel device number}. The kernel gives a device a
        new number every time it re-enumerates, so a changed number means it dropped off
        and came back, even if that happened between two looks."""
        now = time.time() if now is None else now
        if ports is None:
            self.units_on_usb = None
            return
        self.units_on_usb = len(ports)
        for port, devnum in ports.items():
            last = self._usb_devnum.get(port)
            if last is not None and devnum != last:
                self._usb_reconnects.setdefault(port, []).append(now)
            self._usb_devnum[port] = devnum
        for port in list(self._usb_reconnects):
            self._usb_reconnects[port] = [t for t in self._usb_reconnects[port] if now - t <= FLAPPING_WINDOW]

    def flapping_units(self) -> Dict[str, int]:
        """Ports whose unit keeps dropping off USB, with how many times in the window."""
        return {p: len(ts) for p, ts in self._usb_reconnects.items() if len(ts) >= FLAPPING_RECONNECTS}

    def units(self) -> Optional[Dict[str, Any]]:
        """Filament units plugged in vs units the printer is using. A unit that was off or
        still starting when the printer's software started stays missing until it looks
        again; say so, and offer to."""
        fu = self.unit_state()
        present = self.units_on_usb
        if fu is None and not present:
            return None
        known = fu["known"] if fu else 0
        missing = max(0, (present or 0) - known)
        notice = None
        flapping = self.flapping_units()
        if flapping:
            # Looking again can't help a unit that won't stay connected: say what to check.
            times = max(flapping.values())
            one = len(flapping) == 1
            return {"present": present, "known": known, "missing": missing, "flapping": len(flapping),
                    "notice": {
                        "headline": "A filament unit keeps disconnecting." if one else f"{len(flapping)} filament units keep disconnecting.",
                        "detail": (f"{'It has' if one else 'They have'} dropped off and come back {times} times in the last "
                                   "two minutes. Check the USB cable and power, or try another USB port."),
                    },
                    "actions": []}
        if missing:
            one = missing == 1
            notice = {
                "headline": "One filament unit isn't showing up." if one else f"{missing} filament units aren't showing up.",
                "detail": (f"{'It' if one else 'They'}'{'s' if one else 're'} plugged in, but the printer hasn't picked "
                           f"{'it' if one else 'them'} up. Looking again restarts the printer's software "
                           "and takes about 20 seconds."),
            }
        return {"present": present, "known": known, "missing": missing, "flapping": 0, "notice": notice,
                "actions": [_action("rescan_units", "Look again", primary=bool(missing))]}

    # ---- each unit: its slots and its dryer (design/slots/, B) ------------------------

    def _units_raw(self) -> List[Dict[str, Any]]:
        fu = self.unit_state()
        return fu["units"] if fu else []

    def _observe_dryers(self, now: float) -> None:
        """Whether each dryer counts down in seconds or minutes, from the time between two of its steps. An ACE
        Pro on firmware V1.3.856 counts seconds; until two steps are seen, _drying guesses."""
        for u in self._units_raw():
            d = u["dryer"] if isinstance(u["dryer"], dict) else {}
            left = d.get("remain_time")
            if not isinstance(left, (int, float)) or self._drying(d, now) is None:
                self._dryer_seen.pop(u["index"], None)
                continue
            was = self._dryer_seen.get(u["index"])
            if was is None or left > was[0]:
                self._dryer_seen[u["index"]] = (left, None)
            elif left < was[0]:
                if was[1] is not None and now > was[1]:
                    self._dryer_seconds[u["index"]] = (was[0] - left) / (now - was[1]) > 0.1
                self._dryer_seen[u["index"]] = (left, now)

    @staticmethod
    def _drying(d: Any, now: float, seconds: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """The dryer's own report, or None when it's off. seconds: how it counts, once seen; None guesses."""
        if not isinstance(d, dict):
            return None
        if str(d.get("status") or "").lower() in ("", "stop", "stopped", "idle", "off", "none"):
            return None
        total = float(d.get("duration") or 0)   # minutes, as ACE_START_DRYING sent it
        left = float(d.get("remain_time") or 0)
        # The guess: more than the whole duration can only be seconds. It misreads the last stretch of seconds.
        if seconds or (seconds is None and left > (total * 1.5 if total else 600)):
            left /= 60
        return {"target": int(d.get("target_temp") or 0), "minutes_left": int(round(left)),
                "minutes_total": int(total), "ends_clock": _clock(now + left * 60)}

    def dry_plan(self, slots: List[Dict[str, Any]]) -> Dict[str, Any]:
        """How warm and how long, from what's inside: the most delicate material sets the heat,
        the slowest one the time. Never above what this unit allows."""
        mats: List[str] = []
        for s in slots:
            k = _material_key(s.get("material")) if s.get("status") in ("ready", "low") else None
            if k and k not in mats:
                mats.append(k)
        known = [m for m in mats if m in DRY_PRESETS]
        if known:
            temp = min(DRY_PRESETS[m][0] for m in known)
            hours = max(DRY_PRESETS[m][1] for m in known)
            soft = next(m for m in known if DRY_PRESETS[m][0] == temp)
            slow = next(m for m in known if DRY_PRESETS[m][1] == hours)
            why = f"because {soft} softens above that" if len(known) > 1 and any(DRY_PRESETS[m][0] > temp for m in known) else f"for {soft}"
            hours_why = f"{slow}'s time" if len(known) > 1 else f"for {slow}"
        else:
            temp, hours = DRY_UNKNOWN
            why, hours_why = "gently, since I don't know what's inside", "long enough for most"
        if temp > self.dryer_max:
            temp, why = int(self.dryer_max), "as warm as this unit goes"
        return {"temp": int(temp), "hours": hours, "why": why, "hours_why": hours_why,
                "materials": mats, "names": [s["name"] for s in slots if s.get("status") in ("ready", "low") and s.get("name")]}

    def unit_list(self, spools: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
        """One entry per filament unit: its slots, its temperature, its dryer, and Dry or Stop."""
        raw = self._units_raw()
        out = []
        for u in raw:
            slots = [s for s in spools if u["offset"] <= s["slot"] < u["offset"] + u["n"]]
            drying = self._drying(u["dryer"], now, self._dryer_seconds.get(u["index"]))
            plan = self.dry_plan(slots)
            actions: List[Dict[str, Any]] = []
            if self.klippy_state == "ready" and u["connected"]:
                actions = ([_action("stop_drying", "Stop", unit=u["index"])] if drying
                           else [_action("dry_unit", "Dry", unit=u["index"], hours=plan["hours"])])
            temp = u["temp"]
            out.append({
                "index": u["index"],
                "name": u["alias"] or ("Filament unit" if len(raw) == 1 else f"Unit {u['index'] + 1}"),
                "slots": [s["slot"] for s in slots],
                "connected": u["connected"],
                "temp": round(float(temp)) if isinstance(temp, (int, float)) else None,
                "drying": drying,
                "dry": plan,
                "actions": actions,
            })
        return out

    def _units_view(self, spools: List[Dict[str, Any]], now: float) -> Optional[Dict[str, Any]]:
        """units() (plugged in vs picked up), plus each unit and the carry-on switch."""
        u = self.units()
        if u is None:
            return None
        return dict(u, list=self.unit_list(spools, now), carry_on=self.carry_on())

    # ---- carry on with a matching spool -------------------------------------------

    def carry_on(self) -> Optional[bool]:
        """The unit's endless spool switch; None when its driver doesn't have one."""
        fu = self.unit_state()
        return fu["carry_on"] if fu else None

    def _observe_carried(self, frm: int, to: int, now: float) -> None:
        names = {s["slot"]: s.get("name") for s in self.spools()}
        progress = float((self.status.get("virtual_sdcard") or {}).get("progress") or 0)
        self._carried = {"from": frm, "to": to, "name": names.get(frm) or names.get(to), "pct": int(progress * 100), "at": now}

    def _carried_view(self, now: float) -> Optional[Dict[str, Any]]:
        c = self._carried
        if not c:
            return None
        if now - c["at"] > CARRIED_NOTE_SECONDS:
            self._carried = None
            return None
        if c.get("kind") == "colour":
            # A planned colour change the unit made by itself (design/colour-change/, CPhone)
            back = f" {c['was']} went back to slot {c['from'] + 1}." if c.get("was") and c.get("from") is not None else ""
            return {"from": c["from"], "to": c["to"], "pct": c["pct"], "kind": "colour",
                    "headline": f"Changed to {c['name']} at {_at_layer(c.get('layer'))}.",
                    "detail": f"As planned.{back}",
                    "push": {"title": f"changed to {c['name']}",
                             "body": f"{c['job']}, {_at_layer(c.get('layer'))}, as planned. Carrying on."},
                    "actions": [_action("carried_ok", "OK")]}
        return {"from": c["from"], "to": c["to"], "pct": c["pct"],
                "headline": f"Carried on with slot {c['to'] + 1}.",
                "detail": f"{c['name'] or 'The spool'} ran out at {c['pct']}%.",
                "actions": [_action("carried_ok", "OK")]}

    def _spares(self, spools: List[Dict[str, Any]]) -> Dict[str, Dict[int, int]]:
        """Which loaded spools would carry on for which. "in": slot -> the slot that would take
        over from it; "for": slot -> the one it stands by for (marked "spare" on its card). Only
        with carry-on switched on, and only same colour and same material."""
        out: Dict[str, Dict[int, int]] = {"in": {}, "for": {}}
        if not self.carry_on():
            return out
        by = {s["slot"]: s for s in spools}
        for s in spools:
            if s["status"] not in ("ready", "low") or not s.get("material"):
                continue
            alt = self.find_alternative(spools, s["slot"])
            if not alt or not alt.get("material"):
                continue
            out["in"][s["slot"]] = alt["slot"]
            # the spare is the one waiting: not in the head, with more on it, or the later slot
            a, b = by[s["slot"]], alt
            b_waits = (not b["in_use"]) and (a["in_use"] or (a.get("grams") or 0) < (b.get("grams") or 0)
                                             or ((a.get("grams") or 0) == (b.get("grams") or 0) and a["slot"] < b["slot"]))
            if b_waits:
                out["for"][b["slot"]] = a["slot"]
        return out

    # ---- a spool pushed into an empty slot -------------------------------------------

    def _observe_slots(self) -> None:
        """An empty slot that turns ready had a spool pushed in. Without a tag, ask what it is,
        unless the swap routine is already asking about that slot."""
        if self.unit_state() is None:
            return
        mine = self._change["slot"] if self._change and self._change.get("kind") in ("slot", "colour") else None
        for s in self.spools():
            g, st = s["slot"], s["status"]
            was, self._slot_seen[g] = self._slot_seen.get(g), st
            if st == "empty" or s["rfid"]:
                self._new_spools.pop(g, None)
            elif was == "empty" and st in ("ready", "low") and g != mine:
                self._new_spools[g] = {"name": s["name"], "color": s["color"], "material": s["material"]}

    def new_spool_notice(self, spools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not self._new_spools:
            return None
        g = min(self._new_spools)
        return {"slot": g, "headline": f"New spool in slot {g + 1}. What is it?", "detail": "It has no tag, so tell me once.",
                "choices": self._slot_choices(g, self._new_spools[g], spools)}

    @staticmethod
    def _slot_choices(slot: int, was: Optional[Dict[str, Any]], spools: List[Dict[str, Any]],
                      action: str = "set_spool") -> List[Dict[str, Any]]:
        """Quick answers to "What is it?" for a slot: what was there before, then what else is loaded."""
        out: List[Dict[str, Any]] = []
        seen: List[tuple] = []

        def add(label: str, color: Optional[str], material: Optional[str]) -> None:
            key = (_material_key(material), color)
            if not material or not color or any(k[0] == key[0] and _color_distance(k[1], color) < COLOR_MATCH for k in seen):
                return
            seen.append(key)
            out.append(_action(action, label, slot=slot, color=color, material=_material_key(material)))
        if was and was.get("name"):
            add(f"{was['name']} again", was.get("color"), was.get("material"))
        for s in spools:
            if s["slot"] != slot and s["status"] in ("ready", "low") and s.get("name") and len(out) < 4:
                add(s["name"], s.get("color"), s.get("material"))
        return out

    # ---- feed assist: the unit pushing along while it prints ----------------------------

    def feed_assist(self, slot: Optional[int]) -> Optional[bool]:
        fu = self.unit_state()
        lst = fu["feed_assist"] if fu else None
        if slot is None or lst is None or not 0 <= slot < len(lst):
            return None
        return lst[slot]

    def _assist_work(self) -> List[tuple]:
        """KlipperACE turns feed assist on after every load but forgets it on a restart. A print
        running without it, that nobody switched off, gets it back once."""
        ps = self.status.get("print_stats") or {}
        if self.direct or ps.get("state") != "printing" or not self._print_started or self.klippy_state != "ready":
            return []
        sel = self._selected_slot()
        if sel is None or sel in self._assist_off or self.feed_assist(sel) is not False:
            return []
        key = (self._job_file, sel)
        if key in self._assist_sent:
            return []
        cmds = self.unit_commands()
        if cmds is None:
            return []
        self._assist_sent.add(key)
        return [(cmds.kind, cmds.feed_assist(sel, True))]

    def slot_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        """What a person said about a slot that only the intent layer needs to remember."""
        now = time.time() if now is None else now
        op = payload.get("op")
        if op == "swap":
            return self.begin_slot_swap(int(payload["slot"]), now)
        if op == "told":
            self._new_spools.pop(int(payload["slot"]), None)
        elif op == "assist":
            (self._assist_off.discard if payload.get("on") else self._assist_off.add)(int(payload["slot"]))
        elif op == "carried_ok":
            self._carried = None
        else:
            return False
        return True

    # ---- the filament in the head ---------------------------------------

    @staticmethod
    def head_sensor_name(object_names: List[str]) -> Optional[str]:
        """The filament sensor nearest the nozzle: a toolhead sensor, else the extruder one."""
        sensors = [o for o in object_names if o.startswith("filament_switch_sensor ")]
        for word in ("toolhead", "extruder"):
            for o in sensors:
                if word in o.lower():
                    return o
        return None

    def head_loaded(self) -> Optional[bool]:
        if not self.head_sensor:
            return None
        v = (self.status.get(self.head_sensor) or {}).get("filament_detected")
        return bool(v) if isinstance(v, bool) else None

    def begin_swap(self, to: int, frm: Optional[int], purge: bool, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        spools = {s["slot"]: s for s in self.spools()}
        if to < 0 and frm is not None and frm in spools:
            self._last_unloaded = {"color": spools[frm]["color"], "material": spools[frm]["material"]}
        self._swap = {"to": to, "from": frm, "purge": purge, "started": now, "step": -1, "error": None,
                      "to_name": spools.get(to, {}).get("name") if to >= 0 else None,
                      "from_name": spools.get(frm, {}).get("name") if frm is not None else None}
        self._mismatch = None

    def end_swap(self, error: Optional[str] = None, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._last_swap_end = now
        if not self._swap:
            return
        if error:
            self._swap["error"] = error
        else:
            sw = self._swap
            spools = {s["slot"]: s for s in self.spools()}
            old = spools.get(sw["from"]) if sw["from"] is not None else None
            if old and sw["to"] >= 0:
                self._last_unloaded = {"color": old["color"], "material": old["material"]}
            if sw["to"] >= 0 and sw["purge"]:
                # The colour changed: ask whether it's coming out clean before calling it done.
                new = spools.get(sw["to"]) or {}
                done = [(k, label) for k, label in self._swap_labels(sw) if k in self._swap_wanted(sw)]
                self._change = {
                    "kind": "ace", "mid": False, "steps": [k for k, _ in done] + ["check"],
                    "labels": dict(done), "step": "check",
                    "out": {"color": old["color"], "material": old["material"], "name": old["name"]} if old else None,
                    "inn": {"color": new.get("color"), "material": new.get("material"), "name": new.get("name")},
                    "temp": int(MATERIAL_TEMPS.get(_material_key(new.get("material")) or "", DEFAULT_CHANGE_TEMP)),
                    "busy": None, "error": None, "stop": False, "more": False, "purges": 0,
                    "head_at": self.head_loaded(), "seen_in": False, "told_in": False, "heat_sent": True,
                }
            self._swap = None

    def ack_swap(self) -> None:
        self._swap = None

    def ack_head(self) -> None:
        """Someone said the spool the printer remembers really is in the head, whatever the
        sensor says. Holds until the sensor or the spool changes."""
        sel = self._selected_slot()
        if sel is not None and self.head_loaded() is False:
            self._head_ok = sel

    @staticmethod
    def _swap_labels(sw: Dict[str, Any]) -> List[tuple]:
        return [("unload", f"Taking out {sw['from_name'] or 'the old filament'}"),
                ("feed", f"Feeding {sw['to_name'] or 'the new filament'}"),
                ("nozzle", "Feeding it to the nozzle"),
                ("clean", "Cleaning the nozzle")]

    @staticmethod
    def _swap_wanted(sw: Dict[str, Any]) -> List[str]:
        return [k for k, _ in SWAP_STEPS
                if (k != "unload" or sw["from"] is not None)
                and (k not in ("feed", "nozzle") or sw["to"] >= 0)
                and (k != "clean" or sw["purge"])]

    # ---- changing filament by hand (and the check after a swap) ------------------

    def begin_change(self, kind: str, now: Optional[float] = None) -> bool:
        """Change filament ("change"), just take it out ("unload"), or load into an empty head
        ("load") on a printer without a unit. Idle, or paused mid-print for a person. The steps
        are fixed here; work() moves through them."""
        now = time.time() if now is None else now
        if self._change is not None or self._swap is not None or not self.direct:
            return False
        ps = self.status.get("print_stats") or {}
        paused = bool((self.status.get("pause_resume") or {}).get("is_paused"))
        mid = ps.get("state") in ("printing", "paused")
        if mid and (not paused or kind != "change"):
            return False
        entry = self._direct_entry()
        out = ({"color": entry["color"], "material": entry["material"], "name": entry["name"]}
               if entry["color"] or entry["material"] else None)
        target = float((self.status.get("extruder") or {}).get("target") or 0)
        if mid and target > 0:
            temp = int(target)   # the print's own temperature, for both halves
        else:
            temp = int(MATERIAL_TEMPS.get(_material_key(entry["material"]) or "", DEFAULT_CHANGE_TEMP))
        if kind == "load":
            steps = ["push", "load", "check"]
        elif kind == "unload":
            steps = ["warm", "unload", "pull"]
        elif kind == "change":
            steps = ["warm", "unload", "pull", "push", "load", "check"]
        else:
            return False
        if mid:
            steps.remove("warm")   # it's warm, and the print's temperature stays as it is
            reason = (self._pause_reason or {}).get("phase")
            if reason == "color_change" and self.head_loaded() is False:
                # The printer's own M600 already took it out: start at the new spool.
                steps = [s for s in steps if s not in ("unload", "pull")]
        self._change = {"kind": kind, "mid": mid, "steps": steps, "step": steps[0], "out": out, "inn": None,
                        "temp": temp, "busy": None, "error": None, "stop": False, "more": False, "purges": 0,
                        "head_at": self.head_loaded(), "seen_in": False, "told_in": False, "heat_sent": False}
        self._keep_warm_until = None
        return True

    def begin_slot_swap(self, slot: int, now: Optional[float] = None) -> bool:
        """Swap the spool in one slot of a filament unit (design/slots/, B). Idle only. Out of the
        head first if it's there, then pulled back until the slot reads empty; work() drives it."""
        if self._change is not None or self._swap is not None or self.direct or self.klippy_state != "ready":
            return False
        if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            return False
        s = next((x for x in self.spools() if x["slot"] == slot), None)
        if not s or s["status"] == "empty":
            return False
        in_head = slot == self._selected_slot()
        steps = (["unload"] if in_head else []) + ["pullback", "swap", "what"]
        name = s["name"] or f"slot {slot + 1}"
        self._change = {"kind": "slot", "slot": slot, "mid": False, "steps": steps, "step": steps[0],
                        "out": {"color": s["color"], "material": s["material"], "name": s["name"]}, "inn": None,
                        "labels": {k: v.format(out=name) for k, v in SLOT_LABELS.items()},
                        "temp": 0, "busy": None, "error": None, "stop": False, "more": False, "purges": 0,
                        "head_at": self.head_loaded(), "seen_in": False, "told_in": False, "heat_sent": True,
                        "pulled": 0, "stuck": False, "seen_out": False}
        self._new_spools.pop(slot, None)
        self._keep_warm_until = None
        return True

    def _slot_now(self, slot: int) -> Optional[Dict[str, Any]]:
        return next((s for s in self.spools() if s["slot"] == slot), None)

    def _finish_slot(self) -> None:
        """The new spool is in. Say what it is in the unit's saved variables, unless its tag does."""
        c = self._change
        s = self._slot_now(c["slot"]) or {}
        inn = c["inn"] or {}
        if inn.get("material") and not s.get("rfid"):
            color = inn.get("color") or s.get("color") or "#FFFFFF"
            for kind, script in plan_set_spool({"slot": c["slot"], "color": color, "material": inn["material"]}, self):
                if kind == ActionPlan.GCODE:
                    self._change_queue.append(("gcode", script))
        self._change = None

    def _work_slot(self, c: Dict[str, Any], out: List[tuple]) -> List[tuple]:
        """One pass of the swap routine; returns what to send."""
        slot = c["slot"]
        cmds = self.unit_commands()
        if cmds is None:
            return out
        for _ in range(len(c["steps"]) + 1):
            if self._change is not c:
                break
            step = c["step"]
            s = self._slot_now(slot) or {}
            st = s.get("status")
            if step == "unload":
                c["busy"] = "unload"
                if not filament_units.can_change_tool(cmds):
                    return out
                return out + [(cmds.long_kind, cmds.change_tool(-1))]
            if step == "pullback":
                if st == "empty":
                    c["seen_out"] = True
                    self._enter("swap")
                    continue
                if c["pulled"] >= PULLBACK_MAX_MM:
                    c["stuck"] = True   # the slot never said empty: a person pulls the rest
                    self._enter("swap")
                    continue
                c["busy"] = "pullback"
                c["pulled"] += PULLBACK_STEP_MM
                return out + [(cmds.long_kind, cmds.move(slot, -PULLBACK_STEP_MM))]
            if step == "swap":
                if st == "empty":
                    c["seen_out"] = True
                elif st in ("ready", "low") and c["seen_out"]:
                    c["seen_in"] = True
                if c["seen_in"] or c["told_in"]:
                    if s.get("rfid"):
                        self._change = None   # its tag says what it is
                        break
                    self._enter("what")
                    continue
            if step == "what":
                if s.get("rfid") or c["inn"]:
                    self._finish_slot()
                    break
            break
        out, self._change_queue = out + self._change_queue, []
        return out

    # ---- colour changes on a printer with a unit (design/colour-change/, C and A) -------------------

    def note_check(self, filename: str, metadata: Optional[Dict[str, Any]]) -> None:
        """The Print sheet showed this file's colour changes: remember them, to check the plan it sends back."""
        changes = (metadata or {}).get("colour_changes") or []
        if not filename or not changes:
            return
        self._checked.pop(filename, None)
        self._checked[filename] = {"material": _material_key(job_material(metadata or {})),
                                   "changes": [{"layer": c.get("layer"), "color": _hex_color(c.get("color"))} for c in changes]}
        while len(self._checked) > CHECKED_FILES_KEPT:
            self._checked.pop(next(iter(self._checked)))

    def restore_colour_plan(self, record: Any) -> None:
        """The stored plan, at start. Anything that doesn't look like one is ignored."""
        if (isinstance(record, dict) and isinstance(record.get("filename"), str) and isinstance(record.get("changes"), list)
                and isinstance(record.get("at"), (int, float))):
            self.colour_plan = {k: record.get(k) for k in ("filename", "changes", "at", "started")}

    def set_colour_plan(self, filename: str, changes: List[Dict[str, Any]], now: float) -> None:
        self.colour_plan = {"filename": filename, "changes": changes, "at": now, "started": False}
        self.colour_plan_dirty = True

    def _claim_colour_plan(self, filename: Optional[str], now: float) -> None:
        """A print started. The plan is for it if it's the file the plan was made for, started soon after (or
        already claimed, after a restart mid-print); otherwise the plan was for a print that never happened."""
        plan = self.colour_plan
        if not plan:
            return
        if plan.get("started"):
            if filename and plan["filename"] == filename:
                return
        elif filename and plan["filename"] == filename and now - float(plan["at"]) <= COLOUR_PLAN_FRESH_SECONDS:
            plan["started"] = True
            self.colour_plan_dirty = True
            return
        self.colour_plan, self.colour_plan_dirty = None, True

    def _colour_now(self) -> Dict[str, Any]:
        """The colour change the print is paused at: which one (counted from 1), its layer and colour from the
        file, and the plan's entry for it."""
        ps = self.status.get("print_stats") or {}
        filename = ps.get("filename") or None
        meta = self.metadata if self.metadata_file == filename else {}
        changes = meta.get("colour_changes") or []
        n = (self._pause_reason or {}).get("n") or self._colour_n or 1
        ch = changes[n - 1] if 0 < n <= len(changes) else {}
        plan = self.colour_plan if self.colour_plan and self.colour_plan.get("started") and self.colour_plan["filename"] == filename else None
        entry = plan["changes"][n - 1] if plan and 0 < n <= len(plan["changes"]) else None
        layer = ch.get("layer") or (entry or {}).get("layer")
        if not layer:
            cur = (ps.get("info") or {}).get("current_layer")
            layer = int(cur) if isinstance(cur, (int, float)) and cur else None
        return {"n": n, "layer": layer, "color": _hex_color(ch.get("color") or (entry or {}).get("color")),
                "entry": entry, "plan": plan, "material": _material_key(job_material(meta)),
                "layers": (ps.get("info") or {}).get("total_layer") or meta.get("layer_count")}

    def _colour_pause_n(self) -> int:
        return (self._pause_reason or {}).get("n") or self._colour_n or 1

    def _paused_for_colour(self) -> bool:
        ps = self.status.get("print_stats") or {}
        paused = bool((self.status.get("pause_resume") or {}).get("is_paused")) or ps.get("state") == "paused"
        getting_ready = bool(self.prep_stage())
        return (paused and not getting_ready and not self.direct
                and (self._pause_reason or {}).get("phase") == "color_change")

    def _maybe_auto_colour(self, now: float) -> None:
        """C: paused at a colour change the Print sheet planned onto a loaded spool. Nobody's needed: the unit
        switches, pushes more through, and the print carries on. Once per change; if it fails, the pause."""
        if (self._change is not None or self._swap is not None or self.klippy_state != "ready"
                or not filament_units.can_change_tool(self.unit_commands()) or not self._paused_for_colour()):
            return
        info = self._colour_now()
        entry, n = info["entry"], info["n"]
        if not entry or n in self._colour_tried or not isinstance(entry.get("slot"), int):
            return
        s = self._slot_now(entry["slot"])
        if not s or s["status"] not in ("ready", "low"):
            return
        self._colour_tried.add(n)
        if entry["slot"] == self._selected_slot():
            # what was planned is already in the head: nothing to switch
            self._colour_done.add(n)
            self._change_queue.append(("gcode", "RESUME"))
            return
        self.begin_colour(entry["slot"], "switch", auto=True, now=now)

    def begin_colour(self, slot: int, flow: str, auto: bool = False, now: Optional[float] = None) -> bool:
        """Switch to a spool mid-print, at a colour-change pause. flow: "switch" (a loaded spool), "put" (a new
        spool into an empty slot first), "swap" (a full slot's spool swapped first; SLOT_SWAP_WHILE_PAUSED).
        auto: planned, so nobody checks; a longer purge instead, then the print carries on."""
        now = time.time() if now is None else now
        if self._change is not None or self._swap is not None or self.direct or not self._paused_for_colour():
            return False
        s = self._slot_now(slot)
        if not s:
            return False
        frm = self._selected_slot()
        if flow == "switch":
            if s["status"] not in ("ready", "low") or slot == frm:
                return False
            steps = (["unload"] if frm is not None else []) + ["feed", "nozzle", "clean"] + ([] if auto else ["check"])
        elif flow == "put":
            if s["status"] != "empty":
                return False
            steps = ["put", "what", "switch", "check"]
        elif flow == "swap":
            if not SLOT_SWAP_WHILE_PAUSED or s["status"] not in ("ready", "low") or slot == frm:
                return False
            steps = ["pullback", "put", "what", "switch", "check"]
        else:
            return False
        info = self._colour_now()
        old = self._slot_now(frm) if frm is not None else None
        target = float((self.status.get("extruder") or {}).get("target") or 0)
        ps = self.status.get("print_stats") or {}
        self._change = {
            "kind": "colour", "flow": flow, "auto": auto, "slot": slot, "frm": frm, "mid": True,
            "steps": steps, "step": steps[0], "sub": None,
            "out": {"color": old["color"], "material": old["material"], "name": old["name"]} if old else None,
            "inn": {"color": s["color"], "material": s["material"], "name": s["name"]} if flow == "switch" else None,
            "was": {"color": s["color"], "material": s["material"], "name": s["name"]} if flow == "swap" else None,
            "want": {"color": info["color"], "material": info["material"]},
            "n": info["n"], "layer": info["layer"], "layers": info["layers"], "job": _pretty_job_name(ps.get("filename")),
            "temp": int(target) if target > 0 else int(MATERIAL_TEMPS.get(_material_key(s.get("material")) or "", DEFAULT_CHANGE_TEMP)),
            "busy": None, "error": None, "stop": False, "more": False, "purges": 0, "switched": False,
            "head_at": self.head_loaded(), "seen_in": False, "told_in": False, "heat_sent": True,
            "pulled": 0, "stuck": False, "seen_out": flow == "put",
        }
        self._new_spools.pop(slot, None)
        self._colour_attended = now
        return True

    def colour_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        """The plan from the Print sheet, or a choice at the pause."""
        now = time.time() if now is None else now
        op = payload.get("op")
        if op == "plan":
            self.set_colour_plan(str(payload["filename"]), list(payload["changes"]), now)
            return True
        if op == "choose":
            self._colour_attended = now
            how = payload.get("how")
            if how == "keep":
                return True   # the print carries on as it is
            return self.begin_colour(int(payload["slot"]), {"switch": "switch", "put_in": "put", "swap": "swap"}.get(how, ""), now=now)
        return False

    def _work_colour(self, c: Dict[str, Any], out: List[tuple], now: float) -> List[tuple]:
        """One pass of a colour switch mid-print; returns what to send."""
        slot = c["slot"]
        cmds = self.unit_commands()
        for _ in range(len(c["steps"]) + 2):
            if self._change is not c or c["busy"] or c["error"]:
                break
            if c["more"]:
                c["more"], c["busy"] = False, "purge"
                return out + [("macro", self._purge_gcode(MORE_PURGE_MM))]
            step = c["step"]
            s = self._slot_now(slot) or {}
            st = s.get("status")
            if step == "pullback":
                if st == "empty":
                    c["seen_out"] = True
                    self._enter("put")
                    continue
                if c["pulled"] >= PULLBACK_MAX_MM:
                    c["stuck"] = True
                    self._enter("put")
                    continue
                c["busy"] = "pullback"
                c["pulled"] += PULLBACK_STEP_MM
                if cmds is None:
                    break
                return out + [(cmds.long_kind, cmds.move(slot, -PULLBACK_STEP_MM))]
            if step == "put":
                if st == "empty":
                    c["seen_out"] = True
                elif st in ("ready", "low") and c["seen_out"]:
                    c["seen_in"] = True
                if c["seen_in"] or c["told_in"]:
                    if s.get("rfid") and (s.get("material") or s.get("color")):
                        c["inn"] = {"color": s.get("color"), "material": s.get("material"), "name": s.get("name")}
                        self._enter("switch")   # its tag says what it is
                    else:
                        self._enter("what")
                    continue
                break
            if step == "what":
                inn = c["inn"]
                if not inn:
                    break
                if inn.get("material") and not s.get("rfid"):
                    color = inn.get("color") or s.get("color") or "#FFFFFF"
                    for kind, script in plan_set_spool({"slot": slot, "color": color, "material": inn["material"]}, self):
                        if kind == ActionPlan.GCODE:
                            self._change_queue.append(("gcode", script))
                self._enter("switch")
                continue
            if step in SWITCH_STEPS or step == "switch":
                if not c["switched"]:
                    c["busy"], c["sub"] = "swap", None
                    out, self._change_queue = out + self._change_queue, []
                    if not filament_units.can_change_tool(cmds):
                        break
                    return out + [(cmds.long_kind, cmds.change_tool(slot))]
                if c["auto"]:
                    if not c["purges"]:
                        c["busy"] = "purge"
                        return out + [("macro", self._purge_gcode(AUTO_PURGE_MM))]
                    self._finish_auto(now)
                    return out + [("gcode", "RESUME")]
                self._enter("check")
                continue
            break   # check: a person looks
        out, self._change_queue = out + self._change_queue, []
        return out

    def _finish_auto(self, now: float) -> None:
        """The planned switch is done: the print carries on, and the phone hears it afterwards (CPhone)."""
        c = self._change
        progress = float((self.status.get("virtual_sdcard") or {}).get("progress") or 0)
        self._carried = {"kind": "colour", "from": c["frm"], "to": c["slot"], "name": (c["inn"] or {}).get("name") or f"slot {c['slot'] + 1}",
                         "was": (c["out"] or {}).get("name"), "layer": c["layer"], "job": c["job"] or "The print",
                         "pct": int(progress * 100), "at": now}
        self._colour_done.add(c["n"])
        self._change = None

    def _colour_tile(self, s: Dict[str, Any], head: Optional[int], material: Optional[str], cw: Optional[str],
                     match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """One slot at the pause (A): what tapping it would do, in words, and the button that does it."""
        g, n = s["slot"], s["slot"] + 1
        name = s.get("name") or f"Slot {n}"
        e: Dict[str, Any] = {"slot": g, "color": s.get("color"), "status": s["status"], "in_use": g == head,
                             "word": _color_name(s["color"]) if s.get("color") else (s.get("material") or f"Slot {n}"),
                             "sub": s.get("material") or "", "tone": None, "how": None, "action": None,
                             "says": None, "says_away": None, "link": None, "ask": None, "confirm_away": None,
                             "at_printer": False, "why": None}
        if s["status"] == "empty":
            what = f"a {cw} spool" if cw else "a spool"
            e.update(word="Empty", sub="put one in", how="put_in", at_printer=True,
                     action=_action("colour_choose", f"Put {what} in slot {n}", primary=True, style="amber", slot=g, how="put_in"),
                     says=[f"Slot {n} is free.", f" Put {what} on and push its end in. I'll notice."])
            return e
        if s["status"] not in ("ready", "low"):
            e.update(word="?", sub="can't tell", why=f"I can't read slot {n} right now.")
            return e
        if g == head and self.head_loaded() is False:
            # an M600 that unloads (Workshop's does UNLOAD_FILAMENT): carrying on would print with nothing in the head
            e.update(sub="out of the head", tone="accent", why=f"{name} is out of the head.")
            return e
        if g == head:
            e.update(sub="in the head", tone="accent", how="keep",
                     action=_action("colour_choose", f"Carry on with {name}", primary=True, style="amber", slot=g, how="keep"),
                     says=[name, f", slot {n}. Nothing changes; the print carries on with it."])
            e["says_away"] = e["says"]
            return e
        differs = bool(material and s.get("material") and _material_key(s["material"]) != material)
        if s["status"] == "low":
            e.update(sub=f"{s.get('material') or ''}, low".lstrip(", "), tone="amber")
        if differs:
            e["tone"] = "amber"
        e.update(how="switch",
                 action=_action("colour_choose", f"Switch to {name}", primary=True, style="amber", slot=g, how="switch"),
                 says=[name, f", slot {n}. I'll switch and clean the nozzle."],
                 says_away=[name, f", slot {n}. I'll switch, clean the nozzle and show you the check here."],
                 confirm_away={"text": f"Switch to {name} from here? Nobody needs to be at the printer; you'll check it on the camera.",
                               "label": "Yes, switch"})
        if match and match["slot"] == g and cw:
            e["says"] = [f"The file asks for {cw}:", f" {name}, slot {n}."]
        if differs:
            e["ask"] = {"text": f"{name} on a {material} print may not stick. Use it anyway?", "label": "Use it anyway"}
        if SLOT_SWAP_WHILE_PAUSED:
            e["link"] = _action("colour_choose", f"Or put a different spool in slot {n}", slot=g, how="swap")
            e["link_at_printer"] = True
        return e

    def _colour_pause(self, spools: List[Dict[str, Any]], job: Optional[Dict[str, Any]], now: float) -> tuple:
        """A: the pause, only for a colour change that can't be automatic, and it says why. Returns headline,
        detail, actions and the `colour` the screens draw (a tile per slot)."""
        info = self._colour_now()
        entry, plan, n = info["entry"], info["plan"], info["n"]
        material = info["material"]
        want = info["color"]
        cw = _colour_word(want) if want else None
        loaded = [s for s in spools if s["status"] in ("ready", "low")]
        match = _closest({"color": want, "material": material}, loaded) if want else None
        head = self._selected_slot()
        job_name = job["name"] if job else "The print"
        planned = entry.get("slot") if entry else None
        planned_spool = next((s for s in loaded if s["slot"] == planned), None) if isinstance(planned, int) else None
        if isinstance(planned, int) and n in self._colour_tried and planned_spool:
            reason = "not_switched"
            detail = f"The unit couldn't switch to {planned_spool['name'] or 'slot ' + str(planned + 1)} by itself."
        elif want and match is None:
            reason = "not_loaded"
            detail = f"The file asks for {cw}, and there's no {cw} in the unit."
        elif planned == "pause":
            reason = "asked"
            detail = f"You asked to choose here when you started {job_name}."
        elif isinstance(planned, int):
            reason = "plan_gone"
            detail = f"The spool planned for {_at_layer(info['layer'])} isn't in the unit anymore."
        else:
            reason = "not_planned"
            detail = f"{job_name} was started outside Elyir Bench, so this one wasn't planned."
        tiles = [self._colour_tile(s, head, material, cw, match) for s in spools]
        by = {t["slot"]: t for t in tiles}
        picked = None
        if reason == "not_loaded":
            picked = next((t["slot"] for t in tiles if t["how"] == "put_in"), None)
        elif match is not None:
            picked = match["slot"]
        elif planned_spool is not None:
            picked = planned
        if picked is None and head is not None and by.get(head, {}).get("how") == "keep":
            picked = head
        if picked is None:
            picked = next((t["slot"] for t in tiles if t["how"]), None)
        empties = [t["slot"] + 1 for t in tiles if t["how"] == "put_in"]
        away_note = None
        if empties:
            which = f"Slot {empties[0]} is" if len(empties) == 1 else f"Slots {_join([str(e) for e in empties])} are"
            away_note = f"{which} empty. Putting a spool in needs someone at the printer."
        units = [{"name": u["name"], "slots": u["slots"]} for u in self.unit_list(spools, now)]
        stop = _action("cancel", "Stop this print", hold=True)
        first = by.get(picked, {}).get("action") if picked is not None else None
        actions = [first, stop] if first else [_action("resume", "Carry on", primary=True, style="amber"), stop]
        colour = {"reason": reason, "n": n, "layer": info["layer"], "color": want, "material": material,
                  "asks": f"The file asks for {cw}." if cw and reason != "not_loaded" else None,
                  "picked": picked, "units": units, "slots": tiles, "away_note": away_note}
        return "Time to change the color.", detail, actions, colour

    def _colour_steps(self) -> List[Dict[str, Any]]:
        c = self._change
        out_name = (c["out"] or {}).get("name") or "the old filament"
        in_name = (c["inn"] or {}).get("name") or "the new filament"
        labels = {"unload": f"Taking out {out_name}", "feed": f"Feeding {in_name}", "nozzle": "Feeding it to the nozzle",
                  "clean": "Cleaning the nozzle", "check": "Check it",
                  "pullback": f"Pulling {(c['was'] or {}).get('name') or 'it'} back to its spool",
                  "put": "Swap the spool" if c["flow"] == "swap" else "Put the new spool in",
                  "what": "Say what it is", "switch": f"Switch to {in_name}" if c["inn"] else "Switch to it"}
        cur = c["steps"].index(c["step"]) if c["step"] in c["steps"] else len(c["steps"])
        sub = dict(self._swap_labels({"from_name": out_name, "to_name": in_name})).get(c["sub"]) if c["sub"] else None
        out = []
        for i, s in enumerate(c["steps"]):
            e = {"id": s, "label": labels[s], "status": "done" if i < cur else ("now" if i == cur else "todo")}
            if s in ("put", "what", "check"):
                e["you"] = True
            if s == "switch" and i == cur and sub:
                e["detail"] = sub
            out.append(e)
        return out

    def _colour_view(self) -> Dict[str, Any]:
        c = self._change
        step = c["step"]
        idx = c["steps"].index(step) if step in c["steps"] else len(c["steps"]) - 1
        art = {"unload": "out", "feed": "push", "nozzle": "push", "clean": "purge", "check": "purge", "switch": "push",
               "pullback": "back", "put": "insert", "what": "still"}.get(step, "still")
        if c["busy"] == "purge":
            art = "purge"
        pill = None
        if c["auto"] and c["layer"]:
            pill = f"Layer {c['layer']} of {c['layers']}" if c["layers"] else f"Layer {c['layer']}"
        choices: List[Dict[str, Any]] = []
        if step == "what":
            # the file's colour first, in the print's material, then what was there and what else is loaded
            want = c["want"] or {}
            if want.get("color") and want.get("material"):
                choices.append(_action("change_what", _spool_name(want["color"], want["material"]) or "",
                                       color=want["color"], material=want["material"]))
            for ch in self._slot_choices(c["slot"], c["was"], self.spools(), "change_what"):
                if len(choices) >= 3:
                    break
                if not any(x["label"] == ch["label"] for x in choices):
                    choices.append(ch)
        return {"kind": "colour", "flow": c["flow"], "auto": c["auto"], "step": step, "art": art, "slot": c["slot"],
                "out": c["out"], "in": c["inn"], "n": idx + 1, "of": len(c["steps"]), "pill": pill,
                "you": step in ("put", "what", "check") and not c["busy"] and not c["error"],
                "ask": step == "what" and not c["inn"], "choices": choices,
                # said first where the camera is shown, the person's eyes on the check (SPhone)
                "look": "Look at the nozzle on the camera." if step == "check" else None}

    def _colour_intent(self, now: float, job: Optional[Dict[str, Any]]) -> tuple:
        """state, phase, headline, detail, actions, steps, expires, raw while switching colour mid-print."""
        c = self._change
        steps = self._colour_steps()
        step, n = c["step"], c["slot"] + 1
        inn, out = c["inn"] or {}, c["out"] or {}
        in_name = inn.get("name") or f"slot {n}"
        expires = max(self._pause_since or now, self._colour_attended or 0) + NEEDS_YOU_HOLD_SECONDS
        stop = _action("cancel", "Stop this print", hold=True)
        if c["error"]:
            what = f"Pulling slot {n} back" if step == "pullback" else (
                "Pushing more through" if step == "check" else f"Switching to {in_name}")
            return ("problem", "change_failed", f"{what} didn't finish.",
                    "Check the tube from the unit isn't tangled or kinked, then try again.",
                    [_action("change_retry", "Try again", primary=True, style="red"), _action("change_end", "It's sorted")],
                    steps, expires, c["error"])
        if c["busy"] == "purge" and not c["auto"]:
            return ("preparing", "colour_purge", "Pushing more through", "Keep clear of the nozzle.", [stop], steps, expires, "")
        if step == "pullback":
            name = (c["was"] or {}).get("name") or f"the spool in slot {n}"
            return ("preparing", "colour_pullback", f"Pulling {name} back to its spool",
                    f"Slot {n}. About a minute. Then it's your turn.", [stop], steps, expires, "")
        if step in SWITCH_STEPS or step == "switch":
            if c["auto"]:
                detail = f"{_at_layer(c['layer']).capitalize()}, as planned. Nobody's needed."
                return ("preparing", "colour_auto", f"Switching to {in_name}", detail, [stop], steps, None, "")
            return ("preparing", "colour_switch", f"Switching to {in_name}", f"From slot {n}. Keep clear of the nozzle.",
                    [stop], steps, expires, "")
        if step == "put":
            if c["flow"] == "swap":
                if c["stuck"]:
                    detail = (f"If its end is still in slot {n}, pull it out gently. Then put the new spool on and push its end in "
                              "until the unit grabs it. I'll notice, then switch to it.")
                else:
                    detail = "Take the old one off, put the new one on and push its end in until the unit grabs it. I'll notice, then switch to it."
                headline = f"Swap the spool in slot {n}."
            else:
                headline = f"Put the new spool in slot {n}."
                detail = "Push its end in until the unit grabs it. I'll notice, ask what it is, then switch to it."
            return ("needs_you", "change_colour_put", headline, detail, [_action("change_in", "It's in"), stop], steps, expires, "")
        if step == "what":
            return ("needs_you", "change_colour_what", f"What's in slot {n}?", "It has no tag, so tell me once. Then I'll switch to it.",
                    [stop], steps, expires, "")
        # check
        colour = _colour_word(inn.get("color")) if inn.get("color") else ""
        was = _colour_word(out.get("color")) if out.get("color") else ""
        name = c["job"] or "The print"
        after = f"{name} carries on from layer {c['layer'] + 1}." if c["layer"] else f"{name} carries on."
        if was and was != colour:
            detail = f"If there's still {was} in it, I'll push more through. Then {after}"
        else:
            detail = f"If it still looks mixed, I'll push more through. Then {after}"
        return ("needs_you", "change_colour_check", f"Is it coming out clean {colour}?" if colour else "Is it coming out clean?",
                detail, [_action("change_good", "Looks good, carry on", primary=True, style="amber"),
                         _action("change_more", "Push more through")], steps, expires, "")

    def _enter(self, step: str) -> None:
        c = self._change
        c.update(step=step, head_at=self.head_loaded(), seen_in=False, told_in=False)

    def _load_temp(self) -> int:
        c = self._change
        if c["mid"]:
            return c["temp"]
        return int(MATERIAL_TEMPS.get(_material_key((c["inn"] or {}).get("material")) or "", c["temp"]))

    def _purge_gcode(self, mm: int = MORE_PURGE_MM) -> str:
        c = self._change
        t = c["temp"] if c["mid"] else self._load_temp()
        return (f"M109 S{t}\nSAVE_GCODE_STATE NAME=elyir_bench_purge\nM83\nG1 E{mm} F150\n"
                "RESTORE_GCODE_STATE NAME=elyir_bench_purge")

    def _finish_change(self, now: float) -> None:
        """Looks good, or the filament is out after "Take it out". Remember what's loaded now.
        Mid-print, wait for Carry on; idle, stay warm a while in case a print comes next."""
        c = self._change
        if c["kind"] == "colour":
            self._change = None   # "Looks good, carry on": the print resumes in the same tap
            return
        if c["kind"] in ("change", "load") and c["inn"] and c["inn"].get("material"):
            self.remember_spool(c["inn"].get("color"), c["inn"]["material"], "told", now=now)
        if c["mid"]:
            c["step"] = "resume"
            return
        if c["kind"] == "ace":
            if c["purges"]:
                self._change_queue.append(("gcode", "M104 S0"))   # the swap had left it cold
        else:
            self._keep_warm_until = now + KEEP_WARM_SECONDS
        self._change = None

    def _end_change(self) -> None:
        """Stopped, or "It's sorted" after a failure. Idle: heaters off. Mid-print: back to the pause."""
        c = self._change
        if c and not c["mid"] and c["kind"] != "ace":
            self._change_queue.append(("gcode", "TURN_OFF_HEATERS"))
        self._change = None

    def change_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        """A person's answer to the routine. Returns False when it doesn't apply right now."""
        now = time.time() if now is None else now
        op = payload.get("op")
        if op == "start":
            return self.begin_change(str(payload.get("kind") or "change"), now)
        c = self._change
        if c is None:
            return False
        step = c["step"]
        if c["kind"] == "colour":
            self._colour_attended = now   # a person did something: the 20 minutes start again
        if op == "stop":
            if c["busy"]:
                c["stop"] = True
            else:
                self._end_change()
            return True
        if op == "end":
            self._end_change() if c["error"] else self._finish_end()
            return True
        if op == "retry":
            if not c["error"]:
                return False
            c["error"] = None
            if step == "check":
                c["more"] = True
            return True
        if c["busy"] or c["error"]:
            return False
        if op == "out" and step == "pull":
            self._after_pull(now)
        elif op == "in" and step in ("push", "swap", "put"):
            c["told_in"] = True
        elif op == "what" and step in ("push", "load", "what"):
            c["inn"] = {"color": payload.get("color"), "material": payload.get("material"),
                        "name": _spool_name(payload.get("color"), payload.get("material"))}
        elif op == "good" and step == "check":
            self._finish_change(now)
        elif op == "more" and step in ("check", "resume"):
            c["step"], c["more"] = "check", True
        else:
            return False
        return True

    def _finish_end(self) -> None:
        """Carry on after a mid-print change: the routine is over, the print resumes."""
        self._change = None

    def _after_pull(self, now: float) -> None:
        if self._change["kind"] == "unload":
            self._finish_change(now)
        else:
            self._enter("push")

    def change_done(self, error: Optional[str] = None, now: Optional[float] = None) -> None:
        """A background command of the routine finished (or failed)."""
        now = time.time() if now is None else now
        c = self._change
        if c is None:
            return
        busy, c["busy"] = c["busy"], None
        if error:
            c["error"] = error
            return
        if c["stop"]:
            self._end_change()
            return
        if c["kind"] == "slot":
            if busy == "unload":
                self._change_queue.append(("gcode", "M104 S0"))   # nothing more needs the nozzle hot
                self._enter("pullback")
            return   # a pull back: work() looks at the slot again
        if c["kind"] == "colour":
            if busy == "swap":
                c["switched"] = True
                if c["out"]:
                    self._last_unloaded = {"color": c["out"]["color"], "material": c["out"]["material"]}
                if c["step"] in SWITCH_STEPS:
                    c["step"] = "clean" if "clean" in c["steps"] else c["step"]
            elif busy == "purge":
                c["purges"] += 1
                if not c["auto"]:
                    self._enter("check")
            return   # work() takes the next step
        if busy == "unload":
            self._enter("pull")
        elif busy == "load":
            self._enter("check")
        elif busy == "purge":
            c["purges"] += 1
            self._enter("check")

    def work(self, now: Optional[float] = None) -> List[tuple]:
        """What to send to the printer now, as ("gcode", script) to run and wait for, or
        ("macro", script) to run in the background and report with change_done(). Call it
        after every status update and on a timer; it only ever hands a command out once."""
        now = time.time() if now is None else now
        out, self._change_queue = list(self._change_queue), []
        out += self._update_warm(now)
        out += self._update_hands(now)
        out += self._assist_work()
        if self._keep_warm_until is not None:
            pstate = (self.status.get("print_stats") or {}).get("state")
            if pstate in ("printing", "paused") or self._change is not None:
                self._keep_warm_until = None
            elif now >= self._keep_warm_until:
                self._keep_warm_until = None
                if (self.status.get("extruder") or {}).get("target") or (self.status.get("heater_bed") or {}).get("target"):
                    out.append(("gcode", "TURN_OFF_HEATERS"))
        c = self._change
        if c is None or c["error"] or c["busy"]:
            return out
        if c["kind"] == "slot":
            return self._work_slot(c, out)
        if c["kind"] == "colour":
            return self._work_colour(c, out, now)
        if c["more"]:
            c["more"], c["busy"] = False, "purge"
            return out + [("macro", self._purge_gcode())]
        loaded = self.head_loaded()
        ext = self.status.get("extruder") or {}
        for _ in range(len(CHANGE_LABELS)):   # a step can finish at once and hand over to the next
            if self._change is not c:
                break   # that was the last step
            step = c["step"]
            if step == "warm":
                if not c["heat_sent"]:
                    c["heat_sent"] = True
                    return out + [("gcode", f"M104 S{c['temp']}")]
                if float(ext.get("temperature") or 0) >= c["temp"] - 3:
                    self._enter("unload")
                    continue
            elif step == "unload":
                c["busy"] = "unload"
                return out + [("macro", f"UNLOAD_FILAMENT TEMP={c['temp']}")]
            elif step == "pull":
                # the sensor has to see it go; one that was already clear can't, so a person says
                if c["head_at"] is True and loaded is False:
                    self._after_pull(now)
                    continue
            elif step == "push":
                if loaded is True and c["head_at"] is not True:
                    c["seen_in"] = True
                if c["inn"] and (c["seen_in"] or c["told_in"]):
                    self._enter("load")
                    continue
            elif step == "load":
                c["busy"] = "load"
                return out + [("macro", f"LOAD_FILAMENT TEMP={self._load_temp()}")]
            break
        return out

    def keep_warm_minutes(self, now: float) -> Optional[int]:
        if self._keep_warm_until is None:
            return None
        return max(1, int((self._keep_warm_until - now + 59) // 60))

    # ---- warming up before a print -------------------------------------------------

    def chamber_limit(self) -> float:
        """How warm this printer's PRINT_START (or Elyir Bench's start macro) waits for the chamber to get; 0
        when it never waits."""
        limit = 0.0
        for name in ("gcode_macro _PRINT_START_SETTINGS", ELYIR_BENCH_START_SETTINGS):
            try:
                limit = limit or float((self.status.get(name) or {}).get("chamber_max") or 0)
            except (TypeError, ValueError):
                pass
        return limit if limit > 0 and self.chamber() is not None else 0.0

    def warm_targets(self, material: str) -> Dict[str, int]:
        m = _material_key(material) or ""
        chamber = self.chamber_limit() if m in WARM_CHAMBER_MATERIALS else 0.0
        return {"bed": WARM_BED.get(m, 60), "chamber": int(chamber), "nozzle": WARM_NOZZLE}

    def begin_warm(self, material: str, now: Optional[float] = None) -> bool:
        """Warm up for a material while the printer is idle. The heaters are set by work()."""
        now = time.time() if now is None else now
        if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            return False
        if self._change is not None or self._swap is not None:
            return False
        m = _material_key(material)
        if not m:
            return False
        t = self.warm_targets(m)
        self._warm = dict(t, material=m, started=now, reached=None, until=None, seen=False)
        self._keep_warm_until = None
        self._change_queue += [("gcode", f"M140 S{t['bed']}"), ("gcode", f"M104 S{t['nozzle']}")]
        return True

    def warm_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        if payload.get("op") == "start":
            return self.begin_warm(str(payload.get("material") or ""), now)
        if payload.get("op") == "stop":
            self._warm = None
            return True
        return False

    def _update_warm(self, now: float) -> List[tuple]:
        """Notice when it's warm, hand over to a print, or give up after a while. Returns
        commands to send (heaters off once it has stayed warm long enough)."""
        w = self._warm
        if w is None:
            return []
        if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            self._warm = None   # PRINT_START takes it from here
            return []
        bed = self.status.get("heater_bed") or {}
        if bed.get("target"):
            w["seen"] = True
        elif w.get("seen") or now - w["started"] > WARM_TARGET_GRACE:
            self._warm = None   # someone turned the heaters off, or the printer never took it
            return []
        if w["reached"] is None:
            bed_ok = float(bed.get("temperature") or 0) >= w["bed"] - 2
            ch = (self.chamber() or {}).get("temperature")
            chamber_ok = not w["chamber"] or (ch is not None and ch >= w["chamber"])
            if bed_ok and (chamber_ok or now - w["started"] >= WARM_CHAMBER_GIVE_UP):
                w["reached"], w["until"] = now, now + WARM_HOLD_SECONDS
        if w["until"] is not None and now >= w["until"]:
            self._warm = None
            return [("gcode", "TURN_OFF_HEATERS")]
        return []

    def _warm_view(self, now: float, spools: List[Dict[str, Any]], show_options: bool) -> Optional[Dict[str, Any]]:
        """What the screens show about warming up: progress while it runs, and the answers to
        "What are you printing next?" while the printer is free to start."""
        w = self._warm
        out: Dict[str, Any] = {"active": w is not None}
        if w is not None:
            bed = self.status.get("heater_bed") or {}
            ch = (self.chamber() or {}).get("temperature")
            bed_t = float(bed.get("temperature") or 0)
            secs = max(0.0, (w["bed"] - bed_t) / WARM_BED_RATE)
            if w["chamber"] and ch is not None:
                secs = max(secs, (w["chamber"] - ch) / WARM_CHAMBER_RATE)
            out.update(material=w["material"], warm=w["reached"] is not None,
                       bed={"temperature": round(bed_t), "target": w["bed"]},
                       chamber={"temperature": round(ch), "target": w["chamber"]} if w["chamber"] and ch is not None else None,
                       minutes=None if w["reached"] is not None else max(1, int(round(secs / 60))),
                       until=_iso(w["until"]))
        if show_options:
            out["options"] = self._warm_options(spools)
        return out if (w is not None or show_options) else None

    def _warm_options(self, spools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The loaded materials, the one in the head first, each with the colours it comes in."""
        loaded = [s for s in spools if s.get("material") and s["status"] in ("ready", "low")]
        loaded.sort(key=lambda s: (not s.get("in_use"), s["slot"]))
        by: Dict[str, List[Dict[str, Any]]] = {}
        for s in loaded:
            by.setdefault(_material_key(s["material"]), []).append(s)
        out = []
        for m, ss in by.items():
            colours = [_color_name(s["color"]) for s in ss if s.get("color")]
            colours = list(dict.fromkeys(colours))
            if ss[0].get("in_use"):
                note = f"{colours[0] if colours else 'The spool'}, in the head"
            elif len(ss) == 1 and not ss[0].get("direct"):
                note = f"{colours[0] + ', s' if colours else 'S'}lot {ss[0]['slot'] + 1}"
            else:
                note = _join(colours) if colours else ""
            out.append(_action("warm_up", m, material=m, color=ss[0].get("color"), note=note))
        return out

    # ---- move and heat by hand (design/hands-on/, C) ----------------------------------

    def hands_why_not(self) -> Optional[str]:
        if self.klippy_state != "ready":
            return "The printer isn't ready."
        if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            return "Not while it's printing."
        if self._change is not None or self._swap is not None:
            return "Not while the filament is changing."
        if self._power is not None:
            return "Not while it's turning off."
        return None

    def z_moves(self) -> str:
        """What moves when Z goes up: "head" (a gantry, or a bed slinger's X axis) or "bed"."""
        for name in (ELYIR_BENCH_START_SETTINGS, "gcode_macro _PRINT_START_SETTINGS"):
            v = str((self.status.get(name) or {}).get("z_moves") or "").lower()
            if v in ("head", "bed"):
                return v
        if "quad_gantry_level" in self.status:
            return "head"
        return "bed" if "z_tilt" in self.status else "head"

    def homed(self) -> bool:
        return set("xyz") <= set(str((self.status.get("toolhead") or {}).get("homed_axes") or ""))

    def _hands_limits(self) -> tuple:
        th = self.status.get("toolhead") or {}
        lo = [float(v) for v in (th.get("axis_minimum") or [0, 0, 0])[:3]]
        hi = [float(v) for v in (th.get("axis_maximum") or [200, 200, 200])[:3]]
        return lo, hi

    def _hands_position(self, now: float) -> List[float]:
        if self._hands_aim is not None and now - self._hands_aim[1] < HANDS_AIM_SECONDS:
            return list(self._hands_aim[0])
        live = (self.status.get("motion_report") or {}).get("live_position") or [0, 0, 0]
        return [float(v) for v in live[:3]]

    def _head_material(self) -> Optional[str]:
        return next((_material_key(s["material"]) for s in self.spools() if s.get("in_use") and s.get("material")), None)

    def _hands_go(self, pos: List[float], target: List[float], now: float) -> List[str]:
        """Z first when it goes up, so the head never drags across the bed; XY first when it comes down."""
        z = [f"G1 Z{target[2]:.2f} F{HANDS_Z_SPEED}"] if abs(target[2] - pos[2]) > 0.01 else []
        xy = [f"G1 X{target[0]:.2f} Y{target[1]:.2f} F{HANDS_XY_SPEED}"] if (abs(target[0] - pos[0]) > 0.01 or abs(target[1] - pos[1]) > 0.01) else []
        self._hands_aim = (tuple(target), now)
        moves = z + xy if target[2] >= pos[2] else xy + z
        return ["G90"] + moves if moves else []

    def hands_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        """A tap in Move and heat. Queues what to send for work(); False when there's nothing to do."""
        now = time.time() if now is None else now
        op = payload.get("op")
        if op == "stop":   # Cool down, from anywhere
            self._hands, self._hands_heat, self._hands_until = None, set(), None
            return True
        if self.hands_why_not():
            return False
        lo, hi = self._hands_limits()
        homed = self.homed()
        pos = self._hands_position(now)
        cmds: List[str] = []
        if op == "home":
            cmds, self._hands_aim, self._hands_homing = ["G28"], None, now
        elif op == "motors_off":
            cmds, self._hands_aim = ["M84"], None
            if self._hands and self._hands["kind"] == "clear":
                self._hands = None
        elif op == "move":
            axis = "xyz".find(str(payload.get("axis") or "").lower())
            try:
                mm = float(payload.get("mm") or 0)
            except (TypeError, ValueError):
                return False
            if axis < 0 or not mm:
                return False
            if not homed:   # the first move finds home; the next one moves
                cmds, self._hands_aim, self._hands_homing = ["G28"], None, now
            else:
                floor = max(lo[2], HANDS_Z_FLOOR) if axis == 2 else lo[axis]
                target = list(pos)
                target[axis] = min(hi[axis], max(floor, pos[axis] + mm))
                if abs(target[axis] - pos[axis]) < 0.01:
                    return False
                cmds = self._hands_go(pos, target, now)
        elif op == "heat":
            heater = payload.get("heater")
            try:
                t = int(float(payload.get("target") or 0))
            except (TypeError, ValueError):
                return False
            if heater == "nozzle":
                t = max(0, min(HANDS_NOZZLE_MAX, t))
                cmds = [f"M104 S{t}"]
                if t:
                    self._hands = {"kind": "nozzle", "target": t, "material": payload.get("material"), "seen": False}
                elif self._hands and self._hands["kind"] in ("nozzle", "clean"):
                    self._hands = None
            elif heater == "bed":
                t = max(0, min(HANDS_BED_MAX, t))
                cmds = [f"M140 S{t}"]
            else:
                return False
            (self._hands_heat.add if t else self._hands_heat.discard)(heater)
        elif op == "nozzle":
            m = _material_key(payload.get("material")) or self._head_material() or "PLA"
            t = int(MATERIAL_TEMPS.get(m, DEFAULT_CHANGE_TEMP))
            cmds = [f"M104 S{t}"]
            self._hands = {"kind": "nozzle", "target": t, "material": m, "seen": False}
            self._hands_heat.add("nozzle")
        elif op == "clear":
            top = min(hi[2] - 10, max(HANDS_CLEAR_Z, pos[2] if homed else 0))
            back = [(lo[0] + hi[0]) / 2, hi[1] - 10]
            if not homed:
                self._hands_homing = now
            start = pos if homed else [back[0], back[1], 0]
            cmds = ([] if homed else ["G28"]) + self._hands_go(start, [back[0], back[1], top], now)
            self._hands = {"kind": "clear", "z": round(top), "z_before": round(pos[2], 2) if homed else None}
        elif op == "clean":
            m = self._head_material() or "PLA"
            t = int(MATERIAL_TEMPS.get(m, DEFAULT_CHANGE_TEMP))
            front = [(lo[0] + hi[0]) / 2, lo[1] + 10]
            z = min(hi[2] - 10, max(HANDS_CLEAN_Z, pos[2] if homed else 0))
            if not homed:
                self._hands_homing = now
            start = pos if homed else [front[0], front[1], 0]
            cmds = [f"M104 S{t}"] + ([] if homed else ["G28"]) + self._hands_go(start, [front[0], front[1], z], now)
            self._hands = {"kind": "clean", "target": t, "material": m, "seen": False}
            self._hands_heat.add("nozzle")
        elif op == "lower":
            h = self._hands
            if not h or h["kind"] != "clear" or h.get("z_before") is None or not homed:
                return False
            cmds = self._hands_go(pos, [pos[0], pos[1], max(h["z_before"], HANDS_Z_FLOOR)], now)
            self._hands = None
        elif op == "done":
            h, self._hands = self._hands, None
            if h and h["kind"] in ("clean", "nozzle"):
                cmds = ["M104 S0"]
                self._hands_heat.discard("nozzle")
        elif op == "keep":
            if not self._hands and not self._hands_heat:
                return False
        else:
            return False
        self._hands_until = now + HANDS_IDLE_SECONDS
        if cmds:
            self._change_queue.append(("gcode", "\n".join(cmds)))
        return True

    def _update_hands(self, now: float) -> List[tuple]:
        if self._hands_homing is not None and (self.homed() or now - self._hands_homing > 120):
            self._hands_homing = None
        if self._hands is None and not self._hands_heat:
            return []
        if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            self._hands, self._hands_heat, self._hands_until = None, set(), None   # the print takes it from here
            return []
        h = self._hands
        if h is not None and h["kind"] in ("clean", "nozzle"):
            if (self.status.get("extruder") or {}).get("target"):
                h["seen"] = True
            elif h["seen"]:
                self._hands = None   # turned off elsewhere: Cool down, idle_timeout, a macro
                self._hands_heat.discard("nozzle")
        if self._hands_until is not None and now >= self._hands_until:
            off = ["M104 S0"] if "nozzle" in self._hands_heat else []
            off += ["M140 S0"] if "bed" in self._hands_heat else []
            self._hands, self._hands_heat, self._hands_until = None, set(), None
            return [("gcode", "\n".join(off))] if off else []
        return []

    def _hands_minutes_left(self, now: float) -> Optional[int]:
        return None if self._hands_until is None else max(1, int((self._hands_until - now + 59) // 60))

    def _hands_view(self, now: float) -> Dict[str, Any]:
        """Move and heat's sheet: whether it's offered, the words for this machine, where the head is, presets."""
        lo, hi = self._hands_limits()
        live = (self.status.get("motion_report") or {}).get("live_position") or None
        homed = self.homed()
        head = self._head_material()
        h = self._hands
        return {
            "why_not": self.hands_why_not(),
            "z_moves": self.z_moves(),
            "homed": homed,
            "homing": self._hands_homing is not None and not homed,
            "position": {"x": round(float(live[0]), 1), "y": round(float(live[1]), 1), "z": round(float(live[2]), 1)} if (homed and live) else None,
            "limits": {"min": lo, "max": hi},
            "steps": list(HANDS_STEPS),
            "material": head,
            "clean_temp": int(MATERIAL_TEMPS.get(head or "PLA", DEFAULT_CHANGE_TEMP)),
            "nozzle_presets": [{"material": m, "temp": MATERIAL_TEMPS[m]} for m in HANDS_PRESETS],
            "bed_presets": [{"material": m, "temp": WARM_BED[m]} for m in HANDS_PRESETS],
            "held": dict({k: v for k, v in h.items() if k != "seen"}, minutes=self._hands_minutes_left(now)) if h else None,
            "heat": sorted(self._hands_heat),
        }

    def _hands_now(self, now: float) -> Optional[tuple]:
        """(phase, headline, detail, actions) for Now while a job from Move and heat holds the printer."""
        h = self._hands
        if h is None:
            return None
        mins = self._hands_minutes_left(now) or 1
        later = f"It turns off by itself in {mins} minute{'s' if mins != 1 else ''}."
        if h["kind"] == "clean":
            temp = float((self.status.get("extruder") or {}).get("temperature") or 0)
            if temp >= h["target"] - 5:
                detail = "It's hot and at the front. Brush the tip with a brass brush, then tap Done."
            else:
                detail = f"The head is at the front, heating to {h['target']}° for {h['material']}. Brush the tip once it's hot, then tap Done."
            acts = [_action("hands_done", "Done, cool it", primary=True)]
            if mins <= 5:
                detail, acts = f"{detail} {later}", acts + [_action("hands_keep", "Keep it hot")]
            return "hands_clean", "Clean the nozzle", detail, acts
        if h["kind"] == "nozzle":
            temp = float((self.status.get("extruder") or {}).get("temperature") or 0)
            hot = temp >= h["target"] - 5
            detail = f"{h['target']}°, for pulling filament by hand. {later}" if hot else f"Heating to {h['target']}°. {later}"
            acts = [_action("hands_done", "Done, cool it", primary=True)] + ([_action("hands_keep", "Keep it hot")] if mins <= 5 else [])
            return "hands_nozzle", "Nozzle hot" if hot else "Heating the nozzle", detail, acts
        bed = self.z_moves() == "bed"
        detail = (f"The bed is down at {h['z']} mm. It comes back up by itself before the next print." if bed
                  else f"The head is up at {h['z']} mm. It comes back down by itself before the next print.")
        acts = [_action("hands_done", "Done", primary=True)]
        if h.get("z_before") is not None:
            acts.append(_action("hands_lower", "Raise it again" if bed else "Lower it again"))
        return "hands_clear", "Out of the way", detail, acts

    # ---- the first layer: squish more, squish less (design/first-layer/, B) ----------

    def z_by(self) -> str:
        """How this printer finds Z for a print: "tap" when PRINT_START's tap stage runs, else "scan"."""
        cfg = self.status.get("gcode_macro _PRINT_START_SETTINGS") or {}
        return "tap" if cfg.get("tap") is True or str(cfg.get("tap")).lower() == "true" else "scan"

    def kept_first_layer(self) -> Optional[Dict[str, Any]]:
        """What the printer keeps in [save_variables]. None when it has none: nothing can be kept."""
        sv = self.status.get("save_variables")
        v = sv.get("variables") if isinstance(sv, dict) else None
        if not isinstance(v, dict):
            return None
        try:
            z = round(float(v.get("first_layer_z") or 0.0), 3)
        except (TypeError, ValueError):
            z = 0.0
        hist = v.get("first_layer_history")
        hist = [round(float(h), 3) for h in hist if isinstance(h, (int, float))] if isinstance(hist, list) else []
        at = v.get("first_layer_at")
        return {"set": "first_layer_z" in v, "z": z, "against": str(v.get("first_layer_against") or "scan"),
                "history": hist[-FIRST_LAYER_HISTORY:], "at": float(at) if isinstance(at, (int, float)) else None}

    def _applied_first_layer(self) -> float:
        """What PRINT_START put on top of the printer's Z for this print (the same rules as the macro).
        Elyir Bench's start macro says what it put on: applied_z."""
        if self._own_start:
            try:
                return round(float((self.status.get(ELYIR_BENCH_START) or {}).get("applied_z") or 0.0), 3)
            except (TypeError, ValueError):
                return 0.0
        k = self.kept_first_layer()
        if not k or not k["set"] or k["against"] != self.z_by() or abs(k["z"]) > SQUISH_LIMIT:
            return 0.0
        return k["z"]

    def _homing_z(self) -> Optional[float]:
        origin = (self.status.get("gcode_move") or {}).get("homing_origin")
        try:
            return float(origin[2])
        except (TypeError, ValueError, IndexError):
            return None

    def _observe_squish(self, state: str, getting_ready: bool) -> None:
        """Start this print's record once it's laying plastic; when it ends, take the nudges back
        out of Klipper's offset (they were for this print), unless something else moved it since."""
        sq = self._squish
        if sq is None:
            if state == "printing" and self._print_started and not getting_ready:
                self._squish = {"applied": self._applied_first_layer(), "z_by": self.z_by(), "moved": 0.0,
                                "base": None, "ended": False, "answered": False}
            return
        if sq["ended"] or state in ("printing", "paused"):
            return
        sq["ended"] = True
        z = self._homing_z()
        if sq["moved"] and sq["base"] is not None and z is not None and abs(z - (sq["base"] + sq["moved"])) < 0.001:
            self._change_queue.append(("gcode", f"SET_GCODE_OFFSET Z={sq['base']:.3f}"))

    def squish_open(self) -> bool:
        """Further / Closer are offered: printing (not paused, not getting ready) on layers 1 to 3."""
        sq = self._squish
        if sq is None or sq["ended"]:
            return False
        ps = self.status.get("print_stats") or {}
        if ps.get("state") != "printing" or (self.status.get("pause_resume") or {}).get("is_paused"):
            return False
        if self.prep_stage():
            return False
        layer = (ps.get("info") or {}).get("current_layer")
        if isinstance(layer, (int, float)) and layer >= 1:
            return layer <= SQUISH_LAYERS
        pos = (self.status.get("motion_report") or {}).get("live_position") or []
        return len(pos) > 2 and isinstance(pos[2], (int, float)) and pos[2] < SQUISH_LOW_Z

    def _squish_total(self) -> float:
        sq = self._squish or {}
        return round(sq.get("applied", 0.0) + sq.get("moved", 0.0), 3)

    def _keep_offered(self, state: str, now: float) -> bool:
        """At the end: Finished, or the "Print stopped." note after a stop."""
        sq = self._squish
        stopped = state == "ready" and self._cancelled_at is not None and now - self._cancelled_at < CANCELLED_NOTE_SECONDS
        return (sq is not None and sq["ended"] and not sq["answered"] and abs(sq["moved"]) > 1e-9
                and self.kept_first_layer() is not None and (state == "finished" or stopped))

    def _clear_asked(self) -> bool:
        """A value kept against the other way of finding Z (scan, before tap arrived): PRINT_START
        no longer uses it, and Now asks once whether to clear it."""
        k = self.kept_first_layer()
        return bool(k and k["set"] and abs(k["z"]) > 1e-9 and k["against"] != self.z_by())

    def first_layer_ok(self, payload: Dict[str, Any]) -> bool:
        """Whether first_layer_input would do anything with this, without doing it."""
        op = payload.get("op")
        if op == "nudge":
            by = payload.get("by")
            return (by in (SQUISH_STEP, -SQUISH_STEP) and self.squish_open()
                    and abs(self._squish_total() + by) <= SQUISH_LIMIT + 1e-9)
        if op == "once":
            return self._squish is not None and self._squish["ended"] and not self._squish["answered"]
        k = self.kept_first_layer()
        if k is None:
            return False
        if op == "keep":
            sq = self._squish
            return sq is not None and sq["ended"] and not sq["answered"] and abs(sq["moved"]) > 1e-9
        if op == "back":
            return bool(k["history"])
        if op in ("clear", "keep_old"):
            return self._clear_asked()
        return False

    def first_layer_input(self, payload: Dict[str, Any], now: Optional[float] = None) -> bool:
        """nudge (by ±SQUISH_STEP), keep / once at the end, back (Care), clear / keep_old (the question
        when the way of finding Z changed). Commands go out through work()."""
        now = time.time() if now is None else now
        if not self.first_layer_ok(payload):
            return False
        op, sq, k = payload["op"], self._squish, self.kept_first_layer()
        if op == "nudge":
            by = payload["by"]
            if sq["base"] is None:
                sq["base"] = self._homing_z()
            sq["moved"] = round(sq["moved"] + by, 3)
            self._change_queue.append(("gcode", f"SET_GCODE_OFFSET Z_ADJUST={by:.3f} MOVE=1"))
        elif op == "once":
            sq["answered"] = True
        elif op == "keep":
            sq["answered"] = True
            self._save_first_layer(round(sq["applied"] + sq["moved"], 3), sq["z_by"], k["history"] + [k["z"]], now)
        elif op == "back":
            self._save_first_layer(k["history"][-1], k["against"], k["history"][:-1], now)
        elif op == "clear":
            self._save_first_layer(0.0, self.z_by(), k["history"] + [k["z"]], now)
        elif op == "keep_old":
            self._save_first_layer(k["z"], self.z_by(), k["history"], now)
        return True

    def _save_first_layer(self, z: float, against: str, history: List[float], now: float) -> None:
        hist = ", ".join(f"{h:.3f}" for h in history[-FIRST_LAYER_HISTORY:])
        # Klipper splits parameters like a shell, then runs literal_eval on VALUE
        self._change_queue.append(("gcode", "\n".join([
            f"SAVE_VARIABLE VARIABLE=first_layer_z VALUE={z:.3f}",
            f"SAVE_VARIABLE VARIABLE=first_layer_against VALUE='\"{against}\"'",
            f"SAVE_VARIABLE VARIABLE=first_layer_history VALUE='[{hist}]'",
            f"SAVE_VARIABLE VARIABLE=first_layer_at VALUE={int(now)}",
        ])))

    def _first_layer_view(self, state: str, now: float) -> Optional[Dict[str, Any]]:
        """What the screens show: Further / Closer with the total while the first layers go down,
        the question at the end, what's kept (Care), and the question when tap arrives."""
        k = self.kept_first_layer()
        sq = self._squish
        out: Dict[str, Any] = {"can_keep": k is not None, "adjust": None, "keep": None, "kept": None, "ask": None}
        if state == "printing" and self.squish_open():
            total = self._squish_total()
            acts = []
            if total + SQUISH_STEP <= SQUISH_LIMIT + 1e-9:
                acts.append(_action("squish_less", "Further"))
            if total - SQUISH_STEP >= -SQUISH_LIMIT - 1e-9:
                acts.append(_action("squish_more", "Closer"))
            out["adjust"] = {"total": total, "words": squish_words(total), "mm": squish_mm(total),
                             "moved": sq["moved"], "actions": acts}
        if self._keep_offered(state, now):
            m = sq["moved"]
            out["keep"] = {"moved": m, "total": self._squish_total(),
                           "headline": "Keep the new first layer for next time?",
                           "detail": f"You moved it {squish_words(m).lower()} {'from' if m > 0 else 'to'} the bed ({squish_mm(m)}).",
                           "actions": [_action("keep_first_layer", "Keep it", primary=True),
                                       _action("just_this_once", "Just this once")]}
        if k is not None:
            z = k["z"] if k["set"] else 0.0
            back = k["history"][-1] if k["history"] else None
            out["kept"] = {"z": z, "words": squish_words(z), "mm": squish_mm(z),
                           "against": k["against"] if k["set"] else None,
                           "used": not k["set"] or k["against"] == self.z_by(), "at": _iso(k["at"]),
                           "back": {"z": back, "words": squish_words(back), "mm": squish_mm(back)} if back is not None else None,
                           "actions": [_action("first_layer_back", "Back to how it was")] if back is not None else []}
        if state == "ready" and self._clear_asked():
            now_tap = self.z_by() == "tap"
            out["ask"] = {"headline": (f"{self.printer_name} now finds its own first layer. Clear your old adjustment?" if now_tap
                                       else f"{self.printer_name} no longer finds its own first layer. Clear your old adjustment?"),
                          "detail": f"It's {squish_words(k['z']).lower()} ({squish_mm(k['z'])}), set before. It isn't used until you choose.",
                          "actions": [_action("first_layer_clear", "Clear it", primary=True),
                                      _action("first_layer_keep_old", "Keep it")]}
        return out

    def _change_steps(self) -> List[Dict[str, Any]]:
        c = self._change
        out_name = (c["out"] or {}).get("name") or "the old filament"
        labels = {**CHANGE_LABELS, "unload": f"Taking out {out_name}", **(c.get("labels") or {})}
        cur = c["steps"].index(c["step"]) if c["step"] in c["steps"] else len(c["steps"])
        you = SLOT_YOU if c["kind"] == "slot" else CHANGE_YOU
        return [dict({"id": s, "label": labels[s], "status": "done" if i < cur else ("now" if i == cur else "todo")},
                     **({"you": True} if s in you else {}))
                for i, s in enumerate(c["steps"])]

    def _change_choices(self) -> List[Dict[str, Any]]:
        """"What is it?": the spool that came out, then the ones before it, as one-tap answers."""
        c = self._change
        seen: List[Dict[str, Any]] = []
        rec = self.direct_spool or {}
        for r in ([c["out"]] if c["out"] else []) + list(rec.get("recent") or []):
            if not r or not r.get("material"):
                continue
            if any(_material_key(k.get("material")) == _material_key(r.get("material"))
                   and _color_distance(k.get("color"), r.get("color")) < COLOR_MATCH for k in seen):
                continue
            seen.append(r)
        inn = c["inn"] or {}
        out = []
        for i, r in enumerate(seen[:4]):
            name = _spool_name(r.get("color"), r.get("material"))
            on = (_material_key(inn.get("material")) == _material_key(r.get("material"))
                  and _color_distance(inn.get("color"), r.get("color")) < COLOR_MATCH)
            out.append(_action("change_what", "Same as before" if i == 0 and c["out"] and r is c["out"] else name,
                               primary=on, color=_hex_color(r.get("color")), material=_material_key(r.get("material"))))
        return out

    def _change_view(self) -> Optional[Dict[str, Any]]:
        """What the screens draw beside the words: the head, what's coming out and going in."""
        c = self._change
        if c is None:
            return None
        if c["kind"] == "colour":
            return self._colour_view()
        steps = c["steps"]
        step = c["step"]
        idx = steps.index(step) if step in steps else len(steps) - 1
        if c["kind"] == "slot":
            return {"kind": "slot", "step": step, "art": SLOT_ART.get(step, "still"), "slot": c["slot"],
                    "out": c["out"], "in": c["inn"], "n": idx + 1, "of": len(steps),
                    "you": step in SLOT_YOU and not c["busy"] and not c["error"],
                    "ask": step == "what" and not c["inn"],
                    "choices": self._slot_choices(c["slot"], c["out"], self.spools(), "change_what") if step == "what" else []}
        return {
            "kind": c["kind"],
            "step": step,
            "art": "purge" if c["busy"] == "purge" else ("done" if step == "resume" else CHANGE_ART.get(step, "still")),
            "out": c["out"],
            "in": c["inn"],
            "n": idx + 1,
            "of": len(steps),
            "you": step in CHANGE_YOU and not c["busy"] and not c["error"],
            "ask": step == "push" and not c["inn"],
            "choices": self._change_choices() if step in ("push", "load") and c["kind"] != "ace" else [],
        }

    def _change_intent(self, now: float, job: Optional[Dict[str, Any]]) -> tuple:
        """state, phase, headline, detail, actions, steps, expires, raw while changing filament."""
        c = self._change
        if c["kind"] == "slot":
            return self._slot_intent()
        if c["kind"] == "colour":
            return self._colour_intent(now, job)
        ext = self.status.get("extruder") or {}
        steps = self._change_steps()
        step = c["step"]
        out = c["out"] or {}
        inn = c["inn"] or {}
        out_name = out.get("name") or "the old filament"
        expires = (self._pause_since or now) + NEEDS_YOU_HOLD_SECONDS if c["mid"] else None
        stop = _action("change_stop", "Stop")

        if c["error"]:
            what = {"unload": f"Taking out {out_name}", "load": f"Loading {inn.get('name') or 'the new filament'}",
                    "check": "Pushing more through"}.get(step, "Changing filament")
            return ("problem", "change_failed", f"{what} didn't finish.",
                    "It stopped partway. Check the head, then try again.",
                    [_action("change_retry", "Try again", primary=True, style="red"), _action("change_end", "It's sorted")],
                    steps, expires, c["error"])

        if c["busy"] or step in ("warm", "unload", "load"):
            if c["busy"] == "purge":
                headline = "Pushing more through"
            elif c["kind"] == "unload":
                headline = f"Taking out {out_name}"
            elif c["kind"] == "load":
                headline = f"Loading {inn.get('name') or 'filament'}"
            else:
                headline = "Changing filament"
            t, target = float(ext.get("temperature") or 0), float(ext.get("target") or 0)
            if c["stop"]:
                detail = "Stopping after this step."
            elif target and t < target - 3:
                detail = f"Nozzle at {int(t)}° of {int(target)}°."
            else:
                detail = "Keep clear of the nozzle."
            return ("preparing", "change_" + (c["busy"] if c["busy"] == "purge" else step), headline, detail,
                    [] if c["stop"] else [stop], steps, expires, "")

        sensor = self.head_sensor is not None and self.head_loaded() is not None
        if step == "pull":
            seen = sensor and c["head_at"] is True
            return ("needs_you", "change_pull", "Pull the filament out.",
                    "Gently, from the top of the head. " + ("I'll notice when it's out." if seen else "Then tell me."),
                    [_action("change_out", "It's out", primary=True, style="amber"), stop], steps, expires, "")
        if step == "push":
            if not c["inn"] and (c["seen_in"] or c["told_in"]):
                headline, detail = "Got it. What is it?", "Tap what you loaded, and I'll push it through."
            elif not c["inn"]:
                headline = "Push the new filament in."
                detail = "Until it stops, and tell me what it is." + (" I'll feel it and take over." if sensor else "")
            else:
                headline = f"Push the {inn['name'] or 'new filament'} in."
                detail = "Until it stops. " + ("I'll feel it and take over." if sensor else "Then tell me.")
            actions = [_action("change_in", "It's in", primary=bool(c["inn"]) and not sensor, style="amber"), stop]
            return ("needs_you", "change_push", headline, detail, actions, steps, expires, "")
        if step == "check":
            colour = _color_name(inn.get("color")).lower() if inn.get("color") else ""
            was = _color_name(out.get("color")).lower() if out.get("color") else ""
            headline = f"Is it coming out clean {colour}?" if colour else "Is it coming out clean?"
            if was and was != colour:
                detail = f"If there's still {was} in it, I'll push more through."
            else:
                detail = "If it still looks mixed, I'll push more through."
            return ("needs_you", "change_check", headline, detail,
                    [_action("change_good", "Looks good", primary=True, style="amber"),
                     _action("change_more", "Push more through")], steps, expires, "")
        # resume: mid-print, the new filament is in and the print waits for Carry on
        info = (self.status.get("print_stats") or {}).get("info") or {}
        layer = info.get("current_layer")
        name = job["name"] if job else "The print"
        detail = (f"{name} carries on from layer {int(layer) + 1}." if isinstance(layer, (int, float)) and layer
                  else f"{name} carries on where it left off.")
        return ("needs_you", "change_done", f"{inn.get('name') or 'The new filament'} is in.", detail,
                [_action("resume", "Carry on", primary=True, style="amber"), _action("change_more", "Push more through")],
                steps, expires, "")

    def _slot_intent(self) -> tuple:
        """state, phase, headline, detail, actions, steps, expires, raw while swapping a spool in a slot.
        Phases start with change_ so a "your turn" step tells the phone only if nobody comes."""
        c = self._change
        steps = self._change_steps()
        step, n = c["step"], c["slot"] + 1
        name = (c["out"] or {}).get("name") or f"the spool in slot {n}"
        stop = _action("change_stop", "Stop")
        if c["error"]:
            what = f"Taking {name} out of the head" if step == "unload" else f"Pulling {name} back"
            return ("problem", "change_failed", f"{what} didn't finish.",
                    "Check the tube from the unit isn't tangled or kinked, then try again.",
                    [_action("change_retry", "Try again", primary=True, style="red"), _action("change_end", "It's sorted")],
                    steps, None, c["error"])
        if c["busy"] or step in ("unload", "pullback"):
            if c["stop"]:
                detail = "Stopping after this step."
            elif step == "unload":
                detail = "Keep clear of the nozzle."
            else:
                detail = f"Slot {n}. About a minute. Then it's your turn."
            headline = f"Taking {name} out of the head" if step == "unload" else f"Pulling {name} back to its spool"
            return ("preparing", "change_slot_" + step, headline, detail, [] if c["stop"] else [stop], steps, None, "")
        if step == "swap":
            if c["stuck"]:
                detail = (f"If its end is still in slot {n}, pull it out gently. Then put the new spool on and push "
                          f"its end in until the unit grabs it.")
            else:
                detail = f"Take the old one off, put the new one on, and push its end into slot {n} until the unit grabs it. I'll notice."
            return ("needs_you", "change_slot_swap", f"Swap the spool in slot {n}.", detail,
                    [_action("change_in", "It's in"), stop], steps, None, "")
        return ("needs_you", "change_slot_what", f"What's in slot {n}?", "It has no tag, so tell me once.",
                [stop], steps, None, "")

    def _match_swap_step(self, low: str) -> None:
        # The first step whose words appear: "unloading tool" also contains "loading tool"
        hit = next((i for i, (_, needles) in enumerate(SWAP_STEPS) if any(n in low for n in needles)), None)
        if hit is None:
            return
        c = self._change
        if c is not None and c.get("kind") == "colour" and c["busy"] == "swap":
            # the unit's tool change says where it is on the console: the steps follow it
            key = SWAP_STEPS[hit][0]
            if key in c["steps"]:
                if c["steps"].index(key) > c["steps"].index(c["step"]):
                    c["step"] = key
            elif "switch" in c["steps"]:
                c["sub"] = key
            return
        if not self._swap or self._swap.get("error"):
            return
        if hit > self._swap["step"]:
            self._swap["step"] = hit

    def should_purge(self, slot: int) -> bool:
        """Purge after loading unless the filament coming out is the same colour and material:
        then the nozzle already holds the right thing. Unknown counts as different."""
        spools = {s["slot"]: s for s in self.spools()}
        new = spools.get(slot)
        sel = self._selected_slot()
        old = spools.get(sel) if sel is not None else self._last_unloaded
        if not new or not old or not new.get("color") or not old.get("color"):
            return True
        same_colour = _color_distance(new["color"], old["color"]) < COLOR_MATCH
        same_material = _material_key(new.get("material")) == _material_key(old.get("material"))
        return not (same_colour and same_material)

    def head(self, now: float) -> Dict[str, Any]:
        """What's in the head, and whether the sensor and the printer's memory disagree.
        A disagreement has to last a little while, and not straight after a swap, before
        it's raised: the sensor flips while filament is moving."""
        loaded = self.head_loaded()
        if self.direct:
            # The spool and the head are the same thing here: nothing to disagree about.
            return {"loaded": loaded, "slot": 0 if loaded else None, "mismatch": None, "notice": None,
                    "actions": [], "choices": []}
        sel = self._selected_slot()
        spools = {s["slot"]: s for s in self.spools()}
        kind = None
        if loaded is True and sel is None:
            kind = "unknown_spool"
        elif loaded is False and sel is not None:
            kind = "phantom_spool"
        if kind == "phantom_spool" and sel == self._head_ok:
            kind = None                     # they told us it's in there
        else:
            self._head_ok = None
        busy = self._swap is not None or now - self._last_swap_end < SWAP_QUIET_SECONDS
        if kind is None or busy:
            self._mismatch = None
        elif not self._mismatch or self._mismatch[0] != kind:
            self._mismatch = (kind, now)
        settled = bool(self._mismatch) and now - self._mismatch[1] >= HEAD_MISMATCH_SECONDS
        out: Dict[str, Any] = {"loaded": loaded, "slot": sel, "mismatch": None, "notice": None, "actions": [], "choices": []}
        if not settled:
            return out
        if kind == "unknown_spool":
            out["mismatch"] = kind
            out["notice"] = {"headline": "There's filament in the head, but I don't know which spool.",
                             "detail": "Tap the spool it came from. Nothing will move."}
            ready = [s for s in spools.values() if s["status"] in ("ready", "low")]
            names = [s["name"] for s in ready]

            def label(s: Dict[str, Any]) -> str:
                # two spools that look the same get their slot number, so the choice is clear
                if not s["name"]:
                    return f"Slot {s['slot'] + 1}"
                return f"{s['name']} (slot {s['slot'] + 1})" if names.count(s["name"]) > 1 else s["name"]
            out["choices"] = [_action("mark_loaded", label(s), slot=s["slot"]) for s in ready]
            out["actions"] = [_action("open_materials", "Tell me which", primary=True)]
        else:
            name = (spools.get(sel) or {}).get("name") or f"the spool in slot {sel + 1}"
            out["mismatch"] = kind
            out["notice"] = {"headline": f"The head looks empty, but I think {name} is loaded.",
                             "detail": "Tell me which is right and nothing moves. Or unload it to start clean."}
            out["actions"] = [_action("mark_loaded", "It's empty", primary=True, slot=-1),
                              _action("head_ok", f"{name} is loaded"),
                              _action("unload_spool", f"Unload {name}")]
        return out

    def _with_spool_actions(self, spools: List[Dict[str, Any]], can_move: bool) -> List[Dict[str, Any]]:
        spares = self._spares(spools) if not self.direct else {"in": {}, "for": {}}
        by = {s["slot"]: s for s in spools}
        out = []
        for s in spools:
            e = dict(s, **self.spool_actions(s, can_move))
            if self.direct:
                out.append(e)
                continue
            alt = spares["in"].get(s["slot"])
            e["spare_for"] = spares["for"].get(s["slot"])
            e["spare_note"] = (f"If it runs out mid-print, the {(by[alt].get('name') or 'spool')} in slot {alt + 1} carries on."
                               if alt is not None else None)
            e["assist"] = self.feed_assist(s["slot"]) if s.get("in_use") else None
            out.append(e)
        return out

    def spool_actions(self, s: Dict[str, Any], can_move: bool) -> Dict[str, Any]:
        """What tapping a spool can do: load it, switch to it, or unload it, plus the quiet
        correction when the printer's memory is wrong. Empty when nothing should move."""
        if not can_move:
            return {"actions": [], "note": None, "fix": None, "move": False}
        if s.get("direct"):
            # One spool: the change routine. Now walks through it.
            if s["status"] == "empty":
                return {"actions": [_action("change_start", "Load filament", primary=True, kind="load")],
                        "note": "Then Now walks you through it.", "fix": None}
            return {"actions": [_action("change_start", "Change filament", primary=True, kind="change"),
                                _action("change_start", "Take it out", kind="unload")],
                    "note": "Then Now walks you through it.", "fix": None}
        name = s.get("name") or f"slot {s['slot'] + 1}"
        sel = self._selected_slot()
        g = s["slot"]
        swap = _action("swap_start", "Swap the spool", slot=g)
        if s["status"] == "empty":
            # Loading an empty slot is something hands do: say how, then notice (design/slots/).
            return {"actions": [], "move": False,
                    "note": f"Put a spool on and push its end into slot {g + 1} until the unit grabs it. I'll notice and ask what it is.",
                    "fix": _action("move_filament", "It won't catch? Pull it in", slot=g, mm=PULL_IN_MM)}
        if s.get("in_use"):
            return {"actions": [_action("unload_spool", "Unload", style="default"), swap], "move": False,
                    "note": f"Unload takes {name} out of the head. Swap also pulls it back so you can put a new spool on.",
                    "fix": _action("mark_loaded", "Not actually loaded? Mark as empty", slot=-1)}
        if s["status"] not in ("ready", "low"):
            return {"actions": [], "note": None, "fix": None, "move": False}
        purge = self.should_purge(g)
        label = "Switch to this spool" if sel is not None else "Load this spool"
        what = "swaps the filament" if sel is not None else "feeds it in"
        note = f"Heats the nozzle, {what}{' and cleans the nozzle' if purge else ''}. About {3 if sel is not None else 2} minutes."
        return {"actions": [_action("load_spool", label, primary=True, slot=g), swap],
                "note": note, "move": True,
                "fix": _action("mark_loaded", "Already in the head? Mark as in use", slot=g)}

    # ---- spools --------------------------------------------------------

    def spools(self) -> List[Dict[str, Any]]:
        """One entry per gate. Per-slot RFID data (from each device) wins over the
        top-level user-configured colour and material lists; either alone is fine. Without a
        filament unit, the one spool on the printer."""
        if self.direct:
            return [self._direct_entry()]
        fu = self.unit_state()
        if fu is None:
            return []
        selected = fu["selected"]
        out: List[Dict[str, Any]] = []
        for raw in fu["slots"]:
            st, color, material, grams = raw["status"], raw["color"], raw["material"], raw["remain"]
            if grams is not None and grams <= 0:
                grams = None
            if st == "ready" and grams is not None and grams < 80:
                st = "low"
            mat = str(material).upper() if material else None
            # What to call it on screen. An empty slot only has a name once someone set one.
            if mat:
                name = f"{_color_name(color)} {mat}" if color else mat
            elif color and st != "empty":
                name = _color_name(color)
            else:
                name = None
            out.append({
                "slot": raw["slot"],
                "name": name,
                "color": color,
                "material": mat,
                "grams": grams,
                "status": st,
                "in_use": raw["slot"] == selected,
                "rfid": raw["tagged"],
            })
        return out

    def find_alternative(self, spools: List[Dict[str, Any]], slot: Optional[int]) -> Optional[Dict[str, Any]]:
        if slot is None:
            return None
        ref = next((s for s in spools if s["slot"] == slot), None)
        if not ref:
            return None
        best, best_d = None, 999.0
        for s in spools:
            if s["slot"] == slot or s["status"] not in ("ready", "low"):
                continue
            if ref["material"] and s["material"] and ref["material"] != s["material"]:
                continue
            d = _color_distance(ref["color"], s["color"])
            if d < best_d and d < 70:
                best, best_d = s, d
        return best

    # ---- job -----------------------------------------------------------

    def job(self, now: float) -> Optional[Dict[str, Any]]:
        ps = self.status.get("print_stats", {})
        state = ps.get("state", "standby")
        if state in ("standby",) or not ps.get("filename"):
            return None
        vsd = self.status.get("virtual_sdcard", {})
        progress = float(vsd.get("progress") or 0.0)
        duration = float(ps.get("print_duration") or 0.0)
        total = float(ps.get("total_duration") or 0.0)
        info = ps.get("info") or {}
        est = None
        if self.metadata_file == ps.get("filename") and self.metadata.get("estimated_time"):
            est = float(self.metadata["estimated_time"])

        remaining: Optional[float] = None
        if state in ("printing", "paused"):
            slicer_left = (est - duration) if est is not None and est > duration else None
            linear_left = (duration * (1 - progress) / progress) if progress > 0.03 and duration > 0 else None
            if slicer_left is not None and linear_left is not None:
                w = min(1.0, progress * 2)   # trust measured pace more as the print goes on
                remaining = (1 - w) * slicer_left + w * linear_left
            else:
                remaining = linear_left if linear_left is not None else (slicer_left if slicer_left is not None else est)
            if remaining is not None:
                remaining = max(0.0, remaining)

        has_meta = self.metadata_file == ps.get("filename")
        thumb = _best_thumbnail(ps.get("filename"), self.metadata) if has_meta else None
        grams = self.metadata.get("filament_weight_total") if has_meta else None

        return {
            "name": _pretty_job_name(ps.get("filename")),
            "filename": ps.get("filename"),
            "thumbnail": thumb,
            "grams": (int(round(float(grams))) if isinstance(grams, (int, float)) and grams > 0 else None),
            "state": state,
            "progress": round(progress, 4),
            "layer": info.get("current_layer"),
            "layers": info.get("total_layer"),
            "elapsed_s": int(duration),
            "total_s": int(total),
            "remaining_s": (int(remaining) if remaining is not None else None),
            "eta": _iso(now + remaining) if remaining is not None else None,
            "eta_clock": _clock(now + remaining) if remaining is not None else None,
            "estimated_s": int(est) if est else None,
            "colors": job_colors(self.metadata) if has_meta else [],
            "material": job_material(self.metadata) if has_meta else None,
        }

    # ---- the picture in the ring (design/now-illustrated/, A) ----------

    def _art_stage(self) -> Optional[str]:
        """What the ring draws while getting ready, or None when nothing is getting ready."""
        prep = self.prep_stage()
        if prep in ART_STAGES:
            return ART_STAGES[prep]
        if prep == "own":
            # The person's own start G-code has no picture of its own: drawn from their M117s, if any
            return self._art_message if self._art_message in ART_HEAD_STAGES else ART_FROM_STEP["leveling"]
        if prep:
            return None
        idx = self._prep_index if self._prep_index >= 0 else self._seen_step
        if self._print_started or idx < 0:
            return None
        step = PREP_STEPS[min(idx, len(PREP_STEPS) - 1)]["id"]
        if step == "leveling" and self._art_message in ("home", "level", "mesh"):
            return self._art_message
        if step == "heating" and self._art_message == "prime":
            return "prime"
        return ART_FROM_STEP.get(step)

    # ---- skip a part (design/skip-objects/, A) ------------------------------

    def parts(self, state: str) -> Optional[Dict[str, Any]]:
        """The labelled parts of the print, numbered front-left to back-right the way the person sees the
        bed, each with its outline and where it is in words; None unless there's more than one. From
        Klipper's [exclude_object]: objects (name, center, polygon), excluded_objects, current_object."""
        if state not in ("printing", "needs_you", "finished"):
            return None
        ex = self.status.get("exclude_object") or {}
        objects = [o for o in ex.get("objects") or [] if isinstance(o, dict) and o.get("name")]
        if len(objects) < 2:
            return None
        skipped = set(ex.get("excluded_objects") or [])
        current = ex.get("current_object")
        th = self.status.get("toolhead") or {}
        lo, hi = th.get("axis_minimum") or [0, 0], th.get("axis_maximum") or [350, 350]

        def box(o):
            pts = o.get("polygon") or []
            c = o.get("center") or (pts[0] if pts else [0, 0])
            xs = [float(p[0]) for p in pts] or [float(c[0])]
            ys = [float(p[1]) for p in pts] or [float(c[1])]
            return float(c[0]), float(c[1]), max(xs) - min(xs), max(ys) - min(ys)

        boxes = {o["name"]: box(o) for o in objects}
        heights = sorted(b[3] for b in boxes.values()) or [1.0]
        band = max(5.0, heights[len(heights) // 2] * 0.6)      # parts within this of each other front to back share a row
        rows: List[List[str]] = []
        for name in sorted(boxes, key=lambda n: boxes[n][1]):
            if rows and abs(boxes[rows[-1][0]][1] - boxes[name][1]) <= band:
                rows[-1].append(name)
            else:
                rows.append([name])
        ordered = [n for row in rows for n in sorted(row, key=lambda n: boxes[n][0])]
        labels = {n: _part_label(n) for n in ordered}
        repeated = {l for l in labels.values() if list(labels.values()).count(l) > 1}
        items = []
        for i, name in enumerate(ordered, 1):
            r = next(k for k, row in enumerate(rows) if name in row)
            row = sorted(rows[r], key=lambda n: boxes[n][0])
            o = next(o for o in objects if o["name"] == name)
            items.append({"name": name, "n": i, "label": labels[name] + (f" {i}" if labels[name] in repeated else ""),
                          "where": _where_words(r, len(rows), row.index(name), len(row)),
                          "center": [round(boxes[name][0], 1), round(boxes[name][1], 1)],
                          "polygon": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in (o.get("polygon") or [])],
                          "state": "skipped" if name in skipped else ("printing" if name == current and state != "finished" else "waiting")})
        left = sum(1 for it in items if it["state"] != "skipped")
        return {"items": items, "total": len(items), "left": left, "skipped": [it["label"] for it in items if it["state"] == "skipped"],
                "bed": [float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])],
                "can_skip": state in ("printing", "needs_you") and left > 1}

    def skip_ok(self, name: str) -> bool:
        """A part may be skipped while printing or paused, if it's one of them, not skipped yet, and not the last."""
        p = self.parts("printing" if (self.status.get("print_stats") or {}).get("state") in ("printing", "paused") else "ready")
        if not p or not p["can_skip"]:
            return False
        return any(it["name"] == name and it["state"] != "skipped" for it in p["items"])

    def _head_on_bed(self) -> Optional[List[float]]:
        """The head over the bed: x and y from 0 to 1 across the axes' travel, z in mm."""
        pos = (self.status.get("motion_report") or {}).get("live_position")
        th = self.status.get("toolhead") or {}
        lo, hi = th.get("axis_minimum"), th.get("axis_maximum")
        if not pos or not lo or not hi or len(pos) < 3:
            return None
        out = []
        for i in (0, 1):
            span = float(hi[i]) - float(lo[i])
            if span <= 0:
                return None
            out.append(min(1.0, max(0.0, (float(pos[i]) - float(lo[i])) / span)))
        return out + [float(pos[2])]

    def _observe_art(self) -> None:
        """While meshing, light every cell the head has passed over since the last look."""
        stage = self._art_stage()
        if stage != self._art_was:
            if stage == "mesh":
                self._mesh_seen, self._mesh_at = 0, None
            self._art_was = stage
        if stage != "mesh":
            return
        at = self._head_on_bed()
        if at is None:
            return
        a = self._mesh_at or at
        for k in range(9):   # the head may cross a few cells between two looks
            f = k / 8
            x, y = a[0] + (at[0] - a[0]) * f, a[1] + (at[1] - a[1]) * f
            i, j = min(MESH_CELLS - 1, int(x * MESH_CELLS)), min(MESH_CELLS - 1, int(y * MESH_CELLS))
            self._mesh_seen |= 1 << (j * MESH_CELLS + i)
        self._mesh_at = at

    def art(self, state: str, phase: str, job: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """What the picture in the ring is drawn from. Every number is the printer's own:
        the stage, where the head is (only while that's what the picture shows), the
        levelling pass, the cells the mesh has covered, and how far up the object is built."""
        if not job or self._change is not None:
            return None
        stage = self._art_stage() if state == "preparing" and phase != "stopping" else None
        head = None
        if stage in ART_HEAD_STAGES:
            h = self._head_on_bed()
            if h:
                # rounded, so the intent changes (and is pushed) only when the picture would
                head = [round(h[0] / 0.02) * 0.02, round(h[1] / 0.02) * 0.02, round(h[2])]
                head = [round(head[0], 2), round(head[1], 2), head[2]]
        built = None
        if state in ("printing", "needs_you", "finished") and self._print_started:
            if job.get("layer") and job.get("layers"):
                built = float(job["layer"]) / float(job["layers"])
            else:
                h, top = self._head_on_bed(), self.metadata.get("object_height")
                if h and top:
                    built = h[2] / float(top)
            if state == "finished":
                built = 1.0
            built = None if built is None else round(min(1.0, max(0.0, built)), 3)
        return {
            "stage": stage,
            "head": head,
            "level": dict(self._level) if stage == "level" and self._level else None,
            "mesh": {"n": MESH_CELLS, "seen": self._mesh_seen} if stage == "mesh" else None,
            "built": built,
        }

    # ---- the intent object ---------------------------------------------

    def intent(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        spools = self.spools()
        job = self.job(now)
        ps = self.status.get("print_stats", {})
        pstate = ps.get("state", "standby")
        paused = bool(self.status.get("pause_resume", {}).get("is_paused"))
        prep_stage = self.prep_stage()
        getting_ready = bool(prep_stage) and pstate in ("printing", "paused")
        bed = self.status.get("heater_bed", {})
        ext = self.status.get("extruder", {})
        raw = ""

        state, phase, headline, detail = "ready", "idle", "Ready", ""
        actions: List[Dict[str, Any]] = []
        steps: List[Dict[str, Any]] = []
        safe = True
        expires: Optional[float] = None
        colour_view: Optional[Dict[str, Any]] = None

        # 0. Stop now was pressed: the emergency stop and restart are ours
        if self._stopping_since is not None and now - self._stopping_since < STOP_RESTART_SECONDS:
            state, phase = "preparing", "stopping"
            headline = "Stopping"
            detail = "Everything is off. The printer is restarting, which takes about half a minute."

        # 0b. Turning off or restarting (design/power/): ahead of Klipper's state, since it's going anyway
        elif self._power is not None:
            p, name = self._power, self.printer_name
            off = p["kind"] == "off"
            if p["error"]:
                state, phase = "problem", "power_failed"
                headline = f"{name} couldn't turn itself off." if off else f"{name} couldn't restart itself."
                detail = (f"The system didn't let it. Wait for the nozzle to drop below {int(POWER_COOL_TEMP)}°, then "
                          + ("switch it off, or turn it off from Advanced." if off else "restart it from Advanced."))
                raw = p["error"]
                actions = [_action("power_retry", "Try again", primary=True, style="red"), _action("power_keep", "Keep it on")]
            else:
                state, phase = "preparing", "turning_off" if off else "restarting"
                headline = "Turning off" if off else "Restarting"
                if p["going"] is not None:
                    detail = ("Now. When the screen goes dark, switch it off." if off
                              else "Now. It's back in about a minute.")
                else:
                    t = self._nozzle_temp()
                    mins = max(1, round((t - POWER_COOL_TEMP) / 45))
                    detail = (f"The nozzle is cooling, with its fan on. {name} {'stops' if off else 'restarts'} in about "
                              f"{mins} minute{'s' if mins != 1 else ''}, at {int(POWER_COOL_TEMP)}°.")
                    actions = [_action("power_keep", "Keep it on"),
                               _action("power_now", "Turn off now" if off else "Restart now")]

        # 1. Can we even talk to Klipper?
        elif self.klippy_state == "disconnected":
            offline_for = now - (self.offline_since or now)
            if offline_for < OFFLINE_GRACE_SECONDS:
                state, phase = "preparing", "starting_up"
                headline = "Starting up"
                detail = "Give me a moment to wake the printer's brain."
            else:
                state, phase = "problem", "offline"
                headline = "I can't reach the printer's brain."
                detail = "It hasn't answered for a while. Try restarting it. If that doesn't help, power the printer off and on."
                actions = [_action("restart_firmware", "Restart", primary=True, style="red")]
            raw = self.klippy_message
        elif self.klippy_state == "startup":
            state, phase = "preparing", "starting_up"
            headline = "Starting up"
            if now - (self.startup_since or now) < STARTUP_SLOW_SECONDS:
                detail = "Checking the electronics and finding home. About a minute."
            else:
                detail = ("This is taking longer than usual. One of the printer's boards may not be "
                          "answering yet. If nothing changes in a few minutes, check its cable.")
            raw = self.klippy_message
        elif self.klippy_state == "error" and NO_CONFIG.search(self.klippy_message or ""):
            # a fresh card: three ways to a config (two for now), not Try again
            state, phase, headline = "setup", "no_config", SETUP_HEADLINE
            detail = SETUP_DETAIL_FOUND if self.setup_found else SETUP_DETAIL_NOTHING
            raw = self.klippy_message
            actions = [_action("bring_open", "Bring it over", primary=True), _action("write_own", "Write my own")]
        elif self.klippy_state in ("shutdown", "error"):
            state = "problem"
            headline, detail, phase = _translate_error(self.klippy_message)
            raw = self.klippy_message
            actions = [_action("try_again", "Try again", primary=True, style="red"),
                       _action("help", "Show me what to check")]

        # 2. Klipper is up. Where is the job?
        elif pstate == "error":
            state = "problem"
            headline, detail, phase = _translate_error(ps.get("message") or "")
            raw = ps.get("message") or ""
            actions = [_action("try_again", "Try again", primary=True, style="red"),
                       _action("help", "Show me what to check")]

        elif self._swap is not None and self._swap.get("error"):
            sw = self._swap
            state, phase = "problem", "swap_failed"
            what = sw["to_name"] or f"slot {sw['to'] + 1}"
            headline = (f"Loading {what} didn't finish." if sw["to"] >= 0
                        else f"Unloading {sw['from_name'] or 'the filament'} didn't finish.")
            low = sw["error"].lower()
            if "not ready" in low:
                detail = "That slot doesn't have filament ready. Push the filament into the unit until it catches, then try again."
            elif "sensor" in low or "timeout" in low or "did not" in low or "didn't" in low:
                detail = "The filament didn't get where it should. Check the tube between the unit and the head is clear, then try again."
            else:
                detail = "It stopped partway. Check the head, then try again."
            raw = sw["error"]
            retry = (_action("load_spool", "Try again", primary=True, style="red", slot=sw["to"]) if sw["to"] >= 0
                     else _action("unload_spool", "Try again", primary=True, style="red"))
            actions = [retry, _action("dismiss_swap", "It's sorted")]

        elif self._swap is not None:
            sw = self._swap
            state = "preparing"
            names = dict(self._swap_labels(sw))
            wanted = self._swap_wanted(sw)
            at = SWAP_STEPS[sw["step"]][0] if sw["step"] >= 0 else wanted[0]
            idx = wanted.index(at) if at in wanted else 0
            for i, k in enumerate(wanted):
                steps.append({"id": k, "label": names[k], "status": "done" if i < idx else ("now" if i == idx else "todo")})
            if sw["to"] >= 0 and sw["purge"]:
                steps.append({"id": "check", "label": "Check it", "status": "todo", "you": True})
            phase = "swap_" + wanted[idx]
            if sw["to"] < 0:
                headline = f"Unloading {sw['from_name'] or 'the filament'}"
            elif sw["from"] is not None:
                headline = f"Switching to {sw['to_name'] or 'slot ' + str(sw['to'] + 1)}"
            else:
                headline = f"Loading {sw['to_name'] or 'slot ' + str(sw['to'] + 1)}"
            if ext.get("target") and ext.get("temperature", 0) < ext.get("target", 0) - 3:
                detail = f"Nozzle at {int(ext.get('temperature', 0))}° of {int(ext['target'])}°."
            else:
                detail = "Keep clear of the nozzle."

        elif self._change is not None:
            state, phase, headline, detail, actions, steps, expires, raw = self._change_intent(now, job)

        elif ((paused or pstate == "paused") and not getting_ready and self._carried and self._pause_since is not None
              and self._carried.get("kind") != "colour" and self._carried["at"] >= self._pause_since - 5):
            # The unit paused for a runout and is switching to a matching spool by itself: nobody's needed.
            c = self._carried
            state, phase = "preparing", "carrying_on"
            headline = f"Switching to slot {c['to'] + 1}"
            detail = f"{c['name'] or 'The spool'} ran out. Same color, same material, so the print carries on by itself."
            actions = [_action("cancel", "Stop this print", hold=True)]

        elif ((paused or pstate == "paused") and not getting_ready and not self.direct
              and (self._pause_reason or {}).get("phase") == "color_change"
              and (self._colour_pause_n() in self._colour_done)):
            # The unit made the planned switch; the print is about to carry on. Nobody's needed.
            c = self._carried or {}
            state, phase = "preparing", "colour_resuming"
            headline = f"Carrying on with {c.get('name') or 'the new spool'}"
            detail = f"{_at_layer(c.get('layer')).capitalize()}, as planned. Nobody's needed."
            actions = [_action("cancel", "Stop this print", hold=True)]

        elif (paused or pstate == "paused") and not getting_ready:
            state = "needs_you"
            reason = self._pause_reason or {}
            phase = reason.get("phase", "paused")
            since = self._pause_since or now
            expires = since + NEEDS_YOU_HOLD_SECONDS
            slot = reason.get("slot")
            spool = next((s for s in spools if s["slot"] == slot), None) if slot is not None else None
            colour = _color_name(spool["color"]) if spool else None
            material = spool["material"] if spool and spool["material"] else "filament"
            what = f"{colour} {material}" if colour else material.capitalize()
            slot_h = (slot + 1) if slot is not None else None   # people count from 1
            alt = self.find_alternative(spools, slot)
            into = f" into slot {slot_h}" if slot_h is not None and not self.direct else ""

            if phase in ("runout", "color_change") and self.direct:
                # One spool and a person's hands: the change routine takes it from here, so the
                # print only carries on once the new filament has reached the nozzle.
                job_name = job["name"] if job else "The print"
                if phase == "runout":
                    headline = f"{what} ran out."
                    detail = (f"{job_name} is paused. Load a new spool and I'll walk you through it. "
                              f"I'll keep everything warm for 20 minutes.")
                    actions = [_action("change_start", "Load a new spool", primary=True, style="amber", kind="change"),
                               _action("cancel", "Stop this print", hold=True)]
                else:
                    headline = "Time to change the color."
                    detail = f"{job_name} is paused. I'll take out {what} and walk you through the new one."
                    actions = [_action("change_start", "Change it now", primary=True, style="amber", kind="change"),
                               _action("cancel", "Stop this print", hold=True)]
            elif phase == "runout":
                headline = f"{what} ran out."
                if alt:
                    detail = (f"Load a new spool into slot {slot_h}, or let me switch to the "
                              f"{_color_name(alt['color']).lower()} in slot {alt['slot'] + 1}. "
                              f"I'll keep everything warm for 20 minutes.")
                    actions = [_action("swap_slot", f"Use slot {alt['slot'] + 1} instead", primary=True, style="amber", slot=alt["slot"]),
                               _action("loaded", "I've loaded a new spool")]
                else:
                    detail = (f"Load a new spool{into} and I'll carry on. "
                              f"I'll keep everything warm for 20 minutes.")
                    actions = [_action("loaded", "I've loaded a new spool", primary=True, style="amber"),
                               _action("cancel", "Stop this print", hold=True)]
            elif phase == "feed_error":
                headline = f"{what} isn't feeding."
                detail = (f"Check the spool{f' in slot {slot_h}' if into else ''} isn't tangled and the tube is clear, "
                          f"then tell me to carry on.")
                actions = [_action("resume", "Carry on", primary=True, style="amber"),
                           _action("cancel", "Stop this print", hold=True)]
            elif phase == "color_change" and self.unit_state() is not None:
                # A printer with a unit: its spools are the answer, and the pause says why it's a pause (A)
                headline, detail, actions, colour_view = self._colour_pause(spools, job, now)
                expires = max(since, self._colour_attended or 0) + NEEDS_YOU_HOLD_SECONDS
            elif phase == "color_change":
                headline = "Time to change the color."
                detail = "Swap the spool, then tell me to carry on."
                actions = [_action("resume", "Carry on", primary=True, style="amber"),
                           _action("cancel", "Stop this print", hold=True)]
            else:
                headline = "Paused."
                detail = "The print is waiting for you. Everything is warm and safe."
                actions = [_action("resume", "Carry on", primary=True, style="amber"),
                           _action("cancel", "Stop this print", hold=True)]
            raw = ps.get("message") or ""

        elif pstate == "printing" or getting_ready:
            if self._print_started and not getting_ready:
                state, phase = "printing", "printing"
                headline = job["name"] if job else "Printing"
                if job and job.get("eta_clock"):
                    detail = f"Done at about {job['eta_clock']}"
                else:
                    detail = "Working out the finish time"
                actions = [_action("pause", "Pause"), _action("cancel", "Stop this print", hold=True)]
            else:
                state = "preparing"
                idx = self._prep_index
                if prep_stage in PRINT_START_STAGES:
                    step_id = PRINT_START_STAGES[prep_stage]
                    idx = next(i for i, s in enumerate(PREP_STEPS) if s["id"] == step_id)
                elif idx < 0 and self._seen_step >= 0:
                    idx = self._seen_step               # a start routine that names no step: what the printer did
                elif idx < 0:
                    # No M117 seen yet: infer from heaters
                    if bed.get("target", 0) and bed.get("temperature", 0) < bed.get("target", 0) - 3:
                        idx = 0
                    elif ext.get("target", 0) and ext.get("temperature", 0) < ext.get("target", 0) - 3:
                        idx = 3
                    else:
                        idx = 0
                phase = PREP_STEPS[min(idx, len(PREP_STEPS) - 1)]["id"]
                words = ART_WORDS.get(self._art_stage() or "")
                for i, s in enumerate(PREP_STEPS):
                    label = OWN_START_LABEL if s["id"] == "leveling" and self._own_start else s["label"]
                    steps.append({"id": s["id"], "label": label,
                                  "status": "done" if i < idx else ("now" if i == idx else "todo")})
                    if i == idx and words:
                        steps[-1]["detail"] = words
                headline = f"Getting ready for {job['name']}" if job else "Getting ready"
                remaining = job.get("remaining_s") if job else None
                if phase == "heating" and ext.get("target"):
                    detail = f"Nozzle at {int(ext.get('temperature', 0))}° of {int(ext['target'])}°."
                elif bed.get("target"):
                    detail = f"Bed at {int(bed.get('temperature', 0))}° of {int(bed['target'])}°."
                else:
                    detail = ""
                # Cancel waits for a homing, levelling or mesh step to finish; Stop now doesn't.
                actions = [_action("cancel", "Cancel"), _action("stop_now", "Stop now", hold=True)]

        elif pstate == "complete" and not self._finished_ack:
            state, phase = "finished", "cooling"
            mat = (job or {}).get("material") or self._last_material
            release = RELEASE_TEMP.get(str(mat).upper(), DEFAULT_RELEASE_TEMP) if mat else DEFAULT_RELEASE_TEMP
            bed_t = float(bed.get("temperature", 0) or 0)
            headline = "Done."
            if bed_t > release + 1:
                # ~1.5 °C/min passive cooling is typical for a heated bed in a warm room
                mins = max(1, int((bed_t - release) / 1.5))
                detail = f"Let the bed cool for about {mins} more minute{'s' if mins != 1 else ''} and the print will pop off without a fight."
                if self.phones_notified:
                    detail += " I'll tell your phone."
            else:
                phase = "ready_to_lift"
                detail = "The bed is cool enough. Lift the print off whenever you like."
            nxt = self.next_plate()
            if nxt:
                # The rest of what was asked for, on the plate Orca made for what didn't fit
                detail += f" The other {nxt['what'] or 'parts'} are on a second plate, ready when the bed is clear."
                actions = [_action("start_file", f"Print the other {nxt['count']}" if nxt.get("count") else "Print the next plate",
                                   primary=True, style="green", filename=nxt["file"]),
                           _action("taken_off", "I've taken it off")]
            else:
                actions = [_action("print_another", "Print another", primary=True, style="green"),
                           _action("taken_off", "I've taken it off")]

        else:
            state, phase = "ready", "idle"
            headline = "Ready"
            if self._cancelled_at and now - self._cancelled_at < CANCELLED_NOTE_SECONDS:
                phase = "cancelled"
                headline = "Print stopped."
                detail = "Clear the bed when you're ready. Nothing else to do."
            else:
                loaded = [s for s in spools if s["status"] in ("ready", "low")]
                low = [s for s in loaded if s["status"] == "low"]
                if self.direct:
                    detail = _direct_ready_words(spools[0])
                elif loaded:
                    detail = f"{len(loaded)} spool{'s' if len(loaded) != 1 else ''} loaded."
                    if low:
                        detail += f" {_color_name(low[0]['color'])} {low[0]['material'] or ''} is running low.".replace("  ", " ")
                else:
                    detail = "No spools loaded yet."
                head = self.head(now)
                units = self.units()
                if head["mismatch"]:
                    phase = "head_" + head["mismatch"]
                    detail = f"{detail} {head['notice']['headline']}"
                    actions = head["actions"][:2]
                elif units and units["flapping"]:
                    phase = "unit_flapping"
                    detail = f"{detail} {units['notice']['headline']}"
                elif units and units["missing"]:
                    phase = "unit_missing"
                    detail = f"{detail} {units['notice']['headline']}"
                    actions = [_action("rescan_units", "Look again", primary=True)]
                elif self.care and self.care.get("hint"):
                    # last: upkeep never hides a hardware problem
                    phase = "care_due"
                    detail = f"{detail} {self.care['hint']}"
                if phase in ("idle", "care_due") and self.klippy_state == "ready":
                    # Warm up before a print: one tap for the spool in the head, or ask
                    head_mat = next((_material_key(s["material"]) for s in spools if s.get("in_use") and s.get("material")), None)
                    if head_mat:
                        actions = [_action("warm_up", f"Warm up for {head_mat}", primary=True, material=head_mat),
                                   _action("warm_choose", "Something else")]
                    else:
                        actions = [_action("warm_choose", "Warm up", primary=True)]
            self._update_warm(now)
            held = self._hands_now(now)
            if held is not None:
                phase, headline, detail, actions = held
            elif self._warm is not None:
                w = self._warm
                if w["reached"] is None:
                    phase = "warming_up"
                    headline = f"Warming up for {w['material']}"
                    mins = (self._warm_view(now, spools, False) or {}).get("minutes") or 1
                    detail = f"About {mins} minute{'s' if mins != 1 else ''}. You can print now; it carries on."
                else:
                    phase = "warmed"
                    headline = f"Warm for {w['material']}"
                    left = max(1, int((w["until"] - now + 59) // 60))
                    detail = f"Staying warm for {left} minute{'s' if left != 1 else ''}. Print whenever you like."
                actions = [_action("cool_down", "Cool down")]
            elif bool(ext.get("target")) or bool(bed.get("target")):
                phase = "warm"
                mins = self.keep_warm_minutes(now)
                if mins is not None:
                    detail = (f"{_direct_ready_words(spools[0]) + ' ' if self.direct else ''}"
                              f"Staying warm for {mins} more minute{'s' if mins != 1 else ''} in case you print next.")
                else:
                    detail = "Heaters are on. Tap to cool down."
                actions = [_action("cool_down", "Cool down")]

        if state != self._last_state_seen():
            self._state_since = now
        self._remember_state(state)
        if job and job.get("material"):
            self._last_material = job["material"]

        return {
            "version": SCHEMA_VERSION,
            "state": state,
            "phase": phase,
            "since": _iso(self._state_since or now),
            "headline": headline,
            "detail": detail,
            "safe": safe,
            "expires": _iso(expires),
            "actions": actions,
            "steps": steps,
            "job": job,
            "art": self.art(state, phase, job),
            "change": self._change_view(),
            "colour": colour_view,
            "first_layer": self._first_layer_view(state, now),
            "parts": self.parts(state),
            "warm": self._warm_view(now, spools, state == "ready" and phase in ("idle", "care_due")
                                    and self.klippy_state == "ready"),
            "spools": self._with_spool_actions(spools, state == "ready" and self.klippy_state == "ready"),
            "units": self._units_view(spools, now),
            "new_spool": self.new_spool_notice(spools) if state == "ready" else None,
            "carried": self._carried_view(now),
            "head": self.head(now),
            "care": dict(self.care, hint=self.care["hint"] if phase == "care_due" else None) if self.care else None,
            "power": self._power_view(),
            "hands": self._hands_view(now) if state == "ready" or self._hands is not None else None,
            "printer": {
                "name": self.printer_name,
                "connected": self.klippy_state == "ready",
                "bed": {"temperature": round(float(bed.get("temperature", 0) or 0), 1), "target": float(bed.get("target", 0) or 0)},
                "nozzle": {"temperature": round(float(ext.get("temperature", 0) or 0), 1), "target": float(ext.get("target", 0) or 0)},
                "chamber": self.chamber(),
            },
            "raw": raw,
            "now": _iso(now),
        }

    # tiny bit of memory for "since"
    _seen_state: Optional[str] = None

    def _last_state_seen(self) -> Optional[str]:
        return self._seen_state

    def _remember_state(self, state: str) -> None:
        self._seen_state = state


# --------------------------------------------------------------------------
# Phone notifications: which changes are worth interrupting someone for.
# The component broadcasts each event; the door (pairing, Web Push) sends it.
# --------------------------------------------------------------------------

NOTIFY_REPEAT_GUARD_SECONDS = 10 * 60   # the same alert again this soon is a flap, not news


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text or "")
    return m.group(1) if m else (text or "")


class Notifier:
    """
    Feed it every intent object; it returns the notification events those
    changes deserve, usually none. Kinds:

        needs_you      paused for a person (runout, colour change, a check)
        problem        stopped during a job; a problem while idle waits for
                       someone to look at the screen
        finished       a print completed
        ready_to_lift  the bed has cooled enough to take the print off

    Each kind is sent once per print for finished/ready_to_lift. Within one
    print, needs_you and problem repeat only when the reason changes or after
    a quiet spell, so a flapping connection doesn't buzz the phone. The first intent after a
    restart only primes it: whatever is on screen then was already news.
    """

    def __init__(self, boot: str):
        self.boot = boot
        self._last_id = 0
        self._prev: Optional[tuple] = None
        self._job: Optional[str] = None
        self._job_sent: set = set()
        self._recent: Dict[str, float] = {}
        self._care_sent: set = set()
        self._your_turn: Optional[List[Any]] = None   # [phase, since, sent] for a change routine step
        self._drying: Dict[int, Dict[str, Any]] = {}   # unit index -> its drying, last seen
        self._carried: Optional[tuple] = None           # the carry-on last told

    def observe(self, intent: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        priming = self._prev is None
        return self._observe_job(intent, now) + self._care_due(intent, now, priming) + self._units(intent, now, priming)

    def _units(self, intent: Dict[str, Any], now: float, priming: bool) -> List[Dict[str, Any]]:
        """A unit that finished drying (not one somebody stopped early), and a print that carried
        on with a matching spool by itself."""
        out = []
        printer = (intent.get("printer") or {}).get("name") or "Printer"
        units = ((intent.get("units") or {}).get("list")) or []
        drying = {u["index"]: dict(u["drying"], name=u["name"]) for u in units if u.get("drying")}
        for idx, was in self._drying.items():
            if idx not in drying and not priming and was["minutes_left"] <= DRY_DONE_MINUTES:
                hours = max(1, round(was["minutes_total"] / 60)) if was["minutes_total"] else None
                body = (f"{was['target']}° for {hours} hour{'s' if hours != 1 else ''}. The spools are ready." if hours
                        else "The spools are ready.")
                out.append(self._event("dried", now, intent, f"{printer}: {was['name']} is done drying", body))
        self._drying = drying
        c = intent.get("carried")
        key = (c["from"], c["to"], c["pct"]) if c else None
        if key and key != self._carried and not priming:
            if c.get("push"):
                # a planned colour change the unit made by itself (design/colour-change/, CPhone)
                out.append(self._event("carried_on", now, intent, f"{printer} {c['push']['title']}", c["push"]["body"]))
            else:
                out.append(self._event("carried_on", now, intent, f"{printer} carried on with slot {c['to'] + 1}",
                                       f"{c['detail']} Same color, same material."))
        self._carried = key
        return out

    def _care_due(self, intent: Dict[str, Any], now: float, priming: bool) -> List[Dict[str, Any]]:
        """One low-priority note per due task, only while the printer is Ready. Again only
        after it stops being due and comes back (a "Later" that ran out); "Done" makes a
        new task id, which starts fresh."""
        items = ((intent.get("care") or {}).get("items")) or []
        due = {i["id"]: i for i in items if i.get("due")}
        self._care_sent &= set(due)
        if intent.get("state") != "ready":
            return []
        out = []
        printer = (intent.get("printer") or {}).get("name") or "Printer"
        for cid, item in due.items():
            if cid in self._care_sent:
                continue
            self._care_sent.add(cid)
            if priming:
                continue   # already due before a restart: the phone heard then
            what = item["name"][0].lower() + item["name"][1:]
            out.append(self._event("care_due", now, intent, f"{printer}: time to {what}",
                                   item.get("note") or "Mark it done in Care when you have."))
        return out

    def _observe_job(self, intent: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
        state, phase = intent.get("state"), intent.get("phase")
        job = intent.get("job") or {}
        job_id = job.get("filename")
        prev, self._prev = self._prev, (state, phase)

        # A step of the change routine that waits on a person is news only if nobody came: the
        # person who started it is usually standing at the printer. Hold it back a while.
        if state == "needs_you" and str(phase).startswith("change_"):
            yt = self._your_turn
            if not yt or yt[0] != phase:
                self._your_turn = [phase, now, False]
            elif not yt[2] and now - yt[1] >= CHANGE_NOTIFY_SECONDS:
                yt[2] = True
                printer = (intent.get("printer") or {}).get("name") or "Printer"
                return self._alert("needs_you", now, intent, f"{printer} needs you",
                                   f"{intent.get('headline', '')} {_first_sentence(intent.get('detail', ''))}".strip())
            return []
        self._your_turn = None

        # A new print, even of the same file, starts with a clean slate.
        if state in ("preparing", "printing") and phase != "starting_up" and (
                job_id != self._job or (prev is not None and prev[0] in ("ready", "finished"))):
            self._job, self._job_sent, self._recent = job_id, set(), {}
        if prev is None or prev == (state, phase):
            return []

        printer = (intent.get("printer") or {}).get("name") or "Printer"
        name = job.get("name") or "Your print"
        headline, detail = intent.get("headline", ""), intent.get("detail", "")
        was_busy = prev[0] in ("printing", "needs_you") or (prev[0] == "preparing" and prev[1] != "starting_up")

        if state == "ready" and phase == "warmed" and prev[1] == "warming_up":
            material = (intent.get("warm") or {}).get("material") or "printing"
            return [self._event("warmed", now, intent, f"{printer} is warm for {material}",
                                f"Staying warm for {WARM_HOLD_SECONDS // 60} minutes.")]
        if state == "needs_you":
            return self._alert("needs_you", now, intent, f"{printer} needs you",
                               f"{headline} {_first_sentence(detail)}".strip())
        if state == "problem" and was_busy:
            return self._alert("problem", now, intent, f"{printer} stopped",
                               f"{headline} {_first_sentence(detail)}".strip())
        if state == "finished":
            if phase == "ready_to_lift":
                if "ready_to_lift" in self._job_sent:
                    return []
                if "finished" in self._job_sent:
                    return [self._event("ready_to_lift", now, intent, f"{printer}: {name} is ready to lift off",
                                        "The bed has cooled. It should pop off without a fight.")]
                self._job_sent.add("ready_to_lift")   # finished and already cool: one message says both
                return [self._event("finished", now, intent, f"{printer}: {name} is done",
                                    "The bed is cool. Lift it off whenever you like.")]
            if "finished" not in self._job_sent:
                return [self._event("finished", now, intent, f"{printer}: {name} is done",
                                    "I'll tell you when the bed is cool enough to lift it off.")]
        return []

    def _alert(self, kind: str, now: float, intent: Dict[str, Any], title: str, body: str) -> List[Dict[str, Any]]:
        key = f"{kind}:{intent.get('phase')}:{intent.get('headline')}"
        last = self._recent.get(key)
        self._recent[key] = now
        if last is not None and now - last < NOTIFY_REPEAT_GUARD_SECONDS:
            return []
        return [self._event(kind, now, intent, title, body)]

    def _event(self, kind: str, now: float, intent: Dict[str, Any], title: str, body: str) -> Dict[str, Any]:
        self._last_id = max(self._last_id + 1, int(now * 1000))   # ids keep rising across restarts
        if kind in ("finished", "ready_to_lift"):
            self._job_sent.add(kind)
        printer = (intent.get("printer") or {}).get("name") or "Printer"
        slug = re.sub(r"[^a-z0-9]+", "-", printer.lower()).strip("-") or "printer"
        attention = kind in ("needs_you", "problem")
        care = kind == "care_due"
        return {
            "boot": self.boot,
            "id": self._last_id,
            "ts": _iso(now),
            "printer": printer,
            "job": None if care or kind == "dried" else (intent.get("job") or {}).get("filename"),
            "kind": kind,
            "urgency": "high" if attention else ("low" if care else "normal"),
            "title": title,
            "body": body,
            # a newer one replaces the older on the phone
            "tag": f"{slug}-{'attention' if attention else ('care' if care else ('unit' if kind == 'dried' else 'job'))}",
            "url": "/care" if care else ("/materials" if kind == "dried" else "/"),
        }


# --------------------------------------------------------------------------
# Actions: what each button does, in printer terms. The UI never sees this.
# --------------------------------------------------------------------------

class ActionPlan:
    """Describes what an action means. The component executes it; the
    simulator pretends to."""
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    GCODE = "gcode"
    UNIT = "unit"            # payload {"op", ...}: a command for the filament-unit service (filament_units.Elyir)
    FIRMWARE_RESTART = "firmware_restart"
    EMERGENCY_STOP = "emergency_stop"   # skips Klipper's command queue, unlike CANCEL_PRINT; Klipper is then restarted in the background
    START_LAST = "start_last"
    START_FILE = "start_file"
    KLIPPY_RESTART = "klippy_restart"
    SWAP = "swap"            # payload {"to": slot or -1, "from": slot or None, "purge": bool}; runs in the background
    ACK_SWAP = "ack_swap"
    ACK_HEAD = "ack_head"    # the spool the printer remembers is in the head; the sensor is wrong
    ACK_FINISHED = "ack_finished"
    REMEMBER_SPOOL = "remember_spool"   # payload {"color", "material"}: what's on a printer without a unit
    CHANGE = "change"        # payload {"op", ...}: an answer to the change routine, for IntentTracker.change_input
    WARM = "warm"            # payload {"op": "start", "material"} or {"op": "stop"}, for IntentTracker.warm_input
    FIRST_LAYER = "first_layer"   # payload {"op", ...}, for IntentTracker.first_layer_input
    SLOT = "slot"            # payload {"op", ...}, for IntentTracker.slot_input (design/slots/)
    POWER = "power"          # payload {"op": "start" | "keep" | "now" | "retry", "kind"}, for IntentTracker.power_input;
                             # the component turns the Pi off or restarts it once IntentTracker.power_due says (design/power/)
    COLOUR = "colour"        # payload {"op": "plan" | "choose", ...}, for IntentTracker.colour_input; a plan is also
                             # stored in Moonraker's database at elyir-bench/colour_plan (design/colour-change/)
    HANDS = "hands"          # payload {"op", ...}, for IntentTracker.hands_input (design/hands-on/)
    NONE = "none"


HANDS_OPS = {"hands_home": "home", "hands_motors_off": "motors_off", "hands_move": "move", "hands_heat": "heat",
             "hands_clear": "clear", "hands_clean": "clean", "hands_nozzle": "nozzle", "hands_lower": "lower",
             "hands_done": "done", "hands_keep": "keep"}


def plan_action(action_id: str, args: Optional[Dict[str, Any]], tracker: IntentTracker) -> List[tuple]:
    """Return an ordered list of (kind, payload) for the component to run."""
    args = args or {}
    if action_id == "pause":
        return [(ActionPlan.PAUSE, None)]
    if action_id in ("resume", "loaded"):
        if tracker._change is not None:
            # Carry on after a change mid-print ends the routine; never in the middle of one.
            if tracker._change["step"] != "resume" or tracker._change["busy"]:
                return []
            return [(ActionPlan.CHANGE, {"op": "end"}), (ActionPlan.RESUME, None)]
        return [(ActionPlan.RESUME, None)]
    if action_id.startswith("change_"):
        return plan_change(action_id, args, tracker)
    if action_id == "colour_choose":
        return plan_colour_choose(args, tracker)
    if action_id == "print_planned":
        return plan_print_planned(args, tracker)
    if action_id == "cancel":
        return [(ActionPlan.CANCEL, None)]
    if action_id == "stop_now":
        return [(ActionPlan.EMERGENCY_STOP, None)]
    if action_id == "swap_slot":
        slot = int(args.get("slot", -1))
        cmds = tracker.unit_commands()
        if slot < 0 or not filament_units.can_change_tool(cmds):
            return []
        return [(cmds.kind, cmds.change_tool(slot)), (ActionPlan.RESUME, None)]
    if action_id in ("try_again", "restart_firmware"):
        return [(ActionPlan.FIRMWARE_RESTART, None)]
    if action_id == "print_another":
        return [(ActionPlan.START_LAST, None)]
    if action_id == "taken_off":
        return [(ActionPlan.ACK_FINISHED, None)]
    if action_id == "cool_down":
        return [(ActionPlan.WARM, {"op": "stop"}), (ActionPlan.HANDS, {"op": "stop"}), (ActionPlan.GCODE, "TURN_OFF_HEATERS")]
    if action_id in HANDS_OPS:
        if tracker.hands_why_not():
            return []
        return [(ActionPlan.HANDS, dict(args, op=HANDS_OPS[action_id]))]
    if action_id == "warm_up":
        material = _material_key(args.get("material"))
        if (tracker.klippy_state != "ready" or not material or material not in WARM_BED
                or (tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused")
                or tracker._change is not None or tracker._swap is not None):
            return []
        return [(ActionPlan.WARM, {"op": "start", "material": material})]
    if action_id in FIRST_LAYER_OPS:
        if tracker.klippy_state != "ready":
            return []
        payload = dict(FIRST_LAYER_OPS[action_id])
        return [(ActionPlan.FIRST_LAYER, payload)] if tracker.first_layer_ok(payload) else []
    if action_id in ("help", "bring_open", "write_own"):   # the screens open these themselves
        return [(ActionPlan.NONE, None)]
    if action_id == "skip_part":
        # design/skip-objects/: one part stops, the rest carry on. Klipper names have no spaces (Orca's labels).
        name = str(args.get("name") or "").strip()
        if not name or not re.fullmatch(r"[^\s]+", name) or not tracker.skip_ok(name):
            return []
        return [(ActionPlan.GCODE, f"EXCLUDE_OBJECT NAME={name}")]
    if action_id == "start_file":
        filename = str(args.get("filename") or "").strip()
        return [(ActionPlan.START_FILE, filename)] if filename else []
    if action_id == "set_spool":
        steps = plan_set_spool(args, tracker)
        return steps + [(ActionPlan.SLOT, {"op": "told", "slot": int(args.get("slot", -1))})] if steps and not tracker.direct else steps
    if action_id in ("swap_start", "move_filament", "feed_assist", "dry_unit", "stop_drying", "carry_on", "carried_ok"):
        return plan_slot(action_id, args, tracker)
    if action_id == "confirm_spool":
        # "Yes, that's what's loaded" at print time: remember it, then print.
        spool = _told_spool(args, tracker)
        filename = str(args.get("filename") or "").strip()
        return [(ActionPlan.REMEMBER_SPOOL, spool), (ActionPlan.START_FILE, filename)] if spool and filename else []
    if action_id in ("load_spool", "unload_spool", "mark_loaded"):
        return plan_spool_move(action_id, args, tracker)
    if action_id == "dismiss_swap":
        return [(ActionPlan.ACK_SWAP, None)]
    if action_id == "head_ok":
        if tracker.direct or tracker._selected_slot() is None or tracker.head_loaded() is not False:
            return []
        return [(ActionPlan.ACK_HEAD, None)]
    if action_id in ("power_off", "power_restart"):
        if tracker.power_why_not() or tracker._power is not None:
            return []
        kind = "off" if action_id == "power_off" else "restart"
        heaters = [(ActionPlan.WARM, {"op": "stop"}), (ActionPlan.GCODE, "TURN_OFF_HEATERS")] if tracker.klippy_state == "ready" else []
        return heaters + [(ActionPlan.POWER, {"op": "start", "kind": kind})]
    if action_id in ("power_keep", "power_now", "power_retry"):
        return [(ActionPlan.POWER, {"op": action_id[len("power_"):]})] if tracker._power is not None else []
    if action_id == "rescan_units":
        # Restarting the printer's software is how the filament units are looked for again.
        # Never during a print.
        if (tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
            return []
        return [(ActionPlan.KLIPPY_RESTART, None)]
    return []


# Squish more = closer to the bed = a lower Z offset.
FIRST_LAYER_OPS = {"squish_more": {"op": "nudge", "by": -SQUISH_STEP}, "squish_less": {"op": "nudge", "by": SQUISH_STEP},
                   "keep_first_layer": {"op": "keep"}, "just_this_once": {"op": "once"},
                   "first_layer_back": {"op": "back"}, "first_layer_clear": {"op": "clear"},
                   "first_layer_keep_old": {"op": "keep_old"}}

CHANGE_OPS = {"change_out": "out", "change_in": "in", "change_what": "what", "change_good": "good",
              "change_more": "more", "change_stop": "stop", "change_retry": "retry", "change_end": "end"}


def plan_change(action_id: str, args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """Start the change routine, or answer it. Starting needs a printer without a unit that's
    idle, or paused mid-print waiting for a person; the answers need a routine in progress."""
    if tracker.klippy_state != "ready":
        return []
    if action_id == "change_start":
        kind = str(args.get("kind") or "change")
        if kind not in ("change", "unload", "load") or not tracker.direct:
            return []
        if tracker._change is not None or tracker._swap is not None:
            return []
        ps = tracker.status.get("print_stats") or {}
        paused = bool((tracker.status.get("pause_resume") or {}).get("is_paused"))
        if ps.get("state") in ("printing", "paused") and not (paused and kind == "change"):
            return []
        return [(ActionPlan.CHANGE, {"op": "start", "kind": kind})]
    op = CHANGE_OPS.get(action_id)
    if op is None or tracker._change is None:
        return []
    c = tracker._change
    if op == "good" and c["kind"] == "colour":
        # "Looks good, carry on": one tap ends the check and the print carries on (3 October 2026)
        if c["step"] != "check" or c["busy"] or c["error"]:
            return []
        return [(ActionPlan.CHANGE, {"op": "good"}), (ActionPlan.RESUME, None)]
    if op == "what":
        material = _material_key(args.get("material"))
        if not material or not re.fullmatch(r"[A-Z0-9\-]{2,12}", material):
            return []
        return [(ActionPlan.CHANGE, {"op": "what", "material": material, "color": _hex_color(args.get("color"))})]
    return [(ActionPlan.CHANGE, {"op": op})]


def plan_colour_choose(args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """A choice at a colour-change pause on a printer with a unit (design/colour-change/, A): keep the spool in
    the head, switch to a loaded one, put a spool into an empty slot, or swap a full slot's spool (only with
    SLOT_SWAP_WHILE_PAUSED). A different material from the print's is asked about first: it needs sure."""
    if tracker.klippy_state != "ready" or tracker._change is not None or not tracker._paused_for_colour():
        return []
    if tracker._swap is not None and not tracker._swap.get("error"):
        return []
    how = str(args.get("how") or "")
    slot = _int(args.get("slot"))
    s = tracker._slot_now(slot) if slot is not None else None
    if not s:
        return []
    head = tracker._selected_slot()
    if how == "keep":
        if slot != head or tracker.head_loaded() is False:
            return []
        return [(ActionPlan.COLOUR, {"op": "choose", "slot": slot, "how": "keep"}), (ActionPlan.RESUME, None)]
    if how == "switch":
        if s["status"] not in ("ready", "low") or slot == head:
            return []
        material = tracker._colour_now()["material"]
        if material and s.get("material") and _material_key(s["material"]) != material and args.get("sure") is not True:
            return []   # asked about first, never refused
    elif how == "put_in":
        if s["status"] != "empty":
            return []
    elif how == "swap":
        if not SLOT_SWAP_WHILE_PAUSED or s["status"] not in ("ready", "low") or slot == head:
            return []
    else:
        return []
    return [(ActionPlan.COLOUR, {"op": "choose", "slot": slot, "how": how})]


def plan_print_planned(args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """Print from the Print sheet with its colour changes planned (design/colour-change/, C): one entry per
    M600 the sheet showed, a loaded spool or "pause". A spool of another material needs sure. Checked against
    what check_print found in the file, then stored, then the file starts."""
    filename = str(args.get("filename") or "").strip()
    checked = tracker._checked.get(filename)
    changes = args.get("changes")
    if (tracker.klippy_state != "ready" or tracker.direct or not filename or not checked
            or not isinstance(changes, list) or len(changes) != len(checked["changes"])):
        return []
    if (tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
        return []
    spools = {s["slot"]: s for s in tracker.spools()}
    material = checked["material"]
    out = []
    for want, ch in zip(checked["changes"], changes):
        if not isinstance(ch, dict):
            return []
        slot = ch.get("slot")
        if slot == "pause":
            out.append({"layer": want["layer"], "slot": "pause", "color": want["color"]})
            continue
        g = _int(slot)
        s = spools.get(g) if g is not None and not isinstance(slot, bool) else None
        if not s or s["status"] not in ("ready", "low"):
            return []
        if material and s.get("material") and _material_key(s["material"]) != material and ch.get("sure") is not True:
            return []
        out.append({"layer": want["layer"], "slot": g, "color": want["color"]})
    return [(ActionPlan.COLOUR, {"op": "plan", "filename": filename, "changes": out}), (ActionPlan.START_FILE, filename)]


def swap_gcode(payload: Dict[str, Any], cmds: Optional[Any] = None) -> str:
    """The filament unit's tool change for a swap payload, by its driver (KlipperACE when not given)."""
    return (cmds or filament_units.DRIVERS["klipperace"]).change_tool(int(payload["to"]), payload.get("purge", True))


def plan_spool_move(action_id: str, args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """Load, unload, or correct which spool is in the head. Only while the printer is idle;
    loading only from a slot that has filament ready."""
    cmds = tracker.unit_commands()
    if tracker.klippy_state != "ready" or tracker.direct or cmds is None:
        return []
    if (tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
        return []
    if tracker._swap is not None and not tracker._swap.get("error"):
        return []
    spools = {s["slot"]: s for s in tracker.spools()}
    sel = tracker._selected_slot()
    if action_id == "unload_spool":
        if sel is None or not filament_units.can_change_tool(cmds):
            return []
        return [(ActionPlan.SWAP, {"to": -1, "from": sel, "purge": False})]
    try:
        slot = int(args.get("slot", -2))
    except (TypeError, ValueError):
        return []
    if action_id == "mark_loaded":
        if slot != -1 and slot not in spools:
            return []
        return [(cmds.kind, cmds.mark_loaded(slot))]
    # load_spool
    if slot not in spools or spools[slot]["status"] not in ("ready", "low") or slot == sel:
        return []
    if not filament_units.can_change_tool(cmds):
        return []
    return [(ActionPlan.SWAP, {"to": slot, "from": sel, "purge": tracker.should_purge(slot)})]


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def plan_slot(action_id: str, args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """What a slot and its unit can do (design/slots/, B): swap a spool, move filament, feed
    assist, drying, and carrying on with a matching spool. Refused on a printer without a unit."""
    cmds = tracker.unit_commands()
    if tracker.klippy_state != "ready" or cmds is None:
        return []
    on = args.get("on") in (True, 1, "1", "true", "True")
    if action_id == "carried_ok":
        return [(ActionPlan.SLOT, {"op": "carried_ok"})]
    if action_id == "carry_on":
        if tracker.carry_on() is None:
            return []
        return [(cmds.kind, cmds.carry_on(on))]
    if action_id in ("dry_unit", "stop_drying"):
        units = {u["index"]: u for u in tracker._units_raw()}
        u = units.get(_int(args.get("unit")))
        if not u or not u["connected"]:
            return []
        if action_id == "stop_drying":
            return [(cmds.kind, cmds.stop_drying(u))]
        hours = _int(args.get("hours"))
        if hours is None or not DRY_HOURS[0] <= hours <= DRY_HOURS[1]:
            return []
        slots = [s for s in tracker.spools() if u["offset"] <= s["slot"] < u["offset"] + u["n"]]
        temp = tracker.dry_plan(slots)["temp"]
        return [(cmds.kind, cmds.dry(u, temp, hours * 60))]
    spools = {s["slot"]: s for s in tracker.spools()}
    slot = _int(args.get("slot"))
    if slot not in spools:
        return []
    sel = tracker._selected_slot()
    if action_id == "feed_assist":
        # only the slot feeding the head; allowed while printing, which is when it matters
        if slot != sel:
            return []
        return [(cmds.kind, cmds.feed_assist(slot, on)), (ActionPlan.SLOT, {"op": "assist", "slot": slot, "on": on})]
    # swapping and moving filament: idle, nothing else moving
    if (tracker.status.get("print_stats") or {}).get("state") in ("printing", "paused"):
        return []
    if tracker._change is not None or (tracker._swap is not None and not tracker._swap.get("error")):
        return []
    if action_id == "swap_start":
        # the spool in the head comes out with a tool change first
        if spools[slot]["status"] == "empty" or (slot == sel and not filament_units.can_change_tool(cmds)):
            return []
        return [(ActionPlan.SLOT, {"op": "swap", "slot": slot})]
    # move_filament: never the slot in the head, which would grind cold filament
    mm = _int(args.get("mm"))
    if slot == sel or mm is None:
        return []
    empty = spools[slot]["status"] == "empty"
    if empty and mm != PULL_IN_MM:
        return []
    if not empty and abs(mm) not in MOVE_STEPS_MM:
        return []
    return [(cmds.kind, cmds.move(slot, mm))]


def _told_spool(args: Dict[str, Any], tracker: IntentTracker) -> Optional[Dict[str, Any]]:
    """Colour and material someone said is on a printer without a unit. The material is
    needed; a colour is welcome."""
    if not tracker.direct:
        return None
    material = _material_key(args.get("material"))
    if not material or not re.fullmatch(r"[A-Z0-9\-]{2,12}", material):
        return None
    return {"color": _hex_color(args.get("color")), "material": material}


def plan_set_spool(args: Dict[str, Any], tracker: IntentTracker) -> List[tuple]:
    """Colour and material for a spool entered by hand. They live in the filament unit's
    saved variables, which the unit re-reads on every status update. A spool with a tag
    is refused: the tag would win over anything typed here. On a printer without a unit
    the printer just remembers it."""
    if tracker.direct:
        spool = _told_spool(args, tracker)
        return [(ActionPlan.REMEMBER_SPOOL, spool)] if spool else []
    fu, cmds = tracker.unit_state(), tracker.unit_commands()
    if fu is None or cmds is None:
        return []
    try:
        slot = int(args.get("slot", -1))
    except (TypeError, ValueError):
        return []
    spools = tracker.spools()
    if not any(s["slot"] == slot for s in spools):
        return []
    if next(s for s in spools if s["slot"] == slot).get("rfid"):
        return []
    color = _hex_color(args.get("color"))
    material = _material_key(args.get("material"))
    if not color or not material or not re.fullmatch(r"[A-Z0-9\-]{2,12}", material):
        return []
    n = max(len(spools), len(fu["lists"]["color"]))
    lines = cmds.set_spool(fu["lists"], n, slot, color, material, MATERIAL_TEMPS,
                           lambda was, now: _material_key(was) == now)
    return [(cmds.kind, line) for line in lines]
