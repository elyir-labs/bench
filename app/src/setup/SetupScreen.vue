<template>
  <!-- A new printer's first Wi-Fi, on its panel (design/setup/, direction C, picked 4 October 2026; docs/setup.md).
       Both ways from the first screen: the phone (a QR code for the setup Wi-Fi) or here (a list and a keyboard).
       Both meet while it joins: its name, with a tap. Then Connected and the phone code, inside a phone.
       Shown instead of the app, on the panel only, while setup/wifi_setup.py says it's setting up. -->
  <main class="setup">
    <header class="top">
      <span class="who"><svg viewBox="0 0 24 24" class="mark" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.6"/><circle cx="12" cy="12" r="3.4" fill="currentColor"/></svg><b>New printer</b></span>
      <ol class="steps" aria-label="Steps">
        <li v-for="(t, i) in STEPS" :key="t" :class="{ on: i === step, done: i < step }" :aria-current="i === step ? 'step' : undefined">
          <svg v-if="i < step" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <i v-else>{{ i + 1 }}</i>{{ t }}
        </li>
      </ol>
    </header>

    <!-- looking: listing the networks before the setup Wi-Fi opens -->
    <section v-if="screen === 'looking'" class="centered">
      <svg class="eye spin" viewBox="0 0 126 126" aria-hidden="true"><circle cx="63" cy="63" r="56" fill="none" stroke="var(--a-track)" stroke-width="13"/><circle cx="63" cy="63" r="56" fill="none" stroke="var(--a-accent)" stroke-width="13" stroke-linecap="round" stroke-dasharray="100 352" transform="rotate(-90 63 63)"/><circle cx="63" cy="63" r="22" fill="var(--a-accent)"/></svg>
      <p class="big">Looking for Wi-Fi networks</p>
      <p class="sub">A few seconds.</p>
    </section>

    <!-- start: two ways in, side by side -->
    <section v-else-if="screen === 'start'" class="start">
      <h1 class="a-display">Let's get this printer on your Wi-Fi.</h1>
      <div class="ways">
        <div class="card phone-way">
          <div class="qr"><QrCode :value="s.setup?.qr ?? ''" ecc="H" label="The printer's setup Wi-Fi" /><span class="in-qr" v-html="WIFI_SIGN" /></div>
          <div class="txt">
            <span class="label accent"><span class="ic" v-html="WIFI_SIGN" />With your phone</span>
            <p class="sub">Scan with the camera. Your phone joins the printer for a minute and asks which Wi-Fi.</p>
          </div>
        </div>
        <div class="card here-way">
          <div class="txt">
            <span class="label">Without one</span>
            <p class="sub">Pick your Wi-Fi and type its password on this screen.</p>
          </div>
          <button class="a-btn here" @click="here = { at: 'list' }">Set up here</button>
        </div>
      </div>
    </section>

    <!-- list: the networks it heard, on the panel -->
    <section v-else-if="screen === 'list'" class="list">
      <div class="side">
        <button class="a-btn ghost round" aria-label="Back" @click="here = { at: 'start' }"><span v-html="BACK" /></button>
        <h1 class="a-display">Pick your Wi-Fi.</h1>
        <p class="sub">The networks this printer can hear.</p>
        <button class="link" :disabled="busy" @click="lookAgain">Look again</button>
        <p v-if="error" class="err">{{ error }}</p>
      </div>
      <div class="card rows">
        <button v-for="n in s.networks" :key="n.ssid" class="row" :disabled="n.security === 'enterprise'" @click="pick(n)">
          <span class="ssid"><b>{{ n.ssid }}</b><small v-if="n.security === 'enterprise'">Needs a username too: not supported yet</small></span>
          <span class="sig"><span v-if="n.security !== 'open'" class="lock" v-html="LOCK" /><span v-html="barsSvg(n.signal)" /></span>
        </button>
        <p v-if="!s.networks.length" class="row none">It didn't hear any. Look again, or type yours.</p>
        <button class="row other" @click="here = { at: 'type', what: 'ssid' }"><span class="ssid">Other network…</span><span v-html="CHEV" /></button>
      </div>
    </section>

    <!-- keyboard: a password, another network's name, or the printer's own name -->
    <section v-else-if="screen === 'keyboard' && here.at === 'type'" class="typing">
      <div class="head">
        <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
        <b class="title">{{ typingTitle }}</b>
      </div>
      <label class="field" :class="{ bad: !!error }">
        <input ref="input" v-model="typed" :type="here.what === 'password' && !showing ? 'password' : 'text'" inputmode="none"
               autocomplete="off" autocapitalize="none" spellcheck="false" :aria-label="typingTitle" @keydown.enter.prevent="go" />
        <button v-if="here.what === 'password'" type="button" class="link" @pointerdown.prevent @click="showing = !showing">{{ showing ? 'Hide' : 'Show' }}</button>
      </label>
      <p class="note" :class="{ err: !!error }">{{ error ?? typingNote }}</p>
      <PanelKeyboard v-model="typed" :action="typingAction" :can-go="canGo && !busy" class="keys" @go="go" />
    </section>

    <!-- wrong: the setup Wi-Fi is back, with the same code -->
    <section v-else-if="screen === 'wrong'" class="split">
      <div class="side">
        <span class="chip amber"><i />Not connected</span>
        <h1 class="a-display">{{ wrong.headline }}</h1>
        <p class="sub">{{ wrong.sub }}</p>
        <div class="btns">
          <button class="a-btn ghost" @click="typeFor(s.ssid ?? '')">Type it here instead</button>
          <button class="a-btn ghost" @click="here = { at: 'list' }">Another network</button>
        </div>
      </div>
      <div class="card qcard">
        <span class="label accent"><span class="ic" v-html="WIFI_SIGN" />Join the printer's Wi-Fi</span>
        <div class="qr"><QrCode :value="s.setup?.qr ?? ''" ecc="H" label="The printer's setup Wi-Fi" /><span class="in-qr" v-html="WIFI_SIGN" /></div>
        <span class="caption">{{ s.setup?.ssid }}</span>
      </div>
    </section>

    <!-- name: while it joins (or once it's on, if nobody chose yet), with a tap -->
    <section v-else-if="screen === 'name'" class="naming">
      <span v-if="s.mode === 'joining'" class="chip blue"><svg class="spin mini" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="18 60" stroke-linecap="round"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>Joining {{ s.ssid }}…</span>
      <span v-else class="chip green"><i />{{ s.via === 'cable' ? 'Connected by cable' : `On ${s.ssid}` }}</span>
      <h1 class="a-display">{{ s.mode === 'joining' ? "While it joins: what's this printer called?" : "What's this printer called?" }}</h1>
      <div class="names">
        <button v-for="n in nameChoices" :key="n" class="a-btn" :class="n === s.name ? 'accent' : 'ghost'" :disabled="busy" @click="setName(n)">
          <span v-if="n === s.name" class="ic" v-html="CHECK" />{{ n }}
        </button>
        <button class="a-btn ghost" @click="here = { at: 'type', what: 'name' }; typed = ''">Another name…</button>
      </div>
      <p class="sub small">{{ s.name ? `On your Wi-Fi it will be ${hostnameFor(s.name)}.local.` : 'Tap one, or type your own.' }}</p>
      <p v-if="error" class="err">{{ error }}</p>
    </section>

    <!-- done: Connected first, then the phone code, inside a phone -->
    <section v-else-if="screen === 'done'" class="split done">
      <div class="side">
        <svg class="check" viewBox="0 0 126 126" aria-hidden="true"><circle cx="63" cy="63" r="56" fill="var(--a-tint-green)" stroke="var(--a-green)" stroke-width="13"/><path d="M40 64l15 15 31-32" fill="none" stroke="var(--a-green)" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <h1 class="a-display">{{ s.via === 'cable' ? `${s.name} is connected by cable.` : `${s.name} is on ${s.ssid}.` }}</h1>
        <template v-if="!waiting.length">
          <p class="sub">Last step: put it on your phone, to see prints and hear when one needs you.</p>
        </template>
        <div v-for="a in waiting" :key="a.id" class="ask">
          <span>{{ a.name }} wants to connect</span>
          <span class="btns">
            <button class="a-btn accent" :disabled="busy" @click="reply(a.id, true)">Allow</button>
            <button class="a-btn ghost" :disabled="busy" @click="reply(a.id, false)">Not now</button>
          </span>
        </div>
        <div class="finish">
          <button class="a-btn" :class="allowed || !code ? 'accent' : 'ghost'" :disabled="busy" @click="finish">{{ allowed || !code ? 'Done' : 'Skip for now' }}</button>
          <!-- Bring it over (docs/bring-it-over.md): Wi-Fi setup ends first, then its screen opens -->
          <button class="link bring-link" :disabled="busy" @click="bringOver">{{ WIFI_LINK }}</button>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
      </div>
      <div class="pframe">
        <b>Put {{ s.name }}<br>on your phone</b>
        <div v-if="s.renaming || !phoneLink" class="getting"><span class="spin ring" />Getting {{ s.name }} ready on the Wi-Fi…</div>
        <div v-else class="qr"><QrCode :value="phoneLink" ecc="H" :label="`Put ${s.name} on your phone`" /><span class="in-qr" v-html="EYE" /></div>
        <span class="caption">{{ code ? 'Scan with the camera' : phoneLink.replace(/^http:\/\//, '').replace(/\/$/, '') }}</span>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import QrCode from '@/components/door/QrCode.vue'
import PanelKeyboard from './PanelKeyboard.vue'
import { wifi, wifiAsk } from './useWifi'
import { NAMES, bars, homeAddress, hostnameFor, passwordProblem, screenFor, stepOf, wrongWords, type Here, type WifiNetwork } from './wifi'
import { newPairCode, type PairCode } from '@/door'
import { answer, asks, followAsks } from '@/asks'
import { useIntentStore } from '@/intent/store'
import { WIFI_LINK, bringFromWifi } from '@/intent/bring'
import { openBring } from '@/intent/useBring'

const STEPS = ['Wi-Fi', 'Name', 'Phone']
const WIFI_SIGN = '<svg viewBox="0 0 24 24"><circle cx="12" cy="18.5" r="2" fill="currentColor"/><path d="M8.4 14.6a5.2 5.2 0 0 1 7.2 0M5.3 11.4a9.6 9.6 0 0 1 13.4 0M2.3 8.2a14 14 0 0 1 19.4 0" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>'
const EYE = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="12" cy="12" r="3.6" fill="currentColor"/></svg>'
const BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>'
const CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:.4"><path d="M9 5l7 7-7 7"/></svg>'
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
const LOCK = '<svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="2.5" fill="currentColor"/><path d="M8 10V7.5a4 4 0 0 1 8 0V10" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>'
const barsSvg = (signal: number) => {
  const n = bars(signal), a = (i: number, d: string) => `<path d="${d}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" opacity="${n >= i ? 1 : 0.25}"/>`
  return `<svg viewBox="0 0 24 24" aria-label="signal ${n} of 3"><circle cx="12" cy="18.5" r="1.8" fill="currentColor"/>${a(1, 'M8.4 14.6a5.2 5.2 0 0 1 7.2 0')}${a(2, 'M5.3 11.4a9.6 9.6 0 0 1 13.4 0')}${a(3, 'M2.3 8.2a14 14 0 0 1 19.4 0')}</svg>`
}

const s = computed(() => wifi.state)
const here = ref<Here>({ at: 'start' })
const screen = computed(() => screenFor(s.value, here.value))
const step = computed(() => stepOf(screen.value, here.value))
const wrong = computed(() => wrongWords(s.value))
const busy = ref(false)
const error = ref<string | null>(null)
watch([screen, () => (here.value.at === 'type' ? here.value.what : '')], () => { error.value = null })

// ── typing ─────────────────────────────────────────────────────────────────
const typed = ref('')
const showing = ref(false)
const input = ref<HTMLInputElement | null>(null)
const security = computed(() => {
  const h = here.value
  if (h.at !== 'type' || h.what !== 'password') return 'wpa'
  return s.value.networks.find((n) => n.ssid === h.ssid)?.security ?? 'wpa'
})
const typingTitle = computed(() => {
  const h = here.value
  if (h.at !== 'type') return ''
  if (h.what === 'password') return `Password for ${h.ssid}`
  return h.what === 'ssid' ? 'Network name' : 'Name this printer'
})
const typingAction = computed(() => (here.value.at === 'type' && here.value.what === 'ssid' ? 'Next' : here.value.at === 'type' && here.value.what === 'name' ? 'Save' : 'Connect'))
const typingNote = computed(() => {
  const h = here.value
  if (h.at === 'type' && h.what === 'password') return h.hidden ? 'Leave it empty if the network has no password.' : 'The printer asks for its name while it joins.'
  if (h.at === 'type' && h.what === 'ssid') return "Exactly as it's written, capitals too."
  return typed.value.trim() ? `On your Wi-Fi it will be ${hostnameFor(typed.value)}.local.` : ''
})
const canGo = computed(() => {
  const h = here.value
  if (h.at !== 'type') return false
  if (h.what === 'password') return h.hidden && !typed.value ? true : passwordProblem(typed.value, security.value) === null
  return typed.value.trim().length > 0 && typed.value.trim().length <= 32
})

function typeFor(ssid: string, hidden = false): void {
  here.value = { at: 'type', what: 'password', ssid, hidden: hidden || !s.value.networks.some((n) => n.ssid === ssid) }
  typed.value = ''
  showing.value = false
}

function pick(n: WifiNetwork): void {
  if (n.security === 'open') { join(n.ssid, '', false); return }
  typeFor(n.ssid)
}

function back(): void {
  const h = here.value
  if (h.at === 'type' && h.what === 'name') here.value = { at: 'start' }
  else if (h.at === 'type' && h.what === 'password' && h.hidden) { here.value = { at: 'type', what: 'ssid' }; typed.value = h.ssid ?? '' }
  else here.value = { at: 'list' }
}

async function go(): Promise<void> {
  const h = here.value
  if (h.at !== 'type' || !canGo.value || busy.value) return
  if (h.what === 'ssid') { typeFor(typed.value.trim(), true); return }
  if (h.what === 'name') {
    if (await setName(typed.value)) here.value = { at: 'start' }
    return
  }
  await join(h.ssid ?? '', typed.value, !!h.hidden)
}

async function join(ssid: string, password: string, hidden: boolean): Promise<void> {
  busy.value = true
  error.value = await wifiAsk('join', { ssid, password, hidden })
  busy.value = false
  if (!error.value) { here.value = { at: 'start' }; typed.value = '' }
}

async function lookAgain(): Promise<void> {
  busy.value = true
  error.value = await wifiAsk('scan')
  busy.value = false
}

// ── naming ─────────────────────────────────────────────────────────────────
const nameChoices = computed(() => {
  const n = s.value.name
  return n && !NAMES.includes(n) ? [n, ...NAMES.slice(0, 4)] : NAMES
})

async function setName(name: string): Promise<boolean> {
  busy.value = true
  error.value = await wifiAsk('name', { name })
  busy.value = false
  return !error.value
}

// ── done: the phone code (the door's pairing when it has one, else its own address at home) ───────────
const code = ref<PairCode | null>(null)
const allowed = ref(false)
const phoneLink = computed(() => (code.value ? code.value.shell_url ?? code.value.url : s.value.host ? homeAddress(s.value) : ''))
const waiting = computed(() => asks.list.filter((a) => a.kind !== 'printer' && a.kind !== 'backup'))
let codeTimer = 0
let stopAsks: (() => void) | null = null

async function getCode(): Promise<void> {
  window.clearTimeout(codeTimer)
  try {
    code.value = await newPairCode()
    codeTimer = window.setTimeout(getCode, Math.max(30, code.value.expires - Date.now() / 1000 - 30) * 1000)
  } catch {
    code.value = null   // no door here: the phone opens the printer at home, no pairing
  }
}

watch(() => screen.value === 'done' && !s.value.renaming, (ready) => {
  if (!ready) return
  getCode()
  if (!stopAsks) stopAsks = followAsks(useIntentStore().on)
}, { immediate: true })

async function reply(id: string, allow: boolean): Promise<void> {
  busy.value = true
  try {
    await answer(id, allow)
    if (allow) allowed.value = true
  } catch (e) {
    error.value = (e as Error).message
  }
  busy.value = false
}

async function finish(): Promise<void> {
  busy.value = true
  error.value = await wifiAsk('done')
  busy.value = false
}

/** "Bring things over from another printer": the same end of Wi-Fi setup, then Bring it over's sources. */
async function bringOver(): Promise<void> {
  busy.value = true
  error.value = await bringFromWifi(() => wifiAsk('done'), openBring)
  busy.value = false
}

watch(() => here.value.at === 'type', async (typing) => {
  if (typing) { await nextTick(); input.value?.focus() }
})

onMounted(() => {
  // the boot screen's first frame (index.html) is the app's to take down: here, that's this screen
  delete document.documentElement.dataset.boot
  document.getElementById('boot-frame')?.remove()
})
onBeforeUnmount(() => {
  window.clearTimeout(codeTimer)
  stopAsks?.()
})
</script>

<style scoped>
.setup {
  --a-track: color-mix(in srgb, var(--a-ink) 10%, transparent);
  position: fixed; inset: 0; display: flex; flex-direction: column; overflow: hidden;
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font); -webkit-font-smoothing: antialiased;
}
.top { flex: none; height: calc(52 * var(--u)); padding: calc(18 * var(--u)) calc(36 * var(--u)) 0 calc(32 * var(--u)); display: flex; align-items: center; justify-content: space-between; color: var(--a-ink-3); }
.who { display: inline-flex; align-items: center; gap: calc(10 * var(--u)); }
.who .mark { width: calc(26 * var(--u)); height: calc(26 * var(--u)); color: var(--a-accent); }
.who b { font-size: calc(15 * var(--u) + 1px); letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-2); font-weight: 650; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; align-items: center; gap: calc(26 * var(--u)); font-size: calc(15 * var(--u) + 1px); font-weight: 650; }
.steps li { display: inline-flex; align-items: center; gap: calc(7 * var(--u)); position: relative; }
.steps li + li::before { content: ''; position: absolute; left: calc(-21 * var(--u)); width: calc(16 * var(--u)); height: 1.5px; background: var(--a-ink-3); opacity: .5; }
.steps i { font-style: normal; width: calc(22 * var(--u)); height: calc(22 * var(--u)); border-radius: 50%; border: 1.5px solid currentColor; display: grid; place-items: center; font-size: calc(12 * var(--u)); }
.steps svg { width: calc(22 * var(--u)); height: calc(22 * var(--u)); }
.steps .on { color: var(--a-ink); }
.steps .on i { background: var(--a-accent); border-color: transparent; color: var(--a-accent-ink); }
.steps .done { color: var(--a-green-text); }

section { flex: 1; min-height: 0; padding: calc(14 * var(--u)) calc(36 * var(--u)) calc(30 * var(--u)) calc(40 * var(--u)); }
h1 { margin: 0; font-size: calc(38 * var(--u) + 2px); }
.sub { margin: 0; color: var(--a-ink-2); font-size: calc(19 * var(--u) + 1px); line-height: 1.4; }
.sub.small { font-size: calc(17 * var(--u) + 1px); color: var(--a-ink-3); }
.err { margin: 0; color: var(--a-red-text); font-size: calc(17 * var(--u) + 1px); }
.card { background: var(--a-surface); border-radius: calc(22 * var(--u)); box-shadow: var(--a-card-shadow); }
.label { display: inline-flex; align-items: center; gap: calc(8 * var(--u)); font-size: calc(14 * var(--u) + 1px); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-2); }
.label.accent { color: var(--a-accent-text); }
.ic { display: inline-flex; width: calc(20 * var(--u)); height: calc(20 * var(--u)); }
.ic :deep(svg), .in-qr :deep(svg) { width: 100%; height: 100%; display: block; }
.link { appearance: none; border: 0; background: none; padding: calc(6 * var(--u)) 0; font: 650 calc(18 * var(--u)) var(--a-font); color: var(--a-accent-text); cursor: pointer; justify-self: start; }
.link[disabled] { opacity: .5; }
.round { flex: none; width: calc(46 * var(--u) + 4px); height: calc(46 * var(--u) + 4px); min-height: 0; padding: 0; display: grid; place-items: center; border-radius: 50%; }
.round span { width: calc(22 * var(--u)); height: calc(22 * var(--u)); display: block; }
.round span :deep(svg) { width: 100%; height: 100%; display: block; }
.chip { display: inline-flex; align-items: center; gap: calc(8 * var(--u)); justify-self: start; border-radius: 999px; padding: calc(5 * var(--u)) calc(14 * var(--u)); font-size: calc(15 * var(--u) + 1px); font-weight: 650; }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.chip.amber { background: var(--a-tint-amber); color: var(--a-amber-text); }
.chip.green { background: var(--a-tint-green); color: var(--a-green-text); }
.chip.blue { background: var(--a-tint-blue); color: var(--a-accent-text); }

/* the QR codes: the setup Wi-Fi's with the Wi-Fi sign in the middle, the phone's with the eye */
.qr { position: relative; flex: none; border-radius: calc(14 * var(--u)); overflow: hidden; }
.in-qr { position: absolute; left: 50%; top: 50%; width: 22%; height: 22%; transform: translate(-50%, -50%); background: #fff; border-radius: 18%; display: grid; place-items: center; padding: 3%; color: #1f6fe0; }

.centered { display: grid; place-content: center; justify-items: center; gap: calc(10 * var(--u)); text-align: center; padding-bottom: calc(60 * var(--u)); }
.centered .eye { width: calc(140 * var(--u)); height: calc(140 * var(--u)); margin-bottom: calc(18 * var(--u)); }
.big { margin: 0; font-size: calc(26 * var(--u) + 1px); font-weight: 650; }

.start { display: grid; grid-template-rows: auto 1fr; gap: calc(18 * var(--u)); }
.ways { display: grid; grid-template-columns: 452fr 252fr; gap: calc(20 * var(--u)); min-height: 0; }
.phone-way { display: flex; align-items: center; gap: calc(20 * var(--u)); padding: calc(20 * var(--u)) calc(22 * var(--u)); }
.phone-way .qr { width: calc(200 * var(--u)); }
.txt { display: grid; gap: calc(10 * var(--u)); align-content: start; }
.here-way { display: grid; align-content: space-between; padding: calc(22 * var(--u)); }
.here-way .here { background: var(--a-surface-2); }

.list { display: grid; grid-template-columns: calc(290 * var(--u)) 1fr; gap: calc(26 * var(--u)); }
.side { display: grid; gap: calc(14 * var(--u)); align-content: start; justify-items: start; min-width: 0; }
.rows { overflow-y: auto; align-self: start; max-height: 100%; }
.row { appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; width: 100%; min-height: calc(64 * var(--u)); display: flex; align-items: center; gap: calc(14 * var(--u)); padding: calc(8 * var(--u)) calc(20 * var(--u)); color: var(--a-ink); font: inherit; text-align: left; cursor: pointer; }
.row:first-child { border-top: 0; }
.row[disabled] { cursor: default; opacity: .6; }
.row.none { color: var(--a-ink-2); font-size: calc(18 * var(--u)); cursor: default; }
.ssid { flex: 1; min-width: 0; display: grid; font-size: calc(21 * var(--u) + 1px); overflow-wrap: anywhere; }
.ssid b { font-weight: 650; }
.ssid small { font-size: calc(14 * var(--u) + 1px); color: var(--a-ink-3); }
.other .ssid { color: var(--a-ink-2); }
.other > span:last-child { width: calc(20 * var(--u)); height: calc(20 * var(--u)); display: block; }
.other > span:last-child :deep(svg) { width: 100%; height: 100%; display: block; }
.sig { display: inline-flex; align-items: center; gap: calc(6 * var(--u)); color: var(--a-ink-2); flex: none; }
.sig > span { display: block; width: calc(26 * var(--u)); height: calc(26 * var(--u)); }
.sig .lock { width: calc(14 * var(--u)); height: calc(14 * var(--u)); opacity: .55; }
.sig :deep(svg) { width: 100%; height: 100%; display: block; }

.typing { display: flex; flex-direction: column; gap: calc(10 * var(--u)); padding: calc(8 * var(--u)) calc(36 * var(--u)) 0 calc(32 * var(--u)); }
.head { display: flex; align-items: center; gap: calc(14 * var(--u)); }
.title { font-size: calc(24 * var(--u) + 1px); font-weight: 650; overflow-wrap: anywhere; }
.field { display: flex; align-items: center; height: calc(56 * var(--u) + 4px); padding: 0 calc(10 * var(--u)) 0 calc(18 * var(--u)); border-radius: calc(14 * var(--u)); background: var(--a-surface); border: 1px solid var(--a-accent); box-shadow: 0 0 0 3px var(--a-tint-blue); }
.field.bad { border-color: var(--a-red); box-shadow: 0 0 0 3px var(--a-tint-red); }
.field input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--a-ink); font: 500 calc(24 * var(--u) + 1px) var(--a-font); letter-spacing: .02em; }
.note { margin: 0; min-height: 1.3em; color: var(--a-ink-3); font-size: calc(16 * var(--u) + 1px); }
.keys { margin: auto calc(-36 * var(--u)) 0 calc(-32 * var(--u)); }

.split { display: flex; justify-content: space-between; gap: calc(24 * var(--u)); }
.split .side { flex: 1; gap: calc(14 * var(--u)); padding-top: calc(4 * var(--u)); max-width: calc(450 * var(--u)); }
.btns { display: flex; flex-wrap: wrap; gap: calc(12 * var(--u)); }
.finish { display: flex; align-items: center; gap: calc(22 * var(--u)); margin-top: calc(4 * var(--u)); }
.bring-link { white-space: normal; max-width: calc(170 * var(--u)); line-height: 1.25; text-align: left; font-size: calc(17 * var(--u)); }
.btns .a-btn, .done .finish > .a-btn { font-size: calc(18 * var(--u) + 1px); padding: calc(12 * var(--u) + 4px) calc(18 * var(--u)); border-radius: 999px; white-space: nowrap; }
.qcard { flex: none; align-self: start; display: grid; justify-items: center; gap: calc(10 * var(--u)); padding: calc(16 * var(--u)) calc(18 * var(--u)) calc(14 * var(--u)); }
.qcard .qr { width: calc(224 * var(--u)); }
.caption { color: var(--a-ink-3); font-size: calc(15 * var(--u) + 1px); }

.naming { display: grid; gap: calc(16 * var(--u)); align-content: start; justify-items: start; }
.names { width: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: calc(12 * var(--u)); }
.names .a-btn { min-height: calc(60 * var(--u)); padding: 0 calc(12 * var(--u)); border-radius: 999px; font-size: calc(21 * var(--u) + 1px); display: inline-flex; align-items: center; justify-content: center; gap: calc(8 * var(--u)); }
.mini { width: calc(18 * var(--u) + 2px); height: calc(18 * var(--u) + 2px); }

.done .check { width: calc(76 * var(--u)); height: calc(76 * var(--u)); }
.ask { display: grid; gap: calc(8 * var(--u)); font-size: calc(19 * var(--u) + 1px); font-weight: 650; }
.pframe { flex: none; align-self: start; margin-top: calc(-6 * var(--u)); position: relative; border: 3px solid color-mix(in srgb, var(--a-ink) 30%, transparent); border-radius: calc(36 * var(--u)); padding: calc(30 * var(--u)) calc(20 * var(--u)) calc(18 * var(--u)); display: grid; gap: calc(12 * var(--u)); justify-items: center; text-align: center; width: calc(222 * var(--u)); }
.pframe::before { content: ''; position: absolute; top: calc(11 * var(--u)); left: 50%; width: calc(58 * var(--u)); height: 6px; margin-left: calc(-29 * var(--u)); border-radius: 3px; background: color-mix(in srgb, var(--a-ink) 30%, transparent); }
.pframe b { font-size: calc(17 * var(--u) + 1px); line-height: 1.2; }
.pframe .qr { width: calc(176 * var(--u)); }
.getting { width: calc(176 * var(--u)); height: calc(176 * var(--u)); display: grid; place-content: center; justify-items: center; gap: calc(12 * var(--u)); color: var(--a-ink-2); font-size: calc(16 * var(--u) + 1px); }
.ring { width: calc(36 * var(--u)); height: calc(36 * var(--u)); border-radius: 50%; border: 4px solid var(--a-track); border-top-color: var(--a-accent); display: block; }

@media (prefers-reduced-motion: no-preference) {
  .spin { animation: spin 1.6s linear infinite; transform-origin: 50% 50%; }
  @keyframes spin { to { transform: rotate(360deg); } }
}
</style>
