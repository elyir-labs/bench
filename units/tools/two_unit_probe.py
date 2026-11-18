"""Two units on one printer: does feed assist on the head's slot carry on while a slot on the other unit feeds and
retracts? Runs on the printer against the running service, stdlib only. Every move is undone.

usage: python3 two_unit_probe.py <slot to move> <out.jsonl> [--same-unit <slot>]

--same-unit also moves a slot on the head's unit, which should end its feed assist (captures/2026-10-18-moves.jsonl);
feed assist is started again on the head's slot afterwards.
"""
import argparse
import asyncio
import json
import os
import sys
import time

SOCK = os.environ.get("ELYIR_UNITS_SOCK") or os.path.expanduser("~/printer_data/comms/elyir-units.sock")
MM = 30
SAMPLE_S = 0.15
MOVING = ("shifting", "feeding", "unwinding")


class Client:
    def __init__(self) -> None:
        self.rid = 0
        self.lock = asyncio.Lock()

    async def open(self) -> None:
        self.reader, self.writer = await asyncio.open_unix_connection(SOCK)

    async def call(self, method: str, **params):
        async with self.lock:
            self.rid += 1
            self.writer.write((json.dumps({"id": self.rid, "method": method, "params": params}) + "\n").encode())
            await self.writer.drain()
            while True:
                m = json.loads(await asyncio.wait_for(self.reader.readline(), 150))
                if m.get("id") == self.rid:
                    if "error" in m:
                        raise RuntimeError(f"{method} {params}: {m['error']['message']}")
                    return m["result"]


def where(state, slot):
    for u in state["units"]:
        if u["offset"] <= slot < u["offset"] + u["n"]:
            return u["index"]
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slot", type=int)
    ap.add_argument("out")
    ap.add_argument("--same-unit", type=int)
    args = ap.parse_args()

    ctl, watch = Client(), Client()
    await ctl.open()
    await watch.open()
    try:
        await ctl.call("raw")
    except RuntimeError:
        print("REFUSED: this service has no raw method yet; deploy a release from main first")
        return 3
    st = await ctl.call("state")
    head = st["selected"]
    units = [u for u in st["units"] if u["connected"]]
    problems = []
    if len(st["units"]) != 2 or len(units) != 2:
        problems.append(f"need two connected units, the service has {len(units)} of {len(st['units'])}")
    if head is None:
        problems.append("the service doesn't know which slot is in the head")
    elif not st["feed_assist"][head]:
        problems.append(f"feed assist isn't on for slot {head + 1} in the head (turn it on from the screen first)")
    for name, s in (("slot", args.slot), ("--same-unit", args.same_unit)):
        if s is None:
            continue
        if not 0 <= s < len(st["slots"]):
            problems.append(f"{name} {s + 1}: no such slot")
        elif s == head:
            problems.append(f"{name} {s + 1} is the slot in the head")
        elif st["slots"][s]["status"] != "ready":
            problems.append(f"{name} {s + 1} is {st['slots'][s]['status']}, not ready")
    if not problems:
        if where(st, args.slot) == where(st, head):
            problems.append(f"slot {args.slot + 1} is on the head's unit; pick one on the other unit")
        if args.same_unit is not None and where(st, args.same_unit) != where(st, head):
            problems.append(f"--same-unit {args.same_unit + 1} isn't on the head's unit")
    if problems:
        print("REFUSED: " + "; ".join(problems))
        return 3

    hu = where(st, head)
    log = open(args.out, "w")
    phase = ["start"]
    seen = []

    def note(**kw):
        kw["t"] = time.time()
        log.write(json.dumps(kw) + "\n")
        log.flush()

    async def sample():
        last = None
        while True:
            raw = await watch.call("raw", now=True)
            note(ev="raw", phase=phase[0], units=raw)
            h = raw[hu]["status"]
            key = tuple((u["status"].get("status"), u["status"].get("action"), u["status"].get("feed_assist_count"))
                        for u in raw)
            moving = h.get("status") == "busy" or any(sl.get("status") in MOVING for sl in h.get("slots") or [])
            seen.append((phase[0], moving, h.get("feed_assist_count")))
            if key != last:
                print(f"{time.strftime('%H:%M:%S')} {phase[0]:<14} " +
                      "  ".join(f"unit {i + 1}: {s} {a or '-'} assist#{c}" for i, (s, a, c) in enumerate(key)))
                last = key
            await asyncio.sleep(SAMPLE_S)

    async def step(name, slot, mm):
        phase[0] = name
        note(ev="cmd", phase=name, slot=slot, mm=mm)
        t0 = time.time()
        await ctl.call("move", slot=slot, mm=mm, wait=True)
        note(ev="done", phase=name, seconds=round(time.time() - t0, 2))

    print(f"head: slot {head + 1} on unit {hu + 1}, feed assist on; moving slot {args.slot + 1} "
          f"on unit {where(st, args.slot) + 1}, {MM} mm each way")
    sampler = asyncio.create_task(sample())
    failed = None
    try:
        phase[0] = "baseline"
        await asyncio.sleep(2)
        base = sorted({c for p, a, c in seen if p == "baseline"}, key=str)
        if not base or 0 in base or None in base:
            sampler.cancel()
            print(f"\nREFUSED: the head unit's feed assist count was {base} before anything moved, so it isn't "
                  "assisting. Turn feed assist off and on from the screen, then run again.")
            return 3
        await step("other-feed", args.slot, MM)
        await step("other-unwind", args.slot, -MM)
        phase[0] = "settle"
        await asyncio.sleep(2)
        if args.same_unit is not None:
            await step("same-feed", args.same_unit, MM)
            await step("same-unwind", args.same_unit, -MM)
            phase[0] = "assist-again"
            await ctl.call("feed_assist", slot=head, on=True)
            await asyncio.sleep(2)
    except Exception as e:
        failed = e
    finally:
        sampler.cancel()
        try:
            await sampler
        except asyncio.CancelledError:
            pass

    other = [(m, c) for p, m, c in seen if p.startswith("other")]
    kept = bool(other) and all(c not in (0, None) for _, c in other)
    still = bool(other) and not any(m for m, _ in other)
    print()
    print(f"other unit's moves: {'done' if not failed else 'FAILED: ' + str(failed)}")
    print(f"head unit's feed assist through them: {'kept' if kept else 'LOST'} "
          f"(count {sorted({str(c) for _, c in other})}), head unit {'stayed still' if still else 'MOVED'}")
    if args.same_unit is not None:
        same = [c for p, a, c in seen if p.startswith("same")]
        print(f"same-unit move: feed assist count {sorted({str(c) for c in same})} (0 = ended, as captured)")
    final = await ctl.call("state")
    print(f"feed assist on slot {head + 1} now (service): {final['feed_assist'][head]}")
    return 0 if (kept and still and not failed) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
