<template>
  <main class="add-page">
    <router-link v-if="printers.length && mode !== 'added' && mode !== 'camera'" to="/" class="back">‹ Printers</router-link>

    <!-- Added: from a scan, a code, or an ask that was allowed -->
    <section v-if="mode === 'added'" class="center">
      <div class="tick" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <h1 class="a-display">Added {{ addedName }}</h1>
      <p class="sub">This {{ kind }} can see it and get its notifications, at home and away.</p>
      <p class="hint">Opening {{ addedName }}…</p>
    </section>

    <!-- iPhone in Safari after scanning: nothing is paired here (the Home Screen app keeps its own storage) -->
    <section v-else-if="mode === 'install'">
      <h1 class="a-display">Add Printers to your Home Screen</h1>
      <p class="sub">On iPhone, notifications only reach the Home Screen app. Nothing is added here.</p>
      <ol class="steps">
        <li>Tap <b>Share</b>, then <b>Add to Home Screen</b>.</li>
        <li>Open <b>Printers</b> and tap <b>Add a printer</b>.</li>
        <li>Tap <b>{{ scannedName }}</b>, then Allow on the printer's screen.</li>
      </ol>
      <button class="link" @click="pairWithCode(scanned.p, scanned.c)">Just use Safari, without notifications</button>
    </section>

    <!-- Adding with the code from a scan -->
    <section v-else-if="mode === 'scanning'" class="center">
      <p class="hint">Adding {{ scannedName }}…</p>
    </section>

    <!-- Waiting for somebody at the printer to say yes -->
    <section v-else-if="mode === 'asking'" class="center">
      <div class="ring" :style="{ '--v': asking.left / asking.total }"><span class="a-num">{{ clock(asking.left) }}</span></div>
      <h1 class="a-display">Asking {{ asking.label }}</h1>
      <p class="sub">Allow it on the printer's screen, or on a phone at home that's already paired with it.</p>
      <p class="hint">This {{ kind }} is asking as “{{ name }}”.</p>
      <button class="a-btn ghost" @click="stopAsking">Cancel</button>
    </section>

    <section v-else-if="mode === 'refused' || mode === 'expired'" class="center">
      <h1 class="a-display">{{ mode === 'refused' ? `${asking.label} said not now` : 'No answer in time' }}</h1>
      <p class="sub">{{ mode === 'refused' ? 'Someone at the printer turned this down.' : 'Nobody allowed it within two minutes.' }}</p>
      <button class="a-btn accent" @click="askTo(asking.target!)">Ask again</button>
      <button class="link" @click="mode = 'pick'">Back</button>
    </section>

    <section v-else-if="mode === 'away'">
      <h1 class="a-display">Add a printer</h1>
      <div class="notice">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5L12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        <span><b>Ask from home</b>A printer only takes new devices on its own Wi-Fi. Connect to your home Wi-Fi and try again, or use a code from the printer's screen.</span>
      </div>
      <button class="a-btn accent full" @click="mode = 'pick'; findNearby()">Try again</button>
      <button class="link" @click="mode = 'pick'; showCode = true">Have a code?</button>
    </section>

    <!-- Scanning the printer's code with this device's camera (design/scan/) -->
    <section v-else-if="mode === 'camera'" class="camera">
      <button class="link" @click="stopScanning">‹ Add a printer</button>
      <h1 class="a-display">Scan the printer's code</h1>
      <div class="viewfinder">
        <video ref="video" autoplay muted playsinline disablepictureinpicture></video>
        <span v-if="!cameraLive" class="starting">Starting the camera…</span>
        <div class="corners" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      </div>
      <p v-if="refusal" class="err" role="status">{{ refusal }}</p>
      <p class="sub">Point this {{ kind }} at the code on the printer's screen.</p>
      <p class="hint">On the printer: Care, then Phones, then Add a phone.</p>
      <span class="grow-v"></span>
      <button class="a-btn ghost full" @click="stopScanning">Cancel</button>
    </section>

    <!-- Pick: scan the printer's code, printers on this Wi-Fi, a name, or a code -->
    <section v-else>
      <h1 class="a-display">Add a printer</h1>
      <div v-if="cameraTrouble" class="notice">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 3l18 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span v-if="cameraTrouble === 'denied'"><b>The camera isn't allowed</b>Tap Try again and allow it, or add the printer one of these ways.
          <button class="link" @click="startScanning">Try again</button></span>
        <span v-else><b>No camera to scan with</b>This {{ kind }} has no camera Printers can use right now. Add the printer one of these ways.
          <button class="link" @click="startScanning">Try again</button></span>
      </div>
      <template v-else>
        <button class="a-btn accent full scan" @click="startScanning">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><rect x="8" y="8" width="3" height="3"/><rect x="13" y="8" width="3" height="3"/><rect x="8" y="13" width="3" height="3"/><path d="M13 13h3v3"/></svg>
          Scan the printer's code
        </button>
        <p class="hint">On the printer's screen: Care, then Phones, then Add a phone.</p>
      </template>
      <template v-if="nearby === null">
        <p class="sub">Looking for printers on this Wi-Fi…</p>
      </template>
      <template v-else-if="nearby.length">
        <p class="sub">Printers on this Wi-Fi. Tap one and allow it on the printer's screen.</p>
        <h2 class="label">On this Wi-Fi</h2>
        <div class="list">
          <div v-for="t in nearby" :key="t.away ?? t.label" class="row">
            <span class="pname">{{ t.label }}</span>
            <button v-if="added(t)" class="a-btn ghost small" disabled>Added</button>
            <button v-else class="a-btn accent small" :disabled="busy" @click="askTo(t)">Add</button>
          </div>
        </div>
        <h2 class="label">Not listed?</h2>
      </template>
      <p v-else class="sub">Type the printer's name. It asks on its screen, and you're in once someone allows it.</p>

      <form class="ask-form" @submit.prevent="askTyped">
        <label class="grow"><span class="sr">Printer name</span>
          <input v-model="typed" placeholder="Printer name, like workshop" autocapitalize="none" autocorrect="off" spellcheck="false" />
        </label>
        <button class="a-btn" :class="nearby && nearby.length ? 'ghost' : 'accent'" type="submit" :disabled="busy || !typed.trim()">Ask</button>
      </form>

      <p v-if="error" class="err">{{ error }}</p>

      <button v-if="!showCode" class="link" @click="showCode = true">Have a code?</button>
      <form v-else class="code-box" @submit.prevent="pairWithCode(where, code)">
        <span class="code-title">Have a code?</span>
        <span class="hint">From the printer's screen: Care, then Phones, then Add a phone.</span>
        <label><span>Printer</span><input v-model="where" placeholder="workshop" autocapitalize="none" autocorrect="off" spellcheck="false" /></label>
        <label><span>Code</span><input v-model="code" class="a-num codein" placeholder="ABCD-EFGH" autocapitalize="characters" spellcheck="false" maxlength="9" /></label>
        <button class="a-btn accent full" type="submit" :disabled="busy || !where.trim() || code.replace(/[^a-z0-9]/gi, '').length < 8">Add printer</button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { guessDeviceKind, guessDeviceName } from '@/door'
import { printers, printerById, savePrinter, type Addresses } from '../printers'
import { subscribePrinter } from '../push'
import { addressOf, shortName, startScan, type CameraTrouble, type Scan } from '../scan'
import { frameReader } from '../qr-frame'

interface Target { id?: string; label: string; home: string | null; away: string | null }
type Mode = 'pick' | 'camera' | 'install' | 'scanning' | 'added' | 'asking' | 'refused' | 'expired' | 'away'

const router = useRouter()
const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const standalone = window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true

const name = guessDeviceName()                 // renamed later in Phones, never asked for here
const kindOfDevice = guessDeviceKind()
const kind = kindOfDevice   // 'phone' | 'tablet' | 'computer', for "this phone can see it"
const hash = new URLSearchParams(location.hash.slice(1))
const scanned = reactive({ p: hash.get('p') ?? '', c: hash.get('c') ?? '' })   // a scanned link, or the camera
const scannedName = computed(() => (scanned.p ? shortName(scanned.p) : 'the printer').toUpperCase())

const mode = ref<Mode>('pick')
const nearby = ref<Target[] | null>(null)
const typed = ref('')
const showCode = ref(false)
const where = ref(scanned.p)
const code = ref(scanned.c.toUpperCase())
const busy = ref(false)
const error = ref<string | null>(null)
const addedName = ref('')
const asking = reactive({ label: '', left: 120, total: 120, target: null as Target | null })

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, s) % 60).padStart(2, '0')}`
const added = (t: Target) => !!t.id && !!printerById(t.id)

async function json(url: string, init: RequestInit = {}, ms = 4000): Promise<{ status: number; body: any } | null> {
  try {
    const r = await fetch(url, { cache: 'no-store', ...init, signal: AbortSignal.timeout(ms) })
    return { status: r.status, body: await r.json().catch(() => ({})) }
  } catch {
    return null   // unreachable: not on that Wi-Fi, a local-network prompt said no, or the printer is off
  }
}

/** Ask the relay which printers share this Wi-Fi's public address, and keep the ones that are printers. */
async function findNearby() {
  nearby.value = null
  const r = await json('https://nearby.elyir.app/nearby', {}, 3000)
  const names: string[] = Array.isArray(r?.body?.names) ? r!.body.names : []
  const found = await Promise.all(names.map(async (n) => {
    const base = `https://${n}.elyir.app`
    const me = await json(`${base}/door/me`, {}, 3000)
    if (me?.status !== 200 || !me.body?.printer) return null   // a home hub answers 403: not a printer
    return { id: me.body.printer.id, label: me.body.printer.name, home: me.body.addresses?.home ?? null, away: me.body.addresses?.away ?? base } as Target
  }))
  nearby.value = found.filter((t): t is Target => !!t)
}

async function askTyped() {
  error.value = null
  busy.value = true
  const base = addressOf(typed.value)
  const me = await json(`${base}/door/me`)
  busy.value = false
  if (me?.status !== 200 || !me.body?.printer) {
    error.value = `Can't find ${typed.value.trim()}. Check the name, and that it's on.`
    return
  }
  // reached through its home name already: that is where to ask
  const home = me.body.role === 'home' ? base : (me.body.addresses?.home ?? null)
  await askTo({ id: me.body.printer.id, label: me.body.printer.name, home, away: me.body.addresses?.away ?? base })
}

let polling = 0
let ticking = 0
function stopAsking() {
  window.clearTimeout(polling)
  window.clearInterval(ticking)
  polling = ticking = 0
  if (mode.value === 'asking') mode.value = 'pick'
}

async function askTo(t: Target) {
  error.value = null
  asking.target = t
  asking.label = t.label
  if (!t.home) { mode.value = 'away'; return }
  busy.value = true
  const r = await json(`${t.home}/door/ask`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, kind: kindOfDevice }),
  }, 6000)
  busy.value = false
  if (!r || r.status === 403) { mode.value = 'away'; return }   // its home name isn't reachable from here
  if (r.status !== 201) { error.value = r.body?.message || "The printer couldn't take the ask. Try again."; mode.value = 'pick'; return }
  const handle: string = r.body.handle
  asking.total = Math.max(1, Math.round(r.body.expires - Date.now() / 1000))
  asking.left = asking.total
  mode.value = 'asking'
  ticking = window.setInterval(() => { asking.left = Math.max(0, Math.round(r.body.expires - Date.now() / 1000)) }, 1000)
  const poll = async () => {
    if (mode.value !== 'asking') return
    const s = await json(`${t.home}/door/ask/${encodeURIComponent(handle)}`, {}, 4000)
    if (mode.value !== 'asking') return
    if (s?.status === 404 || s?.body?.state === 'expired') { stopAsking(); mode.value = 'expired'; return }
    if (s?.body?.state === 'refused') { stopAsking(); mode.value = 'refused'; return }
    if (s?.body?.state === 'allowed' && s.body.token) {
      stopAsking()
      await finish(s.body, t.home!)
      return
    }
    polling = window.setTimeout(poll, 1500)
  }
  poll()
}

/** Paired: keep it, give it this phone's notifications if they're on, and open it. */
/** A Bench Box answers pairing with itself, not a printer (design/bench-look/, C): it's kept as a box. */
async function finishBox(d: { token: string; box: { name: string; address: string } }, reached: string) {
  const away = reached.startsWith('https://') ? `https://${d.box.address}` : reached
  const id = 'bench-' + (d.box.address.split('.')[0] || 'box').replace(/[^a-z0-9-]/gi, '').toLowerCase()
  await savePrinter({ id, name: d.box.name, token: d.token, added: Date.now(), addresses: { home: null, away }, kind: 'bench' })
  addedName.value = d.box.name
  mode.value = 'added'
  history.replaceState(null, '', '/add')
  window.setTimeout(() => router.replace('/'), 1400)
}

async function finish(d: { token: string; printer: { id: string; name: string }; addresses?: Addresses }, reached: string) {
  // a local test door on plain http reports names it doesn't answer on: keep the one that worked
  const addresses: Addresses = reached.startsWith('https://')
    ? { home: d.addresses?.home ?? null, away: d.addresses?.away ?? null }
    : { home: null, away: reached }
  await savePrinter({ id: d.printer.id, name: d.printer.name, token: d.token, added: Date.now(), addresses })
  const p = printerById(d.printer.id)
  if (p && 'Notification' in window && Notification.permission === 'granted') await subscribePrinter(p)
  addedName.value = d.printer.name
  mode.value = 'added'
  history.replaceState(null, '', '/add')   // drop a used code from the address
  window.setTimeout(() => router.replace(`/p/${d.printer.id}`), 1400)
}

async function pairWithCode(p: string, c: string) {
  error.value = null
  busy.value = true
  if (mode.value !== 'pick') mode.value = 'scanning'
  const base = addressOf(p)
  const r = await json(`${base}/door/pair`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: c.replace(/[^a-z0-9]/gi, '').toUpperCase(), name }),
  }, 8000)
  busy.value = false
  if (r?.status === 200 && r.body?.token && !r.body.printer && r.body.box) return finishBox(r.body, base)
  if (r?.status === 200 && r.body?.token) return finish(r.body, base)
  error.value = !r ? `Can't reach ${shortName(p)}. Check the name, and that it's on.` : (r.body?.message || "That code didn't work. Get a new one from the printer.")
  mode.value = 'pick'
  showCode.value = true
}

// ---------- scanning the printer's code ----------

const video = ref<HTMLVideoElement | null>(null)
const cameraLive = ref(false)
const cameraTrouble = ref<CameraTrouble | null>(null)
const refusal = ref<string | null>(null)
// a localhost door is only for the development rig (npm run dev:shell)
const allowLocal = ['localhost', '127.0.0.1'].includes(location.hostname)
let scan: Scan | null = null

/** Scan was tapped: the camera is asked for now, never before. */
function startScanning() {
  stopScanning()
  error.value = null
  cameraTrouble.value = null
  refusal.value = null
  cameraLive.value = false
  mode.value = 'camera'
  let read: (() => Promise<string | null>) | null = null
  // started inside the tap, so getUserMedia is called while it still counts as one
  const s = startScan({
    media: navigator.mediaDevices,
    allowLocal,
    async attach(stream) {
      await nextTick()
      const v = video.value
      if (!v) return
      v.srcObject = stream as MediaStream
      await v.play().catch(() => {})
      cameraLive.value = true
      read = await frameReader(v)
    },
    decode: () => (read ? read() : Promise.resolve(null)),
    trouble(t) {
      if (scan !== s) return
      scan = null
      cameraTrouble.value = t
      mode.value = 'pick'
    },
    refused(message) { refusal.value = message },
    found(address, c) {
      if (scan !== s) return
      scan = null
      cameraLive.value = false
      tookCode(address, c)
    },
  })
  scan = s
}

/** Cancel, leaving the page, or the app going to the background: the camera goes off. */
function stopScanning() {
  scan?.stop()
  scan = null
  cameraLive.value = false
  if (video.value) video.value.srcObject = null
  if (mode.value === 'camera') mode.value = 'pick'
}

/** The camera read a printer's code: the same as opening a scanned link. */
function tookCode(address: string, c: string) {
  scanned.p = address
  scanned.c = c
  where.value = address
  code.value = c
  // an iPhone in Safari: pairing Safari leaves an unused "iPhone" in Phones; say how to get the app
  if (isIOS && !standalone) mode.value = 'install'
  else pairWithCode(address, c)
}

const onHidden = () => { if (document.visibilityState === 'hidden') stopScanning() }
document.addEventListener('visibilitychange', onHidden)

onMounted(() => {
  if (scanned.p && scanned.c) {
    // Scan = done, except an iPhone in Safari: pairing Safari would leave an unused "iPhone" in Phones
    if (isIOS && !standalone) mode.value = 'install'
    else pairWithCode(scanned.p, scanned.c)
    return
  }
  findNearby()
})
onBeforeUnmount(() => {
  stopAsking()
  stopScanning()
  document.removeEventListener('visibilitychange', onHidden)
})
</script>

<style scoped>
.add-page {
  min-height: 100dvh; box-sizing: border-box; max-width: 440px; margin: 0 auto;
  padding: calc(18px + env(safe-area-inset-top, 0px)) 20px 28px;
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font);
  display: flex; flex-direction: column;
}
section { display: flex; flex-direction: column; gap: 14px; }
.center { flex: 1; align-items: center; justify-content: center; text-align: center; }
.back { display: inline-block; color: var(--a-accent-text); text-decoration: none; font-weight: 600; font-size: 16px; margin-bottom: 14px; }
h1 { font-size: 30px; margin: 0; }
.sub { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0; }
.sub b, .steps b, .notice b { color: var(--a-ink); }
.hint { color: var(--a-ink-3); font-size: 15px; margin: 0; }
.label { margin: 8px 0 0; font-size: 13px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-ink-3); }
.list { background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.row { display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-top: 1px solid var(--a-line); }
.row:first-child { border-top: 0; }
.pname { flex: 1; font-weight: 700; font-size: 19px; }
.small { padding: 8px 18px; min-height: 44px; font-size: 16px; }
.ask-form { display: flex; gap: 10px; }
.grow { flex: 1; display: flex; }
.sr { position: absolute; left: -9999px; }
input {
  font: inherit; font-size: 18px; font-weight: 500; color: var(--a-ink); min-width: 0; flex: 1;
  background: var(--a-surface); border: 1px solid var(--a-line); border-radius: 14px;
  padding: 14px 16px; outline: none; user-select: text; -webkit-user-select: text;
}
input:focus { border-color: var(--a-accent); }
.code-box { margin-top: 6px; padding: 16px; background: var(--a-surface); border-radius: 16px; display: flex; flex-direction: column; gap: 10px; }
.code-box label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
.code-box input { background: var(--a-bg); }
.code-title { font-weight: 700; font-size: 17px; }
.codein { font-size: 22px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.full { width: 100%; }
.err { color: var(--a-red-text); font-size: 16px; margin: 0; }
.link { appearance: none; background: none; border: 0; padding: 8px 0; font: inherit; font-size: 16px; font-weight: 600; color: var(--a-accent-text); cursor: pointer; align-self: flex-start; }
.center .link { align-self: center; }
.steps { list-style: decimal; margin: 0; padding-left: 1.3em; font-size: 18px; line-height: 1.55; color: var(--a-ink-2); }
.steps li { margin: 0 0 4px; color: var(--a-ink-2); }
.tick { width: 96px; height: 96px; border-radius: 50%; background: var(--a-green); color: #fff; display: flex; align-items: center; justify-content: center; }
.tick svg { width: 50%; height: 50%; }
.ring {
  --v: 1; width: 120px; height: 120px; border-radius: 50%;
  background: conic-gradient(var(--a-accent) calc(var(--v) * 360deg), var(--a-surface-2) 0);
  display: flex; align-items: center; justify-content: center; position: relative;
}
.ring::before { content: ''; position: absolute; inset: 8px; border-radius: 50%; background: var(--a-bg); }
.ring span { position: relative; font-size: 26px; font-weight: 700; }
.notice { display: flex; gap: 14px; align-items: flex-start; padding: 18px; background: var(--a-surface); border-radius: 18px; color: var(--a-ink-2); font-size: 16px; line-height: 1.45; }
.notice svg { width: 28px; height: 28px; flex: none; color: var(--a-amber-text); }
.notice b { display: block; font-size: 19px; margin-bottom: 4px; }
.notice .link { display: block; padding-bottom: 0; }
.scan { display: flex; align-items: center; justify-content: center; gap: 10px; }
.scan svg { width: 24px; height: 24px; flex: none; }
.camera { flex: 1; }
.camera > .link:first-child { margin-bottom: -6px; }
.grow-v { flex: 1; }
.viewfinder {
  position: relative; width: 100%; aspect-ratio: 1; border-radius: 24px; overflow: hidden;
  background: #111419; color: rgba(255, 255, 255, 0.7);
}
.viewfinder video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.starting { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 16px; }
.corners { position: absolute; inset: 15%; pointer-events: none; }
.corners i { position: absolute; width: 11%; aspect-ratio: 1; border: 4px solid #fff; filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.5)); }
.corners i:nth-child(1) { left: 0; top: 0; border-right: 0; border-bottom: 0; border-top-left-radius: 14px; }
.corners i:nth-child(2) { right: 0; top: 0; border-left: 0; border-bottom: 0; border-top-right-radius: 14px; }
.corners i:nth-child(3) { left: 0; bottom: 0; border-right: 0; border-top: 0; border-bottom-left-radius: 14px; }
.corners i:nth-child(4) { right: 0; bottom: 0; border-left: 0; border-top: 0; border-bottom-right-radius: 14px; }
</style>
