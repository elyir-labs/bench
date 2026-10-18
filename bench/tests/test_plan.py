"""Several models from the Bench Box's shelf at once (bench/plan.py, design/bench-several/ C): the plan's rules on their
own, then the plan against the real slicing service with the slicer tests' stand-in Orca (25 on a plate), into the queue
as beds, and from away."""
import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import FormData

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "slicer"))
sys.path.insert(0, str(ROOT / "slicer" / "tests"))
import bench_service as B  # noqa: E402
import doors as DR  # noqa: E402
import plan as P  # noqa: E402
import slice_service as S  # noqa: E402
from test_queue import Printer, write  # noqa: E402
from test_slice import FAKE_ORCA, _boxes_stl  # noqa: E402

GRAY, WHITE, BLUE, BLACK = "#8A8D91", "#F4F4F2", "#2563EB", "#1C1C1E"
HOW = {"purpose": "everyday", "supports": None, "brim": None, "settings": {}}


def spool(slot, material, color, direct=False):
    return {"slot": slot, "material": material, "color": color, "status": "ready", "direct": direct}


# ── the rules, with a fit given ──

def rows(**printers):
    """name=(state, spools) → the plan's printer rows, every printer able to print PLA, PETG and ASA."""
    intents = {pid.lower(): {"state": st, "spools": sp, "job": {"remaining_s": 1800, "eta_clock": "7:40 pm"} if st == "printing" else None}
               for pid, (st, sp) in printers.items()}
    names = {pid.lower(): {"name": pid.replace("_", " ")} for pid in printers}
    joined = {pid: {"entry": {"materials": ["PLA", "PETG", "ASA"]}} for pid in intents}
    return P.printer_rows(names, intents, joined, set())


def model(name, copies=1, material="PETG", color=GRAY, **kw):
    return {"shelf": name.lower().replace(" ", "")[:12], "name": name, "copies": copies, "picture": None,
            "filament": {"material": material, "color": color, "filament": None, "filament_name": None} if material else None,
            "how": {**HOW, **kw.pop("how", {})}, "printer": kw.pop("printer", None), "own": kw.pop("own", False), "each": kw.pop("each", None)}


def roomy(pid, members):
    return {"counts": [n for _, n in members]}


def beds_of(p):
    return [(b["printer"], [(m["name"], m["copies"]) for m in b["models"]]) for b in p["beds"]]


SCENE = dict(Workshop=("ready", [spool(2, "PETG", GRAY)]), Kobra_3=("ready", [{"slot": 0, "status": "unknown", "direct": True}]),
             Kobra_3_2=("ready", [spool(0, "PETG", GRAY, True)]), Desk=("ready", [spool(0, "PETG", BLACK, True)]),
             Studio=("printing", [spool(0, "PLA", WHITE, True)]))


def test_the_drawn_plan_same_filament_shares_another_goes_elsewhere_busy_takes_it_next_nothing_loaded_waits():
    ms = [model("Phone stand", 2), model("Cable clips", 4), model("Battery tray", 1, "PLA", BLUE),
          model("Hinge", 6, "PLA", WHITE), model("Vent", 1, "ASA", BLACK)]
    p = P.plan(ms, rows(**SCENE), roomy, 1000.0)
    assert beds_of(p) == [("kobra_3_2", [("Phone stand", 2), ("Cable clips", 4)]), ("kobra_3", [("Battery tray", 1)]),
                          ("studio", [("Hinge", 6)]), (None, [("Vent", 1)])]
    tray, hinge, vent = p["beds"][1:]
    assert tray["asks"] and "put Blue PLA on" in tray["why"] and tray["when"]["kind"] == "now"
    assert hinge["when"] == {"kind": "next", "clock": "7:40 pm", "at": 1000.0 + 1800}
    assert vent["when"]["kind"] == "waits" and vent["why"].startswith("Black ASA isn't loaded on any printer")
    assert [f["name"] for f in p["free_left"]] == ["Desk", "Workshop"] and p["printers"] == 3 and p["cant"] == []


def test_too_much_for_one_bed_goes_to_another_free_printer_with_it_else_a_second_bed_after():
    def fit(pid, members):                                  # the stands and 22 clips fit one bed
        left, out = 24, []
        for m, n in members:
            out.append(min(n, left))
            left -= out[-1]
        return {"counts": out}
    ms = [model("Phone stand", 2), model("Cable clips", 30)]
    p = P.plan(ms, rows(Workshop=SCENE["Workshop"], Kobra_3_2=SCENE["Kobra_3_2"]), fit, 0.0)
    assert beds_of(p) == [("kobra_3_2", [("Phone stand", 2), ("Cable clips", 22)]), ("workshop", [("Cable clips", 8)])]
    assert p["beds"][0]["split"] and p["beds"][0]["models"][1]["of"] == 30
    assert p["said"] == ["Not all of it fits one bed on Kobra 3 2: Cable clips × 8 go on Workshop, which has Gray PETG too."]
    p = P.plan(ms, rows(Workshop=SCENE["Workshop"]), fit, 0.0)                      # nobody else has it: a second bed on Workshop
    assert beds_of(p) == [("workshop", [("Phone stand", 2), ("Cable clips", 22)]), ("workshop", [("Cable clips", 8)])]
    assert [b["order"] for b in p["beds"]] == [1, 2] and p["beds"][1]["when"]["kind"] == "after"
    # Keep them all on Workshop: asked for a printer, the rest stays there
    p = P.plan([model("Phone stand", 2, printer="workshop"), model("Cable clips", 30, printer="workshop")],
               rows(Workshop=SCENE["Workshop"], Kobra_3_2=SCENE["Kobra_3_2"]), fit, 0.0)
    assert [b["printer"] for b in p["beds"]] == ["workshop", "workshop"]


def test_two_colors_both_on_one_unit_go_to_another_printer_with_it_first_else_a_second_bed():
    unit = ("ready", [spool(0, "PLA", WHITE), spool(2, "PETG", GRAY)])
    ms = [model("Stand", 1), model("Lid", 1, "PLA", WHITE)]
    p = P.plan(ms, rows(Workshop=unit, Desk=("printing", [spool(0, "PLA", WHITE, True)])), roomy, 0.0)
    assert beds_of(p) == [("workshop", [("Stand", 1)]), ("desk", [("Lid", 1)])]
    p = P.plan(ms, rows(Workshop=unit, Desk=("ready", [spool(0, "PETG", BLACK, True)])), roomy, 0.0)
    assert beds_of(p) == [("workshop", [("Stand", 1)]), ("workshop", [("Lid", 1)])]
    assert p["beds"][0]["why"] == "Gray PETG in slot 3." and p["beds"][1]["slot"] == 1


def test_different_purposes_supports_or_own_bed_never_share():
    ms = [model("Stand", 1), model("Clips", 4, how={"purpose": "strong"}), model("Hook", 1, how={"supports": "tree"}), model("Peg", 1, own=True)]
    p = P.plan(ms, rows(Workshop=SCENE["Workshop"]), roomy, 0.0)
    assert [(b["printer"], b["order"], b["purpose"], [m["name"] for m in b["models"]]) for b in p["beds"]] == [
        ("workshop", 1, "everyday", ["Stand"]), ("workshop", 2, "strong", ["Clips"]), ("workshop", 3, "everyday", ["Hook"]), ("workshop", 4, "everyday", ["Peg"])]


def test_a_bed_says_how_it_prints_and_a_brim_its_models_differ_on_is_mixed():
    """11 October 2026: each card's How it prints line shows what the box planned with. Brims don't split a bed (the
    slicer gives each model its own), so a bed whose models differ says mixed."""
    ms = [model("Stand", 1, how={"supports": "tree", "settings": {"wall_loops": "4"}}),
          model("Clips", 4, how={"supports": "tree", "settings": {"wall_loops": "4"}, "brim": "ears"})]
    p = P.plan(ms, rows(Workshop=SCENE["Workshop"]), roomy, 0.0)
    (b,) = p["beds"]
    assert (b["purpose"], b["supports"], b["settings"], b["brim"]) == ("everyday", "tree", {"wall_loops": "4"}, "mixed")
    p = P.plan([model("Stand", 1, how={"brim": "all"}), model("Clips", 4, how={"brim": "all"})], rows(Workshop=SCENE["Workshop"]), roomy, 0.0)
    assert p["beds"][0]["brim"] == "all"
    assert P.plan([model("Stand", 1)], rows(Workshop=SCENE["Workshop"]), roomy, 0.0)["beds"][0]["brim"] is None


def test_the_box_never_adds_copies_to_fill_a_bed():
    p = P.plan([model("Clip", 3)], rows(Workshop=SCENE["Workshop"]), lambda pid, m: {"counts": [200]}, 0.0)
    assert beds_of(p) == [("workshop", [("Clip", 3)])]


def test_a_model_never_printed_takes_the_first_loaded_filament_of_its_printer():
    unit = ("ready", [spool(3, "PETG", GRAY), spool(1, "PLA", WHITE)])
    p = P.plan([model("New", 1, material=None)], rows(Workshop=unit), roomy, 0.0)
    assert (p["beds"][0]["material"], p["beds"][0]["color"], p["beds"][0]["models"][0]["first"]) == ("PLA", WHITE, True)
    p = P.plan([model("New", 1, material=None, printer="desk")], rows(Workshop=unit, Desk=("finished", [spool(0, "ASA", BLACK, True)])), roomy, 0.0)
    assert (p["beds"][0]["printer"], p["beds"][0]["material"], p["beds"][0]["when"]["kind"]) == ("desk", "ASA", "clear")


def test_a_model_never_printed_takes_the_filament_loaded_on_the_most_printers():
    """10 October 2026: never-printed models all went to Desk in Black ASA, the first free printer by name, and every other
    printer was grayed out for them."""
    GREEN = "#00FF00"
    bench = rows(Desk=("ready", [spool(0, "ASA", BLACK, True)]), Workshop=("ready", [spool(0, "PETG", GREEN), spool(2, "PETG", GRAY)]),
                 Kobra_3=("ready", [spool(0, "PETG", GRAY, True)]), Kobra_3_2=("ready", [spool(0, "PETG", GRAY, True)]))
    p = P.plan([model("T1", 1, material=None), model("T2", 1, material=None)], bench, roomy, 0.0)
    assert [(b["printer"], b["material"], b["color"]) for b in p["beds"]] == [("kobra_3", "PETG", GRAY)]
    p = P.plan([model("T1", 1, material=None, printer="workshop")], bench, roomy, 0.0)
    assert (p["beds"][0]["printer"], p["beds"][0]["color"], p["beds"][0]["slot"]) == ("workshop", GRAY, 3)


def test_a_printer_asked_for_that_cant_take_it_says_why():
    p = P.plan([model("Lid", 1, "PLA", WHITE, printer="desk")], rows(Desk=("ready", [spool(0, "PETG", BLACK, True)])), roomy, 0.0)
    assert p["beds"] == [] and p["cant"] == [{"shelf": "lid", "name": "Lid", "copies": 1, "why": "Desk has Black PETG, not White PLA."}]


def test_unknown_fits_are_assumed_and_rough_times_add_up():
    ms = [model("Stand", 2, each={"seconds": 600, "grams": 10}), model("Clip", 4, each={"seconds": 300, "grams": 2})]
    p = P.plan(ms, rows(Workshop=SCENE["Workshop"]), lambda pid, m: None, 1000.0)
    b = p["beds"][0]
    assert (b["fits"], b["seconds"], b["grams"], b["start_at"], b["done_at"], p["done_at"]) == (None, 2400, 28, 1000.0, 3400.0, 3400.0)
    p = P.plan([model("Stand", 2), model("Clip", 4, each={"seconds": 300})], rows(Workshop=SCENE["Workshop"]), roomy, 0.0)
    assert (p["beds"][0]["seconds"], p["beds"][0]["done_at"]) == (None, None)       # one model never timed: no guess


# ── on the box, against the real slicer ──

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
    workshop = Printer("ready", [spool(0, "ASA", WHITE), spool(2, "PETG", GRAY)])
    desk = Printer("printing", [spool(0, "ASA", WHITE, True)])
    unit = json.loads(workshop.files["elyir-bench-slicer/printer.json"][0])
    workshop.files["elyir-bench-slicer/printer.json"][0] = json.dumps({**unit, "machine": "Desk", "tools": 4}).encode()   # Workshop has a unit
    s1, s3 = await aiohttp_server(workshop.app()), await aiohttp_server(desk.app())
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], slicer=str(sserver.make_url("")))
    bench.printers = {pid: {"name": pid.upper(), "host": "127.0.0.1", "port": 1, "moonraker_port": s.port, "home": "http://127.0.0.1:9", "token": "t"}
                      for pid, s in (("workshop", s1), ("desk", s3))}
    bench.doors.relay(DR.BOX).save({"name": "bench", "address": "bench.elyir.app", "secret": "s", "addr": "a", "token": "t"})
    client = await aiohttp_client(bench.app())
    away = await aiohttp_client(bench.away.app())
    ids = {}
    for name, material, color in (("phone_stand.stl", "PETG", GRAY), ("cable_clips.stl", "PETG", GRAY), ("cap.stl", "ASA", WHITE)):
        form = FormData()
        form.add_field("model", b"solid x\nendsolid x\n", filename=name)
        it = await (await client.post("/bench/shelf", data=form)).json()
        saved = bench.shelf.item(it["id"])
        saved["last"] = {"printer": "workshop", "printer_name": "Workshop", "copies": 1, "material": material, "color": color, "at": 1.0}
        bench.shelf.save(saved)
        ids[it["name"]] = it["id"]

    class R: pass
    r = R()
    r.client, r.away, r.bench, r.q, r.workshop, r.desk, r.ids, r.slicer = client, away, bench, bench.queue, workshop, desk, ids, slicer
    return r


async def settle(r, tries=80):
    for _ in range(tries):
        await r.q.look()
        if not any(it["state"] == "setting" for it in r.q.items):
            return await (await r.client.get("/bench/queue")).json()
        await asyncio.sleep(0.05)
    raise AssertionError("still setting up")


async def test_the_plan_checks_each_bed_fits_on_the_slicer_and_says_so_while_it_works(rig):
    want = {"models": [{"shelf": rig.ids["Phone stand"], "copies": 2}, {"shelf": rig.ids["Cable clips"], "copies": 4},
                       {"shelf": rig.ids["Cap"], "copies": 1}]}
    first = await (await rig.client.post("/bench/plan", json=want)).json()
    assert first["checking"] is True and {b["fits"] for b in first["beds"]} == {None}
    p = await (await rig.client.post("/bench/plan", json={**want, "wait": True})).json()
    assert p["checking"] is False and beds_of(p) == [("workshop", [("Phone stand", 2), ("Cable clips", 4)]), ("desk", [("Cap", 1)])]
    assert [b["fits"] for b in p["beds"]] == [True, True]
    assert p["beds"][1]["when"]["kind"] == "next"                           # Desk is printing: it takes the cap next
    assert len(rig.bench.plan.fits) == 2 and not rig.bench.plan.checks
    again = await (await rig.client.post("/bench/plan", json=want)).json()  # a re-plan asks the slicer nothing new
    assert again["checking"] is False and not rig.bench.plan.checks


async def test_a_filament_chosen_in_the_plan_wins_over_the_last_one_and_shares_a_bed_in_it(rig):
    """10 October 2026: a model last printed in ASA could only go where ASA was loaded; In on the move sheet changes it."""
    want = {"wait": True, "models": [{"shelf": rig.ids["Phone stand"], "copies": 2},
                                     {"shelf": rig.ids["Cap"], "copies": 1, "in": {"material": "petg", "color": GRAY}}]}
    p = await (await rig.client.post("/bench/plan", json=want)).json()
    assert beds_of(p) == [("workshop", [("Phone stand", 2), ("Cap", 1)])]
    assert [(m["name"], m["chosen"]) for m in p["beds"][0]["models"]] == [("Phone stand", False), ("Cap", True)]
    assert p["beds"][0]["material"] == "PETG"


async def test_too_many_for_one_bed_is_split_by_what_the_slicer_says_fits(rig):
    want = {"models": [{"shelf": rig.ids["Phone stand"], "copies": 2}, {"shelf": rig.ids["Cable clips"], "copies": 30}], "wait": True}
    p = await (await rig.client.post("/bench/plan", json=want)).json()
    assert beds_of(p) == [("workshop", [("Phone stand", 2), ("Cable clips", 23)]), ("workshop", [("Cable clips", 7)])]   # 25 on a plate
    assert p["said"] == ["Not all of it fits one bed on Workshop: Cable clips × 7 go on a second bed there, after the first."]


async def test_bad_plans_are_said(rig):
    assert (await rig.client.post("/bench/plan", json={"models": []})).status == 400
    assert (await rig.client.post("/bench/plan", json={"models": [{"shelf": rig.ids["Cap"], "copies": 201}]})).status == 400
    p = await (await rig.client.post("/bench/plan", json={"models": [{"shelf": "0" * 12}, {"shelf": rig.ids["Cap"], "out": True}]})).json()
    assert p["cant"][0]["why"] == "It's no longer on the shelf." and p["out"] == [{"shelf": rig.ids["Cap"], "name": "Cap"}]


async def test_print_all_puts_each_bed_at_the_end_of_up_next_sliced_together_and_each_model_remembers(rig):
    single = await rig.client.post("/bench/queue", json={"shelf": rig.ids["Cap"], "copies": 1, "material": "ASA", "color": WHITE})
    assert single.status == 201
    p = await (await rig.client.post("/bench/plan", json={"wait": True, "models": [
        {"shelf": rig.ids["Phone stand"], "copies": 2}, {"shelf": rig.ids["Cable clips"], "copies": 4}, {"shelf": rig.ids["Cap"], "copies": 3}]})).json()
    r = await rig.client.post("/bench/plan/print", json={"beds": p["beds"]})
    assert r.status == 201, await r.text()
    queued = (await r.json())["queued"]
    assert [(i["name"], i["on"], i["copies"]) for i in queued] == [("Phone stand × 2, Cable clips × 4", "workshop", 6), ("Cap × 3", "desk", 3)]
    q = await settle(rig)
    assert [i["id"] for i in q][1:] == [i["id"] for i in queued]                  # after what was already waiting
    assert [i["bed"] for i in q] == [False, True, True]                         # a bed's name is ready to show
    # Workshop is the only free one and the cap queued before goes first; the beds wait for the printers the plan gave them
    assert [(i["state"], i["printer"]) for i in q] == [("ready", "workshop"), ("waiting", None), ("waiting", None)]
    assert [i["line"] for i in q[1:]] == ["Gray PETG · Workshop's next, after the bed before it", "White ASA · Desk's next, after its print"]
    assert (await rig.client.delete(f"/bench/queue/{q[0]['id']}")).status == 200
    q = [{"id": "gone"}] + await settle(rig)
    assert [(i["state"], i["printer"]) for i in q[1:]] == [("ready", "workshop"), ("waiting", None)]
    job = rig.slicer.jobs[rig.q.items[0]["job"]]
    assert [p.copies for p in job.parts] == [2, 4] and job.req.material == "PETG" and job.req.slot == 2
    assert q[1]["models"] == [{"shelf": rig.ids["Phone stand"], "name": "Phone stand", "copies": 2},
                              {"shelf": rig.ids["Cable clips"], "name": "Cable clips", "copies": 4}]
    r = await rig.client.post(f"/bench/queue/{q[1]['id']}/start")
    assert r.status == 200, await r.text()
    shelf = {it["name"]: it for it in await (await rig.client.get("/bench/shelf")).json()}
    assert [(shelf[n]["last"]["printer"], shelf[n]["last"]["copies"], shelf[n]["last"]["material"]) for n in ("Phone stand", "Cable clips")] == \
        [("workshop", 2, "PETG"), ("workshop", 4, "PETG")]


async def test_a_bed_that_doesnt_fit_where_it_goes_keeps_one_beds_worth_and_the_rest_waits_behind(rig):
    r = await rig.client.post("/bench/plan/print", json={"beds": [{"printer": "workshop", "material": "PETG", "color": GRAY, "models": [
        {"shelf": rig.ids["Phone stand"], "copies": 2}, {"shelf": rig.ids["Cable clips"], "copies": 30}]}]})
    assert r.status == 201
    q = await settle(rig)
    assert [(i["state"], [(m["name"], m["copies"]) for m in i["models"]]) for i in q] == [
        ("ready", [("Phone stand", 2), ("Cable clips", 23)]), ("waiting", [("Cable clips", 7)])]


async def test_a_bed_whose_printer_lost_its_filament_goes_to_whichever_has_it(rig):
    await rig.client.post("/bench/plan/print", json={"beds": [{"printer": "desk", "material": "ASA", "color": WHITE,
                                                              "models": [{"shelf": rig.ids["Cap"], "copies": 1}]}]})
    assert [(i["state"], i["on"]) for i in await settle(rig)] == [("waiting", "desk")]
    rig.desk.intent["spools"] = [spool(0, "PLA", BLUE, True)]
    assert [(i["state"], i["printer"], i["on"]) for i in await settle(rig)] == [("ready", "workshop", None)]


async def test_a_side_kept_with_a_model_is_how_the_plan_checks_its_fit_and_a_new_side_checks_again(rig, monkeypatch, tmp_path):
    """11 October 2026: which side down, picked on the box, is kept with the model; the plan's fit and its beds use it."""
    laid = []
    prepare = S._prepare
    monkeypatch.setattr(S, "_prepare", lambda parts, folder: laid.append([(p.lay, p.down) for p in parts]) or prepare(parts, folder))
    _boxes_stl(tmp_path / "mount.stl", [((0, 0, 0), (30, 20, 10))])
    form = FormData()
    form.add_field("model", (tmp_path / "mount.stl").read_bytes(), filename="mount.stl")
    sid = (await (await rig.client.post("/bench/shelf", data=form)).json())["id"]
    saved = rig.bench.shelf.item(sid)
    saved["last"] = {"printer": "workshop", "printer_name": "Workshop", "copies": 1, "material": "PETG", "color": GRAY, "at": 1.0}
    rig.bench.shelf.save(saved)
    want = {"wait": True, "models": [{"shelf": sid, "copies": 2}]}
    assert (await (await rig.client.post("/bench/plan", json=want)).json())["beds"][0]["fits"] is True
    assert laid == [[("file", None)]]
    side = [1.0, 0.0, 0.0]
    assert (await rig.client.put(f"/bench/shelf/{sid}/side", json={"part": 0, "lay": "side", "down": side})).status == 200
    p = await (await rig.client.post("/bench/plan", json=want)).json()
    assert p["beds"][0]["fits"] is True and laid[-1] == [("side", side)]
    r = await rig.client.post("/bench/plan/print", json={"beds": p["beds"]})
    assert r.status == 201
    await settle(rig)
    job = rig.slicer.jobs[rig.q.items[0]["job"]]
    assert [(p.lay, p.down, p.copies) for p in job.parts] == [("side", side, 2)]


# ── from away ──

async def phone(rig, name="Alex's iPhone"):
    code = (await (await rig.client.post("/bench/phones/code")).json())["code"]
    return {"Authorization": "Bearer " + (await (await rig.away.post("/door/pair", json={"code": code, "name": name})).json())["token"]}


async def test_a_phone_away_plans_and_adds_to_the_queue_a_guest_cant_and_nobody_away_starts(rig):
    h = await phone(rig)
    want = {"models": [{"shelf": rig.ids["Cap"], "copies": 1}], "wait": True}
    p = await rig.away.post("/bench/plan", json=want, headers=h)
    assert p.status == 200
    r = await rig.away.post("/bench/plan/print", json={"beds": (await p.json())["beds"]}, headers=h)
    assert r.status == 201, await r.text()
    it = (await r.json())["queued"][0]
    assert it["away"] is True and it["by"] == "Alex's iPhone"
    inv = await (await rig.away.post("/door/invites", json={"reach": "step_in"}, headers=h)).json()
    guest = (await (await rig.away.post("/door/join", json={"code": inv["code"], "name": "Jo"})).json())["token"]
    g = {"Authorization": f"Bearer {guest}"}
    assert (await rig.away.post("/bench/plan", json=want, headers=g)).status == 403
    assert (await rig.away.post("/bench/plan/print", json=want, headers=g)).status == 403
    assert len(rig.q.items) == 1
    await settle(rig)
    assert (await rig.away.post(f"/bench/queue/{it['id']}/start", json={"anyway": True}, headers=h)).status == 403
    assert not rig.workshop.actions
    assert all(getattr(x.handler, "__name__", "") != "post_start" for x in rig.away.app.router.routes())


async def test_a_model_printed_alone_gives_the_plan_a_rough_time_per_copy(rig):
    await rig.client.post("/bench/queue", json={"shelf": rig.ids["Cap"], "copies": 2, "material": "ASA", "color": WHITE})
    q = await settle(rig)
    assert (await rig.client.post(f"/bench/queue/{q[0]['id']}/start")).status == 200
    each = rig.bench.shelf.item(rig.ids["Cap"])["last"]["each"]
    assert each == {"seconds": 300.5, "grams": 2.5}                         # the stand-in: 10m1s and 5 g for two
    p = await (await rig.client.post("/bench/plan", json={"models": [{"shelf": rig.ids["Cap"], "copies": 3}]})).json()
    assert (p["beds"][0]["seconds"], p["beds"][0]["grams"], p["beds"][0]["rough"]) == (902, 7.5, True)
    # another side down since: no rough time, it could be hours longer
    kept = rig.bench.shelf.item(rig.ids["Cap"])
    kept["sides"] = {"0": {"lay": "file"}}
    rig.bench.shelf.save(kept)
    p = await (await rig.client.post("/bench/plan", json={"models": [{"shelf": rig.ids["Cap"], "copies": 3}]})).json()
    assert p["beds"][0]["seconds"] is None
