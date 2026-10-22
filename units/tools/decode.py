#!/usr/bin/env python3
"""Reassemble ACE frames from a usbcap.py JSONL capture; identify the checksum; summarize methods and fields."""
import collections, json, sys


def crc16(data, poly, init, refin, refout, xorout):
    def rev(v, n):
        return int(f"{v:0{n}b}"[::-1], 2)
    crc = init
    for b in data:
        if refin:
            b = rev(b, 8)
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    if refout:
        crc = rev(crc, 16)
    return crc ^ xorout


CANDIDATES = {
    "CRC-16/MCRF4XX": (0x1021, 0xFFFF, True, True, 0x0000),
    "CRC-16/X-25": (0x1021, 0xFFFF, True, True, 0xFFFF),
    "CRC-16/KERMIT": (0x1021, 0x0000, True, True, 0x0000),
    "CRC-16/CCITT-FALSE": (0x1021, 0xFFFF, False, False, 0x0000),
    "CRC-16/XMODEM": (0x1021, 0x0000, False, False, 0x0000),
    "CRC-16/MODBUS": (0x8005, 0xFFFF, True, True, 0x0000),
    "CRC-16/ARC": (0x8005, 0x0000, True, True, 0x0000),
}


def frames(rows, direction):
    stream = bytearray()
    for r in rows:
        if r["dir"] == direction and (direction == "in") == (r["ev"] == "C"):
            stream += bytes.fromhex(r["hex"])
            while True:
                i = stream.find(b"\xff\xaa")
                if i < 0 or len(stream) < i + 4:
                    break
                n = int.from_bytes(stream[i + 2:i + 4], "little")
                if len(stream) < i + 4 + n + 3:
                    break
                payload, check, tail = bytes(stream[i + 4:i + 4 + n]), bytes(stream[i + 4 + n:i + 6 + n]), stream[i + 6 + n]
                yield r["t"], payload, check, tail
                del stream[:i + 7 + n]


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__


if __name__ == "__main__":
    rows = [json.loads(l) for f in sys.argv[1:] for l in open(f)]
    out = {d: list(frames(rows, d)) for d in ("out", "in")}
    print({d: len(v) for d, v in out.items()})

    for name, p in CANDIDATES.items():
        ok = sum(crc16(pl, *p).to_bytes(2, "little") == ck for d in out for _, pl, ck, _ in out[d])
        total = sum(len(v) for v in out.values())
        if ok:
            print(f"checksum {name} (little-endian): {ok}/{total}")
    print("tails:", collections.Counter(t for d in out for *_, t in out[d]))

    methods = collections.Counter()
    reqs = {}
    for t, pl, *_ in out["out"]:
        m = json.loads(pl)
        methods[m.get("method")] += 1
        reqs[m["id"]] = (t, m)
    print("methods:", dict(methods))
    lat = []
    for t, pl, *_ in out["in"]:
        m = json.loads(pl)
        if m.get("id") in reqs:
            lat.append((t - reqs[m["id"]][0]) * 1000)
    if lat:
        lat.sort()
        print(f"reply time ms: min {lat[0]:.1f} median {lat[len(lat)//2]:.1f} max {lat[-1]:.1f}")
    ts = [t for t, *_ in out["out"]]
    if len(ts) > 1:
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        print(f"poll gap s: median {gaps[len(gaps)//2]:.3f}")
    for t, pl, *_ in out["out"][:3]:
        print("REQ", pl.decode())
    seen = set()
    for t, pl, *_ in out["in"]:
        m = json.loads(pl)
        key = json.dumps(shape(m), sort_keys=True)
        if key not in seen:
            seen.add(key)
            print("REPLY SHAPE", key)
            print("REPLY SAMPLE", pl.decode()[:1500])
