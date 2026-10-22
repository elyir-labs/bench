"""A pretend ACE Pro on a pseudo-terminal, answering the way the captured unit does (ace-protocol.md). For tests
and the simulator. Unlike the real one it knows where each slot's filament is, so tests can check distances."""
import asyncio
import os
import pty
import tty
from typing import Any, Dict, List, Optional

from ace_link import Decoder, encode

SHIFT_S = 0.3        # every move starts by shifting to its slot; a feed stop sent then is ignored
TAIL_S = 1.0         # the slot keeps its moving status this long after the motor stops
BACKLOG = 64 * 1024
RELEASE_MM = 15      # stopping feed assist pulls the filament back about this far
INFO = {"id": 1, "slots": 4, "model": "Anycubic Color Engine Pro", "firmware": "V1.3.856",
        "boot_firmware": "V1.0.1", "structure_version": "0"}


def blank_slot() -> Dict[str, Any]:
    return {"status": "ready", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1}


class PretendAce:
    def __init__(self, slots: Optional[List[Dict[str, Any]]] = None, time_scale: float = 1.0) -> None:
        self.master, self._slave = pty.openpty()
        tty.setraw(self._slave)
        os.set_blocking(self.master, False)   # replies queue in self.out and go out as the terminal takes them
        self.out = bytearray()
        self.port = os.ttyname(self._slave)
        self.scale = time_scale
        self.slots = [dict(blank_slot(), **(s or {})) for s in (slots or [{}] * 4)]
        self.position = [0.0] * 4            # mm ahead of where each slot's filament started
        self.motion: Optional[Dict[str, Any]] = None
        self.tail: Optional[Dict[str, Any]] = None
        self.assist: Optional[int] = None
        self.dryer: Dict[str, Any] = {"status": "stop", "target_temp": 0, "duration": 0, "end": None}
        self.action: Optional[str] = None    # absent from status until the first command
        self.feed_assist_count = 0
        self.requests: List[Dict[str, Any]] = []
        self.silent = False                  # stops answering, as a unit that hangs
        self.one_at_a_time = True            # of requests arriving together, only the first is answered
        self.dec = Decoder()
        self._t0 = None

    def now(self) -> float:
        loop = asyncio.get_running_loop()
        if self._t0 is None:
            self._t0 = loop.time()
        return (loop.time() - self._t0) * self.scale

    async def start(self) -> None:
        self.now()
        asyncio.get_running_loop().add_reader(self.master, self._readable)

    def close(self) -> None:
        try:
            asyncio.get_running_loop().remove_reader(self.master)
            asyncio.get_running_loop().remove_writer(self.master)
        except (RuntimeError, ValueError):
            pass
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def _readable(self) -> None:
        try:
            data = os.read(self.master, 4096)
        except (BlockingIOError, OSError):
            return
        for i, msg in enumerate(self.dec.feed(data)):
            self.requests.append(msg)
            if self.silent or (self.one_at_a_time and i > 0):
                continue
            self.out += encode(self.handle(msg))
            del self.out[:-BACKLOG]          # nobody reading at all: keep the newest, as a full USB buffer would
            self._flush()

    def _flush(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while self.out:
                n = os.write(self.master, bytes(self.out))
                del self.out[:n]
        except BlockingIOError:
            loop.add_writer(self.master, self._flush)
            return
        except OSError:
            self.out.clear()
        loop.remove_writer(self.master)

    # ---- the unit's behavior ---------------------------------------------------------

    def _settle(self) -> None:
        """Bring motion and the dryer up to now."""
        t = self.now()
        m = self.motion
        if m:
            moving_since = m["t0"] + SHIFT_S
            if t >= moving_since:
                done = min(m["length"], (t - moving_since) * m["speed"])
                self.position[m["slot"]] = m["start"] + m["dir"] * done
                if done >= m["length"]:
                    self._finish(m, moving_since + m["length"] / m["speed"])
        if self.tail and t >= self.tail["until"]:
            self.tail = None
        if self.dryer["end"] is not None and t >= self.dryer["end"]:
            self.dryer = {"status": "stop", "target_temp": 0, "duration": 0, "end": None}

    def _finish(self, m: Dict[str, Any], at: float) -> None:
        self.motion = None
        self.action = "ready"
        self.tail = {"slot": m["slot"], "state": m["state"], "until": at + TAIL_S}

    def _move(self, msg: Dict[str, Any], direction: int) -> Dict[str, Any]:
        p = msg.get("params") or {}
        slot = p.get("index")
        if not isinstance(slot, int) or not 0 <= slot < len(self.slots):
            return {"result": {}, "code": 0, "msg": "FORBIDDEN"}
        self._settle()
        if self.motion or self.tail:
            return {"result": {}, "code": 0, "msg": "FORBIDDEN"}    # still busy (captures/2026-10-18-busy-probe.txt)
        state = "feeding" if direction > 0 else "unwinding"
        self.motion = {"slot": slot, "dir": direction, "state": state, "t0": self.now(),
                       "length": float(p.get("length") or 0), "speed": float(p.get("speed") or 50),
                       "start": self.position[slot]}
        self.tail = None
        self.action = "shifting"
        if direction > 0:
            self.feed_assist_count = 0
        return {"result": {}, "code": 0, "msg": "success"}

    def _stop(self, direction: int) -> Dict[str, Any]:
        self._settle()
        m = self.motion
        if m and m["dir"] == direction and self.now() >= m["t0"] + SHIFT_S:
            self._finish(m, self.now())
        return {"result": {}, "code": 0, "msg": "success"}

    def status(self) -> Dict[str, Any]:
        self._settle()
        t = self.now()
        m, tail = self.motion, self.tail
        slots = []
        for i, s in enumerate(self.slots):
            st = s["status"]
            if m and m["slot"] == i:
                st = "shifting" if t < m["t0"] + SHIFT_S else m["state"]
            elif tail and tail["slot"] == i:
                st = tail["state"]
            slots.append({"index": i, "status": st, "sku": s["sku"], "type": s["type"],
                          "color": list(s["color"]), "rfid": s["rfid"]})
        action = self.action
        if m:
            action = "shifting" if t < m["t0"] + SHIFT_S else m["state"]
        d = self.dryer
        out = {"status": "busy" if (m or tail) else "ready",
               "dryer_status": {"status": d["status"], "target_temp": d["target_temp"], "duration": d["duration"],
                                "remain_time": max(0, int(round(d["end"] - t))) if d["end"] is not None else 0},
               "temp": d["target_temp"] or 31, "enable_rfid": 1, "fan_speed": 7000,
               "feed_assist_count": self.feed_assist_count, "cont_assist_time": 0.0, "slots": slots}
        if action is not None:
            out["action"] = action
        return out

    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        rid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "get_info":
            reply = {"code": 0, "result": dict(INFO), "msg": "success"}
        elif method == "get_status":
            reply = {"result": self.status(), "code": 0, "msg": "success"}
        elif method == "feed_filament":
            reply = self._move(msg, +1)
        elif method == "unwind_filament":
            reply = self._move(msg, -1)
        elif method == "stop_feed_filament":
            reply = self._stop(+1)
        elif method == "stop_unwind_filament":
            reply = self._stop(-1)
        elif method == "start_feed_assist":
            self.assist, self.action = p.get("index"), "shifting"
            self.feed_assist_count += 1
            reply = {"result": {}, "code": 0, "msg": "success"}
        elif method == "stop_feed_assist":
            # as the real unit did on 18 October: an empty msg, then a short pull back (shifting, unwinding)
            slot, self.assist = p.get("index"), None
            if isinstance(slot, int) and 0 <= slot < len(self.slots) and not (self.motion or self.tail):
                self._move({"params": {"index": slot, "length": RELEASE_MM, "speed": 50}}, -1)
            reply = {"result": {}, "code": 0, "msg": ""}
        elif method == "drying":
            minutes = int(p.get("duration") or 0)
            self.dryer = {"status": "drying", "target_temp": int(p.get("temp") or 0), "duration": minutes,
                          "end": self.now() + minutes * 60}
            reply = {"result": {}, "code": 0, "msg": "drying"}
        elif method == "drying_stop":
            self.dryer = {"status": "stop", "target_temp": 0, "duration": 0, "end": None}
            reply = {"result": {}, "code": 0, "msg": "success"}
        else:
            reply = {"result": {}, "code": 400, "msg": "InvalidCommand"}
        return dict(reply, id=rid)

    def filament_at(self, slot: int) -> float:
        """How far this slot's filament is ahead of where it started, in mm."""
        self._settle()
        return self.position[slot]

    # ---- what a person does to the unit ----------------------------------------------

    def insert(self, slot: int, color=(0, 0, 0), kind: str = "", sku: str = "") -> None:
        """A spool pushed in; a tagged one carries its color, type and SKU."""
        tagged = bool(sku or kind)
        self.slots[slot] = {"status": "ready", "sku": sku, "type": kind, "color": list(color), "rfid": 2 if tagged else 1}
        self.position[slot] = 0.0

    def empty(self, slot: int) -> None:
        self.slots[slot] = dict(blank_slot(), status="empty")
