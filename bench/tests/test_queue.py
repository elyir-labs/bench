"""The Bench Box's queue (bench_queue.py, design/bench-queue/ Queue A) against the real slicing service with the slicer
tests' stand-in Orca, and printers whose intent says whether they're free and what they have loaded."""
import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import FormData, web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "slicer"))
sys.path.insert(0, str(ROOT / "slicer" / "tests"))
import bench_queue as Q  # noqa: E402
import bench_service as B  # noqa: E402
import slice_service as S  # noqa: E402
from test_slice import DESK_PROFILE, FAKE_ORCA, PrinterMoonraker  # noqa: E402

WHITE = "#F4F4F2"


class Printer(PrinterMoonraker):
    """A printer with its slicing profile, its intent (free or not, what's loaded), its spool check and its buttons."""
    def __init__(self, state="ready", spools=None):
        super().__init__(DESK_PROFILE)
        self.intent = {"state": state, "spools": spools if spools is not None else [{"slot": 0, "material": "ASA", "color": WHITE, "status": "ready", "direct": True}]}
        self.check = {"ok": True}
        self.actions = []

    def app(self):
        app = super().app()
        async def intent(r):
            return web.json_response({"result": self.intent})
        async def check(r):
            return web.json_response({"result": {**self.check, "filename": r.query["filename"]}})
        async def action(r):
            self.actions.append(await r.json())
            return web.json_response({"result": {"intent": self.intent}})
        app.router.add_get("/printer/intent", intent)
        app.router.add_get("/printer/intent/check_print", check)
        app.router.add_post("/printer/intent/action", action)
        return app


def write(root: Path, rel: str, d: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client):
    system = tmp_path / "system"
    write(system, "Voron/machine/base.json", {"name": "Voron base", "printable_area": ["0x0", "350x0", "350x350", "0x350"],
                                              "machine_start_gcode": "PRINT_START TOOL=[initial_tool]"})
    write(system, "Voron/machine/v24.json", {"name": "Voron 2.4 350", "inherits": "Voron base", "nozzle_diameter": ["0.4"]})
    write(system, "Voron/process/std.json", {"name": "0.20mm Standard @Voron", "layer_height": "0.2", "wall_loops": "3",
                                             "sparse_infill_density": "15%", "top_shell_layers": "4", "bottom_shell_layers": "3",
                                             "enable_support": "0", "support_type": "normal(auto)", "compatible_printers": ["Voron 2.4 350"]})
    write(system, "Voron/filament/asa.json", {"name": "Generic ASA", "filament_type": ["ASA"], "hot_plate_temp": ["110"]})
    orca = tmp_path / "orca"
    orca.write_text(FAKE_ORCA)
    orca.chmod(orca.stat().st_mode | stat.S_IEXEC)
    slicer = S.Service({"orca": [sys.executable, str(orca)], "nice": 0, "profiles": [str(system)], "lend": True,
                        "allow": "anyone", "printers": {}}, str(tmp_path / "work"))
    sserver = await aiohttp_server(slicer.app())
    desk, workshop = Printer("ready"), Printer("printing")
    s3, s1 = await aiohttp_server(desk.app()), await aiohttp_server(workshop.app())
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], slicer=str(sserver.make_url("")))
    bench.printers = {pid: {"name": {"desk": "Desk", "workshop": "Workshop"}[pid], "host": "127.0.0.1", "port": 1, "moonraker_port": s.port, "home": "http://127.0.0.1:9", "token": "t"}
                      for pid, s in (("desk", s3), ("workshop", s1))}
    client = await aiohttp_client(bench.app())
    form = FormData()
    form.add_field("model", b"solid x\nendsolid x\n", filename="cable_clip.stl")
    model = await (await client.post("/bench/shelf", data=form)).json()

    class R: pass
    r = R()
    r.client, r.q, r.desk, r.workshop, r.model, r.slicer = client, bench.queue, desk, workshop, model, slicer
    return r


async def settle(r, tries=60):
    """The box's looks, until nothing is being set up."""
    for _ in range(tries):
        await r.q.look()
        if not any(it["state"] == "setting" for it in r.q.items):
            return await (await r.client.get("/bench/queue")).json()
        await asyncio.sleep(0.05)
    raise AssertionError("still setting up")


async def add(r, copies=1, material="ASA", color=WHITE):
    resp = await r.client.post("/bench/queue", json={"shelf": r.model["id"], "copies": copies, "material": material, "color": color})
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def test_a_queued_print_goes_to_the_free_printer_with_its_filament_and_starts_once_the_bed_is_clear(rig):
    await add(rig)
    q = await settle(rig)
    assert [(i["name"], i["state"], i["printer"], i["line"]) for i in q] == [
        ("Cable clip", "ready", "desk", "White ASA · Desk is free: clear its bed")]          # never the busy Workshop
    assert not rig.desk.uploads                                                            # nothing on Desk until someone says
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start")
    assert r.status == 200, await r.text()
    assert len(rig.desk.uploads) == 1 and rig.desk.actions == [{"action": "start_file", "args": {"filename": rig.desk.uploads[0]["name"]}}]
    assert await (await rig.client.get("/bench/queue")).json() == []
    assert (await (await rig.client.get("/bench/shelf")).json())[0]["last"]["printer"] == "desk"


async def test_a_filament_nobody_has_loaded_waits_and_says_so(rig):
    await add(rig, material="PETG", color="#2563EB")
    q = await settle(rig)
    assert [(i["state"], i["line"]) for i in q] == [("waiting", "Blue PETG · waits: no printer has it loaded")]


async def test_a_printer_that_gets_busy_lets_its_queued_print_go_back_to_waiting(rig):
    await add(rig)
    q = await settle(rig)
    rig.desk.intent["state"] = "printing"                   # someone started something on Desk meanwhile
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start")
    assert r.status == 409 and "isn't free any more" in (await r.json())["error"]
    assert not rig.desk.uploads and not rig.desk.actions
    q = await settle(rig)
    assert [(i["state"], i["printer"]) for i in q] == [("waiting", None)]
    rig.desk.intent["state"] = "finished"                   # free once its bed is cleared: it can take it again
    assert [(i["state"], i["printer"]) for i in await settle(rig)] == [("ready", "desk")]


async def test_the_order_is_the_persons(rig):
    a, b = await add(rig), await add(rig, copies=2)
    r = await rig.client.put("/bench/queue", json=[b["id"], a["id"]])
    assert [i["id"] for i in await r.json()] == [b["id"], a["id"]]
    q = await settle(rig)
    assert [(i["copies"], i["state"]) for i in q] == [(2, "ready"), (1, "waiting")]     # one free printer: the first goes
    assert (await rig.client.put("/bench/queue", json=[a["id"]])).status == 409
    assert (await rig.client.delete(f"/bench/queue/{b['id']}")).status == 200
    assert [(i["id"], i["state"]) for i in await settle(rig)] == [(a["id"], "ready")]


async def test_copies_that_dont_fit_one_bed_wait_behind_for_the_next_free_printer(rig):
    await add(rig, copies=30)                               # the stand-in Orca puts 25 on a plate
    q = await settle(rig)
    assert [(i["copies"], i["state"], i["printer"]) for i in q] == [(25, "ready", "desk"), (5, "waiting", None)]


async def test_the_printers_own_check_can_refuse_and_be_overruled(rig):
    await add(rig)
    q = await settle(rig)
    rig.desk.check = {"ok": False, "headline": "This needs white ASA.", "detail": "Slot 1 has white PLA."}
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start")
    assert r.status == 409 and (await r.json())["refused"]["headline"] == "This needs white ASA."
    assert not rig.desk.actions
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start", json={"anyway": True})
    assert r.status == 200 and len(rig.desk.uploads) == 1 and len(rig.desk.actions) == 1   # sent once, started once


async def test_a_queued_print_is_set_up_the_way_the_model_prints_as_it_stands_then(rig):
    rig.desk.db[("elyir-bench", "slice_usual")] = {"supports": "tree", "purposes": {"strong": {"sparse_infill_density": "40%"}}}
    await add(rig)
    how = {"purpose": "strong", "supports": None, "brim": "ears", "settings": {"wall_loops": "4"}}
    r = await rig.client.put(f"/bench/shelf/{rig.model['id']}/how", json=how)       # changed after it was queued
    assert r.status == 200, await r.text()
    q = await settle(rig)
    job = rig.slicer.jobs[rig.q.items[0]["job"]]
    assert (job.req.purpose, job.req.supports, job.req.kept, job.req.settings) == \
        ("strong", "tree", {"sparse_infill_density": "40%"}, {"wall_loops": "4"})
    assert [p.brim for p in job.parts] == ["ears"]
    assert (await rig.client.post(f"/bench/queue/{q[0]['id']}/start")).status == 200
    assert (await (await rig.client.get("/bench/shelf")).json())[0]["last"]["how"] == how


def test_a_copy_of_the_model_is_one_of_each_of_its_parts():
    job = {"plates": [{"counts": [10, 20]}, {"counts": [2, 4]}], "parts": [{"copies": 12}, {"copies": 24}]}
    assert Q.fits_first_bed(job, 12) == 10
    assert Q.fits_first_bed({"plates": [{"counts": [5]}]}, 5) == 5
    assert Q.color_name("#F2F2F0") == "White" and Q.color_name(None) == ""


async def test_a_printer_whose_one_spool_nobody_described_takes_it_and_asks_at_the_start(rig):
    rig.desk.intent["spools"] = [{"slot": 0, "material": None, "color": None, "status": "unknown", "direct": True}]   # a Kobra just added
    await add(rig, material="ASA", color=WHITE)
    q = await settle(rig)
    assert [(i["state"], i["printer"]) for i in q] == [("ready", "desk")]
    rig.desk.check = {"ok": False, "ask": True, "headline": "This file uses White ASA. Is that what's loaded?",
                      "actions": [{"id": "confirm_spool", "label": "Yes, print", "args": {"filename": "x", "color": WHITE, "material": "ASA"}}]}
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start")
    assert r.status == 409 and (await r.json())["refused"]["ask"] is True and not rig.desk.actions
    r = await rig.client.post(f"/bench/queue/{q[0]['id']}/start", json={"confirm": True})
    assert r.status == 200 and rig.desk.actions == [{"action": "confirm_spool", "args": {"filename": "x", "color": WHITE, "material": "ASA"}}]
    assert len(rig.desk.uploads) == 1                                        # sent once
