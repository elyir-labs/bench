<template>
  <!-- Measuring Happy Hare's gear inside Check and measure (design/unit-setup/, "Gear calibration", C with B's mark):
       boards gc-plan, gc-tradrack, gb-mark, gb-ruler, gb-pad, gb-done, gc-encoder, gb-phone, gc-phone -->
  <div class="gear" :class="['g-' + g.step, { failed }]">
    <div v-if="failed" class="body">
      <h1 class="a-display fh1">{{ uc.headline }}</h1>
      <p class="fd failed"><span class="mark q">!</span> {{ uc.detail }}</p>
      <div v-if="g.cards" class="chks"><GearCards :cards="g.cards" /></div>
    </div>

    <div v-else-if="g.step === 'plan'" class="body two">
      <div class="words">
        <h1 class="a-display fh1">{{ uc.headline }}</h1>
        <p v-if="uc.detail" class="fd">{{ uc.detail }}</p>
        <ol class="clist">
          <li v-for="(p, i) in g.plan" :key="p.title"><span class="num">{{ i + 1 }}</span><span>{{ p.title }}<small v-if="p.sub">{{ p.sub }}</small></span></li>
        </ol>
      </div>
      <div v-if="g.art === 'one_gear'" class="side-art">
        <div class="art one">
          <svg viewBox="0 0 270 180" aria-hidden="true">
            <rect x="30" y="98" width="210" height="44" rx="9" class="body-shape" />
            <g v-for="i in g.slots_n" :key="i">
              <line :x1="gx(i - 1)" :y1="i === 1 ? 28 : 34" :x2="gx(i - 1)" y2="86" :class="i === 1 ? 'gate on' : 'gate'" />
              <rect :x="gx(i - 1) - 7" y="84" width="14" height="14" rx="3" :class="i === 1 ? 'hole on' : 'hole'" />
            </g>
          </svg>
        </div>
        <p class="caption">The shared gear, behind all {{ g.slots_n }} slots.</p>
      </div>
      <div v-else-if="g.side" class="side"><b>{{ g.side.title }}</b><span>{{ g.side.text }}</span></div>
    </div>

    <div v-else-if="g.step === 'free' || g.step === 'mark'" class="body two">
      <div class="words">
        <h1 class="a-display fh1">{{ uc.headline }}</h1>
        <ol class="clist">
          <li v-for="(c, i) in checklist" :key="c.title" :class="c.state">
            <span class="num">{{ c.state === 'd' ? '✓' : i + 1 }}</span><span>{{ c.title }}<small>{{ c.sub }}</small></span>
          </li>
        </ol>
      </div>
      <div class="art outlet-art">
        <OutletArt :unit="uc.unit" tube-off :tip="g.pushed" :mark="g.step === 'mark' && !g.busy ? 1.5 : null"
                   :mark-label="g.step === 'mark' && !g.busy ? 'Your mark, at the edge' : ''" />
      </div>
    </div>

    <div v-else-if="g.step === 'ruler'" class="body">
      <h1 class="a-display fh1">{{ uc.headline }}</h1>
      <p v-if="uc.detail" class="fd small">{{ uc.detail }}</p>
      <div class="art wide">
        <OutletArt :unit="uc.unit" :tip="g.busy ? g.pushed + g.push : 118.5" :mark="98.5" :ruler="g.busy ? 0 : 120"
                   :zero="!g.busy" :read="!g.busy" :view="[0, 42, 440, 154]" />
      </div>
    </div>

    <div v-else-if="g.step === 'pad'" class="body two pad">
      <div class="words">
        <h1 class="a-display fh1">{{ uc.headline }}</h1>
        <p v-if="g.busy" class="fd small">{{ uc.detail }}</p>
        <div class="art phone-ruler">
          <OutletArt :unit="uc.unit" :tip="118.5" :mark="98.5" :ruler="120" zero read :view="[0, 42, 440, 154]" />
        </div>
        <div class="readout" :class="{ warn: outside }"><b>{{ typed || ' ' }}</b><i></i><span>mm</span></div>
        <div class="art small-ruler">
          <OutletArt :unit="uc.unit" :tip="118.5" :mark="98.5" :ruler="120" :view="[0, 78, 440, 84]" />
        </div>
      </div>
      <NumberPad class="pad-keys" :disabled="g.busy" @press="press" />
    </div>

    <div v-else-if="g.step === 'back'" class="body two">
      <div class="words">
        <h1 class="a-display fh1">{{ uc.headline }}</h1>
        <p class="fd">{{ uc.detail }}</p>
      </div>
      <div v-if="g.rows" class="sum">
        <div v-for="r in g.rows" :key="r.title"><b :class="{ amb: r.tone === 'amber' }">{{ r.title }}</b><span>{{ r.sub }}</span></div>
      </div>
    </div>

    <div v-else class="body">
      <h1 class="a-display fh1">{{ uc.headline }}</h1>
      <p class="fd small">{{ uc.detail }}</p>
      <div v-if="g.cards" class="chks"><GearCards :cards="g.cards" /></div>
    </div>

    <footer class="fbar">
      <span v-if="g.progress && !failed" class="t prog">
        <span class="bar"><i :style="{ width: prog.pct * 100 + '%' }"></i></span>
        <span>{{ prog.words }}<span class="then">. {{ g.progress.then }}</span></span>
      </span>
      <span v-else class="t">{{ note }}</span>
      <button v-for="b in buttons" :key="b.action.id + b.action.label" class="a-btn" :class="b.action.primary ? 'accent' : 'ghost'"
              :disabled="b.disabled || !!store.busyAction" @click="store.act(b.action)">
        {{ store.busyAction === b.action.id ? '…' : b.action.label }}
      </button>
    </footer>

    <div v-if="g.sheet" class="scrim" role="dialog" aria-modal="true" :aria-label="g.sheet.title">
      <div class="sheet">
        <p class="eb">{{ uc.unit }} · Slot 1 · The gear</p>
        <h2 class="a-display">{{ g.sheet.title }}</h2>
        <p class="detail">{{ g.sheet.text }}</p>
        <div class="sheet-bar">
          <button v-for="a in g.sheet.actions" :key="a.id" class="a-btn" :class="a.primary ? 'accent' : 'ghost'"
                  :disabled="!!store.busyAction" @click="sheetAct(a)">{{ a.label }}</button>
          <span v-if="g.sheet.note" class="note">{{ g.sheet.note }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentAction } from '@/intent/types'
import { gearButtons, gearChecklist, padNumber, padPress, progress, type GearView, type UnitCheckView } from '@/intent/unitCheck'
import GearCards from './GearCards.vue'
import NumberPad from './NumberPad.vue'
import OutletArt from './OutletArt.vue'

const props = defineProps<{ uc: UnitCheckView }>()
const store = useIntentStore()
const g = computed(() => props.uc.gear as GearView)
const failed = computed(() => props.uc.tone === 'failed')
const checklist = computed(() => gearChecklist(g.value))

// What's typed stays on the screen; it starts empty for each new push of 100 mm.
const typed = ref('')
watch(() => [g.value.tries, g.value.step], () => { typed.value = '' })
function press(k: string) { typed.value = padPress(typed.value, k) }
const outside = computed(() => {
  const mm = padNumber(typed.value)
  return mm != null && (mm < g.value.range[0] || mm > g.value.range[1])
})
function sheetAct(a: IntentAction) {
  if (a.id === 'unit_check_gear_type') typed.value = ''
  store.act(a)
}

const buttons = computed(() => gearButtons(props.uc, typed.value))
const note = computed(() => {
  if (failed.value) return ''
  if (g.value.step === 'free') return 'The tube goes back on at the end.'
  if (g.value.step === 'mark') return "No cutting. Where the tip ends up doesn't matter."
  if (g.value.step === 'ruler') return 'Hold the filament straight along the ruler.'
  if (g.value.step === 'pad') return `Bench expects ${g.value.range[0]} to ${g.value.range[1]} mm.`
  return ''
})

// one gear behind every gate (board gc-tradrack): gates spread across the body
const gx = (i: number) => 42 + (i * 186) / Math.max(1, g.value.slots_n - 1)

// The printer says how long the runs have gone each time it publishes; between those, count here.
const heardAt = ref(Date.now())
const nowMs = ref(Date.now())
watch(() => g.value.progress?.elapsed, () => { heardAt.value = Date.now() })
let timer = 0
onMounted(() => { timer = window.setInterval(() => { nowMs.value = Date.now() }, 500) })
onBeforeUnmount(() => window.clearInterval(timer))
const prog = computed(() => g.value.progress
  ? progress(g.value.progress, g.value.progress.elapsed == null ? 0 : Math.max(0, (nowMs.value - heardAt.value) / 1000))
  : { pct: 0, words: '' })
</script>

<style scoped>
.gear { flex: 1; min-height: 0; display: flex; flex-direction: column; position: relative; }
.body { flex: 1; min-height: 0; margin-top: 14px; }
.body.two { display: flex; gap: 24px; justify-content: space-between; align-items: flex-start; }
.words { flex: 0 1 390px; min-width: 0; }
.fh1 { font-size: 32px; line-height: 1.08; margin: 0; text-wrap: pretty; }
.fd { font-size: 19px; color: var(--a-ink-2); line-height: 1.35; margin: 8px 0 0; }
.fd.small { font-size: 18px; margin-top: 4px; }
.fd.failed { color: var(--a-ink); }
.mark.q { color: var(--a-amber-text); font-weight: 700; }

.clist { list-style: none; padding: 0; margin: 14px 0 0; display: grid; gap: 10px; }
.clist li { display: flex; gap: 12px; align-items: flex-start; font-size: 18px; color: var(--a-ink); line-height: 1.25; }
.clist li > span:last-child { display: grid; gap: 2px; }
.clist small { font-size: 14px; color: var(--a-ink-3); }
.num { flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font: 700 14px var(--a-display);
  background: color-mix(in srgb, var(--a-accent) 16%, transparent); color: var(--a-accent-text); margin-top: -1px; }
.clist li.d .num { background: var(--a-green, #1f9d55); color: #fff; }
.clist li.n .num { background: var(--a-accent); color: #fff; }

.side { flex: 0 0 290px; background: var(--a-surface); border-radius: 18px; padding: 16px 18px; box-shadow: var(--a-card-shadow); display: grid; gap: 6px; margin-top: 10px; }
.side b { font-size: 17px; }
.side span { font-size: 15px; color: var(--a-ink-2); line-height: 1.35; }

.art { border-radius: 22px; background: radial-gradient(circle at 50% 40%, var(--a-obj-hi, var(--a-surface)), var(--a-obj-lo, var(--a-surface-2))); overflow: hidden; }
.outlet-art { flex: 0 0 360px; height: 240px; display: grid; place-items: center; padding: 0 8px; box-sizing: border-box; }
.side-art { flex: 0 0 300px; }
.art.one { height: 200px; display: grid; place-items: center; }
.art.one svg { width: 270px; height: 180px; }
.body-shape { fill: var(--a-ink-3); opacity: 0.4; }
.gate { stroke: var(--a-ink-3); stroke-width: 2; opacity: 0.6; }
.gate.on { stroke: var(--a-accent); stroke-width: 3.5; opacity: 1; }
.hole { fill: var(--a-surface); stroke: var(--a-ink-3); stroke-width: 1; opacity: 0.8; }
.hole.on { stroke: var(--a-accent); stroke-width: 3; opacity: 1; }
.caption { margin: 10px 0 0; font-size: 15px; color: var(--a-ink-3); text-align: center; }
.art.wide { margin-top: 14px; height: 196px; display: grid; place-items: center; }
.art.wide :deep(svg) { width: 560px; max-width: 100%; height: auto; }

.pad .words { flex: 0 1 350px; }
.readout { margin-top: 14px; height: 74px; border-radius: 18px; background: var(--a-surface); border: 2px solid var(--a-accent); display: flex; align-items: center; gap: 6px; padding: 0 20px; box-sizing: border-box; }
.readout.warn { border-color: var(--a-amber); }
.readout b { font: 700 44px var(--a-display); letter-spacing: -0.5px; color: var(--a-ink); }
.readout i { width: 2.5px; height: 40px; background: var(--a-accent); border-radius: 2px; animation: caret 1.1s steps(1) infinite; }
.readout span { font-size: 20px; color: var(--a-ink-3); margin-left: 6px; }
@keyframes caret { 50% { opacity: 0; } }
.small-ruler { margin-top: 12px; height: 100px; border-radius: 16px; display: grid; place-items: center; }
.small-ruler :deep(svg) { width: 330px; height: auto; }
.phone-ruler { display: none; }
.pad-keys { flex: 0 0 330px; margin-top: 2px; }

.sum { flex: 0 0 370px; display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); }
.sum > div { background: var(--a-surface); padding: 11px 16px; display: grid; gap: 2px; }
.sum b { font-size: 16.5px; }
.sum b.amb { color: var(--a-amber-text); }
.sum span { font-size: 14px; color: var(--a-ink-3); line-height: 1.3; }

.chks { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.chks :deep(.chk) { padding: 8px 12px; gap: 3px; }
.failed .fd { font-size: 18px; }

.fbar { flex: none; display: flex; align-items: center; gap: 14px; min-height: 60px; margin-top: 10px; }
.fbar .t { flex: 1; min-width: 0; font-size: 16px; color: var(--a-ink-3); }
.fbar .prog { display: grid; gap: 8px; }
.then { display: none; }
.bar { display: block; width: 340px; max-width: 100%; height: 8px; border-radius: 4px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--a-accent); border-radius: 4px; transition: width 0.5s linear; }
.fbar .a-btn { flex: none; height: 60px; min-height: 60px; font-size: 21px; border-radius: 20px; padding: 0 30px; }

.scrim { position: fixed; inset: 0; background: rgba(8, 12, 20, 0.42); display: grid; place-items: center; z-index: 30; padding: 20px; }
.sheet { background: var(--a-surface); border-radius: 26px; padding: 26px 30px; max-width: 690px; width: 100%; box-sizing: border-box; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25); }
.sheet .eb { margin: 0 0 8px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
.sheet h2 { font-size: 31px; line-height: 1.1; margin: 0; }
.sheet .detail { font-size: 19px; color: var(--a-ink-2); line-height: 1.35; margin: 10px 0 20px; }
.sheet-bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.sheet-bar .a-btn { height: 56px; font-size: 19px; border-radius: 18px; padding: 0 24px; }
.sheet-bar .note { margin-left: auto; font-size: 15px; color: var(--a-ink-3); max-width: 190px; line-height: 1.3; }

@media (max-width: 599px) {
  .body { margin-top: 18px; }
  .body.two { flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 18px; }
  .words, .pad .words { flex: none; }
  .fh1 { font-size: 28px; }
  .fd { font-size: 17px; }
  .side, .sum, .side-art, .outlet-art { flex: none; }
  .outlet-art { height: auto; aspect-ratio: 3 / 2; }
  .side-art .art.one { height: auto; aspect-ratio: 3 / 2; }
  .art.wide { height: auto; }
  .chks { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pad.body.two { gap: 14px; }
  .phone-ruler { display: grid; place-items: center; margin-top: 14px; height: 124px; border-radius: 18px; }
  .phone-ruler :deep(svg) { width: 100%; height: auto; }
  .small-ruler { display: none; }
  .pad-keys { flex: none; }
  .then { display: inline; }
  .fbar { flex-wrap: wrap; }
  .fbar .t { flex: 1 1 100%; font-size: 15px; }
  .fbar .a-btn { flex: 1 1 0; height: 56px; min-height: 56px; font-size: 18px; padding: 0 16px; }
  .bar { width: 100%; }
  .sheet { padding: 22px 20px; }
  .sheet h2 { font-size: 26px; }
  .sheet-bar .a-btn { flex: 1 1 0; }
  .sheet-bar .note { flex: 1 1 100%; max-width: none; margin-left: 0; }
}
</style>
