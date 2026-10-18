"""
Elyir Bench care: maintenance that the printer counts for itself.

Tasks live in Moonraker's `maintenance` database namespace in Mainsail's own
format, so reminders made or ticked off behind the Advanced door (Mainsail)
and on the Care tab are the same records. Usage comes from Moonraker's history
totals (print seconds, filament mm). Like elyir_bench_intent.py, this module has
no Moonraker imports and is tested on its own.

A Mainsail maintenance entry (the fields we use):
    name, note, start_time, end_time, start_filament, end_filament,
    start_printtime, end_printtime, last_entry, perform_note,
    reminder: {type: null|'one-time'|'repeat',
               printtime: {bool, value: hours},
               filament:  {bool, value: metres},
               date:      {bool, value: days}}
An entry with end_time set has been done; a repeating one is followed by a
fresh entry (last_entry pointing back) that counts from that moment.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

# The starting set, made once per printer. Intervals are in print hours; edit
# them in Mainsail (Advanced > History > Maintenance) and Care follows.
DEFAULT_TASKS = [
    {"name": "Wipe the bed", "hours": 40,
     "note": "Wipe the build plate with isopropyl alcohol so prints keep sticking."},
    {"name": "Clean the nozzle", "hours": 150,
     "note": "While it's hot, brush off any plastic stuck to the outside of the nozzle."},
    {"name": "Check the belts", "hours": 300,
     "note": "Both belts should feel equally firm. A loose belt shows up as wavy walls."},
    {"name": "Lubricate the rails", "hours": 500,
     "note": "A drop of light oil on each rail, then move the head end to end."},
]

LATER_PRINT_HOURS = 5    # "Later" waits this much more printing...
LATER_DAYS = 3           # ...or this many days, whichever comes first

INIT_MARKER = "MAINTENANCE_INIT"   # Mainsail's placeholder record, not a task


def _totals(totals: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    t = totals or {}
    return float(t.get("total_print_time") or 0.0), float(t.get("total_filament_used") or 0.0)


def new_entry(name: str, note: str, reminder: Dict[str, Any], totals: Dict[str, Any], now: float,
              last_entry: Optional[str] = None) -> Dict[str, Any]:
    printtime, filament = _totals(totals)
    return {
        "name": name, "note": note,
        "start_time": now, "end_time": None,
        "start_filament": filament, "end_filament": None,
        "start_printtime": printtime, "end_printtime": None,
        "last_entry": last_entry, "perform_note": None,
        "reminder": reminder,
    }


def default_entries(totals: Dict[str, Any], now: float) -> Dict[str, Dict[str, Any]]:
    """The starting set, counting from now (not the printer's lifetime, so nothing is
    overdue on day one). Keys are new ids, as Mainsail makes them."""
    out = {}
    for t in DEFAULT_TASKS:
        reminder = {"type": "repeat",
                    "printtime": {"bool": True, "value": t["hours"]},
                    "filament": {"bool": False, "value": None},
                    "date": {"bool": False, "value": None}}
        out[str(uuid.uuid4())] = new_entry(t["name"], t["note"], reminder, totals, now)
    return out


def _measures(entry: Dict[str, Any], printtime: float, filament: float, now: float) -> List[Dict[str, Any]]:
    """How far along each enabled reminder is, as fractions of its interval."""
    r = entry.get("reminder") or {}
    out = []
    pt = r.get("printtime") or {}
    if pt.get("bool") and pt.get("value"):
        used = (printtime - float(entry.get("start_printtime") or 0)) / 3600
        out.append({"unit": "print hours", "used": used, "every": float(pt["value"])})
    fi = r.get("filament") or {}
    if fi.get("bool") and fi.get("value"):
        used = (filament - float(entry.get("start_filament") or 0)) / 1000
        out.append({"unit": "m of filament", "used": used, "every": float(fi["value"])})
    da = r.get("date") or {}
    if da.get("bool") and da.get("value"):
        used = (now - float(entry.get("start_time") or now)) / 86400
        out.append({"unit": "days", "used": used, "every": float(da["value"])})
    return out


def _snoozed(snooze: Optional[Dict[str, Any]], printtime: float, now: float) -> bool:
    if not snooze:
        return False
    return printtime < float(snooze.get("printtime", 0)) and now < float(snooze.get("until", 0))


def summary(entries: Optional[Dict[str, Dict[str, Any]]], totals: Optional[Dict[str, Any]], now: float,
            snoozes: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What Care shows and what the Ready screen and the phone hear about.

    {items: [{id, name, note, due, snoozed, progress, label}], due: n, hint}
    Due items first, then the closest to due. progress is 0..1 of the nearest
    reminder; label reads like "112 of 150 print hours".
    """
    printtime, filament = _totals(totals)
    items = []
    for eid, e in (entries or {}).items():
        if not isinstance(e, dict) or e.get("name") == INIT_MARKER or e.get("end_time") is not None:
            continue
        if not (e.get("reminder") or {}).get("type"):
            continue   # a logged job with no reminder: history, not a task
        ms = _measures(e, printtime, filament, now)
        if not ms:
            continue
        m = max(ms, key=lambda x: x["used"] / x["every"])
        frac = max(0.0, m["used"] / m["every"])
        snoozed = frac >= 1 and _snoozed((snoozes or {}).get(eid), printtime, now)
        used = max(0, int(m["used"]))
        items.append({
            "id": eid,
            "name": e.get("name") or "Maintenance",
            "note": e.get("note") or "",
            "due": frac >= 1 and not snoozed,
            "snoozed": snoozed,
            "progress": round(min(frac, 1.0), 3),
            "label": f"{used:g} of {m['every']:g} {m['unit']}",
        })
    items.sort(key=lambda i: (not i["due"], -i["progress"]))
    due = [i for i in items if i["due"]]
    hint = None
    if due:
        hint = f"Time to {due[0]['name'][0].lower()}{due[0]['name'][1:]}."
        if len(due) > 1:
            hint += f" {len(due) - 1} more in Care."
    return {"items": items, "due": len(due), "hint": hint}


def perform(entries: Dict[str, Dict[str, Any]], eid: str, totals: Dict[str, Any], now: float) -> Dict[str, Dict[str, Any]]:
    """Mark a task done, exactly as Mainsail's "perform" does: close this entry and,
    for a repeating reminder, start a fresh one counting from now. Returns the
    records to write ({id: entry}); empty if the task isn't open."""
    e = (entries or {}).get(eid)
    if not e or e.get("end_time") is not None:
        return {}
    printtime, filament = _totals(totals)
    done = dict(e, end_time=now, end_filament=filament, end_printtime=printtime)
    done.pop("id", None)
    out = {eid: done}
    if (e.get("reminder") or {}).get("type") == "repeat":
        out[str(uuid.uuid4())] = new_entry(e.get("name", ""), e.get("note", ""), dict(e["reminder"]),
                                           totals, now, last_entry=eid)
    return out


def later(eid: str, totals: Dict[str, Any], now: float) -> Dict[str, Any]:
    """The snooze record for "Later": quiet until a few more print hours or days."""
    printtime, _ = _totals(totals)
    return {"printtime": printtime + LATER_PRINT_HOURS * 3600, "until": now + LATER_DAYS * 86400}
