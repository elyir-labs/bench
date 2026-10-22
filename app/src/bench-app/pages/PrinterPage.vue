<template>
  <!-- A printer, opened on the box (design/bench-box/, D): its own screens in bench chrome, laid out for the
       box, under one top row (the other printers a tap away) and its sections as a row under its name. -->
  <section class="printer" :class="{ away: here.away }">
    <header class="top">
      <router-link to="/" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>Bench</router-link>
      <nav class="switch" aria-label="Printers">
        <router-link v-for="t in on" :key="t.id" :to="`/p/${t.id}`" class="chip" :class="['tone-' + t.tone, { here: t.id === id }]"><i></i>{{ t.name }}</router-link>
        <span v-if="offCount" class="more">+ {{ offCount }} off</span>
      </nav>
      <AwayChip v-if="here.away" class="end" />
      <span v-else class="clock a-num">{{ clock }}</span>
    </header>
    <div class="sub" v-if="p">
      <span class="who"><i :class="'tone-' + tile?.tone"></i><b>{{ p.name }}</b> · {{ tile?.word }}</span>
      <div class="seg" role="tablist" aria-label="Sections">
        <button v-for="a in AREAS" :key="a.path" role="tab" :aria-selected="area === a.path" :class="{ on: area === a.path }" @click="go(a.path)">{{ a.label }}</button>
      </div>
      <Vitals v-if="p.intent" :intent="p.intent" class="vit" />
    </div>
    <iframe v-if="src" ref="frame" :key="p!.id" :src="src" class="frame" :title="p!.name" allow="local-network-access; fullscreen"></iframe>
    <p v-else-if="p" class="gone">{{ p.name }} isn't answering. It may be off.</p>
    <p v-else class="gone">That printer isn't on this bench.</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Vitals from '@/components/now/Vitals.vue'
import { theme } from '@/theme'
import { bench } from '../live'
import { ordered, tileOf } from '../bench'
import { here } from '../here'
import AwayChip from './AwayChip.vue'

// away, a printer's Print isn't offered (printing a model starts at home), so its section isn't either
const AREAS = [{ path: '/', label: 'Now' }, { path: '/print', label: 'Print' }, { path: '/materials', label: 'Materials' }, { path: '/care', label: 'Care' }]
  .filter((a) => !here.away || a.path !== '/print')
const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))
const p = computed(() => bench.printers.find((x) => x.id === id.value) ?? null)
const tile = computed(() => (p.value ? tileOf(p.value) : null))
const tiles = computed(() => ordered(bench.printers))
const on = computed(() => tiles.value.filter((t) => t.tone !== 'off'))
const offCount = computed(() => tiles.value.length - on.value.length)
const area = ref('/' + String(route.params.area ?? ''))
const frame = ref<HTMLIFrameElement | null>(null)

// the frame's own address, opened where the bench asked (a tile's Print a model opens Print)
const start = ref(area.value)
watch(id, () => { start.value = area.value })
const src = computed(() => {
  const r = p.value?.record
  if (!r || !p.value?.live) return null
  // on a real box the printer's own app talks to its own Moonraker; in dev one app draws every simulator
  const dev = /^https?:/.test(r.moonraker) ? (() => { const m = new URL(r.moonraker); return `&printer=${m.hostname}:${m.port || 80}` })() : ''
  return `${r.app}${start.value === '/' ? '/' : start.value}?embed=1&chrome=bench&theme=${theme.value}${dev}`
})

function go(path: string) {
  area.value = path
  frame.value?.contentWindow?.postMessage({ type: 'elyir-bench:navigate', path }, new URL(p.value!.record.app).origin)
}

// the frame asks for its access (the door's token for this box; '' for a printer reached without a door),
// and says where it is, so the sections follow it
function onMessage(ev: MessageEvent) {
  if (!p.value || ev.source !== frame.value?.contentWindow || ev.origin !== new URL(p.value.record.app).origin) return
  if (ev.data?.type === 'elyir-bench:ready') frame.value!.contentWindow!.postMessage({ type: 'elyir-bench:token', token: p.value.record.token ?? '' }, ev.origin)
  if (ev.data?.type === 'elyir-bench:path' && typeof ev.data.path === 'string') {
    const here = AREAS.find((a) => a.path !== '/' && ev.data.path.startsWith(a.path))?.path ?? '/'
    area.value = here
  }
}
onMounted(() => window.addEventListener('message', onMessage))
onBeforeUnmount(() => window.removeEventListener('message', onMessage))

const clock = ref('')
const tick = () => { clock.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase() }
tick()
const timer = window.setInterval(tick, 10000)
onBeforeUnmount(() => window.clearInterval(timer))
void router
</script>

<style scoped>
.printer { height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto auto minmax(0, 1fr); box-sizing: border-box; padding: 16px 0 0; }
.top { display: flex; align-items: center; gap: 18px; padding: 0 40px 0 32px; }
.back { display: inline-flex; align-items: center; gap: 6px; height: 46px; padding: 0 18px 0 12px; border-radius: 999px; background: var(--a-surface); border: 1px solid var(--a-line); color: var(--a-ink-2); font-weight: 650; font-size: 18px; text-decoration: none; flex: none; }
.back svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.switch { display: flex; gap: 8px; align-items: center; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.chip { display: inline-flex; align-items: center; gap: 7px; font-weight: 650; border-radius: 999px; padding: 7px 14px; font-size: 16px; white-space: nowrap; background: var(--a-surface); color: var(--a-ink-2); text-decoration: none; }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: var(--a-accent); }
.chip.tone-amber i { background: var(--a-amber); } .chip.tone-red i { background: var(--a-red); } .chip.tone-green i { background: var(--a-green); }
.chip.here { background: var(--a-ink); color: var(--a-bg); }
.more { color: var(--a-ink-3); font-size: 15px; white-space: nowrap; }
.clock { margin-left: auto; flex: none; white-space: nowrap; color: var(--a-ink-3); font-size: 21px; }
.end { margin-left: auto; flex: none; }
.sub { display: flex; align-items: center; gap: 22px; padding: 14px 40px 0; }
.who { display: inline-flex; align-items: center; gap: 10px; font-size: 22px; color: var(--a-ink-3); white-space: nowrap; }
.who b { color: var(--a-ink); letter-spacing: .04em; }
.who i { width: 11px; height: 11px; border-radius: 50%; background: var(--a-accent); }
.who i.tone-amber { background: var(--a-amber); } .who i.tone-red { background: var(--a-red); } .who i.tone-green { background: var(--a-green); }
.seg { display: inline-flex; background: var(--a-surface-2); border-radius: 999px; padding: 4px; }
.seg button { appearance: none; border: 0; background: none; font: inherit; padding: 8px 22px; border-radius: 999px; font-size: 18px; font-weight: 650; color: var(--a-ink-3); cursor: pointer; }
.seg button.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.vit { margin-left: auto; }
.frame { width: 100%; height: 100%; border: 0; display: block; background: var(--a-bg); }
.gone { padding: 40px; color: var(--a-ink-3); font-size: 22px; }
@media (max-height: 540px) and (min-width: 600px) {
  .printer { padding-top: 8px; }
  .top { padding: 0 20px 0 16px; gap: 12px; }
  .back { height: 40px; padding: 0 14px 0 8px; font-size: 16px; }
  .chip { padding: 5px 11px; font-size: 14px; }
  .more { font-size: 13px; }
  .clock { font-size: 17px; }
  .sub { padding: 8px 20px 0; gap: 14px; }
  .who { font-size: 18px; }
  .seg button { padding: 6px 14px; font-size: 15px; }
  .gone { padding: 24px; font-size: 18px; }
}
@media (max-width: 599px) {
  .top { padding: 0 12px; gap: 10px; } .clock { display: none; }
  .away .switch { display: none; }
  .sub { padding: 10px 12px 0; gap: 10px; flex-wrap: wrap; } .vit { display: none; }
  .seg button { padding: 6px 12px; font-size: 15px; }
}
</style>
