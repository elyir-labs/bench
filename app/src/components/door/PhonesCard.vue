<template>
  <!-- On the printer's own screen: who can reach it from away, and pairing a new phone.
       Hidden when the printer has no door (listPhones() answers null). -->
  <div v-if="phones" class="card">
    <div class="head">
      <div class="text">
        <span class="name">Phones</span>
        <span class="when">{{ phones.length ? 'These can see the printer and get its notifications from anywhere.' : 'Add a phone to see the printer and get its notifications from anywhere.' }}</span>
      </div>
      <button class="a-btn accent add" @click="open">Add a phone</button>
    </div>
    <ul v-if="phones.length" class="phones">
      <li v-for="p in phones" :key="p.id">
        <div class="who">
          <span class="pname">{{ p.name }}</span>
          <span class="when">{{ seen(p) }}<template v-if="p.notifications"> · notifications on</template></span>
        </div>
        <button class="a-btn ghost small" :disabled="removing === p.id" @click="remove(p)">
          {{ confirming === p.id ? 'Remove?' : 'Remove' }}
        </button>
      </li>
    </ul>
    <p v-if="error" class="err">{{ error }}</p>

    <Teleport to="body">
      <Transition name="sheet">
        <div v-if="sheet" class="scrim" @click.self="close">
          <div class="sheet" role="dialog" aria-modal="true" aria-label="Add a phone">
            <template v-if="paired">
              <h2 class="a-display">{{ paired }} is paired</h2>
              <p class="sub">It can reach the printer from anywhere now. To get notifications, open the printer from its Home Screen and turn them on in Care.</p>
              <div class="actions"><button class="a-btn accent" @click="close">Done</button></div>
            </template>
            <template v-else-if="code">
              <div class="pair">
                <div class="qr"><QrCode :value="code.shell_url ?? code.url" label="Pairing code" /></div>
                <div class="how">
                  <h2 class="a-display">Add a phone</h2>
                  <!-- once a device is asking, the instructions have done their job: the ask takes their place -->
                  <ol v-if="!waiting.length">
                    <li>Scan this with the phone's camera.</li>
                    <li v-if="code.shell_url">Or in Printers ({{ host }}), tap Add a printer, then <b>{{ printer.toUpperCase() }}</b>.</li>
                    <li v-else>Or go to <b>{{ host }}/pair</b> and type <b class="a-num code">{{ pretty }}</b></li>
                  </ol>
                  <div v-for="a in waiting" :key="a.id" class="ask">
                    <span class="ask-name">{{ a.name }} wants to connect</span>
                    <div class="ask-actions">
                      <button class="a-btn accent" :disabled="answering === a.id" @click="reply(a.id, true)">Allow</button>
                      <button class="a-btn ghost" :disabled="answering === a.id" @click="reply(a.id, false)">Not now</button>
                    </div>
                  </div>
                  <p class="sub a-num">Code <b class="code">{{ pretty }}</b> · works once, for {{ left }}.</p>
                  <div class="actions"><button class="a-btn ghost" @click="close">Cancel</button></div>
                </div>
              </div>
            </template>
            <template v-else>
              <h2 class="a-display">Add a phone</h2>
              <p class="sub">{{ sheetError || 'Getting a code…' }}</p>
              <div class="actions"><button class="a-btn ghost" @click="close">Close</button></div>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { answer, asks } from '@/asks'
import QrCode from './QrCode.vue'
import { listPhones, newPairCode, removePhone, type DoorPhone, type PairCode } from '@/door'

const phones = ref<DoorPhone[] | null>(null)
const error = ref<string | null>(null)
const removing = ref<string | null>(null)
const confirming = ref<string | null>(null)

const sheet = ref(false)
const code = ref<PairCode | null>(null)
const sheetError = ref<string | null>(null)
const paired = ref<string | null>(null)
const now = ref(Date.now() / 1000)
let timer = 0

async function refresh() {
  const list = await listPhones()
  if (sheet.value && code.value && phones.value && list && list.length > phones.value.length) {
    const fresh = list.find((p) => !phones.value!.some((q) => q.id === p.id))
    paired.value = fresh?.name ?? 'The phone'
  }
  phones.value = list
}

function seen(p: DoorPhone): string {
  const t = p.last_seen ?? p.joined
  const mins = Math.max(0, Math.round((Date.now() / 1000 - t) / 60))
  if (mins < 2) return 'Seen just now'
  if (mins < 60) return `Seen ${mins} minutes ago`
  const hours = Math.round(mins / 60)
  if (hours < 36) return `Seen ${hours} hour${hours === 1 ? '' : 's'} ago`
  return `Seen ${Math.round(hours / 24)} days ago`
}

async function remove(p: DoorPhone) {
  if (confirming.value !== p.id) {   // a second tap confirms
    confirming.value = p.id
    return
  }
  removing.value = p.id
  error.value = null
  try {
    await removePhone(p.id)
    await refresh()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    removing.value = null
    confirming.value = null
  }
}

async function open() {
  sheet.value = true
  code.value = null
  paired.value = null
  sheetError.value = null
  try {
    code.value = await newPairCode()
  } catch (e) {
    sheetError.value = (e as Error).message
  }
}
function close() {
  sheet.value = false
  code.value = null
}

// While this sheet is open it shows waiting asks itself; the interrupting card stays out of the way.
watch(sheet, (open) => { asks.inline = open })
const waiting = computed(() => asks.list.filter((a) => a.expires > now.value && a.kind !== 'backup'))
const answering = ref<string | null>(null)
async function reply(id: string, allow: boolean) {
  answering.value = id
  try {
    await answer(id, allow)
    if (allow) await refresh()
  } catch (e) {
    sheetError.value = (e as Error).message
  } finally {
    answering.value = null
  }
}

const host = computed(() => (code.value ? new URL(code.value.shell_url ?? code.value.url).host : ''))
const printer = computed(() => (code.value ? new URL(code.value.url).host.split('.')[0] : ''))   // "workshop": what Add a printer accepts
const pretty = computed(() => (code.value ? code.value.code.replace(/^(.{4})(.+)$/, '$1-$2') : ''))
const left = computed(() => {
  if (!code.value) return ''
  const s = Math.max(0, Math.round(code.value.expires - now.value))
  return s >= 90 ? `${Math.round(s / 60)} more minutes` : `${s} more seconds`
})

onMounted(() => {
  refresh()
  timer = window.setInterval(() => {
    now.value = Date.now() / 1000
    if (code.value && code.value.expires <= now.value && !paired.value) open()   // a fresh code when this one runs out
    if (sheet.value) refresh()   // notice the phone that just paired
  }, 3000)
})
onBeforeUnmount(() => { window.clearInterval(timer); asks.inline = false })
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
.name, .pname { font-weight: 600; }
.when { color: var(--a-ink-3); font-size: 0.85em; }
.add { flex: none; padding: calc(9 * var(--u) + 4px) calc(16 * var(--u) + 6px); font-size: calc(16 * var(--u) + 4px); min-height: 44px; }
.phones { list-style: none; margin: calc(10 * var(--u) + 4px) 0 0; padding: 0; }
.phones li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: calc(8 * var(--u) + 4px) 0; border-top: 1px solid var(--a-line); margin: 0; color: var(--a-ink); }
.who { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.small { flex: none; padding: calc(6 * var(--u) + 4px) calc(14 * var(--u) + 4px); font-size: calc(15 * var(--u) + 4px); min-height: 40px; }
.err { color: var(--a-red-text); font-size: 0.85em; margin: 8px 0 0; }

.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: calc(14 * var(--u) + 6px);
}
.sheet {
  container-type: inline-size;   /* the layout below follows the sheet, not the window */
  background: var(--a-surface);
  color: var(--a-ink);
  border-radius: calc(22 * var(--u) + 8px);
  box-shadow: var(--a-card-shadow);
  max-width: 720px; width: 100%;
  max-height: 100%; overflow: auto;
  padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px);
}
.sheet h2 { font-size: calc(22 * var(--u) + 6px); margin: 0 0 calc(6 * var(--u) + 2px); }
.sub { color: var(--a-ink-2); font-size: calc(14 * var(--u) + 5px); margin: 0; line-height: 1.4; }
.pair { display: flex; gap: calc(20 * var(--u) + 8px); align-items: center; }
/* the code shrinks with the sheet and the words keep the rest; long names and codes wrap */
.qr { flex: none; width: min(calc(220 * var(--u) + 40px), 46vh, 42cqi); }
.how { flex: 1; min-width: 0; }
.how b { overflow-wrap: anywhere; }
.how ol { list-style: decimal; margin: 0 0 calc(8 * var(--u) + 3px); padding-left: 1.2em; color: var(--a-ink-2); font-size: calc(15 * var(--u) + 5px); line-height: 1.45; }
.how li { margin: 0 0 4px; color: var(--a-ink-2); }
.how b { color: var(--a-ink); }
.ask { margin: 2px 0 10px; padding: calc(10 * var(--u) + 4px) calc(12 * var(--u) + 4px); border-radius: calc(12 * var(--u) + 4px); background: var(--a-bg); display: flex; flex-direction: column; gap: calc(8 * var(--u) + 2px); }
.ask-name { font-weight: 700; font-size: calc(15 * var(--u) + 5px); overflow-wrap: anywhere; }
.ask-actions { display: flex; gap: calc(8 * var(--u) + 2px); }
.ask-actions .a-btn { flex: 1 1 0; padding: calc(8 * var(--u) + 4px) calc(12 * var(--u) + 4px); font-size: calc(15 * var(--u) + 4px); min-height: 44px; }
.code { letter-spacing: 0.06em; white-space: nowrap; overflow-wrap: normal; }   /* typed by hand: never split */
.actions { display: flex; gap: calc(10 * var(--u) + 4px); margin-top: calc(14 * var(--u) + 4px); }
.actions .a-btn { flex: 0 1 auto; padding: calc(10 * var(--u) + 4px) calc(20 * var(--u) + 6px); font-size: calc(18 * var(--u) + 4px); }
.sheet-enter-active, .sheet-leave-active { transition: opacity 160ms ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 560px) { .head { flex-direction: column; align-items: stretch; } }
@container (max-width: 560px) {
  .pair { flex-direction: column; align-items: flex-start; }
  .qr { width: min(260px, 70cqi, 40vh); align-self: center; }
}
</style>
