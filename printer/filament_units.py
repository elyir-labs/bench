"""Filament units, whatever drives them (design/ace-driver/, A).

The printer code reads one shape here instead of a driver's own status object, and asks the unit's driver
for the commands it takes. A new kind of unit is a new reader and, if Bench may drive it, a new set of
commands. Nothing here talks to Klipper or Moonraker; UnitsLink talks to our own service.

The shape, from read():
    driver     "elyir" (our service, units/service.py, as `elyir_units`), "klipperace" (KlipperACE's `ace`),
               "happy_hare" (Happy Hare's `mmu`, which Rinkhals also reports) or "afc" (Armored Turtle's `AFC`)
    lanes      AFC only: each slot's lane name, which AFC's commands take instead of a number
    selected   the slot feeding the head, or None
    known      how many units the driver knows about
    units      [{index, alias, offset, n, connected, temp, dryer}], dryer being the driver's own report
    slots      [{slot, status, color, material, tagged, remain}], status "ready", "empty" or "unknown"
    feed_assist  one bool per slot, or None when the driver doesn't say
    carry_on   the driver's endless-spool switch, or None when it has none
    lists      the colors, materials and temperatures the driver keeps for untagged spools
    change     our service's tool change, going ({from, to, in_print, step}) or failed ({..., error}); else None
"""
import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional


def hex_color(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return "#%02X%02X%02X" % (int(value[0]), int(value[1]), int(value[2]))
    s = str(value).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return "#" + s.upper()
    if re.fullmatch(r"[0-9a-fA-F]{8}", s):
        return "#" + s[:6].upper()
    return None


def read(status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The printer's filament units in one shape, or None without any."""
    ours = status.get("elyir_units")
    if isinstance(ours, dict) and ours.get("units"):
        return _elyir(ours)
    ace = status.get("ace")
    if isinstance(ace, dict):
        return _klipperace(ace)
    mmu = status.get("mmu")
    if isinstance(mmu, dict):
        return _happy_hare(mmu, status.get("mmu_machine"))
    afc = status.get("AFC")
    if isinstance(afc, dict) and afc.get("lanes"):
        return _afc(afc, status)
    return None


def afc_lane_objects(objects: List[str]) -> List[str]:
    """The Klipper objects AFC reports each lane as: `AFC_stepper <lane>` or `AFC_lane <lane>`."""
    return [o for o in objects if o.startswith(("AFC_stepper ", "AFC_lane "))]


def _at(lst: Any, i: int, default: Any = None) -> Any:
    return lst[i] if isinstance(lst, list) and i < len(lst) else default


def _slot(g: int, raw: Dict[str, Any], top_colors: List[Any], top_mats: List[Any],
          dev_colors: List[Any], dev_mats: List[Any], i: int) -> Dict[str, Any]:
    """One KlipperACE slot. A tag's color and type win over the colors and materials kept for untagged spools."""
    st = str(raw.get("status") or "unknown").lower()
    if st not in ("ready", "empty"):
        st = "unknown"
    tag_color = hex_color(raw.get("color")) if raw.get("color") not in (None, [0, 0, 0], (0, 0, 0)) else None
    tag_type = (raw.get("type") or "").strip() or None
    remain = raw.get("remain") if isinstance(raw.get("remain"), (int, float)) else None
    return {
        "slot": g,
        "status": st,
        "color": tag_color or hex_color(_at(top_colors, g)) or hex_color(_at(dev_colors, i)),
        "material": tag_type or _at(top_mats, g) or _at(dev_mats, i) or None,
        "tagged": bool(raw.get("rfid")) and bool(tag_color or tag_type or raw.get("sku")),
        "remain": remain,
    }


def _elyir(st: Dict[str, Any]) -> Dict[str, Any]:
    """Our service already speaks this shape; only what it can't know is filled in."""
    slots = st.get("slots") or []
    return {
        "driver": "elyir",
        "selected": st.get("selected") if isinstance(st.get("selected"), int) and st["selected"] >= 0 else None,
        "known": len(st["units"]),
        "units": [{k: u.get(k) for k in ("index", "alias", "offset", "n", "connected", "temp", "dryer")} for u in st["units"]],
        "slots": [{"slot": s["slot"], "status": s.get("status") or "unknown", "color": hex_color(s.get("color")),
                   "material": s.get("material"), "tagged": bool(s.get("tagged")), "remain": s.get("remain")} for s in slots],
        "feed_assist": [bool(a) for a in st["feed_assist"]] if isinstance(st.get("feed_assist"), list) else None,
        "carry_on": bool(st["carry_on"]) if "carry_on" in st else None,
        "lists": {"color": [], "material": [], "temp": []},
        "dryer_max": st.get("dryer_max"),
        "change": st.get("change") if isinstance(st.get("change"), dict) else None,
    }


def _klipperace(ace: Dict[str, Any]) -> Dict[str, Any]:
    selected = None
    for key in ("selected_gate", "current_index"):
        v = ace.get(key)
        if isinstance(v, int) and v >= 0:
            selected = v
            break

    if isinstance(ace.get("devices"), list):
        known = len(ace["devices"])
    elif isinstance(ace.get("num_devices"), int):
        known = ace["num_devices"]
    else:
        known = (len(ace.get("gate_color") or []) + 3) // 4

    top_colors = ace.get("gate_color") or []
    top_mats = ace.get("gate_material") or []
    devices = ace.get("devices") if isinstance(ace.get("devices"), list) else None
    units: List[Dict[str, Any]] = []
    slots: List[Dict[str, Any]] = []
    if devices:
        for i, dev in enumerate(devices):
            if not isinstance(dev, dict):
                continue
            st = dev.get("status") if isinstance(dev.get("status"), dict) else {}
            offset = int(dev.get("gate_offset", i * 4) or 0)
            raw_slots = st.get("slots") or dev.get("slots") or []
            statuses = st.get("active_gate") or []
            units.append({"index": i, "alias": dev.get("alias") or None, "offset": offset,
                          "n": len(st.get("slots") or []) or len(dev.get("gates") or []) or 4,
                          "connected": dev.get("connected", True) is not False,
                          "temp": st.get("temp", (dev.get("health") or {}).get("temperature")),
                          "dryer": st.get("dryer_status") or dev.get("dryer_status")})
            slot_offset = int(dev.get("gate_offset", 0) or 0)
            for k in range(max(len(raw_slots), len(dev.get("gates", []) or []), len(statuses))):
                raw = dict(raw_slots[k]) if k < len(raw_slots) and isinstance(raw_slots[k], dict) else {}
                if "status" not in raw and k < len(statuses):
                    raw["status"] = statuses[k]
                slots.append(_slot(slot_offset + k, raw, top_colors, top_mats,
                                   st.get("gate_color") or dev.get("gate_color") or [],
                                   st.get("gate_material") or dev.get("gate_material") or [], k))
    else:
        raw_slots = ace.get("slots") or []
        units.append({"index": 0, "alias": None, "offset": 0,
                      "n": max(len(top_colors), len(raw_slots)), "connected": True,
                      "temp": ace.get("temp"), "dryer": ace.get("dryer_status")})
        statuses = ace.get("active_gate") if isinstance(ace.get("active_gate"), list) else []
        for k in range(max(len(top_colors), len(raw_slots), len(statuses))):
            raw = dict(raw_slots[k]) if k < len(raw_slots) and isinstance(raw_slots[k], dict) else {}
            if "status" not in raw and k < len(statuses):
                raw["status"] = statuses[k]
            slots.append(_slot(k, raw, top_colors, top_mats, [], [], k))

    assist = ace.get("gate_feed_assist")
    return {
        "driver": "klipperace",
        "selected": selected,
        "known": known,
        "units": units,
        "slots": slots,
        "feed_assist": [bool(a) for a in assist] if isinstance(assist, list) else None,
        "carry_on": bool(ace.get("endless_spool")) if "endless_spool" in ace else None,
        "lists": {"color": list(top_colors), "material": list(top_mats), "temp": list(ace.get("gate_temp") or [])},
    }


def _happy_hare(mmu: Dict[str, Any], machine: Any) -> Optional[Dict[str, Any]]:
    """Happy Hare's `mmu` and `mmu_machine`, as Rinkhals reports a Kobra's ACE Pro. None when there's no unit:
    Rinkhals reports an `mmu` with no gates on a Kobra without one."""
    if mmu.get("enabled") is False or not int(mmu.get("num_gates") or 0):
        return None
    n = int(mmu["num_gates"])
    state = [_at(mmu.get("gate_status"), i, -1) for i in range(n)]      # -1 unknown, 0 empty, 1 and 2 loaded
    loaded = [st in (1, 2) for st in state]
    raw_units = [machine.get(f"unit_{k}") for k in range(int(machine.get("num_units") or 1))] if isinstance(machine, dict) else []
    raw_units = [u for u in raw_units if isinstance(u, dict)] or [{"name": "ACE", "first_gate": 0, "num_gates": n}]
    units = []
    for k, u in enumerate(raw_units):
        first, count = int(u.get("first_gate") or 0), int(u.get("num_gates") or 4)
        left = int(u.get("dryer_remaining") or 0)
        units.append({"index": k, "alias": u.get("display_name") or None, "offset": first, "n": max(0, min(count, n - first)),
                      "connected": True,
                      "temp": u.get("dryer_temp"),
                      "dryer": {"status": u.get("dryer_status") or "stop", "remain_time": left,
                                "target_temp": u.get("dryer_target_temp") or 0, "duration": max(left, 1)}})
    slots = []
    for g in range(n):
        material = str(_at(mmu.get("gate_material"), g) or "")
        slots.append({"slot": g,
                      "status": "ready" if loaded[g] else "empty" if state[g] == 0 else "unknown",
                      "color": hex_color(str(_at(mmu.get("gate_color"), g) or "")[:6]) if loaded[g] else None,
                      "material": material if loaded[g] and material.lower() not in ("", "unknown") else None,
                      "tagged": False, "remain": None})
    gate = mmu.get("gate")
    if mmu.get("filament") == "Unloaded":
        gate = None   # Happy Hare keeps the selector's gate with nothing in the head
    carry = mmu.get("endless_spool_enabled", mmu.get("endless_spool"))
    return {
        "driver": "happy_hare",
        "selected": gate if isinstance(gate, int) and gate >= 0 else None,
        "known": len(units),
        "units": units,
        "slots": slots,
        "feed_assist": None,
        "carry_on": bool(carry) if carry is not None else None,
        "lists": {"color": [str(_at(mmu.get("gate_color"), g) or "") for g in range(n)],
                  "material": [str(_at(mmu.get("gate_material"), g) or "") for g in range(n)],
                  "temp": [_at(mmu.get("gate_temperature"), g, 0) for g in range(n)]},
    }


def _afc(afc: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
    """AFC's `AFC` and one object per lane. Lanes are grouped by unit so each unit's slots are in a row; a lane's
    load sensor says filament is there, its prep sensor alone that a spool went in but AFC hasn't taken it yet."""
    lanes: List[tuple] = []
    for name in afc["lanes"]:
        raw = status.get(f"AFC_stepper {name}") or status.get(f"AFC_lane {name}") or {}
        lanes.append((str(name), raw if isinstance(raw, dict) else {}))
    order: List[str] = []
    for _, raw in lanes:
        unit = str(raw.get("unit") or "")
        if unit not in order:
            order.append(unit)
    lanes.sort(key=lambda lane: order.index(str(lane[1].get("unit") or "")))
    units, slots = [], []
    for k, unit in enumerate(order):
        mine = [g for g, (_, raw) in enumerate(lanes) if str(raw.get("unit") or "") == unit]
        units.append({"index": k, "alias": unit.replace("_", " ") or None, "offset": mine[0], "n": len(mine),
                      "connected": True, "temp": None, "dryer": None})
    for g, (_, raw) in enumerate(lanes):
        here = raw.get("load") is True or raw.get("tool_loaded") is True
        st = "ready" if here else "unknown" if raw.get("prep") is True or not raw else "empty"
        material = str(raw.get("material") or "")
        slots.append({"slot": g, "status": st, "color": hex_color(raw.get("color")) if here else None,
                      "material": material if here and material else None, "tagged": False, "remain": None})
    names = [name for name, _ in lanes]
    current = afc.get("current_load")
    return {
        "driver": "afc",
        "selected": names.index(current) if current in names else None,
        "known": len(units),
        "units": units,
        "slots": slots,
        "feed_assist": None,
        "carry_on": None,
        "lists": {"color": [str(raw.get("color") or "") for _, raw in lanes],
                  "material": [str(raw.get("material") or "") for _, raw in lanes],
                  "temp": [raw.get("extruder_temp") or 0 for _, raw in lanes]},
        "lanes": names,
    }


class KlipperAce:
    """The G-code KlipperACE takes. kind is the step a quick command is sent as, long_kind one that takes a while."""
    name = "klipperace"
    kind, long_kind = "gcode", "macro"
    check_slot = measure_slot = measure_tube = None   # the slot check (unit_check.py) is for Happy Hare and AFC

    @staticmethod
    def move(slot: int, mm: int) -> str:
        return f"{'ACE_FEED' if mm > 0 else 'ACE_RETRACT'} INDEX={slot} LENGTH={abs(mm)}"

    @staticmethod
    def dry(unit: Dict[str, Any], temp: int, minutes: int) -> str:
        return f"ACE_START_DRYING GATE={unit['offset']} TEMP={temp} DURATION={minutes}"

    @staticmethod
    def stop_drying(unit: Dict[str, Any]) -> str:
        return f"ACE_STOP_DRYING GATE={unit['offset']}"

    @staticmethod
    def feed_assist(slot: int, on: bool) -> str:
        return f"ACE_{'ENABLE' if on else 'DISABLE'}_FEED_ASSIST INDEX={slot}"

    @staticmethod
    def carry_on(on: bool) -> str:
        return f"ACE_ENDLESS_SPOOL ENABLE={1 if on else 0}"

    @staticmethod
    def change_tool(slot: int, purge: bool = True) -> str:
        """Load a slot into the head; -1 unloads."""
        cmd = f"ACE_CHANGE_TOOL TOOL={slot}"
        if slot >= 0 and not purge:
            cmd += " PURGE=0"
        return cmd

    @staticmethod
    def mark_loaded(slot: int) -> str:
        return f"ACE_SET_GATE GATE={slot}"

    @staticmethod
    def set_spool(lists: Dict[str, List[Any]], n: int, slot: int, color: str, material: str,
                  temps: Dict[str, int], same_material: Any) -> List[str]:
        """Color and material for an untagged spool. They live in Klipper's saved variables, which KlipperACE
        re-reads on every status update; the print temperature follows a changed material."""
        colors = [str(c).lstrip("#").upper() for c in lists["color"]] + ["FFFFFF"] * n
        mats = [str(m or "") for m in lists["material"]] + [""] * n
        heat = list(lists["temp"]) + [230] * n
        colors, mats, heat = colors[:n], mats[:n], heat[:n]
        changed = not same_material(mats[slot], material)
        colors[slot] = color.lstrip("#")
        mats[slot] = material
        if changed and material in temps:
            heat[slot] = temps[material]

        def value(lst: List[Any]) -> str:
            # Klipper splits command parameters like a shell (shlex), which strips quotes, then runs
            # literal_eval on VALUE. Wrapping in single quotes keeps the inner double quotes; a value that
            # fails to parse there shuts Klipper down, so it must always parse.
            text = json.dumps(lst, separators=(",", ":"))
            if "'" in text or ";" in text or "#" in text:
                raise ValueError("unsafe value for SAVE_VARIABLE")
            return "'" + text + "'"

        out = [f"SAVE_VARIABLE VARIABLE=ace_gate_color VALUE={value(colors)}",
               f"SAVE_VARIABLE VARIABLE=ace_gate_type VALUE={value(mats)}"]
        if changed:
            out.append(f"SAVE_VARIABLE VARIABLE=ace_gate_temp VALUE={value([int(t) for t in heat])}")
        return out


class Elyir:
    """What our service takes (units/service.py), sent as "unit" steps: {"op", ...}."""
    name = "elyir"
    kind, long_kind = "unit", "unit_macro"
    check_slot = measure_slot = measure_tube = None

    @staticmethod
    def change_tool(slot: int, purge: bool = True) -> Dict[str, Any]:
        """Load a slot into the head; -1 unloads. The service runs the whole change (the quiet pause)."""
        return {"op": "change_tool", "slot": slot, "purge": purge}

    @staticmethod
    def move(slot: int, mm: int) -> Dict[str, Any]:
        return {"op": "move", "slot": slot, "mm": mm}

    @staticmethod
    def dry(unit: Dict[str, Any], temp: int, minutes: int) -> Dict[str, Any]:
        return {"op": "dry", "unit": unit["index"], "temp": temp, "minutes": minutes}

    @staticmethod
    def stop_drying(unit: Dict[str, Any]) -> Dict[str, Any]:
        return {"op": "stop_drying", "unit": unit["index"]}

    @staticmethod
    def feed_assist(slot: int, on: bool) -> Dict[str, Any]:
        return {"op": "feed_assist", "slot": slot, "on": on}

    @staticmethod
    def carry_on(on: bool) -> Dict[str, Any]:
        return {"op": "carry_on", "on": on}

    @staticmethod
    def mark_loaded(slot: int) -> Dict[str, Any]:
        return {"op": "mark_loaded", "slot": slot}

    @staticmethod
    def purge(mm: int, temp: int) -> Dict[str, Any]:
        """Push more through, at the printer's purge spot."""
        return {"op": "purge", "mm": mm, "temp": temp}

    @staticmethod
    def set_spool(lists: Dict[str, List[Any]], n: int, slot: int, color: str, material: str,
                  temps: Dict[str, int], same_material: Any) -> List[Dict[str, Any]]:
        return [{"op": "set_spool", "slot": slot, "color": color, "material": material}]


class HappyHare:
    """The G-code Happy Hare (v3 and v4) takes. It runs the whole tool change itself, prints use its T0..Tn, and a
    command a unit can't take is None so nothing offers it: no moves (its own selector and gear do that) and no
    drying, which only some units have."""
    name = "happy_hare"
    kind, long_kind = "gcode", "macro"
    move = dry = stop_drying = feed_assist = None

    @staticmethod
    def change_tool(slot: int, purge: bool = True) -> str:
        """Load a slot into the head; -1 unloads. STANDALONE: asked for from a screen, not by a slicer's file."""
        if slot < 0:
            return "MMU_UNLOAD"
        return f"MMU_CHANGE_TOOL GATE={slot} STANDALONE=1" + ("" if purge else " SKIP_PURGE=1")

    @staticmethod
    def mark_loaded(slot: int) -> str:
        return "MMU_RECOVER LOADED=0" if slot < 0 else f"MMU_RECOVER GATE={slot} LOADED=1"

    @staticmethod
    def carry_on(on: bool) -> str:
        return f"MMU_ENDLESS_SPOOL ENABLE={1 if on else 0}"

    @staticmethod
    def set_spool(lists: Dict[str, List[Any]], n: int, slot: int, color: str, material: str,
                  temps: Dict[str, int], same_material: Any) -> List[str]:
        """MMU_GATE_MAP sets the temperature back to Happy Hare's default when TEMP is left out, so it's always sent:
        the material's when the material changed, else what the gate had."""
        was = _at(lists["material"], slot, "")
        temp = _at(lists["temp"], slot, 0)
        if (not same_material(was, material) and material in temps) or not temp:
            temp = temps.get(material, 220)
        return [f"MMU_GATE_MAP GATE={slot} COLOR={color.lstrip('#').lower()} MATERIAL={material} TEMP={int(temp)}"]

    # The slot check and measuring (unit_check.py). Happy Hare 3 checks a gate only once the selector is homed;
    # 4 homes it itself, so MMU_HOME goes first only when the status says it isn't.
    measure_slot = None   # MMU_CALIBRATE_GATE measures each gate's gear against an encoder: not built

    @staticmethod
    def check_slot(slot: int, home: bool = False) -> str:
        """Loads to the gate's endstop and parks: the gear motor turns and the gate sensor (or encoder) must see it."""
        return ("MMU_HOME\n" if home else "") + f"MMU_CHECK_GATE GATE={slot} QUIET=1"

    @staticmethod
    def measure_tube(slot: int, home: bool = False) -> str:
        """MMU_CALIBRATE_BOWDEN takes no gate: it measures with the one selected."""
        return ("MMU_HOME\n" if home else "") + f"MMU_SELECT GATE={slot}\nMMU_CALIBRATE_BOWDEN"

    @staticmethod
    def needs_home(status: Dict[str, Any]) -> bool:
        return (status.get("mmu") or {}).get("is_homed") is False

    @staticmethod
    def sees(status: Dict[str, Any], slot: int) -> Optional[bool]:
        """The gate's own sensor (v4 mmu_entry_N, v3 mmu_pre_gate_N), or None on a unit without one."""
        for name in (f"mmu_entry_{slot}", f"mmu_pre_gate_{slot}"):
            st = status.get(f"filament_switch_sensor {name}")
            if isinstance(st, dict) and "filament_detected" in st:
                return bool(st["filament_detected"])
        return None

    @staticmethod
    def believes(status: Dict[str, Any], slot: int) -> bool:
        """Happy Hare marked the gate available (gate_status 1, or 2 from a buffer)."""
        return _at((status.get("mmu") or {}).get("gate_status"), slot, -1) in (1, 2)

    @staticmethod
    def version(status: Dict[str, Any]) -> Optional[str]:
        """Happy Hare 4 says its version in mmu_machine; 3 doesn't say."""
        v = (status.get("mmu_machine") or {}).get("happy_hare_version")
        if v is None:
            return None
        parts = str(v).split(".")
        return "Happy Hare " + ".".join(parts[:2])


class Afc:
    """The G-code Armored Turtle's AFC takes (Box Turtle, Night Owl and others). Its commands name a lane, not a
    number. AFC has no dryers and no single carry-on switch (each lane names its own runout lane)."""
    name = "afc"
    kind, long_kind = "gcode", "macro"
    dry = stop_drying = feed_assist = carry_on = None

    def __init__(self, lanes: List[str]) -> None:
        self.lanes = lanes

    def change_tool(self, slot: int, purge: bool = True) -> str:
        """Load a slot into the head; -1 unloads. AFC purges by its own settings, so purge isn't passed on."""
        return "TOOL_UNLOAD" if slot < 0 else f"CHANGE_TOOL LANE={self.lanes[slot]}"

    def move(self, slot: int, mm: int) -> str:
        return f"LANE_MOVE LANE={self.lanes[slot]} DISTANCE={mm}"

    def mark_loaded(self, slot: int) -> str:
        return "UNSET_LANE_LOADED" if slot < 0 else f"SET_LANE_LOADED LANE={self.lanes[slot]}"

    def set_spool(self, lists: Dict[str, List[Any]], n: int, slot: int, color: str, material: str,
                  temps: Dict[str, int], same_material: Any) -> List[str]:
        lane = self.lanes[slot]
        return [f"SET_COLOR LANE={lane} COLOR={color.lstrip('#')}", f"SET_MATERIAL LANE={lane} MATERIAL={material}"]

    # The slot check and measuring (unit_check.py). CALIBRATE_AFC ends by opening AFC's own dialog in Mainsail
    # ("Would you like to do more calibrations?"), which Bench's screens don't show: it's closed again at once.
    PROMPT_END = "RESPOND TYPE=command MSG=action:prompt_end"

    def check_slot(self, slot: int, home: bool = False) -> str:
        """Back 10 mm and forward again: the lane's motor turns and its load sensor must still see the filament."""
        lane = self.lanes[slot]
        return f"LANE_MOVE LANE={lane} DISTANCE=-10\nLANE_MOVE LANE={lane} DISTANCE=10"

    def measure_slot(self, slot: int) -> str:
        """The lane's load sensor to its hub (dist_hub)."""
        return f"CALIBRATE_AFC LANE={self.lanes[slot]}\n{self.PROMPT_END}"

    def measure_tube(self, slot: int, home: bool = False) -> str:
        """The hub to the sensor where the head starts (the hub's afc_bowden_length), with this lane's filament."""
        return f"CALIBRATE_AFC BOWDEN={self.lanes[slot]}\n{self.PROMPT_END}"

    @staticmethod
    def needs_home(status: Dict[str, Any]) -> bool:
        return False

    def lane(self, status: Dict[str, Any], slot: int) -> Dict[str, Any]:
        name = self.lanes[slot]
        raw = status.get(f"AFC_stepper {name}") or status.get(f"AFC_lane {name}") or {}
        return raw if isinstance(raw, dict) else {}

    def sees(self, status: Dict[str, Any], slot: int) -> Optional[bool]:
        """The lane's load sensor; prep alone means AFC hasn't pulled it in yet."""
        raw = self.lane(status, slot)
        return bool(raw.get("load")) if "load" in raw else None

    def believes(self, status: Dict[str, Any], slot: int) -> bool:
        return self.sees(status, slot) is True

    @staticmethod
    def version(status: Dict[str, Any]) -> Optional[str]:
        return None   # AFC keeps its version out of the status


DRIVERS = {"klipperace": KlipperAce(), "elyir": Elyir(), "happy_hare": HappyHare()}


def commands(units: Optional[Dict[str, Any]], watch_only: bool = False) -> Optional[Any]:
    """What Bench may tell this unit to do, or None when it can only watch: a Kobra's unit through Rinkhals reports
    Happy Hare's shape but takes none of its commands."""
    if not units or watch_only:
        return None
    if units["driver"] == "afc":
        return Afc(units.get("lanes") or [])
    return DRIVERS.get(units["driver"])


def can(cmds: Optional[Any], what: str) -> bool:
    """Whether the unit's driver takes this command (move, dry, feed_assist...)."""
    return cmds is not None and getattr(cmds, what, None) is not None


def check_objects(objects: List[str]) -> List[str]:
    """Klipper objects the slot check reads besides the unit's own: Happy Hare's gate sensors and AFC's hubs."""
    return [o for o in objects
            if re.fullmatch(r"filament_switch_sensor mmu_(entry|pre_gate)_\d+", o) or o.startswith("AFC_hub ")]


def can_change_tool(cmds: Optional[Any]) -> bool:
    return cmds is not None and getattr(cmds, "change_tool", None) is not None


class UnitsLink:
    """The filament-unit service's socket (units/service.py, JSON lines): its state pushed in, commands out.
    The component looks for the socket every few seconds and runs this while it's there, so the service can
    start after Moonraker, restart, or not run at all."""

    def __init__(self, path: str, on_state) -> None:
        self.path, self.on_state = path, on_state
        self.writer: Optional[asyncio.StreamWriter] = None
        self.pending: Dict[int, asyncio.Future] = {}
        self.rid = 0
        self.running = False

    def due(self) -> bool:
        return not self.running and os.path.exists(self.path)

    async def run(self) -> None:
        self.running = True
        try:
            reader, self.writer = await asyncio.open_unix_connection(self.path)
            self.writer.write(b'{"id": 0, "method": "subscribe"}\n')    # id 0 is never a call's
            while True:
                line = await reader.readline()
                if not line:
                    break
                m = json.loads(line)
                if m.get("method") == "state":
                    self.on_state(m.get("params"))
                elif m.get("id") == 0:
                    self.on_state(m.get("result"))
                else:
                    fut = self.pending.pop(m.get("id"), None)
                    if fut and not fut.done():
                        fut.set_result(m)
        except (OSError, ValueError) as e:
            logging.info("intent: the filament-unit service went away: %s", e)
        finally:
            if self.writer:
                self.writer.close()
            self.writer = None
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("the filament-unit service went away"))
            self.pending.clear()
            self.running = False
            self.on_state(None)

    async def call(self, payload: Dict[str, Any], timeout: float = 150.0) -> Any:
        """Run {"op", ...} on the service; its result, or an error saying what went wrong."""
        if self.writer is None:
            raise ConnectionError("The filament-unit service isn't running.")
        self.rid += 1
        params = {k: v for k, v in payload.items() if k != "op"}
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.rid] = fut
        self.writer.write((json.dumps({"id": self.rid, "method": payload["op"], "params": params}) + "\n").encode())
        await self.writer.drain()
        m = await asyncio.wait_for(fut, timeout)
        if "error" in m:
            raise RuntimeError(m["error"].get("message") or "The filament unit refused.")
        return m.get("result")
