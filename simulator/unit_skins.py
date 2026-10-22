"""--units afc / --units happy_hare: the simulator's pretend ACE Pros shown to Bench as AFC's lanes or Happy Hare's
gates, and their commands turned back into the pretend's own. The pretend keeps KlipperACE's `ace` underneath, so
every scenario still works; only what Bench sees and sends changes."""
from typing import Any, Dict, List, Optional, Tuple

SKINS = ("afc", "happy_hare")
SIM_TUBE_MM = 742.0   # what the pretend unit's tube to the head measures (the check, design/unit-setup/)


def _slot_states(ace: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for dev in ace.get("devices") or []:
        out += [str(s.get("status") or "unknown") for s in (dev.get("status") or {}).get("slots") or []]
    return out


def lane_name(g: int) -> str:
    return f"lane{g + 1}"


def view(skin: str, ace: Dict[str, Any]) -> Dict[str, Any]:
    """The objects AFC or Happy Hare would report for this `ace`."""
    states = _slot_states(ace)[:ace.get("sim_slots") or None]   # sim_slots: as many as the unit set up has
    n = len(states)
    colors, mats, temps = ace.get("gate_color") or [], ace.get("gate_material") or [], ace.get("gate_temp") or []
    sel = ace.get("selected_gate")
    sel = sel if isinstance(sel, int) and sel >= 0 else None
    at = lambda lst, g, d="": lst[g] if g < len(lst) else d
    if skin == "happy_hare":
        # one ERCF with a gate for every pretend slot, as an ERCF is one unit of 4 to 12 gates
        return {
            "mmu": {"enabled": True, "num_gates": n, "gate": -1 if sel is None else sel, "tool": -1 if sel is None else sel,
                    "filament": "Unloaded" if sel is None else "Loaded", "action": "Idle", "print_state": "idle",
                    "gate_status": [1 if st == "ready" else 0 if st == "empty" else -1 for st in states],
                    "gate_material": [str(at(mats, g)).upper() for g in range(n)],
                    "gate_color": [str(at(colors, g)).lower() for g in range(n)],
                    "gate_temperature": [int(at(temps, g, 210)) for g in range(n)],
                    "endless_spool_enabled": 1 if ace.get("endless_spool") else 0, "is_homed": True},
            "mmu_machine": {"happy_hare_version": 4.1, "num_units": 1, "num_gates": n,
                            "unit_0": {"name": "ercf_1", "display_name": "ERCF 1", "first_gate": 0, "num_gates": n,
                                       "selector_type": "LinearSelector"}},
            # an ERCF with a sensor at each gate's entry (Happy Hare 4 names them mmu_entry_N)
            **{f"filament_switch_sensor mmu_entry_{g}": {"filament_detected": st != "empty", "enabled": True}
               for g, st in enumerate(states)},
        }
    out: Dict[str, Any] = {"AFC": {"lanes": [lane_name(g) for g in range(n)], "current_state": "Idle",
                                   "current_load": None if sel is None else lane_name(sel), "error_state": False}}
    for g, st in enumerate(states):
        here = st == "ready"
        color = str(at(colors, g))
        out[f"AFC_stepper {lane_name(g)}"] = {
            "name": lane_name(g), "unit": f"Turtle_{g // 4 + 1}", "lane": g % 4, "map": f"T{g}",
            "load": here, "prep": st != "empty", "tool_loaded": g == sel,
            "color": f"#{color}" if color else "", "material": at(mats, g) or None, "extruder_temp": int(at(temps, g, 210)),
            "hub": f"Turtle_{g // 4 + 1}", "dist_hub": (ace.get("sim_dist_hub") or {}).get(str(g), 60.0)}
    for k in range((n + 3) // 4):
        out[f"AFC_hub Turtle_{k + 1}"] = {"state": False, "afc_bowden_length": ace.get("sim_bowden") or 1000.0,
                                          "lanes": [lane_name(g) for g in range(k * 4, min(n, k * 4 + 4))]}
    return out


def _params(words: List[str]) -> Dict[str, str]:
    return {k.upper(): v for k, v in (w.split("=", 1) for w in words[1:] if "=" in w)}


def to_ace(skin: str, line: str) -> Tuple[Optional[str], Optional[Tuple[int, Dict[str, Any]]]]:
    """One of the unit's commands as the pretend's own: (ACE command, None), (None, (slot, {color, material, temp}))
    for a spool's details, or (line, None) when it isn't the unit's."""
    words = line.split()
    if not words:
        return line, None
    cmd, p = words[0].upper(), _params(words)
    lane = lambda: int(p["LANE"].replace("lane", "")) - 1
    if skin == "happy_hare":
        if cmd == "MMU_CHANGE_TOOL":
            return f"ACE_CHANGE_TOOL TOOL={p.get('GATE', p.get('TOOL'))}", None
        if cmd == "MMU_UNLOAD":
            return "ACE_CHANGE_TOOL TOOL=-1", None
        if cmd == "MMU_ENDLESS_SPOOL":
            return f"ACE_ENDLESS_SPOOL ENABLE={p.get('ENABLE', '0')}", None
        if cmd == "MMU_RECOVER":
            return f"ACE_SET_GATE GATE={p['GATE'] if p.get('LOADED') == '1' else -1}", None
        if cmd == "MMU_GATE_MAP":
            return None, (int(p["GATE"]), {"color": p.get("COLOR"), "material": p.get("MATERIAL"), "temp": p.get("TEMP")})
    else:
        if cmd == "CHANGE_TOOL":
            return f"ACE_CHANGE_TOOL TOOL={lane()}", None
        if cmd == "TOOL_UNLOAD":
            return "ACE_CHANGE_TOOL TOOL=-1", None
        if cmd == "LANE_MOVE":
            mm = int(float(p["DISTANCE"]))
            return f"{'ACE_FEED' if mm > 0 else 'ACE_RETRACT'} INDEX={lane()} LENGTH={abs(mm)}", None
        if cmd == "SET_LANE_LOADED":
            return f"ACE_SET_GATE GATE={lane()}", None
        if cmd == "UNSET_LANE_LOADED":
            return "ACE_SET_GATE GATE=-1", None
        if cmd == "SET_COLOR":
            return None, (lane(), {"color": p["COLOR"].lstrip("#")})
        if cmd == "SET_MATERIAL":
            return None, (lane(), {"material": p["MATERIAL"]})
    return line, None


# ---- the slot check and measuring (printer/unit_check.py): what the unit says, and how long it takes ----------------

CHECK_COMMANDS = ("MMU_HOME", "MMU_CHECK_GATE", "MMU_SELECT", "MMU_CALIBRATE_BOWDEN", "CALIBRATE_AFC", "RESPOND")


def is_check(skin: Optional[str], script: str) -> bool:
    """A script of the check's, which the pretend answers itself (LANE_MOVE pairs only then: Move sends one)."""
    first = (script.split() or [""])[0].upper()
    return bool(skin) and (first in CHECK_COMMANDS or (first == "LANE_MOVE" and "\n" in script))


def check_answer(skin: str, line: str, states: List[str], failing: Optional[int]) -> Tuple[float, List[str], Dict[str, Any]]:
    """(seconds it takes, console lines, what it measured: {"tube": mm} or {"hub": (slot, mm)}) for one line.
    failing: the slot whose motor test fails (once)."""
    words = line.split()
    if not words:
        return 0, [], {}
    cmd, p = words[0].upper(), _params(words)
    if cmd == "MMU_HOME":
        return 2, ["// Homing MMU...", "// MMU selector homed"], {}
    if cmd == "MMU_CHECK_GATE":
        g = int(p["GATE"])
        if g == failing:
            return 4, [f"!! MMU issue: Failure during check gate {g} :",
                       "Couldn't pick up filament at gate (gate endstop didn't trigger)"], {}
        if g >= len(states) or states[g] == "empty":
            return 4, [f"// Gate {g} marked EMPTY (no filament detected during homing)"], {}
        return 4, [f"// Gate {g} - Filament detected. Marked available"], {}
    if cmd == "MMU_SELECT":
        return 1, [], {}
    if cmd == "MMU_CALIBRATE_BOWDEN":
        mm = SIM_TUBE_MM
        return 30, ["// Calibrating bowden length for gate using mmu_gate as gate reference point and extruder as "
                    "extruder homing point", f"// Filament homed to extruder after {mm:.1f}mm movement",
                    f"// Calibrated bowden length is {mm:.1f}mm"], {"tube": mm}
    if cmd == "LANE_MOVE":
        g = int(p["LANE"].replace("lane", "")) - 1
        if g == failing:
            return 1, [f"!! {p['LANE']} didn't move: no motion from its motor"], {}
        return 1, [], {}
    if cmd == "CALIBRATE_AFC":
        if "LANE" in p:
            g = int(p["LANE"].replace("lane", "")) - 1
            mm = round(58.0 + 1.7 * g, 1)
            return 8, ["// Starting AFC distance Calibrations", f"// Calibrating {p['LANE']}",
                       f"// {p['LANE']} dist_hub: New: {mm} Old: 60.0", "// Lane calibration Done!"], {"hub": (g, mm)}
        return 45, [f"// Calibrating Bowden Length with {p.get('BOWDEN')}",
                    f"// afc_bowden_length: New: {SIM_TUBE_MM} Old: 1000.0", "// Bowden length calibration Done!"], {"tube": SIM_TUBE_MM}
    return 0, [], {}
