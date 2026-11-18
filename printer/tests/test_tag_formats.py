"""Spool tag formats (design/spool-tags/): each one byte for byte against what's known to read, and back again."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tag_formats as f  # noqa: E402

UID7 = bytes.fromhex("04A1B2C3D4E5F6")
RED_PLA = {"brand": "Polymaker", "material": "PLA", "name": "PolyLite Red", "color": "FF0000", "weight": 1000,
           "nozzle": [190, 230], "bed": [50, 60]}


def applied(ops, size, base=4):
    """The tag's memory after the writes, as a reader would return it (from page base)."""
    mem = bytearray(size)
    for op in ops:
        assert op["op"] == "write"
        at = (op["block"] - base) * 4
        mem[at:at + 4] = op["data"]
    return bytes(mem)


def ntag(chip="ntag213", data=None):
    return f.Tag(chip, UID7, data if data is not None else bytes(f.NTAG[chip]))


# ---- Anycubic ACE -----------------------------------------------------------------------------------

def test_anycubic_pages_match_the_known_good_writer_for_red_pla():
    ops = f.encode("anycubic", RED_PLA, ntag())
    assert [o["block"] for o in ops] == list(range(4, 40))   # pages 4-39, every one written
    mem = {o["block"]: o["data"].hex() for o in ops}
    assert mem[4] == "7b006500"
    assert bytes.fromhex(mem[5] + mem[6] + mem[7]) == b"AHPLBK-101\x00\x00"
    assert mem[10] == "41430000"                     # "AC"
    assert mem[15] == "504c4100"                     # "PLA"
    assert mem[20] == "ff0000ff"                     # alpha, blue, green, red
    assert mem[24] == "be00e600"                     # 190 / 230, little-endian
    assert mem[29] == "32003c00"
    assert mem[30][:4] == "af00"                     # 1.75 mm
    assert mem[31] == "e8030000"                     # 1000 g
    assert mem[39] == "00000000"


def test_anycubic_reads_back_with_the_real_brand_and_name():
    tag = ntag(data=applied(f.encode("anycubic", RED_PLA, ntag()), 144))
    fmt, spool = f.read(tag)
    assert fmt == "anycubic"
    assert spool["brand"] == "Polymaker" and spool["name"] == "PolyLite Red"
    assert spool["material"] == "PLA" and spool["color"] == "FF0000" and spool["nozzle"] == [190, 230]


def test_anycubic_factory_tag_from_the_known_dump_reads():
    mem = bytearray(144)
    for page, hexs in {4: "7b006500", 5: "4148504c", 6: "5042572d", 7: "31303200", 10: "41430000", 15: "504c412b",
                       20: "ffedf0f0", 24: "cd00d700", 29: "32003c00", 30: "af004a01", 31: "e8030000"}.items():
        mem[(page - 4) * 4:(page - 4) * 4 + 4] = bytes.fromhex(hexs)
    _, s = f.read(ntag(data=bytes(mem)))
    assert s["brand"] == "Anycubic" and s["material"] == "PLA+" and s["sku"] == "AHPLPBW-102"
    assert s["color"] == "F0F0ED" and s["nozzle"] == [205, 215] and s["length"] == 330


def test_anycubic_types_follow_the_slicers_names():
    assert f._ace_type("PLA", "Matte Black") == "PLA Matte"
    assert f._ace_type("PETG-CF") == "PETG"
    assert f._ace_type("PLA+") == "PLA+"


# ---- TigerTag --------------------------------------------------------------------------------------

def test_tigertag_is_big_endian_with_its_magic_and_no_signature():
    ops = f.encode("tigertag", RED_PLA, ntag())
    mem = applied(ops, 144)
    assert mem[0:4] == bytes.fromhex("5bf59264") and mem[4:8] == b"\xff" * 4
    assert mem[12] == 0x8E and mem[13] == 0x38          # filament, 1.75 mm
    assert mem[16:20] == bytes.fromhex("ff0000ff")       # RGBA
    assert mem[20:24] == bytes.fromhex("0003e815")       # 1000, grams
    assert mem[24:28] == bytes.fromhex("00be00e6")       # 190 / 230 big-endian
    assert not any(mem[80:])


def test_tigertag_round_trip_names_the_material_and_brand():
    tag = ntag(data=applied(f.encode("tigertag", RED_PLA, ntag()), 144))
    fmt, s = f.read(tag)
    assert fmt == "tigertag" and s["material"] == "PLA" and s["brand"] == "Polymaker"
    assert s["weight"] == 1000 and s["color"] == "FF0000" and s["bed"] == [50, 60] and not s["signed"]


# ---- OpenSpool -------------------------------------------------------------------------------------

def test_openspool_needs_an_ntag215():
    assert "NTAG215" in f.fits(f.BY_ID["openspool"], ntag("ntag213"))
    assert f.fits(f.BY_ID["openspool"], ntag("ntag215")) is None


def test_openspool_is_one_json_record_and_reads_back():
    tag = ntag("ntag215")
    mem = applied(f.encode("openspool", RED_PLA, tag), 504)
    assert mem[0] == 0x03 and b"application/json" in mem[:40]
    _, s = f.read(ntag("ntag215", mem))
    assert s["material"] == "PLA" and s["color"] == "FF0000" and s["nozzle"] == [190, 230] and s["brand"] == "Polymaker"


# ---- Creality CFS ----------------------------------------------------------------------------------

def test_aes_matches_the_fips_197_vector():
    key = bytes(range(16))
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = f.aes_encrypt_block(key, pt)
    assert ct.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
    assert f.aes_decrypt_block(key, ct) == pt


def test_cfs_key_from_the_uid_matches_the_published_example():
    assert f.cfs_key(bytes.fromhex("60EA1221")).hex() == "1f1e83a97182"


def test_cfs_record_is_48_characters_in_the_known_layout():
    text = f.cfs_plain({"material": "PLA", "color": "0000FF", "weight": 500})
    assert text == "AB1240276A21" + "00001" + "0" + "0000FF" + "0165" + "000001" + "0" * 14


def test_cfs_blank_tag_writes_data_then_its_keys_and_reads_back():
    uid = bytes.fromhex("60EA1221")
    tag = f.Tag("classic1k", uid, bytes(48), extra={"keyed": False, "access": bytes.fromhex("ff078069")})
    ops = f.encode("cfs", {"material": "PETG", "color": "112233", "weight": 1000}, tag)
    assert ops[0] == f.auth(4, b"\xff" * 6)
    assert [o["block"] for o in ops[1:]] == [4, 5, 6, 7]
    key = f.cfs_key(uid)
    assert ops[-1]["data"] == key + bytes.fromhex("ff078069") + key
    data = b"".join(o["data"] for o in ops[1:4])
    fmt, s = f.read(f.Tag("classic1k", uid, data, extra={"keyed": True}))
    assert fmt == "cfs" and s["material"] == "PETG" and s["color"] == "112233" and s["weight"] == 1000


def test_cfs_keyed_tag_keeps_its_keys():
    uid = bytes.fromhex("01020304")
    ops = f.encode("cfs", {"material": "PLA"}, f.Tag("classic1k", uid, bytes(48), extra={"keyed": True}))
    assert ops[0]["key"] == f.cfs_key(uid) and 7 not in [o.get("block") for o in ops if o["op"] == "write"]


# ---- OpenPrintTag ----------------------------------------------------------------------------------

def slix2(data=None):
    return f.Tag("slix2", bytes.fromhex("E004010866 2F6FBC".replace(" ", "")), data or bytes(320))


def test_openprinttag_fills_a_slix2_like_the_reference():
    mem = applied(f.encode("openprinttag", RED_PLA, slix2()), 320, base=0)
    assert mem[0:4] == bytes.fromhex("e1402801")
    assert mem[4:8] == bytes.fromhex("03ff0137")          # 311-byte NDEF message
    assert mem[8:14] == bytes.fromhex("c21c00000115")     # long record, 277-byte payload
    assert mem[14:42] == b"application/vnd.openprinttag"
    assert mem[319] == 0xFE


def test_openprinttag_round_trip():
    mem = applied(f.encode("openprinttag", dict(RED_PLA, material="PETG", weight=800), slix2()), 320, base=0)
    fmt, s = f.read(slix2(mem))
    assert fmt == "openprinttag"
    assert s["material"] == "PETG" and s["brand"] == "Polymaker" and s["color"] == "FF0000"
    assert s["weight"] == 800 and s["left"] == 800 and s["bed"] == [50, 60]


def test_cbor_round_trips_what_openprinttag_uses():
    v = {8: 0, 10: "PLA Galaxy", 19: b"\x01\x02\x03", 29: 1.24, 34: 215, -1: -7}
    out, used = f.cbor_loads(f.cbor_dumps(v))
    assert used == len(f.cbor_dumps(v)) and out[10] == "PLA Galaxy" and abs(out[29] - 1.24) < 1e-6 and out[-1] == -7


# ---- choosing --------------------------------------------------------------------------------------

def test_formats_say_which_tag_they_need():
    t = ntag("ntag213")
    why = {fmt["id"]: f.fits(fmt, t) for fmt in f.FORMATS}
    assert why["anycubic"] is None and why["tigertag"] is None
    assert "MIFARE Classic" in why["cfs"] and "SLIX2" in why["openprinttag"] and "Bambu" in why["bambu"]


def test_a_blank_tag_reads_as_nothing_and_says_blank():
    assert f.read(ntag()) is None and ntag().blank()
    assert ntag(data=b"\x03\x00\xfe" + bytes(141)).blank()
    assert not ntag(data=applied(f.encode("anycubic", RED_PLA, ntag()), 144)).blank()
