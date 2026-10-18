"""
Finish setting up (docs/setup-card.md, design/getting-started/ C), as the simulator plays it.

The state behind GET /printer/intent/setup and the card's actions. sim.py runs the timed parts
(fetching the screen's parts, the 120 s trial, the include going in) and publishes the intent;
this file only keeps the state and says what the printer would answer.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

TRIAL_S = 120          # the screen trial, then back to KlipperScreen by itself
FETCH_S = 6.0          # "fetching what it needs": apt on a real printer, a few seconds here
INCLUDE_S = 2.5        # writing elyir-bench.cfg and the include line, before Klipper restarts

SLICER_LINES = {
    "before": "ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]",
    "after": "ELYIR_BENCH_PRINT_START_DONE",
}
# expectations() as the installer saves it (installer/elyir_bench.py): a Raspberry Pi 4 that can't slice by itself
BOARD = {
    "board": "Raspberry Pi 4, 2 GB, Debian 12",
    "verdict": "differences",
    "why_not": None,
    "differences": ["It can't slice by itself. Another printer with Elyir Bench on your Wi-Fi can slice for it; "
                    "files from your own slicer print as always."],
    "note": None,
}
ROW_IDS = ("notify", "screen", "works")


class SetupCard:
    def __init__(self) -> None:
        self.reset(active=False)

    def reset(self, active: bool, screen: Optional[str] = "offer", why: Optional[str] = None) -> None:
        """active: the install command just ran here, so the phone shows the card (setup_new)."""
        self.active = active
        self.dismissed: List[str] = []
        self.screen = screen            # None: no screen, or it already runs Elyir Bench; the row isn't sent
        self.screen_why = why           # with "cant"
        self.cant_after_fetch = why is not None and screen == "offer"   # setup_cant: the fetch fails
        self.parts = False              # the screen's parts are in (fetched once, by the first Try it)
        self.include = "off"
        self.include_why: Optional[str] = None
        self.name_from = "mainsail"
        self.trial_until: Optional[float] = None

    # ---- what the intent carries -----------------------------------------------------------------

    def trial(self, now: float) -> Optional[Dict[str, int]]:
        if self.trial_until is None:
            return None
        return {"seconds_left": max(0, math.ceil(self.trial_until - now))}

    def done(self, row: str, phones: bool) -> bool:
        """The printer's view of a finished row. Notifications: some phone listens (elyir-bench/phones)."""
        if row == "notify":
            return phones
        if row == "screen":
            return self.screen in (None, "done", "kept_klipperscreen")
        return self.include == "on"

    def open(self, phones: bool) -> bool:
        return self.active and any(r not in self.dismissed and not self.done(r, phones) for r in ROW_IDS)

    # ---- GET /printer/intent/setup -----------------------------------------------------------------

    def features(self, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
        """What works on this printer, from the pretend printer's own objects (facts: runout, camera, unit, chamber)."""
        on = self.include == "on"
        macro = "now" if on else "with_macro"
        out: List[Dict[str, Any]] = [{"id": "core", "group": "now", "label": "Ready, printing, history, Care"}]
        if facts.get("runout"):
            out.append({"id": "runout", "group": "now", "label": "Filament runs out", "note": "Your runout sensor"})
        if facts.get("camera"):
            out.append({"id": "camera", "group": "now", "label": "Camera"})
        if facts.get("unit"):
            out.append({"id": "unit", "group": "now", "label": "Filament unit slots"})
        steps = {"id": "steps", "group": macro, "label": "The steps while it gets ready"}
        if not on:
            steps["note"] = "Rough today, from your messages"
        out += [steps,
                {"id": "cancel", "group": macro, "label": "Cancel while it warms up"},
                {"id": "squish", "group": macro, "label": "Squish the first layer more or less"}]
        if facts.get("chamber"):
            out.append({"id": "chamber", "group": macro, "label": "Wait for the chamber to warm"})
        if not facts.get("unit"):
            out.append({"id": "unit", "group": "not_here", "label": "Filament unit slots", "note": "No ACE Pro found"})
        return out

    def info(self, name: str, facts: Dict[str, Any]) -> Dict[str, Any]:
        feats = self.features(facts)
        count = lambda g: sum(1 for f in feats if f["group"] == g)
        rows: List[Dict[str, Any]] = [{"id": "notify"}]
        if self.screen is not None:
            row: Dict[str, Any] = {"id": "screen", "state": self.screen}
            if self.screen == "cant":
                row["why"] = self.screen_why
            rows.append(row)
        rows.append({"id": "works", "now": count("now"), "with_macro": count("with_macro")})
        return {
            "name": name, "name_from": self.name_from,
            "secure_link": getattr(self, "secure_link", "waiting"),   # a tester on day one: claimed, not approved yet
            "rows": rows,
            "dismissed": list(self.dismissed),
            "works": {
                "board": dict(BOARD, differences=list(BOARD["differences"])),
                "features": feats,
                "include": self.include,
                "include_why": self.include_why if self.include == "failed" else None,
                "include_text": "[include elyir-bench.cfg]",
                "slicer_lines": dict(SLICER_LINES),
            },
        }

    # ---- actions: the checks; sim.py does the waiting ------------------------------------------

    def refusal(self, action: str, printing: bool) -> Optional[str]:
        """Why the printer would refuse this action now, in words, or None."""
        if action in ("screen_try",):
            if self.screen is None:
                return "This printer has no screen to try it on."
            if self.screen == "cant":
                return self.screen_why or "This printer's screen can't run Elyir Bench."
            if self.screen in ("fetching", "trial"):
                return "The screen is already being tried."
        if action in ("screen_keep", "screen_back") and self.trial_until is None:
            return "The screen isn't on trial."
        if action in ("include_add", "include_remove"):
            if printing:
                return "Not while it prints. Try again once the print is done."
            if self.include in ("adding", "removing"):
                return "Klipper is already restarting for that."
        return None
