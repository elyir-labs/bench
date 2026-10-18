"""Speaking to an Anycubic printer over its own LAN mode (design/kobra-lan/, B; docs/bench.md).

With LAN mode on, the printer gives its MQTT login to anyone on the Wi-Fi who asks the way Anycubic's slicer does:
GET :18910/info (a token), a POST to its ctrlInfoUrl signed with that token, and the answer, AES-decrypted with it, is
the broker, user, password and a device certificate. Over MQTT (TLS, :9883) it reports what it's doing; it starts,
pauses and stops prints; a file goes to it first over HTTP (its fileUploadurl). Nothing is installed on the printer.

LanUpstream answers what the box's stand-in asks of a printer's Moonraker (standin.Upstream's call()), from those
reports: Klipper-shaped status the engine reads unchanged, and what a Moonraker would keep (the spool, Care, history),
kept on the box. Protocol facts from github.com/chrisfore/anycubic_ha_local (MIT, research/PROTOCOL-VALIDATED.md) and
github.com/rvanderp3/kobra-connect (Apache-2.0), and a real Kobra 3 and Kobra 3 Max, 6 October 2026.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import shutil
import ssl
import string
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData

HERE = Path(__file__).resolve().parent
for _p in (HERE.parent / "printer", HERE / "printer"):
    if _p.is_dir():
        sys.path.insert(0, str(_p))
        break
import orca_profile  # noqa: E402

log = logging.getLogger("lan")

PREFIX = "anycubic/anycubicCloud/v1"
INFO_PORT = 18910
POLL = 3.0              # seconds between info queries: the job's stage is pushed by nothing (anycubic_ha_local)
RECONNECT = 10.0
CALL_TIMEOUT = 10.0
KEEP = 20               # files kept on the box for a Kobra, newest first
MISSES = 3              # info queries unanswered in a row before the printer counts as gone

# The stages of a job (project.state), and what the engine reads for each: getting ready ones as the message a start
# routine would show, then Klipper's print_stats states. Anycubic's "preheating" lasts from the start to the first layer
# (heating, homing, cleaning the nozzle, heating it to print), so it says nothing: the engine follows that by the
# temperatures (a Kobra 3, 6 October 2026). Leveling and the calibrations, when they run, are named.
GETTING_READY = {"preheating": "", "auto_leveling": "Leveling the bed", "vibrating": "Measuring vibration",
                 "flow_calibrating": "Calibrating the flow"}
RUNNING = set(GETTING_READY) | {"printing", "resuming", "resumed", "updated"}
PAUSED = {"pausing", "paused"}
STOPPED = {"stopping", "stoped", "stopped"}
FINISHED = {"finished", "finish"}
OBJECTS = ["webhooks", "print_stats", "virtual_sdcard", "display_status", "pause_resume", "idle_timeout", "heater_bed",
           "extruder", "gcode_move"]


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ── the handshake ──

def sign(token: str, ts: int, nonce: str) -> str:
    return hashlib.md5((hashlib.md5(token[:16].encode()).hexdigest() + str(ts) + nonce).encode()).hexdigest()


def decrypt(blob: str, token: str, local_token: str) -> Dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    dec = Cipher(algorithms.AES(token[16:32].encode()), modes.CBC(local_token.encode()[:16].ljust(16, b"\0"))).decryptor()
    padded = dec.update(base64.b64decode(blob)) + dec.finalize()
    unpad = PKCS7(128).unpadder()
    return json.loads((unpad.update(padded) + unpad.finalize()).decode())


async def handshake(session: ClientSession, host: str, port: int = INFO_PORT) -> Dict[str, Any]:
    """The printer's MQTT login, as Anycubic's slicer gets it. Raises RpcError when LAN mode is off."""
    async with session.get(f"http://{host}:{port}/info") as r:
        info = json.loads(await r.text())
    if info.get("ctrlType") == "cloud":
        raise RpcError(409, "LAN mode is off")
    token, ctrl = info.get("token"), info.get("ctrlInfoUrl")
    if not token or not ctrl:
        raise RpcError(409, "This printer doesn't offer LAN mode's login")
    ts, nonce = int(time.time() * 1000), "".join(random.choices(string.ascii_letters + string.digits, k=6))
    did = "".join(random.choices(string.ascii_uppercase + string.digits, k=32))
    async with session.post(ctrl, params={"ts": ts, "nonce": nonce, "sign": sign(token, ts, nonce), "did": did}) as r:
        got = json.loads(await r.text())
    if got.get("code") != 200:
        raise RpcError(502, f"the printer refused the login: {got.get('message')}")
    data = decrypt(got["data"]["info"], token, got["data"]["token"])
    m = re.match(r"mqtts?://([^:]+):(\d+)", data["broker"])
    return {"host": m.group(1) if m else host, "port": int(m.group(2)) if m else 9883, "username": data["username"],
            "password": data["password"], "device": data["deviceId"], "model": str(info.get("modelId")),
            "cert": data.get("devicecrt", ""), "key": data.get("devicepk", ""), "upload": info.get("fileUploadurl"),
            "name": info.get("modelName"), "version": info.get("version")}


# ── what it reports, as Klipper would say it ──

def job_key(p: Optional[Dict[str, Any]]) -> Optional[str]:
    return f"{p.get('filename')}|{p.get('print_time')}|{p.get('total_layers')}" if p else None


def stopped(p: Dict[str, Any]) -> bool:
    return str(p.get("state") or "").lower() in STOPPED or p.get("pause") == 4


def done(p: Dict[str, Any]) -> bool:
    """A finished job a Kobra still reports: it keeps it in info, at 100% with nothing left, until someone touches its
    screen (a Kobra 3, 9 October 2026: a whole day)."""
    if not p or stopped(p) or str(p.get("state") or "").lower() in PAUSED or p.get("pause") in (1, 2):
        return False
    return str(p.get("state") or "").lower() in FINISHED or (
        float(p.get("progress") or 0) >= 100 and float(p.get("remain_time") or 0) <= 0)


def how_it_ended(job: Dict[str, Any], last: Dict[str, Any]) -> str:
    """complete | cancelled, for a job the box saw run. What the box saw comes first: a job last seen on its last layer
    finished. last_project only holds the last print that finished, and only once the printer is free again (busy a
    while after a print, 8 October 2026; after a stop it still names an older one), so it counts only when it's this job's."""
    if job.get("stopped"):
        return "cancelled"
    p = job.get("project") or {}
    total = p.get("total_layers") or 0
    # read every 3 s, so the last look may come a layer early; a stop seen on the way out is a stop all the same
    at_end = float(p.get("progress") or 0) >= 95 or bool(total and (p.get("curr_layer") or 0) >= total - 1)
    finished = str(last.get("state") or "").lower() in FINISHED and last.get("filename") == job["filename"]
    return "complete" if at_end or (finished and job_key(last) != job.get("before")) else "cancelled"


def status_from(info: Dict[str, Any], ended: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Klipper-shaped status from an info report. ended: the job the box last saw end ({state, project}), shown on a free
    printer as Done or stopped until someone says the bed is clear or another job starts."""
    p = info.get("project") or {}
    temp = info.get("temp") or {}
    stage = str(p.get("state") or "").lower()
    pause = p.get("pause")
    if p and stopped(p):
        state = "cancelled"
    elif p and (stage in PAUSED or pause in (1, 2)):
        state = "paused"
    elif p:
        state = "printing"
    elif ended:
        state, p = ended["state"], ended["project"]
    else:
        state = "standby"
    print_s = float(p.get("print_time") or 0) * 60
    left_s = float(p.get("remain_time") or 0) * 60
    progress = float(p.get("progress") or 0) / 100
    if print_s + left_s > 0 and state == "printing":
        progress = max(progress, print_s / (print_s + left_s))
    message = GETTING_READY.get(stage, "") if state == "printing" else ""
    return {
        "webhooks": {"state": "ready", "state_message": "Printer is ready"},
        "print_stats": {"state": state, "filename": p.get("filename") or "", "print_duration": print_s,
                        "total_duration": print_s, "message": "",
                        "info": {"current_layer": p.get("curr_layer"), "total_layer": p.get("total_layers")}},
        "virtual_sdcard": {"progress": progress, "is_active": state == "printing", "file_path": p.get("filename") or ""},
        "display_status": {"message": message, "progress": progress},
        "pause_resume": {"is_paused": state == "paused"},
        "idle_timeout": {"state": "Printing" if state in ("printing", "paused") else "Idle"},
        "heater_bed": {"temperature": float(temp.get("curr_hotbed_temp") or 0), "target": float(temp.get("target_hotbed_temp") or 0)},
        "extruder": {"temperature": float(temp.get("curr_nozzle_temp") or 0), "target": float(temp.get("target_nozzle_temp") or 0),
                     "can_extrude": float(temp.get("curr_nozzle_temp") or 0) >= 170},
        "gcode_move": {"homing_origin": [0.0, 0.0, 0.0, 0.0]},
    }


def changed(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, obj in new.items():
        was = old.get(name) or {}
        diff = {k: v for k, v in obj.items() if was.get(k) != v}
        if diff:
            out[name] = diff
    return out


# ── a file the box sends: what Moonraker would have read in it ──

# Orca writes every plate's bed temperatures; the file heats for the plate it was sliced for (curr_bed_type)
PLATES = {"cool plate": "cool_plate_temp_initial_layer", "engineering plate": "eng_plate_temp_initial_layer",
          "high temp plate": "hot_plate_temp_initial_layer", "smooth pei plate": "hot_plate_temp_initial_layer",
          "textured pei plate": "textured_plate_temp_initial_layer", "textured cool plate": "textured_cool_plate_temp_initial_layer",
          "supertack plate": "supertack_plate_temp_initial_layer"}
_EST = re.compile(r"estimated printing time.*?=\s*(.+)", re.I)
_THUMB = re.compile(r"; thumbnail(?:_PNG)? begin (\d+)x(\d+) \d+\n(.*?); thumbnail(?:_PNG)? end", re.S)


def seconds(text: str) -> Optional[int]:
    parts = dict((u, int(n)) for n, u in re.findall(r"(\d+)\s*([dhms])", text))
    return sum(parts.get(u, 0) * k for u, k in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))) if parts else None


def gcode_metadata(path: Path, thumbs: Path, name: Optional[str] = None) -> Dict[str, Any]:
    """Moonraker's metadata for an Orca file, as far as the engine reads it; its pictures saved under thumbs."""
    head = path.read_bytes()[:1 << 20].decode("utf-8", "replace")
    out: Dict[str, Any] = {"size": path.stat().st_size, "modified": path.stat().st_mtime, "slicer": "OrcaSlicer"}
    m = _EST.search(head)
    if m:
        out["estimated_time"] = seconds(m.group(1))
    m = re.search(r"total layer number:\s*(\d+)", head)
    if m:
        out["layer_count"] = int(m.group(1))
    m = re.search(r"total filament weight \[g\]\s*:\s*([\d.,]+)", head)
    if m:
        out["filament_weight_total"] = sum(float(x) for x in m.group(1).split(",") if x)
    block = (orca_profile.read(str(path)) or {}).get("block") or {}

    def first(key: str) -> Optional[str]:
        v = block.get(key)
        return v.split(",")[0].split(";")[0].strip().strip('"') if v else None
    if first("filament_type"):
        out["filament_type"] = ";".join(t.strip().strip('"') for t in block["filament_type"].split(";"))
    if block.get("filament_colour"):
        out["filament_colors"] = [c.strip().strip('"') for c in block["filament_colour"].split(";")]
    plate = PLATES.get((first("curr_bed_type") or "").lower())
    for key, want in (("nozzle_temperature_initial_layer", "first_layer_extr_temp"), ("first_layer_temperature", "first_layer_extr_temp"),
                      (plate, "first_layer_bed_temp"), ("bed_temperature_initial_layer_single", "first_layer_bed_temp"),
                      ("hot_plate_temp_initial_layer", "first_layer_bed_temp"), ("layer_height", "layer_height")):
        if not key:
            continue
        v = first(key)
        if v and want not in out:
            try:
                out[want] = float(v)
            except ValueError:
                pass
    pics = []
    thumbs.mkdir(parents=True, exist_ok=True)
    for w, h, body in _THUMB.findall(head):
        png = base64.b64decode("".join(line.lstrip("; ").strip() for line in body.splitlines()))
        name_png = f"{Path(name or path.name).stem}-{w}x{h}.png"
        (thumbs / name_png).write_bytes(png)
        pics.append({"width": int(w), "height": int(h), "size": len(png), "relative_path": f".thumbs/{name_png}"})
    if pics:
        out["thumbnails"] = pics
    return out


# ── what a Moonraker keeps, kept on the box ──

class Store:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.d: Dict[str, Any] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("db", {})
        self.d.setdefault("history", [])
        self.d.setdefault("files", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=1))
        os.replace(tmp, self.path)


class LanUpstream:
    """standin.Upstream's part, over LAN mode. mqtt: a paho-like client factory (tests give a fake)."""

    def __init__(self, host: str, folder: Path, on_notify: Callable[[str, list], Any], on_up: Callable[[], Any],
                 on_down: Callable[[], Any], mqtt=None, poll: float = POLL, info_port: int = INFO_PORT):
        self.host, self.folder, self.on_notify, self.on_up, self.on_down = host, folder, on_notify, on_up, on_down
        self.info_port = info_port
        self.mqtt_factory, self.poll = mqtt, poll
        self.store = Store(folder / "lan.json")
        self.thumbs = folder / "thumbs"
        self.held = folder / "gcodes"
        self.login: Optional[Dict[str, Any]] = None
        self.client = None
        self.connected = False
        self.info: Dict[str, Any] = {}
        self.status: Dict[str, Any] = {}
        self.job: Optional[Dict[str, Any]] = None          # the job running now, to write into history when it ends
        self.ended: Optional[Dict[str, Any]] = None        # the last one the box saw end, until the bed is said clear
        # The heaters' targets as its tempature query gives them: info and the tempature reports it pushes keep the last
        # print update's targets after they're turned off (a Kobra 3, 7 October 2026)
        self.targets: Dict[str, Any] = {}
        self.waiting: Dict[str, asyncio.Future] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.session: Optional[ClientSession] = None

    @property
    def up(self) -> bool:
        return self.connected

    # ── the connection ──

    def _client(self):
        if self.mqtt_factory:
            return self.mqtt_factory()
        import paho.mqtt.client as mqtt
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bench-{uuid.uuid4().hex[:8]}")

    async def run(self, session: ClientSession) -> None:
        self.loop, self.session = asyncio.get_running_loop(), session
        while True:
            try:
                await self._connect()
                await self._poll_forever()
            except (RpcError, ClientError, OSError, asyncio.TimeoutError, ValueError, KeyError) as e:
                log.info("%s: %s", self.host, getattr(e, "message", None) or type(e).__name__)
            except Exception:
                log.exception("%s: LAN mode", self.host)      # never the end of trying: it comes back next round
            finally:
                if self.connected:
                    self.connected = False
                    await self.on_down()
                if self.client is not None:
                    try:
                        self.client.loop_stop()
                        self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None
            await asyncio.sleep(RECONNECT)

    async def _connect(self) -> None:
        self.login = await handshake(self.session, self.host, self.info_port)
        c = self._client()
        c.username_pw_set(self.login["username"], self.login["password"])
        if not self.mqtt_factory:
            cert, key = self.folder / "lan-cert.pem", self.folder / "lan-key.pem"
            self.folder.mkdir(parents=True, exist_ok=True)
            for f, body in ((cert, self.login["cert"]), (key, self.login["key"])):
                f.write_text(body)
                os.chmod(f, 0o600)
            c.tls_set(str(cert), keyfile=str(key), cert_reqs=ssl.CERT_NONE)   # its certificate is its own: no CA to check it by
            c.tls_insecure_set(True)
        ready = asyncio.Event()
        loop = self.loop

        def on_connect(cl, ud, flags, rc, props=None):
            cl.subscribe(f"{PREFIX}/printer/public/{self.login['model']}/{self.login['device']}/#")
            loop.call_soon_threadsafe(ready.set)

        def on_message(cl, ud, msg):
            loop.call_soon_threadsafe(self._message, msg.topic, msg.payload)
        c.on_connect, c.on_message = on_connect, on_message
        self.client = c
        c.connect(self.login["host"], self.login["port"], keepalive=60)
        c.loop_start()
        await asyncio.wait_for(ready.wait(), CALL_TIMEOUT)
        await self.query("info")
        self.connected = True
        log.info("%s: LAN mode, %s %s", self.host, self.login.get("name"), self.login.get("version"))
        res = self.on_up()
        if asyncio.iscoroutine(res):
            asyncio.create_task(res)

    async def _poll_forever(self) -> None:
        """Only MISSES unanswered info queries in a row is a lost printer, so a blip on the Wi-Fi doesn't take it off the
        bench. paho itself reconnects a dropped connection."""
        misses = 0
        while self.client is not None:
            await asyncio.sleep(self.poll)
            try:
                await self.query("info")
                misses = 0
                self._publish("tempature", "query", None, web=True)
            except asyncio.TimeoutError:
                misses += 1
                log.info("%s: no answer (%d of %d)", self.host, misses, MISSES)
                if misses >= MISSES:
                    raise

    def _publish(self, kind: str, action: str, data: Any, web: bool) -> str:
        msgid = uuid.uuid4().hex
        where = "web" if web else "slicer"
        self.client.publish(f"{PREFIX}/{where}/printer/{self.login['model']}/{self.login['device']}/{kind}",
                            json.dumps({"type": kind, "action": action, "timestamp": int(time.time() * 1000), "msgid": msgid,
                                        "data": data}))
        return msgid

    async def query(self, kind: str) -> Dict[str, Any]:
        """Ask it something: the next report of that kind is the answer."""
        fut = self.waiting.get(kind)
        if fut is None or fut.done():
            fut = self.waiting[kind] = self.loop.create_future()
        self._publish(kind, "query", None, web=True)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), CALL_TIMEOUT)
        finally:
            if self.waiting.get(kind) is fut and fut.done():
                self.waiting.pop(kind, None)

    def _message(self, topic: str, payload: bytes) -> None:
        try:
            body = json.loads(payload)
        except ValueError:
            return
        kind = topic.rsplit("/", 2)[-2] if topic.endswith("/report") else ""
        data = body.get("data") if isinstance(body, dict) else None
        if kind == "info" and isinstance(data, dict):
            self._info(data)
        elif kind == "tempature" and isinstance(data, dict) and self.info:
            if body.get("action") == "query":
                self.targets = {k: v for k, v in data.items() if k.startswith("target_")}
            self._info({**self.info, "temp": {**(self.info.get("temp") or {}), **{k: v for k, v in data.items() if k.startswith("curr_")}}})
        elif kind == "print" and isinstance(data, dict) and self.info and (self.info.get("project") or body.get("action") != "update"):
            # (an idle printer's answer to a temperature update is no job)
            stage = body.get("state")
            proj = {**(self.info.get("project") or {}), **{k: v for k, v in data.items() if k in (
                "curr_layer", "total_layers", "progress", "remain_time", "print_time", "filename")}}
            if stage and stage not in ("done", "failed"):
                proj["state"] = stage
            self._info({**self.info, "project": proj, "state": "busy" if stage not in ("finished", "stoped") else self.info.get("state")})
        fut = self.waiting.pop(kind, None)
        if fut and not fut.done():
            fut.set_result(body if isinstance(body, dict) else {})

    def _info(self, info: Dict[str, Any]) -> None:
        p, last = info.get("project") or {}, info.get("last_project") or {}
        if done(p):
            if self.job:
                self.job["project"] = {**(self.job.get("project") or {}), **p}
            elif not self.ended:                      # finished before the box was watching
                self.ended = {"state": "complete", "project": dict(p)}
            info, p = {k: v for k, v in info.items() if k != "project"}, {}
        if p:
            if not self.job or self.job["filename"] != p.get("filename"):
                self.job = {"filename": p.get("filename"), "start": time.time(), "before": job_key(last)}
                self.ended = None
            self.job["project"] = dict(p)
            self.job["stopped"] = self.job.get("stopped") or stopped(p)
        elif self.job:                                # it ended: into history, as Moonraker keeps it
            how = how_it_ended(self.job, last)
            theirs = how == "complete" and last.get("filename") == self.job["filename"] and job_key(last) != self.job.get("before")
            self.ended = {"state": how, "project": last if theirs else self.job["project"]}
            self.store.d["history"].insert(0, {"filename": self.job["filename"], "start_time": self.job["start"], "end_time": time.time(),
                                               "print_duration": float(self.ended["project"].get("print_time") or 0) * 60,
                                               "status": "completed" if how == "complete" else "cancelled",
                                               "metadata": self.store.d["files"].get(self.job["filename"] or "", {})})
            del self.store.d["history"][200:]
            self.store.save()
            self.job = None
        if self.targets:
            info = {**info, "temp": {**(info.get("temp") or {}), **self.targets}}
        self.info = info
        new = status_from(info, self.ended)
        diff = changed(self.status, new)
        self.status = new
        if diff and self.connected:
            res = self.on_notify("notify_status_update", [diff, time.monotonic()])
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)

    # ── what the stand-in asks of a Moonraker ──

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = CALL_TIMEOUT) -> Any:
        params = params or {}
        if not self.connected and method != "server.info":
            raise RpcError(503, "The printer isn't answering")
        db = self.store.d["db"]
        if method == "server.info":
            return {"klippy_state": "ready" if self.connected else "disconnected"}
        if method == "printer.objects.list":
            return {"objects": OBJECTS}
        if method in ("printer.objects.subscribe", "printer.objects.query"):
            want = params.get("objects") or {}
            return {"eventtime": time.monotonic(), "status": {k: (v if want.get(k) is None else {f: v[f] for f in want[k] if f in v})
                                                              for k, v in self.status.items() if k in want}}
        if method == "server.files.metadata":
            meta = self.store.d["files"].get(params.get("filename", ""))
            if not meta:
                raise RpcError(404, "Metadata not available")
            return {"filename": params["filename"], **meta}
        if method == "server.database.get_item":
            ns, key = db.get(params.get("namespace", ""), {}), params.get("key")
            if key is None:
                return {"namespace": params.get("namespace"), "value": ns}
            if key not in ns:
                raise RpcError(404, f"Key '{key}' not found")
            return {"namespace": params["namespace"], "key": key, "value": ns[key]}
        if method == "server.database.post_item":
            db.setdefault(params["namespace"], {})[params["key"]] = params.get("value")
            self.store.save()
            return {"namespace": params["namespace"], "key": params["key"], "value": params.get("value")}
        if method == "server.database.delete_item":
            value = db.get(params.get("namespace", ""), {}).pop(params.get("key"), None)
            self.store.save()
            return {"namespace": params.get("namespace"), "key": params.get("key"), "value": value}
        if method == "server.history.totals":
            jobs = self.store.d["history"]
            return {"job_totals": {"total_jobs": len(jobs), "total_time": sum(j["end_time"] - j["start_time"] for j in jobs),
                                   "total_print_time": sum(j["print_duration"] for j in jobs), "total_filament_used": 0.0,
                                   "longest_job": max((j["end_time"] - j["start_time"] for j in jobs), default=0.0),
                                   "longest_print": max((j["print_duration"] for j in jobs), default=0.0)}}
        if method == "server.history.list":
            jobs = self.store.d["history"][: int(params.get("limit", 50) or 50)]
            return {"count": len(jobs), "jobs": [{**j, "job_id": str(i), "exists": j["filename"] in self.store.d["files"]} for i, j in enumerate(jobs)]}
        if method == "server.webcams.list":
            return {"webcams": []}
        if method == "server.files.list":
            if params.get("root", "gcodes") != "gcodes":
                return []
            return [{"path": n, "modified": m.get("modified", 0), "size": m.get("size", 0), "permissions": "rw"}
                    for n, m in self.store.d["files"].items()]
        if method == "printer.print.start":
            return await self.start(str(params.get("filename", "")))
        if method in ("printer.print.pause", "printer.print.resume", "printer.print.cancel"):
            action = {"printer.print.pause": "pause", "printer.print.resume": "resume", "printer.print.cancel": "stop"}[method]
            self._publish("print", action, {"taskid": "-1"}, web=False)
            return "ok"
        if method == "printer.gcode.script":
            return self.gcode(str(params.get("script", "")))
        raise RpcError(404, f"{method} isn't there over LAN mode")

    def gcode(self, script: str) -> str:
        """Only what LAN mode can do as a setting: warm the bed and nozzle, or turn them off."""
        settings: Dict[str, int] = {}
        for line in script.upper().splitlines():
            m = re.match(r"\s*M(104|109|140|190)\s+S(\d+)", line)
            if m:
                settings["target_nozzle_temp" if m.group(1) in ("104", "109") else "target_hotbed_temp"] = int(m.group(2))
            elif line.strip() == "TURN_OFF_HEATERS":
                settings.update(target_nozzle_temp=0, target_hotbed_temp=0)
            elif line.strip():
                raise RpcError(400, "That G-code can't be sent over LAN mode")
        if not settings:
            return "ok"
        if self.info.get("project"):
            self._publish("print", "update", {"taskid": "-1", "settings": settings}, web=True)
            return "ok"
        # Idle, Kobras differ: one ignores a print update to 0 (Kobra 3, fw 2.4.6.7), another ignores a print update at
        # all (Kobra 3 #2, 7 October 2026). Warming sends both, the same targets twice; off is the Orca plugin's way only.
        bed, nozzle = settings.get("target_hotbed_temp"), settings.get("target_nozzle_temp")
        if all(settings.values()):
            self._publish("print", "update", {"taskid": "-1", "settings": settings}, web=True)
        self._publish("tempature", "set", {"type": 2 if bed is not None and nozzle is not None else (1 if bed is not None else 0),
                                           "target_hotbed_temp": bed or 0, "target_nozzle_temp": nozzle or 0}, web=True)
        return "ok"

    def ack(self) -> None:
        """Someone said the bed is clear after a job ended."""
        self.ended = None

    def keep(self, name: str, path: Path) -> str:
        """A file the box sends, read for its metadata and kept here until it's started: a Kobra that's sent a file warms
        up and waits on "Downloading files" for the start that Anycubic's slicer sends straight after (7 October 2026)."""
        meta = gcode_metadata(path, self.thumbs, name)
        meta["md5"] = hashlib.md5(path.read_bytes()).hexdigest()
        self.held.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self.held / name)
        self.store.d["files"][name] = meta
        self.store.save()
        for old in sorted(self.held.iterdir(), key=lambda f: f.stat().st_mtime)[:-KEEP]:
            old.unlink()
        return name

    async def _send(self, name: str) -> str:
        """Upload a kept file as Anycubic's slicer does. Its name on the printer."""
        path = self.held / name
        url = (self.login or {}).get("upload")
        if not url:
            raise RpcError(503, "The printer isn't answering")
        form = FormData()
        form.add_field("filename", name)
        form.add_field("gcode", path.read_bytes(), filename=name, content_type="application/octet-stream")
        async with self.session.post(url, data=form, headers={"X-File-Length": str(path.stat().st_size)},
                                     timeout=ClientTimeout(total=600)) as r:
            got = json.loads(await r.text())
        if got.get("code") != 200:
            raise RpcError(502, f"the printer didn't take the file: {got.get('message') or got.get('code')}")
        on_printer = (got.get("data") or {}).get("gcode") or name
        if on_printer != name:
            self.store.d["files"][on_printer] = self.store.d["files"].get(name, {})
            self.store.save()
        return on_printer

    async def start(self, filename: str) -> str:
        if (self.held / filename).is_file():          # sent with the start, as Anycubic's slicer does; else it's on the printer
            filename = await self._send(filename)
        meta = self.store.d["files"].get(filename, {})
        self._publish("print", "start", {
            # Anycubic's slicer sends a url even for a file already on the printer (filetype 1)
            "taskid": "-1", "url": "https://anycubic.com/store/aaa.gcode", "filename": filename, "md5": meta.get("md5") or hashlib.md5(filename.encode()).hexdigest(),
            "filepath": None, "filetype": 1, "project_type": 1, "filesize": meta.get("size", 0),
            "ams_settings": {"use_ams": False, "ams_box_mapping": []},
            "task_settings": {"auto_leveling": 0, "vibration_compensation": 0, "flow_calibration": 0, "dry_mode": 0,
                              "timelapse": {"status": 0, "count": 0, "type": 0}, "ai_settings": {"status": 0, "count": 0, "type": 0},
                              "drying_settings": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
                              "model_objects_skip_parts": []}}, web=False)
        return "ok"
