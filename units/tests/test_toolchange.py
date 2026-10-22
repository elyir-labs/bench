"""Tool changes by the service (the quiet pause), on pretend units and a pretend printer: loading from the screen,
a change from one slot to another, one asked for by a print's ELYIR_TOOL, a jam, and Cancel during a change."""
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
from pretend_printer import PretendPrinter  # noqa: E402

SENSOR_AT, GRIP, NOZZLE = 600.0, 8.0, 120.0
SETTINGS = {"before_macro": "BEFORE_CHANGE", "after_macro": "AFTER_CHANGE", "sensor_to_nozzle": NOZZLE, "park": 170}


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(S, "POLL_S", 0.05)
    monkeypatch.setattr(S, "RETRY_S", 0.1)
    monkeypatch.setattr(S, "SCAN_S", 0.1)


class Rig:
    def __init__(self, tmp_path, loaded=None, settings=None):
        self.ace = PretendAce(time_scale=20.0)
        self.tmp = tmp_path
        self.loaded = loaded
        self.settings = dict(SETTINGS, **(settings or {}))

    async def start(self):
        await self.ace.start()
        self.printer = PretendPrinter([self.ace], SENSOR_AT, GRIP, NOZZLE, loaded=self.loaded, time_scale=20.0)
        await self.printer.start()
        with open(self.tmp / "units.json", "w") as f:
            json.dump({"selected": self.loaded, "settings": self.settings}, f)
        self.sockdir = tempfile.mkdtemp(prefix="u", dir="/tmp")
        self.sock = os.path.join(self.sockdir, "s")
        self.svc = S.Service(str(self.tmp / "units.json"), scan=lambda: {"3-1.1": self.ace.port}, moonraker=self.printer.url)
        self.task = asyncio.create_task(self.svc.run(self.sock))
        await until(lambda: self.svc.units and self.svc.units[0].connected and self.svc.changer.mr is not None
                    and self.svc.changer.mr.ready.is_set())
        self.reader, self.writer = await asyncio.open_unix_connection(self.sock)
        self.rid = 0

    async def call(self, method, timeout=30, **params):
        self.rid += 1
        rid = self.rid
        self.writer.write((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        await self.writer.drain()
        while True:
            m = json.loads(await asyncio.wait_for(self.reader.readline(), timeout))
            if m.get("id") == rid:
                return m

    def moves(self):
        return [m for m in self.ace.requests if m["method"] not in ("get_status", "get_info")]

    async def stop(self):
        self.writer.close()
        self.task.cancel()
        for t in self.svc.tasks.values():
            t.cancel()
        await asyncio.gather(self.task, *self.svc.tasks.values(), return_exceptions=True)
        await self.printer.close()
        self.ace.close()
        shutil.rmtree(self.sockdir, ignore_errors=True)


async def until(cond, timeout=10.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.02)


@pytest.fixture
async def empty_head(tmp_path):
    r = Rig(tmp_path)
    await r.start()
    yield r
    await r.stop()


@pytest.fixture
async def slot1_in_head(tmp_path):
    r = Rig(tmp_path, loaded=1)
    await r.start()
    yield r
    await r.stop()


async def test_loading_from_the_screen_feeds_to_the_sensor_then_the_extruder_takes_it_to_the_nozzle(empty_head):
    r = empty_head
    assert (await r.call("change_tool", slot=2)) == {"id": r.rid, "result": {}}
    p = r.printer
    assert p.detected and p.x[2] >= SENSOR_AT + GRIP + NOZZLE - 10
    assert [e[0] for e in p.edges] == [True]
    assert p.gcode_log[0].startswith("BEFORE_CHANGE FROM=-1 TO=2 TEMP=230")
    assert "M109 S230" in p.gcode_log and p.gcode_log[-1].startswith("AFTER_CHANGE")
    methods = [m["method"] for m in r.moves()]
    assert methods[:2] == ["feed_filament", "stop_feed_filament"] and "start_feed_assist" in methods
    st = (await r.call("state"))["result"]
    assert st["selected"] == 2 and st["feed_assist"][2] and st["change"] is None


async def test_a_change_takes_the_old_filament_out_stopping_at_the_sensor_and_parks_it(slot1_in_head):
    r = slot1_in_head
    await r.call("change_tool", slot=3)
    p = r.printer
    assert [e[0] for e in p.edges] == [False, True]
    cleared_at = p.edges[0][1]
    # parked 170 mm behind where the sensor cleared, plus at most the short pull stopping feed assist makes
    from pretend_ace import RELEASE_MM
    assert -170 - RELEASE_MM - 3 <= r.ace.filament_at(1) - cleared_at <= -170 + 3
    assert p.x[1] < SENSOR_AT and p.x[3] >= SENSOR_AT + GRIP + NOZZLE - 10
    out = next(i for i, line in enumerate(p.gcode_log) if line.startswith("G1 E-125"))
    assert p.gcode_log[out + 1] == "M400", "the service waits for the extruder's move to end"
    assert (await r.call("state"))["result"]["selected"] == 3


async def test_a_print_asking_for_another_slot_pauses_changes_and_carries_on(slot1_in_head):
    r = slot1_in_head
    p = r.printer
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=0")
    assert p.paused
    await until(lambda: p.state == "printing" and r.svc.changer.going is None, 15)
    assert p.gcode_log[-1] == "RESUME_BASE" and p.x[0] >= SENSOR_AT + GRIP + NOZZLE - 10
    assert (await r.call("state"))["result"]["selected"] == 0


async def test_the_slicer_s_purge_length_goes_to_the_after_change_macro(slot1_in_head):
    r = slot1_in_head
    p = r.printer
    p.start_print()
    await p.run_gcode("ELYIR_PURGE LENGTH=98.53\nELYIR_TOOL T=0")
    await until(lambda: p.state == "printing" and r.svc.changer.going is None, 15)
    after = [g for g in p.gcode_log if g.startswith("AFTER_CHANGE")]
    assert after == ["AFTER_CHANGE FROM=1 TO=0 TEMP=230 PURGE=1 LENGTH=98.5"]
    # the next change without one: the macro's own amount
    await p.run_gcode("ELYIR_TOOL T=1")
    await until(lambda: p.state == "printing" and r.svc.changer.going is None, 15)
    assert [g for g in p.gcode_log if g.startswith("AFTER_CHANGE")][-1] == "AFTER_CHANGE FROM=0 TO=1 TEMP=230 PURGE=1"


async def test_a_jam_stops_the_unit_and_says_so_and_a_print_stays_paused(slot1_in_head):
    r = slot1_in_head
    p = r.printer
    p.blocked.add(2)
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=2")
    await until(lambda: r.svc.changer.error is not None and r.svc.changer.going is None, 20)
    assert r.svc.changer.error == "The filament didn't reach the toolhead."
    assert p.paused and p.state == "paused" and "RESUME_BASE" not in p.gcode_log
    st = (await r.call("state"))["result"]
    assert st["change"] == {"from": 1, "to": 2, "in_print": True, "error": "The filament didn't reach the toolhead.",
                            "cooled": False}
    assert r.svc.saved["assist"] is None, "a restart now would push the old filament on into a stuck head"
    assert r.ace.motion is None


async def test_a_print_asking_for_a_slot_that_isnt_there_stays_paused_with_the_old_filament_in(slot1_in_head):
    r = slot1_in_head
    p = r.printer
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=5")
    await until(lambda: r.svc.changer.error is not None and r.svc.changer.going is None, 20)
    assert r.svc.changer.error == "This print wants slot 6, and there are 4 slots."
    assert p.paused and "RESUME_BASE" not in p.gcode_log
    assert not [m for m in r.moves() if m["method"] in ("feed_filament", "unwind_filament")]
    assert not any(line.startswith("NOZZLE") for line in p.gcode_log)
    assert (await r.call("state"))["result"]["selected"] == 1


@pytest.fixture
async def quick_to_cool(tmp_path):
    r = Rig(tmp_path, loaded=1, settings={"cool_after": 0.3, "standby_temp": 150})
    await r.start()
    yield r
    await r.stop()


async def test_a_failed_change_nobody_answers_cools_the_nozzle_and_try_again_heats_it_first(quick_to_cool):
    r = quick_to_cool
    p = r.printer
    p.blocked.add(2)
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=2")
    await until(lambda: r.svc.changer.error is not None and r.svc.changer.going is None, 20)
    assert (await r.call("state"))["result"]["change"]["cooled"] is False
    await until(lambda: "M104 S150" in p.gcode_log, 5)
    assert p.paused and (await r.call("state"))["result"]["change"]["cooled"] is True
    p.blocked.clear()
    p.gcode_log.clear()
    await r.call("change_tool", slot=2)
    heat = next(i for i, line in enumerate(p.gcode_log) if line.startswith("M109 S") and float(line[6:]) > 150)
    assert heat < next(i for i, line in enumerate(p.gcode_log) if line.startswith("G1 E"))
    assert (await r.call("state"))["result"]["change"] is None


async def test_a_failed_change_answered_in_time_leaves_the_nozzle_hot(quick_to_cool):
    r = quick_to_cool
    p = r.printer
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=7")
    await until(lambda: r.svc.changer.error is not None and r.svc.changer.going is None, 20)
    await r.call("change_tool", slot=2)
    await asyncio.sleep(0.6)
    assert "M104 S150" not in p.gcode_log


async def test_cancel_during_a_change_stops_the_unit(slot1_in_head):
    r = slot1_in_head
    p = r.printer
    p.start_print()
    await p.run_gcode("ELYIR_TOOL T=3")
    await until(lambda: r.svc.changer.step == "in", 15)
    await p.run_gcode("CANCEL_PRINT")
    await until(lambda: r.svc.changer.going is None, 5)
    assert r.svc.changer.error == "The print was stopped during the tool change."
    await asyncio.sleep(0.2)
    assert r.ace.motion is None and "RESUME_BASE" not in p.gcode_log


async def test_a_switch_right_after_a_load_turns_feed_assist_off_before_pulling(empty_head):
    r = empty_head
    await r.call("change_tool", slot=2)
    assert r.ace.assist == 2
    assert (await r.call("change_tool", slot=0)) == {"id": r.rid, "result": {}}
    methods = [m["method"] for m in r.moves()]
    second = methods[methods.index("start_feed_assist") + 1:]
    assert second.index("stop_feed_assist") < second.index("unwind_filament")
    assert r.printer.x[2] < SENSOR_AT and r.printer.x[0] >= SENSOR_AT + GRIP + NOZZLE - 10 and r.ace.assist == 0


async def test_the_nozzle_heats_for_the_hotter_of_the_two_materials(slot1_in_head):
    r = slot1_in_head
    await r.call("set_spool", slot=1, color="#FFFFFF", material="ABS")
    await r.call("set_spool", slot=3, color="#00FF00", material="PLA")
    await r.call("change_tool", slot=3)
    assert r.printer.gcode_log[0] == "BEFORE_CHANGE FROM=1 TO=3 TEMP=250 PURGE=1"
    assert "M109 S250" in r.printer.gcode_log


async def test_a_unit_that_goes_quiet_mid_change_ends_it_with_an_answer(empty_head):
    r = empty_head

    async def quiet():
        await until(lambda: r.svc.changer.step == "in", 10)
        r.ace.silent = True
    asyncio.ensure_future(quiet())
    reply = await r.call("change_tool", slot=2, timeout=40)
    assert "error" in reply and r.svc.changer.going is None
    r.ace.silent = False


async def test_feed_assist_is_off_before_the_extruder_pulls_back(empty_head):
    r = empty_head
    await r.call("change_tool", slot=2)
    assert r.ace.assist == 2
    await r.call("change_tool", slot=0)
    assert r.printer.buckled == [], "the extruder pulled the filament back while feed assist pushed it"
    assert r.printer.x[2] < SENSOR_AT and r.printer.x[0] >= SENSOR_AT + GRIP + NOZZLE - 10


async def test_feed_assist_is_off_before_the_printers_own_macro_pulls_back_for_the_tip_cut(empty_head):
    r = empty_head
    r.printer.before_retract = 20
    await r.call("change_tool", slot=2)
    assert r.ace.assist == 2
    await r.call("change_tool", slot=0)
    assert r.printer.buckled == [], "the tip cut pulled the filament back while feed assist pushed it"


@pytest.fixture
async def with_purge_moves(tmp_path):
    r = Rig(tmp_path, settings={"purge_moves": "70,348 25,349", "push_start": "SET_PIN PIN=goose_belt VALUE=0.5",
                                "push_end": "SET_PIN PIN=goose_belt VALUE=0"})
    await r.start()
    yield r
    await r.stop()


async def test_filament_is_pushed_into_the_nozzle_only_at_the_purge_spot(with_purge_moves):
    r = with_purge_moves
    await r.call("change_tool", slot=2)
    assert r.printer.pushed_at and set(r.printer.pushed_at) == {(25.0, 349.0)}
    i = r.printer.gcode_log.index("G1 X25 Y349 F3000")
    assert r.printer.gcode_log[i - 1] == "G1 X70 Y348 F3000" and any(l.startswith("G1 E120") for l in r.printer.gcode_log[i:])


async def test_push_more_through_goes_to_the_purge_spot_first(with_purge_moves):
    r = with_purge_moves
    assert (await r.call("purge", mm=30, temp=240)) == {"id": r.rid, "result": {}}
    log = r.printer.gcode_log
    assert log.index("M109 S240") < log.index("G1 X25 Y349 F3000") < log.index("G1 E30 F150")
    assert r.printer.pushed_at[-1] == (25.0, 349.0)


async def test_the_belt_runs_while_filament_is_pushed_into_the_nozzle(with_purge_moves):
    r = with_purge_moves
    await r.call("change_tool", slot=2)
    await r.call("purge", mm=30)
    log = r.printer.gcode_log
    for push in ("G1 E120", "G1 E30 "):
        i = next(n for n, line in enumerate(log) if line.startswith(push))
        assert log[i - 2] == "SET_PIN PIN=goose_belt VALUE=0.5" and log[i + 2] == "SET_PIN PIN=goose_belt VALUE=0"


@pytest.fixture
async def with_a_cutter(tmp_path):
    r = Rig(tmp_path, loaded=1, settings={"backoff": 0})
    await r.start()
    yield r
    await r.stop()


@pytest.fixture
async def cut_below_the_gears(tmp_path):
    r = Rig(tmp_path, loaded=1, settings={"backoff": 50})
    await r.start()
    yield r
    await r.stop()


async def test_a_cut_below_the_gears_backs_out_while_the_unit_pulls(cut_below_the_gears):
    r = cut_below_the_gears
    r.printer.x[1] = SENSOR_AT + GRIP + 20    # cut: the end sits under the gears, which still hold it
    await r.call("change_tool", slot=3)
    assert r.printer.buckled == [], "the extruder pushed the filament back up while the unit held it"
    assert any(line.startswith("G1 E-50 ") for line in r.printer.gcode_log)
    assert r.printer.x[1] < SENSOR_AT and r.printer.x[3] >= SENSOR_AT + GRIP + NOZZLE - 10


async def test_with_a_cutter_the_extruder_never_backs_off_and_the_unit_pulls_it_clear(with_a_cutter):
    r = with_a_cutter
    r.printer.x[1] = SENSOR_AT + GRIP / 2    # cut: the free tip sits past the sensor, above the gears
    await r.call("change_tool", slot=3)
    assert not any(line.startswith("G1 E-") for line in r.printer.gcode_log)
    assert r.printer.x[1] < SENSOR_AT and r.printer.x[3] >= SENSOR_AT + GRIP + NOZZLE - 10
