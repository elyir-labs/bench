"""A printer's camera through the Bench Box (bench_service.py), for the bed question (design/bench-print/, A-clear):
where it is from the box, how it's mounted, and its picture passed through."""
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench_service as B  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0frame\xff\xd9"


def printer(webcams) -> web.Application:
    """A printer's Moonraker and its web server in one (as on the simulator): the camera list, and /webcam/."""
    async def listing(request):
        return web.json_response({"result": {"webcams": webcams(request)}})

    async def cam(request):
        if request.query.get("action") != "stream":
            return web.Response(body=JPEG, content_type="image/jpeg")
        out = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"})
        await out.prepare(request)
        for _ in range(3):
            await out.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + JPEG + b"\r\n")
        return out
    app = web.Application()
    app.router.add_get("/server/webcams/list", listing)
    app.router.add_get("/webcam/", cam)
    return app


@pytest.fixture
async def rig(tmp_path, aiohttp_server, aiohttp_client):
    relative = lambda r: [{"name": "Off", "enabled": False, "snapshot_url": "/nope"},
                          {"name": "Bed", "service": "mjpegstreamer-adaptive", "rotation": 180, "aspect_ratio": "16:9",
                           "stream_url": "/webcam/?action=stream", "snapshot_url": "/webcam/?action=snapshot"}]
    # the simulator, and some printers, name themselves localhost: from the box that's the printer, not the box
    local = lambda r: [{"name": "Main", "service": "webrtc-camerastreamer", "stream_url": "http://localhost:1/webrtc",
                        "snapshot_url": f"http://localhost:{r.url.port}/webcam/?action=snapshot"}]
    a, b, c = (await aiohttp_server(printer(relative)), await aiohttp_server(printer(local)),
               await aiohttp_server(printer(lambda r: [])))
    bench = B.Bench(tmp_path / "bench", "Bench Box", [], scanner=lambda: [])
    bench.printers = {pid: {"name": pid.upper(), "host": "127.0.0.1", "port": s.port, "moonraker_port": s.port,
                            "home": "http://127.0.0.1:9", "token": "t"} for pid, s in (("workshop", a), ("desk", b), ("kobra3", c))}
    return await aiohttp_client(bench.app())


async def test_a_camera_is_described_and_its_picture_comes_through_the_box(rig):
    cam = await (await rig.get("/bench/p/workshop/camera")).json()
    assert cam == {"name": "Bed", "rotation": 180, "aspect_ratio": "16:9", "flip_horizontal": False, "flip_vertical": False,
                   "stream": "/bench/p/workshop/camera/stream", "snapshot": "/bench/p/workshop/camera/snapshot"}
    r = await rig.get(cam["snapshot"])
    assert r.status == 200 and r.content_type == "image/jpeg" and await r.read() == JPEG
    r = await rig.get(cam["stream"])
    assert r.status == 200 and r.content_type == "multipart/x-mixed-replace"
    assert (await r.read()).count(JPEG) == 3


async def test_localhost_means_the_printer_and_a_stream_an_img_cant_show_is_left_to_stills(rig):
    cam = await (await rig.get("/bench/p/desk/camera")).json()
    assert cam["stream"] is None and cam["snapshot"] == "/bench/p/desk/camera/snapshot"
    assert await (await rig.get(cam["snapshot"])).read() == JPEG


async def test_no_camera_is_said_plainly(rig):
    assert await (await rig.get("/bench/p/kobra3/camera")).json() is None
    assert (await rig.get("/bench/p/kobra3/camera/snapshot")).status == 404
    assert (await rig.get("/bench/p/nobody/camera")).status == 404
