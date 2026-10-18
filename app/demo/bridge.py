"""The simulator, in the browser.

sim-worker.js loads this into Pyodide next to an unchanged copy of simulator/ and printer/.
sim.py imports aiohttp for its web server; here there is no server, so a stand-in module gives it
the few names it touches at import time and in its logic (the HTTP errors). Everything else is
the real pretend printer and the real intent engine: requests arrive as JSON-RPC text from the
page's stand-in websocket and go to sim.dispatch, and what the printer broadcasts goes back to
every open screen.
"""

import asyncio
import json
import sys
import time
import types


# ---- aiohttp stand-in -------------------------------------------------------------------------

class _Anything:
    """Any aiohttp name sim.py mentions but the browser never uses (Request, Response, ...)."""

    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)


class HTTPException(Exception):
    status = 500

    def __init__(self, *args, text=None, **kwargs):
        super().__init__(text or "")
        self.text = text or ""


class HTTPNotFound(HTTPException):
    status = 404


class HTTPBadRequest(HTTPException):
    status = 400


web = types.ModuleType("aiohttp.web")
web.HTTPException = HTTPException
web.HTTPNotFound = HTTPNotFound
web.HTTPBadRequest = HTTPBadRequest
web.middleware = lambda fn: fn
web.__getattr__ = lambda name: _Anything   # PEP 562: every other name
aiohttp = types.ModuleType("aiohttp")
aiohttp.web = web
aiohttp.WSMsgType = types.SimpleNamespace(TEXT=1)
sys.modules["aiohttp"] = aiohttp
sys.modules["aiohttp.web"] = web

sys.path.insert(0, "/sim/simulator")
import sim as S  # noqa: E402


# ---- the printer --------------------------------------------------------------------------------

class DemoPrinter(S.SimPrinter):
    base = ""   # the demo's own address, for the Advanced page

    def broadcast(self, method, params):
        send_all(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, default=str))

    def intent(self):
        i = super().intent()
        i["printer"]["advanced_url"] = self.base + "advanced.html"
        return i


printer = None
send_all = lambda text: None   # noqa: E731  set by start()


async def _ticker():
    last = time.time()
    while True:
        await asyncio.sleep(1.0)
        now = time.time()
        try:
            printer.physics(now - last)
        except Exception as e:  # keep the demo alive, as sim.py's own ticker would not
            print("physics:", e)
        last = now


async def start(base, send, scenario="day", speed=4.0, name="Workshop"):
    """base: the demo's address ending in '/'; send(text): to every open screen."""
    global printer, send_all
    send_all = send
    DemoPrinter.base = base
    printer = DemoPrinter(name, speed)
    printer.webcams = [{
        "name": "Main", "enabled": True, "service": "mjpegstreamer-adaptive",
        # an animated picture of the same frames sim.py streams; an <img> shows both the same way
        "stream_url": base + "camera.webp", "snapshot_url": base + "camera.jpg",
        "flip_horizontal": False, "flip_vertical": False, "rotation": 0,
        "aspect_ratio": "4:3", "target_fps": S.CAMERA_FPS, "location": "printer",
    }]
    asyncio.ensure_future(_ticker())
    await printer.start_scenario(scenario)


async def rpc(text):
    """One JSON-RPC request from a screen; returns the reply text, or None for a notification."""
    try:
        req = json.loads(text)
    except ValueError:
        return None
    req_id = req.get("id")
    try:
        result = await S.dispatch(printer, req.get("method", ""), req.get("params"))
        reply = S.rpc_result(req_id, result)
    except HTTPException as e:
        reply = S.rpc_error(req_id, -32601 if e.status == 404 else -32000, e.text or str(e))
    except Exception as e:
        reply = S.rpc_error(req_id, -32000, str(e))
    return reply if req_id is not None else None


def scenarios():
    return json.dumps({"scenarios": {k: (v.__doc__ or "").strip() for k, v in S.SCENARIOS.items()},
                       "running": printer.scenario_name, "ace": printer.ace})


async def run(name):
    await printer.start_scenario(name)
    return json.dumps({"ok": True, "scenario": name})


def insert(slot):
    printer.insert_spool(int(slot), None)
    return json.dumps({"ok": True, "slot": int(slot)})
