"""Spool tags (design/spool-tags/, round 1 C + round 2 A/A/A): hold a tag on the reader and Bench asks.

A blank tag asks which spool it's for (the slots' untagged spools, ones written before, the library), then writes
the format that fits the tag in hand and the printers here (pick 5 A: the tag picks, Change offers the rest). A
written tag reads back, any format, and can be copied onto a blank one. The reader only moves bytes; it reports
tags with on_tag() and runs the writes work() hands out, then reports with on_written().
"""
import importlib.util
import os
import time
from typing import Any, Callable, Dict, List, Optional


def _sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"{name}.py not found next to {__file__}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


formats = _sibling("tag_formats")
library = _sibling("filament_library")

HISTORY_KEPT = 8
GONE_CLOSES_AFTER = 1.5     # a read or written tag lifted off closes its sheet after this long
WRITE_TIMEOUT = 15.0

READERS = {
    "anycubic": "every ACE here reads it",
    "tigertag": "an open format many apps and printers read",
    "openspool": "OpenSpool readers and phones read it",
    "cfs": "Creality's CFS reads it",
    "openprinttag": "Prusa printers and our filament unit read it",
}
READERS_NO_ACE = dict(READERS, anycubic="Anycubic's ACE reads it")


def spool_label(s: Dict[str, Any]) -> str:
    """'Polymaker PolyLite PETG Orange', or 'Orange PETG' for a slot's spool told by color and material."""
    brand, name, material = (s.get("brand") or "").strip(), (s.get("name") or "").strip(), (s.get("material") or "").strip()
    if brand and name:
        text = name if name.lower().startswith(brand.lower()) else f"{brand} {name}"
        return text if material.lower() in text.lower() else f"{text} {material}".strip()
    return " ".join(x for x in (name or brand, material) if x) or "A spool"


def facts(s: Dict[str, Any]) -> List[str]:
    c = formats.complete(s)
    out = [c["material"], f"{c['weight'] / 1000:g} kg" if c["weight"] >= 1000 else f"{c['weight']} g",
           f"{c['diameter']:g} mm", f"{c['nozzle'][0]}–{c['nozzle'][1]} °C", f"bed {c['bed'][0]}–{c['bed'][1]} °C"]
    if s.get("left") and s["left"] < c["weight"] - 5:
        out.insert(2, f"{s['left']} g left")
    return out


class SpoolTags:
    def __init__(self, spools: Callable[[], List[Dict[str, Any]]], has_ace: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._spools, self._has_ace, self._clock = spools, has_ace, clock
        self.reader: Optional[Dict[str, Any]] = None   # {"name", "state": ready | missing | error, "why"}
        self.tag: Optional[Any] = None                  # formats.Tag on the reader now
        self.found: Optional[tuple] = None              # (format id, spool) the tag holds
        self.sheet: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]] = []         # spools written here, newest first
        self.choice_by_chip: Dict[str, str] = {}        # format picked under Change, per kind of tag
        self.dirty = False                              # history or choices changed: the component saves them
        self._quiet_uid: Optional[bytes] = None         # "Not now": that tag is left alone until it's lifted
        self._gone_at: Optional[float] = None
        self._pending: Optional[Dict[str, Any]] = None  # writes handed out, waiting for on_written

    # ---- what the component keeps ----------------------------------------------------------------

    def saved(self) -> Dict[str, Any]:
        return {"history": self.history, "choice_by_chip": self.choice_by_chip}

    def restore(self, kept: Optional[Dict[str, Any]]) -> None:
        kept = kept or {}
        self.history = [h for h in (kept.get("history") or []) if isinstance(h, dict)][:HISTORY_KEPT]
        self.choice_by_chip = {k: v for k, v in (kept.get("choice_by_chip") or {}).items() if v in formats.BY_ID}

    # ---- from the reader -------------------------------------------------------------------------

    def on_reader(self, name: Optional[str], state: str, why: Optional[str] = None) -> None:
        self.reader = {"name": name, "state": state, "why": why} if name or state != "missing" else None

    def on_tag(self, tag: Optional[Any]) -> None:
        now = self._clock()
        if tag is None:
            if self.tag is not None:
                self.tag, self.found = None, None
                self._quiet_uid = None
                self._gone_at = now
            return
        same = self.tag is not None and self.tag.uid == tag.uid
        self.tag, self._gone_at = tag, None
        self.found = formats.read(tag)
        if same or tag.uid == self._quiet_uid or (self._pending and self._pending.get("uid") == tag.uid):
            return
        if self.sheet and self.sheet["step"] in ("which", "library", "write", "formats") and self.sheet.get("waiting"):
            self.sheet["waiting"] = False   # the tag came back to finish what was started
            return
        if self.sheet and self.sheet["step"] == "copy":
            if tag.blank() or self.found is None:
                self._to_write(self.sheet["spool"])
            return
        if self.found:
            fmt, spool = self.found
            self.sheet = {"step": "read", "format": fmt, "spool": spool}
        elif tag.blank():
            self.sheet = {"step": "which"}
        else:
            self.sheet = {"step": "unknown"}

    def on_written(self, ok: bool, why: Optional[str] = None, tag: Optional[Any] = None) -> None:
        pending, self._pending = self._pending, None
        if pending is None or not self.sheet:
            return
        if tag is not None:
            self.tag = tag
            self.found = formats.read(tag)
        if ok and self.found and self.found[0] == pending["format"]:
            entry = dict(pending["spool"], format=pending["format"])
            entry.pop("left", None)
            key = spool_label(entry).lower()
            self.history = [entry] + [h for h in self.history if spool_label(h).lower() != key][:HISTORY_KEPT - 1]
            self.dirty = True
            self.sheet = {"step": "written", "format": pending["format"], "spool": pending["spool"]}
        else:
            self.sheet = dict(self.sheet, step="failed",
                              why=why or "The tag read back different from what was written.")

    def work(self) -> Optional[Dict[str, Any]]:
        """The writes to run now, once: {"uid", "ops", "format"}."""
        if self._pending and not self._pending.get("handed"):
            self._pending["handed"] = True
            self._pending["at"] = self._clock()
            return {"uid": self._pending["uid"], "ops": self._pending["ops"], "format": self._pending["format"]}
        if self._pending and self._pending.get("handed") and self._clock() - self._pending["at"] > WRITE_TIMEOUT:
            self.on_written(False, "The reader didn't answer. Try again.")
        return None

    def tick(self) -> None:
        if self._gone_at is not None and self.sheet and self.sheet["step"] in ("read", "written", "unknown"):
            if self._clock() - self._gone_at >= GONE_CLOSES_AFTER:
                self.sheet, self._gone_at = None, None

    # ---- from the screen -------------------------------------------------------------------------

    def input(self, payload: Dict[str, Any]) -> None:
        op = payload.get("op")
        if op == "close":
            if self.tag is not None:
                self._quiet_uid = self.tag.uid
            self.sheet, self._pending = None, None
            return
        if not self.sheet:
            return
        step = self.sheet["step"]
        if op == "pick":
            spool = self._picked(payload)
            if spool:
                self._to_write(spool)
        elif op == "library":
            self.sheet = dict(self.sheet, step="library")
        elif op == "back":
            self.sheet = {"step": "write" if step == "formats" else "which",
                          **({k: self.sheet[k] for k in ("spool", "format") if k in self.sheet} if step == "formats" else {})}
        elif op == "formats" and step == "write":
            self.sheet = dict(self.sheet, step="formats")
        elif op == "format" and step in ("write", "formats"):
            fid = payload.get("format")
            if fid in formats.BY_ID and self.tag is not None and formats.fits(formats.BY_ID[fid], self.tag) is None:
                self.choice_by_chip[self._chip_kind()] = fid
                self.dirty = True
                self.sheet = dict(self.sheet, step="write", format=fid)
        elif op == "write" and step in ("write", "failed"):
            self._start_write()
        elif op == "rewrite" and step in ("read", "unknown", "written"):
            self.sheet = {"step": "which", "over": True}
        elif op == "copy" and step == "read":
            self.sheet = {"step": "copy", "spool": self.sheet["spool"]}

    # ---- the view --------------------------------------------------------------------------------

    def view(self) -> Optional[Dict[str, Any]]:
        if self.reader is None and self.sheet is None:
            return None
        out: Dict[str, Any] = {"reader": self.reader, "sheet": None}
        if self.sheet is None:
            return out
        s = dict(self.sheet)
        s["tag"] = self._tag_view()
        if s["step"] in ("which", "library"):
            s["choices"] = self._choices()
        if "spool" in s:
            s["label"] = spool_label(s["spool"])
            s["facts"] = facts(s["spool"])
            s["color"] = formats.complete(s["spool"])["color"]
        if s.get("format"):
            readers = READERS if self._has_ace() else READERS_NO_ACE
            s["format_name"] = formats.BY_ID[s["format"]]["name"]
            s["readers"] = readers.get(s["format"], "")
        if s["step"] == "formats" and self.tag is not None:
            readers = READERS if self._has_ace() else READERS_NO_ACE
            s["formats"] = [{"id": f["id"], "name": f["name"], "why_not": formats.fits(f, self.tag),
                             "readers": readers.get(f["id"], "")} for f in formats.FORMATS]
        s["writing"] = bool(self._pending)
        out["sheet"] = s
        return out

    def _tag_view(self) -> Optional[Dict[str, Any]]:
        if self.tag is None:
            return None
        return {"chip": formats.CHIP_NAMES.get(self.tag.chip, self.tag.chip), "blank": self.tag.blank(),
                "uid": self.tag.uid.hex().upper()}

    def _choices(self) -> List[Dict[str, Any]]:
        out = []
        for sp in self._spools():
            if sp.get("rfid") or sp.get("status") == "empty" or not (sp.get("material") or sp.get("color")):
                continue
            out.append({"kind": "slot", "slot": sp["slot"], "label": sp.get("name") or spool_label(sp),
                        "color": (sp.get("color") or "").lstrip("#").upper() or None,
                        "sub": f"Slot {sp['slot'] + 1} · here now"})
        for i, h in enumerate(self.history[:4]):
            out.append({"kind": "history", "index": i, "label": spool_label(h),
                        "color": formats.complete(h)["color"], "sub": "Written here before"})
        return out

    # ---- helpers ---------------------------------------------------------------------------------

    def _picked(self, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if p.get("slot") is not None:
            sp = next((s for s in self._spools() if s.get("slot") == p["slot"]), None)
            if not sp:
                return None
            material = sp.get("material") or "PLA"
            words = (sp.get("name") or "").replace(material, "").strip()   # "Orange PETG" -> "Orange"
            return {"brand": "", "material": material, "name": words,
                    "color": (sp.get("color") or "").lstrip("#"), "weight": 1000, "source": "slot"}
        if p.get("history") is not None:
            try:
                h = dict(self.history[int(p["history"])])
            except (IndexError, ValueError):
                return None
            h.pop("format", None)
            return h
        if p.get("product") is not None:
            return library.spool(p["product"], p.get("color", ""), p.get("weight"))
        return None

    def _chip_kind(self) -> str:
        chip = self.tag.chip if self.tag is not None else ""
        return "ntag" if chip in formats.NTAG else chip

    def default_format(self) -> Optional[str]:
        """Pick 5 A: the tag in hand decides, unless a different one was picked for this kind of tag before."""
        if self.tag is None:
            return None
        kept = self.choice_by_chip.get(self._chip_kind())
        if kept and formats.fits(formats.BY_ID[kept], self.tag) is None:
            return kept
        order = (["anycubic", "tigertag"] if self._has_ace() else ["tigertag", "anycubic"]) + ["cfs", "openprinttag", "openspool"]
        return next((f for f in order if formats.fits(formats.BY_ID[f], self.tag) is None), None)

    def _to_write(self, spool: Dict[str, Any]) -> None:
        self.sheet = {"step": "write", "spool": spool, "format": self.default_format(), "waiting": self.tag is None}

    def _start_write(self) -> None:
        if self.tag is None:
            self.sheet = dict(self.sheet, step="write", waiting=True)
            return
        fid = self.sheet.get("format") or self.default_format()
        if fid is None:
            self.sheet = dict(self.sheet, step="failed", why="No format Bench writes fits this tag.")
            return
        try:
            ops = formats.encode(fid, self.sheet["spool"], self.tag)
        except ValueError as e:
            self.sheet = dict(self.sheet, step="failed", why=str(e))
            return
        self.sheet = dict(self.sheet, step="write", format=fid)
        self._pending = {"uid": self.tag.uid, "ops": ops, "format": fid, "spool": self.sheet["spool"]}
