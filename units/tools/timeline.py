#!/usr/bin/env python3
"""Timeline of a capture: every frame that isn't a routine get_status, plus get_status fields as they change."""
import json, sys
from decode import frames

cap, markers = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None
rows = [json.loads(l) for l in open(cap)]
events = [(t, "->", json.loads(p)) for t, p, *_ in frames(rows, "out")]
events += [(t, "<-", json.loads(p)) for t, p, *_ in frames(rows, "in")]
if markers:
    events += [(m["t"], "##", m) for m in map(json.loads, open(markers))]
events.sort(key=lambda e: e[0])

status_ids, last, t0 = set(), {}, events[0][0]


def flat(v, prefix=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from flat(x, f"{prefix}{k}.")
    elif isinstance(v, list) and v and isinstance(v[0], dict):
        for i, x in enumerate(v):
            yield from flat(x, f"{prefix}{i}.")
    else:
        yield prefix.rstrip("."), v


for t, d, m in events:
    stamp = f"{t - t0:8.3f}"
    if d == "->" and m.get("method") == "get_status":
        status_ids.add(m["id"])
        continue
    if d == "<-" and m.get("id") in status_ids:
        now = dict(flat(m.get("result", {})))
        changed = {k: v for k, v in now.items() if last.get(k) != v}
        if last and changed:
            print(stamp, "~~", json.dumps(changed))
        last = now
        continue
    print(stamp, d, json.dumps(m))
