"""
Bring it over (docs/bring-it-over.md, design/printer-setup/ A), as the simulator plays it.

The state behind GET /printer/intent/bring and its actions (bring_scan, bring_plan, bring_address, bring_apply).
sim.py runs the timed parts (looking, planning, the copy and Klipper's restart) and publishes the intent;
this file keeps the state and says what the printer's component would answer.

What the simulator pretends is there (setup_printer): an old card in a USB reader with a Voron's setup from 3 October
(19 config files, 46 G-code files, 212 prints, the same boards as the ones plugged in), and Studio on the Wi-Fi
(Elyir Bench, changed two hours ago, whose main board has another serial and whose toolhead board isn't plugged in here).
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

ACTIONS = ("bring_scan", "bring_plan", "bring_address", "bring_apply", "bring_cloud_ask", "bring_cloud_check",
           "bring_cloud_email", "bring_cloud_code")

SCAN_S = 1.2           # looking at the USB devices and the Wi-Fi
PLAN_S = 0.8           # reading a source's config and comparing the boards
STEP_S = 1.4           # each step of bringing it over, in real seconds

# What this Pi sees plugged in (a-start's chips): the contract leaves these to the component; see docs/bring-it-over.md
FOUND = ["Main board · STM32F446 on USB", "Toolhead board · on CAN", "ACE Pro", "Camera"]

CARD_WHEN = datetime(2026, 10, 3, 21, 14).timestamp()

# Bench Cloud (docs/cloud.md, design/cloud/ C): the owner taps Allow this long after being asked, unless the email's
# code comes first; the code that works
CLOUD_ALLOW_S = 12.0
CLOUD_CODE = "482913"


def card_source() -> Dict[str, Any]:
    return {"id": "card-sda2", "kind": "card", "name": "Voron", "detail": "In a USB reader", "when": CARD_WHEN,
            "files": 19, "gcodes": 46, "history": 212, "boards": ["stm32f446xx", "can 6cc850bbec73"]}


def studio_source(now: float) -> Dict[str, Any]:
    return {"id": "printer-studio", "kind": "printer", "name": "Studio", "detail": "Elyir Bench", "when": now - 2 * 3600,
            "files": 14, "gcodes": 23, "history": 96, "boards": ["stm32f446xx", "can 1f0e5a2c9b11"]}


def cloud_source(now: float, name: str = "Workshop") -> Dict[str, Any]:
    night = datetime.fromtimestamp(now).replace(hour=2, minute=10, second=0).timestamp()
    return {"id": "cloud-p-" + name.lower(), "kind": "cloud", "name": name, "detail": "Your Bench Cloud backup",
            "when": night if night < now else night - 86400, "files": None, "gcodes": None, "history": None, "boards": [],
            "owner_phone": "Alex's iPhone", "owner_email": "a•••x@example.net"}


PLANS: Dict[str, Dict[str, Any]] = {
    "card-sda2": {"config": 19, "history": 212, "spools": True, "mainsail": True,
                  "gcodes": {"count": 46, "bytes": 812_000_000},
                  "boards": [{"name": "Main board", "chip": "stm32f446xx", "match": "same"},
                             {"name": "Toolhead board", "can": "6cc850bbec73", "match": "same"}]},
    "printer-studio": {"config": 14, "history": 96, "spools": True, "mainsail": True,
                       "gcodes": {"count": 23, "bytes": 301_000_000},
                       "boards": [{"name": "Main board", "chip": "stm32f446xx", "match": "changed"},
                                  {"name": "Toolhead board", "can": "1f0e5a2c9b11", "match": "missing"}]},
}


def host_name(address: str) -> str:
    """'voron.local:7125' -> 'voron'; an IP address stays as typed."""
    host = re.sub(r"^\w+://", "", address.strip()).split("/")[0]
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if re.fullmatch(r"[\d.]+", host):
        return host
    return host.split(".")[0]


class Bring:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.no_config = False        # Klipper can't start: no printer.cfg (the intent says setup)
        self.state = "idle"
        self.sources: List[Dict[str, Any]] = []
        self.hidden: List[Dict[str, Any]] = []   # what the next scan finds (a card plugged in, a file sent)
        self.files: List[Dict[str, Any]] = []     # backups sent from a phone: config/elyir-bench-bring/<name>
        self.plan: Optional[Dict[str, Any]] = None
        self.progress: Optional[Dict[str, Any]] = None
        self.result: Optional[Dict[str, Any]] = None
        self.why: Optional[str] = None
        self.found: List[str] = []
        self.boards: Optional[int] = None         # printer boards plugged in (design/role/)
        self.role: Optional[Dict[str, Any]] = None   # becoming a Bench Box: {state, progress, why, url}
        self.cloud: Optional[Dict[str, Any]] = None  # a Bench Cloud backup being asked for (docs/cloud.md)

    def fresh_card(self, now: float, cloud: bool = False) -> None:
        """setup_printer: a fresh card, an old one in a reader, Studio on the Wi-Fi; setup_cloud: and its Bench Cloud backup."""
        self.reset()
        self.no_config = True
        self.found = list(FOUND)
        self.boards = 2
        self.sources = [card_source(), studio_source(now)] + ([cloud_source(now)] if cloud else [])
        self.hidden = list(self.sources)

    # ---- GET /printer/intent/bring -----------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {"state": self.state, "sources": deepcopy(self.sources), "plan": deepcopy(self.plan),
                "progress": deepcopy(self.progress), "result": deepcopy(self.result), "why": self.why,
                "found": list(self.found), "boards": self.boards, "role": deepcopy(self.role), "cloud": deepcopy(self.cloud)}

    # ---- the steps sim.py drives -----------------------------------------------------------------

    def source(self, sid: str) -> Optional[Dict[str, Any]]:
        return next((s for s in self.sources if s["id"] == sid), None)

    def refusal(self, action: str, args: Dict[str, Any], printing: bool) -> Optional[str]:
        if self.state == "bringing":
            return "It's already bringing one over."
        if action == "bring_apply" and printing:
            return "Not while it prints."
        if action in ("bring_plan", "bring_apply") and not self.source(str(args.get("id", ""))):
            return "That one isn't there any more. Look again."
        if action == "bring_address" and not str(args.get("address") or "").strip():
            return "Type the printer's address, like voron.local."
        if action == "bring_cloud_ask" and (self.source(str(args.get("id", ""))) or {}).get("kind") != "cloud":
            return "That isn't a Bench Cloud backup."
        if action in ("bring_cloud_email", "bring_cloud_code") and not self.cloud:
            return "Nothing is being asked for. Pick the backup again."
        if action == "bring_cloud_code" and "".join(c for c in str(args.get("code") or "") if c.isdigit()) != CLOUD_CODE:
            return "That code isn't right, or it has run out. Ask for a new one."
        return None

    # ---- a Bench Cloud backup (docs/cloud.md) -------------------------------------------------------

    def cloud_ask(self, sid: str) -> None:
        s = self.source(sid) or {}
        self.cloud = {"id": sid, "name": s.get("name"), "state": "waiting", "owner_phone": s.get("owner_phone"),
                      "owner_email": s.get("owner_email"), "emailed": None}

    def cloud_emailed(self) -> None:
        self.cloud["emailed"] = self.cloud.get("owner_email")

    def cloud_allowed(self, now: float) -> None:
        """The owner said yes: the backup is a backup file here, planned and brought like any other."""
        if not self.cloud or self.cloud["state"] != "waiting":
            return
        name = f"{self.cloud['name'].lower()}-bench-cloud.tar.gz"
        self.add_file(name, 0, now)
        sid = "file-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        self.files[-1].update(name=self.cloud["name"], history=212, files=19)
        PLANS[sid] = dict(PLANS["card-sda2"], gcodes=None)
        self.hidden = [s for s in self.hidden if s.get("kind") != "cloud"]
        self.sources = [s for s in self.sources if s["id"] != sid] + [deepcopy(self.files[-1])]
        self.cloud.update(state="allowed", file=sid)

    def scanned(self) -> None:
        self.sources = sorted(self.hidden + self.files, key=lambda s: -(s.get("when") or 0))
        self.state = "idle"

    def add_file(self, name: str, size: int, now: float) -> None:
        """A backup sent from the phone, uploaded to config/elyir-bench-bring/<name>: the next scan lists it."""
        sid = "file-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        self.files = [f for f in self.files if f["id"] != sid] + [
            {"id": sid, "kind": "file", "name": name, "detail": "A backup file", "when": now,
             "files": 17, "gcodes": 0, "history": 140, "boards": ["stm32f446xx"]}]
        PLANS[sid] = {"config": 17, "history": 140, "spools": True, "mainsail": False, "gcodes": None,
                      "boards": [{"name": "Main board", "chip": "stm32f446xx", "match": "same"}]}

    def add_address(self, address: str, now: float) -> Optional[Dict[str, Any]]:
        """A printer typed in by address. 'nothing' anywhere in it plays one that doesn't answer."""
        if "nothing" in address.lower():
            return None
        name = host_name(address)
        sid = "printer-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        src = {"id": sid, "kind": "printer", "name": name, "detail": f"At {address.strip()}", "when": now - 26 * 3600,
               "files": 11, "gcodes": 8, "history": 31, "boards": ["stm32f446xx"]}
        PLANS[sid] = {"config": 11, "history": 31, "spools": False, "mainsail": True,
                      "gcodes": {"count": 8, "bytes": 64_000_000},
                      "boards": [{"name": "Main board", "chip": "stm32f446xx", "match": "same"}]}
        self.hidden = [s for s in self.hidden if s["id"] != sid] + [src]
        self.sources = [s for s in self.sources if s["id"] != sid] + [src]
        return src

    def planned(self, sid: str) -> None:
        self.plan = dict(deepcopy(PLANS[sid]), id=sid)
        self.state = "idle"

    def failed(self, why: str) -> None:
        self.state, self.why, self.progress = "failed", why, None

    def steps(self, gcodes: bool) -> List[str]:
        out = ["Keeping the config it had", "Copying the config", "Bringing the history and spools"]
        if gcodes:
            out.append("Copying the files")
        return out + ["Restarting Klipper"]

    def done(self, kind: str) -> None:
        where = {"card": "your old card", "printer": "the other printer", "file": "your backup", "cloud": "your backup"}.get(kind, "it")
        self.state, self.progress, self.no_config = "done", None, False
        self.result = {"klipper": "ready", "message": f"Klipper is running with the config from {where}."}

