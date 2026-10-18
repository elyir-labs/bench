"""
What's on the pretend printer: 23 files and the history behind them, as on the Print library
boards (design/print-library/). Two files just sent from Orca and never printed, a folder of
Voron spares, one file sliced without a picture, one whose last attempt failed in seconds (its
own estimate is 41 min), and a past print whose file was removed from Advanced.

`files()` is merged into scenarios.FILES (filename -> Moonraker metadata, with `modified`);
`history()` is SimPrinter.history, newest first, the way server.history.list answers.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

DAY = 86400
BLACK, WHITE, RED, BLUE, GREY, ORANGE = "#2B2B2B", "#F1F1F1", "#D9534F", "#3B82F6", "#8A8D91", "#FF8800"
SPARES = "Voron spares/"


def _file(minutes: float, grams: float, colors: List[str], material: str, thumb: Optional[str],
          age_days: float, slicer: str = "OrcaSlicer", layers: int = 120) -> Dict[str, Any]:
    hot = {"PLA": (60, 215), "PETG": (80, 240), "ASA": (105, 255)}[material]
    meta: Dict[str, Any] = {
        "estimated_time": int(minutes * 60), "layer_count": layers, "layer_height": 0.2,
        "first_layer_bed_temp": hot[0], "first_layer_extr_temp": hot[1],
        "filament_type": ";".join([material] * len(colors)), "filament_colors": colors,
        "filament_weight_total": grams, "filament_weights": [round(grams / len(colors), 1)] * len(colors),
        "filament_total": grams * 330, "object_height": 30, "slicer": slicer,
        "age_days": age_days,   # turned into `modified` when the simulator starts
    }
    if thumb:
        meta["thumbnails"] = [{"width": 400, "height": 300, "size": 9000, "relative_path": f".thumbs/{thumb}"}]
    return meta


# filename -> metadata. Times and grams are the boards'.
LIBRARY: Dict[str, Dict[str, Any]] = {
    "[a]_lid_for_the_parts_bin_0.2mm_PLA_1h12m.gcode": _file(72, 38, [BLUE], "PLA", "parts_bin_lid-400x300.svg", 5 / 1440),
    "spool_holder_PETG_2h40m.gcode": _file(160, 96, ["#1C1C1E"], "PETG", "spool_holder-400x300.svg", 1.05),
    "hinge_pin_x6.gcode": _file(12, 4, [BLACK], "PLA", None, 12),
    "bag_clip_x2.gcode": _file(20, 5, [WHITE], "PLA", None, 30),
    "rear_body_g2e.gcode": _file(76, 14, [GREY], "ASA", None, 40),
    "front_bearing_holder.gcode": _file(14, 3, [GREY], "ASA", None, 120),
    "cable_chain_2_hole.gcode": _file(46, 8, [GREY], "ASA", None, 121),
    "rear_body.gcode": _file(99, 19, [GREY], "ASA", None, 122),
    "Body80.gcode": _file(41, 10, [GREY], "ASA", None, 123),
    "Body1.gcode": _file(211, 46, [GREY], "ASA", None, 124),
    "Body2.gcode": _file(421, 91, [GREY], "ASA", None, 125),
    SPARES + "voron_cube_ASA.gcode": _file(48, 21, [GREY, "#C0262C"], "ASA", "voron_cube-400x300.svg", 60),
    SPARES + "skirt_clip_x4.gcode": _file(18, 4, [BLACK], "PLA", None, 61),
    SPARES + "z_belt_clamp.gcode": _file(22, 5, [BLACK], "PLA", None, 62),
    SPARES + "bed_spacer_x3.gcode": _file(9, 2, [BLACK], "PLA", None, 63),
    SPARES + "door_handle.gcode": _file(35, 11, [RED], "PLA", None, 64),
    SPARES + "filament_latch.gcode": _file(16, 3, [RED], "PLA", None, 65),
    SPARES + "panel_clip_x8.gcode": _file(28, 6, [BLACK], "PLA", None, 66),
    SPARES + "hall_effect_cover.gcode": _file(11, 2, [RED], "PLA", None, 67),
}
# How old the original four files are (scenarios.FILES), so the shelf reads like Workshop's.
AGES = {"phone_stand_0.2mm_PLA_MK4_1h40m.gcode": 20, "cable_clip_x4.gcode": 25,
        "Benchy.gcode": 19, "planter_orange_PETG_2h5m.gcode": 33}
# Printed once, two weeks ago, then removed from Advanced: in history, not on the printer.
GONE = {"filament_guide.gcode": _file(18, 6, [WHITE], "PLA", "filament_guide-400x300.svg", 16)}

# (filename, days ago, status, seconds printed); several per file, newest first.
JOBS = [
    ("phone_stand_0.2mm_PLA_MK4_1h40m.gcode", 1, "completed", 6000),
    ("cable_clip_x4.gcode", 2, "completed", 1500),
    ("Benchy.gcode", 5, "completed", 3400),
    (SPARES + "voron_cube_ASA.gcode", 7, "completed", 2900),
    ("filament_guide.gcode", 14, "completed", 1080),
    ("rear_body_g2e.gcode", 21, "completed", 4560),
    ("Body80.gcode", 22, "klippy_shutdown", 20),     # the last attempt: under a minute
    ("cable_clip_x4.gcode", 23, "completed", 1500),
    ("phone_stand_0.2mm_PLA_MK4_1h40m.gcode", 24, "completed", 6000),
    ("bag_clip_x2.gcode", 26, "completed", 1200),
    ("Benchy.gcode", 27, "completed", 3400),
    ("planter_orange_PETG_2h5m.gcode", 30, "completed", 7500),
    ("cable_clip_x4.gcode", 31, "completed", 1500),
    ("bag_clip_x2.gcode", 32, "cancelled", 300),
    (SPARES + "voron_cube_ASA.gcode", 45, "completed", 2900),
    ("Benchy.gcode", 50, "completed", 3400),
    ("cable_clip_x4.gcode", 52, "completed", 1500),
    ("phone_stand_0.2mm_PLA_MK4_1h40m.gcode", 55, "completed", 6000),
    (SPARES + "skirt_clip_x4.gcode", 61, "completed", 1080),
    (SPARES + "z_belt_clamp.gcode", 62, "completed", 1320),
    (SPARES + "bed_spacer_x3.gcode", 63, "completed", 540),
    (SPARES + "door_handle.gcode", 64, "completed", 2100),
    (SPARES + "filament_latch.gcode", 65, "completed", 960),
    (SPARES + "panel_clip_x8.gcode", 66, "completed", 1680),
    (SPARES + "hall_effect_cover.gcode", 67, "completed", 660),
    ("cable_clip_x4.gcode", 70, "completed", 1500),
    ("phone_stand_0.2mm_PLA_MK4_1h40m.gcode", 80, "completed", 6000),
    ("cable_clip_x4.gcode", 90, "completed", 1500),
    ("front_bearing_holder.gcode", 120, "completed", 840),
    ("cable_chain_2_hole.gcode", 121, "completed", 2760),
    ("rear_body.gcode", 122, "completed", 5940),
    ("Body80.gcode", 123, "completed", 2460),
    ("Body1.gcode", 124, "completed", 12660),
    ("Body1.gcode", 124.5, "completed", 12660),
    ("Body2.gcode", 125, "completed", 25260),
    ("Body1.gcode", 126, "completed", 12660),
    ("Body2.gcode", 127, "cancelled", 3000),
    ("Body1.gcode", 128, "completed", 12660),
]


def files(originals: Dict[str, Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Every file on the pretend printer, each with Moonraker's `modified` (seconds)."""
    now = now or time.time()
    out: Dict[str, Dict[str, Any]] = {}
    for name, meta in {**originals, **LIBRARY}.items():
        m = dict(meta)
        m["modified"] = now - float(m.pop("age_days", AGES.get(name, 10))) * DAY
        out[name] = m
    return out


def history(metadata: Dict[str, Dict[str, Any]], now: Optional[float] = None) -> List[Dict[str, Any]]:
    now = now or time.time()
    jobs = []
    for i, (name, days, status, secs) in enumerate(JOBS):
        meta = metadata.get(name) or dict(GONE.get(name, {}))
        meta.pop("age_days", None)
        start = now - days * DAY
        jobs.append({"job_id": f"{0x100 - i:06X}", "filename": name, "status": status,
                     "start_time": start, "end_time": start + secs, "print_duration": secs,
                     "total_duration": secs + 300, "filament_used": float(meta.get("filament_total") or 0),
                     "metadata": meta})
    return jobs
