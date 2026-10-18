#!/usr/bin/env python3
"""The power button turns the printer off the way Care's Turn off does (design/power/, A): the nozzle cools first,
then the Pi halts, and the panel going dark says it's safe to switch off. A second press while it waits means now.

    python3 printer/power_key.py --moonraker http://127.0.0.1:7125

The installer's "power button" step runs this as elyir-bench-power-key.service and tells logind to ignore a short press
of the key (a long press still halts at once). The button is any input device with KEY_POWER that's named as one (the
Pi 5's pwr_button). Where Moonraker doesn't answer (a Bench Box, which has no nozzle, or Moonraker down), a press
powers off at once, which is what the key did before. Standard library only.
"""
import argparse
import json
import logging
import os
import struct
import subprocess
import time
import urllib.request
from typing import Any, Dict, Optional

EV_KEY, KEY_POWER = 1, 116
EVENT = struct.Struct("llHHi")      # struct input_event: timeval, type, code, value
NAMES = ("pwr_button", "power button")   # the Pi 5's, and what most PCs' ACPI buttons are called
DEBOUNCE = 1.5                      # seconds: one press, however the switch bounces


def find_button(sys_input: str = "/sys/class/input") -> Optional[str]:
    """The /dev/input/eventN of the power button, or None."""
    try:
        entries = sorted(os.listdir(sys_input))
    except OSError:
        return None
    for e in entries:
        if not e.startswith("event"):
            continue
        try:
            with open(os.path.join(sys_input, e, "device", "name")) as f:
                name = f.read().strip().lower()
        except OSError:
            continue
        if any(n in name for n in NAMES):
            return f"/dev/input/{e}"
    return None


def decide(intent: Optional[Dict[str, Any]]) -> str:
    """What a press means, from the printer's intent (None: Moonraker didn't answer):
    'off' (start turning off), 'now' (already waiting: don't), 'nothing' (printing: the press is ignored, and a long
    press still forces it), or 'halt' (no printer to cool: power off at once)."""
    if intent is None:
        return "halt"
    power = intent.get("power")
    if not isinstance(power, dict):
        return "halt"           # an intent layer older than design/power/: the key does what it always did
    if power.get("kind") == "off" and not power.get("going"):
        return "now"
    if power.get("kind"):
        return "nothing"        # restarting, or already going
    return "off" if power.get("allowed") else "nothing"


def ask(url: str, path: str, body: Optional[Dict[str, Any]] = None, timeout: float = 4) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null").get("result")


def press(url: str) -> str:
    try:
        intent = ask(url, "/printer/intent")
    except Exception:
        intent = None
    what = decide(intent)
    logging.info("power button: %s", what)
    if what in ("off", "now"):
        try:
            ask(url, "/printer/intent/action", {"action": "power_off" if what == "off" else "power_now",
                                                 "source": "power button"})
        except Exception as e:
            logging.warning("power button: the printer didn't take it (%s); powering off", e)
            what = "halt"
    if what == "halt":
        subprocess.run(["sudo", "-n", "systemctl", "poweroff"], check=False)
    return what


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--moonraker", default="http://127.0.0.1:7125")
    ap.add_argument("--device", help="the button's /dev/input/eventN (found by name if not given)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    device = a.device or find_button()
    if not device:
        logging.info("power button: none here")
        while True:             # nothing to listen to; stay up so systemd doesn't keep restarting it
            time.sleep(3600)
    last = 0.0
    with open(device, "rb") as f:
        logging.info("power button: listening on %s", device)
        while True:
            data = f.read(EVENT.size)
            if len(data) < EVENT.size:
                continue
            _, _, etype, code, value = EVENT.unpack(data)
            if etype == EV_KEY and code == KEY_POWER and value == 1 and time.monotonic() - last > DEBOUNCE:
                last = time.monotonic()
                press(a.moonraker)


if __name__ == "__main__":
    main()
