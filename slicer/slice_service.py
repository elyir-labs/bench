#!/usr/bin/env python3
"""The slicing service: a model, a purpose and a spool in; G-code and what was decided out.
See docs/slicer.md.

  GET  /slice/options            what can be chosen: purposes, printers (materials, slots, bed size)
  GET  /slice/filaments?q=&material=   Orca's filament library, searched: {filaments: [{preset, name, brand, material}]}
  POST /slice/models             multipart: model. Kept for a day; answers its id, size in mm, and how it
                                 lies: whether its biggest flat side is down, and its size laid flat. A 3MF
                                 answers {models: [...]}: each part in it, with how many times it's placed
  POST /slice                    JSON {parts: [{model, copies, scale, lay, brim}], printer, purpose, supports, material,
                                 color, slot, thumbnail (PNG, base64)}; {model, scale, lay} for one part; or
                                 multipart with the model itself
  POST /slice/fit                JSON {printer, parts, part}: how many of that part fit on one plate with the rest;
                                 part null: how many of each part plate 1 holds, as they are
  POST /slice/test               JSON {printer, test: "pressure_advance", material, color, slot}: a calibration print
  GET  /slice/models/{id}/file   the model as uploaded (to slice a skipped part again: design/skip-objects/)
  POST /slice/models/{id}/cut    JSON {z, lay, down, scale}: what's above z of it as printed, as a new model
                                 (Print the rest after a power cut: design/power-loss/)
  GET  /slice/{id}               queued | slicing | done | failed, the changes, the estimate, every plate
  GET  /slice/{id}/gcode         the file (the first plate)
  POST /slice/{id}/send          upload it to the printer ({"print": true} starts it as well), and any
                                 later plates with it, which Now offers when the first is done
  DELETE /slice/{id}             not wanted any more: dropped from the queue, or stopped mid-slice

  PUT    /slice/printers/{id}    another printer joins ({name, moonraker}); its profile is copied from its Moonraker
  GET    /slice/printers/{id}    whether it has joined, and what it slices with
  DELETE /slice/printers/{id}    it leaves, or is stopped from here
  GET    /slice/printers         who this machine slices for
  GET    /slice/asks             printers waiting for a yes on this machine's screen
  POST   /slice/asks/{id}/allow  yes (copies its profile and joins it) | /refuse: no, for a day

Through a printer's nginx (header X-Elyir-Bench-Printer) a request only sees, slices and sends for that printer.

One slice at a time, at low priority: on a printer's own Pi the slicer must never starve Klipper.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import time
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote, unquote
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData, TCPConnector, web

import elyir_bench_slice as sl

log = logging.getLogger("slicer")

KEEP_JOBS = 24 * 3600                  # a finished slice stays downloadable for a day
TIMEOUT = 15 * 60                      # a slice that takes longer than this is stuck


class Job:
    def __init__(self, jid: str, printer: sl.Printer, req: sl.Request, parts: List[sl.Part], workdir: str,
                 thumbnail: Optional[bytes] = None):
        self.id, self.printer, self.req, self.parts, self.workdir = jid, printer, req, parts, workdir
        self.thumbnail = thumbnail
        self.plates: List[Dict[str, Any]] = []   # {gcode, result, counts, placed}; the first is the one printed now
        self.state = "queued"
        self.created = time.time()
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.changes: List[sl.Change] = []
        self.result: Dict[str, Any] = {}
        self.gcode: Optional[str] = None
        self.error: Optional[str] = None          # for people
        self.error_detail: Optional[str] = None   # what the slicer said, for Advanced
        self.sent: Optional[str] = None
        self.sent_later: List[str] = []
        self.warnings: List[str] = []
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.lines: Optional[Dict[str, Any]] = None       # support_lines, once asked for
        self.layers: Optional[Tuple[Dict[str, Any], List[Any]]] = None   # layer_index, once asked for (design/look/)
        self.values: Dict[str, str] = {}                  # every editable setting as it prints (design/edit-settings/)
        self.before: Dict[str, str] = {}                  # the same before the person's own changes
        self.brims: List[Dict[str, str]] = []             # each part's brim as sliced: sl.brim_pick (design/brim/)
        self.colors: Optional[Dict[str, Any]] = None      # several colors: each spool's use and every change (design/multi-color/)

    @property
    def model(self) -> str:
        return self.parts[0].model

    def as_dict(self) -> Dict[str, Any]:
        r = self.req
        out: Dict[str, Any] = {
            "id": self.id, "state": self.state, "model": self.parts[0].name,
            "printer": self.printer.id,
            "request": {"purpose": r.purpose, "supports": r.supports, "material": r.material.upper(),
                        "color": r.color, "slot": r.slot, "orient": r.orient,
                        **({"spools": [{"material": s.material.upper(), "color": s.color, "slot": s.slot, "hand": s.hand}
                                       for s in r.spools],
                            "purge": r.purge or sl.default_purge(self.printer)} if r.spools else {}),
                        **({"one_after_other": True} if r.one_after_other else {})},
            "parts": [{"model": p.name, "copies": p.copies, "scale": p.scale, "lay": p.lay, "brim": p.brim, "spool": p.spool,
                       **({"down": p.down} if p.lay == "side" else {}),
                       **({"brim_pick": self.brims[i]} if i < len(self.brims) else {})} for i, p in enumerate(self.parts)],
            "changes": [c.as_dict() for c in self.changes],
        }
        if self.values:
            out["values"], out["before"] = self.values, self.before
        if self.started and self.finished:
            out["took"] = round(self.finished - self.started, 1)
        if self.state == "done":
            secs = self.result.get("seconds")
            out["estimate"] = {"seconds": secs, "time": sl.short_duration(secs) if secs else None,
                               "grams": self.result.get("grams"), "layers": self.result.get("layers")}
            if self.colors:
                out["colors"] = self.colors
                out["estimate"]["changes_seconds"] = self.colors["changes_seconds"]
            out["supports_added"] = self.result.get("supports")
            out["gcode"] = os.path.basename(self.gcode or "")
            out["sent"] = self.sent
            out["sent_later"] = self.sent_later
            out["warnings"] = self.warnings
            out["plates"] = [{"plate": i + 1, "seconds": p["result"].get("seconds"),
                              "time": sl.short_duration(p["result"]["seconds"]) if p["result"].get("seconds") else None,
                              "grams": p["result"].get("grams"), "counts": p["counts"],
                              "gcode": os.path.basename(p["gcode"])} for i, p in enumerate(self.plates)]
            out["placed"] = self.plates[0]["placed"] if self.plates else []
        if self.error:
            out["error"] = self.error
            out["error_detail"] = self.error_detail
        return out


class Service:
    def __init__(self, config: Dict[str, Any], work: str):
        self.orca: List[str] = config["orca"] if isinstance(config["orca"], list) else [config["orca"]]
        self.orca = [os.path.expanduser(p) for p in self.orca]
        self.env = {**os.environ, **{k: os.path.expanduser(v) for k, v in config.get("orca_env", {}).items()}}
        self.nice = int(config.get("nice", 10))
        self.profiles: List[str] = list(config["profiles"])    # shared by every printer, after its own presets
        self.lend = bool(config.get("lend"))                   # other printers may join (docs/slicer.md, "Slicing for other printers")
        # ask: a printer that wants to join waits for a yes on this machine's screen (design/slicing-elsewhere/, A);
        # anyone: it joins at once (a Bench Box, until it has a screen of its own to say yes on)
        self.allow = "anyone" if config.get("allow") == "anyone" else "ask"
        self.origins = set(config.get("origins", []))
        self.work = Path(os.path.expanduser(work))
        self.work.mkdir(parents=True, exist_ok=True)
        self.printers: Dict[str, sl.Printer] = {}
        self.presets: Dict[str, sl.Presets] = {}               # each printer's own: two printers' "PLA" may differ
        self.beds: Dict[str, Optional[List[float]]] = {}
        self.kinds: Dict[str, str] = {}                        # each printer's usual support, from its process preset
        # this machine's own printer, whose printer.json is read from its folder ("home") and read again when it
        # changes: the printer learns it from its own files (docs/slicer-profile.md), with no apply in between
        self.homes: Dict[str, Dict[str, Any]] = {}
        self.homes_checked = 0.0
        for pid, d in config["printers"].items():
            if d.get("home"):
                self.homes[pid] = {"entry": d, "sig": None}
                self._load_home(pid)
            else:
                self._add(sl.Printer.from_config(pid, d))
        self.own = set(self.printers) | set(self.homes)        # in the config; the rest joined
        # what people call this slicer: its own printer's name ("Workshop"), or the Bench Box's
        self.name = str(config.get("name") or next((p.name for p in self.printers.values()), "") or "The slicer")
        self.joined: Dict[str, Dict[str, Any]] = {}            # id → {name, moonraker, files, checked}
        self.asks: Dict[str, Dict[str, Any]] = {}              # id → {name, moonraker, at}: waiting for a yes
        self.refused: Dict[str, float] = {}                    # id → when it was told no (or stopped)
        if self.lend:
            self._load_joined()
        self.models: Dict[str, Dict[str, Any]] = {}
        self.jobs: Dict[str, Job] = {}
        self.queue: Optional["asyncio.Queue[Job]"] = None      # made on startup, inside the loop
        self.engine: Optional[asyncio.Lock] = None             # one Orca at a time, slicing or arranging

    def _add(self, printer: sl.Printer) -> None:
        presets = sl.Presets([*printer.presets, *self.profiles])
        try:
            bed = sl.bed_of(presets.resolve(printer.machine))
        except sl.PresetError:
            bed = None
        try:
            kind = sl.support_kind(presets.resolve(printer.process))
        except sl.PresetError:
            kind = "normal"
        self.printers[printer.id], self.presets[printer.id] = printer, presets
        self.beds[printer.id], self.kinds[printer.id] = bed, kind

    # ── this machine's own printer: printer.json in its folder, read again when it changes ──

    @staticmethod
    def _home_sig(folder: Path) -> Tuple[Any, ...]:
        files = [folder / "printer.json", *sorted((folder / "presets").glob("**/*.json"))]
        out = []
        for f in files:
            try:
                st = f.stat()
                out.append((str(f), st.st_mtime_ns, st.st_size))
            except OSError:
                out.append((str(f), None, None))
        return tuple(out)

    def _load_home(self, pid: str) -> None:
        h = self.homes[pid]
        d = h["entry"]
        folder = Path(os.path.expanduser(d["home"]))
        h["sig"] = self._home_sig(folder)
        try:
            pj = json.loads((folder / "printer.json").read_text())
            if not isinstance(pj, dict):
                raise ValueError("printer.json isn't an object")
            printer = sl.Printer.from_config(pid, {**pj, "name": d.get("name", pid), "moonraker": d.get("moonraker"),
                                                   "presets": [str(folder / "presets")]})
        except FileNotFoundError:
            for kept in (self.printers, self.presets, self.beds, self.kinds):
                kept.pop(pid, None)
            log.info("printer %s: no printer.json in %s yet", pid, folder)
            return
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("printer %s: printer.json can't be used (%s); %s", pid, e,
                        "the one before still slices" if pid in self.printers else "nothing to slice with yet")
            return
        self._add(printer)
        log.info("printer %s: slicing with %s / %s", pid, printer.machine, printer.process)

    def _check_homes(self) -> None:
        """printer.json or the presets beside it changed (learned from the printer's files, or edited in Mainsail):
        read them again. Looked at every few seconds at most."""
        if not self.homes or time.time() - self.homes_checked < HOME_CHECK:
            return
        self.homes_checked = time.time()
        for pid, h in self.homes.items():
            if self._home_sig(Path(os.path.expanduser(h["entry"]["home"]))) != h["sig"]:
                self._load_home(pid)

    # ── printers that join: their profile is theirs, read from their Moonraker ──

    def _joined_file(self) -> Path:
        return self.work / "printers.json"

    def _profile_dir(self, pid: str) -> Path:
        return self.work / "printers" / pid

    def _load_joined(self) -> None:
        """The printers that joined before a restart, from the profiles kept here; refreshed when next used."""
        try:
            saved = json.loads(self._joined_file().read_text())
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        if "joined" in saved:                                  # {joined, asks, refused}; before 4 October: joined alone
            self.asks = {k: v for k, v in (saved.get("asks") or {}).items() if isinstance(v, dict)}
            self.refused = {k: float(v) for k, v in (saved.get("refused") or {}).items()}
            saved = saved.get("joined") or {}
        for pid, j in saved.items():
            try:
                self._add(self._joined_printer(pid, j))
            except (OSError, ValueError, KeyError, TypeError, sl.PresetError) as e:
                log.warning("joined printer %s: its kept profile can't be used (%s)", pid, e)
                continue
            self.joined[pid] = {**j, "checked": 0.0}

    def _save_joined(self) -> None:
        keep = {pid: {k: j[k] for k in ("name", "moonraker", "files", "joined")} for pid, j in self.joined.items()}
        tmp = self._joined_file().with_suffix(".tmp")
        tmp.write_text(json.dumps({"joined": keep, "asks": self.asks, "refused": self.refused}, indent=1, sort_keys=True))
        os.replace(tmp, self._joined_file())

    def _joined_printer(self, pid: str, j: Dict[str, Any], folder: Optional[Path] = None) -> sl.Printer:
        folder = folder or self._profile_dir(pid)
        d = json.loads((folder / "printer.json").read_text())
        if not isinstance(d, dict):
            raise ValueError("printer.json isn't an object")
        d = {**d, "name": j["name"], "moonraker": j["moonraker"], "presets": [str(folder / "presets")]}
        return sl.Printer.from_config(pid, d)

    async def _profile_files(self, s: ClientSession, moonraker: str) -> Dict[str, float]:
        """The printer's slicing profile as Moonraker lists it: elyir-bench-slicer/printer.json and the presets."""
        async with s.get(f"{moonraker}/server/files/list", params={"root": "config"}) as r:
            if r.status != 200:
                raise ProfileError(f"its Moonraker answered {r.status} when asked for its config files")
            listed = (await r.json()).get("result") or []
        files = {f["path"]: float(f.get("modified") or 0) for f in listed if isinstance(f, dict)
                 and (f.get("path") == PROFILE or (str(f.get("path", "")).startswith(PROFILE_PRESETS)
                                                   and str(f["path"]).endswith(".json")))}
        if PROFILE not in files:
            raise ProfileError(f"it has no {PROFILE} in its config folder")
        return files

    async def _fetch_profile(self, pid: str, j: Dict[str, Any]) -> sl.Printer:
        """Copy the printer's profile here and check it slices: its machine, process and every material resolve."""
        async with ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=60)) as s:
            try:
                files = await self._profile_files(s, j["moonraker"])
            except (ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
                raise ProfileError(f"its Moonraker at {j['moonraker']} can't be reached ({type(e).__name__})")
            new = self.work / "printers" / f".{pid}-new"
            shutil.rmtree(new, ignore_errors=True)
            try:
                for path in sorted(files):
                    async with s.get(f"{j['moonraker']}/server/files/config/{quote(path)}") as r:
                        if r.status != 200:
                            raise ProfileError(f"its Moonraker answered {r.status} for {path}")
                        body = await r.read()
                    dest = new / path[len("elyir-bench-slicer/"):]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(body)
                try:
                    printer = self._joined_printer(pid, j, new)
                except (ValueError, KeyError, TypeError) as e:
                    raise ProfileError(f"its {PROFILE} can't be read ({e})")
                presets = sl.Presets([*printer.presets, *self.profiles])
                missing = []
                for name in (printer.machine, printer.process, *printer.materials.values()):
                    try:
                        presets.resolve(name)
                    except sl.PresetError as e:
                        missing.append(str(e))
                if missing:
                    raise ProfileError("its presets don't resolve: " + "; ".join(missing))
                old = self._profile_dir(pid)
                shutil.rmtree(old, ignore_errors=True)
                os.replace(new, old)
            finally:
                shutil.rmtree(new, ignore_errors=True)
        j["files"] = files
        return self._joined_printer(pid, j)

    async def _refresh(self, pid: str) -> None:
        """A joined printer's profile changed on the printer (Mainsail's editor, new presets): copy it again.
        Looked at once a minute at most; when the printer can't be reached, the kept profile slices."""
        j = self.joined.get(pid)
        if j is None or time.time() - j.get("checked", 0) < REFRESH:
            return
        j["checked"] = time.time()
        try:
            async with ClientSession(connector=TCPConnector(family=socket.AF_INET), timeout=ClientTimeout(total=10)) as s:
                files = await self._profile_files(s, j["moonraker"])
            if files != j.get("files"):
                self._add(await self._fetch_profile(pid, j))
                self._save_joined()
                log.info("joined printer %s: profile copied again", pid)
        except (ProfileError, ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
            log.warning("joined printer %s: kept profile used (%s)", pid, e)

    async def put_printer(self, request: web.Request) -> web.Response:
        """A printer joins (or joins again, on every `elyir-bench apply`): {name, moonraker}."""
        pid = request.match_info["id"]
        if not self.lend:
            return _err(403, "This slicer only slices for its own printer. Set slice_for_others: on in its elyir-bench.conf.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", pid):
            return _bad("a printer id is lowercase letters, digits and dashes")
        if pid in self.own:
            return _err(409, f"{pid} is this slicer's own printer")
        try:
            body = await request.json()
            name, moonraker = str(body["name"]).strip(), str(body["moonraker"]).rstrip("/")
        except (ValueError, KeyError, TypeError, AttributeError):
            return _bad("send {name, moonraker}")
        if not name or not re.fullmatch(r"https?://[^/\s]+", moonraker):
            return _bad("moonraker must be the printer's Moonraker address, like http://desk.local:7125")
        new = pid not in self.joined
        if new and self.allow == "ask" and time.time() - self.refused.get(pid, 0) < REFUSED_FOR:
            return _err(403, f"{self.name} said no. It can be asked again tomorrow.", refused=True, slicer=self.name)
        j = {"name": name, "moonraker": moonraker, "joined": self.joined.get(pid, {}).get("joined") or time.time()}
        try:
            printer = await self._fetch_profile(pid, j)           # a profile that can't slice is said now, not after the yes
        except ProfileError as e:
            return _err(422, f"{name} can't slice here yet: {e}.")
        except (ClientError, OSError, asyncio.TimeoutError) as e:
            return _err(422, f"{name} can't slice here yet: its Moonraker at {moonraker} stopped answering ({type(e).__name__}).")
        if new and self.allow == "ask":
            self.asks[pid] = {"name": name, "moonraker": moonraker, "at": self.asks.get(pid, {}).get("at") or time.time()}
            self._save_joined()
            log.info("printer %s (%s) asks to join, from %s", pid, name, moonraker)
            return web.json_response({"id": pid, "name": name, "waiting": True, "slicer": self.name}, status=202)
        self._join(pid, j, printer)
        return web.json_response(self._entry(pid))

    def _join(self, pid: str, j: Dict[str, Any], printer: sl.Printer) -> None:
        self._add(printer)
        self.joined[pid] = {**j, "checked": time.time()}
        self.asks.pop(pid, None)
        self.refused.pop(pid, None)
        self._save_joined()
        log.info("printer %s (%s) joined from %s", pid, j["name"], j["moonraker"])

    # ── asks: answered on this machine's own screen (the app's Allow card, kind "printer") ──

    def _answerer(self, request: web.Request) -> None:
        """Only this machine answers: its own printer's nginx, or no printer at all (here, a Bench Box)."""
        caller = request.headers.get(PRINTER_HEADER)
        if caller is not None and caller not in self.own:
            raise _http(403, "Only the slicer's own screen can answer")

    async def get_asks(self, request: web.Request) -> web.Response:
        self._answerer(request)
        return web.json_response({"slicer": self.name, "asks": [{"id": pid, "name": a["name"], "kind": "printer", "at": a["at"]}
                                                                for pid, a in sorted(self.asks.items(), key=lambda kv: kv[1]["at"])]})

    async def answer_ask(self, request: web.Request) -> web.Response:
        self._answerer(request)
        pid, how = request.match_info["id"], request.match_info["how"]
        a = self.asks.get(pid)
        if a is None:
            return _err(404, "Nobody is asking any more")
        if how == "refuse":
            self.asks.pop(pid)
            self.refused[pid] = time.time()
            self._save_joined()
            log.info("printer %s (%s) was told no", pid, a["name"])
            return web.json_response({"id": pid, "refused": True})
        j = {"name": a["name"], "moonraker": a["moonraker"], "joined": time.time()}
        try:
            printer = await self._fetch_profile(pid, j)
        except (ProfileError, ClientError, OSError, asyncio.TimeoutError) as e:
            return _err(502, f"{a['name']} can't be reached to copy its settings ({e}). Try again when it's on.")
        self._join(pid, j, printer)
        return web.json_response(self._entry(pid))

    async def list_printers(self, request: web.Request) -> web.Response:
        """Who this machine slices for, for its Care: its own printer and the ones that joined."""
        self._answerer(request)
        return web.json_response({"slicer": self.name, "printers": [self._entry(pid) for pid in self.printers]})

    async def get_printer(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        if pid in self.asks:
            return web.json_response({"id": pid, "name": self.asks[pid]["name"], "waiting": True, "slicer": self.name})
        if pid not in self.printers:
            if time.time() - self.refused.get(pid, 0) < REFUSED_FOR:
                return _err(403, f"{self.name} said no. It can be asked again tomorrow.", refused=True, slicer=self.name)
            return _err(404, f"{pid} hasn't joined this slicer")
        return web.json_response(self._entry(pid))

    async def delete_printer(self, request: web.Request) -> web.Response:
        pid = request.match_info["id"]
        if pid in self.own:
            return _err(409, f"{pid} is this slicer's own printer")
        if self.joined.pop(pid, None) is not None or self.asks.pop(pid, None) is not None:
            name = self.printers[pid].name if pid in self.printers else pid
            self.printers.pop(pid, None)
            self.presets.pop(pid, None)
            # its prints still waiting in line go with it, saying why (one queued when Workshop stopped slicing for Desk
            # on 5 October 2026 crashed on the presets that had just gone)
            for job in self.jobs.values():
                if job.printer.id == pid and job.state == "queued":
                    job.state, job.finished = "failed", time.time()
                    job.error = f"{self.name} stopped slicing for {name} before this one started."
            shutil.rmtree(self._profile_dir(pid), ignore_errors=True)
            if request.headers.get(PRINTER_HEADER) != pid:      # stopped here, not left by itself: don't ask again today
                self.refused[pid] = time.time()
            self._save_joined()
        return web.json_response({"left": pid})

    def _entry(self, pid: str) -> Dict[str, Any]:
        entry = sl.options({pid: self.printers[pid]}, self.beds, self.kinds)["printers"][0]
        return {**entry, "joined": pid in self.joined, "moonraker": self.printers[pid].moonraker}

    # ── who is asking ──

    def _caller(self, request: web.Request) -> Optional[str]:
        """The printer a request comes through: its nginx says so (X-Elyir-Bench-Printer), and then it only
        sees, slices and sends for itself. Without the header (on this machine, in dev) it can name any."""
        self._check_homes()
        pid = request.headers.get(PRINTER_HEADER)
        if pid is None:
            return None
        if pid not in self.printers and pid in self.homes:
            raise _http(404, f"{self.homes[pid]['entry'].get('name', pid)} has no slicing settings yet. Slice one file "
                        "in OrcaSlicer and print it, and Elyir Bench learns them from it.", settings=False)
        if pid not in self.printers:
            if pid in self.asks:
                raise _http(403, f"Waiting for {self.name} to say yes on its screen.", waiting=True, slicer=self.name)
            if time.time() - self.refused.get(pid, 0) < REFUSED_FOR:
                raise _http(403, f"{self.name} said no, so it doesn't slice for this printer.", refused=True, slicer=self.name)
            raise _http(404, f"{pid} hasn't joined this slicer yet")
        return pid

    def _printer(self, request: web.Request, fields: Dict[str, Any]) -> sl.Printer:
        caller = self._caller(request)
        asked = str(fields.get("printer") or caller or "")
        if caller and asked != caller:
            raise _http(403, f"a slice sent through {self.printers[caller].name} is for {self.printers[caller].name}")
        printer = self.printers.get(asked)
        if printer is None:
            raise _http(400, f"printer must be one of {', '.join(self.printers)}")
        return printer

    # ── http ──

    def app(self) -> web.Application:
        app = web.Application(client_max_size=256 * 1024 * 1024, middlewares=[self.cors])
        app.router.add_get("/slice/options", self.get_options)
        app.router.add_get("/slice/filaments", self.get_filaments)
        app.router.add_put("/slice/printers/{id}", self.put_printer)
        app.router.add_get("/slice/printers/{id}", self.get_printer)
        app.router.add_delete("/slice/printers/{id}", self.delete_printer)
        app.router.add_get("/slice/printers", self.list_printers)
        app.router.add_get("/slice/asks", self.get_asks)
        app.router.add_post("/slice/asks/{id}/{how:allow|refuse}", self.answer_ask)
        app.router.add_post("/slice/models", self.post_model)
        app.router.add_post("/slice", self.post_slice)
        app.router.add_post("/slice/fit", self.post_fit)
        app.router.add_post("/slice/test", self.post_test)
        app.router.add_get("/slice/models/{id}/file", self.get_model_file)
        app.router.add_get("/slice/models/{id}/piece/{k}", self.get_model_piece)
        app.router.add_post("/slice/models/{id}/cut", self.post_cut)
        app.router.add_get("/slice/{id}", self.get_job)
        app.router.add_get("/slice/{id}/gcode", self.get_gcode)
        app.router.add_get("/slice/{id}/supports", self.get_supports)
        app.router.add_get("/slice/{id}/layers", self.get_layers)
        app.router.add_get("/slice/{id}/layers/{n}", self.get_layer)
        app.router.add_post("/slice/{id}/send", self.send)
        app.router.add_delete("/slice/{id}", self.cancel)
        app.on_startup.append(self._start)
        app.on_cleanup.append(self._stop)
        return app

    @web.middleware
    async def cors(self, request: web.Request, handler):
        origin = request.headers.get("Origin")
        if request.method == "OPTIONS":
            resp: web.StreamResponse = web.Response(status=204)
        else:
            resp = await handler(request)
        if origin and origin in self.origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Vary"] = "Origin"
        return resp

    async def get_options(self, request: web.Request) -> web.Response:
        caller = self._caller(request)
        here = {"name": self.name, "here": caller in self.own if caller else None}
        if caller:
            await self._refresh(caller)
            return web.json_response({**sl.options({caller: self.printers[caller]}, self.beds, self.kinds), "slicer": here})
        return web.json_response({**sl.options(self.printers, self.beds, self.kinds), "slicer": here})

    async def _save_model(self, part, folder: Path) -> Path:
        name = os.path.basename(unquote(part.filename))     # some clients percent-encode "[a]_part.stl"
        if Path(name).suffix.lower() not in sl.UPLOAD_TYPES:
            raise ValueError(f"{name}: send a model as {', '.join(sorted(sl.UPLOAD_TYPES))}")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        with open(path, "wb") as f:
            while chunk := await part.read_chunk():
                f.write(chunk)
        return path

    async def post_model(self, request: web.Request) -> web.Response:
        """A model on its own, so the four purposes and every change after can share one upload."""
        caller = self._caller(request)
        mid = secrets.token_hex(6)
        folder = self.work / "models" / mid
        try:
            reader = await request.multipart()
            async for part in reader:
                if part.name == "model" and part.filename:
                    path = await self._save_model(part, folder)
                    if path.suffix.lower() == ".3mf":
                        return await self._three_mf(path, folder, caller)
                    size = await asyncio.to_thread(sl.model_size, str(path))
                    lying = await asyncio.to_thread(sl.lying, str(path))
                    if lying:
                        lying["size_flat"] = await asyncio.to_thread(sl.size_laid_flat, str(path), lying["flat_normal"])
                    _own(folder, caller)
                    self.models[mid] = {"id": mid, "name": path.name, "path": str(path), "size": size,
                                        "lying": lying, "created": time.time(), "printer": caller}
                    return web.json_response({"model": mid, "name": path.name, "size": size, "lying": lying}, status=201)
            return _bad("no model: send the file as 'model'")
        except ValueError as e:
            shutil.rmtree(folder, ignore_errors=True)
            return _bad(str(e))

    async def _three_mf(self, path: Path, folder: Path, caller: Optional[str]) -> web.Response:
        """A 3MF read as its parts: each kept as an STL of its own, as if uploaded on its own (design/plate/).
        One that brings its own colors is kept whole, to be sliced as it is (design/multi-color/)."""
        try:
            colors = await asyncio.to_thread(sl.three_mf_colors, str(path))
            parts = await asyncio.to_thread(sl.three_mf_parts, str(path))
        except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise ValueError(f"{path.name} couldn't be read as a 3MF ({type(e).__name__})")
        if colors and parts:
            mid = folder.name
            size = sl.size_of_tris(parts)
            drawn = await asyncio.to_thread(_write_pieces, folder, parts)
            _own(folder, caller)
            self.models[mid] = {"id": mid, "name": path.name, "path": str(path), "size": size, "lying": None,
                                "colors": colors, "pieces": drawn, "created": time.time(), "printer": caller}
            return web.json_response({"model": mid, "name": path.name, "size": size, "lying": None, "colors": colors,
                                      "pieces": drawn}, status=201)
        shutil.rmtree(folder, ignore_errors=True)
        if not parts:
            raise ValueError(f"There's nothing to print in {path.name}.")
        if len(parts) > 50:
            raise ValueError(f"{path.name} has {len(parts)} parts; at most 50 go on one plate")
        out = []
        for p in parts:
            mid = secrets.token_hex(6)
            sub = self.work / "models" / mid
            sub.mkdir(parents=True)
            stem = re.sub(r"\.(stl|obj)$", "", p["name"], flags=re.I).strip() or "part"
            stl = sub / (re.sub(r"[/\\:]+", "_", stem) + ".stl")
            await asyncio.to_thread(sl.write_stl, str(stl), p["tris"])
            size = await asyncio.to_thread(sl.model_size, str(stl))
            lying = await asyncio.to_thread(sl.lying, str(stl))
            if lying:
                lying["size_flat"] = await asyncio.to_thread(sl.size_laid_flat, str(stl), lying["flat_normal"])
            _own(sub, caller)
            self.models[mid] = {"id": mid, "name": stl.name, "path": str(stl), "size": size, "lying": lying,
                                "created": time.time(), "printer": caller}
            out.append({"model": mid, "name": stl.name, "size": size, "lying": lying, "copies": p["copies"]})
        return web.json_response({"models": out, "from": path.name}, status=201)

    async def post_slice(self, request: web.Request) -> web.Response:
        fields: Dict[str, Any] = {}
        jid = secrets.token_hex(6)
        workdir = self.work / jid
        parts: List[sl.Part] = []
        queued = False
        try:
            if request.content_type == "application/json":
                fields = await request.json()
                if not isinstance(fields, dict):
                    return _bad("send a JSON object")
                parts = self._parts(fields, self._caller(request))
            else:
                reader = await request.multipart()
                model: Optional[Path] = None
                async for part in reader:
                    if part.name == "model" and part.filename:
                        model = await self._save_model(part, workdir)
                    elif part.name:
                        fields[part.name] = (await part.text()).strip()
                if model is None:
                    return _bad("no model: send the file as 'model'")
                parts = [_part(str(model), fields)]
            printer = self._printer(request, fields)
            slot = fields.get("slot")
            req = sl.Request(
                purpose=str(fields.get("purpose", "everyday")),
                supports=str(fields.get("supports", "auto")),
                material=str(fields.get("material", "PLA")),
                filament=self._filament(printer, fields.get("filament")),
                color=fields.get("color") or None,
                slot=int(slot) - 1 if slot not in (None, "") else None,
                orient=str(fields.get("orient", "")).lower() in ("1", "true", "yes"),
                kept=fields.get("kept") or {},
                settings=fields.get("settings") or {},
                spools=_spools(fields.get("spools")),
                purge=str(fields["purge"]) if fields.get("purge") else None,
                one_after_other=fields.get("one_after_other") is True,
            )
            problems = req.problems(printer) + [q for p in parts for q in p.problems()] + self._plate_problems(req, parts)
            if problems:
                return _bad("; ".join(problems))
            thumb = None
            if fields.get("thumbnail"):
                try:
                    thumb = base64.b64decode(str(fields["thumbnail"]).split(",")[-1], validate=True)
                    sl.png_size(thumb)
                except (binascii.Error, ValueError):
                    return _bad("thumbnail must be a base64 PNG")
            workdir.mkdir(parents=True, exist_ok=True)
            job = Job(jid, printer, req, parts, str(workdir), thumb)
            self.jobs[jid] = job
            self.queue.put_nowait(job)
            queued = True
            return web.json_response(job.as_dict(), status=202)
        except (ValueError, TypeError) as e:
            return _bad(str(e))
        finally:
            if not queued:
                shutil.rmtree(workdir, ignore_errors=True)

    def _plate_problems(self, req: sl.Request, parts: List[sl.Part]) -> List[str]:
        out = [f"part {i + 1}: spool must be one of the plate's {req.colors} colors"
               for i, p in enumerate(parts) if p.spool >= req.colors]
        project = next((p for p in parts if p.project), None)
        if project:
            if len(parts) > 1:
                out.append("a 3MF with its own colors goes on a plate of its own")
            m = self._model(_model_id(project.model) or "", None)
            n = len((m or {}).get("colors", {}).get("colors", []))
            if n and len(req.spools) != n:
                out.append(f"{project.name} has {n} colors: send a spool for each, in its order")
        return out

    def _filament(self, printer: sl.Printer, name: Any) -> Optional[str]:
        """A filament preset asked for by name: one of Orca's library, or one the printer's own presets have."""
        if not name:
            return None
        d = self.presets[printer.id].by_name.get(str(name))
        if not d or d.get("type") != "filament":
            raise ValueError(f"no filament called {name!r}")
        return str(name)

    def _library(self) -> List[Dict[str, str]]:
        if getattr(self, "_library_cache", None) is None:
            self._library_cache = sl.library_filaments(sl.Presets(self.profiles))
        return self._library_cache

    async def get_filaments(self, request: web.Request) -> web.Response:
        q, material = request.query.get("q", ""), request.query.get("material", "")
        found = await asyncio.get_running_loop().run_in_executor(None, lambda: sl.search_filaments(self._library(), q, material))
        return web.json_response({"filaments": found, "total": len(self._library())})

    def _parts(self, fields: Dict[str, Any], caller: Optional[str]) -> List[sl.Part]:
        """The plate from a JSON request: "parts", or the one "model" (with its scale and lay) of before."""
        given = fields.get("parts")
        if given is None:
            given = [{k: fields[k] for k in ("model", "scale", "lay", "copies", "brim") if k in fields}]
        if not isinstance(given, list) or not given or not all(isinstance(p, dict) for p in given):
            raise ValueError("parts must be a list of {model, copies, scale, lay, brim}")
        if len(given) > 50:
            raise ValueError("at most 50 different parts on one plate")
        out = []
        for g in given:
            m = self._model(str(g.get("model", "")), caller)
            if m is None:
                raise ValueError("no such model: upload it to /slice/models first")
            out.append(_part(m["path"], g, m.get("lying")))
        return out

    def _model(self, mid: str, caller: Optional[str]) -> Optional[Dict[str, Any]]:
        """An uploaded model by id: in memory, or still on disk from before a restart (kept a day). Through a
        printer, only the models uploaded through it."""
        m = self.models.get(mid)
        if m is None:
            folder = self.work / "models" / mid
            if not re.fullmatch(r"[0-9a-f]{12}", mid) or not folder.is_dir():
                return None
            files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in sl.UPLOAD_TYPES]
            if len(files) != 1:
                return None
            path = files[0]
            owner = (folder / OWNER).read_text().strip() if (folder / OWNER).exists() else None
            if path.suffix.lower() == ".3mf":
                colors = sl.three_mf_colors(str(path))
                if not colors:
                    return None
                m = self.models[mid] = {"id": mid, "name": path.name, "path": str(path),
                                        "size": sl.size_of_tris(sl.three_mf_parts(str(path))), "lying": None, "colors": colors,
                                        "created": path.stat().st_mtime, "printer": owner}
            else:
                m = self.models[mid] = {"id": mid, "name": path.name, "path": str(path), "size": sl.model_size(str(path)),
                                        "lying": sl.lying(str(path)), "created": path.stat().st_mtime, "printer": owner}
        if caller and m.get("printer") != caller:
            return None
        return m

    async def get_model_piece(self, request: web.Request) -> web.StreamResponse:
        """One piece of a 3MF with colors, as an STL to draw (its filament is in the upload's answer)."""
        m = await asyncio.to_thread(self._model, request.match_info["id"], self._caller(request))
        k = request.match_info["k"]
        f = Path(m["path"]).parent / PIECES / f"{k}.stl" if m else None
        if f is None or not k.isdigit() or not f.is_file():
            raise web.HTTPNotFound(text="no such piece")
        return web.FileResponse(f)

    async def get_model_file(self, request: web.Request) -> web.StreamResponse:
        m = await asyncio.to_thread(self._model, request.match_info["id"], self._caller(request))
        if m is None:
            raise web.HTTPNotFound(text="no such model: it's kept for a day")
        return web.FileResponse(m["path"], headers={"Content-Disposition": f'attachment; filename="{m["name"]}"'})

    async def post_cut(self, request: web.Request) -> web.Response:
        """{z, lay, down, scale}: what's above z of a model laid and sized as it was printed, as a model of its own
        (Print the rest, design/power-loss/). 404 when the model is gone, 422 when nothing is above z."""
        caller = self._caller(request)
        m = await asyncio.to_thread(self._model, request.match_info["id"], caller)
        if m is None:
            raise web.HTTPNotFound(text="no such model: it's kept for a day")
        try:
            body = await request.json()
            z = float(body["z"])
        except (ValueError, KeyError, TypeError):
            return _bad("send {z}: the height it stopped at, in mm")
        mid = secrets.token_hex(6)
        folder = self.work / "models" / mid
        stem = re.sub(r"\.(stl|obj)$", "", m["name"], flags=re.I)
        dest = folder / f"{stem}_rest.stl"
        part = _part(m["path"], {"lay": body.get("lay"), "down": body.get("down"), "scale": body.get("scale")}, m.get("lying"))
        try:
            laid = await asyncio.to_thread(_prepare, [part], str(folder / "laid"))
            cut = await asyncio.to_thread(sl.cut_above, laid[0], str(dest), z)
        finally:
            shutil.rmtree(folder / "laid", ignore_errors=True)
        if not cut:
            shutil.rmtree(folder, ignore_errors=True)
            return web.json_response({"error": "nothing above that height"}, status=422)
        _own(folder, caller)
        size = await asyncio.to_thread(sl.model_size, str(dest))
        self.models[mid] = {"id": mid, "name": dest.name, "path": str(dest), "size": size, "lying": None,
                            "created": time.time(), "printer": caller}
        return web.json_response({"model": mid, "name": dest.name, "size": size, "lying": None}, status=201)

    async def post_fit(self, request: web.Request) -> web.Response:
        """How many of one part fit on a plate with the others as they are: "Fill the plate" on its sheet.
        Orca only arranges (no slicing), with more copies than could fit, and plate 1 is counted. With part null:
        the parts as they are, and how many of each plate 1 holds (several shelf models on one bed)."""
        try:
            fields = await request.json()
            if not isinstance(fields, dict):
                return _bad("send a JSON object")
            parts = self._parts(fields, self._caller(request))
            i = None if fields.get("part", 0) is None else int(fields.get("part", 0))
            if i is not None and not 0 <= i < len(parts):
                return _bad("part must be one of the parts")
            printer = self._printer(request, fields)
            problems = [q for p in parts for q in p.problems()]
            if problems:
                return _bad("; ".join(problems))
        except (ValueError, TypeError) as e:
            return _bad(str(e))
        workdir = self.work / ("fit-" + secrets.token_hex(6))
        try:
            req = sl.Request(material=sorted(printer.materials)[0])
            p = await asyncio.to_thread(sl.plan, printer, req, self.presets[printer.id])
            out = workdir / "out"
            out.mkdir(parents=True)
            sl.write_plan(p, str(workdir))
            files = await asyncio.to_thread(_prepare, parts, str(workdir / "parts"))
            if i is not None:
                parts[i].copies = sl.fit_guess(await asyncio.to_thread(sl.model_size, files[i]), self.beds.get(printer.id))
            cmd = sl.orca_command(self.orca, str(workdir), _repeat(files, parts), str(out), False, slice_it=False)
            if self.nice:
                cmd = ["nice", "-n", str(self.nice), *cmd]
            async with self.engine:
                proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(workdir), env=self.env,
                                                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    code = await asyncio.wait_for(proc.wait(), TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    return web.json_response({"error": "Working out what fits took too long."}, status=504)
            try:
                plates = await asyncio.to_thread(sl.read_arrangement, str(out / sl.PLATES_3MF))
            except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
                return web.json_response({"error": f"The slicer couldn't arrange it (exit code {code})."}, status=502)
            first = sl.counts(plates.get(1, []), len(parts))
            if i is None:
                return web.json_response({"counts": first, "plates": max([1, *plates]),
                                          "fits": all(first[k] >= p.copies for k, p in enumerate(parts))})
            others = all(first[k] >= parts[k].copies for k in range(len(parts)) if k != i)
            # every copy asked for fitted: there's room for more than were tried
            return web.json_response({"part": i, "fits": first[i], "others_fit": others,
                                      "at_least": first[i] >= parts[i].copies})
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def post_test(self, request: web.Request) -> web.Response:
        """A calibration print, sliced like a model: the slicer makes the model itself (pa_tower_stl)."""
        try:
            fields = await request.json()
            if not isinstance(fields, dict):
                return _bad("send a JSON object")
            printer = self._printer(request, fields)
            slot = fields.get("slot")
            req = sl.Request(purpose="everyday", supports="off", material=str(fields.get("material", "PLA")),
                             color=fields.get("color") or None, slot=int(slot) - 1 if slot not in (None, "") else None,
                             test=str(fields.get("test") or ""))
            problems = req.problems(printer)
            if problems:
                return _bad("; ".join(problems))
        except (ValueError, TypeError) as e:
            return _bad(str(e))
        jid = secrets.token_hex(6)
        workdir = self.work / jid
        workdir.mkdir(parents=True)
        model = workdir / f"{req.test}_test.stl"
        await asyncio.to_thread(sl.pa_tower_stl, str(model))
        job = Job(jid, printer, req, [sl.Part(model=str(model))], str(workdir))
        self.jobs[jid] = job
        self.queue.put_nowait(job)
        return web.json_response(job.as_dict(), status=202)

    def _job(self, request: web.Request) -> Job:
        job = self.jobs.get(request.match_info["id"])
        caller = self._caller(request)
        if job is None or (caller and job.printer.id != caller):
            raise web.HTTPNotFound(text="no such slice")
        return job

    async def get_job(self, request: web.Request) -> web.Response:
        return web.json_response(self._view(self._job(request)))

    def _view(self, job: Job) -> Dict[str, Any]:
        """A job, and when it waits, what it waits behind: shared by every printer that slices here."""
        out = job.as_dict()
        if job.state == "queued":
            before = [j for j in self.jobs.values() if j is not job and j.created < job.created and j.state in ("queued", "slicing")]
            busy = next((j for j in before if j.state == "slicing"), None)
            out["ahead"] = len(before)
            out["behind"] = busy.printer.name if busy else None
        return out

    async def cancel(self, request: web.Request) -> web.Response:
        """The app changed its mind (another spool, size or supports): don't spend the Pi on this one."""
        job = self._job(request)
        if job.state == "queued":
            job.state, job.finished = "cancelled", time.time()
        elif job.state == "slicing":
            job.state = "cancelled"
            if job.proc and job.proc.returncode is None:
                job.proc.kill()
        return web.json_response(job.as_dict())

    async def get_gcode(self, request: web.Request) -> web.StreamResponse:
        job = self._job(request)
        if job.state != "done" or not job.gcode:
            raise web.HTTPConflict(text=f"slice is {job.state}")
        return web.FileResponse(job.gcode, headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(job.gcode)}"'})

    async def _layers(self, request: web.Request) -> Tuple[Job, Tuple[Dict[str, Any], List[Any]]]:
        job = self._job(request)
        if job.state != "done" or not job.gcode:
            raise web.HTTPConflict(text=f"slice is {job.state}")
        if job.layers is None:
            job.layers = await asyncio.to_thread(sl.layer_index, job.gcode)
        return job, job.layers

    async def get_layers(self, request: web.Request) -> web.Response:
        """The first plate's layers (design/look/, A with C's layers): their heights and every outer wall."""
        _, (public, _) = await self._layers(request)
        return web.json_response(public)

    async def get_layer(self, request: web.Request) -> web.Response:
        """One layer's paths, each tagged with what it prints."""
        job, (public, starts) = await self._layers(request)
        try:
            n = int(request.match_info["n"])
        except ValueError:
            raise web.HTTPNotFound(text="no such layer")
        if not 0 <= n < len(starts):
            raise web.HTTPNotFound(text="no such layer")
        start, state = starts[n]
        end = starts[n + 1][0] if n + 1 < len(starts) else None
        return web.json_response(await asyncio.to_thread(sl.layer_paths, job.gcode, start, end, state, public["z"][n]))

    async def get_supports(self, request: web.Request) -> web.Response:
        """The first plate's supports as lines to draw (design/supports/, A). Read from the G-code once, then kept."""
        job = self._job(request)
        if job.state != "done" or not job.gcode:
            raise web.HTTPConflict(text=f"slice is {job.state}")
        if job.lines is None:
            job.lines = await asyncio.to_thread(sl.support_lines, job.gcode)
        return web.json_response(job.lines)

    async def send(self, request: web.Request) -> web.Response:
        job = self._job(request)
        if job.state != "done" or not job.gcode:
            raise web.HTTPConflict(text=f"slice is {job.state}")
        if not job.printer.moonraker:
            raise web.HTTPConflict(text=f"{job.printer.name} has no address to send to")
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            return _bad("send a JSON body, or none")
        start = bool(isinstance(body, dict) and body.get("print"))
        # IPv4 only: .local names answer slowly or not at all over IPv6 on this network.
        async with ClientSession(connector=TCPConnector(family=socket.AF_INET),
                                 timeout=ClientTimeout(total=300)) as s:
            names = []
            for k, plate in enumerate(job.plates or [{"gcode": job.gcode}]):
                form = FormData()
                form.add_field("file", open(plate["gcode"], "rb"), filename=os.path.basename(plate["gcode"]))
                if start and k == 0:
                    form.add_field("print", "true")
                async with s.post(f"{job.printer.moonraker}/server/files/upload", data=form) as r:
                    if r.status >= 300:
                        return web.json_response({"error": f"{job.printer.name} said {r.status}: {(await r.text())[:200]}"},
                                                 status=502)
                    info = await r.json()
                names.append(info.get("item", {}).get("path") or os.path.basename(plate["gcode"]))
                if k == 0:
                    printing = bool(info.get("print_started"))
            if len(names) > 1:
                # What Now offers when each plate is done (printer/elyir_bench_intent.py, next plate)
                after = [{"after": names[k], "file": names[k + 1], "count": sum(job.plates[k + 1]["counts"]),
                          "what": sl.plate_words([p.name for p in job.parts], job.plates[k + 1]["counts"])}
                         for k in range(len(names) - 1)]
                async with s.post(f"{job.printer.moonraker}/server/database/item",
                                  json={"namespace": "elyir-bench", "key": "next_plates", "value": after}) as r:
                    if r.status >= 300:
                        log.warning("slice %s: couldn't note the later plates: %s", job.id, r.status)
            await self._remember(s, job, names)
        job.sent, job.sent_later = names[0], names[1:]
        return web.json_response({"sent": job.sent, "printing": printing, "later": job.sent_later})


    # ── the worker ──

    async def _start(self, app: web.Application) -> None:
        self.queue = asyncio.Queue()
        self.engine = asyncio.Lock()
        app["worker"] = asyncio.create_task(self._worker())

    async def _stop(self, app: web.Application) -> None:
        app["worker"].cancel()

    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            if job.state != "queued":                    # cancelled, or failed while waiting (its printer left)
                continue
            try:
                async with self.engine:
                    await self._slice(job)
            except Exception as e:                       # one bad slice never stops the queue
                log.exception("slice %s", job.id)
                job.state, job.error, job.error_detail = "failed", "Something went wrong while slicing.", f"{type(e).__name__}: {e}"
            finally:
                job.finished = time.time()
                self._forget_old()

    async def _slice(self, job: Job) -> None:
        if job.printer.id not in self.presets:
            # the printer left (or was stopped) after this was queued: said in words, never a KeyError
            job.state, job.finished = "failed", time.time()
            job.error = f"{self.name} no longer slices for {job.printer.name}."
            return
        job.state, job.started = "slicing", time.time()
        for part in job.parts:
            if part.lay == "flat" and part.lying is None:
                part.lying = await asyncio.to_thread(sl.lying, part.model)
        p = await asyncio.to_thread(sl.plan, job.printer, job.req, self.presets[job.printer.id])
        # a brim for each part (design/brim/, A); a calibration test keeps its own
        if not job.req.test:
            default = sl.brim_default(job.req, sl.PURPOSES[job.req.purpose]["label"])
            job.brims = [await asyncio.to_thread(sl.brim_pick, part, job.req.material, default) for part in job.parts]
        orca_brims = [sl.orca_brim(b["kind"]) for b in job.brims]
        mixed = len(set(orca_brims)) > 1
        if orca_brims:
            # one brim for every part goes in the preset; parts that differ are arranged with room for a brim all round
            p.process["brim_type"] = "outer_only" if mixed else orca_brims[0]
        job.changes = sl.model_changes(job.parts, job.brims) + p.changes
        job.values, job.before = p.values, p.before
        sl.write_plan(p, job.workdir)
        out = os.path.join(job.workdir, "out")
        os.makedirs(out, exist_ok=True)
        files = await asyncio.to_thread(_prepare, job.parts, os.path.join(job.workdir, "parts"))
        models = _repeat(files, job.parts)
        three_mf = os.path.join(out, sl.PLATES_3MF)
        n = job.req.colors
        # each model's color (a 3MF that brings its own keeps them)
        ids = [p.spool + 1 for p in job.parts for _ in range(p.copies)] if n > 1 and not job.parts[0].project else None
        if mixed:
            code = await self._orca(job, sl.orca_command(self.orca, job.workdir, models, out, job.req.orient, slice_it=False,
                                                         filaments=n, ids=ids))
            if code == 0 and os.path.exists(three_mf) and job.state != "cancelled":
                own = os.path.join(job.workdir, "brims.3mf")
                await asyncio.to_thread(sl.set_brims, three_mf, own, orca_brims)
                code = await self._orca(job, sl.orca_slice_3mf(self.orca, job.workdir, own, out, filaments=n))
        else:
            code = await self._orca(job, sl.orca_command(self.orca, job.workdir, models, out, job.req.orient,
                                                         filaments=n, ids=ids))
        if job.state == "cancelled":
            return
        gcodes = sorted(Path(out).glob("plate_*.gcode"), key=lambda g: int(re.sub(r"\D", "", g.stem) or 0))
        if code != 0 or not gcodes:
            raw = _orca_error(out, job.workdir, code)
            job.state, job.error, job.error_detail = "failed", sl.explain(raw, job.printer.name), raw
            return
        try:
            where = await asyncio.to_thread(sl.read_arrangement, three_mf)
        except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
            where = {}                                   # no 3MF: everything was on the one plate
        with contextlib.suppress(OSError):
            os.remove(three_mf)                          # it carries every plate's G-code again
        n = len(job.parts)
        purge = job.req.purge or sl.default_purge(job.printer)
        for k, g in enumerate(gcodes, 1):
            placed = where.get(k, [])
            how = sl.counts(placed, n) if where else ([p.copies for p in job.parts] if k == 1 else [0] * n)
            if job.parts[0].project:
                how = [1] if k == 1 else [0]     # its objects are named by the file, not p0__
            await asyncio.to_thread(sl.mark_ours, str(g))   # the printer never learns how to slice from its own files
            if job.req.colors > 1:
                try:
                    assigned = await asyncio.to_thread(sl.assign_spools, str(g), job.req.spools, job.printer, purge)
                except ValueError as e:
                    job.state, job.error = "failed", str(e)
                    return
                if k == 1:
                    job.colors = _colors(job, assigned)
            elif job.req.slot is not None and not await asyncio.to_thread(sl.use_slot, str(g), job.req.slot, job.printer.unit):
                if not job.warnings:
                    job.warnings.append(f"{job.printer.name}'s start G-code doesn't say which slot to use, so this "
                                        "prints from whichever is loaded, not slot {}.".format(job.req.slot + 1))
            if job.thumbnail:
                await asyncio.to_thread(sl.embed_thumbnail, str(g), job.thumbnail)
            extra = sl.TESTS.get(job.req.test or "", {}).get("after_start")
            if extra and not await asyncio.to_thread(sl.after_start, str(g), extra):
                job.warnings.append(f"{job.printer.name}'s start G-code has no PRINT_START, so the test's own commands weren't added.")
            result = await asyncio.to_thread(sl.read_result, str(g))
            first = next((i for i, c in enumerate(how) if c), 0)
            name = sl.gcode_name(job.parts[first].name, job.req.material, result["seconds"], how, k, len(gcodes))
            dest = os.path.join(job.workdir, name)
            os.replace(g, dest)
            job.plates.append({"gcode": dest, "result": result, "counts": how,
                               "placed": [x for x in placed if "x" in x]})
        job.result, job.gcode = job.plates[0]["result"], job.plates[0]["gcode"]
        if job.colors:
            job.colors["grams"] = job.result.get("grams_each") or []
        job.state = "done"
        log.info("slice %s: %s in %.1fs", job.id, os.path.basename(job.gcode), time.time() - job.started)

    async def _orca(self, job: Job, cmd: List[str]) -> Optional[int]:
        """One Orca run for a job, logged to its orca.log, stopped after TIMEOUT."""
        if self.nice:
            cmd = ["nice", "-n", str(self.nice), *cmd]
        with open(os.path.join(job.workdir, "orca.log"), "ab") as logf:
            proc = job.proc = await asyncio.create_subprocess_exec(*cmd, cwd=job.workdir, env=self.env,
                                                                   stdout=logf, stderr=asyncio.subprocess.STDOUT)
            try:
                return await asyncio.wait_for(proc.wait(), TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"the slicer took longer than {TIMEOUT // 60} minutes")

    def _forget_old(self) -> None:
        now = time.time()
        for jid, job in list(self.jobs.items()):
            if job.finished and now - job.finished > KEEP_JOBS:
                shutil.rmtree(job.workdir, ignore_errors=True)
                del self.jobs[jid]
        for mid, m in list(self.models.items()):
            if now - m["created"] > KEEP_JOBS:
                shutil.rmtree(self.work / "models" / mid, ignore_errors=True)
                del self.models[mid]


    async def _remember(self, session: ClientSession, job: Job, names: List[str]) -> None:
        """What each plate sent was made of, so a part skipped mid-print can be sliced again the same way
        (design/skip-objects/): elyir-bench/sliced in Moonraker, by file name, the newest REMEMBER kept."""
        ids = [_model_id(p.model) for p in job.parts]
        if not all(ids):
            return                                       # sent with the model itself (multipart): nothing to slice again from
        r = job.req
        record = {"parts": [{"model": mid, "name": p.name, "scale": p.scale, "lay": p.lay, "brim": p.brim,
                             **({"down": p.down} if p.lay == "side" else {})}
                            for mid, p in zip(ids, job.parts)],
                  "purpose": r.purpose, "supports": r.supports, "kept": r.kept, "settings": r.settings,
                  "material": r.material.upper(), "color": r.color,
                  "slot": r.slot + 1 if r.slot is not None else None, "at": time.time()}
        url = f"{job.printer.moonraker}/server/database/item"
        try:
            async with session.get(url, params={"namespace": "elyir-bench", "key": "sliced"}) as g:
                old = (await g.json()).get("result", {}).get("value") if g.status == 200 else None
            sliced = old if isinstance(old, dict) else {}
            for name in names:
                sliced[name] = record
            keep = sorted(sliced, key=lambda k: -float((sliced[k] or {}).get("at") or 0))[:REMEMBER]
            async with session.post(url, json={"namespace": "elyir-bench", "key": "sliced", "value": {k: sliced[k] for k in keep}}) as w:
                if w.status >= 300:
                    log.warning("slice %s: couldn't remember the plate: %s", job.id, w.status)
        except Exception:
            log.exception("slice %s: remembering the plate", job.id)

REMEMBER = 30   # plates whose parts are remembered, newest kept
PRINTER_HEADER = "X-Elyir-Bench-Printer"   # set by the printer's nginx in front of a slicer elsewhere
PROFILE = "elyir-bench-slicer/printer.json"
PROFILE_PRESETS = "elyir-bench-slicer/presets/"
REFRESH = 60    # seconds between looks at a joined printer's profile
HOME_CHECK = 5  # seconds between looks at this machine's own printer.json
REFUSED_FOR = 24 * 3600   # a printer told no (or stopped) can ask again after this
OWNER = ".printer"   # in a model's folder: the printer it was uploaded through


class ProfileError(Exception):
    """Why a printer's slicing profile can't be used here, said so the installer can print it."""


def _own(folder: Path, caller: Optional[str]) -> None:
    if caller:
        (folder / OWNER).write_text(caller)


def _model_id(path: str) -> Optional[str]:
    """The id of an uploaded model from where it's kept (work/models/<id>/name)."""
    parent = Path(path).parent
    return parent.name if parent.parent.name == "models" else None


def _part(path: str, g: Dict[str, Any], lying: Optional[Dict[str, Any]] = None) -> sl.Part:
    down = g.get("down")
    return sl.Part(model=path, copies=int(g.get("copies", 1)), scale=float(g.get("scale") or 1),
                   lay=str(g.get("lay") or "file"), lying=lying, down=down if isinstance(down, list) else None,
                   brim=str(g.get("brim") or "auto"), spool=int(g.get("spool") or 0))


PIECES = "pieces"


def _write_pieces(folder: Path, parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A 3MF with colors in pieces for the app to draw, one STL each: [{piece, name, filament}]."""
    out = []
    (folder / PIECES).mkdir(exist_ok=True)
    for k, p in enumerate(sl.pieces(parts)[:200]):
        sl.write_stl(str(folder / PIECES / f"{k}.stl"), p["tris"])
        out.append({"piece": k, "name": p["name"], "filament": p["filament"]})
    return out


def _spools(given: Any) -> List[sl.Spool]:
    """The plate's colors from a request: [{material, color, filament, slot (1-based), hand}]."""
    if given in (None, []):
        return []
    if not isinstance(given, list) or not all(isinstance(s, dict) for s in given):
        raise ValueError("spools must be a list of {material, color, slot, hand}")
    out = []
    for s in given:
        slot = s.get("slot")
        out.append(sl.Spool(material=str(s.get("material") or "PLA"), color=s.get("color") or None,
                            filament=str(s["filament"]) if s.get("filament") else None,
                            slot=int(slot) - 1 if slot not in (None, "") else None, hand=s.get("hand") is True))
    return out


def _colors(job: "Job", assigned: Dict[str, Any]) -> Dict[str, Any]:
    """What the Colors card shows (design/multi-color/, B): which parts use each spool, every change, the swaps by
    hand and when, and the time the changes add (the unit's, and a swap's taken as the same)."""
    changes = assigned["changes"]
    spools = []
    for k, sp in enumerate(job.req.spools):
        spools.append({"spool": k, "parts": [i for i, p in enumerate(job.parts) if p.spool == k and not p.project],
                       "first": assigned["first"] == k,
                       "swaps": [c["at"] for c in changes if c["to"] == k and c["hand"]],
                       "changes": sum(1 for c in changes if c["to"] == k)})
    return {"spools": spools, "changes": changes, "hand_swaps": sum(1 for c in changes if c["hand"]),
            "unit_changes": sum(1 for c in changes if not c["hand"]),
            "changes_seconds": len(changes) * job.printer.change_seconds, "grams": []}


def _prepare(parts: List[sl.Part], folder: str) -> List[str]:
    """Each part as Orca gets it: turned and resized here first (Orca's own --scale crashes), and named
    p0__, p1__... so the plates it makes can be read back as parts."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, part in enumerate(parts):
        cur = part.model
        normal = part.down if part.lay == "side" else (part.lying or {}).get("flat_normal") if part.lay == "flat" else None
        if normal:
            flat = os.path.join(folder, f"flat{i}.stl")
            sl.lay_flat(cur, flat, normal)
            cur = flat
        if part.scale != 1:
            scaled = os.path.join(folder, f"scaled{i}{Path(cur).suffix.lower()}")
            sl.scale_model(cur, scaled, part.scale)
            cur = scaled
        # the cleaned name ("buildplate_bushing_open"), as Klipper and Mainsail will show it
        stem = re.sub(r"\W+", "_", sl.display_name(part.name)).strip("_").lower() or "part"
        dest = os.path.join(folder, sl.part_file(i, stem + Path(cur).suffix.lower()))
        shutil.copyfile(cur, dest)
        out.append(dest)
    return out


def _repeat(files: List[str], parts: List[sl.Part]) -> List[str]:
    """Each copy as a file of its own (p0c0__, p0c1__...): a hard link, so 25 bushings cost nothing. Orca
    names objects after their files, and Klipper can only skip a copy whose name is its own."""
    out = []
    for i, (f, p) in enumerate(zip(files, parts)):
        folder, name = os.path.split(f)
        name = re.sub(r"^p\d+__", "", name)
        for k in range(p.copies):
            dest = os.path.join(folder, sl.part_file(i, name, k))
            if not os.path.exists(dest):
                try:
                    os.link(f, dest)
                except OSError:
                    shutil.copyfile(f, dest)
            out.append(dest)
    return out


def _orca_error(out: str, workdir: str, code: Optional[int]) -> str:
    """Orca leaves its reason in result.json; failing that, the last error line it logged."""
    try:
        with open(os.path.join(out, "result.json")) as f:
            msg = json.load(f).get("error_string")
            if msg:
                return msg
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(workdir, "orca.log"), errors="replace") as f:
            errs = [l.strip() for l in f if "[error]" in l or l.startswith("Error")]
        if errs:
            return errs[-1].split("[error]")[-1].strip()[-300:]
    except OSError:
        pass
    return f"the slicer stopped with exit code {code}"


def _bad(msg: str) -> web.Response:
    return web.json_response({"error": msg}, status=400)


def _err(status: int, msg: str, **more: Any) -> web.Response:
    return web.json_response({"error": msg, **more}, status=status)


def _http(status: int, msg: str, **more: Any) -> web.HTTPException:
    """An error to raise from inside a handler, with the JSON body the app reads its words from."""
    cls = {400: web.HTTPBadRequest, 403: web.HTTPForbidden, 404: web.HTTPNotFound}[status]
    return cls(text=json.dumps({"error": msg, **more}), content_type="application/json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, help="printers and paths, see slicer/slicer.example.json")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--work", default="~/.cache/elyir-bench-slicer", help="where models and G-code are kept")
    ap.add_argument("--moonraker", help="send every printer's files here instead (the simulator, in dev)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with open(os.path.expanduser(a.config)) as f:
        config = json.load(f)
    if a.moonraker:
        for p in config["printers"].values():
            p["moonraker"] = a.moonraker
    web.run_app(Service(config, a.work).app(), host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
