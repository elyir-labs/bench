<template>
  <!-- Now the printer itself (design/printer-setup/, A, agreed 5 October 2026; docs/bring-it-over.md): a fresh card
       has no printer.cfg, so instead of Problem, the ways to a config. Bring it over is built (a-bring, a-bring-what,
       then a-done without the check list); Write my own opens Mainsail; a printer it knows comes later.
       Shown instead of the app (App.vue) while bring.ts shown() says so; the panel first, the phone too. -->
  <main class="bring" :class="[phone ? 'phone' : 'wide', 'at-' + screen]">
    <header class="top">
      <span class="who"><span class="mark" aria-hidden="true" v-html="MARK" /><b>{{ header.who }}</b></span>
      <ol class="steps" aria-label="Steps">
        <li v-for="(t, i) in header.steps" :key="t" :class="{ on: i === step, done: i < step }" :aria-current="i === step ? 'step' : undefined">
          <span v-if="i < step" class="tick" aria-hidden="true" v-html="CHECK" /><i v-else>{{ i + 1 }}</i>{{ t }}
        </li>
      </ol>
    </header>

    <!-- a-start: three ways to a config, under what it found plugged in -->
    <section v-if="screen === 'start'" class="start">
      <h1 class="a-display">{{ START_TITLE }}</h1>
      <p class="sub">{{ startSub(info.found) }}</p>
      <div v-if="info.found?.length" class="found"><span v-for="f in info.found" :key="f">{{ f }}</span></div>
      <div class="ways">
        <component
          :is="w.later ? 'div' : 'button'" v-for="w in wayList" :key="w.id" class="way"
          :class="{ rec: w.id === 'bring', later: w.later, own: w.id === 'own' }" :aria-disabled="w.later ? 'true' : undefined"
          @click="pickWay(w.id)"
        >
          <span v-if="w.pill" class="pill" :class="{ blue: !w.later }">{{ w.pill }}</span>
          <b>{{ w.title }}</b>
          <p>{{ w.line }}</p>
        </component>
      </div>
      <!-- design/role/, B: a board found, so a printer; the box is still a line away -->
      <p v-if="error" class="foot">{{ error }}</p>
      <p v-else-if="canBox" class="foot">{{ BOX_LINK.before }} <button class="link" @click="boxAsk = true">{{ BOX_LINK.link }}</button>{{ BOX_LINK.after }}</p>
      <p v-else class="foot">{{ START_FOOT }}</p>
    </section>

    <!-- design/role/, B: nothing plugged in, so the Bench Box leads -->
    <section v-else-if="screen === 'none'" class="start none">
      <h1 class="a-display">{{ NONE_TITLE }}</h1>
      <p class="sub">{{ NONE_SUB }}</p>
      <div class="ways two">
        <button class="way rec" :disabled="busy" @click="makeBox">
          <span class="pill blue">{{ BOX_WAY.pill }}</span>
          <span class="art" aria-hidden="true" v-html="BOX_ART" />
          <b>{{ BOX_WAY.title }}</b>
          <p>{{ BOX_WAY.line }}</p>
        </button>
        <button class="way" :disabled="busy" @click="itsAPrinter">
          <span class="art" aria-hidden="true" v-html="PRINTER_ART" />
          <b>{{ PRINTER_WAY.title }}</b>
          <p>{{ PRINTER_WAY.line }}</p>
        </button>
      </div>
      <p class="foot">{{ error ?? NONE_FOOT }}</p>
    </section>

    <!-- becoming a Bench Box: elyir-bench role controller's steps; Moonraker goes last, then the Bench app has the screen -->
    <section v-else-if="screen === 'box'" class="centered becoming">
      <template v-if="info.role?.state === 'failed'">
        <svg class="glyph" viewBox="0 0 126 126" aria-hidden="true"><circle cx="63" cy="63" r="56" fill="var(--a-tint-red)" stroke="var(--a-red)" stroke-width="13"/><path d="M63 36v34M63 88v.5" fill="none" stroke="var(--a-red)" stroke-width="12" stroke-linecap="round"/></svg>
        <p class="big">{{ boxEnd.title }}</p>
        <p class="sub small">{{ boxEnd.line }}</p>
        <div class="btns"><button class="a-btn accent" :disabled="busy" @click="boxBack">Back</button></div>
      </template>
      <template v-else>
        <p class="big">{{ BOX_TITLE }}</p>
        <p class="sub small">{{ store.connected ? BOX_SUB : boxGone(info.role?.url ?? null) }}</p>
        <ol class="box-steps">
          <li v-for="b in boxStepList" :key="b.label" :class="b.status">
            <span class="mk" aria-hidden="true"><span v-if="b.status === 'ok'" v-html="CHECK" /></span>{{ b.label }}
          </li>
        </ol>
      </template>
    </section>

    <!-- a-bring: what it can see, newest first -->
    <section v-else-if="screen === 'sources'" class="split sources">
      <div class="side">
        <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
        <h1 class="a-display">{{ SOURCES_TITLE }}</h1>
        <p class="sub">{{ SOURCES_SUB }}</p>
        <button class="link" :disabled="info.state === 'scanning' || busy" @click="scan">{{ info.state === 'scanning' ? LOOKING : LOOK_AGAIN }}</button>
      </div>
      <div class="col">
        <div class="card rows">
          <button v-for="r in rows" :key="r.id" class="src" :disabled="busy || (r.press === 'file' && !!sending)" @click="pickRow(r)">
            <span class="ic" :class="{ lit: r.lit }" v-html="ROW_ICONS[r.icon]" />
            <span class="words"><b>{{ r.title }}</b><small>{{ r.press === 'file' && sending ? SENDING(sending) : r.line }}</small></span>
            <span class="chev" v-html="CHEV" />
          </button>
        </div>
        <p class="note" :class="{ err: !!error }">{{ error ?? SOURCES_NOTE }}</p>
      </div>
      <input ref="picker" type="file" class="picker" :accept="BACKUP_ACCEPT" @change="sendFile" />
    </section>

    <!-- design/cloud/ C-panel-restore: a Bench Cloud backup needs the house's owner, on their phone or by the email's code -->
    <section v-else-if="screen === 'cloud'" class="split cloud">
      <div class="side">
        <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
        <h1 class="a-display">{{ CLOUD_TITLE }}</h1>
        <p v-if="cloudLine" class="sub">{{ cloudLine }}</p>
        <p class="note">{{ CLOUD_NOTE }}</p>
      </div>
      <div class="col">
        <div v-if="cloudOver" class="card owner">
          <b class="owner-title">{{ cloudOver.title }}</b>
          <p class="sub small">{{ cloudOver.line }}</p>
          <button class="a-btn accent" :disabled="busy" @click="askOwner">{{ CLOUD_ASK_AGAIN }}</button>
        </div>
        <div v-else-if="cloud?.state === 'allowed'" class="card owner centered-row">
          <span class="spinner" aria-hidden="true" /><b>{{ CLOUD_GETTING }}</b>
        </div>
        <div v-else-if="cloud?.emailed && !phone" class="card owner typing-code">
          <b class="owner-title">{{ CLOUD_TYPE }}</b>
          <small class="owner-line">{{ cloudTypeLine(cloud) }}</small>
          <div class="digits" aria-live="polite"><span v-for="i in 6" :key="i" :class="{ on: i === code.length + 1 }">{{ code[i - 1] ?? '' }}</span></div>
          <div class="keypad">
            <button v-for="k in KEYS" :key="k" class="key" :class="{ blank: !k }" :disabled="!k || busy" @click="key(k)">{{ k }}</button>
          </div>
          <button class="link" :disabled="busy" @click="sendCode">{{ CLOUD_SEND_AGAIN }}</button>
        </div>
        <div v-else class="card owner">
          <b class="owner-title">{{ CLOUD_NEEDS }}</b>
          <div class="way-row">
            <span class="ic lit" v-html="PHONE" />
            <span class="words"><b>{{ cloudAllowTitle(cloud ?? {}) }}</b>
              <small v-if="cloud">{{ CLOUD_ASKED }} <span class="dots" aria-hidden="true"><i /><i /><i /></span></small>
              <small v-else>{{ LOOKING }}</small></span>
          </div>
          <div class="way-row">
            <span class="ic lit" v-html="MAIL" />
            <span class="words"><b>{{ CLOUD_EMAIL_TITLE }}</b><small>{{ cloudEmailLine(cloud ?? {}) }}</small></span>
          </div>
          <template v-if="cloud?.emailed">
            <form class="code-form" @submit.prevent="bringBack">
              <label class="field"><input v-model="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="7"
                                          :aria-label="CLOUD_EMAIL_TITLE" placeholder="000000" /></label>
              <button type="submit" class="a-btn accent" :disabled="busy || !isCode(code)">{{ CLOUD_CODE_GO }}</button>
            </form>
            <button class="link" :disabled="busy" @click="sendCode">{{ CLOUD_SEND_AGAIN }}</button>
          </template>
          <button v-else class="a-btn ghost" :disabled="busy || !cloud" @click="sendCode">{{ CLOUD_SEND }}</button>
        </div>
        <p v-if="error" class="note err">{{ error }}</p>
      </div>
    </section>

    <!-- another printer's address: the panel's own keyboard, the phone's -->
    <section v-else-if="screen === 'address'" class="typing">
      <div class="head">
        <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
        <b class="title">{{ ADDRESS_TITLE }}</b>
      </div>
      <form class="field-row" @submit.prevent="lookAt">
        <label class="field" :class="{ bad: !!typedProblem }">
          <input ref="addressIn" v-model="typed" type="text" :inputmode="phone ? 'url' : 'none'" autocomplete="off" autocapitalize="none"
                 spellcheck="false" :aria-label="ADDRESS_TITLE" placeholder="voron.local" />
        </label>
        <button v-if="phone" type="submit" class="a-btn accent" :disabled="!canLook">{{ ADDRESS_GO }}</button>
      </form>
      <p class="note" :class="{ err: !!(typedProblem || error) }">{{ typedProblem ?? error ?? ADDRESS_NOTE }}</p>
      <PanelKeyboard v-if="!phone" v-model="typed" :action="ADDRESS_GO" :can-go="canLook" class="keys" @go="lookAt" />
    </section>

    <!-- a backup file, on the panel: nothing to pick here, so from the phone -->
    <section v-else-if="screen === 'file'" class="split">
      <div class="side">
        <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
        <h1 class="a-display">{{ FILE_TITLE }}</h1>
      </div>
      <div class="col file-lines">
        <p v-for="l in fileLines(name)" :key="l" class="sub">{{ l }}</p>
      </div>
    </section>

    <!-- reading the source picked -->
    <section v-else-if="screen === 'planning'" class="centered">
      <span class="spinner" aria-hidden="true" />
      <p class="big">{{ PLANNING }}</p>
    </section>

    <!-- a-bring-what: what comes over, and whether the boards match -->
    <section v-else-if="screen === 'plan' && plan" class="split what">
      <div class="side">
        <div class="titled">
          <button class="a-btn ghost round" aria-label="Back" @click="back"><span v-html="BACK" /></button>
          <h1 class="a-display">{{ planTitle(source) }}</h1>
        </div>
        <span class="lbl">{{ COMES_OVER }}</span>
        <div v-for="l in comesOver(plan)" :key="l" class="tickline"><span class="tick" v-html="CHECK" />{{ l }}</div>
        <button v-if="offer" class="tickline offer" :class="{ on: withFiles }" role="checkbox" :aria-checked="withFiles" @click="withFiles = !withFiles">
          <span class="box"><span v-if="withFiles" v-html="CHECK" /></span>
          <span>{{ offer.label }}<small>{{ offer.line }}</small></span>
        </button>
      </div>
      <div class="col">
        <div v-if="plan.boards.length" class="card boards">
          <b class="boards-title">{{ BOARDS_TITLE }}</b>
          <div v-for="b in boardLines" :key="b.name" class="board" :class="b.tone">
            <span class="mk" v-html="b.tone === 'green' ? CHECK : b.tone === 'blue' ? SWAP : WARN" />
            <span><b>{{ b.name }}</b><small>{{ b.line }}</small></span>
          </div>
        </div>
        <ul v-if="notes.length" class="notes">
          <li v-for="n in notes" :key="n">{{ n }}</li>
        </ul>
        <div class="go">
          <button class="a-btn accent big-btn" :disabled="busy" @click="apply">{{ busy ? '…' : APPLY }}</button>
          <p class="note centered-note" :class="{ err: !!error }">{{ error ?? APPLY_NOTE }}</p>
        </div>
      </div>
    </section>

    <!-- bringing it over: the step, and how far -->
    <section v-else-if="screen === 'bringing'" class="centered">
      <svg class="eye" viewBox="0 0 126 126" aria-hidden="true">
        <circle cx="63" cy="63" r="56" fill="none" stroke="var(--a-track)" stroke-width="13" />
        <circle cx="63" cy="63" r="56" fill="none" stroke="var(--a-accent)" stroke-width="13" stroke-linecap="round"
                :stroke-dasharray="`${Math.max(0.04, prog.frac) * 351.9} 352`" transform="rotate(-90 63 63)" class="arc" />
        <circle cx="63" cy="63" r="22" fill="var(--a-accent)" />
      </svg>
      <p class="kicker">{{ BRINGING_TITLE }}</p>
      <p class="big">{{ prog.step }}</p>
      <p class="sub small">{{ [prog.count, bringingNote(source?.kind)].filter(Boolean).join(' · ') }}</p>
    </section>

    <!-- a-done, without the check list (Check the printer isn't built): what came over instead -->
    <section v-else-if="screen === 'done' || screen === 'stopped' || screen === 'failed'" class="split ended">
      <div class="side">
        <svg v-if="screen === 'done'" class="glyph" viewBox="0 0 126 126" aria-hidden="true"><circle cx="63" cy="63" r="56" fill="var(--a-tint-green)" stroke="var(--a-green)" stroke-width="13"/><path d="M40 64l15 15 31-32" fill="none" stroke="var(--a-green)" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <svg v-else class="glyph" viewBox="0 0 126 126" aria-hidden="true"><circle cx="63" cy="63" r="56" fill="var(--a-tint-red)" stroke="var(--a-red)" stroke-width="13"/><path d="M63 36v34M63 88v.5" fill="none" stroke="var(--a-red)" stroke-width="12" stroke-linecap="round"/></svg>
        <h1 class="a-display">{{ ended.title }}</h1>
        <p class="sub">{{ ended.line }}</p>
        <div class="btns">
          <button v-if="screen === 'done'" class="a-btn accent" @click="finish">{{ DONE }}</button>
          <button v-else-if="screen === 'failed'" class="a-btn accent" @click="toSources">Back</button>
          <template v-else>
            <button v-if="canDoor" class="a-btn accent" @click="doorOpen = true">{{ OPEN_DOOR }}</button>
            <button class="a-btn ghost" @click="finish">{{ DONE }}</button>
          </template>
        </div>
      </div>
      <div v-if="screen !== 'failed' && plan" class="card came">
        <span class="lbl">{{ ended.came ?? 'Came over' }}</span>
        <div v-for="l in comesOver(plan)" :key="l" class="tickline"><span class="tick" v-html="CHECK" />{{ l }}</div>
      </div>
    </section>

    <AdvancedDoor v-if="doorOpen" :url="store.advancedUrl" @close="doorOpen = false" />
    <SliceSheet :open="boxAsk" :title="BOX_ASK.title" :sub="BOX_ASK.line" @close="boxAsk = false">
      <div class="ask-btns">
        <button class="a-btn ghost" :disabled="busy" @click="boxAsk = false">{{ BOX_ASK.keep }}</button>
        <button class="a-btn accent" :disabled="busy" @click="makeBox">{{ busy ? '…' : BOX_ASK.go }}</button>
      </div>
    </SliceSheet>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { authHeaders, embedded } from '@/auth'
import { door } from '@/door'
import { layout } from '@/shell/useLayout'
import AdvancedDoor from '@/shell/AdvancedDoor.vue'
import PanelKeyboard from '@/setup/PanelKeyboard.vue'
import { bring, bringAct, finishBring, refreshBring, seen } from '@/intent/useBring'
import {
  CLOUD_ASK_AGAIN, CLOUD_ASKED, CLOUD_CODE_GO, CLOUD_EMAIL_TITLE, CLOUD_GETTING, CLOUD_NEEDS, CLOUD_NOTE, CLOUD_SEND, CLOUD_SEND_AGAIN,
  CLOUD_TITLE, CLOUD_TYPE, backupWords, cloudAllowTitle, cloudEmailLine, cloudEnd, cloudTypeLine, isCode,
  ADDRESS_GO, ADDRESS_NOTE, ADDRESS_TITLE, APPLY, APPLY_NOTE, BACKUP_ACCEPT, BOARDS_TITLE, BRINGING_TITLE, COMES_OVER, DONE, EMPTY,
  FILE_TITLE, LOOKING, LOOK_AGAIN, NOT_A_BACKUP, OPEN_DOOR, PLANNING, SENDING, SOURCES_NOTE, SOURCES_SUB, SOURCES_TITLE, START_FOOT,
  START_TITLE, addressProblem, BOX_ASK, BOX_LINK, BOX_SUB, BOX_TITLE, BOX_WAY, NONE_FOOT, NONE_SUB, NONE_TITLE, PRINTER_WAY,
  boxFailed, boxGone, boxSteps, headerFor, backupUpload, boardLine, planNotes, bringingNote, comesOver, failedWords, fileLines, gcodesOffer, isBackup,
  planTitle, progressWords, resultWords, screenFor, sourceRows, startSub, stepOf, ways, type SourceRow,
} from '@/intent/bring'
import { BACK, BOX_ART, CHECK, CHEV, MAIL, MARK, PHONE, PRINTER_ART, ROW_ICONS, SWAP, WARN } from './icons'
import SliceSheet from '@/components/slice/SliceSheet.vue'

const store = useIntentStore()
const phone = computed(() => layout.value === 'compact')
const info = computed(() => bring.info ?? EMPTY)
const screen = computed(() => screenFor(info.value, bring.here, seen.value))
const step = computed(() => stepOf(screen.value))
const header = computed(() => headerFor(screen.value))
const name = computed(() => store.intent?.printer?.name ?? 'the printer')
const busy = ref(false)
const error = ref<string | null>(null)
watch(screen, () => { error.value = null })

// the clock for "changed 2 hours ago", a minute at a time
const now = ref(Date.now())
onMounted(() => window.setInterval(() => (now.value = Date.now()), 60_000))

async function act(action: string, args: Record<string, unknown> = {}): Promise<boolean> {
  busy.value = true
  error.value = await bringAct(store, action, args)
  busy.value = false
  return !error.value
}

// ── a-start ─────────────────────────────────────────────────────────────────
const wayList = computed(() => ways(info.value.sources))
// Mainsail is on the home network: not from away, and not inside the Printers app (as AppShell's door)
const canDoor = computed(() => !door.away && !embedded)
const doorOpen = ref(false)
function pickWay(id: string): void {
  if (id === 'bring') toSources()
  else if (id === 'own') {
    if (canDoor.value) doorOpen.value = true
    else error.value = "Mainsail opens on the printer's own screen, or on a phone at home."
  }
}

// ── printer or Bench Box (design/role/, B) ───────────────────────────────────
// Only when the printer's side can (it sends `role`, null or not)
const canBox = computed(() => info.value.role !== undefined)
const boxAsk = ref(false)
const boxStepList = computed(() => boxSteps(info.value.role?.progress ?? null))
const boxEnd = computed(() => boxFailed(info.value.role?.why ?? null))
async function makeBox(): Promise<void> {
  if (await act('role_box')) { boxAsk.value = false; refreshBring(store) }
}
function itsAPrinter(): void { bring.here = { at: 'printer' } }
async function boxBack(): Promise<void> { if (await act('role_back')) refreshBring(store) }

// ── a-bring ─────────────────────────────────────────────────────────────────
const rows = computed(() => sourceRows(info.value.sources, now.value))
function toSources(): void {
  bring.here = { at: 'sources' }
  scan()
}
async function scan(): Promise<void> { await act('bring_scan') }

function back(): void {
  const h = bring.here
  if (h.at === 'sources') {
    // opened from the Wi-Fi's link on a printer that has a config: back is out
    if (store.intent?.state !== 'setup') { bring.requested = false }
    bring.here = { at: 'start' }
  } else bring.here = { at: 'sources' }
}

const picker = ref<HTMLInputElement | null>(null)
async function pickRow(r: SourceRow): Promise<void> {
  if (r.press === 'address') { typed.value = ''; bring.here = { at: 'address' }; return }
  if (r.press === 'cloud') { bring.here = { at: 'cloud', id: r.id }; code.value = ''; await act('bring_cloud_ask', { id: r.id }); return }
  if (r.press === 'file') {
    if (layout.value !== 'panel') picker.value?.click()   // the panel has nothing to pick from
    else bring.here = { at: 'file' }
    return
  }
  bring.here = { at: 'plan', id: r.id }
  withFiles.value = false
  await act('bring_plan', { id: r.id })
}

// ── a Bench Cloud backup (design/cloud/ C-panel-restore) ─────────────────────
const cloud = computed(() => info.value.cloud ?? null)
const cloudSource = computed(() => info.value.sources.find((s) => s.id === (bring.here.at === 'cloud' ? bring.here.id : '')))
const cloudLine = computed(() => {
  const s = cloudSource.value
  return s ? [s.name, s.when ? backupWords(s.when, now.value) : ''].filter(Boolean).join(' · ') : ''
})
const cloudOver = computed(() => (cloud.value ? cloudEnd(cloud.value.state) : null))
const code = ref('')
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫']
async function askOwner(): Promise<void> {
  if (bring.here.at === 'cloud') { code.value = ''; await act('bring_cloud_ask', { id: bring.here.id }) }
}
async function sendCode(): Promise<void> { await act('bring_cloud_email') }
async function bringBack(): Promise<void> {
  if (isCode(code.value) && !(await act('bring_cloud_code', { code: code.value.replace(/\s/g, '') }))) code.value = ''
}
function key(k: string): void {
  if (k === '⌫') code.value = code.value.slice(0, -1)
  else if (code.value.length < 6) code.value += k
  if (code.value.length === 6) bringBack()
}
// allowed: the backup is a backup file here now; what comes over from it, like any other
watch(() => cloud.value?.state === 'allowed' ? cloud.value.file : null, async (file) => {
  if (file && bring.here.at === 'cloud') {
    bring.here = { at: 'plan', id: file }
    withFiles.value = false
    await act('bring_plan', { id: file })
  }
})

// a backup from the phone: to Moonraker's config root, elyir-bench-bring/<name>, then a scan lists it
const sending = ref<string | null>(null)
const sent = ref<string | null>(null)
async function sendFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  if (!isBackup(f.name)) { error.value = NOT_A_BACKUP; return }
  const ep = store.endpoint
  if (!ep) return
  const up = backupUpload(f.name)
  const form = new FormData()
  form.append('root', up.root)
  form.append('path', up.path)
  form.append('file', f, up.name)
  sending.value = up.name
  error.value = null
  try {
    const r = await fetch(`${ep.http}/server/files/upload`, { method: 'POST', body: form, headers: authHeaders() })
    if (!r.ok) throw new Error(String(r.status))
    sent.value = up.name
    await act('bring_scan')
  } catch {
    error.value = `${up.name} didn't reach the printer. Try again.`
  }
  sending.value = null
}
// once the scan lists the file sent, it opens: what comes over from it
watch(() => info.value, (i) => {
  if (!sent.value || i.state !== 'idle') return
  const s = i.sources.find((x) => x.kind === 'file' && x.name === sent.value)
  if (!s) return
  sent.value = null
  pickRow({ id: s.id, icon: 'file', title: s.name, line: '', press: 'plan', lit: false })
})

// ── another printer's address ─────────────────────────────────────────────────
const typed = ref('')
const addressIn = ref<HTMLInputElement | null>(null)
const typedProblem = computed(() => addressProblem(typed.value))
const canLook = computed(() => !!typed.value.trim() && !typedProblem.value && !busy.value)
async function lookAt(): Promise<void> {
  if (!canLook.value) return
  bring.here = { at: 'plan' }
  withFiles.value = false
  await act('bring_address', { address: typed.value.trim() })
}
watch(screen, async (s) => { if (s === 'address') { await nextTick(); addressIn.value?.focus() } })

// ── a-bring-what ────────────────────────────────────────────────────────────
const plan = computed(() => info.value.plan)
const source = computed(() => info.value.sources.find((s) => s.id === plan.value?.id))
const offer = computed(() => (plan.value ? gcodesOffer(plan.value) : null))
const withFiles = ref(false)   // the files are offered, never ticked to begin with
const boardLines = computed(() => plan.value?.boards.map(boardLine) ?? [])
const notes = computed(() => planNotes(plan.value))
async function apply(): Promise<void> {
  const p = plan.value
  if (!p) return
  bring.here = { at: 'plan', id: p.id, applied: true }
  bring.inFlow = true
  if (!(await act('bring_apply', { id: p.id, gcodes: withFiles.value }))) bring.inFlow = false
}

// ── bringing, and how it ended ──────────────────────────────────────────────
const prog = computed(() => progressWords(info.value.progress))
const ended = computed(() => {
  if (screen.value === 'failed') {
    return { ...failedWords(info.value.why, bring.here.at === 'plan' && !!bring.here.applied), came: null }
  }
  const r = info.value.result ?? { klipper: 'ready' as const, message: '' }
  return resultWords(r, name.value)
})
function finish(): void { finishBring() }

onMounted(() => {
  // the boot screen's first frame (index.html) is the app's to take down: here, that's this screen
  delete document.documentElement.dataset.boot
  document.getElementById('boot-frame')?.remove()
  refreshBring(store)
})
</script>

<style scoped>
.bring {
  --a-track: color-mix(in srgb, var(--a-ink) 10%, transparent);
  position: fixed; inset: 0; display: flex; flex-direction: column; overflow: hidden;
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font); -webkit-font-smoothing: antialiased;
}
.top { flex: none; height: calc(52 * var(--u)); padding: calc(18 * var(--u)) calc(36 * var(--u)) 0 calc(32 * var(--u)); display: flex; align-items: center; justify-content: space-between; color: var(--a-ink-3); }
.who { display: inline-flex; align-items: center; gap: calc(10 * var(--u)); }
.mark { display: block; width: calc(26 * var(--u)); height: calc(26 * var(--u)); color: var(--a-accent); }
.who b { font-size: calc(15 * var(--u) + 1px); letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-2); font-weight: 650; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; align-items: center; gap: calc(26 * var(--u)); font-size: calc(15 * var(--u) + 1px); font-weight: 650; }
.steps li { display: inline-flex; align-items: center; gap: calc(7 * var(--u)); position: relative; }
.steps li + li::before { content: ''; position: absolute; left: calc(-21 * var(--u)); width: calc(16 * var(--u)); height: 1.5px; background: var(--a-ink-3); opacity: .5; }
.steps i { font-style: normal; width: calc(22 * var(--u)); height: calc(22 * var(--u)); border-radius: 50%; border: 1.5px solid currentColor; display: grid; place-items: center; font-size: calc(12 * var(--u)); }
.steps .tick { display: block; width: calc(22 * var(--u)); height: calc(22 * var(--u)); }
.steps .on { color: var(--a-ink); }
.steps .on i { background: var(--a-accent); border-color: transparent; color: var(--a-accent-ink); }
.steps .done { color: var(--a-green-text); }
:deep(svg) { width: 100%; height: 100%; display: block; }

section { flex: 1; min-height: 0; padding: calc(14 * var(--u)) calc(36 * var(--u)) calc(24 * var(--u)) calc(40 * var(--u)); }
h1 { margin: 0; font-size: calc(38 * var(--u) + 2px); }
.sub { margin: 0; color: var(--a-ink-2); font-size: calc(17 * var(--u) + 1px); line-height: 1.4; }
.sub.small { color: var(--a-ink-3); }
.note { margin: 0; color: var(--a-ink-3); font-size: calc(15 * var(--u) + 1px); line-height: 1.4; }
.err { color: var(--a-red-text); }
.card { background: var(--a-surface); border-radius: calc(22 * var(--u)); box-shadow: var(--a-card-shadow); }
.lbl { font-size: calc(13 * var(--u) + 1px); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-3); }
.pill { justify-self: start; display: inline-flex; align-items: center; font-weight: 650; border-radius: 999px; padding: calc(3 * var(--u)) calc(10 * var(--u)); font-size: calc(13 * var(--u) + 1px); background: var(--a-surface-2); color: var(--a-ink-3); white-space: nowrap; }
.pill.blue { background: var(--a-tint-blue); color: var(--a-accent-text); }
.link { appearance: none; border: 0; background: none; padding: calc(6 * var(--u)) 0; font: 650 calc(17 * var(--u) + 1px) var(--a-font); color: var(--a-accent-text); cursor: pointer; justify-self: start; }
.link[disabled] { opacity: .55; cursor: default; }
.round { flex: none; width: calc(46 * var(--u)); height: calc(46 * var(--u)); min-height: 0; padding: 0; display: grid; place-items: center; border-radius: 50%; }
.round span { width: calc(22 * var(--u)); height: calc(22 * var(--u)); display: block; }

/* a-start */
.start { display: flex; flex-direction: column; gap: calc(10 * var(--u)); padding-top: calc(12 * var(--u)); }
.start h1 { font-size: calc(34 * var(--u) + 2px); }
.found { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u)); margin-top: calc(2 * var(--u)); }
.found span { font-size: calc(14 * var(--u) + 1px); font-weight: 600; padding: calc(5 * var(--u)) calc(12 * var(--u)); border-radius: 999px; background: var(--a-surface-2); color: var(--a-ink-2); }
.ways { flex: 1; min-height: 0; display: grid; grid-template-columns: 1.15fr 1fr 1fr; gap: calc(14 * var(--u)); margin-top: calc(6 * var(--u)); }
.way { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; background: var(--a-surface); border-radius: calc(20 * var(--u)); padding: calc(20 * var(--u)); display: grid; gap: calc(10 * var(--u)); align-content: start; border: 1.5px solid transparent; }
.way.rec { border-color: var(--a-accent); }
.way b { font-size: calc(22 * var(--u) + 1px); letter-spacing: -.01em; font-weight: 700; }
.way p { margin: 0; font-size: calc(16 * var(--u) + 1px); color: var(--a-ink-2); line-height: 1.35; }
.way.own b { color: var(--a-ink-2); }
.way.later { cursor: default; opacity: .5; }
.foot { margin: 0; color: var(--a-ink-3); font-size: calc(15 * var(--u) + 1px); }
.foot .link { appearance: none; background: none; border: 0; padding: 0; font: inherit; font-weight: 650; color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
/* design/role/ */
.ways.two { grid-template-columns: 1.25fr 1fr; }
.way .art { display: block; width: calc(44 * var(--u) + 4px); height: calc(44 * var(--u) + 4px); color: var(--a-ink-2); }
.way.rec .art { color: var(--a-accent); }
.becoming .box-steps { list-style: none; margin: calc(16 * var(--u)) 0 0; padding: 0; display: grid; gap: calc(12 * var(--u)); text-align: left; }
.box-steps li { display: flex; align-items: center; gap: calc(14 * var(--u)); font-size: calc(18 * var(--u) + 1px); }
.box-steps .mk { width: calc(26 * var(--u)); height: calc(26 * var(--u)); border-radius: 50%; display: grid; place-items: center; flex: none; }
.box-steps .ok .mk { background: var(--a-green); color: #fff; padding: 4px; }
.box-steps .now .mk { border: 3px solid var(--a-accent); border-top-color: transparent; animation: spin 1s linear infinite; }
.box-steps .todo { color: var(--a-ink-3); }
.box-steps .todo .mk { border: 2px solid var(--a-line); }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .box-steps .now .mk { animation: none; } }
.ask-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ask-btns .a-btn { height: 54px; font-size: 17px; border-radius: 18px; }

/* a-bring and a-bring-what: words on the left, the card on the right */
.split { display: flex; gap: calc(22 * var(--u)); }
.side { flex: none; width: calc(250 * var(--u)); display: grid; gap: calc(14 * var(--u)); align-content: start; justify-items: start; padding-top: calc(4 * var(--u)); }
.col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: calc(16 * var(--u)); padding-top: calc(10 * var(--u)); }
.rows { overflow-y: auto; flex: 0 1 auto; min-height: 0; }
.src { appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; width: 100%; min-height: calc(76 * var(--u)); display: grid; grid-template-columns: calc(44 * var(--u)) 1fr calc(20 * var(--u)); gap: calc(14 * var(--u)); align-items: center; padding: calc(8 * var(--u)) calc(20 * var(--u)); color: var(--a-ink); font: inherit; text-align: left; cursor: pointer; }
.src:first-child { border-top: 0; }
.src[disabled] { cursor: default; }
.src .ic { width: calc(44 * var(--u)); height: calc(44 * var(--u)); border-radius: calc(12 * var(--u)); background: var(--a-surface-2); display: grid; place-items: center; color: var(--a-ink-2); padding: calc(10 * var(--u)); }
.src .ic.lit { background: var(--a-tint-blue); color: var(--a-accent-text); }
.words { display: grid; min-width: 0; }
.words b { font-size: calc(19 * var(--u) + 1px); font-weight: 650; overflow-wrap: anywhere; }
.words small { font-size: calc(15 * var(--u) + 1px); color: var(--a-ink-3); overflow-wrap: anywhere; }
.chev { width: calc(20 * var(--u)); height: calc(20 * var(--u)); opacity: .4; }
.picker { display: none; }
.file-lines { gap: calc(14 * var(--u)); padding-top: calc(70 * var(--u)); max-width: calc(440 * var(--u)); }

.what .side { width: calc(340 * var(--u)); gap: calc(12 * var(--u)); }
.titled { display: flex; align-items: center; gap: calc(12 * var(--u)); margin-left: calc(-4 * var(--u)); }
.titled h1 { font-size: calc(32 * var(--u) + 2px); }
.what .lbl { margin-top: calc(4 * var(--u)); }
.tickline { display: flex; gap: calc(10 * var(--u)); align-items: center; font-size: calc(17 * var(--u) + 1px); line-height: 1.3; }
.tickline .tick { flex: none; width: calc(22 * var(--u)); height: calc(22 * var(--u)); color: var(--a-green-text); }
.offer { appearance: none; border: 0; background: none; padding: 0; color: var(--a-ink-2); font: inherit; font-size: calc(17 * var(--u) + 1px); text-align: left; cursor: pointer; }
.offer.on { color: var(--a-ink); }
.offer small { display: block; font-size: calc(14 * var(--u) + 1px); color: var(--a-ink-3); }
.box { flex: none; width: calc(22 * var(--u)); height: calc(22 * var(--u)); border-radius: calc(6 * var(--u)); border: 2px solid var(--a-ink-3); display: grid; place-items: center; color: var(--a-accent-ink); padding: 1px; }
.offer.on .box { background: var(--a-accent); border-color: var(--a-accent); }
.what .col { padding-top: calc(6 * var(--u)); gap: calc(40 * var(--u)); }
.boards { padding: calc(18 * var(--u)) calc(20 * var(--u)); display: grid; gap: calc(10 * var(--u)); }
.boards-title { font-size: calc(19 * var(--u) + 1px); font-weight: 700; }
.board { display: grid; grid-template-columns: calc(24 * var(--u)) 1fr; gap: calc(10 * var(--u)); font-size: calc(16 * var(--u) + 1px); }
.board .mk { width: calc(22 * var(--u)); height: calc(22 * var(--u)); color: var(--a-green-text); }
.board.blue .mk { color: var(--a-accent-text); }
.board.amber .mk { color: var(--a-amber-text); }
.board b { font-weight: 650; }
.board small { display: block; color: var(--a-ink-3); font-size: calc(14 * var(--u) + 1px); }
.board.amber small { color: var(--a-amber-text); }
.go { display: grid; gap: calc(10 * var(--u)); }
.big-btn { height: calc(56 * var(--u)); border-radius: 999px; font-size: calc(19 * var(--u) + 1px); }
.centered-note { text-align: center; }

/* bringing */
.centered { display: grid; place-content: center; justify-items: center; gap: calc(8 * var(--u)); text-align: center; padding-bottom: calc(50 * var(--u)); }
.eye { width: calc(130 * var(--u)); height: calc(130 * var(--u)); margin-bottom: calc(14 * var(--u)); }
.arc { transition: stroke-dasharray .6s ease; }
.kicker { margin: 0; font-size: calc(15 * var(--u) + 1px); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-3); }
.big { margin: 0; color: var(--a-ink); font-size: calc(28 * var(--u) + 1px); font-weight: 700; letter-spacing: -.01em; }
.spinner { width: calc(48 * var(--u)); height: calc(48 * var(--u)); border-radius: 50%; border: 5px solid var(--a-track); border-top-color: var(--a-accent); margin-bottom: calc(10 * var(--u)); }

/* a-done */
.ended .side { width: auto; flex: 1; max-width: calc(410 * var(--u)); gap: calc(14 * var(--u)); padding-top: calc(6 * var(--u)); }
.glyph { width: calc(70 * var(--u)); height: calc(70 * var(--u)); }
.ended h1 { font-size: calc(36 * var(--u) + 2px); }
.btns { display: flex; flex-wrap: wrap; gap: calc(12 * var(--u)); margin-top: calc(6 * var(--u)); }
.btns .a-btn { height: calc(54 * var(--u)); padding: 0 calc(24 * var(--u)); border-radius: 999px; font-size: calc(18 * var(--u) + 1px); white-space: nowrap; }
.came { margin-left: auto; align-self: start; margin-top: calc(18 * var(--u)); width: calc(294 * var(--u)); padding: calc(18 * var(--u)) calc(20 * var(--u)); display: grid; gap: calc(12 * var(--u)); }
.came .tickline { font-size: calc(16 * var(--u) + 1px); }

/* another printer's address */
.typing { display: flex; flex-direction: column; gap: calc(10 * var(--u)); padding: calc(8 * var(--u)) calc(36 * var(--u)) 0 calc(32 * var(--u)); }
.head { display: flex; align-items: center; gap: calc(14 * var(--u)); }
.title { font-size: calc(24 * var(--u) + 1px); font-weight: 650; }
.field-row { display: flex; gap: calc(10 * var(--u)); }
.field { flex: 1; display: flex; align-items: center; height: calc(56 * var(--u) + 4px); padding: 0 calc(18 * var(--u)); border-radius: calc(14 * var(--u)); background: var(--a-surface); border: 1px solid var(--a-accent); box-shadow: 0 0 0 3px var(--a-tint-blue); }
.field.bad { border-color: var(--a-red); box-shadow: 0 0 0 3px var(--a-tint-red); }
.field input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--a-ink); font: 500 calc(24 * var(--u) + 1px) var(--a-font); }
.field input::placeholder { color: var(--a-ink-3); }
.typing .note { min-height: 1.3em; }
.keys { margin: auto calc(-36 * var(--u)) 0 calc(-32 * var(--u)); }

@media (prefers-reduced-motion: no-preference) {
  .spinner { animation: spin 1.1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
}

/* ── the phone: one column, scrolling, the same words ──────────────────────── */
.phone { --u: 1px; position: relative; inset: auto; min-height: 100dvh; overflow: visible; padding-bottom: env(safe-area-inset-bottom); }
.phone .top { height: auto; padding: calc(14px + env(safe-area-inset-top)) 18px 6px; }
.phone .who b { font-size: 13px; }
.phone .steps { gap: 28px; font-size: 14px; }
.phone .steps li + li::before { left: -22px; width: 16px; }
.phone section { flex: none; padding: 14px 20px 28px; }
.phone h1, .phone .start h1, .phone .ended h1, .phone .titled h1 { font-size: 30px; }
.phone .ways { grid-template-columns: 1fr; gap: 12px; }
.phone .way { padding: 18px; gap: 8px; }
.phone .way b { font-size: 21px; }
.phone .foot { margin-top: 4px; }
.phone .split { flex-direction: column; gap: 18px; }
.owner { padding: calc(18 * var(--u)) calc(20 * var(--u)); display: grid; gap: calc(12 * var(--u)); justify-items: stretch; }
.owner-title { font-size: calc(19 * var(--u) + 1px); }
.way-row { display: grid; grid-template-columns: calc(40 * var(--u)) 1fr; gap: calc(12 * var(--u)); align-items: center;
  padding: calc(10 * var(--u)) calc(12 * var(--u)); border: 1px solid var(--a-line); border-radius: calc(16 * var(--u)); }
.way-row .ic { width: calc(40 * var(--u)); height: calc(40 * var(--u)); border-radius: calc(12 * var(--u)); background: var(--a-tint-blue);
  color: var(--a-accent-text); display: grid; place-items: center; padding: calc(8 * var(--u)); }
.way-row .words { display: grid; gap: 2px; }
.way-row small { color: var(--a-ink-3); display: inline-flex; align-items: center; gap: 8px; }
.dots { display: inline-flex; gap: 6px; }
.dots i { width: 8px; height: 8px; border-radius: 50%; background: var(--a-accent); animation: dot 1.2s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay: .2s; } .dots i:nth-child(3) { animation-delay: .4s; }
@keyframes dot { 0%, 100% { opacity: .25 } 50% { opacity: 1 } }
.typing-code { gap: calc(10 * var(--u)); }
.owner-line { color: var(--a-ink-3); font-size: calc(15 * var(--u) + 1px); margin-top: calc(-6 * var(--u)); }
.code-form { display: grid; gap: 10px; }
.code-form .field input { letter-spacing: 0.2em; }
.digits { display: flex; gap: calc(8 * var(--u)); }
.digits span { width: calc(44 * var(--u)); height: calc(44 * var(--u)); border-radius: calc(12 * var(--u)); border: 1px solid var(--a-line);
  display: grid; place-items: center; font-size: calc(22 * var(--u)); font-weight: 700; }
.digits span.on { border: 2px solid var(--a-accent); }
.keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: calc(6 * var(--u)); }
.key { appearance: none; border: 0; height: calc(36 * var(--u)); border-radius: calc(12 * var(--u)); background: var(--a-surface-2);
  color: var(--a-ink); font: inherit; font-size: calc(19 * var(--u)); font-weight: 650; }
.key.blank { background: none; }
.centered-row { display: flex; align-items: center; gap: 14px; }
.phone .side, .phone .what .side, .phone .ended .side { width: auto; max-width: none; }
.phone .col { padding-top: 0; }
.phone .file-lines { padding-top: 0; }
.phone .src { min-height: 70px; padding: 8px 16px; }
.phone .what .col { gap: 18px; }
.phone .came { margin: 0; width: auto; align-self: stretch; }
.phone .centered { min-height: 60dvh; }
.phone .typing { padding: 8px 20px; }
.phone .field input { font-size: 20px; }
.phone .field-row .a-btn { border-radius: 14px; padding: 0 20px; font-size: 17px; }
.notes { margin: 10px 4px 0; padding-left: 18px; display: grid; gap: 4px; color: var(--a-ink-2); font-size: calc(14 * var(--u, 1px)); }
</style>
