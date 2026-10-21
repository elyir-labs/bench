<template>
  <!-- Care, on the box (design/bench-box/, D): every printer's maintenance in one list, what's due first, then
       the nearest. Each printer counts its own; doing it and marking it done is on that printer's Care. -->
  <section class="bpage">
    <BenchTop title="Care" />
    <h1 class="a-display say">{{ line }}</h1>
    <ul class="rows">
      <li v-for="r in rows" :key="r.printerId + r.id" class="row" :class="{ due: r.due && !r.snoozed }" @click="router.push(`/p/${r.printerId}/care`)">
        <span class="t"><b>{{ r.name }}</b><span>{{ r.snoozed ? 'Later' : r.due ? 'Due now' : r.label }}</span></span>
        <span class="bar" aria-hidden="true"><i :style="{ width: Math.min(1, r.progress) * 100 + '%' }"></i></span>
        <span class="who">{{ r.printer }}</span>
      </li>
    </ul>

    <!-- phones, guests and invites (design/bench-remote/, C): the box's own screen and phones at home only -->
    <PhonesSection v-if="!here.away" @remote="remote?.refresh()" />

    <!-- the box itself (design/power/, A; design/role/'s way back): From away, Turn off with Restart, and Make it a printer -->
    <template v-if="box">
      <h2 class="group">{{ BOX_HEAD }}</h2>
      <p v-if="going" class="going">{{ going }}</p>
      <div v-else-if="box.role" class="card becoming">
        <span class="t"><b>{{ box.role.state === 'failed' ? "It didn't become a printer." : 'Becoming a printer' }}</b>
          <span>{{ box.role.state === 'failed' ? box.role.why : 'Its screen changes to the new printer setup in a minute or two.' }}</span></span>
        <ol v-if="box.role.state !== 'failed'" class="steps">
          <li v-for="st in roleSteps(box.role)" :key="st.label" :class="st.status"><i aria-hidden="true"></i>{{ st.label }}</li>
        </ol>
      </div>
      <template v-else>
        <RemoteRow ref="remote" />
        <div class="card">
          <span class="t"><b>{{ POWER_ROW.title }}</b><span>{{ POWER_ROW.line }}</span></span>
          <span class="acts"><button class="a-btn ghost" @click="ask = 'restart'">Restart</button><button class="a-btn ghost" @click="ask = 'off'">Turn off</button></span>
        </div>
        <div class="card">
          <span class="t"><b>{{ ROLE_ROW.title }}</b><span>{{ ROLE_ROW.line }}</span></span>
          <span class="acts"><button class="a-btn ghost" @click="ask = 'role'">Make it a printer</button></span>
        </div>
        <!-- a card's OS and the way in over SSH: home only (bench/box.py; the away listener never routes them) -->
        <template v-if="!here.away">
          <div v-if="box.os?.update" class="card">
            <span class="t"><b>{{ box.os.update.state === 'failed' ? "It didn't update." : 'Updating' }}</b>
              <span>{{ box.os.update.state === 'failed' ? box.os.update.why : box.os.update.line || 'Looking for the new version.' }}</span></span>
            <span v-if="box.os.update.state === 'failed'" class="acts"><button class="a-btn ghost" @click="ask = 'update'">Try again</button></span>
          </div>
          <div v-else-if="box.os && osInfo" class="card">
            <span class="t"><b>{{ osInfo.title }}</b><span>{{ osInfo.line }}</span></span>
            <span v-if="osInfo.newer || !box.os.latest" class="acts"><button class="a-btn ghost" @click="ask = 'update'">Update now</button></span>
          </div>
          <div v-if="box.ssh && sshInfo" class="card">
            <span class="t"><b>{{ sshInfo.title }}</b><span>{{ sshInfo.line }}</span></span>
            <span class="acts"><button class="a-btn ghost" @click="openAddKey">Add a key</button></span>
          </div>
          <ul v-if="box.ssh?.keys.length" class="keylist">
            <li v-for="k in box.ssh.keys" :key="k.id"><span class="t"><b>{{ k.name || 'A key' }}</b><span>{{ k.kind }}</span></span>
              <button class="a-btn ghost" @click="dropKey = k">Take off</button></li>
          </ul>
        </template>
      </template>
      <p v-if="err" class="err">{{ err }}</p>
    </template>
    <SliceSheet :open="ask === 'off' || ask === 'restart'" :title="sheet.title" :sub="sheet.line" @close="ask = null">
      <div class="ask-btns"><button class="a-btn ghost" @click="ask = null">Keep it on</button><button class="a-btn accent" :disabled="busy" @click="power">{{ sheet.go }}</button></div>
    </SliceSheet>
    <SliceSheet :open="ask === 'update'" :title="UPDATE_ASK.title" :sub="UPDATE_ASK.line" @close="ask = null">
      <div class="ask-btns"><button class="a-btn ghost" @click="ask = null">{{ UPDATE_ASK.keep }}</button><button class="a-btn accent" :disabled="busy" @click="updateNow">{{ UPDATE_ASK.go }}</button></div>
    </SliceSheet>
    <SliceSheet :open="ask === 'key'" :title="SSH_ADD.title" :sub="SSH_ADD.line" @close="ask = null">
      <textarea v-model="keyText" class="keybox" rows="4" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Public key"
        placeholder="ssh-ed25519 AAAA… you@computer"></textarea>
      <p v-if="keyErr" class="err">{{ keyErr }}</p>
      <div class="ask-btns"><button class="a-btn ghost" @click="ask = null">{{ SSH_ADD.keep }}</button><button class="a-btn accent" :disabled="busy || !keyText.trim()" @click="addKey">{{ SSH_ADD.go }}</button></div>
    </SliceSheet>
    <SliceSheet :open="!!dropKey" :title="`Take ${dropKey?.name || 'this key'} off?`" sub="It can't sign in to this box any more." @close="dropKey = null">
      <div class="ask-btns"><button class="a-btn ghost" @click="dropKey = null">Keep it</button><button class="a-btn accent" :disabled="busy" @click="takeOff">Take it off</button></div>
    </SliceSheet>
    <SliceSheet :open="ask === 'role'" :title="ROLE_ASK.title" :sub="ROLE_ASK.line" @close="ask = null">
      <div class="ask-btns"><button class="a-btn ghost" @click="ask = null">{{ ROLE_ASK.keep }}</button><button class="a-btn accent" :disabled="busy" @click="becomePrinter">{{ ROLE_ASK.go }}</button></div>
    </SliceSheet>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import { BOX_HEAD, POWER_ROW, ROLE_ASK, ROLE_ROW, SSH_ADD, UPDATE_ASK, boxInfo, boxPost, osRow, powerAsk, powerGoing, removeKey, roleSteps, sshRow,
  type BoxInfo, type BoxKey, type BoxPower } from '../box'
import { useRouter } from 'vue-router'
import { bench } from '../live'
import { careRows, careSentence } from '../tabs'
import BenchTop from './BenchTop.vue'
import PhonesSection from './PhonesSection.vue'
import RemoteRow from './RemoteRow.vue'
import { here } from '../here'

const router = useRouter()
const remote = ref<InstanceType<typeof RemoteRow> | null>(null)
const rows = computed(() => careRows(bench.printers))
const line = computed(() => (bench.loaded ? careSentence(rows.value) : ''))

// the box itself (bench/box.py): null on a service too old to say
const NAME = 'the Bench Box'
const box = ref<BoxInfo | null>(null)
const ask = ref<BoxPower | 'role' | 'update' | 'key' | null>(null)
const busy = ref(false)
const err = ref<string | null>(null)
const going = ref<string | null>(null)
const sheet = computed(() => powerAsk(ask.value === 'restart' ? 'restart' : 'off', NAME))
let timer = 0
async function refresh() { box.value = await boxInfo() }
onMounted(() => { refresh(); timer = window.setInterval(refresh, 2000) })
onBeforeUnmount(() => window.clearInterval(timer))
async function power() {
  const kind: BoxPower = ask.value === 'restart' ? 'restart' : 'off'
  busy.value = true
  err.value = await boxPost('power', { kind })
  busy.value = false
  ask.value = null
  if (!err.value) going.value = powerGoing(kind, NAME)
}
const osInfo = computed(() => (box.value?.os ? osRow(box.value.os) : null))
const sshInfo = computed(() => (box.value?.ssh ? sshRow(box.value.ssh.user, box.value.ssh.keys) : null))
const keyText = ref('')
const keyErr = ref<string | null>(null)
const dropKey = ref<BoxKey | null>(null)
async function updateNow() {
  busy.value = true
  err.value = await boxPost('update')
  busy.value = false
  ask.value = null
  refresh()
}
function openAddKey() {
  keyText.value = ''
  keyErr.value = null
  ask.value = 'key'
}
async function addKey() {
  busy.value = true
  keyErr.value = await boxPost('ssh', { key: keyText.value })
  busy.value = false
  if (!keyErr.value) ask.value = null
  refresh()
}
async function takeOff() {
  if (!dropKey.value) return
  busy.value = true
  err.value = await removeKey(dropKey.value.id)
  busy.value = false
  dropKey.value = null
  refresh()
}
async function becomePrinter() {
  busy.value = true
  err.value = await boxPost('role')
  busy.value = false
  ask.value = null
  refresh()
}
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 16px; }
.say { margin: 8px 0 0; font-size: 40px; line-height: 1.08; letter-spacing: -.025em; text-wrap: balance; }
.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.row { display: grid; grid-template-columns: minmax(0, 1fr) 220px 140px; align-items: center; gap: 24px; padding: 14px 22px;
       background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); cursor: pointer; }
.row.due { box-shadow: 0 0 0 3px var(--a-amber), var(--a-card-shadow); }
.t { display: grid; gap: 2px; min-width: 0; }
.t b { font-size: 21px; } .t span { color: var(--a-ink-3); font-size: 17px; }
.row.due .t span { color: var(--a-amber-text); font-weight: 650; }
.group { margin: 18px 0 0; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.card { display: flex; align-items: center; gap: 24px; padding: 18px 22px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.card .acts { display: flex; gap: 10px; flex: none; }
.card .acts .a-btn { height: 52px; padding: 0 24px; border-radius: 999px; font-size: 18px; white-space: nowrap; }
.card .t { flex: 1; }
.becoming { flex-direction: column; align-items: stretch; }
.steps { list-style: none; margin: 4px 0 0; padding: 0; display: grid; gap: 10px; }
.steps li { display: flex; align-items: center; gap: 12px; font-size: 18px; }
.steps i { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--a-line); flex: none; }
.steps .ok i { background: var(--a-green); border-color: var(--a-green); }
.steps .now i { border: 3px solid var(--a-accent); border-top-color: transparent; }
.steps .todo { color: var(--a-ink-3); }
.going { margin: 0; font-size: 20px; color: var(--a-ink-2); }
.err { margin: 0; color: var(--a-red-text); font-size: 15px; }
.keylist { list-style: none; margin: -6px 0 0; padding: 0 0 0 22px; display: grid; gap: 8px; }
.keylist li { display: flex; align-items: center; gap: 16px; padding: 10px 14px 10px 18px; background: var(--a-surface); border-radius: 14px; }
.keylist .t { flex: 1; } .keylist .t b { font-size: 18px; } .keylist .t span { font-size: 15px; }
.keylist .a-btn { height: 44px; padding: 0 18px; border-radius: 999px; font-size: 16px; flex: none; }
.keybox { box-sizing: border-box; width: 100%; margin: 4px 0 12px; padding: 12px 14px; border-radius: 14px; border: 1px solid var(--a-line);
          background: var(--a-surface); color: var(--a-ink); font: 15px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; resize: vertical; word-break: break-all; }
.ask-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ask-btns .a-btn { height: 54px; font-size: 17px; border-radius: 18px; }
.bar { height: 8px; border-radius: 4px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 4px; background: var(--a-accent); }
.row.due .bar i { background: var(--a-amber); }
.who { justify-self: end; font-weight: 650; font-size: 18px; color: var(--a-ink-2); }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 24px; gap: 10px; }
  .say { font-size: 25px; }
  .row { grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; padding: 10px 14px; border-radius: 14px; }
  .bar { grid-column: 1 / -1; grid-row: 2; height: 6px; }
  .t b { font-size: 16px; } .t span { font-size: 13px; } .who { font-size: 14px; }
  /* the box's rows: the buttons under the words, not squeezing them to a word a line */
  .card { flex-direction: column; align-items: stretch; gap: 12px; padding: 14px 16px; border-radius: 14px; }
  .card .acts .a-btn { height: 46px; padding: 0 20px; font-size: 16px; }
  .keylist { padding-left: 0; }
  .keylist .t b { font-size: 16px; } .keylist .t span { font-size: 13px; }
}
</style>
