"""The whole chain without hardware: a pretend ACE Pro, the service, the printer code's link to it, the engine
reading the state, and an action planned by the engine reaching the unit."""
import asyncio
import os
import shutil
import sys
import tempfile

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "printer"))
import elyir_bench_intent as engine  # noqa: E402
import service as S  # noqa: E402
from pretend_ace import PretendAce  # noqa: E402

fu = engine.filament_units


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(S, "POLL_S", 0.05)
    monkeypatch.setattr(S, "RETRY_S", 0.1)
    monkeypatch.setattr(S, "SCAN_S", 0.1)


async def until(cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.02)


async def test_an_action_planned_by_the_engine_moves_the_pretend_unit(tmp_path):
    ace = PretendAce(time_scale=8.0)
    await ace.start()
    ace.insert(2, color=(117, 120, 123), kind="PETG", sku="AHPEGY-101")
    sockdir = tempfile.mkdtemp(prefix="u", dir="/tmp")
    sock = os.path.join(sockdir, "s")
    svc = S.Service(str(tmp_path / "units.json"), scan=lambda: {"3-1.3": ace.port})
    served = asyncio.create_task(svc.run(sock))

    t = engine.IntentTracker("Workshop")
    t.set_klippy_state("ready")
    t.update_status({"print_stats": {"state": "standby"}})

    def on_state(st):
        t.update_status({"elyir_units": st or {"units": [], "slots": []}})
        t.has_unit = bool(st and st.get("units"))

    link = fu.UnitsLink(sock, on_state)
    try:
        await until(lambda: os.path.exists(sock))
        assert link.due()
        linked = asyncio.create_task(link.run())
        await until(lambda: t.unit_state() is not None and t.unit_state()["units"][0]["connected"])
        assert t.unit_state()["driver"] == "elyir"
        spools = t.spools()
        assert len(spools) == 4 and spools[2]["name"] == "Gray PETG" and spools[2]["rfid"]

        for kind, payload in engine.plan_slot("move_filament", {"slot": 3, "mm": 50}, t):
            assert kind == engine.ActionPlan.UNIT
            await link.call(payload)
        await until(lambda: ace.filament_at(3) == pytest.approx(50))

        for kind, payload in engine.plan_spool_move("mark_loaded", {"slot": 2}, t):
            await link.call(payload)
        await until(lambda: t._selected_slot() == 2)
        assert [s["in_use"] for s in t.spools()] == [False, False, True, False]

        with pytest.raises(RuntimeError, match="no such slot"):
            await link.call({"op": "move", "slot": 9, "mm": 10})

        served.cancel()
        for task in svc.tasks.values():
            task.cancel()
        for w in list(svc.subscribers):
            w.close()
        await until(lambda: t.unit_state() is None)
        await linked
        assert not link.running and t.direct and len(t.spools()) == 1     # back to one spool, no unit
    finally:
        served.cancel()
        for task in svc.tasks.values():
            task.cancel()
        await asyncio.gather(served, *svc.tasks.values(), return_exceptions=True)
        ace.close()
        shutil.rmtree(sockdir, ignore_errors=True)
