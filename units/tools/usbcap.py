#!/usr/bin/env python3
"""Passive USB capture via the kernel's binary usbmon interface. Writes JSONL: one bulk transfer per line."""
import json, os, struct, sys, time

bus, dev, seconds, out = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
HDR = struct.Struct("<QBBBBHbbqiiII8s")
fd = os.open(f"/dev/usbmon{bus}", os.O_RDONLY)
end = time.time() + seconds
with open(out, "w") as f:
    while time.time() < end:
        buf = os.read(fd, HDR.size + 65536)
        (_id, typ, xfer, ep, devnum, _bus, _fs, _fd, sec, usec, status, length, cap, _s) = HDR.unpack_from(buf)
        data = buf[HDR.size:HDR.size + cap]
        if devnum != dev or xfer != 3 or not data:
            continue
        f.write(json.dumps({"t": sec + usec / 1e6, "dir": "in" if ep & 0x80 else "out",
                            "ev": chr(typ), "hex": data.hex()}) + "\n")
        f.flush()
