"""A door for each printer the box speaks for (docs/door.md, docs/bench.md "Printers the box speaks for").

A Kobra has no Pi to run the door, so the box runs one per Kobra, in front of that Kobra's stand-in, which already
publishes the intent and its events as a printer's Moonraker does:

  its public name   claimed on the relay with its own secret (state/bench/standins/<id>/relay.json, 0600)
  door.py           its own process and state (phones, push keys), on three loopback ports of its own
  frpc              its own tunnel, logged in as its name, to the one Caddy below
  Caddy             one for every Kobra: each name's certificate (TLS-ALPN-01 through the relay), on 127.0.0.1:9444

The box's own public name (design/bench-remote/, C) is claimed and tunnelled the same way, with its own secret
(state/bench/box/relay.json, 0600), and the same Caddy serves it in front of the box's away listener (bench/away.py).

Pairing is at the printer as anywhere: the Kobra's screen opened on the box (Care, Phones) reaches the door's house
listener through the stand-in's /door/.

Its name at home spells the box's address on the Wi-Fi (192-0-2-40.kobra-3-max.home.elyir.app), as a printer's does
its own: lego proves it over DNS-01 through the relay with the printer's secret, and the same Caddy serves it on the
Wi-Fi (--home-port, 443 on a box) in front of the door's home listener, so a phone at home never goes through the relay.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import ClientError, ClientSession, ClientTimeout

log = logging.getLogger("doors")

RELAY_API = "https://api.elyir.app"
ACME_CA = "https://acme-v02.api.letsencrypt.org/directory"
CADDY_PORT = 9444          # the Kobras' Caddy; a printer's own door (if the box had one) keeps 9443
DOOR_PORTS = 8200          # each Kobra's door: away, home and house listeners from 8200 + 4 × its place
RESTART_AFTER = 3.0
LINK_EVERY = 300           # how often the relay is asked whether it carries each name (the app's secure link)
HOME_EVERY = 900           # the names at home are looked at this often: a new box address means a new name
LOG_KEEP = 1 << 20         # a log over 1 MB is set aside (as .old) when its program starts again
HERE = Path(__file__).resolve().parent
BOX = "@box"               # the box's own name, beside the Kobras': never a Kobra's id (those are slugs)


def slug(name: str) -> str:
    """What the relay is asked for: "Kobra 3 Max" -> kobra-3-max."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "printer"


def invite_code(raw: str) -> Optional[str]:
    t = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    return "-".join(t[i:i + 4] for i in (0, 4, 8)) if len(t) == 12 else None


def render_frpc(relay: Dict[str, Any], port: int = CADDY_PORT) -> str:
    """As the installer writes a printer's (installer/elyir_bench.py, render_frpc), aimed at the Kobras' Caddy."""
    name = relay["name"]
    return "\n".join([
        "# Managed by the Bench Box (bench/doors.py). Holds this printer's relay secret: mode 0600.",
        "# NOT here, deliberately: any `plugin` line. The raw handshake goes to Caddy, which holds the name's only key.",
        f'serverAddr = "{relay.get("addr", "")}"',
        "serverPort = 443",
        "loginFailExit = false",
        'auth.method = "token"',
        f'auth.token = "{relay.get("token", "")}"',
        f'user = "{name}"',
        f'metadatas.house = "{name}"',
        f'metadatas.secret = "{relay["secret"]}"',
        "transport.tls.disableCustomTLSFirstByte = false",
        'log.to = "console"',
        'log.level = "info"',
        "",
        "[[proxies]]",
        'name = "away"',
        'type = "https"',
        f'customDomains = ["{relay["address"]}"]',
        'localIP = "127.0.0.1"',
        f"localPort = {port}",
        'transport.proxyProtocolVersion = "v2"',
    ]) + "\n"


def home_name(relay: Dict[str, Any], ip: str) -> Optional[str]:
    """192-0-2-40.kobra-3-max.home.elyir.app: the relay's DNS answers it with the box's address on the Wi-Fi."""
    if not (relay.get("secret") and relay.get("address") and relay.get("name") and ip):
        return None
    try:
        if not ipaddress.ip_address(ip).is_private:
            return None
    except ValueError:
        return None
    return f"{ip.replace('.', '-')}.{relay['name']}.home.{relay['address'].split('.', 1)[1]}"


def lan_ip() -> Optional[str]:
    """The box's address on the Wi-Fi, from the routing table (nothing is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def render_caddyfile(sites: List[Tuple[str, int]], storage: Path, acme_ca: str = ACME_CA, port: int = CADDY_PORT,
                     homes: Optional[List[Tuple[str, Path, int]]] = None, home_port: int = 443) -> str:
    """Every Kobra's public name on its own certificate, each in front of its own door's away listener; and each
    name at home (its certificate from lego), in front of that door's home listener."""
    head = f"""# Managed by the Bench Box (bench/doors.py): the public names of the printers it speaks for.
{{
	admin off
	auto_https disable_redirects
	storage file_system {storage}
	servers 127.0.0.1:{port} {{
		listener_wrappers {{
			proxy_protocol {{
				timeout 5s
				allow 127.0.0.1/32 ::1/128
			}}
			tls
		}}
	}}
}}
"""
    blocks = [f"""
{address}:{port} {{
	bind 127.0.0.1
	tls {{
		issuer acme {{
			dir {acme_ca}
			disable_http_challenge
			alt_tlsalpn_port {port}
		}}
	}}
	reverse_proxy 127.0.0.1:{away}
}}
""" for address, away in sorted(sites)]
    blocks += [f"""
{name}:{home_port} {{
	tls {cert}/cert.pem {cert}/key.pem
	reverse_proxy 127.0.0.1:{local}
}}
""" for name, cert, local in sorted(homes or [])]
    return head + "".join(blocks)


async def relay_call(session: ClientSession, api: str, method: str, path: str, body: Optional[dict] = None,
                     secret: Optional[str] = None) -> Tuple[int, dict]:
    headers = {"Accept": "application/json", **({"Authorization": f"Bearer {secret}"} if secret else {})}
    try:
        async with session.request(method, api.rstrip("/") + path, json=body, headers=headers) as r:
            try:
                return r.status, await r.json(content_type=None) or {}
            except ValueError:
                return r.status, {}
    except (ClientError, OSError, asyncio.TimeoutError):
        return 0, {}            # no answer: never an exception that stops the box


def refusal(out: dict) -> str:
    d = out.get("detail")
    return (d.get("message") if isinstance(d, dict) else d) or "the relay refused it"


class Relay:
    """One printer's claim on the relay, as the installer keeps a printer's (RemoteName), in its own file."""

    def __init__(self, path: Path, api: str = RELAY_API):
        self.path, self.api = path, api

    def load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def save(self, d: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    async def claim(self, session: ClientSession, want: str, invite: Optional[str], tag: str) -> Tuple[bool, str]:
        """Its public name: the one held already (an invite code goes to it), else the first of want, the relay's
        suggestion and want-<tag> it gets. A name it can't get never fails anything: the next try asks again."""
        r = self.load()
        if r.get("name") and r.get("secret"):
            if not invite:
                return True, f"{r['address']}, claimed"
            code, out = await relay_call(session, self.api, "POST", f"/houses/{r['name']}/invite", {"code": invite}, r["secret"])
            if code == 200:
                return True, f"invite code used: the relay carries {r['address']}"
            if code != 404:
                return True, f"the invite code wasn't used: {refusal(out) if code else 'no answer from the relay'}"
            r = {}      # the relay let the name go (unapproved for a day): claimed again below, with the code
        tried, todo, code, out = [], [want], 0, {}
        while todo and len(tried) < 4:
            name = todo.pop(0)
            if name in tried:
                continue
            tried.append(name)
            code, out = await relay_call(session, self.api, "POST", "/houses", {"name": name, **({"invite": invite} if invite else {})})
            if code == 403 and invite:
                invite = None
                tried.pop()
                todo.insert(0, name)
                continue
            if code == 409:
                detail = out.get("detail") if isinstance(out.get("detail"), dict) else {}
                todo = [n for n in detail.get("suggestions", []) if isinstance(n, str)][:1] + [f"{tried[0]}-{tag}"] + todo
                continue
            if code == 422 and len(tried) == 1:     # kept for the service itself (bench, printers): this name, made its own
                todo = [f"{tried[0]}-{tag}"] + todo
                continue
            break
        if code != 201:
            why = "no answer from the relay" if code == 0 else f"{', '.join(tried)} taken" if code == 409 else refusal(out)
            return False, f"no public name yet ({why})"
        self.save({"name": out["name"], "address": out["address"], "secret": out["secret"],
                   "addr": (out.get("relay") or {}).get("addr", ""), "token": (out.get("relay") or {}).get("token", "")})
        return True, (f"claimed {out['address']}; the relay carries it" if out.get("carried") else
                      f"claimed {out['address']}; the relay carries it once Elyir approves it, or with an invite code")

    async def carried(self, session: ClientSession) -> Optional[bool]:
        r = self.load()
        if not r.get("secret"):
            return False
        code, st = await relay_call(session, self.api, "GET", f"/houses/{r['name']}", secret=r["secret"])
        return bool(st.get("carried")) if code == 200 else None


class Process:
    """A program kept running, as systemd's Restart=always would."""

    def __init__(self, label: str, argv: List[str], logfile: Path, spawn=asyncio.create_subprocess_exec):
        self.label, self.argv, self.logfile, self.spawn = label, argv, logfile, spawn
        self.proc = None
        self.task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._keep())

    async def _keep(self) -> None:
        while True:
            try:
                self.logfile.parent.mkdir(parents=True, exist_ok=True)
                if self.logfile.exists() and self.logfile.stat().st_size > LOG_KEEP:
                    self.logfile.replace(self.logfile.with_suffix(".old"))
                with open(self.logfile, "ab") as out:
                    self.proc = await self.spawn(*self.argv, stdout=out, stderr=asyncio.subprocess.STDOUT)
                code = await self.proc.wait()
                log.warning("%s stopped (%s): see %s", self.label, code, self.logfile)
            except (OSError, ValueError) as e:
                log.error("%s couldn't start: %s", self.label, e)
            await asyncio.sleep(RESTART_AFTER)

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()


def binary(bin_dir: Path, name: str) -> Optional[Path]:
    """The installer's pinned copy (~/elyir-bench/bin/<name>-<version>), the newest if there are several."""
    found = sorted(bin_dir.glob(f"{name}-*"), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.name)])
    return next((p for p in reversed(found) if os.access(p, os.X_OK)), None)


class Doors:
    def __init__(self, state: Path, api: str = RELAY_API, bin_dir: Path = Path.home() / "elyir-bench" / "bin",
                 python: str = sys.executable, door_py: Path = HERE.parent / "door" / "door.py", acme_ca: str = ACME_CA,
                 tag: str = "box", spawn=asyncio.create_subprocess_exec, home_port: int = 0, ip=lan_ip):
        self.state, self.api, self.bin_dir, self.python, self.door_py = state, api, bin_dir, python, door_py
        self.acme_ca, self.tag, self.spawn, self.home_port, self.ip = acme_ca, tag, spawn, home_port, ip
        self.links: Dict[str, str] = {}                  # id -> off | waiting | on, as the relay last said
        self.running: Dict[str, Dict[str, Any]] = {}     # id -> {door, frpc, address, away, house}
        self.caddy: Optional[Process] = None
        self.session: Optional[ClientSession] = None

    def _dir(self, pid: str) -> Path:
        return self.state / "box" if pid == BOX else self.state / "standins" / pid

    def relay(self, pid: str) -> Relay:
        return Relay(self._dir(pid) / "relay.json", self.api)

    @staticmethod
    def ports(standin_port: int) -> Tuple[int, int, int]:
        """away, home, house: four ports for each Kobra, by its stand-in's place from 8101."""
        base = DOOR_PORTS + 4 * max(0, standin_port - 8101)
        return base, base + 1, base + 2

    async def _session(self) -> ClientSession:
        if self.session is None or self.session.closed:
            self.session = ClientSession(timeout=ClientTimeout(total=20))
        return self.session

    async def claim(self, pid: str, want: str, invite: Optional[str]) -> Tuple[bool, str]:
        return await self.relay(pid).claim(await self._session(), slug(want), invite_code(invite or "") if invite else None, self.tag)

    def missing(self) -> List[str]:
        out = [n for n in ("caddy", "frpc") if not binary(self.bin_dir, n)]
        if not self.door_py.is_file():
            out.append("door.py")
        return out

    async def start(self, pid: str, printer: Dict[str, Any]) -> Optional[str]:
        """Open its door, when it has a name. Says why not otherwise."""
        r = self.relay(pid).load()
        if not (r.get("address") and r.get("secret")):
            return "no public name yet"
        if self.missing():
            return "the box is missing " + ", ".join(self.missing()) + " (elyir-bench apply downloads them)"
        await self.stop(pid)
        away, home, house = self.ports(printer["port"])
        here = f"http://127.0.0.1:{printer['port']}"
        door_state = self.state / "standins" / pid / "door"
        door = Process(f"{pid} door", [self.python, str(self.door_py), "--state", str(door_state), "--moonraker", here,
                                       "--app", here, "--camera", f"{here}/webcam", "--address", r["address"],
                                       "--printer-id", r["name"], "--printer-name", printer["name"],
                                       "--away-port", str(away), "--local-port", str(home), "--home-port", str(house)],
                       self.state / "standins" / pid / "door.log", self.spawn)
        conf = self.state / "standins" / pid / "frpc.toml"
        conf.write_text(render_frpc(r))
        os.chmod(conf, 0o600)
        frpc = Process(f"{pid} tunnel", [str(binary(self.bin_dir, "frpc")), "-c", str(conf)],
                       self.state / "standins" / pid / "frpc.log", self.spawn)
        door.start()
        frpc.start()
        self.running[pid] = {"door": door, "frpc": frpc, "address": r["address"], "away": away, "house": house, "local": home}
        await self._caddy()
        log.info("%s: its door is open at https://%s", pid, r["address"])
        return None

    async def open_box(self, away: int) -> Optional[str]:
        """The box's own name: its tunnel, and a site on the one Caddy in front of its away listener. Says why not."""
        r = self.relay(BOX).load()
        if not (r.get("address") and r.get("secret")):
            return "no public name yet"
        missing = [n for n in ("caddy", "frpc") if not binary(self.bin_dir, n)]
        if missing:
            return "the box is missing " + ", ".join(missing) + " (elyir-bench apply downloads them)"
        await self.stop(BOX)
        conf = self._dir(BOX) / "frpc.toml"
        conf.write_text(render_frpc(r))
        os.chmod(conf, 0o600)
        frpc = Process("box tunnel", [str(binary(self.bin_dir, "frpc")), "-c", str(conf)], self._dir(BOX) / "frpc.log", self.spawn)
        frpc.start()
        self.running[BOX] = {"frpc": frpc, "address": r["address"], "away": away, "house": None, "local": None}
        await self._caddy()
        log.info("the box's door is open at https://%s", r["address"])
        return None

    def is_open(self, pid: str) -> bool:
        return pid in self.running

    async def stop(self, pid: str) -> None:
        run = self.running.pop(pid, None)
        if run:
            for k in ("door", "frpc"):
                if run.get(k):
                    await run[k].stop()
            await self._caddy()

    async def _caddy(self) -> None:
        """One Caddy for every open door, written afresh and restarted when the set changes."""
        if self.caddy:
            await self.caddy.stop()
            self.caddy = None
        sites = [(r["address"], r["away"]) for r in self.running.values()]
        if not sites:
            return
        homes = [(h, self._home_cert(pid), r["local"]) for pid, r in self.running.items() if r["local"] and (h := self.home_of(pid))]
        conf = self.state / "doors" / "Caddyfile"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(render_caddyfile(sites, self.state / "doors" / "caddy", self.acme_ca, homes=homes,
                                         home_port=self.home_port))
        self.caddy = Process("caddy", [str(binary(self.bin_dir, "caddy")), "run", "--config", str(conf), "--adapter", "caddyfile"],
                             self.state / "doors" / "caddy.log", self.spawn)
        self.caddy.start()

    # ── its name at home ──

    def _home_cert(self, pid: str) -> Path:
        return self.state / "standins" / pid / "home-cert"

    def home_of(self, pid: str) -> Optional[str]:
        """The name at home Caddy serves: the one the certificate was last got for, if its files are there.
        The door reads the same file (its state's parent's home.json) for /door/me."""
        if not self.home_port:
            return None
        try:
            name = json.loads((self.state / "standins" / pid / "home.json").read_text()).get("name")
        except (OSError, ValueError):
            return None
        cert = self._home_cert(pid)
        return name if name and (cert / "cert.pem").exists() and (cert / "key.pem").exists() else None

    async def homecert(self, pid: str) -> Optional[str]:
        """Get or renew its name at home, as `elyir-bench homecert` does a printer's. Says what's wrong, or None; cheap
        when nothing changed (lego only asks Let's Encrypt within 30 days of expiry, or for a new name)."""
        if not self.home_port:
            return "names at home are off"
        r = self.relay(pid).load()
        name = home_name(r, self.ip() or "")
        lego = binary(self.bin_dir, "lego")
        if not name or not lego:
            return "no claimed name, or no address on the Wi-Fi" if not name else "the box has no lego"
        zone = r["address"].split(".", 1)[1]
        root = self.state / "standins" / pid / "lego"
        crt, key = root / "certificates" / f"{name}.crt", root / "certificates" / f"{name}.key"
        root.mkdir(parents=True, exist_ok=True)
        argv = [str(lego), "--accept-tos", "--email", f"{r['name']}@{zone}", "--server", self.acme_ca, "--dns", "httpreq",
                "--domains", name, "--path", str(root)] + (["renew", "--days", "30", "--no-random-sleep"] if crt.exists() else ["run"])
        env = {**os.environ, "HTTPREQ_ENDPOINT": f"{self.api.rstrip('/')}/acme", "HTTPREQ_USERNAME": r["name"],
               "HTTPREQ_PASSWORD": r["secret"]}
        proc = await self.spawn(*argv, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if not (crt.exists() and key.exists()):
            return f"no certificate for {name} yet: {out.decode(errors='replace').strip()[-200:]}"
        cert, changed = self._home_cert(pid), False
        cert.mkdir(parents=True, exist_ok=True)
        os.chmod(cert, 0o700)
        for src, dst in ((crt, cert / "cert.pem"), (key, cert / "key.pem")):
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                tmp = dst.with_suffix(".tmp")
                tmp.write_bytes(src.read_bytes())
                os.chmod(tmp, 0o600)
                os.replace(tmp, dst)
                changed = True
        home = self.state / "standins" / pid / "home.json"
        if not home.exists() or json.loads(home.read_text() or "{}").get("name") != name:
            home.write_text(json.dumps({"name": name}))
            changed = True
        if changed and pid in self.running:
            await self._caddy()
        return None

    # ── what the app's secure link says ──

    async def look(self, pid: str) -> str:
        """off (no name), waiting (claimed; Elyir hasn't approved it) or on (the relay carries it), asked now."""
        r = self.relay(pid).load()
        if not r.get("secret"):
            self.links[pid] = "off"
        else:
            carried = await self.relay(pid).carried(await self._session())
            self.links[pid] = "on" if carried else "waiting" if carried is False or pid not in self.links else self.links[pid]
        return self.links[pid]

    def link(self, pid: str) -> str:
        return self.links.get(pid) or ("waiting" if self.relay(pid).load().get("secret") else "off")

    def house(self, pid: str) -> Optional[int]:
        run = self.running.get(pid)
        return run["house"] if run else None

    async def view(self, pid: str) -> Dict[str, Any]:
        r = self.relay(pid).load()
        link = await self.look(pid)
        return {"name": r.get("name"), "address": r.get("address"), "open": pid in self.running, "carried": link == "on",
                "link": link, "home": self.home_of(pid)}

    async def close(self) -> None:
        for pid in list(self.running):
            await self.stop(pid)
        if self.session:
            await self.session.close()
