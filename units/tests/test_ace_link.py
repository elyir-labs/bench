"""Our link against the pretend unit, which answers as the captured ACE Pro does (ace-protocol.md)."""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ace_link import Decoder, Link, LinkClosed, crc16_mcrf4xx, encode  # noqa: E402
from pretend_ace import PretendAce  # noqa: E402

HERE = os.path.dirname(__file__)


def test_every_captured_frame_decodes_with_its_crc():
    with open(os.path.join(HERE, "..", "captures", "2026-10-18-moves.jsonl")) as f:
        rows = [json.loads(line) for line in f]
    out, inn = Decoder(), Decoder()
    sent = [m for r in rows if r["dir"] == "out" and r["ev"] == "S" for m in out.feed(bytes.fromhex(r["hex"]))]
    got = [m for r in rows if r["dir"] == "in" and r["ev"] == "C" for m in inn.feed(bytes.fromhex(r["hex"]))]
    assert len(sent) == len(got) == 60 and out.dropped == inn.dropped == 0
    assert {m["method"] for m in sent} >= {"get_status", "feed_filament", "unwind_filament", "drying", "drying_stop"}


def test_our_frames_match_the_units():
    frame = encode({"id": 34896, "method": "feed_filament", "params": {"index": 3, "length": 50, "speed": 80}})
    assert frame[:4] == b"\xff\xaa\x51\x00" and frame[-1:] == b"\xfe"
    assert int.from_bytes(frame[-3:-1], "little") == crc16_mcrf4xx(frame[4:-3])


@pytest.fixture
async def unit():
    ace = PretendAce(time_scale=4.0)
    await ace.start()
    link = Link(ace.port)
    await link.open()
    yield ace, link
    link.close()
    ace.close()


async def test_info_and_status(unit):
    ace, link = unit
    info = await link.call("get_info")
    assert info["result"]["firmware"] == "V1.3.856" and info["code"] == 0
    st = (await link.call("get_status"))["result"]
    assert st["status"] == "ready" and len(st["slots"]) == 4 and "action" not in st


async def test_a_slot_that_doesnt_exist_is_forbidden_with_code_0_and_an_unknown_method_is_400(unit):
    _, link = unit
    r = await link.call("feed_filament", {"index": 9, "length": 10, "speed": 50})
    assert (r["code"], r["msg"]) == (0, "FORBIDDEN")
    r = await link.call("no_such_method")
    assert (r["code"], r["msg"]) == (400, "InvalidCommand")


async def test_a_frame_with_a_bad_crc_gets_no_answer(unit):
    ace, link = unit
    bad = bytearray(encode({"id": 9000, "method": "get_status"}))
    bad[-2] ^= 0xFF
    os.write(link.fd, bytes(bad))
    await asyncio.sleep(0.1)
    assert not ace.requests and ace.dec.dropped == 1
    assert (await link.call("get_status"))["code"] == 0


async def test_an_unwind_stopped_mid_motion_stops_and_a_feed_stop_while_shifting_is_ignored(unit):
    ace, link = unit
    await link.call("unwind_filament", {"index": 2, "length": 30, "speed": 50})
    await asyncio.sleep(0.15)                       # 0.6 s on the unit: shifting done, moving
    await link.call("stop_unwind_filament", {"index": 2})
    stopped = ace.filament_at(2)
    assert -30 < stopped < -5
    await asyncio.sleep(0.2)
    assert ace.filament_at(2) == stopped
    r = await link.call("feed_filament", {"index": 2, "length": 20, "speed": 50})
    assert r["msg"] == "FORBIDDEN"                  # still busy for a moment after the motor stops
    await asyncio.sleep(0.2)
    await link.call("feed_filament", {"index": 2, "length": 20, "speed": 50})
    await link.call("stop_feed_filament", {"index": 2})   # still shifting
    await asyncio.sleep(0.4)
    assert ace.filament_at(2) == pytest.approx(stopped + 20)


async def test_the_dryer_counts_down_in_seconds(unit):
    ace, link = unit
    r = await link.call("drying", {"temp": 40, "fan_speed": 7000, "duration": 1})
    assert r["msg"] == "drying"
    d = (await link.call("get_status"))["result"]["dryer_status"]
    assert d["status"] == "drying" and d["duration"] == 1 and 58 <= d["remain_time"] <= 60


async def test_a_unit_that_stops_answering_times_out_and_a_closed_link_says_so(unit):
    ace, link = unit
    ace.silent = True
    with pytest.raises(asyncio.TimeoutError):
        await link.call("get_status", timeout=0.2)
    link.close()
    with pytest.raises(LinkClosed):
        await link.call("get_status")


async def test_requests_go_one_at_a_time_so_none_is_lost(unit):
    ace, link = unit
    # two frames written together: the unit answers only the first, as the real one missed replies
    os.write(link.fd, encode({"id": 9001, "method": "get_status"}) + encode({"id": 9002, "method": "get_status"}))
    await asyncio.sleep(0.1)
    assert [m["id"] for m in ace.requests[-2:]] == [9001, 9002]
    # through the link, many at once all come back
    replies = await asyncio.gather(*(link.call("get_status") for _ in range(8)))
    assert all(r["code"] == 0 for r in replies)
