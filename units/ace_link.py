"""One Anycubic ACE Pro over its USB serial port, for asyncio. Written from ace-protocol.md, which was written
from captures of a real unit; never from another ACE project's code."""
import asyncio
import json
import os
import termios
import tty
from typing import Any, Dict, Optional

START, END = b"\xff\xaa", b"\xfe"


def crc16_mcrf4xx(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def encode(msg: Dict[str, Any]) -> bytes:
    payload = json.dumps(msg, separators=(",", ":")).encode()
    return START + len(payload).to_bytes(2, "little") + payload + crc16_mcrf4xx(payload).to_bytes(2, "little") + END


class Decoder:
    """Frames out of a byte stream. A frame with a bad CRC or end byte is dropped, as the unit drops ours."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, data: bytes):
        self.buf += data
        while True:
            i = self.buf.find(START)
            if i < 0:
                del self.buf[:-1]
                return
            del self.buf[:i]
            if len(self.buf) < 4:
                return
            n = int.from_bytes(self.buf[2:4], "little")
            if len(self.buf) < n + 7:
                return
            payload, crc, end = bytes(self.buf[4:4 + n]), self.buf[4 + n:6 + n], self.buf[6 + n:7 + n]
            if end != END or int.from_bytes(crc, "little") != crc16_mcrf4xx(payload):
                del self.buf[:2]
                self.dropped += 1
                continue
            del self.buf[:n + 7]
            try:
                yield json.loads(payload)
            except ValueError:
                self.dropped += 1


class LinkClosed(Exception):
    pass


class Link:
    """Requests and replies over one port, one at a time: the unit missed replies when a second request came
    while one was open (twice on the first day, each as a stop met a status poll). Replies are matched by id;
    the unit sends nothing unasked."""

    def __init__(self, port: str) -> None:
        self.port = port
        self.fd: Optional[int] = None
        self.dec = Decoder()
        self.next_id = 1
        self.pending: Dict[int, asyncio.Future] = {}
        self._turn: Optional[asyncio.Lock] = None

    async def open(self) -> None:
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(fd)
            termios.tcflush(fd, termios.TCIOFLUSH)
        except termios.error:
            pass    # a pseudo-terminal in tests can refuse a flush
        self.fd = fd
        asyncio.get_running_loop().add_reader(fd, self._readable)

    def _readable(self) -> None:
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            self.close()
            return
        if not data:
            self.close()
            return
        for m in self.dec.feed(data):
            fut = self.pending.pop(m.get("id"), None)
            if fut and not fut.done():
                fut.set_result(m)

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 1.0) -> Dict[str, Any]:
        """The unit's reply. Raises asyncio.TimeoutError when it doesn't answer, LinkClosed when the port is gone."""
        if self._turn is None:
            self._turn = asyncio.Lock()
        async with self._turn:
            return await self._call(method, params, timeout)

    async def _call(self, method: str, params: Optional[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
        if self.fd is None:
            raise LinkClosed(self.port)
        rid = self.next_id
        self.next_id = self.next_id % 65535 + 1
        msg: Dict[str, Any] = {"id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            os.write(self.fd, encode(msg))
        except OSError as e:
            self.pending.pop(rid, None)
            self.close()
            raise LinkClosed(self.port) from e
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(self.fd)
        except RuntimeError:
            pass
        os.close(self.fd)
        self.fd = None
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(LinkClosed(self.port))
        self.pending.clear()
