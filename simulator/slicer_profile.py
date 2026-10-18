"""
Slicing like their prints (docs/slicer-profile.md, design/getting-started/ C), as the simulator plays it.

The state behind GET /printer/intent/profile and its actions (profile_use, profile_told, profile_keep). On a
printer the Moonraker component reads the settings block at the end of each OrcaSlicer file; here the profiles
it would have found are written out by the scenarios (profile_found, profile_ask, profile_newer, profile_none).
Every other scenario plays a printer whose printer.json was written by hand: "yours", nothing learned.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

DAY = 86400
KLIPPER_BED = [350, 350]   # the simulator's toolhead.axis_maximum


def profile(pid: str, process: str, nozzle: float, files: int, days_ago: float,
            materials: Dict[str, Any], printer: str = "Voron 2.4 350", bed=(350, 350),
            start: str = "PRINT_START", start_ok: bool = True) -> Dict[str, Any]:
    """One group of files that agree, as the component reports it."""
    bed = [bed[0], bed[1]]
    return {
        "id": pid, "printer": printer, "process": process, "nozzle": nozzle, "bed": bed,
        "files": files, "slicer": "OrcaSlicer 2.3", "newest": int(time.time() - days_ago * DAY),
        "materials": materials, "start": start,
        "checks": {"bed_ok": all(abs(a - b) <= 2 for a, b in zip(bed, KLIPPER_BED)),
                   "bed_klipper": list(KLIPPER_BED), "start_ok": start_ok},
    }


def mat(preset: str, files: int) -> Dict[str, Any]:
    return {"preset": preset, "files": files}


class SlicerProfile:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """A hand-written printer.json (the owner's printers): nothing learned, the app slices as before."""
        self.set("yours", [], None, told=True)

    def set(self, state: str, found: List[Dict[str, Any]], using: Optional[str], told: bool = False) -> None:
        self.state = state
        self.found = found
        self.using = using
        self.told = told
        self.kept: List[str] = []   # newer profiles declined with profile_keep: never offered again

    # ---- the scenarios' printers ----------------------------------------------------------------

    def play_found(self) -> None:
        """Using, not told: 15 files agree; two older ones carry something else (one for another bed)."""
        self.set("using", [
            profile("a1b2", "0.20mm Standard @Voron", 0.4, 15, 1,
                    {"PLA": mat("Generic PLA @Voron", 12), "PETG": mat("Generic PETG @Voron", 3)}),
            profile("c3d4", "0.20mm Strength @Voron", 0.4, 1, 40, {"PETG": mat("Generic PETG @Voron", 1)}),
            profile("e5f6", "0.20mm Standard @Voron", 0.4, 1, 120, {"PLA": mat("Generic PLA @Voron", 1)},
                    printer="Voron 2.4 300", bed=(300, 300)),
        ], "a1b2")

    def play_ask(self) -> None:
        """The files disagree: two nozzles, 0.4 in 9 files and 0.6 in 4."""
        self.set("ask", [
            profile("a1b2", "0.20mm Standard @Voron", 0.4, 9, 2,
                    {"PLA": mat("Generic PLA @Voron", 7), "PETG": mat("Generic PETG @Voron", 2)}),
            profile("b7c8", "0.30mm Standard @Voron 0.6 nozzle", 0.6, 4, 5,
                    {"PETG": mat("Generic PETG @Voron", 3), "ASA": mat("Generic ASA @Voron", 1)},
                    printer="Voron 2.4 350 0.6 nozzle"),
        ], None)

    def play_newer(self) -> None:
        """Slicing like Standard (told long ago); the newer files use Strength."""
        self.set("newer", [
            profile("a1b2", "0.20mm Standard @Voron", 0.4, 15, 9,
                    {"PLA": mat("Generic PLA @Voron", 12), "PETG": mat("Generic PETG @Voron", 3)}),
            profile("c3d4", "0.20mm Strength @Voron", 0.4, 6, 0.5,
                    {"PETG": mat("Generic PETG @Voron", 4), "ASA": mat("Generic ASA @Voron", 2)}),
        ], "a1b2", told=True)

    def play_none(self) -> None:
        """No file carries a settings block (Cura, PrusaSlicer, or nothing sliced yet): slicing waits."""
        self.set("none", [], None)

    # ---- GET /printer/intent/profile ----------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {"state": self.state, "told": self.told, "using": self.using, "found": deepcopy(self.found),
                "bed_klipper": list(KLIPPER_BED)}

    # ---- actions ----------------------------------------------------------------------------------

    def act(self, action: str, args: Dict[str, Any]) -> Optional[str]:
        """Do it, or say in words why the printer wouldn't."""
        if action == "profile_use":
            pid = str(args.get("id", ""))
            if not any(p["id"] == pid for p in self.found):
                return "Those settings aren't in this printer's files any more."
            self.using, self.state = pid, "using"   # printer.json and presets/0-learned/ written from it
        elif action == "profile_told":
            self.told = True
        elif action == "profile_keep":
            if self.state != "newer":
                return "There's nothing newer to keep these over."
            using = next((p for p in self.found if p["id"] == self.using), None)
            self.kept += [p["id"] for p in self.found
                          if p["id"] != self.using and using and p["newest"] > using["newest"]]
            self.state = "using"
        return None


ACTIONS = ("profile_use", "profile_told", "profile_keep")
