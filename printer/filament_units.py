"""Filament units, whatever drives them (design/ace-driver/, A).

The printer code reads one shape here instead of a driver's own status object, and asks the unit's driver
for the commands it takes. A new kind of unit is a new reader and, if Bench may drive it, a new set of
commands. Nothing here talks to Klipper or Moonraker; UnitsLink talks to our own service.

The shape, from read():
    driver     "elyir" (our service, units/service.py, as `elyir_units`), "klipperace" (KlipperACE's `ace`) or
               "happy_hare" (Happy Hare's `mmu`, which Rinkhals also reports)
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
    return None


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
        units.append({"index": k, "alias": None, "offset": first, "n": max(0, min(count, n - first)), "connected": True,
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
    return {
        "driver": "happy_hare",
        "selected": gate if isinstance(gate, int) and gate >= 0 else None,
        "known": len(units),
        "units": units,
        "slots": slots,
        "feed_assist": None,
        "carry_on": None,
        "lists": {"color": [], "material": [], "temp": [_at(mmu.get("gate_temperature"), g, 0) for g in range(n)]},
    }


class KlipperAce:
    """The G-code KlipperACE takes. kind is the step a quick command is sent as, long_kind one that takes a while."""
    name = "klipperace"
    kind, long_kind = "gcode", "macro"

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


DRIVERS = {"klipperace": KlipperAce(), "elyir": Elyir()}


def commands(units: Optional[Dict[str, Any]]) -> Optional[Any]:
    """What Bench may tell this unit to do, or None when it can only watch (a Kobra's unit through Rinkhals)."""
    return DRIVERS.get(units["driver"]) if units else None


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
