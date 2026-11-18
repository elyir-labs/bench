"""The USB NFC reader for spool tags (design/spool-tags/): an ACS ACR1552U on the printer, through pcscd.

Only moves bytes: finds the tag, reads its memory into a tag_formats.Tag, runs the writes spool_tags hands out.
Talks to libpcsclite with ctypes, so the printer needs `pcscd` and `libccid` from apt and nothing from pip.
Runs in its own thread; everything it learns goes out through emit(kind, *args):
  ("reader", name or None, "ready" | "missing" | "error", why), ("tag", Tag or None), ("written", ok, why, Tag).

The APDUs are the PC/SC Part 3 pseudo-APDUs ACS readers take (FF B0 read, FF D6 write, FF 82 load key, FF 86
authenticate, FF CA UID). Not yet run against a real ACR1552U: the first tag on Workshop is the test (pick 4).
"""
import ctypes
import ctypes.util
import importlib.util
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


def _sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"{name}.py not found next to {__file__}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


formats = _sibling("tag_formats")

Emit = Callable[..., None]
POLL_MS = 1000
RELIST_SECONDS = 3.0
NTAG_BY_CC = {0x12: "ntag213", 0x3E: "ntag215", 0x6D: "ntag216"}


# ---- applying writes to memory (the fake reader, and checks) ---------------------------------------

def apply_to_memory(tag: Any, ops: List[Dict[str, Any]]) -> Any:
    """The tag as it would read after ops: NTAG memory from page 4, Type 5 from block 0, Classic blocks 4-6."""
    mem = bytearray(tag.data.ljust(tag.size, b"\x00"))
    extra = dict(tag.extra)
    for op in ops:
        if op["op"] != "write":
            continue
        b, data = op["block"], op["data"]
        if tag.chip == "classic1k":
            if 4 <= b <= 6:
                mem[(b - 4) * 16:(b - 3) * 16] = data
            elif b == 7:
                extra["keyed"] = True
        else:
            at = (b - 4) * 4 if tag.is_ntag else b * 4
            mem[at:at + len(data)] = data
    return formats.Tag(tag.chip, tag.uid, bytes(mem), tag.size, extra)


class FakeReader:
    """A reader on the desk for the simulator and tests: tags are put down and lifted by hand."""

    name = "Simulated reader"

    def __init__(self) -> None:
        self.tag: Optional[Any] = None
        self.fail_next: Optional[str] = None

    def put(self, tag: Optional[Any]) -> None:
        self.tag = tag

    def write(self, uid: bytes, ops: List[Dict[str, Any]]) -> Tuple[bool, Optional[str], Optional[Any]]:
        if self.tag is None or self.tag.uid != uid:
            return False, "The tag was lifted before it was written. Hold it still and try again.", self.tag
        if self.fail_next:
            why, self.fail_next = self.fail_next, None
            return False, why, self.tag
        self.tag = apply_to_memory(self.tag, ops)
        return True, None, self.tag


# ---- PC/SC through libpcsclite -----------------------------------------------------------------------

SCARD_SCOPE_SYSTEM, SCARD_SHARE_SHARED, SCARD_LEAVE_CARD = 2, 2, 0
SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1 = 1, 2
SCARD_STATE_UNAWARE, SCARD_STATE_CHANGED, SCARD_STATE_PRESENT = 0, 0x2, 0x20
SCARD_E_TIMEOUT, SCARD_E_NO_READERS = 0x8010000A, 0x8010002E


class _ReaderState(ctypes.Structure):
    _fields_ = [("szReader", ctypes.c_char_p), ("pvUserData", ctypes.c_void_p),
                ("dwCurrentState", ctypes.c_ulong), ("dwEventState", ctypes.c_ulong),
                ("cbAtr", ctypes.c_ulong), ("rgbAtr", ctypes.c_ubyte * 33)]


class _IoRequest(ctypes.Structure):
    _fields_ = [("dwProtocol", ctypes.c_ulong), ("cbPciLength", ctypes.c_ulong)]


class PcscError(Exception):
    pass


class Pcsc:
    """The few pcsc-lite calls needed. On Linux, pcsc-lite's DWORD and LONG are C longs."""

    def __init__(self) -> None:
        path = ctypes.util.find_library("pcsclite") or "libpcsclite.so.1"
        self.lib = ctypes.CDLL(path)
        for fn in ("SCardEstablishContext", "SCardListReaders", "SCardGetStatusChange", "SCardConnect",
                   "SCardTransmit", "SCardDisconnect", "SCardReleaseContext"):
            getattr(self.lib, fn).restype = ctypes.c_long
        self.ctx = ctypes.c_long()
        self._check(self.lib.SCardEstablishContext(SCARD_SCOPE_SYSTEM, None, None, ctypes.byref(self.ctx)), "context")

    @staticmethod
    def _check(rv: int, what: str) -> None:
        rv &= 0xFFFFFFFF
        if rv:
            raise PcscError(f"{what}: 0x{rv:08X}")

    def readers(self) -> List[str]:
        n = ctypes.c_ulong(0)
        rv = self.lib.SCardListReaders(self.ctx, None, None, ctypes.byref(n)) & 0xFFFFFFFF
        if rv == SCARD_E_NO_READERS or n.value == 0:
            return []
        self._check(rv, "list readers")
        buf = ctypes.create_string_buffer(n.value)
        self._check(self.lib.SCardListReaders(self.ctx, None, buf, ctypes.byref(n)), "list readers")
        return [r.decode() for r in buf.raw[:n.value].split(b"\x00") if r]

    def wait(self, reader: str, known: int, timeout_ms: int) -> Tuple[int, bytes]:
        """(event state, ATR) once the reader's state differs from known, or the same state after the timeout."""
        st = _ReaderState(reader.encode(), None, known, 0, 0)
        rv = self.lib.SCardGetStatusChange(self.ctx, ctypes.c_ulong(timeout_ms), ctypes.byref(st), ctypes.c_ulong(1))
        rv &= 0xFFFFFFFF
        if rv == SCARD_E_TIMEOUT:
            return known, b""
        self._check(rv, "status")
        return st.dwEventState & ~SCARD_STATE_CHANGED, bytes(st.rgbAtr[:st.cbAtr])

    def connect(self, reader: str) -> "Card":
        h, proto = ctypes.c_long(), ctypes.c_ulong()
        self._check(self.lib.SCardConnect(self.ctx, reader.encode(), SCARD_SHARE_SHARED,
                                          SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1, ctypes.byref(h), ctypes.byref(proto)),
                    "connect")
        return Card(self, h, proto.value)


class Card:
    def __init__(self, pcsc: Pcsc, handle: ctypes.c_long, protocol: int) -> None:
        self.pcsc, self.h, self.protocol = pcsc, handle, protocol

    def apdu(self, cmd: bytes) -> Tuple[bytes, int]:
        pci = _IoRequest(self.protocol, ctypes.sizeof(_IoRequest))
        out = (ctypes.c_ubyte * 258)()
        n = ctypes.c_ulong(len(out))
        send = (ctypes.c_ubyte * len(cmd))(*cmd)
        self.pcsc._check(self.pcsc.lib.SCardTransmit(self.h, ctypes.byref(pci), send, ctypes.c_ulong(len(cmd)), None,
                                                     out, ctypes.byref(n)), "transmit")
        raw = bytes(out[:n.value])
        if len(raw) < 2:
            return b"", 0
        return raw[:-2], (raw[-2] << 8) | raw[-1]

    def ok(self, cmd: bytes) -> Optional[bytes]:
        data, sw = self.apdu(cmd)
        return data if sw == 0x9000 else None

    def close(self) -> None:
        self.pcsc.lib.SCardDisconnect(self.h, SCARD_LEAVE_CARD)


def chip_from_atr(atr: bytes) -> Optional[str]:
    """PC/SC Part 3 storage-card ATR: 3B 8F 80 01 80 4F 0C A0 00 00 03 06 <standard> <card name, 2 bytes>."""
    if len(atr) < 15 or atr[7:12] != bytes.fromhex("A000000306"):
        return None
    standard, name = atr[12], int.from_bytes(atr[13:15], "big")
    if name in (0x0001, 0x0002):
        return "classic1k"
    if standard == 0x03:
        return "ultralight"     # NTAG21x report as Ultralight; the capability container says which
    if standard in (0x0B, 0x0C):
        return "iso15693"
    return None


def read_card(card: Card, atr: bytes) -> Optional[Any]:
    uid = card.ok(b"\xff\xca\x00\x00\x00") or b""
    kind = chip_from_atr(atr)
    if kind == "classic1k":
        return _read_classic(card, uid)
    if kind in ("ultralight", None):
        cc = card.ok(b"\xff\xb0\x00\x03\x04")
        if cc and len(cc) >= 4 and cc[0] == 0xE1 and cc[2] in NTAG_BY_CC:
            chip = NTAG_BY_CC[cc[2]]
            size = formats.NTAG[chip]
            data = b""
            for page in range(4, 4 + size // 4, 4):
                chunk = card.ok(bytes([0xFF, 0xB0, 0x00, page, 0x10])) or b""
                data += chunk[:16].ljust(16, b"\x00")
            return formats.Tag(chip, uid, data[:size])
    if kind in ("iso15693", None):
        first = card.ok(b"\xff\xb0\x00\x00\x04")
        if first is not None:
            size = first[2] * 8 if first[:1] in (b"\xe1", b"\xe2") and first[2] else formats.SLIX2_BYTES
            data = bytearray(first[:4])
            for block in range(1, size // 4):
                data += (card.ok(bytes([0xFF, 0xB0, 0x00, block, 0x04])) or b"\x00" * 4)[:4]
            return formats.Tag("slix2" if size == formats.SLIX2_BYTES else "iso15693", uid, bytes(data), size)
    return None


def _auth(card: Card, block: int, key: bytes, slot: int = 0, key_type: int = 0x60) -> bool:
    if card.ok(bytes([0xFF, 0x82, 0x00, slot, 0x06]) + key) is None:
        return False
    return card.ok(bytes([0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, block, key_type, slot])) is not None


def _read_classic(card: Card, uid: bytes) -> Any:
    for keyed, key in ((False, formats.CFS_DEFAULT_KEY), (True, formats.cfs_key(uid))):
        if _auth(card, 4, key):
            data = b"".join((card.ok(bytes([0xFF, 0xB0, 0x00, b, 0x10])) or bytes(16))[:16] for b in (4, 5, 6))
            trailer = card.ok(b"\xff\xb0\x00\x07\x10") or b""
            extra = {"keyed": keyed}
            if len(trailer) >= 10:
                extra["access"] = trailer[6:10]
            return formats.Tag("classic1k", uid, data, 48, extra)
    return formats.Tag("classic1k", uid, b"", 48, {"keyed": None, "locked": True})


def write_card(card: Card, tag: Any, ops: List[Dict[str, Any]]) -> Optional[str]:
    for op in ops:
        if op["op"] == "auth":
            if not _auth(card, op["block"], op["key"], 0, op.get("key_type", 0x60)):
                return "The tag wouldn't let Bench in. It may be locked by another app."
        elif tag.chip == "classic1k":
            if card.ok(bytes([0xFF, 0xD6, 0x00, op["block"], 0x10]) + op["data"]) is None:
                return f"Writing block {op['block']} failed."
        else:
            if card.ok(bytes([0xFF, 0xD6, 0x00, op["block"], 0x04]) + op["data"]) is None:
                return f"Writing page {op['block']} failed. The tag may be locked."
    return None


class ReaderThread(threading.Thread):
    """Watches the first reader pcscd knows, reads each tag put on it, runs writes asked for with write()."""

    def __init__(self, emit: Emit, fake: Optional[FakeReader] = None) -> None:
        super().__init__(name="spool-tags", daemon=True)
        self.emit, self.fake = emit, fake
        self.requests: "queue.Queue[tuple]" = queue.Queue()
        self.stopping = False
        self._tag: Optional[Any] = None

    def write(self, uid: bytes, ops: List[Dict[str, Any]]) -> None:
        self.requests.put((uid, ops))

    def stop(self) -> None:
        self.stopping = True

    def run(self) -> None:
        if self.fake is not None:
            return self._run_fake()
        try:
            pcsc = Pcsc()
        except (OSError, PcscError) as e:
            logging.info("spool tags: no pcscd (%s), so no tag reader", e)
            self.emit("reader", None, "missing", None)
            return
        reader, state, last_list = None, SCARD_STATE_UNAWARE, 0.0
        while not self.stopping:
            try:
                if reader is None:
                    if time.monotonic() - last_list < RELIST_SECONDS:
                        time.sleep(0.5)
                        continue
                    last_list = time.monotonic()
                    names = pcsc.readers()
                    reader = names[0] if names else None
                    self.emit("reader", reader, "ready" if reader else "missing", None)
                    state = SCARD_STATE_UNAWARE
                    continue
                self._serve_writes(pcsc, reader)
                new, atr = pcsc.wait(reader, state, POLL_MS)
                if new == state:
                    continue
                present = bool(new & SCARD_STATE_PRESENT)
                state = new   # the whole state, event counter too, or pcscd answers at once every time
                if present and atr:
                    self._read(pcsc, reader, atr)
                elif not present and self._tag is not None:
                    self._tag = None
                    self.emit("tag", None)
            except PcscError as e:
                logging.info("spool tags: reader %s: %s", reader, e)
                reader, self._tag = None, None
                self.emit("reader", None, "missing", None)
            except Exception:
                logging.exception("spool tags: reader loop")
                time.sleep(1.0)

    def _read(self, pcsc: Pcsc, reader: str, atr: bytes) -> None:
        card = pcsc.connect(reader)
        try:
            self._tag = read_card(card, atr)
            self._atr = atr
        finally:
            card.close()
        self.emit("tag", self._tag)

    def _serve_writes(self, pcsc: Pcsc, reader: str) -> None:
        while not self.requests.empty():
            uid, ops = self.requests.get_nowait()
            if self._tag is None or self._tag.uid != uid:
                self.emit("written", False, "Put the tag back on the reader and try again.", self._tag)
                continue
            card = pcsc.connect(reader)
            try:
                why = write_card(card, self._tag, ops)
            finally:
                card.close()
            card = pcsc.connect(reader)
            try:
                self._tag = read_card(card, self._atr) or self._tag
            finally:
                card.close()
            self.emit("written", why is None, why, self._tag)

    def _run_fake(self) -> None:
        self.emit("reader", self.fake.name, "ready", None)
        seen: Optional[bytes] = None
        while not self.stopping:
            uid = self.fake.tag.uid if self.fake.tag is not None else None
            if uid != seen:
                seen = uid
                self.emit("tag", self.fake.tag)
            while not self.requests.empty():
                uid, ops = self.requests.get_nowait()
                ok, why, tag = self.fake.write(uid, ops)
                self.emit("written", ok, why, tag)
            time.sleep(0.2)
