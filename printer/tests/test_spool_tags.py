"""Spool tags (design/spool-tags/): hold a tag and it asks (round 1 C); the tag picks the format, Change offers the
rest (5 A); the library is SpoolmanDB on the printer (6 A)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import filament_library as lib  # noqa: E402
import spool_tags as st  # noqa: E402
import tag_formats as f  # noqa: E402
import tag_reader as r  # noqa: E402

SLOTS = [{"slot": 0, "name": "Green PETG", "color": "#2FC46A", "material": "PETG", "rfid": True, "status": "ready"},
         {"slot": 1, "name": "Orange PETG", "color": "#F07A2B", "material": "PETG", "rfid": False, "status": "ready"},
         {"slot": 2, "name": None, "color": None, "material": None, "rfid": False, "status": "empty"}]


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def flow(ace=True):
    clock = Clock()
    return st.SpoolTags(lambda: SLOTS, lambda: ace, clock), clock


def blank(chip="ntag213", uid=b"\x04\x01\x02\x03\x04\x05\x06"):
    return f.Tag(chip, uid, bytes(f.NTAG.get(chip, 320) if chip != "classic1k" else 48),
                 extra={"keyed": False} if chip == "classic1k" else None)


def run_write(t, reader):
    job = t.work()
    ok, why, tag = reader.write(job["uid"], job["ops"])
    t.on_written(ok, why, tag)


def test_a_blank_tag_asks_which_spool_with_the_untagged_slots_first():
    t, _ = flow()
    t.on_tag(blank())
    v = t.view()["sheet"]
    assert v["step"] == "which" and v["tag"]["chip"] == "NTAG213" and v["tag"]["blank"]
    assert [c["label"] for c in v["choices"]] == ["Orange PETG"]       # tagged and empty slots aren't offered


def test_picking_a_slot_writes_anycubic_on_an_ntag_where_there_is_an_ace_and_reads_back():
    t, _ = flow()
    reader = r.FakeReader()
    reader.put(blank())
    t.on_tag(reader.tag)
    t.input({"op": "pick", "slot": 1})
    v = t.view()["sheet"]
    assert v["step"] == "write" and v["format"] == "anycubic" and v["readers"] == "every ACE here reads it"
    t.input({"op": "write"})
    assert t.view()["sheet"]["writing"]
    run_write(t, reader)
    v = t.view()["sheet"]
    assert v["step"] == "written" and v["label"] == "Orange PETG" and v["color"] == "F07A2B"
    assert f.read(reader.tag)[0] == "anycubic"
    assert t.history[0]["material"] == "PETG" and t.dirty


def test_without_an_ace_an_ntag_gets_tigertag():
    t, _ = flow(ace=False)
    t.on_tag(blank())
    t.input({"op": "pick", "slot": 1})
    assert t.view()["sheet"]["format"] == "tigertag"


def test_the_tag_in_hand_picks_the_format():
    for chip, fmt in (("classic1k", "cfs"), ("slix2", "openprinttag")):
        t, _ = flow()
        t.on_tag(blank(chip))
        t.input({"op": "pick", "slot": 1})
        assert t.view()["sheet"]["format"] == fmt


def test_change_lists_every_format_with_why_not_and_the_pick_sticks_for_that_kind_of_tag():
    t, _ = flow()
    t.on_tag(blank())
    t.input({"op": "pick", "slot": 1})
    t.input({"op": "formats"})
    rows = {x["id"]: x for x in t.view()["sheet"]["formats"]}
    assert rows["anycubic"]["why_not"] is None and "NTAG215" in rows["openspool"]["why_not"]
    assert "MIFARE" in rows["cfs"]["why_not"] and "Bambu" in rows["bambu"]["why_not"]
    t.input({"op": "format", "format": "openspool"})                   # can't go on an NTAG213: ignored
    assert t.view()["sheet"]["step"] == "formats"
    t.input({"op": "format", "format": "tigertag"})
    assert t.view()["sheet"]["format"] == "tigertag" and t.choice_by_chip == {"ntag": "tigertag"}
    t2, _ = flow()
    t2.restore(t.saved())
    t2.on_tag(blank(uid=b"\x04" * 7))
    t2.input({"op": "pick", "slot": 1})
    assert t2.view()["sheet"]["format"] == "tigertag"


def test_a_written_tag_reads_back_and_its_sheet_closes_once_lifted():
    t, clock = flow()
    tag = r.apply_to_memory(blank(), f.encode("tigertag", {"brand": "Sunlu", "material": "PLA", "color": "123456"}, blank()))
    t.on_tag(tag)
    v = t.view()["sheet"]
    assert v["step"] == "read" and v["format_name"] == "TigerTag" and v["label"] == "Sunlu PLA"
    t.on_tag(None)
    clock.t += 2
    t.tick()
    assert (t.view() or {}).get("sheet") is None


def test_copy_onto_a_blank_tag_waits_for_one_then_writes_the_same_spool():
    t, _ = flow()
    reader = r.FakeReader()
    known = r.apply_to_memory(blank(), f.encode("anycubic", {"brand": "Elegoo", "material": "PLA+", "name": "Black",
                                                             "color": "111111"}, blank()))
    t.on_tag(known)
    t.input({"op": "copy"})
    assert t.view()["sheet"]["step"] == "copy"
    t.on_tag(None)
    reader.put(blank(uid=b"\x04\x09" * 3 + b"\x01"))
    t.on_tag(reader.tag)
    v = t.view()["sheet"]
    assert v["step"] == "write" and v["label"] == "Elegoo Black PLA+"
    t.input({"op": "write"})
    run_write(t, reader)
    assert t.view()["sheet"]["step"] == "written"


def test_not_now_leaves_that_tag_alone_until_it_is_lifted():
    t, _ = flow()
    t.on_tag(blank())
    t.input({"op": "close"})
    t.on_tag(blank())
    assert (t.view() or {}).get("sheet") is None
    t.on_tag(None)
    t.on_tag(blank())
    assert t.view()["sheet"]["step"] == "which"


def test_lifting_the_tag_before_write_asks_for_it_back():
    t, _ = flow()
    reader = r.FakeReader()
    reader.put(blank())
    t.on_tag(reader.tag)
    t.input({"op": "pick", "slot": 1})
    t.on_tag(None)
    t.input({"op": "write"})
    assert t.view()["sheet"]["waiting"] and t.work() is None
    t.on_tag(reader.tag)
    t.input({"op": "write"})
    run_write(t, reader)
    assert t.view()["sheet"]["step"] == "written"


def test_a_failed_write_says_why_and_can_try_again():
    t, _ = flow()
    reader = r.FakeReader()
    reader.put(blank())
    t.on_tag(reader.tag)
    t.input({"op": "pick", "slot": 1})
    t.input({"op": "write"})
    reader.fail_next = "Writing page 9 failed. The tag may be locked."
    run_write(t, reader)
    v = t.view()["sheet"]
    assert v["step"] == "failed" and "locked" in v["why"]
    t.input({"op": "write"})
    run_write(t, reader)
    assert t.view()["sheet"]["step"] == "written"


def test_the_library_finds_a_color_and_fills_the_spool():
    found = lib.search("polylite petg orange")["results"]
    assert found and found[0]["brand"] == "Polymaker"
    hit = next(c for c in found[0]["colors"] if c["hit"])
    spool = lib.spool(found[0]["id"], hit["name"])
    assert spool["material"] == "PETG" and spool["nozzle"] and spool["weight"] in (1000, 750, 3000)
    assert lib.search()["brands"][0] == "Polymaker"


def test_picking_from_the_library_writes_its_brand_and_temperatures():
    t, _ = flow()
    reader = r.FakeReader()
    reader.put(blank())
    t.on_tag(reader.tag)
    t.input({"op": "library"})
    p = lib.search("polylite petg")["results"][0]
    t.input({"op": "pick", "product": p["id"], "color": p["colors"][0]["name"]})
    t.input({"op": "write"})
    run_write(t, reader)
    _, s = f.read(reader.tag)
    assert s["brand"] == "Polymaker" and s["nozzle"] == p["nozzle"]
