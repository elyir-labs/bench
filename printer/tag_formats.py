"""Spool tags (design/spool-tags/): what each filament tag format holds, as raw tag memory.

A reader (tag_reader.py, or later a filament unit's lane) only moves bytes. Everything a format means lives here:
decode() turns a tag's memory into a spool, encode() turns a spool into the writes for one tag. Nothing here touches
hardware, so every format is tested offline (tests/test_tag_formats.py).

Sources, all community-documented or open specs (none of the vendor formats is published by its vendor):
- Anycubic ACE: Molodos/anycubic-nfc-filament and DnG-Crafts/ACE-RFID (NTAG21x pages 4-39).
- TigerTag: TigerTag-Project/TigerTag-RFID-Guide spec 2.3 (NTAG213 raw pages, big-endian), ID tables CC0.
- OpenSpool: spuder/OpenSpool docs/rfid.md (one application/json NDEF record; NTAG215/216 only).
- Creality CFS: DnG-Crafts/K2-RFID (MIFARE Classic 1K sector 1, AES-128 ECB, keys from the UID).
- OpenPrintTag: OpenPrintTag/openprinttag-specification (NFC Forum Type 5, CBOR regions in one NDEF record).
"""
import datetime
import json
import os
import struct
from typing import Any, Dict, List, Optional, Tuple

# ---- chips -----------------------------------------------------------------------------------------

NTAG = {"ntag213": 144, "ntag215": 504, "ntag216": 888}   # user bytes from page 4
SLIX2_BYTES = 320
CHIP_NAMES = {"ntag213": "NTAG213", "ntag215": "NTAG215", "ntag216": "NTAG216", "classic1k": "MIFARE Classic 1K",
              "slix2": "ICODE SLIX2", "iso15693": "ISO 15693 tag"}


class Tag:
    """One tag as a reader found it. data is the user memory: NTAG from page 4, a Type 5 tag from block 0, a MIFARE
    Classic the three data blocks of sector 1 (raw, as stored). blank says the reader saw nothing written."""

    def __init__(self, chip: str, uid: bytes, data: bytes = b"", size: Optional[int] = None,
                 extra: Optional[Dict[str, Any]] = None) -> None:
        self.chip, self.uid, self.data = chip, bytes(uid), bytes(data)
        self.size = size if size is not None else (NTAG.get(chip) or (SLIX2_BYTES if chip == "slix2" else len(data)))
        self.extra = dict(extra or {})

    @property
    def is_ntag(self) -> bool:
        return self.chip in NTAG

    @property
    def is_type5(self) -> bool:
        return self.chip in ("slix2", "iso15693")

    def blank(self) -> bool:
        if self.chip == "classic1k":
            return not self.extra.get("keyed") and not any(self.data)
        body = self.data
        if self.is_type5:
            body = body[4:]   # the capability container is there from the factory
        return not any(b not in (0, 0xFE) for b in body[:64]) or body[:3] == b"\x03\x00\xfe"


def write(block: int, data: bytes) -> Dict[str, Any]:
    return {"op": "write", "block": block, "data": bytes(data)}


def auth(block: int, key: bytes, key_type: int = 0x60) -> Dict[str, Any]:
    return {"op": "auth", "block": block, "key": bytes(key), "key_type": key_type}


def pages(start: int, data: bytes) -> List[Dict[str, Any]]:
    """4-byte writes from page (or Type 5 block) start, the data zero-padded to whole pages."""
    data = bytes(data) + b"\x00" * (-len(data) % 4)
    return [write(start + i // 4, data[i:i + 4]) for i in range(0, len(data), 4)]


# ---- spools ----------------------------------------------------------------------------------------
# A spool is a plain dict: brand, material, name (the color's name, or product and color), color (RRGGBB),
# weight (g), diameter (mm), nozzle [min, max], bed [min, max], density, and optional length (m).

MATERIALS: Dict[str, Dict[str, Any]] = {
    "PLA": {"nozzle": [190, 230], "bed": [50, 60], "density": 1.24, "dry": [50, 6]},
    "PLA+": {"nozzle": [200, 230], "bed": [50, 60], "density": 1.24, "dry": [50, 6]},
    "PETG": {"nozzle": [230, 250], "bed": [70, 80], "density": 1.27, "dry": [65, 6]},
    "ABS": {"nozzle": [240, 260], "bed": [90, 100], "density": 1.04, "dry": [80, 6]},
    "ASA": {"nozzle": [240, 260], "bed": [90, 100], "density": 1.07, "dry": [80, 6]},
    "TPU": {"nozzle": [210, 230], "bed": [30, 60], "density": 1.21, "dry": [55, 6]},
    "PC": {"nozzle": [260, 290], "bed": [100, 110], "density": 1.20, "dry": [80, 8]},
    "PA": {"nozzle": [250, 280], "bed": [80, 100], "density": 1.14, "dry": [80, 8]},
    "PCTG": {"nozzle": [240, 260], "bed": [70, 80], "density": 1.23, "dry": [65, 6]},
    "HIPS": {"nozzle": [230, 250], "bed": [90, 100], "density": 1.04, "dry": [70, 6]},
    "PVA": {"nozzle": [190, 210], "bed": [50, 60], "density": 1.23, "dry": [50, 8]},
    "PP": {"nozzle": [220, 250], "bed": [80, 100], "density": 0.90, "dry": [70, 6]},
}


def family(material: str) -> str:
    """PETG-CF, PETG HF and PETG Translucent are PETG; TPU-95A is TPU; Nylon/PA6 is PA."""
    m = (material or "").upper().strip()
    if m.startswith("PLA+"):
        return "PLA+"
    for key in ("PCTG", "PETG", "PLA", "ABS", "ASA", "TPU", "HIPS", "PVA", "PC", "PP"):
        if m.startswith(key):
            return key
    if m.startswith("PA") or "NYLON" in m:
        return "PA"
    if m.startswith("FLEX") or m.startswith("TPE"):
        return "TPU"
    return m or "PLA"


def defaults(material: str) -> Dict[str, Any]:
    return MATERIALS.get(family(material), MATERIALS["PLA"])


def complete(spool: Dict[str, Any]) -> Dict[str, Any]:
    """The spool with every field a format needs, the material's defaults where it says nothing."""
    d = defaults(spool.get("material", "PLA"))
    s = dict(spool)
    s["material"] = (s.get("material") or "PLA").strip()
    s["color"] = (s.get("color") or "000000").lstrip("#").upper()[:6].rjust(6, "0")
    s["weight"] = int(round(float(s.get("weight") or 1000)))
    s["diameter"] = float(s.get("diameter") or 1.75)
    s["nozzle"] = [int(v) for v in (s.get("nozzle") or d["nozzle"])]
    s["bed"] = [int(v) for v in (s.get("bed") or d["bed"])]
    s["density"] = float(s.get("density") or d["density"])
    s.setdefault("brand", "")
    s.setdefault("name", "")
    if not s.get("length"):
        r = s["diameter"] / 20.0   # cm
        s["length"] = int(round(s["weight"] / (s["density"] * 3.14159265 * r * r) / 100.0))
    return s


def _rgb(hex6: str) -> Tuple[int, int, int]:
    h = (hex6 or "000000").lstrip("#")[:6].rjust(6, "0")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: int, g: int, b: int) -> str:
    return f"{r:02X}{g:02X}{b:02X}"


def _ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


def _put(buf: bytearray, offset: int, raw: bytes, size: int) -> None:
    raw = raw[:size]
    buf[offset:offset + len(raw)] = raw


# ---- the shipped tables (tag_data/) ---------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tag_data")
_tigertag: Optional[Dict[str, Any]] = None


def tigertag_tables() -> Dict[str, Any]:
    """TigerTag's ID tables (CC0), trimmed by tools/build-tag-data.py."""
    global _tigertag
    if _tigertag is None:
        try:
            with open(os.path.join(DATA_DIR, "tigertag.json")) as f:
                _tigertag = json.load(f)
        except (OSError, ValueError):
            _tigertag = {"materials": [], "brands": [], "aspects": []}
    return _tigertag


# ==== Anycubic ACE ==================================================================================
# NTAG21x pages 4-39, numbers little-endian, color as alpha, blue, green, red. Pages 32-38 are unused by Anycubic;
# Bench keeps the spool's real brand and name there ("EB" first), since page 10 stays "AC" as on every tag known
# to read. The ACE is reported to check the SKU looks real, so the SKU is Anycubic's own for the material.

ACE_SKUS = {"PLA": "AHPLBK-101", "PLA+": "AHPLPBK-102", "PLA High Speed": "AHHSBK-102", "PLA Matte": "HYGBK-101",
            "PLA Silk": "HSCWH-101", "PETG": "HPEBK-103", "ASA": "HASBK-101", "ABS": "HABBK-102",
            "TPU": "HTPBK-101", "PLA Luminous": "HFGBL-101"}
ACE_HEADER = b"\x7b\x00\x65\x00"
ACE_EXT = b"EB"


def _ace_type(material: str, name: str = "") -> str:
    fam = family(material)
    low = f"{material} {name}".lower()
    if fam == "PLA":
        for word, t in (("matte", "PLA Matte"), ("silk", "PLA Silk"), ("high speed", "PLA High Speed"),
                        ("luminous", "PLA Luminous"), ("glow", "PLA Luminous")):
            if word in low:
                return t
    return fam if fam in ACE_SKUS else (material or "PLA")[:20]


def _ace_at(page: int) -> int:
    return (page - 4) * 4


def ace_encode(spool: Dict[str, Any], tag: Tag) -> List[Dict[str, Any]]:
    s = complete(spool)
    kind = _ace_type(s["material"], s.get("name", ""))
    sku = ACE_SKUS.get(kind) or ACE_SKUS.get(family(kind), "AHPLBK-101")
    buf = bytearray(144)
    buf[0:4] = ACE_HEADER
    _put(buf, _ace_at(5), sku.encode(), 20)
    _put(buf, _ace_at(10), b"AC", 20)
    _put(buf, _ace_at(15), kind.encode(), 20)
    r, g, b = _rgb(s["color"])
    buf[_ace_at(20):_ace_at(20) + 4] = bytes([0xFF, b, g, r])
    buf[_ace_at(24):_ace_at(24) + 4] = struct.pack("<HH", *s["nozzle"])
    buf[_ace_at(29):_ace_at(29) + 4] = struct.pack("<HH", *s["bed"])
    buf[_ace_at(30):_ace_at(30) + 4] = struct.pack("<HH", int(round(s["diameter"] * 100)), min(s["length"], 0xFFFF))
    buf[_ace_at(31):_ace_at(31) + 4] = struct.pack("<HH", min(s["weight"], 0xFFFF), 0)
    ext = ACE_EXT + (s.get("brand") or "").encode()[:12] + b"\x00" + (s.get("name") or "").encode()
    _put(buf, _ace_at(32), ext, 28)
    return pages(4, bytes(buf))


def ace_decode(tag: Tag) -> Optional[Dict[str, Any]]:
    d = tag.data
    if not tag.is_ntag or len(d) < 112 or d[0] != 0x7B or d[2] not in (0x64, 0x65):
        return None
    kind = _ascii(d[_ace_at(15):_ace_at(20)])
    if not kind:
        return None
    _, b, g, r = d[_ace_at(20):_ace_at(20) + 4]
    nozzle = list(struct.unpack("<HH", d[_ace_at(24):_ace_at(24) + 4]))
    bed = list(struct.unpack("<HH", d[_ace_at(29):_ace_at(29) + 4]))
    dia, length = struct.unpack("<HH", d[_ace_at(30):_ace_at(30) + 4])
    weight = struct.unpack("<H", d[_ace_at(31):_ace_at(31) + 2])[0]
    brand, name = "Anycubic", ""
    ext = d[_ace_at(32):_ace_at(32) + 28]
    if ext[:2] == ACE_EXT:
        mine, _, rest = ext[2:].partition(b"\x00")
        brand, name = mine.decode("utf-8", "replace") or brand, _ascii(rest)
    return {"brand": brand, "material": kind, "name": name, "color": _hex(r, g, b), "weight": weight or None,
            "diameter": dia / 100.0 if dia else 1.75, "nozzle": nozzle if any(nozzle) else None,
            "bed": bed if any(bed) else None, "length": length or None,
            "sku": _ascii(d[_ace_at(5):_ace_at(10)])}


# ==== TigerTag ======================================================================================
# NTAG213 pages 4-23 hold 80 bytes of data (big-endian), pages 24-39 a signature only a maker can add. Bench
# writes a plain (unsigned) TigerTag.

TT_IDS = {0x5BF59264: "TigerTag", 0xBC0FCB97: "TigerTag+", 0x6C41A2E1: "TigerTag Init"}
TT_ID = 0x5BF59264
TT_PRODUCT_NONE = 0xFFFFFFFF
TT_FILAMENT = 0x8E
TT_DIAMETERS = {1.75: 0x38, 2.85: 0xDD}
TT_GRAMS, TT_KG = 21, 35
TT_ASPECT_BASIC = 104
TT_BRAND_GENERIC = 65535
TT_EPOCH = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)


def _tt_material(material: str) -> Tuple[int, Dict[str, Any]]:
    mats = tigertag_tables().get("materials", [])
    want = (material or "").upper()
    for key in (lambda m: m["label"].upper() == want, lambda m: m["label"].upper() == family(material),
                lambda m: m.get("type", "").upper() == family(material)):
        hit = next((m for m in mats if key(m)), None)
        if hit:
            return hit["id"], hit
    return 38219, {}   # PLA


def _tt_brand(brand: str) -> int:
    want = (brand or "").lower().replace(" ", "")
    for b in tigertag_tables().get("brands", []):
        if b["name"].lower().replace(" ", "") == want:
            return b["id"]
    return TT_BRAND_GENERIC


def tigertag_encode(spool: Dict[str, Any], tag: Tag, now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
    s = complete(spool)
    mid, mat = _tt_material(s["material"])
    dry = mat.get("dry") or defaults(s["material"])["dry"]
    r, g, b = _rgb(s["color"])
    stamp = int(((now or datetime.datetime.now(datetime.timezone.utc)) - TT_EPOCH).total_seconds())
    aspect = TT_ASPECT_BASIC
    for a in tigertag_tables().get("aspects", []):
        if a["label"].lower() in (s.get("name") or "").lower().split():
            aspect = a["id"]
            break
    data = struct.pack(">IIHBBBBH", TT_ID, TT_PRODUCT_NONE, mid, aspect, 0, TT_FILAMENT,
                       TT_DIAMETERS.get(round(s["diameter"], 2), 0x38), _tt_brand(s.get("brand", "")))
    data += bytes([r, g, b, 0xFF])
    data += min(s["weight"], 0xFFFFFF).to_bytes(3, "big") + bytes([TT_GRAMS])
    data += struct.pack(">HHBBBB", s["nozzle"][0], s["nozzle"][1], int(dry[0]), int(dry[1]),
                        min(s["bed"][0], 255), min(s["bed"][1], 255))
    data += struct.pack(">I", stamp & 0xFFFFFFFF)
    data += b"\x00" * 8 + b"\x00" * 4                               # colors 2 and 3, tag count, reserved; TD unset
    message = (s.get("name") or "").encode("utf-8")[:28]
    data += message + b"\x00" * (28 - len(message))
    data += min(s["weight"], 0xFFFFFF).to_bytes(3, "big") + b"\x00"
    assert len(data) == 80
    return pages(4, data + b"\x00" * 64)


def tigertag_decode(tag: Tag) -> Optional[Dict[str, Any]]:
    d = tag.data
    if not tag.is_ntag or len(d) < 80:
        return None
    ident = struct.unpack(">I", d[0:4])[0]
    if ident not in TT_IDS or ident == 0x6C41A2E1:
        return None
    _, _, mid, _a1, _a2, kind, dia, bid = struct.unpack(">IIHBBBBH", d[0:16])
    if kind != TT_FILAMENT:
        return None
    t = tigertag_tables()
    mat = next((m for m in t.get("materials", []) if m["id"] == mid), {})
    brand = next((b["name"] for b in t.get("brands", []) if b["id"] == bid), "")
    measure = int.from_bytes(d[20:23], "big")
    unit = d[23]
    nmin, nmax, _dt, _dh, bmin, bmax = struct.unpack(">HHBBBB", d[24:32])
    left = int.from_bytes(d[76:79], "big")
    grams = measure * 1000 if unit == TT_KG else measure
    return {"brand": "" if brand == "Generic" else brand, "material": mat.get("label") or "PLA",
            "name": _ascii(d[48:76]), "color": _hex(d[16], d[17], d[18]), "weight": grams or None,
            "diameter": 2.85 if dia == 0xDD else 1.75, "nozzle": [nmin, nmax] if nmax else None,
            "bed": [bmin, bmax] if bmax else None, "left": (left * 1000 if unit == TT_KG else left) or None,
            "signed": any(d[80:144])}


# ==== NDEF (OpenSpool, OpenPrintTag) =================================================================

def ndef_record(mime: str, payload: bytes) -> bytes:
    t = mime.encode()
    if len(payload) < 256:
        return bytes([0xD2, len(t), len(payload)]) + t + payload            # MB ME SR, TNF 2 (media type)
    return bytes([0xC2, len(t)]) + struct.pack(">I", len(payload)) + t + payload


def ndef_tlv(message: bytes) -> bytes:
    if len(message) < 0xFF:
        return bytes([0x03, len(message)]) + message
    return bytes([0x03, 0xFF]) + struct.pack(">H", len(message)) + message


def ndef_records(area: bytes) -> List[Tuple[str, bytes]]:
    """(media type, payload) for each record of the first NDEF message in a run of TLVs."""
    i = 0
    while i < len(area):
        t = area[i]
        if t == 0x00:
            i += 1
            continue
        if t == 0xFE or i + 1 >= len(area):
            return []
        if area[i + 1] == 0xFF:
            n, start = struct.unpack(">H", area[i + 2:i + 4])[0], i + 4
        else:
            n, start = area[i + 1], i + 2
        if t != 0x03:
            i = start + n
            continue
        return _records(area[start:start + n])
    return []


def _records(msg: bytes) -> List[Tuple[str, bytes]]:
    out, i = [], 0
    while i + 3 <= len(msg):
        head = msg[i]
        tlen = msg[i + 1]
        if head & 0x10:
            plen, j = msg[i + 2], i + 3
        else:
            plen, j = struct.unpack(">I", msg[i + 2:i + 6])[0], i + 6
        idlen = 0
        if head & 0x08:
            idlen, j = msg[j], j + 1
        rtype = msg[j:j + tlen]
        j += tlen + idlen
        out.append((rtype.decode("ascii", "replace") if head & 0x07 == 2 else "", bytes(msg[j:j + plen])))
        i = j + plen
        if head & 0x40:
            break
    return out


def type5_area(tag: Tag) -> bytes:
    """The TLVs of a Type 5 tag, after its 4- or 8-byte capability container."""
    d = tag.data
    if len(d) < 8 or d[0] not in (0xE1, 0xE2):
        return b""
    return d[8:] if d[2] == 0 else d[4:]


def ndef_area(tag: Tag) -> bytes:
    return type5_area(tag) if tag.is_type5 else tag.data if tag.is_ntag else b""


# ==== OpenSpool =====================================================================================

OPENSPOOL_MIME = "application/json"


def openspool_encode(spool: Dict[str, Any], tag: Tag) -> List[Dict[str, Any]]:
    s = complete(spool)
    body = {"protocol": "openspool", "version": "1.0", "type": family(s["material"]), "color_hex": s["color"],
            "brand": s.get("brand") or "Generic", "min_temp": str(s["nozzle"][0]), "max_temp": str(s["nozzle"][1])}
    msg = ndef_tlv(ndef_record(OPENSPOOL_MIME, json.dumps(body, separators=(",", ":")).encode())) + b"\xfe"
    return pages(4, msg)


def openspool_decode(tag: Tag) -> Optional[Dict[str, Any]]:
    for mime, payload in ndef_records(ndef_area(tag)):
        if mime != OPENSPOOL_MIME:
            continue
        try:
            body = json.loads(payload.decode("utf-8"))
        except ValueError:
            continue
        if not isinstance(body, dict) or body.get("protocol") != "openspool":
            continue
        nozzle = [int(body["min_temp"]), int(body["max_temp"])] if body.get("min_temp") and body.get("max_temp") else None
        brand = body.get("brand") or ""
        return {"brand": "" if brand == "Generic" else brand, "material": body.get("type") or "PLA", "name": "",
                "color": (body.get("color_hex") or "000000").lstrip("#").upper()[:6], "nozzle": nozzle}
    return None


# ==== Creality CFS ==================================================================================
# MIFARE Classic 1K: sector 1's blocks 4-6 hold 48 ASCII characters, AES-128-ECB encrypted with a fixed key; the
# sector's key A and B are the first 6 bytes of the 4-byte UID (repeated to 16) encrypted with another fixed key.

CFS_DATA_KEY = b"H@CFkRnz@KAtBJp2"
CFS_UID_KEY = b"q3bu^t1nqfZ(pf$1"
CFS_VENDOR = "0276"
CFS_DEFAULT_KEY = b"\xff" * 6
CFS_ACCESS = b"\xff\x07\x80\x69"   # the factory access bits, used only when the tag's own couldn't be read
CFS_LENGTHS = {1000: "0330", 750: "0247", 600: "0198", 500: "0165", 250: "0082"}
CFS_GENERIC = {"PLA": "00001", "PETG": "00003", "ABS": "00004", "TPU": "00005", "ASA": "00007", "PLA+": "09001"}


def cfs_key(uid: bytes) -> bytes:
    u = bytes(uid)[:4]
    return aes_encrypt_block(CFS_UID_KEY, bytes(u[i % len(u)] for i in range(16)))[:6] if u else CFS_DEFAULT_KEY


def _cfs_material(spool: Dict[str, Any]) -> str:
    mats = tigertag_tables().get("materials", [])
    want = (spool.get("material") or "").upper()
    for m in mats:
        if m["label"].upper() == want and m.get("creality"):
            return m["creality"]
    return CFS_GENERIC.get(family(want), "00001")


def cfs_plain(spool: Dict[str, Any], serial: str = "000001") -> str:
    s = complete(spool)
    length = CFS_LENGTHS.get(s["weight"]) or f"{min(9999, int(round(s['weight'] * 0.33))):04d}"
    text = "AB124" + CFS_VENDOR + "A2" + "1" + _cfs_material(s) + "0" + s["color"] + length + serial + "0" * 14
    assert len(text) == 48
    return text


def cfs_encode(spool: Dict[str, Any], tag: Tag) -> List[Dict[str, Any]]:
    secret = b"".join(aes_encrypt_block(CFS_DATA_KEY, cfs_plain(spool).encode()[i:i + 16]) for i in (0, 16, 32))
    key = cfs_key(tag.uid)
    keyed = bool(tag.extra.get("keyed"))
    ops = [auth(4, key if keyed else CFS_DEFAULT_KEY)] + [write(4 + i, secret[i * 16:(i + 1) * 16]) for i in range(3)]
    if not keyed:
        access = bytes(tag.extra.get("access") or CFS_ACCESS)
        ops.append(write(7, key + access + key))   # data first, then the sector's new keys
    return ops


def cfs_decode(tag: Tag) -> Optional[Dict[str, Any]]:
    if tag.chip != "classic1k" or len(tag.data) < 48:
        return None
    try:
        text = b"".join(aes_decrypt_block(CFS_DATA_KEY, tag.data[i:i + 16]) for i in (0, 16, 32)).decode("ascii")
    except (UnicodeDecodeError, ValueError):
        return None
    if not (text[:5].isalnum() and text[5:9].isdigit() and text[11:17].isdigit()
            and all(c in "0123456789ABCDEFabcdef" for c in text[18:24])):
        return None
    mid = text[12:17]
    mat = next((m for m in tigertag_tables().get("materials", []) if m.get("creality") == mid), None)
    name = mat["label"] if mat else next((k for k, v in CFS_GENERIC.items() if v == mid), "PLA")
    length = int(text[24:28]) if text[24:28].isdigit() else 0
    weight = next((w for w, l in CFS_LENGTHS.items() if l == text[24:28]), int(round(length / 0.33)) if length else None)
    return {"brand": "Creality" if text[5:9] == CFS_VENDOR else "", "material": name, "name": "",
            "color": text[18:24].upper(), "weight": weight, "length": length or None, "creality_id": mid}


# ==== OpenPrintTag ==================================================================================
# A Type 5 tag (ICODE SLIX2, 320 bytes): capability container, one NDEF record of type application/vnd.openprinttag
# whose payload is three CBOR maps with integer keys: meta (where the others are), main (the material), aux
# (what changes as it's used). Sized to fill the tag the way the reference implementation does.

OPT_MIME = "application/vnd.openprinttag"
OPT_TYPES = ["PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PCTG", "PP", "PA6", "PA11", "PA12", "PA66", "CPE", "TPE",
             "HIPS", "PHA", "PET", "PEI", "PBT", "PVB", "PVA", "PEKK", "PEEK", "BVOH", "TPC", "PPS", "PPSU", "PVC",
             "PEBA", "PVDF", "PPA", "PCL", "PES", "PMMA", "POM", "PPE", "PS", "PSU", "TPI", "SBS", "OBC", "EVA",
             "PA612"]
OPT_AUX_BYTES = 32
(OPT_CLASS, OPT_TYPE, OPT_NAME, OPT_BRAND, OPT_NOMINAL, OPT_ACTUAL, OPT_COLOR, OPT_DENSITY, OPT_DIAMETER,
 OPT_PRINT_MIN, OPT_PRINT_MAX, OPT_BED_MIN, OPT_BED_MAX) = 8, 9, 10, 11, 16, 17, 19, 29, 30, 34, 35, 37, 38
OPT_CONSUMED = 0


def _opt_type(material: str) -> int:
    fam = family(material)
    for i, t in enumerate(OPT_TYPES):
        if t == (material or "").upper() or t == fam:
            return i
    return {"PA": 8, "PLA+": 0}.get(fam, 0)


def openprinttag_encode(spool: Dict[str, Any], tag: Tag) -> List[Dict[str, Any]]:
    s = complete(spool)
    size = tag.size or SLIX2_BYTES
    main = {OPT_CLASS: 0, OPT_TYPE: _opt_type(s["material"]),
            OPT_NAME: (s.get("name") or s["material"])[:63], OPT_BRAND: (s.get("brand") or "Generic")[:31],
            OPT_NOMINAL: s["weight"], OPT_COLOR: bytes(_rgb(s["color"])), OPT_DENSITY: s["density"],
            OPT_PRINT_MIN: s["nozzle"][0], OPT_PRINT_MAX: s["nozzle"][1], OPT_BED_MIN: s["bed"][0],
            OPT_BED_MAX: s["bed"][1]}
    if abs(s["diameter"] - 1.75) > 0.01:
        main[OPT_DIAMETER] = s["diameter"]
    main_cbor = cbor_dumps(main)
    rec_head = 6 + len(OPT_MIME)                     # long record: payloads of a whole tag are over 255
    message = size - 4 - 4 - 1                       # CC, long TLV head, terminator
    payload_len = message - rec_head
    payload_start = 4 + 4 + rec_head
    aux_at = payload_len - OPT_AUX_BYTES
    aux_at -= (payload_start + aux_at) % 4           # aux on a block boundary of the tag
    meta = cbor_dumps({2: aux_at})
    if len(meta) + len(main_cbor) > aux_at:
        raise ValueError("too much for this tag")
    aux = b"\xbf\x00\x00\xff"                        # {consumed_weight: 0}, indefinite as the spec suggests
    payload = (meta + main_cbor).ljust(aux_at, b"\x00") + aux.ljust(payload_len - aux_at, b"\x00")
    cc = bytes([0xE1, 0x40, size // 8, 0x01])
    body = cc + ndef_tlv(ndef_record(OPT_MIME, payload)) + b"\xfe"
    assert len(body) == size, (len(body), size)
    return pages(0, body)


def openprinttag_decode(tag: Tag) -> Optional[Dict[str, Any]]:
    for mime, payload in ndef_records(ndef_area(tag)):
        if mime != OPT_MIME:
            continue
        try:
            meta, used = cbor_loads(payload)
            if not isinstance(meta, dict):
                return None
            main_at = meta.get(0, used)
            main, _ = cbor_loads(payload[main_at:])
            aux = cbor_loads(payload[meta[2]:])[0] if 2 in meta else {}
        except (ValueError, IndexError, KeyError):
            return None
        if not isinstance(main, dict):
            return None
        ti = main.get(OPT_TYPE)
        color = main.get(OPT_COLOR) or b"\x00\x00\x00"
        full = main.get(OPT_ACTUAL) or main.get(OPT_NOMINAL)
        used_g = (aux or {}).get(OPT_CONSUMED) if isinstance(aux, dict) else None
        out = {"brand": main.get(OPT_BRAND) or "", "name": main.get(OPT_NAME) or "",
               "material": OPT_TYPES[ti] if isinstance(ti, int) and 0 <= ti < len(OPT_TYPES) else "PLA",
               "color": _hex(*color[:3]), "weight": int(full) if full else None,
               "diameter": float(main.get(OPT_DIAMETER) or 1.75), "density": main.get(OPT_DENSITY),
               "nozzle": [main[OPT_PRINT_MIN], main[OPT_PRINT_MAX]] if OPT_PRINT_MAX in main else None,
               "bed": [main[OPT_BED_MIN], main[OPT_BED_MAX]] if OPT_BED_MAX in main else None}
        if full and isinstance(used_g, (int, float)):
            out["left"] = max(0, int(round(full - used_g)))
        return out
    return None


# ==== the formats, in the order they're offered ====================================================

FORMATS: List[Dict[str, Any]] = [
    {"id": "anycubic", "name": "Anycubic ACE", "chips": set(NTAG), "min": 144,
     "encode": ace_encode, "decode": ace_decode},
    {"id": "tigertag", "name": "TigerTag", "chips": set(NTAG), "min": 144,
     "encode": tigertag_encode, "decode": tigertag_decode},
    {"id": "openspool", "name": "OpenSpool", "chips": {"ntag215", "ntag216"}, "min": 504,
     "encode": openspool_encode, "decode": openspool_decode},
    {"id": "cfs", "name": "Creality CFS", "chips": {"classic1k"}, "min": 48,
     "encode": cfs_encode, "decode": cfs_decode},
    {"id": "openprinttag", "name": "OpenPrintTag", "chips": {"slix2", "iso15693"}, "min": 320,
     "encode": openprinttag_encode, "decode": openprinttag_decode},
    {"id": "bambu", "name": "Bambu Lab", "chips": set(), "min": 0, "encode": None, "decode": None},
]
BY_ID = {f["id"]: f for f in FORMATS}
NEEDS = {"anycubic": "an NTAG213, 215 or 216", "tigertag": "an NTAG213, 215 or 216",
         "openspool": "an NTAG215 or 216", "cfs": "a MIFARE Classic 1K", "openprinttag": "an ICODE SLIX2"}


def fits(fmt: Dict[str, Any], tag: Tag) -> Optional[str]:
    """None when this format can go on this tag, else why not, in a few words."""
    if fmt["encode"] is None:
        return "Read only: Bambu signs its own tags"
    if tag.chip not in fmt["chips"] or (tag.size or 0) < fmt["min"]:
        return f"Needs {NEEDS[fmt['id']]}, not this one"
    return None


def read(tag: Tag) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(format id, spool) for the first format that recognizes the tag."""
    for fmt in FORMATS:
        if fmt["decode"] is None:
            continue
        try:
            spool = fmt["decode"](tag)
        except Exception:   # one malformed tag never stops the others being tried
            spool = None
        if spool:
            return fmt["id"], spool
    return None


def encode(fmt_id: str, spool: Dict[str, Any], tag: Tag) -> List[Dict[str, Any]]:
    fmt = BY_ID[fmt_id]
    why = fits(fmt, tag)
    if why:
        raise ValueError(why)
    return fmt["encode"](spool, tag)


# ==== CBOR, only what OpenPrintTag uses ==============================================================

def cbor_dumps(v: Any) -> bytes:
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return _cbor_head(0, v) if v >= 0 else _cbor_head(1, -1 - v)
    if isinstance(v, float):
        if v == int(v) and abs(v) < 2 ** 31:
            return cbor_dumps(int(v))
        packed = struct.pack(">f", v)
        if struct.unpack(">f", packed)[0] == v or abs(struct.unpack(">f", packed)[0] - v) < 1e-6:
            return b"\xfa" + packed
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, (bytes, bytearray)):
        return _cbor_head(2, len(v)) + bytes(v)
    if isinstance(v, str):
        raw = v.encode("utf-8")
        return _cbor_head(3, len(raw)) + raw
    if isinstance(v, (list, tuple)):
        return _cbor_head(4, len(v)) + b"".join(cbor_dumps(x) for x in v)
    if isinstance(v, dict):
        return _cbor_head(5, len(v)) + b"".join(cbor_dumps(k) + cbor_dumps(x) for k, x in v.items())
    raise TypeError(f"can't encode {type(v).__name__}")


def _cbor_head(major: int, n: int) -> bytes:
    m = major << 5
    if n < 24:
        return bytes([m | n])
    for extra, fmt, limit in ((24, ">B", 0xFF), (25, ">H", 0xFFFF), (26, ">I", 0xFFFFFFFF), (27, ">Q", 2 ** 64 - 1)):
        if n <= limit:
            return bytes([m | extra]) + struct.pack(fmt, n)
    raise ValueError("too big")


def cbor_loads(b: bytes, i: int = 0) -> Tuple[Any, int]:
    """(value, the offset after it)."""
    head = b[i]
    major, info = head >> 5, head & 0x1F
    i += 1
    if major == 7:
        if info == 20:
            return False, i
        if info == 21:
            return True, i
        if info in (22, 23):
            return None, i
        if info == 25:
            return _half(struct.unpack(">H", b[i:i + 2])[0]), i + 2
        if info == 26:
            return struct.unpack(">f", b[i:i + 4])[0], i + 4
        if info == 27:
            return struct.unpack(">d", b[i:i + 8])[0], i + 8
        raise ValueError("unknown simple value")
    if info == 31:
        if major == 4:
            out = []
            while b[i] != 0xFF:
                v, i = cbor_loads(b, i)
                out.append(v)
            return out, i + 1
        if major == 5:
            d: Dict[Any, Any] = {}
            while b[i] != 0xFF:
                k, i = cbor_loads(b, i)
                d[k], i = cbor_loads(b, i)
            return d, i + 1
        raise ValueError("indefinite strings aren't used")
    if info < 24:
        n = info
    else:
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        n, i = int.from_bytes(b[i:i + size], "big"), i + size
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major == 2:
        return bytes(b[i:i + n]), i + n
    if major == 3:
        return b[i:i + n].decode("utf-8"), i + n
    if major == 4:
        out = []
        for _ in range(n):
            v, i = cbor_loads(b, i)
            out.append(v)
        return out, i
    if major == 5:
        d = {}
        for _ in range(n):
            k, i = cbor_loads(b, i)
            d[k], i = cbor_loads(b, i)
        return d, i
    if major == 6:
        return cbor_loads(b, i)   # a tag: its value
    raise ValueError("bad CBOR")


def _half(h: int) -> float:
    sign = -1.0 if h & 0x8000 else 1.0
    exp, frac = (h >> 10) & 0x1F, h & 0x3FF
    if exp == 0:
        return sign * frac * 2 ** -24
    if exp == 31:
        return sign * float("inf") if not frac else float("nan")
    return sign * (1 + frac / 1024.0) * 2 ** (exp - 15)


# ==== AES-128, one block at a time (CFS only; no crypto library on the printer) ======================

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a07"
    "1280e2eb27b27509832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cfd0efaafb434d338545f9027f503c9fa851a3"
    "408f929d38f5bcb6da2110fff3d2cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdbe0323a0a4906245cc2d3ac"
    "629195e479e7c8376d8dd54ea96c56f4ea657aae08ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9ee1f8981169"
    "d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_INV = bytes(_SBOX.index(i) for i in range(256))
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xt(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a: int, b: int) -> int:
    out = 0
    while b:
        if b & 1:
            out ^= a
        a, b = _xt(a), b >> 1
    return out


def _round_keys(key: bytes) -> List[List[int]]:
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[x] for x in t[1:] + t[:1]]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _shift(s: List[int], inverse: bool = False) -> List[int]:
    out = [0] * 16
    for c in range(4):
        for r in range(4):
            src = ((c - r) % 4) if inverse else ((c + r) % 4)
            out[c * 4 + r] = s[src * 4 + r]
    return out


def _mix(s: List[int], m: Tuple[int, int, int, int]) -> List[int]:
    out = []
    for c in range(4):
        col = s[c * 4:c * 4 + 4]
        for r in range(4):
            out.append(_mul(col[0], m[(0 - r) % 4]) ^ _mul(col[1], m[(1 - r) % 4])
                       ^ _mul(col[2], m[(2 - r) % 4]) ^ _mul(col[3], m[(3 - r) % 4]))
    return out


def aes_encrypt_block(key: bytes, block: bytes) -> bytes:
    rk = _round_keys(key)
    s = [a ^ b for a, b in zip(block, rk[0])]
    for r in range(1, 11):
        s = _shift([_SBOX[x] for x in s])
        if r < 10:
            s = _mix(s, (2, 3, 1, 1))
        s = [a ^ b for a, b in zip(s, rk[r])]
    return bytes(s)


def aes_decrypt_block(key: bytes, block: bytes) -> bytes:
    rk = _round_keys(key)
    s = [a ^ b for a, b in zip(block, rk[10])]
    for r in range(9, -1, -1):
        s = [_INV[x] for x in _shift(s, inverse=True)]
        s = [a ^ b for a, b in zip(s, rk[r])]
        if r > 0:
            s = _mix(s, (14, 11, 13, 9))
    return bytes(s)
