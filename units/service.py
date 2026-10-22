"""The filament-unit service (design/ace-driver/, A): owns each ACE Pro's USB port, polls it, keeps what the unit
can't remember itself (the slot in the head, colors and materials of untagged spools, feed assist, carry-on), and
answers the printer code over a Unix socket in JSON lines.

Requests  {"id", "method", "params"} -> {"id", "result"} or {"id", "error": {"message"}}
Pushes    {"method": "state", "params": <the units in filament_units.py's shape>} after "subscribe"
"""
import argparse
import asyncio
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from ace_link import Link, LinkClosed
from toolchange import ChangeError, Changer

ACE_USB_IDS = {("28e9", "018a")}
POLL_S = 0.5
RETRY_S = 2.0
SCAN_S = 2.0
FEED_SPEED, UNWIND_SPEED = 80, 50      # mm/s, the speeds the units ran at when captured
DRYER_MAX = 55
DRYER_FAN = 7000
MOVING = ("shifting", "feeding", "unwinding")
MISSES = 3          # unanswered polls in a row before the link is opened again


class UnitError(Exception):
    pass


log = logging.getLogger("units")


def aces_on_usb(root: str = "/sys/bus/usb/devices") -> Dict[str, str]:
    """{USB port path: its serial device} for every ACE Pro plugged in. The port path stays the same for a
    socket on the hub, so a unit keeps its slots across replugs; two units can share a serial number."""
    out: Dict[str, str] = {}
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        d = os.path.join(root, name)
        try:
            with open(os.path.join(d, "idVendor")) as v, open(os.path.join(d, "idProduct")) as p:
                if (v.read().strip().lower(), p.read().strip().lower()) not in ACE_USB_IDS:
                    continue
            ttys = os.listdir(os.path.join(d, f"{name}:1.0", "tty"))
        except OSError:
            continue
        if ttys:
            out[name] = f"/dev/{sorted(ttys)[0]}"
    return out


class Unit:
    """One ACE Pro: its link, what it last said, and whether it's answering."""

    def __init__(self, key: str, device: str) -> None:
        self.key, self.device = key, device
        self.link: Optional[Link] = None
        self.info: Dict[str, Any] = {}
        self.status: Dict[str, Any] = {}
        self.connected = False
        self._seen: tuple = ()

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.connected or self.link is None:
            raise UnitError("The filament unit isn't connected.")
        try:
            r = await self.link.call(method, params)
        except (asyncio.TimeoutError, LinkClosed) as e:
            log.info("%s %s %s -> no answer (%s)", self.key, method, params or "", e.__class__.__name__)
            raise UnitError("The filament unit didn't answer.") from e
        log.info("%s %s %s -> %s %r", self.key, method, params or "", r.get("code"), r.get("msg"))
        # stop_feed_assist can answer with an empty msg (captures/2026-10-18-busy-probe.txt)
        if r.get("code") == 0 and r.get("msg") in ("success", "drying", "", None):
            return r
        if r.get("msg") == "FORBIDDEN":
            raise UnitError("The filament unit refused: it was still busy, or there's no such slot.")
        raise UnitError(f"The filament unit said {r.get('msg') or r.get('code')}.")

    async def status_now(self) -> Dict[str, Any]:
        """The unit's status asked for now, not the last poll's."""
        if self.link is None:
            raise UnitError("The filament unit isn't connected.")
        try:
            return (await self.link.call("get_status")).get("result") or {}
        except (asyncio.TimeoutError, LinkClosed) as e:
            raise UnitError("The filament unit didn't answer.") from e

    async def until_ready(self, timeout: float = 20.0) -> None:
        """A move sent while the unit is busy, the second or so after the motor stops included, is FORBIDDEN."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if (await self.status_now()).get("status") == "ready":
                return
            await asyncio.sleep(0.1)
        raise UnitError("The filament unit stayed busy.")

    async def run(self, changed: Callable[[], None]) -> None:
        while True:
            try:
                self.link = Link(self.device)
                await self.link.open()
                self.info = (await self.link.call("get_info")).get("result") or {}
                self.connected = True
                changed()
                misses = 0
                while True:
                    try:
                        r = await self.link.call("get_status")
                    except asyncio.TimeoutError:
                        misses += 1
                        if misses >= MISSES:
                            raise
                        continue
                    misses = 0
                    st = r.get("result") or {}
                    seen = (st.get("status"), st.get("action"), tuple(sl.get("status") for sl in st.get("slots") or []))
                    if seen != self._seen:
                        log.info("%s status=%s action=%s slots=%s", self.key, *seen)
                        self._seen = seen
                    if st != self.status:
                        self.status = st
                        changed()
                    await asyncio.sleep(POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self.connected:
                    logging.info("units: %s stopped answering: %s", self.key, e)
            finally:
                was = self.connected
                self.connected = False
                if self.link:
                    self.link.close()
                if was:
                    changed()
            await asyncio.sleep(RETRY_S)


class Service:
    def __init__(self, state_path: str, scan: Callable[[], Dict[str, str]] = aces_on_usb,
                 moonraker: Optional[str] = None) -> None:
        self.state_path = state_path
        self.scan = scan
        self.saved = self._load()
        self.units: List[Unit] = []
        self.tasks: Dict[str, asyncio.Task] = {}
        self.subscribers: List[asyncio.StreamWriter] = []
        self._changed = asyncio.Event()
        self.changer = Changer(self, self.saved["settings"])
        self.moonraker_url = moonraker

    # ---- what the service remembers ---------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.state_path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        return {"ports": list(saved.get("ports") or []), "selected": saved.get("selected"),
                "spools": dict(saved.get("spools") or {}), "assist": saved.get("assist"),
                "carry_on": bool(saved.get("carry_on", False)), "settings": dict(saved.get("settings") or {})}

    def _save(self) -> None:
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.saved, f, indent=1)
        os.replace(tmp, self.state_path)

    # ---- units coming and going -------------------------------------------------------

    def refresh(self) -> None:
        """Start a unit for every ACE on USB. Units are kept in the order first seen, so slot numbers don't move."""
        found = self.scan()
        for key in sorted(found):
            if key not in self.saved["ports"]:
                self.saved["ports"].append(key)
                self._save()
        for key in self.saved["ports"]:
            unit = next((u for u in self.units if u.key == key), None)
            if unit is None:
                unit = Unit(key, found.get(key, ""))
                self.units.append(unit)
            if key in found:
                unit.device = found[key]
                if key not in self.tasks or self.tasks[key].done():
                    self.tasks[key] = asyncio.create_task(unit.run(self.changed))
        self.units.sort(key=lambda u: self.saved["ports"].index(u.key))

    async def watch_usb(self) -> None:
        while True:
            self.refresh()
            await asyncio.sleep(SCAN_S)

    def changed(self) -> None:
        self._changed.set()

    # ---- the state, in filament_units.py's shape ----------------------------------------

    def where(self, slot: int) -> tuple:
        """The unit holding a slot, and the slot's number on that unit."""
        if not isinstance(slot, int) or slot < 0:
            raise UnitError("There's no such slot.")
        offset = 0
        for u in self.units:
            n = self._slots_on(u)
            if slot < offset + n:
                return u, slot - offset
            offset += n
        raise UnitError("There's no such slot.")

    @staticmethod
    def _slots_on(u: Any) -> int:
        return len(u.status.get("slots") or []) or 4

    def slot_count(self) -> int:
        return sum(self._slots_on(u) for u in self.units)

    def state(self) -> Dict[str, Any]:
        units, slots, offset = [], [], 0
        spools = self.saved["spools"]
        for i, u in enumerate(self.units):
            st = u.status if u.connected else {}
            raw = st.get("slots") or [{} for _ in range(4)]
            units.append({"index": i, "alias": None, "offset": offset, "n": len(raw), "connected": u.connected,
                          "temp": st.get("temp"), "dryer": st.get("dryer_status"), "busy": st.get("status") == "busy",
                          "firmware": u.info.get("firmware")})
            for k, s in enumerate(raw):
                g = offset + k
                status = str(s.get("status") or "unknown")
                status = "ready" if status in MOVING else status if status in ("ready", "empty") else "unknown"
                rgb = s.get("color")
                tag_color = "#%02X%02X%02X" % tuple(rgb[:3]) if isinstance(rgb, list) and len(rgb) >= 3 and any(rgb) else None
                tag_type = (s.get("type") or "").strip() or None
                told = spools.get(str(g)) or {}
                tagged = s.get("rfid") == 2 and bool(tag_color or tag_type or s.get("sku"))
                slots.append({"slot": g, "status": status if u.connected else "unknown",
                              "color": tag_color or told.get("color"), "material": tag_type or told.get("material"),
                              "tagged": tagged, "remain": None})
            offset += len(raw)
        assist = self.saved["assist"]
        return {"units": units, "slots": slots, "selected": self.saved["selected"],
                "feed_assist": [assist == s["slot"] for s in slots], "carry_on": self.saved["carry_on"],
                "dryer_max": DRYER_MAX, "change": self.changer.state(),
                "printer": self.changer.mr is not None and self.changer.mr.ready.is_set()}

    # ---- what the printer code may ask --------------------------------------------------

    async def move(self, slot: int, mm: int, wait: bool = False) -> Dict[str, Any]:
        u, k = self.where(slot)
        await u.until_ready()
        if mm > 0:
            await u.call("feed_filament", {"index": k, "length": int(mm), "speed": FEED_SPEED})
        else:
            await u.call("unwind_filament", {"index": k, "length": int(-mm), "speed": UNWIND_SPEED})
        if wait:
            await self._until_still(u)
        return {}

    async def _until_still(self, u: Unit, timeout: float = 120.0) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        await asyncio.sleep(POLL_S * 2)
        while loop.time() < end:
            if u.status.get("action") not in MOVING and u.status.get("status") != "busy":
                return
            await asyncio.sleep(POLL_S / 2)
        raise UnitError("The filament unit is still moving.")

    async def stop(self, slot: int) -> Dict[str, Any]:
        u, k = self.where(slot)
        await u.call("stop_feed_filament", {"index": k})
        await u.call("stop_unwind_filament", {"index": k})
        return {}

    async def dry(self, unit: int, temp: int, minutes: int) -> Dict[str, Any]:
        if not 0 <= unit < len(self.units):
            raise UnitError("There's no such unit.")
        await self.units[unit].call("drying", {"temp": min(int(temp), DRYER_MAX), "fan_speed": DRYER_FAN,
                                               "duration": int(minutes)})
        return {}

    async def stop_drying(self, unit: int) -> Dict[str, Any]:
        if not 0 <= unit < len(self.units):
            raise UnitError("There's no such unit.")
        await self.units[unit].call("drying_stop")
        return {}

    async def feed_assist(self, slot: int, on: bool) -> Dict[str, Any]:
        u, k = self.where(slot)
        await u.call("start_feed_assist" if on else "stop_feed_assist", {"index": k})
        self.saved["assist"] = slot if on else None
        self._save()
        self.changed()
        return {}

    async def carry_on(self, on: bool) -> Dict[str, Any]:
        self.saved["carry_on"] = bool(on)
        self._save()
        self.changed()
        return {}

    async def set_spool(self, slot: int, color: str, material: str) -> Dict[str, Any]:
        self.where(slot)
        self.saved["spools"][str(slot)] = {"color": color, "material": material}
        self._save()
        self.changed()
        return {}

    async def mark_loaded(self, slot: int) -> Dict[str, Any]:
        if slot != -1:
            self.where(slot)
        self.saved["selected"] = None if slot == -1 else slot
        self._save()
        self.changed()
        return {}

    async def restore(self) -> None:
        """Feed assist comes back on after a restart, for the slot in the head, once its unit answers."""
        slot = self.saved["assist"]
        if slot is None or slot != self.saved["selected"]:
            return
        for _ in range(60):
            try:
                u, k = self.where(slot)
                if u.connected:
                    await u.call("start_feed_assist", {"index": k})
                    return
            except UnitError:
                pass
            await asyncio.sleep(RETRY_S)

    async def change_tool(self, slot: int, purge: bool = True) -> Dict[str, Any]:
        """Load a slot into the head, or unload it with -1, from the screen."""
        if slot != -1:
            self.where(slot)
        try:
            await self.changer.change(slot, in_print=False, purge=purge)
        except ChangeError as e:
            raise UnitError(str(e)) from e
        return {}

    async def purge(self, mm: float, temp: Optional[int] = None) -> Dict[str, Any]:
        try:
            await self.changer.purge(mm, temp)
        except ChangeError as e:
            raise UnitError(str(e)) from e
        return {}

    METHODS = ("move", "stop", "dry", "stop_drying", "feed_assist", "carry_on", "set_spool", "mark_loaded", "change_tool",
               "purge")

    # ---- the socket ---------------------------------------------------------------------

    async def serve(self, path: str) -> asyncio.AbstractServer:
        if os.path.exists(path):
            os.unlink(path)
        return await asyncio.start_unix_server(self._client, path=path)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Each request runs by itself, so a tool change taking minutes doesn't hold up the others."""
        running = set()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                except ValueError:
                    continue
                task = asyncio.ensure_future(self._answer(req, writer))
                running.add(task)
                task.add_done_callback(running.discard)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if writer in self.subscribers:
                self.subscribers.remove(writer)
            writer.close()

    async def _answer(self, req: Dict[str, Any], writer: asyncio.StreamWriter) -> None:
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        try:
            if method == "subscribe":
                self.subscribers.append(writer)
                result: Any = self.state()
            elif method == "state":
                result = self.state()
            elif method in self.METHODS:
                result = await getattr(self, method)(**params)
            else:
                raise UnitError(f"Unknown method {method}.")
            reply = {"id": rid, "result": result}
        except (UnitError, TypeError) as e:
            reply = {"id": rid, "error": {"message": str(e)}}
        except Exception as e:     # whatever it was, the asker hears back rather than waiting for ever
            logging.exception("units: %s failed", method)
            reply = {"id": rid, "error": {"message": str(e) or e.__class__.__name__}}
        try:
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        except (ConnectionError, RuntimeError):
            pass

    async def publish(self) -> None:
        last = None
        while True:
            await self._changed.wait()
            self._changed.clear()
            st = self.state()
            if st == last:
                continue
            last = st
            line = (json.dumps({"method": "state", "params": st}) + "\n").encode()
            for w in list(self.subscribers):
                try:
                    w.write(line)
                    await w.drain()
                except (ConnectionError, RuntimeError):
                    self.subscribers.remove(w)

    def _printer(self) -> Any:
        from moonraker import Moonraker
        c = self.changer

        def tool(params: Dict[str, Any]) -> None:
            try:
                length = float(params.get("purge", -1))
            except (TypeError, ValueError):
                length = -1.0
            c.start(int(params.get("tool", -1)), bool(params.get("in_print")), length if length >= 0 else None)

        def status(st: Dict[str, Any]) -> None:
            c.on_status(st)
            self.changed()
        c.mr = Moonraker(self.moonraker_url, {"elyir_tool": tool, "elyir_sensor": c.on_sensor_push}, status, c.objects())
        return c.mr

    async def run(self, path: str) -> None:
        server = await self.serve(path)
        self.refresh()
        tasks = [asyncio.create_task(self.watch_usb()), asyncio.create_task(self.publish()),
                 asyncio.create_task(self.restore())]
        if self.moonraker_url:
            tasks.append(asyncio.create_task(self._printer().run()))
        async with server:
            await asyncio.gather(*tasks)


def main() -> None:
    ap = argparse.ArgumentParser(description="The filament-unit service: drives ACE Pro units for the printer code.")
    ap.add_argument("--socket", default=os.path.expanduser("~/printer_data/comms/elyir-units.sock"))
    ap.add_argument("--state", default=os.path.expanduser("~/printer_data/config/elyir-units.json"))
    ap.add_argument("--moonraker", default="ws://127.0.0.1:7125/websocket", help="empty: no tool changes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(Service(args.state, moonraker=args.moonraker or None).run(args.socket))


if __name__ == "__main__":
    main()
