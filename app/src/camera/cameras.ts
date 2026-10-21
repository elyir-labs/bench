// The printer's cameras, as Moonraker lists them (server.webcams.list), made ready to show.
//
// Pure functions only, so tests/camera.test.ts can pin them. useCameras.ts keeps the list live.
//
// Moonraker gives stream and snapshot addresses as the webcam was configured, usually relative
// ("/webcam/?action=stream"). They are relative to the web server in front of the camera:
//   - the page came from the printer itself (Elyir Bench's nginx proxies /webcam/ like Mainsail's):
//     resolve against the page
//   - the page came from somewhere else (Vite in dev, ?printer=workshop.local:7125): resolve against
//     the printer's port 80, where Mainsail's nginx serves them

export interface MoonrakerWebcam {
  name: string
  enabled?: boolean
  service?: string
  stream_url?: string
  snapshot_url?: string
  flip_horizontal?: boolean
  flip_vertical?: boolean
  rotation?: number
  aspect_ratio?: string
  target_fps?: number
}

export interface Camera {
  name: string
  stream: string | null
  snapshot: string | null
  /** CSS transform that undoes the camera's mounting, e.g. "scale(-1, -1)". Empty when none. */
  transform: string
  /** Width over height of the picture as it is shown (after rotation). */
  aspect: number
  fps: number
}

/** Services whose stream address is an MJPEG stream an <img> can show. Others (WebRTC, HLS)
 *  fall back to refreshing the snapshot. */
const MJPEG = new Set(['mjpegstreamer', 'mjpegstreamer-adaptive', 'uv4l-mjpeg', ''])

export function resolveCameraUrl(url: string | undefined | null, pageUrl: string, printerHttp: string): string | null {
  if (!url) return null
  if (/^[a-z]+:\/\//i.test(url)) return url
  const page = new URL(pageUrl)
  const printer = new URL(printerHttp)
  if (page.hostname !== printer.hostname) return new URL(url, `${printer.protocol}//${printer.hostname}/`).toString()
  const under = printer.pathname.replace(/\/$/, '')   // through a Bench Box, the printer is under /screens/<id>
  return new URL((url.startsWith('/') ? under : '') + url, page.origin + under + '/').toString()
}

export function cameraTransform(c: Pick<MoonrakerWebcam, 'flip_horizontal' | 'flip_vertical' | 'rotation'>): string {
  const parts: string[] = []
  const r = ((c.rotation ?? 0) % 360 + 360) % 360
  if (r) parts.push(`rotate(${r}deg)`)
  const sx = c.flip_horizontal ? -1 : 1
  const sy = c.flip_vertical ? -1 : 1
  if (sx !== 1 || sy !== 1) parts.push(`scale(${sx}, ${sy})`)
  return parts.join(' ')
}

export function cameraAspect(c: Pick<MoonrakerWebcam, 'aspect_ratio' | 'rotation'>): number {
  const m = /^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/.exec(c.aspect_ratio ?? '')
  const a = m ? Number(m[1]) / Number(m[2]) : 4 / 3
  const r = ((c.rotation ?? 0) % 360 + 360) % 360
  return r === 90 || r === 270 ? 1 / a : a
}

export function toCameras(list: MoonrakerWebcam[], pageUrl: string, printerHttp: string): Camera[] {
  return list
    .filter(w => w.enabled !== false)
    .map(w => {
      const snapshot = resolveCameraUrl(w.snapshot_url, pageUrl, printerHttp)
      const mjpeg = MJPEG.has(w.service ?? '')
      return {
        name: w.name,
        stream: mjpeg ? resolveCameraUrl(w.stream_url, pageUrl, printerHttp) : null,
        snapshot,
        transform: cameraTransform(w),
        aspect: cameraAspect(w),
        fps: w.target_fps ?? 15,
      }
    })
    .filter(c => c.stream || c.snapshot)
}

/** Live video, or a still refreshed now and then.
 *  Stills when there is no stream, when data is dear (the browser says to save data, or the
 *  phone is on cellular), or when the printer is idle, unless the person asked to watch.
 *  Full screen always asks. */
export type CameraMode = 'live' | 'stills'
export function cameraMode(c: Pick<Camera, 'stream' | 'snapshot'>, opts: { saveData: boolean; watching: boolean; idle?: boolean }): CameraMode {
  if (!c.stream) return 'stills'
  if (opts.watching) return 'live'
  if ((opts.saveData || opts.idle) && c.snapshot) return 'stills'
  return 'live'
}

/** Seconds between stills: an idle printer changes slowly, so it is asked less often. */
export function stillEvery(idle: boolean): number {
  return idle ? 10 : 2
}

/** How Now shows the camera, off the printer's own screen (design/camera-anytime/, A): in every state, Ready
 *  included, so the bed can be seen before a print. Ready is idle (a still now and then) unless it is warming
 *  up, which is watched like a print getting ready. */
export function nowCamera(state: string | undefined, opts: { warming: boolean }): 'live' | 'idle' | null {
  if (!state) return null
  return state === 'ready' && !opts.warming ? 'idle' : 'live'
}
