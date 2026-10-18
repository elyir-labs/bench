// Draws the simulator's pretend camera: 16 JPEG frames of a toolhead sweeping over a print,
// played in a loop by sim.py as an MJPEG stream. Re-run only if the picture should change:
//   node simulator/camera/make-frames.mjs     (needs Playwright)
import { chromium } from 'playwright'
import { readFileSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const here = path.dirname(fileURLToPath(import.meta.url))
const thumb = 'data:image/svg+xml;base64,' + readFileSync(path.join(here, '../thumbs/phone_stand-400x300.svg')).toString('base64')
const N = 16
const page = (i) => `<!doctype html><style>
  html, body { margin: 0; width: 640px; height: 480px; overflow: hidden; background: #111; }
  .cam { position: absolute; inset: 0; background: radial-gradient(90% 70% at 50% 30%, #3d424c, #121418 75%); }
  .gantry { position: absolute; left: 0; right: 0; top: 15%; height: 7%; background: linear-gradient(#24272d, #101215); }
  .bed { position: absolute; left: 6%; right: 6%; bottom: 8%; height: 34%; background: linear-gradient(#2c3037, #1a1d22);
         transform: perspective(500px) rotateX(48deg); transform-origin: 50% 100%; border-radius: 6px; }
  .bed::after { content: ''; position: absolute; inset: 0; background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
         linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px); background-size: 24px 24px; }
  .obj { position: absolute; left: 50%; bottom: 18%; width: 46%; transform: translateX(-50%); filter: saturate(.85) brightness(.9); clip-path: inset(30% 0 0 0); }
  .head { position: absolute; top: 11%; width: 15%; height: 30%; background: linear-gradient(#2e323a, #16181d); border-radius: 6px; }
  .head::after { content: ''; position: absolute; left: 44%; bottom: -10%; width: 12%; height: 14%; background: #c0903a; border-radius: 0 0 3px 3px; }
  .grain { position: absolute; inset: 0; background: repeating-linear-gradient(0deg, rgba(255,255,255,.03) 0 1px, transparent 1px 3px); }
  .stamp { position: absolute; right: 12px; bottom: 10px; font: 600 13px system-ui; color: rgba(255,255,255,.45); }
</style><div class="cam"><div class="gantry"></div><div class="bed"></div><img class="obj" src="${thumb}">
<div class="head" style="left:${34 + 18 * Math.sin((i / N) * 2 * Math.PI)}%"></div><div class="grain"></div><div class="stamp">SIMULATED CAMERA</div></div>`

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 640, height: 480 } })
for (let i = 0; i < N; i++) {
  await p.setContent(page(i))
  await p.screenshot({ path: path.join(here, `frame-${String(i).padStart(2, '0')}.jpg`), type: 'jpeg', quality: 72 })
}
await b.close()
console.log(`${N} frames in ${here}`)
