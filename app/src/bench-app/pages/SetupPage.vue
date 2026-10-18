<template>
  <!-- The first run, and adding a printer later (design/bench-box/, first run): the printers on this Wi-Fi,
       each asked on its own screen, and the answers. -->
  <section class="setup">
    <header class="top">
      <span class="who"><i></i><b>Bench Box</b></span>
      <span class="right">{{ bench.printers.length ? '' : 'Setting up' }}</span>
    </header>
    <h1 class="a-display say">{{ headline }}</h1>
    <p class="lead">{{ lead }}</p>
    <ul class="list">
      <li v-for="f in found" :key="f.id" class="row">
        <span class="ico" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3.5" y="3" width="17" height="18" rx="2" /><path d="M3.5 7.5h17M8 12.5h8M12 7.5v5M7 17.5h10" /></svg></span>
        <span class="t"><b>{{ f.name }}</b><span>{{ line(f) }}</span></span>
        <span v-if="f.on" class="chip green"><i></i>Added</span>
        <button v-else-if="f.kind === 'anycubic'" class="a-btn" :class="f.why ? 'accent' : 'ghost'" @click="guiding = f.id">Set it up</button>
        <button v-else-if="f.door && (!f.ask || ['refused', 'expired', 'unreachable'].includes(f.ask.state))" class="a-btn ghost" :disabled="asking.has(f.id)" @click="ask(f)">{{ f.ask ? 'Ask again' : 'Ask' }}</button>
        <span v-else-if="f.ask?.state === 'waiting'" class="chip">Waiting</span>
      </li>
    </ul>
    <div class="acts">
      <button v-if="askable.length > 1" class="a-btn accent" @click="askAll">Ask all {{ count(askable.length) }}</button>
      <button v-else-if="askable.length === 1" class="a-btn accent" @click="ask(askable[0])">Ask {{ askable[0].name }}</button>
      <router-link v-if="bench.printers.length" to="/" class="a-btn" :class="askable.length ? 'ghost' : 'accent'">Done</router-link>
    </div>
    <KobraGuide v-if="guided" :row="guided" @added="look" @close="guiding = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { bench, loadBench } from '../live'
import KobraGuide from './KobraGuide.vue'

interface Found {
  id: string; name: string; host: string; door: boolean; on: boolean; ask: { state: string; words: string } | null
  kind?: 'anycubic'; why?: string | null   // a printer the box speaks for (design/bench-kobra/, A): added here, not asked
  via?: 'lan' | 'moonraker' | null         // how: Anycubic's LAN mode, or Rinkhals' Moonraker (design/kobra-lan/, B)
}
const found = ref<Found[]>([])
const looked = ref(false)
const asking = ref(new Set<string>())
const NUM = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
const count = (n: number) => (NUM[n] ?? String(n)).toLowerCase()

const askable = computed(() => found.value.filter((f) => !f.on && f.door && !f.ask))
const anycubics = computed(() => found.value.filter((f) => f.kind === 'anycubic'))
// the Kobra being brought on (KobraGuide), followed through each look at the Wi-Fi
const guiding = ref<string | null>(null)
const guided = computed(() => found.value.find((f) => f.id === guiding.value) ?? null)
const added = computed(() => found.value.filter((f) => f.on).length)
const waiting = computed(() => found.value.filter((f) => f.ask?.state === 'waiting'))
const headline = computed(() => {
  if (!looked.value) return 'Looking for printers…'
  if (!found.value.length) return 'No printers on this Wi-Fi yet.'
  if (found.value.every((f) => !f.on && !f.ask)) return `${NUM[found.value.length] ?? found.value.length} printer${found.value.length === 1 ? '' : 's'} on this Wi-Fi.`
  if (!added.value) return 'Asked.'
  return `${NUM[added.value] ?? added.value} ${anycubics.value.some((f) => f.on) ? 'on the bench' : 'said yes'}.`
})
const lead = computed(() => {
  if (!looked.value || !found.value.length) return 'A printer shows up here once it runs Elyir Bench and is on the same Wi-Fi.'
  if (waiting.value.length) return `${waiting.value.map((f) => f.name).join(' and ')} ${waiting.value.length === 1 ? "hasn't" : "haven't"} answered. ${waiting.value.length === 1 ? 'It' : 'Each'} can say yes on ${waiting.value.length === 1 ? 'its' : 'its own'} screen.`
  if (anycubics.value.length && anycubics.value.length === found.value.length) return 'An Anycubic needs LAN mode on, and nothing else. Set it up shows where.'
  if (anycubics.value.length) return 'Printers with Elyir Bench say yes on their own screen. An Anycubic needs LAN mode on, and nothing else.'
  return 'Each one is asked on its own screen. Once it says yes, this box can see and run everything it does.'
})
function line(f: Found): string {
  if (f.kind === 'anycubic') return f.on ? (f.via === 'lan' ? 'On the bench, over LAN mode' : 'On the bench, through Rinkhals')
    : f.why ? 'Anycubic · on its cloud' : `Anycubic · LAN mode is on`
  if (f.on) return 'Said yes'
  if (f.ask) return f.ask.words
  return f.door ? f.host : 'Its door is off, so it has nothing to ask yet'
}

async function ask(f: Found) {
  asking.value.add(f.id)
  try { await fetch(`/bench/ask/${encodeURIComponent(f.id)}`, { method: 'POST' }) } finally { asking.value.delete(f.id); await look() }
}
async function askAll() { await Promise.all(askable.value.map(ask)) }

async function look() {
  try {
    found.value = (await (await fetch('/bench/found', { cache: 'no-store' })).json()) as Found[]
  } catch { /* the box's service is restarting: the next look */ }
  looked.value = true
  if (found.value.some((f) => f.on && !bench.printers.some((p) => p.id === f.id))) await loadBench()   // one just joined
}
let timer = 0
onMounted(() => { void look(); timer = window.setInterval(look, 2000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.setup { min-height: 100dvh; box-sizing: border-box; padding: 22px 64px 32px; display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; justify-content: space-between; align-items: center; color: var(--a-ink-3); font-size: 22px; margin: 0 -24px 6px; }
.who { display: inline-flex; align-items: center; gap: 10px; }
.who i { width: 11px; height: 11px; border-radius: 50%; background: var(--a-green); box-shadow: 0 0 0 4px var(--a-tint-green); }
.who b { color: var(--a-ink); font-size: 17px; letter-spacing: .06em; text-transform: uppercase; }
.say { margin: 0; font-size: 52px; line-height: 1.04; letter-spacing: -.025em; }
.lead { margin: 0 0 12px; color: var(--a-ink-3); font-size: 22px; max-width: 52ch; }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.row { display: flex; align-items: center; gap: 20px; padding: 20px 26px; background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); }
.ico { width: 56px; height: 56px; border-radius: 16px; background: var(--a-surface-2); display: grid; place-items: center; color: var(--a-ink-2); flex: none; }
.ico svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; stroke-linecap: round; }
.t { flex: 1; display: grid; gap: 2px; min-width: 0; }
.t b { font-size: 26px; } .t span { color: var(--a-ink-3); font-size: 19px; }
.chip { display: inline-flex; align-items: center; gap: 7px; font-weight: 650; border-radius: 999px; padding: 6px 14px; font-size: 16px; background: var(--a-surface-2); color: var(--a-ink-2); white-space: nowrap; }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.chip.green { background: color-mix(in srgb, var(--a-green) 18%, transparent); color: var(--a-green-text); }
.row .a-btn { width: auto; flex: none; height: 52px; font-size: 20px; padding: 0 22px; }
.acts { display: flex; gap: 16px; margin-top: 16px; }
.acts .a-btn { width: auto; height: 68px; font-size: 24px; padding: 0 34px; text-decoration: none; display: inline-flex; align-items: center; }
@media (max-width: 599px) {
  .setup { padding: 14px 16px 24px; } .top { margin: 0 0 4px; }
  .say { font-size: 30px; } .lead { font-size: 16px; }
  .row { padding: 12px 14px; gap: 12px; } .ico { width: 40px; height: 40px; } .t b { font-size: 18px; } .t span { font-size: 14px; }
  .acts .a-btn { height: 52px; font-size: 18px; padding: 0 22px; }
}
</style>
