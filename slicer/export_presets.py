#!/usr/bin/env python3
"""Freeze a printer's presets as the person's own Orca resolves them, for the printer to slice with.

    export_presets.py --config slicer.example.json --printer workshop --out /tmp/workshop-presets

The printer runs its own Orca, whose bundled defaults can differ from the desktop Orca the presets were
made in. On workshop (3 October 2026) Orca 2.4.2's Voron machine defaults gave END_PRINT instead of
PRINT_END (so nothing parked), 5 mm retraction instead of 0.8, and 500 mm/s² instead of 20 000. Writing
each preset fully resolved, with no parent left to fill in, makes the printer slice exactly as the desktop
does. Copy the folder to printer_data/config/elyir-bench-slicer/presets/0-resolved/ (it sorts first, so it
wins) and restart elyir-bench-slicer.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elyir_bench_slice as sl  # noqa: E402


def export(config: dict, printer_id: str, out: str) -> list[str]:
    presets = sl.Presets(config["profiles"])
    p = config["printers"][printer_id]
    names = [p["machine"], p["process"], *p["materials"].values()]
    os.makedirs(out, exist_ok=True)
    written = []
    for name in names:
        flat = presets.resolve(name)               # every parent folded in; no inherits left
        flat["name"] = name
        path = os.path.join(out, name.replace("/", "_") + ".json")
        with open(path, "w") as f:
            json.dump(flat, f, indent=1, sort_keys=True)
        written.append(path)
    with open(os.path.join(out, "README.txt"), "w") as f:
        f.write(f"Resolved from the Orca presets on {socket.gethostname()}, "
                f"{datetime.date.today().isoformat()}, by slicer/export_presets.py.\n"
                "Each file is complete: the printer's own Orca defaults no longer fill anything in.\n"
                "Regenerate after changing these presets in Orca on the desktop.\n")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, help="a slicer config whose profiles point at the desktop's Orca")
    ap.add_argument("--printer", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(os.path.expanduser(a.config)) as f:
        config = json.load(f)
    for path in export(config, a.printer, a.out):
        print(path)


if __name__ == "__main__":
    main()
