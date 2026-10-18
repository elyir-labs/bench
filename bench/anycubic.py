"""Anycubic printers on the Wi-Fi, for the Bench Box to speak for (design/bench-kobra/, A).

A Kobra announces nothing (no mDNS). It's found by its own ports: Anycubic's service on 18088 answers on every
one, its LAN mode adds 18910 (/info names the model), and Rinkhals adds Moonraker on 7125, which is what the box's
stand-in needs (bench/standin.py).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from typing import Any, Dict, List, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector

ANYCUBIC_PORT = 18088
LAN_PORT = 18910
MOONRAKER_PORT = 7125
CONNECT_TIMEOUT = 0.6
AT_ONCE = 64             # connection attempts in flight: a small box (or a Mac) allows a few hundred open files

# Rinkhals' model codes and the names in Anycubic's /info, to the slicing profile the box keeps (bench/profiles/)
MODELS = {"K3": "kobra-3", "K3V2": "kobra-3", "K3M": "kobra-3-max",
          "Anycubic Kobra 3": "kobra-3", "Anycubic Kobra 3 V2": "kobra-3", "Anycubic Kobra 3 Max": "kobra-3-max"}
NAMES = {"kobra-3": "Kobra 3", "kobra-3-max": "Kobra 3 Max"}


def own_network() -> Optional[ipaddress.IPv4Network]:
    """The box's /24 on the Wi-Fi, asked of the routing table (nothing is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return ipaddress.ip_network(f"{s.getsockname()[0]}/24", strict=False)
    except OSError:
        return None


async def _open(host: str, port: int) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        w.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def model_of(info: Dict[str, Any]) -> Optional[str]:
    return MODELS.get(str(info.get("modelName") or info.get("model") or "").strip())


def id_of(mac: Optional[str], host: str) -> str:
    """Its Wi-Fi MAC, so it's the same printer at any address and in either mode."""
    tail = re.sub(r"[^0-9a-f]", "", (mac or "").lower())[-6:] or host.replace(".", "-")
    return f"anycubic-{tail}"


async def look(session: ClientSession, host: str) -> Optional[Dict[str, Any]]:
    """One address: an Anycubic or not, and how far it is from being spoken for."""
    if not await _open(host, ANYCUBIC_PORT):
        return None
    lan, info = await _open(host, LAN_PORT), {}
    if lan:
        try:
            async with session.get(f"http://{host}:{LAN_PORT}/info") as r:
                info = json.loads(await r.text()) if r.status == 200 else {}
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            info = {}
    rinkhals, mac = await _open(host, MOONRAKER_PORT), None
    if rinkhals:
        try:
            async with session.get(f"http://{host}:{MOONRAKER_PORT}/machine/system_info") as r:
                sysinfo = ((await r.json()).get("result") or {}).get("system_info") or {}
            for iface in (sysinfo.get("network") or {}).values():
                if iface.get("mac_address"):
                    mac = iface["mac_address"]
                    break
        except (ClientError, OSError, asyncio.TimeoutError, ValueError):
            pass
        if not info:                       # LAN mode off: the bed says which Kobra it is
            try:
                async with session.get(f"http://{host}:{MOONRAKER_PORT}/printer/objects/query?toolhead=axis_maximum") as r:
                    top = (((await r.json()).get("result") or {}).get("status") or {}).get("toolhead", {}).get("axis_maximum") or []
                if top:
                    info = {"modelName": "Anycubic Kobra 3 Max" if float(top[0]) > 300 else "Anycubic Kobra 3"}
            except (ClientError, OSError, asyncio.TimeoutError, ValueError, TypeError):
                pass
    usn = str(info.get("usn") or "")         # "uuid:fdm:A4-E8-8D-80-3E-82": the Wi-Fi's MAC
    mac = mac or (usn.rsplit(":", 1)[-1] if usn else None)
    model = model_of(info)
    name = NAMES.get(model or "", str(info.get("deviceName") or "").replace("Anycubic ", "") or "Anycubic printer")
    # Anycubic's own LAN mode when it's on: nothing installed, and on a Kobra Rinkhals adds little the box can use
    # (design/kobra-lan/; tried on a Kobra 3, 7 October 2026). Rinkhals' Moonraker only with LAN mode off.
    lan = lan and info.get("ctrlType") != "cloud"
    via = "lan" if lan else "moonraker" if rinkhals else None
    why = None if via else "On Anycubic's cloud: turn on LAN mode on its screen"
    return {"id": id_of(mac, host), "name": name, "host": host, "model": model, "mac": mac,
            "rinkhals": rinkhals, "lan": lan, "via": via, "why": why, "version": info.get("version")}


async def find(network: Optional[ipaddress.IPv4Network] = None, hosts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Every Anycubic on the box's /24: a few hundred connection attempts, each given 0.6 s, a few seconds in all."""
    if hosts is None:
        network = network or own_network()
        hosts = [str(h) for h in network.hosts()] if network else []
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(session: ClientSession, host: str) -> Optional[Dict[str, Any]]:
        async with gate:
            return await look(session, host)
    async with ClientSession(connector=TCPConnector(family=socket.AF_INET, limit=AT_ONCE),
                             timeout=ClientTimeout(total=5)) as session:
        found = await asyncio.gather(*(one(session, h) for h in hosts))
    return sorted((f for f in found if f), key=lambda f: f["host"])
