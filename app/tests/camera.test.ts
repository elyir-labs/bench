// The camera in Now (design/responsive/, "B with the camera", 1 October 2026).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolveCameraUrl, cameraTransform, cameraAspect, toCameras, cameraMode, cameraShownFor } from '../src/camera/cameras.ts'

// workshop's camera as Moonraker lists it
const Workshop = {
  name: 'Main', enabled: true, service: 'mjpegstreamer-adaptive',
  stream_url: '/webcam/?action=stream', snapshot_url: '/webcam/?action=snapshot',
  flip_horizontal: true, flip_vertical: true, rotation: 0, aspect_ratio: '4:3', target_fps: 15,
}

test('a relative address goes through the page when the printer served it', () => {
  assert.equal(resolveCameraUrl('/webcam/?action=stream', 'http://workshop.local:8088/', 'http://workshop.local:8088'),
    'http://workshop.local:8088/webcam/?action=stream')
})

test("a relative address goes to the printer's port 80 when the page came from elsewhere", () => {
  assert.equal(resolveCameraUrl('/webcam/?action=stream', 'http://localhost:3000/', 'http://workshop.local:7125'),
    'http://workshop.local/webcam/?action=stream')
})

test("through a Bench Box from away, a relative address is under the printer's path there", () => {
  assert.equal(resolveCameraUrl('/webcam/?action=stream', 'https://bench.elyir.app/screens/workshop/', 'https://bench.elyir.app/screens/workshop'),
    'https://bench.elyir.app/screens/workshop/webcam/?action=stream')
})

test('an absolute address is used as given', () => {
  assert.equal(resolveCameraUrl('http://cam.local:8080/stream', 'http://localhost:3000/', 'http://workshop.local:7125'), 'http://cam.local:8080/stream')
  assert.equal(resolveCameraUrl('', 'http://localhost:3000/', 'http://workshop.local:7125'), null)
})

test('the mounting is undone: flips and rotation', () => {
  assert.equal(cameraTransform(Workshop), 'scale(-1, -1)')
  assert.equal(cameraTransform({ rotation: 90 }), 'rotate(90deg)')
  assert.equal(cameraTransform({}), '')
  assert.equal(cameraAspect({ aspect_ratio: '16:9' }), 16 / 9)
  assert.equal(cameraAspect({ aspect_ratio: '4:3', rotation: 270 }), 3 / 4)
  assert.equal(cameraAspect({}), 4 / 3)
})

test('disabled cameras and ones with no address are left out', () => {
  const list = toCameras([Workshop, { ...Workshop, name: 'Off', enabled: false }, { name: 'Empty' }], 'http://workshop.local:8088/', 'http://workshop.local:8088')
  assert.deepEqual(list.map(c => c.name), ['Main'])
  assert.equal(list[0].stream, 'http://workshop.local:8088/webcam/?action=stream')
})

test('a camera that is not MJPEG refreshes its snapshot instead', () => {
  const [c] = toCameras([{ ...Workshop, service: 'webrtc-camerastreamer' }], 'http://workshop.local:8088/', 'http://workshop.local:8088')
  assert.equal(c.stream, null)
  assert.equal(cameraMode(c, { saveData: false, watching: true }), 'stills')
})

test('live at home, stills when data is dear, always live in full screen', () => {
  const c = { stream: 's', snapshot: 'p' }
  assert.equal(cameraMode(c, { saveData: false, watching: false }), 'live')
  assert.equal(cameraMode(c, { saveData: true, watching: false }), 'stills')
  assert.equal(cameraMode(c, { saveData: true, watching: true }), 'live')
})

test('the camera replaces the ring in every state but Ready', () => {
  for (const s of ['preparing', 'printing', 'needs_you', 'problem', 'finished']) assert.equal(cameraShownFor(s), true, s)
  assert.equal(cameraShownFor('ready'), false)
  assert.equal(cameraShownFor(undefined), false)
})
