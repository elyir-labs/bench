<template>
  <!-- A printer, opened on the box (design/bench-7in/, A): its own screens in bench chrome under one top line (back to the
       bench, its name to switch printers, the other printer that needs you), and one bar at the bottom: its sections. -->
  <section class="printer" :class="{ away: here.away }">
    <header class="top">
      <router-link to="/" class="pill back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>Bench</router-link>
      <button v-if="p" type="button" class="pill who" :aria-expanded="switching" aria-haspopup="dialog" @click="switching = !switching">
        <i :class="'tone-' + tile?.tone"></i><b>{{ p.name }}</b><span class="word">· {{ tile?.word }}</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      <router-link v-if="need && !here.away" :to="`/p/${need.id}`" class="pill need" :class="'tone-' + need.tone"><i></i>{{ need.label }}</router-link>
      <AwayChip v-if="here.away" class="end" />
      <span v-else class="clock a-num">{{ clock }}</span>
    </header>
    <iframe v-if="src" ref="frame" :key="p!.id" :src="src" class="frame" :title="p!.name" allow="local-network-access; fullscreen"></iframe>
    <p v-else-if="p" class="gone">{{ p.name }} isn't answering. It may be off.</p>
    <p v-else class="gone">That printer isn't on this bench.</p>
    <TabBar :items="sections" :label="`${p?.name ?? 'Printer'} sections`" @pick="go" />

    <div v-if="switching" class="scrim" @click="switching = false"></div>
    <div v-if="switching" class="switch" role="dialog" aria-label="Printers">
      <router-link v-for="t in tiles" :key="t.id" :to="`/p/${t.id}`" class="row" :class="{ here: t.id === id, off: t.tone === 'off' }" @click="switching = false">
        <i :class="'tone-' + t.tone"></i><b>{{ t.name }}</b><span class="says">{{ t.tone === 'off' ? 'Off' : t.rank <= 2 ? tileLine(t) : `${t.word} · ${tileLine(t)}` }}</span>
        <span v-if="t.rank === 3 && t.frac" class="bar"><span :style="{ width: Math.round(t.frac * 100) + '%' }"></span></span>
      </router-link>
    </div>
  </section>
</template>

<script setup lang="ts">
import { updateDot } from '@/intent/update'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { theme } from '@/theme'
import { bench } from '../live'
import { needChip, ordered, tileLine, tileOf } from '../bench'
import { here } from '../here'
import AwayChip from './AwayChip.vue'
import TabBar, { type TabItem } from './TabBar.vue'

// away, a printer's Print isn't offered (printing a model starts at home), so its section isn't either
const AREAS = ([{ path: '/', label: 'Now', icon: 'now' }, { path: '/print', label: 'Print', icon: 'print' },
  { path: '/materials', label: 'Materials', icon: 'materials' }, { path: '/care', label: 'Care', icon: 'care' }] as const)
  .filter((a) => !here.away || a.path !== '/print')
const route = useRoute()
const id = computed(() => String(route.params.id))
const p = computed(() => bench.printers.find((x) => x.id === id.value) ?? null)
const tile = computed(() => (p.value ? tileOf(p.value) : null))
const tiles = computed(() => ordered(bench.printers))
const need = computed(() => needChip(tiles.value, id.value))
const area = ref('/' + String(route.params.area ?? ''))
const frame = ref<HTMLIFrameElement | null>(null)
const switching = ref(false)
const careDot = computed(() => updateDot(p.value?.intent?.update))
const sections = computed<TabItem[]>(() => AREAS.map((a) => ({ key: a.path, label: a.label, icon: a.icon, on: area.value === a.path,
  dot: a.path === '/care' && careDot.value })))

// the frame's own address, opened where the bench asked (a tile's Print a model opens Print)
const start = ref(area.value)
watch(id, () => { start.value = area.value; switching.value = false })
const src = computed(() => {
  const r = p.value?.record
  if (!r || !p.value?.live) return null
  // on a real box the printer's own app talks to its own Moonraker; in dev one app draws every simulator
  const dev = /^https?:/.test(r.moonraker) ? (() => { const m = new URL(r.moonraker); return `&printer=${m.hostname}:${m.port || 80}` })() : ''
  return `${r.app}${start.value === '/' ? '/' : start.value}?embed=1&chrome=bench&theme=${theme.value}${dev}`
})

// A tap before the frame listens (it waits for its access first, seconds on a Pi) would be lost: the tab lit, the page
// unchanged. So the section is kept here and sent once the frame says it's listening, and again if it shows another.
const listening = ref(false)
const shown = ref<string | null>(null)
watch(src, () => { listening.value = false; shown.value = null })
function send(path: string) {
  if (p.value && listening.value) frame.value?.contentWindow?.postMessage({ type: 'elyir-bench:navigate', path }, new URL(p.value.record.app).origin)
}
function go(path: string) {
  area.value = path
  send(path)
}

// the frame asks for its access (the door's token for this box; '' for a printer reached without a door),
// and says where it is, so the sections follow it
function onMessage(ev: MessageEvent) {
  if (!p.value || ev.source !== frame.value?.contentWindow || ev.origin !== new URL(p.value.record.app).origin) return
  if (ev.data?.type === 'elyir-bench:ready') frame.value!.contentWindow!.postMessage({ type: 'elyir-bench:token', token: p.value.record.token ?? '' }, ev.origin)
  if (ev.data?.type === 'elyir-bench:listening') {
    listening.value = true
    if (shown.value !== area.value) send(area.value)
  }
  if (ev.data?.type === 'elyir-bench:path' && typeof ev.data.path === 'string') {
    shown.value = AREAS.find((a) => a.path !== '/' && ev.data.path.startsWith(a.path))?.path ?? '/'
    area.value = shown.value
  }
}
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') switching.value = false }
onMounted(() => { window.addEventListener('message', onMessage); window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { window.removeEventListener('message', onMessage); window.removeEventListener('keydown', onKey) })

const clock = ref('')
const tick = () => { clock.value = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase() }
tick()
const timer = window.setInterval(tick, 10000)
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.printer { position: relative; height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr) auto; box-sizing: border-box; }
.top { display: flex; align-items: center; gap: 12px; padding: 14px 32px 6px; min-width: 0; }
.pill { display: inline-flex; align-items: center; gap: 8px; height: 50px; padding: 0 18px; border-radius: 999px; background: var(--a-surface); border: 1px solid var(--a-line);
        color: var(--a-ink); font: inherit; font-size: 19px; font-weight: 650; text-decoration: none; white-space: nowrap; cursor: pointer; flex: none; }
.pill svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; flex: none; }
.back { color: var(--a-ink-2); padding-left: 12px; }
.who { min-width: 0; flex: 0 1 auto; }
.who b { overflow: hidden; text-overflow: ellipsis; }
.who .word { color: var(--a-ink-3); font-weight: 500; }
.who svg { color: var(--a-ink-3); }
i { width: 10px; height: 10px; border-radius: 50%; background: var(--a-accent); flex: none; }
i.tone-amber { background: var(--a-amber); } i.tone-red { background: var(--a-red); } i.tone-green { background: var(--a-green); } i.tone-off { background: var(--a-ink-3); }
.need { min-width: 0; flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; background: color-mix(in srgb, var(--a-amber) 14%, transparent);
        border-color: color-mix(in srgb, var(--a-amber) 45%, transparent); color: var(--a-amber-text); }
.need.tone-red { background: color-mix(in srgb, var(--a-red) 14%, transparent); border-color: color-mix(in srgb, var(--a-red) 45%, transparent); color: var(--a-red-text); }
.need i { background: currentColor; }
.clock { margin-left: auto; flex: none; white-space: nowrap; color: var(--a-ink-3); font-size: 21px; }
.end { margin-left: auto; flex: none; }
.frame { width: 100%; height: 100%; border: 0; display: block; background: var(--a-bg); }
.gone { padding: 40px; color: var(--a-ink-3); font-size: 22px; margin: 0; }

.scrim { position: absolute; inset: 0; background: rgba(0, 0, 0, .5); z-index: 5; }
.switch { position: absolute; z-index: 6; top: 72px; left: 140px; width: min(560px, calc(100% - 32px)); max-height: calc(100% - 160px); overflow: auto;
          background: var(--a-surface); border: 1px solid var(--a-line); border-radius: 20px; padding: 8px; box-shadow: 0 18px 50px rgba(0, 0, 0, .5); }
.row { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 0 14px; border-radius: 14px; color: var(--a-ink); text-decoration: none; }
.row.here { background: var(--a-surface-2); }
.row.off { color: var(--a-ink-3); }
.row b { font-size: 19px; width: 140px; flex: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.says { flex: 1; min-width: 0; color: var(--a-ink-2); font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { width: 70px; height: 6px; border-radius: 3px; background: var(--a-bg); overflow: hidden; flex: none; }
.bar span { display: block; height: 100%; background: var(--a-accent); border-radius: 3px; }

@media (max-height: 540px) and (min-width: 600px) {
  .top { padding: 8px 16px 4px; gap: 10px; }
  .pill { height: 44px; padding: 0 14px; font-size: 16px; gap: 7px; }
  .back { padding-left: 9px; }
  .pill svg { width: 17px; height: 17px; }
  .clock { font-size: 17px; }
  .switch { top: 58px; left: 100px; max-height: calc(100% - 130px); }
  .row { min-height: 50px; } .row b { font-size: 17px; width: 120px; } .says { font-size: 15px; }
  .gone { padding: 24px; font-size: 18px; }
}
@media (max-width: 599px) {
  .top { padding: 10px 12px 4px; gap: 8px; }
  .pill { height: 42px; padding: 0 12px; font-size: 15px; }
  .need, .clock, .who .word { display: none; }
  .switch { left: 12px; right: 12px; width: auto; top: 60px; }
  .row b { width: 110px; }
}
</style>
