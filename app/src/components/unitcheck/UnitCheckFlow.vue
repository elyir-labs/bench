<template>
  <!-- Check and measure a Happy Hare or AFC unit (design/unit-setup/, B, stage 1): boards b-test, a-measure, b-ready -->
  <section class="flow" :class="'step-' + uc.step" aria-live="polite">
    <header class="fhead">
      <button class="back" :disabled="!back || !!store.busyAction" :aria-label="uc.step === 'ready' ? 'Done' : 'Stop checking'" @click="back && act(back)">
        <svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <span class="where">{{ FLOW_TITLE }} · {{ uc.unit }}</span>
      <span class="step a-num">{{ stepLabel(uc) }}<span class="dots" aria-hidden="true"><i v-for="(d, i) in dots(uc)" :key="i" :class="d"></i></span></span>
    </header>

    <div v-if="uc.step === 'slots'" class="body">
      <h1 class="a-display fh1">{{ uc.headline }}</h1>
      <p v-if="uc.detail" class="fd small" :class="uc.tone">
        <span v-if="uc.tone === 'ok'" class="mark ok">✓</span><span v-else-if="uc.tone === 'failed'" class="mark q">!</span>
        {{ uc.detail }}
      </p>
      <div class="chks">
        <div v-for="c in uc.slots" :key="c.slot" class="chk" :class="cardClass(c)">
          <span class="h"><span class="sw" :class="{ empty: c.state === 'next' || c.state === 'skipped' }"></span>{{ c.label }}</span>
          <span v-for="(l, i) in cardLines(c)" :key="i" class="l">
            <span v-if="l.mark === 'y'" class="y">✓</span><span v-else-if="l.mark === 'q'" class="q">!</span><span v-else-if="l.mark === 'spin'" class="spin"></span>{{ l.text }}
          </span>
        </div>
      </div>
    </div>

    <div v-else-if="uc.step === 'measure'" class="body two">
      <div class="words">
        <h1 class="a-display fh1">{{ uc.headline }}</h1>
        <p class="fd" :class="uc.tone">{{ uc.detail }}</p>
        <p v-if="uc.measure && !failed" class="fd quiet">{{ uc.measure.note }}</p>
      </div>
      <div class="art" aria-hidden="true">
        <svg viewBox="0 0 340 230">
          <path :d="TUBE" fill="none" stroke="var(--a-surface-2)" stroke-width="10" stroke-linecap="round" />
          <path :d="TUBE" pathLength="100" fill="none" stroke="var(--a-accent)" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="`${pct * 100} 200`" />
          <circle v-if="!failed" :cx="dot[0]" :cy="dot[1]" r="9" fill="#fff" stroke="var(--a-accent)" stroke-width="4" />
          <rect x="30" y="186" width="80" height="26" rx="6" fill="var(--a-ink-3)" opacity=".5" />
          <text x="70" y="226" text-anchor="middle" class="lbl">{{ uc.unit }}</text>
          <template v-if="uc.measure?.what === 'slot'">
            <rect x="248" y="50" width="52" height="40" rx="10" fill="var(--a-ink-3)" opacity=".55" />
            <text x="274" y="112" text-anchor="middle" class="lbl">The hub</text>
          </template>
          <template v-else>
            <rect x="252" y="58" width="44" height="54" rx="8" fill="var(--a-ink-3)" opacity=".55" />
            <path d="M266 112h16l-5 12h-6z" fill="#c9a24a" />
            <text x="274" y="146" text-anchor="middle" class="lbl">The head</text>
          </template>
          <text v-if="uc.measure" x="215" y="205" text-anchor="middle" class="big">With slot {{ uc.measure.slot + 1 }}</text>
        </svg>
      </div>
    </div>

    <div v-else class="body two ready">
      <div class="words">
        <h1 class="a-display fh1" :class="{ huge: uc.headline.length <= 16 }">{{ uc.headline }}</h1>
        <p class="fd">{{ uc.detail }}</p>
      </div>
      <div class="sum">
        <div v-for="r in uc.ready?.rows ?? []" :key="r.title"><b>{{ r.title }}</b><span>{{ r.sub }}</span></div>
      </div>
    </div>

    <footer class="fbar">
      <span v-if="uc.step === 'measure' && uc.measure && !failed" class="t prog">
        <span class="bar"><i :style="{ width: pct * 100 + '%' }"></i></span>{{ prog.words }}
      </span>
      <span v-else class="t">{{ uc.note }}</span>
      <button
        v-for="a in barButtons(uc)" :key="a.id + a.label" class="a-btn" :class="a.primary ? 'accent' : 'ghost'"
        :disabled="!!store.busyAction" @click="act(a)"
      >{{ store.busyAction === a.id ? '…' : a.label }}</button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { IntentAction } from '@/intent/types'
import {
  FLOW_TITLE, backAction, barButtons, cardLines, dots, progress, stepLabel,
  type UnitCheckCard, type UnitCheckView,
} from '@/intent/unitCheck'

const props = defineProps<{ uc: UnitCheckView }>()
const store = useIntentStore()
const router = useRouter()

const back = computed(() => backAction(props.uc))
const failed = computed(() => props.uc.tone === 'failed')

// The printer says how long measuring has been going each time it publishes; between those, count here.
const heardAt = ref(Date.now())
const nowMs = ref(Date.now())
watch(() => props.uc.measure?.elapsed, () => { heardAt.value = Date.now() })
let timer = 0
onMounted(() => { timer = window.setInterval(() => { nowMs.value = Date.now() }, 500) })
onBeforeUnmount(() => window.clearInterval(timer))
const prog = computed(() => props.uc.measure
  ? progress(props.uc.measure, Math.max(0, (nowMs.value - heardAt.value) / 1000))
  : { pct: 0, words: '' })
const pct = computed(() => (failed.value ? 0 : prog.value.pct))

// The tube from the unit up to the head (board a-measure), and the filament's tip along it
const TUBE = 'M70 190 C 70 60, 200 30, 270 70'
const dot = computed(() => {
  const t = pct.value, u = 1 - t
  const p = [[70, 190], [70, 60], [200, 30], [270, 70]]
  const w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t]
  return [0, 1].map((k) => w.reduce((s, wi, i) => s + wi * p[i][k], 0))
})

function cardClass(c: UnitCheckCard): string {
  return { waiting: 'now', testing: 'now', failed: 'warn', next: 'next', skipped: 'next', ok: '' }[c.state]
}

async function act(a: IntentAction) {
  await store.act(a)
  if (!store.actionError && a.args?.then === 'materials') router.push('/materials')
}
</script>

<style scoped>
.flow { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: calc(6 * var(--u) + 2px) 36px 22px; overflow: auto; }
.fhead { display: flex; align-items: center; gap: 12px; height: 38px; flex: none; }
.back { appearance: none; border: 0; width: 38px; height: 38px; border-radius: 50%; background: var(--a-surface); box-shadow: var(--a-card-shadow); display: grid; place-items: center; flex: none; color: var(--a-ink-2); cursor: pointer; padding: 0; }
.back svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.back[disabled] { opacity: 0.4; cursor: default; }
.where { font-size: 16px; font-weight: 600; color: var(--a-ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.step { margin-left: auto; display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; }
.dots { display: flex; gap: 5px; }
.dots i { width: 8px; height: 8px; border-radius: 50%; background: var(--a-surface-2); }
.dots i.d { background: var(--a-accent); }
.dots i.n { background: var(--a-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--a-accent) 22%, transparent); }

.body { flex: 1; min-height: 0; margin-top: 14px; }
.body.two { display: flex; gap: 24px; justify-content: space-between; align-items: flex-start; }
.words { flex: 0 1 370px; min-width: 0; }
.fh1 { font-size: 32px; line-height: 1.08; margin: 0; text-wrap: pretty; }
.fh1.huge { font-size: 44px; }
.fd { font-size: 19px; color: var(--a-ink-2); line-height: 1.35; margin: 8px 0 0; }
.fd.small { font-size: 18px; margin-top: 4px; }
.fd.quiet { font-size: 16px; color: var(--a-ink-3); }
.fd.failed { color: var(--a-ink); }
.mark { font-weight: 700; }
.mark.ok, .y { color: var(--a-green-text); }
.mark.q, .q { color: var(--a-amber-text); }

.chks { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.chk { background: var(--a-surface); border-radius: 16px; padding: 10px 12px; display: grid; gap: 5px; align-content: start; box-shadow: var(--a-card-shadow); border: 2px solid transparent; min-height: 60px; }
.chk.now { border-color: var(--a-accent); }
.chk.warn { border-color: var(--a-amber); }
.chk.next { background: transparent; box-shadow: none; border: 1.5px dashed var(--a-line); }
.h { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; }
.sw { width: 20px; height: 20px; border-radius: 50%; background: var(--a-ink-3); border: 2px solid var(--a-swatch-edge); box-sizing: border-box; flex: none; }
.sw.empty { background: transparent; border-style: dashed; border-color: var(--a-swatch-empty); }
.l { font-size: 13.5px; color: var(--a-ink-3); display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.l .y, .l .q { font-weight: 700; }
.spin { width: 14px; height: 14px; border-radius: 50%; border: 2.5px solid var(--a-surface-2); border-top-color: var(--a-accent); flex: none; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.art { flex: none; width: 340px; height: 230px; border-radius: 22px; background: radial-gradient(circle at 50% 40%, var(--a-obj-hi, var(--a-surface)), var(--a-obj-lo, var(--a-surface-2))); }
.art svg { width: 100%; height: 100%; display: block; }
.art .lbl { font-size: 13px; font-weight: 600; fill: var(--a-ink-3); font-family: var(--a-display); }
.art .big { font-size: 22px; font-weight: 700; fill: var(--a-ink); font-family: var(--a-display); }

.sum { flex: 0 0 360px; display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); }
.sum > div { background: var(--a-surface); padding: 11px 16px; display: grid; gap: 2px; }
.sum b { font-size: 16.5px; }
.sum span { font-size: 14px; color: var(--a-ink-3); line-height: 1.3; }

.fbar { flex: none; display: flex; align-items: center; gap: 14px; min-height: 60px; margin-top: 10px; }
.fbar .t { flex: 1; min-width: 0; font-size: 16px; color: var(--a-ink-3); }
.fbar .prog { display: grid; gap: 8px; }
.bar { display: block; width: 300px; max-width: 100%; height: 8px; border-radius: 4px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--a-accent); border-radius: 4px; transition: width 0.5s linear; }
.fbar .a-btn { flex: none; height: 60px; min-height: 60px; font-size: 21px; border-radius: 20px; padding: 0 30px; }

/* Phones: one column, the buttons across the bottom */
@media (max-width: 599px) {
  .flow { padding: 8px 20px calc(16px + env(safe-area-inset-bottom, 0px)); }
  .fhead { gap: 10px; }
  .where { font-size: 15px; }
  .step { font-size: 14px; }
  .body { margin-top: 18px; }
  .body.two { flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 20px; }
  .words { flex: none; }
  .fh1 { font-size: 28px; }
  .fh1.huge { font-size: 36px; }
  .fd { font-size: 17px; }
  .chks { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .art { width: 100%; height: auto; aspect-ratio: 340 / 230; }
  .sum { flex: none; }
  .fbar { flex-wrap: wrap; }
  .fbar .t { flex: 1 1 100%; font-size: 15px; }
  .fbar .a-btn { flex: 1 1 0; height: 56px; min-height: 56px; font-size: 18px; padding: 0 16px; }
  .bar { width: 100%; }
}
</style>
