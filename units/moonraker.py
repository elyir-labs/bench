"""The service's line to Moonraker: JSON-RPC over its websocket, as an agent. Klipper macros reach the service
through remote methods (action_call_remote_method), and the service sends G-code and reads status back."""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

import aiohttp


class Moonraker:
    def __init__(self, url: str, remote: Dict[str, Callable[[Dict[str, Any]], None]],
                 on_status: Callable[[Dict[str, Any]], None], objects: Dict[str, Any]) -> None:
        self.url = url
        self.remote = remote            # remote method name -> handler(params)
        self.on_status = on_status      # each notify_status_update, and the first full status
        self.objects = objects          # what to subscribe to
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.pending: Dict[int, asyncio.Future] = {}
        self.rid = 0
        self.ready = asyncio.Event()

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Any:
        if self.ws is None:
            raise ConnectionError("Moonraker isn't connected.")
        self.rid += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.rid] = fut
        await self.ws.send_str(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self.rid}))
        m = await asyncio.wait_for(fut, timeout)
        if "error" in m:
            err = m["error"]
            raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
        return m.get("result")

    async def gcode(self, script: str, timeout: float = 600.0) -> None:
        logging.getLogger("units").info("gcode %s", script.replace("\n", " | "))
        await self.call("printer.gcode.script", {"script": script}, timeout)
        logging.getLogger("units").info("gcode done %s", script.split("\n")[-1])

    async def _setup(self) -> None:
        await self.call("server.connection.identify", {"client_name": "elyir-units", "version": "1",
                                                       "type": "agent", "url": ""})
        for name in self.remote:
            await self.call("connection.register_remote_method", {"method_name": name})
        res = await self.call("printer.objects.subscribe", {"objects": self.objects})
        self.on_status((res or {}).get("status") or {})
        self.ready.set()

    async def run(self, retry: float = 5.0) -> None:
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.url, heartbeat=20) as ws:
                        self.ws = ws
                        setup = asyncio.ensure_future(self._setup())
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            m = json.loads(msg.data)
                            method = m.get("method")
                            if method == "notify_status_update":
                                self.on_status((m.get("params") or [{}])[0])
                            elif method in self.remote:
                                params = m.get("params")
                                self.remote[method](params if isinstance(params, dict) else {})
                            elif "id" in m:
                                fut = self.pending.pop(m["id"], None)
                                if fut and not fut.done():
                                    fut.set_result(m)
                        setup.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.info("units: Moonraker went away: %s", e)
            finally:
                self.ws = None
                self.ready.clear()
                for fut in self.pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Moonraker went away"))
                self.pending.clear()
            await asyncio.sleep(retry)
