<template>
  <!-- Bench Cloud (design/cloud/ C): this printer in the house's cloud, and turning it on from a phone at home, in the
       printer's own page or inside the Printers app. Away and on the panel it says how it is and where to turn it on.
       Hidden without a door that knows Bench Cloud (doorCloud() answers null). -->
  <div v-if="d" class="card">
    <div class="head">
      <div class="text">
        <span class="name">{{ CARD_NAME }}</span>
        <span class="when">{{ line }}</span>
      </div>
      <div v-if="!isPanel && !door.away && state !== 'on'" class="btns">
        <!-- design/account/: Elyir only asks you to sign in on elyir.com, so Bench Cloud is turned on in the Printers app -->
        <a v-if="state === 'off'" class="a-btn accent add" :href="PRINTERS_YOU">{{ TURN_ON_IN_APP }}</a>
        <button v-else class="a-btn accent add" :disabled="busy" @click="addHere">{{ busy ? joining(printer) : addPrinter(printer) }}</button>
      </div>
    </div>
    <p v-if="error" class="err">{{ error }}</p>

    <Teleport to="body">
      <Transition name="sheet">
        <div v-if="step" class="scrim" @click.self="close">
          <form class="sheet" role="dialog" aria-modal="true" :aria-label="JOIN_TITLE" @submit.prevent="go">
            <template v-if="step === 'join'">
              <h2 class="a-display">{{ JOIN_TITLE }}</h2>
              <p class="sub">{{ JOIN_SUB }}</p>
              <ul class="gets">
                <li v-for="g in GETS" :key="g.title"><span class="tick" aria-hidden="true">✓</span><span><b>{{ g.title }}</b><small>{{ g.line }}</small></span></li>
              </ul>
              <p class="later">{{ LATER }}</p>
              <label class="field"><span>{{ EMAIL_LABEL }}</span>
                <input v-model="email" type="email" autocomplete="email" autocapitalize="none" spellcheck="false" placeholder="you@example.net" /></label>
              <p class="hint">{{ EMAIL_HINT }}</p>
              <label class="field"><span>{{ INVITE_LABEL }}</span>
                <input v-model="invite" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="ABCD-2345" /></label>
              <p class="hint">{{ INVITE_HINT }}</p>
            </template>
            <template v-else-if="step === 'signin'">
              <h2 class="a-display">{{ SIGN_IN_TITLE }}</h2>
              <p class="sub">{{ SIGN_IN_SUB }}</p>
              <label class="field"><span>{{ EMAIL_LABEL }}</span>
                <input v-model="email" type="email" autocomplete="email" autocapitalize="none" spellcheck="false" placeholder="you@example.net" /></label>
            </template>
            <template v-else-if="step === 'second'">
              <h2 class="a-display">{{ SECOND_ADD }}</h2>
              <p class="sub">{{ SECOND_ADD_LINE }}</p>
              <label class="field"><span>{{ SECOND_EMAIL }}</span>
                <input v-model="secondEmail" type="email" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="them@example.net" /></label>
            </template>
            <template v-else-if="step === 'join-code' || step === 'signin-code'">
              <h2 class="a-display">{{ codeTitle(sentTo) }}</h2>
              <label class="field"><span class="sr">Code</span>
                <input v-model="code" class="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="7" placeholder="000000" /></label>
            </template>
            <template v-else-if="step === 'on'">
              <span class="done-mark" aria-hidden="true">✓</span>
              <h2 class="a-display">{{ ON_TITLE }}</h2>
              <p class="sub">{{ onLine(owner?.email ?? email, printer) }}</p>
              <div class="second">
                <span class="lbl">{{ SECOND_LABEL }}</span>
                <p class="sub">{{ SECOND_LINE }}</p>
                <button type="button" class="opt" @click="open('second', true)"><b>{{ SECOND_ADD }}</b><small>{{ SECOND_ADD_LINE }}</small></button>
              </div>
            </template>
            <template v-else-if="step === 'second-done'">
              <span class="done-mark" aria-hidden="true">✓</span>
              <h2 class="a-display">{{ secondDone(secondEmail.trim()) }}</h2>
            </template>

            <p v-if="sheetError" class="err">{{ sheetError }}</p>
            <div class="actions">
              <button v-if="goLabel" type="submit" class="a-btn accent" :disabled="busy || !canGo">{{ busy ? '…' : goLabel }}</button>
              <button type="button" class="a-btn ghost" @click="close">{{ closeLabel }}</button>
            </div>
          </form>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useIntentStore } from '@/intent/store'
import { isPanel } from '@/theme'
import { door, doorCloud, guessDeviceName, joinCloud } from '@/door'
import {
  CANCEL, CARD_NAME, CLOUD_API, DONE, EMAIL_HINT, EMAIL_LABEL, GETS, INVITE_HINT, INVITE_LABEL, JOIN_SUB, JOIN_TITLE, LATER, NOT_NOW,
  ON_TITLE, PRINTERS_YOU, TURN_ON_IN_APP, SECOND_ADD, SECOND_ADD_LINE, SECOND_EMAIL, SECOND_GO, SECOND_LABEL, SECOND_LINE, SEND, SIGN_IN, SIGN_IN_GO,
  SIGN_IN_SUB, SIGN_IN_TITLE, TURN_ON, addPrinter, awayLine, cardLine, panelOff, cardState, cloudCall, codeTitle, digitsOf, joining, loadOwner, onLine,
  ownerCall, saveOwner, secondDone, sendCode, sixDigits, validEmail, validInvite, verifyCode, type DoorCloud, type Owner,
  type SupabaseConfig,
} from '@/cloud'

type Step = 'join' | 'join-code' | 'signin' | 'signin-code' | 'on' | 'second' | 'second-done'

const api = (import.meta.env.VITE_CLOUD_URL as string | undefined) || CLOUD_API
const store = useIntentStore()
const printer = computed(() => store.intent?.printer?.name ?? 'This printer')
const storage = (() => { try { return window.localStorage } catch { return null } })()

const d = ref<DoorCloud | null>(null)
const owner = ref<Owner | null>(loadOwner(storage))
const state = computed(() => (d.value ? cardState(d.value, owner.value) : 'off'))
const now = ref(Date.now())
const line = computed(() => {
  if (!d.value) return ''
  if (isPanel && state.value !== 'on') return panelOff(printer.value)
  return (door.away ? awayLine(state.value, printer.value) : null) ?? cardLine(state.value, d.value, printer.value, now.value)
})
const busy = ref(false)
const error = ref<string | null>(null)

const step = ref<Step | null>(null)
const email = ref('')
const invite = ref('')
const code = ref('')
const secondEmail = ref('')
const cfg = ref<SupabaseConfig | null>(null)
const sentTo = ref('')
const sheetError = ref<string | null>(null)

const goLabel = computed(() => ({ join: SEND, signin: SEND, second: SECOND_GO, 'join-code': TURN_ON, 'signin-code': SIGN_IN_GO } as
                                 Record<string, string>)[step.value ?? ''] ?? '')
const closeLabel = computed(() => (step.value === 'on' ? NOT_NOW : step.value === 'second-done' ? DONE : CANCEL))
const canGo = computed(() => {
  if (step.value === 'join') return validEmail(email.value) && validInvite(invite.value)
  if (step.value === 'signin') return validEmail(email.value)
  if (step.value === 'second') return validEmail(secondEmail.value)
  return sixDigits(code.value)
})

function setOwner(o: Owner | null): void {
  owner.value = o
  saveOwner(storage, o)
}

async function refresh(): Promise<void> { d.value = await doorCloud() }

function open(s: Step, keep = false): void {
  step.value = s
  sheetError.value = null
  code.value = ''
  if (!keep) error.value = null
}
function close(): void { step.value = null }

async function joinHere(): Promise<void> {
  const o = owner.value
  if (!o) throw new Error('Sign in to your Bench Cloud first.')
  try {
    const t = await ownerCall(o, setOwner, guessDeviceName(), 'POST', '/v1/join-tokens', { name: printer.value, kind: 'printer' })
    await joinCloud(t.join_token, o.api)
  } catch (e) {
    if (/^Sign in/.test((e as Error).message)) setOwner(null)   // signed out elsewhere (a lost phone moved the owner)
    throw e
  }
  await refresh()
}

async function addHere(): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await joinHere()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function go(): Promise<void> {
  if (!canGo.value || busy.value) return
  busy.value = true
  sheetError.value = null
  const typed = digitsOf(code.value)
  try {
    if (step.value === 'join') {   // the invite first, so nobody types a code only to hear the invite isn't one
      await cloudCall(api, 'POST', '/v1/invites/check', { invite: invite.value.trim() })
      cfg.value = await sendCode(api, email.value.trim())
      sentTo.value = email.value.trim()
      open('join-code', true)
    } else if (step.value === 'signin') {
      cfg.value = await sendCode(api, email.value.trim())
      sentTo.value = email.value.trim()
      open('signin-code', true)
    } else if (step.value === 'second') {
      await ownerCall(owner.value!, setOwner, guessDeviceName(), 'POST', '/v1/owners', { email: secondEmail.value.trim() })
      open('second-done', true)
    } else if ((step.value === 'join-code' || step.value === 'signin-code') && cfg.value) {
      const first = step.value === 'join-code'
      const o = await verifyCode(api, cfg.value, email.value.trim(), typed)
      setOwner(o)
      if (first) await ownerCall(o, setOwner, guessDeviceName(), 'POST', '/v1/start', { invite: invite.value.trim() })
      await joinHere()
      if (first) open('on', true)
      else close()
    }
  } catch (e) {
    sheetError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

let timer = 0
onMounted(() => {
  refresh()
  timer = window.setInterval(() => { now.value = Date.now(); refresh() }, 60_000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.card {
  margin-top: calc(12 * var(--u) + 4px);
  padding: calc(12 * var(--u) + 5px) calc(16 * var(--u) + 6px);
  border-radius: calc(16 * var(--u) + 6px);
  background: var(--a-surface);
  font-size: calc(17 * var(--u) + 5px);
}
.head { display: flex; align-items: center; justify-content: space-between; gap: calc(16 * var(--u) + 6px); }
.text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.name { font-weight: 600; }
.when { color: var(--a-ink-3); font-size: 0.85em; }
.btns { display: flex; gap: calc(8 * var(--u) + 2px); flex: none; }
.add { flex: none; padding: calc(9 * var(--u) + 4px) calc(16 * var(--u) + 6px); font-size: calc(16 * var(--u) + 4px); min-height: 44px; }
.err { color: var(--a-red-text); font-size: 0.85em; margin: 8px 0 0; }

.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: calc(14 * var(--u) + 6px);
}
.sheet {
  background: var(--a-surface);
  color: var(--a-ink);
  border-radius: calc(22 * var(--u) + 8px);
  box-shadow: var(--a-card-shadow);
  max-width: 520px; width: 100%;
  max-height: 100%; overflow: auto;
  padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px);
  display: grid; gap: calc(8 * var(--u) + 4px);
}
.sheet h2 { font-size: calc(22 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(14 * var(--u) + 5px); margin: 0; line-height: 1.4; }
.gets { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.gets li { display: grid; grid-template-columns: 22px 1fr; gap: 8px; margin: 0; color: var(--a-ink); }
.gets .tick { color: var(--a-green-text); font-weight: 700; }
.gets b { display: block; font-size: calc(15 * var(--u) + 5px); }
.gets small, .opt small { display: block; color: var(--a-ink-3); font-size: calc(13 * var(--u) + 4px); line-height: 1.35; }
.later, .hint { color: var(--a-ink-3); font-size: calc(13 * var(--u) + 4px); margin: 0; line-height: 1.35; }
.hint { margin-top: -4px; }
.field { display: grid; gap: 6px; }
.field > span { font-size: calc(14 * var(--u) + 4px); font-weight: 650; color: var(--a-ink-2); }
.field input {
  height: 50px; border-radius: 14px; border: 1px solid var(--a-line); background: var(--a-bg); color: var(--a-ink);
  padding: 0 14px; font: inherit; font-size: 17px;
}
.field input:focus { outline: none; border: 2px solid var(--a-accent); padding: 0 13px; }
.field input.code { letter-spacing: 0.25em; font-size: 22px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.done-mark { width: 48px; height: 48px; border-radius: 14px; background: var(--a-tint-green); color: var(--a-green-text);
  display: grid; place-items: center; font-size: 26px; font-weight: 800; }
.second { display: grid; gap: 8px; padding: 14px 16px; border-radius: 18px; background: var(--a-bg); }
.lbl { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.opt { appearance: none; text-align: left; border: 1px solid var(--a-line); border-radius: 16px; background: var(--a-surface);
  color: var(--a-ink); padding: 12px 14px; font: inherit; cursor: pointer; }
.opt b { font-size: calc(15 * var(--u) + 5px); }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); margin-top: calc(6 * var(--u) + 2px); flex-wrap: wrap; }
.actions .a-btn { flex: 0 1 auto; padding: calc(10 * var(--u) + 4px) calc(20 * var(--u) + 6px); font-size: calc(18 * var(--u) + 4px); }
.sheet-enter-active, .sheet-leave-active { transition: opacity 160ms ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 560px) {
  .head { flex-direction: column; align-items: stretch; }
  .btns .a-btn { flex: 1 1 0; }
  .actions .a-btn { flex: 1 1 0; }
}
</style>
