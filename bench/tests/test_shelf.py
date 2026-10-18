"""The Bench Box's shelf (bench/shelf.py, design/bench-print/ A) against the real slicing service (slicer/), with
the slicer tests' stand-in for Orca and a printer's Moonraker that holds its own profile, as Desk's does."""
import asyncio
import json
import shutil
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, FormData, web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "slicer"))
sys.path.insert(0, str(ROOT / "slicer" / "tests"))
import bench_service as B  # noqa: E402
import slice_service as S  # noqa: E402
from test_slice import DESK_PROFILE, FAKE_ORCA, PrinterMoonraker, _boxes_stl  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def write(root: Path, rel: str, d: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client):
    # Orca's own presets on the box, which Desk's frozen ones inherit from
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
    # the box's slicer: no printer of its own, lends to anyone (role: controller)
    slicer = S.Service({"orca": [sys.executable, str(orca)], "nice": 0, "profiles": [str(system)], "lend": True,
                        "allow": "anyone", "printers": {}}, str(tmp_path / "work"))
    sserver = await aiohttp_server(slicer.app())
    desk, kobra = PrinterMoonraker(DESK_PROFILE), PrinterMoonraker({})          # the Kobra has no slicing profile
    m3, mk = await aiohttp_server(desk.app()), await aiohttp_server(kobra.app())
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [], slicer=str(sserver.make_url("")))
    bench.printers = {"desk": {"name": "Desk", "host": "127.0.0.1", "port": 1, "moonraker_port": m3.port, "home": "http://127.0.0.1:9", "token": "t"},
                      "kobra3": {"name": "Kobra 3", "host": "127.0.0.1", "port": 1, "moonraker_port": mk.port, "home": "http://127.0.0.1:9", "token": "t"}}
    client = await aiohttp_client(bench.app())

    class R: pass
    r = R()
    r.client, r.bench, r.slicer, r.desk, r.work = client, bench, slicer, desk, tmp_path / "work"
    return r


def model(name="phone_stand.stl", body=b"solid x\nendsolid x\n"):
    form = FormData()
    form.add_field("model", body, filename=name)
    return form


async def done(client, jid):
    for _ in range(100):
        d = await (await client.get(f"/bench/slice/{jid}")).json()
        if d["state"] in ("done", "failed"):
            return d
        await asyncio.sleep(0.05)
    raise AssertionError("never set up")


async def test_a_model_added_is_kept_on_the_shelf_with_its_name_and_picture(rig):
    r = await rig.client.post("/bench/shelf", data=model())
    assert r.status == 201, await r.text()
    it = await r.json()
    assert (it["name"], it["file"], it["prints"], it["last"], it["picture"]) == ("Phone stand", "phone_stand.stl", 0, None, None)
    # the page that added it draws it, and the box keeps the picture
    assert (await rig.client.put(f"/bench/shelf/{it['id']}/picture", data=PNG)).status == 200
    assert (await rig.client.put(f"/bench/shelf/{it['id']}/picture", data=b"GIF89a")).status == 400
    shelf = await (await rig.client.get("/bench/shelf")).json()
    assert [(s["name"], s["picture"]) for s in shelf] == [("Phone stand", f"/bench/shelf/{it['id']}/picture")]
    assert await (await rig.client.get(shelf[0]["picture"])).read() == PNG
    # its part, as the slicer reads it, to draw
    assert (await rig.client.get(f"/bench/shelf/{it['id']}/parts/0")).status == 200


async def test_only_models_go_on_the_shelf(rig):
    r = await rig.client.post("/bench/shelf", data=model("notes.txt", b"hello"))
    assert r.status == 400 and "STL, OBJ, 3MF or STEP" in (await r.json())["error"]
    assert await (await rig.client.get("/bench/shelf")).json() == []


async def test_the_box_says_which_printers_it_can_set_a_model_up_for(rig):
    got = await (await rig.client.get("/bench/printable")).json()
    assert got["desk"]["materials"] == ["ASA", "PETG"] and got["desk"]["slots"] == 1
    assert "Kobra 3 can't slice here yet" in got["kobra3"]["error"]       # no profile on the printer: said, not hidden


async def test_set_up_for_a_printer_with_its_own_profile_sent_there_and_remembered(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "copies": 2, "material": "asa", "color": "#F4F4F2"})
    assert r.status == 202, await r.text()
    d = await done(rig.client, (await r.json())["id"])
    assert d["state"] == "done" and d["printer"] == "desk" and d["plates"][0]["counts"] == [2]
    # with Desk's own presets, not another printer's: the slicer joined Desk from its own Moonraker
    assert "desk" in rig.slicer.joined
    sent = await (await rig.client.post(f"/bench/slice/{d['id']}/send")).json()
    assert sent["sent"] and sent["printing"] is False                   # nothing starts: the page asks about the bed
    assert len(rig.desk.uploads) == 1 and rig.desk.uploads[0]["print"] is None
    shelf = await (await rig.client.get("/bench/shelf")).json()
    assert shelf[0]["prints"] == 1
    assert {k: shelf[0]["last"][k] for k in ("printer", "printer_name", "copies", "material")} == \
        {"printer": "desk", "printer_name": "Desk", "copies": 2, "material": "asa"}


async def test_a_setups_layers_come_through_the_box(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "copies": 1, "material": "asa"})
    d = await done(rig.client, (await r.json())["id"])
    layers = await rig.client.get(f"/bench/slice/{d['id']}/layers")
    assert layers.status == 200, await layers.text()
    got = await layers.json()
    assert set(got) == {"count", "z", "width", "walls"}
    if got["count"]:
        one = await (await rig.client.get(f"/bench/slice/{d['id']}/layers/0")).json()
        assert set(one) == {"count", "segs", "kinds"}
    assert (await rig.client.get(f"/bench/slice/{d['id']}/layers/{got['count']}")).status == 404
    assert (await rig.client.get(f"/bench/slice/{d['id']}/layers/x")).status == 404


async def test_the_last_printed_comes_first(rig):
    a = await (await rig.client.post("/bench/shelf", data=model("vent_plug.stl"))).json()
    b = await (await rig.client.post("/bench/shelf", data=model("bin-lid.stl"))).json()
    assert [s["name"] for s in await (await rig.client.get("/bench/shelf")).json()] == ["Bin lid", "Vent plug"]
    j = await (await rig.client.post(f"/bench/shelf/{a['id']}/slice", json={"printer": "desk", "material": "ASA"})).json()
    await done(rig.client, j["id"])
    await rig.client.post(f"/bench/slice/{j['id']}/send")
    assert [s["name"] for s in await (await rig.client.get("/bench/shelf")).json()] == ["Vent plug", "Bin lid"]
    assert (await rig.client.delete(f"/bench/shelf/{b['id']}")).status == 200
    assert [s["name"] for s in await (await rig.client.get("/bench/shelf")).json()] == ["Vent plug"]


async def test_a_model_the_slicer_has_let_go_of_is_given_to_it_again(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    shutil.rmtree(rig.work / "models")                                  # a day later, or the slicer restarted clean
    rig.slicer.models.clear()
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "material": "PETG"})
    assert r.status == 202, await r.text()
    assert (await done(rig.client, (await r.json())["id"]))["state"] == "done"


async def test_what_cant_be_set_up_is_said(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "kobra3", "material": "PLA"})
    assert r.status == 409 and "Kobra 3 can't slice here yet" in (await r.json())["error"]
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "material": "TPU"})
    assert r.status == 400 and (await r.json())["error"]                # Desk has no TPU preset: the slicer's words
    assert (await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"copies": 2})).status == 400
    assert (await rig.client.post("/bench/slice/abcdefabcdef/send")).status == 404


# ── models printed from a printer's own Print land on the shelf too (design/bench-shelf/, A) ──

STL = b"solid x\nendsolid x\n"
THUMB = b"\x89PNG\r\n\x1a\n" + b"thumb" * 8


def own_print(record: dict, models: dict, state: dict) -> web.Application:
    """Workshop as the box reaches it: its Moonraker (what it printed, the G-code's picture) and its nginx's /slice (its
    own slicer's models, a day). state["off"] makes it not answer."""
    async def item(r):
        if state.get("off"):
            return web.Response(status=503)
        return web.json_response({"result": {"namespace": "elyir-bench", "key": "sliced", "value": record}})
    async def meta(r):
        return web.json_response({"result": {"filename": r.query["filename"], "thumbnails": [
            {"width": 32, "height": 32, "relative_path": ".thumbs/small.png"}, {"width": 300, "height": 300, "relative_path": ".thumbs/big.png"}]}})
    async def thumb(r):
        state.setdefault("thumbs", []).append(r.match_info["path"])
        return web.Response(body=THUMB if r.match_info["path"].endswith("big.png") else b"\x89PNG\r\n\x1a\nsmall", content_type="image/png")
    async def model(r):
        mid = r.match_info["id"]
        state["fetched"] = state.get("fetched", 0) + 1
        return web.Response(body=models[mid]) if mid in models else web.Response(status=404, text="kept for a day")
    app = web.Application()
    app.router.add_get("/server/database/item", item)
    app.router.add_get("/server/files/metadata", meta)
    app.router.add_get("/server/files/gcodes/{path:.*}", thumb)
    app.router.add_get("/slice/models/{id}/file", model)
    return app


@pytest.fixture
async def workshop(rig, aiohttp_server):
    record = {"bracket_PETG_48m.gcode": {"parts": [{"model": "aaaaaaaaaaaa", "name": "bracket.stl", "scale": 1.0, "lay": "flat", "brim": "auto"}],
                                         "material": "PETG", "color": "#8A8D91", "slot": 2, "at": 1000.0},
              "plate/bushing_x25_1of2_ASA_2h26m.gcode": {"parts": [{"model": "bbbbbbbbbbbb", "name": "bushing.stl", "scale": 0.84, "lay": "file"},
                                                                   {"model": "cccccccccccc", "name": "pin.stl", "lay": "file"}],
                                                         "material": "ASA", "color": None, "slot": None, "at": 2000.0},
              "old_PLA_1h.gcode": {"parts": [{"model": "dddddddddddd", "name": "old.stl"}], "material": "PLA", "at": 500.0}}
    state: dict = {}
    s = await aiohttp_server(own_print(record, {"aaaaaaaaaaaa": STL, "bbbbbbbbbbbb": STL, "cccccccccccc": STL}, state))
    rig.bench.printers["workshop"] = {"name": "Workshop", "host": "127.0.0.1", "port": s.port, "moonraker_port": s.port, "home": "http://127.0.0.1:9", "token": "t"}
    rig.workshop = state
    return rig


async def test_a_model_printed_from_a_printers_own_print_lands_on_the_shelf(workshop):
    await workshop.bench.shelf.gather()
    shelf = await (await workshop.client.get("/bench/shelf")).json()
    assert [(s["name"], s["from"]["printer_name"], s["from"]["file"]) for s in shelf] == [
        ("Bushing", "Workshop", "plate/bushing_x25_1of2_ASA_2h26m.gcode"), ("Bracket", "Workshop", "bracket_PETG_48m.gcode")]
    bracket = shelf[1]
    assert {k: bracket["last"][k] for k in ("printer_name", "material", "color", "at")} == \
        {"printer_name": "Workshop", "material": "PETG", "color": "#8A8D91", "at": 1000.0}
    assert await (await workshop.client.get(bracket["picture"])).read() == THUMB          # the G-code's own, the biggest
    assert "plate/.thumbs/big.png" in workshop.workshop["thumbs"]                               # beside its file, in its folder
    # and from the shelf it prints on another printer, with its parts as the plate had them
    r = await workshop.client.post(f"/bench/shelf/{shelf[0]['id']}/slice", json={"printer": "desk", "material": "ASA"})
    assert r.status == 202, await r.text()
    d = await done(workshop.client, (await r.json())["id"])
    assert d["state"] == "done" and d["plates"][0]["counts"] == [1, 1]
    assert [(p["scale"], p["lay"]) for p in d["parts"]] == [(0.84, "file"), (1.0, "file")]


async def test_a_model_already_let_go_of_is_left_and_a_printer_thats_off_is_asked_again(workshop):
    workshop.workshop["off"] = True
    assert await workshop.bench.shelf.gather() == []
    workshop.workshop["off"] = False
    assert len(await workshop.bench.shelf.gather()) == 2                                  # the old one's model is gone: left
    fetched = workshop.workshop["fetched"]
    assert await workshop.bench.shelf.gather() == [] and workshop.workshop["fetched"] == fetched  # each plate looked at once


async def test_a_model_taken_off_the_shelf_doesnt_come_back(workshop):
    await workshop.bench.shelf.gather()
    shelf = await (await workshop.client.get("/bench/shelf")).json()
    await workshop.client.delete(f"/bench/shelf/{shelf[1]['id']}")
    again = B.Shelf(workshop.bench.shelf.root, workshop.bench.shelf.slicer, lambda: workshop.bench.printers)   # the box restarted
    async with ClientSession() as again.session:
        assert await again.gather() == []


async def test_the_boxs_own_print_isnt_added_twice(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    j = await (await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "material": "ASA"})).json()
    await done(rig.client, j["id"])
    await rig.client.post(f"/bench/slice/{j['id']}/send")
    assert rig.desk.db.get(("elyir-bench", "sliced"))                                    # Desk recorded it, as for any print
    assert await rig.bench.shelf.gather() == []
    assert len(await (await rig.client.get("/bench/shelf")).json()) == 1


# ── how a model prints, kept with it (design/bench-how/, A; docs/bench-how.md) ──

EVERYDAY = {"purpose": "everyday", "supports": None, "brim": None, "settings": {}}


async def put_how(client, sid, how):
    return await client.put(f"/bench/shelf/{sid}/how", json=how)


async def sliced(rig, sid, **want):
    """Set the model up for Desk; the slicer's own job, as the box asked for it."""
    r = await rig.client.post(f"/bench/shelf/{sid}/slice", json={"printer": "desk", "material": "ASA", **want})
    assert r.status == 202, await r.text()
    jid = (await r.json())["id"]
    return jid, rig.slicer.jobs[jid]


async def test_a_model_prints_everyday_until_its_how_is_changed_and_changes_merge(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    assert it["how"] == EVERYDAY
    assert (await (await rig.client.get("/bench/shelf")).json())[0]["how"] == EVERYDAY
    r = await put_how(rig.client, it["id"], {"purpose": "strong", "settings": {"wall_loops": "4", "layer_height": "0.16"}})
    assert r.status == 200, await r.text()
    assert (await r.json())["how"] == {"purpose": "strong", "supports": None, "brim": None,
                                       "settings": {"wall_loops": "4", "layer_height": "0.16"}}
    # only what's given changes; a setting set to null goes back to the printer's own
    r = await put_how(rig.client, it["id"], {"brim": "ears", "supports": "tree", "settings": {"layer_height": None}})
    assert (await r.json())["how"] == {"purpose": "strong", "supports": "tree", "brim": "ears", "settings": {"wall_loops": "4"}}
    r = await put_how(rig.client, it["id"], {"supports": None, "brim": None})
    kept = {"purpose": "strong", "supports": None, "brim": None, "settings": {"wall_loops": "4"}}
    assert (await r.json())["how"] == kept
    assert (await (await rig.client.get("/bench/shelf")).json())[0]["how"] == kept


async def test_a_how_that_cant_be_kept_is_said_in_words_and_nothing_changes(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    for bad, words in (({"purpose": "sturdy"}, "draft, everyday, display or strong"), ({"supports": "grid"}, "normal, tree, off"),
                       ({"brim": "corners"}, "auto, none, ears, all"), ({"settings": {"Wall-Loops": "4"}}, "lowercase"),
                       ({"settings": {"wall_loops": 4}}, "must be a string"), ({"settings": ["wall_loops"]}, "{key: value}"),
                       ({"colour": "red"}, "purpose, supports, brim and settings"), ([], "Send how it prints")):
        r = await put_how(rig.client, it["id"], bad)
        assert r.status == 400 and words in (await r.json())["error"], (bad, await r.text())
    r = await rig.client.put(f"/bench/shelf/{it['id']}/how", data=b"{not json")
    assert r.status == 400 and (await r.json())["error"]
    assert (await rig.client.put("/bench/shelf/abcdefabcdef/how", json={})).status == 404
    assert (await (await rig.client.get("/bench/shelf")).json())[0]["how"] == EVERYDAY


async def test_the_slicer_is_asked_for_the_models_how_over_the_printers_own(rig):
    rig.desk.db[("elyir-bench", "slice_usual")] = {"supports": "tree", "purposes": {
        "strong": {"sparse_infill_density": "40%", "wall_loops": "3"}, "draft": {"layer_height": "0.28"}}}
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    _, job = await sliced(rig, it["id"])
    # nothing chosen yet: everyday, Desk's usual supports, nothing kept for everyday, each part's own brim
    assert (job.req.purpose, job.req.supports, job.req.kept, job.req.settings) == ("everyday", "tree", {}, {})
    await put_how(rig.client, it["id"], {"purpose": "strong", "settings": {"wall_loops": "4"}})
    _, job = await sliced(rig, it["id"])
    assert (job.req.purpose, job.req.supports) == ("strong", "tree")
    assert job.req.kept == {"sparse_infill_density": "40%", "wall_loops": "3"}        # Desk's own "Yours" for strong
    assert job.req.settings == {"wall_loops": "4"}                                      # the model's own win over it
    await put_how(rig.client, it["id"], {"supports": "off"})
    _, job = await sliced(rig, it["id"])
    assert job.req.supports == "off"


async def test_supports_left_to_the_printer_fall_back_to_its_preset_then_normal(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    _, job = await sliced(rig, it["id"])
    assert job.req.supports == "normal"                       # nothing kept on Desk, its preset prints normal
    rig.bench.shelf.joined["desk"]["entry"]["supports"] = "tree"     # a printer whose process preset prints tree
    _, job = await sliced(rig, it["id"])
    assert job.req.supports == "tree"
    usual = await (await rig.client.get("/bench/usual/desk")).json()
    assert usual == {"supports": "tree", "purposes": {}}
    assert (await rig.client.get("/bench/usual/studio")).status == 404


async def test_the_printers_usual_is_looked_at_again_after_a_minute(rig):
    rig.desk.db[("elyir-bench", "slice_usual")] = {"supports": "tree", "purposes": {"everyday": {"wall_loops": "3"}}}
    assert await (await rig.client.get("/bench/usual/desk")).json() == {"supports": "tree", "purposes": {"everyday": {"wall_loops": "3"}}}
    rig.desk.db[("elyir-bench", "slice_usual")] = {"supports": "off", "purposes": {}}
    assert (await (await rig.client.get("/bench/usual/desk")).json())["supports"] == "tree"      # within the minute
    rig.bench.shelf.usuals["desk"]["at"] -= 61
    assert await (await rig.client.get("/bench/usual/desk")).json() == {"supports": "off", "purposes": {}}


async def test_a_printer_whose_moonraker_doesnt_answer_still_slices(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    await put_how(rig.client, it["id"], {"purpose": "strong"})
    await rig.bench.shelf._join("desk")
    rig.bench.printers["desk"]["moonraker_port"] = 9                   # nothing there: its usual can't be read
    jid, job = await sliced(rig, it["id"])
    assert (job.req.purpose, job.req.supports, job.req.kept) == ("strong", "normal", {})
    assert (await done(rig.client, jid))["state"] == "done"


async def test_the_brim_is_the_models_when_set_else_each_parts_own(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    kept = rig.bench.shelf.item(it["id"])
    kept["parts"][0]["brim"] = "none"                                  # as it last printed
    rig.bench.shelf.save(kept)
    _, job = await sliced(rig, it["id"])
    assert [p.brim for p in job.parts] == ["none"]
    await put_how(rig.client, it["id"], {"brim": "all"})
    _, job = await sliced(rig, it["id"])
    assert [p.brim for p in job.parts] == ["all"]


async def test_a_gathered_plates_parts_all_take_the_models_brim(workshop):
    await workshop.bench.shelf.gather()
    bushing = (await (await workshop.client.get("/bench/shelf")).json())[0]
    assert bushing["how"] == EVERYDAY                                   # gathered before it had a how: everyday
    await put_how(workshop.client, bushing["id"], {"brim": "ears"})
    _, job = await sliced(workshop, bushing["id"])
    assert [(p.brim, p.scale) for p in job.parts] == [("ears", 0.84), ("ears", 1.0)]


async def test_a_how_given_with_one_slice_is_for_that_slice_only(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    await put_how(rig.client, it["id"], {"purpose": "strong", "settings": {"wall_loops": "4"}})
    jid, job = await sliced(rig, it["id"], how={"purpose": "draft", "settings": {"wall_loops": None}})
    assert (job.req.purpose, job.req.settings) == ("draft", {})
    shelf = await (await rig.client.get("/bench/shelf")).json()
    assert shelf[0]["how"] == {"purpose": "strong", "supports": None, "brim": None, "settings": {"wall_loops": "4"}}
    r = await rig.client.post(f"/bench/shelf/{it['id']}/slice", json={"printer": "desk", "material": "ASA", "how": {"purpose": "fast"}})
    assert r.status == 400 and "draft, everyday, display or strong" in (await r.json())["error"]
    # what's sent is noted with the how it was sliced with
    await done(rig.client, jid)
    assert (await rig.client.post(f"/bench/slice/{jid}/send")).status == 200
    last = (await (await rig.client.get("/bench/shelf")).json())[0]["last"]
    assert last["how"] == {"purpose": "draft", "supports": None, "brim": None, "settings": {}}


async def test_what_was_sent_notes_the_models_how(rig):
    it = await (await rig.client.post("/bench/shelf", data=model())).json()
    await put_how(rig.client, it["id"], {"purpose": "display", "brim": "none"})
    jid, _ = await sliced(rig, it["id"])
    await done(rig.client, jid)
    await rig.client.post(f"/bench/slice/{jid}/send")
    # changed after it was sent: the note keeps what it printed with
    await put_how(rig.client, it["id"], {"purpose": "draft"})
    last = (await (await rig.client.get("/bench/shelf")).json())[0]["last"]
    assert last["how"] == {"purpose": "display", "supports": None, "brim": "none", "settings": {}}


async def test_the_box_passes_its_slicers_options_through(rig):
    got = await (await rig.client.get("/bench/slice-options")).json()
    assert [p["id"] for p in got["purposes"]] == ["draft", "everyday", "display", "strong"]
    assert all(p["label"] and p["summary"] for p in got["purposes"])
    assert any(e["key"] == "wall_loops" for e in got["editable"])


# ── which side down, kept with it (design/orientation/, the printer's own; on the box 11 October 2026) ──

def shape(tmp_path, name, boxes):
    _boxes_stl(tmp_path / name, boxes)
    return model(name, (tmp_path / name).read_bytes())


async def put_side(client, sid, **want):
    return await client.put(f"/bench/shelf/{sid}/side", json=want)


async def test_a_side_picked_is_kept_with_the_model_and_every_slice_lies_it_so(rig, tmp_path):
    """11 October 2026: "I still can't change the orientation of the model to be printed, or what side is laid
    down on the bed" on the Bench Box."""
    it = await (await rig.client.post("/bench/shelf", data=shape(tmp_path, "block.stl", [((0, 0, 0), (30, 20, 10))]))).json()
    got = await (await rig.client.get(f"/bench/shelf/{it['id']}/sides")).json()
    part = got["parts"][0]
    assert len(part["lying"]["sides"]) == 6 and (part["lay"], part["picked"], part["own"]["why"]) == ("file", False, "file")
    side = [1.0, 0.0, 0.0]
    r = await put_side(rig.client, it["id"], part=0, lay="side", down=side)
    assert r.status == 200, await r.text()
    part = (await r.json())["parts"][0]
    assert (part["lay"], part["down"], part["normal"], part["picked"]) == ("side", side, side, True)
    assert rig.bench.shelf.item(it["id"])["sides"] == {"0": {"lay": "side", "down": side}}
    _, job = await sliced(rig, it["id"])
    assert [(p.lay, p.down) for p in job.parts] == [("side", side)]
    # the slicer let go of the model: read again, and the side stays
    kept = rig.bench.shelf.item(it["id"])
    kept["uploaded"] = 0
    rig.bench.shelf.save(kept)
    _, job = await sliced(rig, it["id"])
    assert [(p.lay, p.down) for p in job.parts] == [("side", side)]
    # its own bottom again: the way it was, so nothing is kept
    part = (await (await put_side(rig.client, it["id"], part=0, lay="side", down=[0, 0, -2])).json())["parts"][0]
    assert (part["lay"], part["picked"]) == ("file", False) and rig.bench.shelf.item(it["id"])["sides"] == {}
    _, job = await sliced(rig, it["id"])
    assert [p.lay for p in job.parts] == ["file"]


async def test_a_part_on_its_edge_is_laid_flat_for_you_and_stands_if_picked(rig, tmp_path):
    it = await (await rig.client.post("/bench/shelf", data=shape(tmp_path, "mount.stl", [((0, 0, 0), (30, 3, 20))]))).json()
    part = (await (await rig.client.get(f"/bench/shelf/{it['id']}/sides")).json())["parts"][0]
    assert (part["lay"], part["picked"], part["own"]["why"]) == ("flat", False, "flat")
    assert part["normal"] == part["lying"]["flat_normal"]
    _, job = await sliced(rig, it["id"])
    assert [p.lay for p in job.parts] == ["flat"]
    part = (await (await put_side(rig.client, it["id"], part=0, lay="file")).json())["parts"][0]
    assert (part["lay"], part["picked"], part["normal"]) == ("file", True, None)
    _, job = await sliced(rig, it["id"])
    assert [p.lay for p in job.parts] == ["file"]
    part = (await (await put_side(rig.client, it["id"], part=0, lay="auto")).json())["parts"][0]
    assert (part["lay"], part["picked"]) == ("flat", False)


async def test_a_gathered_plates_parts_keep_their_own_way_until_one_is_picked(workshop):
    await workshop.bench.shelf.gather()
    bushing = (await (await workshop.client.get("/bench/shelf")).json())[0]
    parts = (await (await workshop.client.get(f"/bench/shelf/{bushing['id']}/sides")).json())["parts"]
    assert [(p["name"], p["lay"], p["own"]["why"]) for p in parts] == [("0-bushing.stl", "file", "plate"), ("1-pin.stl", "file", "plate")]
    # the stand-in models can't be measured, so only the file's bottom is known: a side can still be asked for by its normal
    r = await put_side(workshop.client, bushing["id"], part=1, lay="side", down=[0, 1, 0])
    assert r.status == 200, await r.text()
    _, job = await sliced(workshop, bushing["id"])
    assert [(p.lay, p.down, p.scale) for p in job.parts] == [("file", None, 0.84), ("side", [0.0, 1.0, 0.0], 1.0)]


async def test_a_side_that_cant_be_kept_is_said_in_words_and_nothing_changes(rig, tmp_path):
    it = await (await rig.client.post("/bench/shelf", data=shape(tmp_path, "step.stl", [((0, 0, 0), (30, 20, 10)), ((30, 0, 0), (60, 20, 5))]))).json()
    for want, words in (({"part": 3, "lay": "file"}, "It has 1 part"), ({"lay": "upside"}, "isn't a way down"),
                        ({"lay": "side"}, "outward normal"), ({"lay": "side", "down": [0, 0, 0]}, "outward normal"),
                        ({"lay": "side", "down": [1, 1, 0]}, "can't rest on that side")):
        r = await put_side(rig.client, it["id"], **want)
        assert r.status == 400 and words in (await r.json())["error"], want
    assert (await rig.client.put(f"/bench/shelf/{it['id']}/side", data=b"{no")).status == 400
    assert (await rig.client.put("/bench/shelf/abcdefabcdef/side", json={"lay": "file"})).status == 404
    assert "sides" not in rig.bench.shelf.item(it["id"])
