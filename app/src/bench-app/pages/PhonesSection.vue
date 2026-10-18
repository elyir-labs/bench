<template>
  <!-- Care, Phones, on the box at home (design/bench-remote/, C-box-phones and A-box-add): the household's phones, guests
       with what they can do and until when, invites nobody has opened, and the two ways to add someone. -->
  <template v-if="list">
    <div class="phead">
      <span class="t"><h2 class="group">{{ PHONES.head }}</h2>
        <span>{{ rows.length ? PHONES.line : 'Add a phone to see the whole bench from anywhere, or invite someone to watch.' }}</span></span>
      <button class="a-btn accent" @click="inviting = true">{{ PHONES.invite }}</button>
      <button class="a-btn ghost" @click="addPhone">{{ PHONES.add }}</button>
    </div>
    <div v-for="r in rows" :key="r.kind + r.id" class="card" :class="[r.kind, { watching: r.watching }]">
      <span class="t"><b>{{ r.title }}<span v-if="r.chip" class="gchip"><svg viewBox="0 0 24 24" aria-hidden="true" v-html="EYE"></svg>{{ r.chip }}</span></b>
        <span>{{ r.line }}</span></span>
      <span class="acts"><button class="a-btn ghost" :disabled="busy === r.id" @click="act(r)">{{ confirming === r.id ? 'Remove?' : r.button }}</button></span>
    </div>
    <p v-if="err" class="err">{{ err }}</p>

    <InviteSheet :open="inviting" @close="inviting = false" @made="refresh" />
    <Teleport to="body">
      <div v-if="adding" class="scrim" @click.self="closeAdd">
        <div class="dialog" role="dialog" aria-modal="true" aria-label="Add a phone">
          <template v-if="paired">
            <div class="how"><h2 class="a-display">{{ paired }} is paired</h2>
              <p class="sub">It sees the whole bench from anywhere now: every printer, its camera, the shelf.</p>
              <div class="end"><button class="a-btn accent" @click="closeAdd">Done</button></div></div>
          </template>
          <template v-else-if="code">
            <div class="code-box"><QrCode :value="code.url" label="Pairing code" /></div>
            <div class="how">
              <h2 class="a-display">Add a phone</h2>
              <ol>
                <li>Scan this with the phone's camera.</li>
                <li>It sees the whole bench from anywhere: every printer, its camera, the shelf.</li>
                <li>Or go to <b>{{ host }}/pair</b> and type <b class="a-num code">{{ prettyCode(code.code) }}</b></li>
              </ol>
              <p class="sub a-num">Code <b>{{ prettyCode(code.code) }}</b> · works once, for {{ codeLeft(code.expires, now) }}.</p>
              <div class="end"><button class="a-btn ghost" @click="closeAdd">Cancel</button></div>
            </div>
          </template>
          <template v-else>
            <div class="how">
              <h2 class="a-display">Add a phone</h2>
              <p class="sub">{{ addErr || 'Getting a code…' }}</p>
              <div class="end">
                <button v-if="off" class="a-btn accent" :disabled="turning" @click="turnOn">{{ turning ? 'Turning it on…' : 'Turn on From away' }}</button>
                <button class="a-btn ghost" @click="closeAdd">Close</button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Teleport>
  </template>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import QrCode from '@/components/door/QrCode.vue'
import { PHONES, codeLeft, phoneRows, prettyCode, type PhoneRow, type PhonesList } from '../away'
import { cancelInvite, getPhones, newCode, removePhone, turnRemote, type PairCode } from '../here'
import InviteSheet from './InviteSheet.vue'
import { EYE } from './AwayChip.vue'

const emit = defineEmits<{ remote: [] }>()
const list = ref<PhonesList | null>(null)
const now = ref(Date.now() / 1000)
const rows = computed(() => (list.value ? phoneRows(list.value, new Date(now.value * 1000)) : []))
const inviting = ref(false)
const confirming = ref<string | null>(null)
const busy = ref<string | null>(null)
const err = ref('')

async function refresh() {
  const l = await getPhones()
  if (adding.value && code.value && list.value && l) {
    const fresh = l.phones.find((p) => !list.value!.phones.some((q) => q.id === p.id))
    if (fresh) paired.value = fresh.name
  }
  list.value = l
}

async function act(r: PhoneRow) {
  if (r.kind !== 'invite' && confirming.value !== r.id) { confirming.value = r.id; return }   // a second tap removes
  busy.value = r.id
  err.value = ''
  try {
    await (r.kind === 'invite' ? cancelInvite(r.id) : removePhone(r.id))
    await refresh()
  } catch (e) {
    err.value = (e as Error).message
  } finally {
    busy.value = null
    confirming.value = null
  }
}

// ── Add a phone: a ten-minute code, shown as a QR of the box's /pair page ──
const adding = ref(false)
const code = ref<PairCode | null>(null)
const addErr = ref('')
const off = ref(false)
const turning = ref(false)
const paired = ref<string | null>(null)
const host = computed(() => (code.value ? new URL(code.value.url).host : ''))

async function addPhone() {
  adding.value = true
  code.value = null
  paired.value = null
  addErr.value = ''
  off.value = false
  try {
    code.value = await newCode()
  } catch (e) {
    const x = e as Error & { detail?: string }
    off.value = x.detail === 'off'
    addErr.value = off.value ? "The Bench Box isn't reachable from outside yet, so a phone away couldn't find it. Turn on From away first." : x.message
  }
}

async function turnOn() {
  turning.value = true
  const r = await turnRemote(true)
  turning.value = false
  emit('remote')
  if (r.error) { addErr.value = r.error; return }
  await addPhone()
}

function closeAdd() {
  adding.value = false
  code.value = null
}

let timer = 0
onMounted(() => {
  refresh()
  timer = window.setInterval(() => {
    now.value = Date.now() / 1000
    if (code.value && code.value.expires <= now.value && !paired.value) addPhone()   // a fresh code when this one runs out
    refresh()
  }, 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.phead { display: flex; align-items: center; gap: 12px; margin-top: 18px; }
.phead .t { flex: 1; display: grid; gap: 2px; min-width: 0; }
.phead .t > span { color: var(--a-ink-3); font-size: 17px; }
.phead .a-btn { height: 50px; padding: 0 24px; border-radius: 999px; font-size: 18px; white-space: nowrap; flex: none; }
.group { margin: 0; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.card { display: flex; align-items: center; gap: 24px; padding: 16px 22px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.card.watching { box-shadow: 0 0 0 2px color-mix(in srgb, var(--a-accent) 35%, transparent), var(--a-card-shadow); }
.card .t { flex: 1; display: grid; gap: 2px; min-width: 0; }
.card .t b { font-size: 21px; display: inline-flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.card .t > span { color: var(--a-ink-3); font-size: 17px; }
.card.invite .t b { color: var(--a-ink-3); font-weight: 650; }
.gchip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; border-radius: 999px; font-size: 14px; font-weight: 650;
         background: color-mix(in srgb, var(--a-accent) 14%, transparent); color: var(--a-accent-text); }
.gchip svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.9; }
.card.invite .gchip svg { display: none; }
.acts .a-btn { height: 50px; padding: 0 24px; border-radius: 999px; font-size: 18px; white-space: nowrap; }
.err { margin: 0; color: var(--a-red-text); font-size: 15px; }

.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, .45); display: grid; place-items: center; padding: 16px; }
.dialog { display: flex; gap: 40px; align-items: center; width: min(980px, 100%); max-height: 100%; overflow: auto; box-sizing: border-box;
          padding: 40px; border-radius: 28px; background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.code-box { flex: none; width: 300px; border-radius: 16px; border: 1px solid var(--a-line); overflow: hidden; }
.how { flex: 1; min-width: 0; }
.how h2 { margin: 0 0 14px; font-size: 38px; letter-spacing: -.02em; }
.how ol { margin: 0 0 14px; padding-left: 1.3em; color: var(--a-ink-2); font-size: 19px; line-height: 1.5; display: grid; gap: 4px; }
.how b { color: var(--a-ink); overflow-wrap: anywhere; }
.code { letter-spacing: .06em; white-space: nowrap; }
.sub { margin: 0; color: var(--a-ink-3); font-size: 16px; }
.end { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
.end .a-btn { flex: none; height: 50px; padding: 0 26px; border-radius: 999px; font-size: 18px; }
@media (max-width: 599px) {
  .phead { flex-wrap: wrap; } .phead .t { flex-basis: 100%; } .phead .a-btn { flex: 1; height: 44px; font-size: 15px; padding: 0 12px; }
  .card { gap: 12px; padding: 12px 14px; border-radius: 14px; } .card .t b { font-size: 16px; } .card .t > span { font-size: 13px; }
  .acts .a-btn { height: 40px; font-size: 14px; padding: 0 14px; }
  .dialog { flex-direction: column; padding: 22px; gap: 18px; } .code-box { width: 220px; } .how h2 { font-size: 26px; } .how ol { font-size: 15px; }
}
</style>
