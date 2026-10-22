"""The service against pretend units: its state, the commands, what it remembers, and units coming and going."""
import asyncio
import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import service as S  # noqa: E402
from pretend_ace import PretendAce  # noqa: E402


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(S, "POLL_S", 0.05)
    monkeypatch.setattr(S, "RETRY_S", 0.1)
    monkeypatch.setattr(S, "SCAN_S", 0.1)


class Rig:
    def __init__(self, tmp_path, n=2):
        self.tmp = tmp_path
        self.aces = [PretendAce(time_scale=8.0) for _ in range(n)]
        self.plugged = {f"3-1.{i + 1}": a.port for i, a in enumerate(self.aces)}
        self.sockdir = tempfile.mkdtemp(prefix="u", dir="/tmp")    # macOS caps socket paths at 104 characters
        self.sock = os.path.join(self.sockdir, "s")

    async def start(self):
        for a in self.aces:
            await a.start()
        self.svc = S.Service(str(self.tmp / "units.json"), scan=lambda: dict(self.plugged))
        self.task = asyncio.create_task(self.svc.run(self.sock))
        for _ in range(100):
            if os.path.exists(self.sock) and all(u.connected for u in self.svc.units) and len(self.svc.units) == len(self.plugged):
                break
            await asyncio.sleep(0.02)
        self.reader, self.writer = await asyncio.open_unix_connection(self.sock)
        self.rid = 0

    async def call(self, method, **params):
        self.rid += 1
        self.writer.write((json.dumps({"id": self.rid, "method": method, "params": params}) + "\n").encode())
        await self.writer.drain()
        while True:
            m = json.loads(await self.reader.readline())
            if m.get("id") == self.rid:
                return m

    async def stop(self):
        self.writer.close()
        self.task.cancel()
        for t in self.svc.tasks.values():
            t.cancel()
        await asyncio.gather(self.task, *self.svc.tasks.values(), return_exceptions=True)
        for a in self.aces:
            a.close()
        shutil.rmtree(self.sockdir, ignore_errors=True)


@pytest.fixture
async def rig(tmp_path):
    r = Rig(tmp_path)
    await r.start()
    yield r
    await r.stop()


async def test_two_units_make_eight_slots_in_the_shape_the_printer_code_reads(rig):
    rig.aces[1].insert(1, color=(117, 120, 123), kind="PETG", sku="AHPEGY-101")
    await asyncio.sleep(0.15)
    st = (await rig.call("state"))["result"]
    assert [(u["offset"], u["n"], u["connected"], u["firmware"]) for u in st["units"]] == [(0, 4, True, "V1.3.856"), (4, 4, True, "V1.3.856")]
    assert len(st["slots"]) == 8 and st["slots"][5] == {"slot": 5, "status": "ready", "color": "#75787B", "material": "PETG",
                                                        "tagged": True, "remain": None}
    assert st["selected"] is None and st["carry_on"] is False and st["dryer_max"] == 55


async def test_moving_filament_on_the_second_unit_uses_its_own_slot_number(rig):
    r = await rig.call("move", slot=6, mm=50, wait=True)
    assert r == {"id": rig.rid, "result": {}}
    assert rig.aces[1].filament_at(2) == pytest.approx(50)
    await rig.call("move", slot=6, mm=-50, wait=True)
    assert rig.aces[1].filament_at(2) == pytest.approx(0)
    assert rig.aces[0].requests and not any(m["method"] in ("feed_filament", "unwind_filament") for m in rig.aces[0].requests)


async def test_a_slot_that_doesnt_exist_and_an_unknown_method_are_errors(rig):
    assert (await rig.call("move", slot=8, mm=10))["error"]["message"] == "There's no such slot."
    assert "Unknown method" in (await rig.call("eject_everything"))["error"]["message"]


async def test_drying_is_capped_at_what_the_unit_allows(rig):
    await rig.call("dry", unit=1, temp=70, minutes=240)
    await asyncio.sleep(0.15)
    dryer = (await rig.call("state"))["result"]["units"][1]["dryer"]
    assert dryer["status"] == "drying" and dryer["target_temp"] == 55 and dryer["duration"] == 240
    await rig.call("stop_drying", unit=1)
    await asyncio.sleep(0.15)
    assert (await rig.call("state"))["result"]["units"][1]["dryer"]["status"] == "stop"


async def test_what_the_unit_cant_remember_survives_a_restart(rig, tmp_path):
    await rig.call("mark_loaded", slot=2)
    await rig.call("set_spool", slot=3, color="#00FF00", material="PLA")
    await rig.call("feed_assist", slot=2, on=True)
    await rig.call("carry_on", on=True)
    st = (await rig.call("state"))["result"]
    assert st["selected"] == 2 and st["feed_assist"][2] and st["carry_on"]
    assert (st["slots"][3]["color"], st["slots"][3]["material"], st["slots"][3]["tagged"]) == ("#00FF00", "PLA", False)
    await rig.stop()

    again = Rig(tmp_path)
    await again.start()
    try:
        st = (await again.call("state"))["result"]
        assert st["selected"] == 2 and st["feed_assist"][2] and st["carry_on"] and st["slots"][3]["material"] == "PLA"
        await asyncio.sleep(0.3)
        assert any(m["method"] == "start_feed_assist" and m["params"] == {"index": 2} for m in again.aces[0].requests)
    finally:
        await again.stop()


async def test_a_subscriber_hears_changes_and_an_unplugged_unit_keeps_its_slots(rig):
    rid = rig.rid + 1
    first = await rig.call("subscribe")
    assert first["id"] == rid and len(first["result"]["slots"]) == 8
    rig.aces[0].empty(1)
    while True:
        m = json.loads(await asyncio.wait_for(rig.reader.readline(), 2))
        if m.get("method") == "state" and m["params"]["slots"][1]["status"] == "empty":
            break
    del rig.plugged["3-1.1"]
    rig.aces[0].silent = True
    while True:    # three unanswered polls in a row, a second each
        m = json.loads(await asyncio.wait_for(rig.reader.readline(), 6))
        if m.get("method") == "state" and not m["params"]["units"][0]["connected"]:
            break
    st = m["params"]
    assert [u["offset"] for u in st["units"]] == [0, 4] and st["slots"][0]["status"] == "unknown"
    assert st["slots"][4]["status"] == "ready"
