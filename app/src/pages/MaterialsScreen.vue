<template>
  <section class="materials" :class="{ away: door.away }">
    <div class="head" v-if="!one">
      <h1 class="a-display title">Materials</h1>
      <span class="head-right" v-if="!one">
        <span class="sub a-num" v-if="spools.length">{{ loaded.length }} of {{ spools.length }} slots loaded</span>
        <button
          v-if="lookAgain && !units?.missing && !door.away"
          class="a-btn ghost look"
          :disabled="store.busy || !!store.busyAction"
          @click="store.act(lookAgain)"
        >{{ lookAgain.label }}</button>
      </span>
    </div>

    <div v-if="head?.notice" class="notice head" role="status">
      <div class="notice-words">
        <b>{{ head.notice.headline }}</b>
        <span>{{ head.notice.detail }}</span>
      </div>
      <template v-if="!door.away">
      <div v-if="head.choices.length" class="choices">
        <button
          v-for="c in head.choices"
          :key="String(c.args?.slot)"
          class="choice"
          :disabled="!!store.busyAction"
          @click="store.act(c)"
        ><span class="dot" :style="{ '--c': colorOf(Number(c.args?.slot)) }"></span>{{ c.label }}</button>
      </div>
      <div v-else class="head-actions">
        <button
          v-for="a in head.actions"
          :key="a.id"
          class="a-btn"
          :class="a.primary ? 'amber' : 'ghost'"
          :disabled="!!store.busyAction"
          @click="store.act(a)"
        >{{ store.busyAction === a.id ? '…' : a.label }}</button>
      </div>
      </template>
    </div>

    <div v-if="units?.notice" class="notice" role="status">
      <div class="notice-words">
        <b>{{ units.notice.headline }}</b>
        <span>{{ units.notice.detail }}</span>
      </div>
      <button v-if="lookAgain && !door.away" class="a-btn amber" :disabled="store.busy || !!store.busyAction" @click="store.act(lookAgain)">
        {{ store.busyAction === lookAgain.id ? '…' : lookAgain.label }}
      </button>
    </div>

    <BusyBanner then="swap spools" />
    <!-- No filament unit: one spool, and the spool is the page -->
    <OneSpool v-if="one" :spool="one" :feeding="feeding" />
    <template v-else>
    <p class="sub away" v-if="door.away">Load, switch and edit spools at the printer.</p>
    <p class="sub" v-if="!spools.length">No filament unit found. Spools will appear here when one is connected.</p>

    <!-- An untagged spool was pushed into an empty slot: ask once (design/slots/, B) -->
    <div v-if="newSpool && !door.away" class="notice head" role="status">
      <div class="notice-words">
        <b>{{ newSpool.headline }}</b>
        <span>{{ newSpool.detail }}</span>
      </div>
      <div class="choices">
        <button
          v-for="c in newSpool.choices"
          :key="c.label"
          class="choice"
          :disabled="!!store.busyAction"
          @click="store.act(c)"
        ><span class="dot" :style="{ '--c': (c.args?.color as string) || 'transparent' }"></span>{{ c.label }}</button>
        <button class="choice plain" @click="openEdit(newSpool.slot)">Something else</button>
      </div>
    </div>

    <!-- Each unit is a thing on the shelf: its line (temperature, Dry or drying), then its slots -->
    <div v-for="g in groups" :key="g.unit?.index ?? 'all'" class="unit">
      <div v-if="g.unit" class="uh">
        <b class="uname">{{ g.unit.name }}</b>
        <template v-if="g.unit.drying">
          <i class="drydot" aria-hidden="true"></i>
          <span class="drying a-num">Drying · {{ g.unit.drying.target }}° · {{ minutes(g.unit.drying.minutes_left) }} left</span>
          <span class="drybar" aria-hidden="true"><i :style="{ width: dryPct(g.unit) + '%' }"></i></span>
        </template>
        <span v-else-if="!g.unit.connected">Not connected</span>
        <span v-else-if="g.unit.temp != null" class="a-num">{{ g.unit.temp }}°</span>
        <span class="spacer"></span>
        <!-- Happy Hare or AFC: check each slot and measure the tube (design/unit-setup/, B) -->
        <button
          v-if="g.unit.check && !door.away"
          class="a-btn ghost unitbtn"
          :disabled="!!g.unit.check.why || !!store.busyAction"
          :title="g.unit.check.why ?? undefined"
          @click="store.act(g.unit.check.action)"
        >{{ store.busyAction === 'unit_check_start' ? '…' : g.unit.check.action.label }}</button>
        <button
          v-if="g.unit.actions.length && !door.away"
          class="a-btn ghost unitbtn"
          :disabled="!!store.busyAction"
          @click="g.unit.drying ? store.act(g.unit.actions[0]) : (dryingUnit = g.unit)"
        >{{ store.busyAction === 'stop_drying' && g.unit.drying ? '…' : (g.unit.drying ? 'Stop' : 'Dry') }}</button>
      </div>
      <div class="grid">
        <button
          v-for="s in g.spools"
          :key="s.slot"
          class="slot"
          :class="[s.status, { inuse: s.in_use, asked: newSpool?.slot === s.slot }]"
          :disabled="door.away"
          :aria-label="`Slot ${s.slot + 1}: ${nameOf(s)}`"
          @click="open(s)"
        >
          <span class="swatch" :class="{ 'a-spool-ring': s.in_use, turning: s.in_use && feeding, unknown: newSpool?.slot === s.slot }" :style="{ '--c': newSpool?.slot === s.slot ? 'transparent' : (s.color || 'transparent') }"></span>
          <span class="t">
            <span class="name">{{ newSpool?.slot === s.slot ? 'New spool' : nameOf(s) }}</span>
            <span class="meta a-num">Slot {{ s.slot + 1 }}<template v-if="metaOf(s)"> · <em :class="metaOf(s)!.tone">{{ metaOf(s)!.text }}</em></template></span>
          </span>
        </button>
      </div>
    </div>

    <div v-if="carryOn != null" class="setline">
      <span class="w">
        <b>When a spool runs out, carry on with a matching one</b>
        <span>Same color and same material only. Otherwise I'll ask.</span>
      </span>
      <Toggle :model-value="carryOn" label="Carry on with a matching spool" :disabled="door.away || !!store.busyAction"
              @update:model-value="(v: boolean) => store.act('carry_on', { on: v })" />
    </div>

    <SpoolSheet :spool="editing" :unit-name="unitNameOf(editing)" :start-editing="editStart" @close="editing = null; editStart = false" />
    <DrySheet :unit="dryingUnit" @close="dryingUnit = null" />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentSpool } from '@/intent/types'
import BusyBanner from '@/components/now/BusyBanner.vue'
import { door } from '@/door'
import SpoolSheet from '@/components/materials/SpoolSheet.vue'
import OneSpool from '@/components/materials/OneSpool.vue'
import DrySheet from '@/components/materials/DrySheet.vue'
import Toggle from '@/components/materials/Toggle.vue'
import type { IntentUnit } from '@/intent/types'

const store = useIntentStore()
const spools = computed(() => store.intent?.spools ?? [])
const one = computed(() => (spools.value.length === 1 && spools.value[0].direct ? spools.value[0] : null))
const loaded = computed(() => spools.value.filter(s => s.status === 'ready' || s.status === 'low'))
const editing = ref<IntentSpool | null>(null)
const units = computed(() => store.intent?.units ?? null)
const head = computed(() => store.intent?.head ?? null)
function colorOf(slot: number): string {
  return spools.value.find(s => s.slot === slot)?.color || 'transparent'
}
const lookAgain = computed(() => units.value?.actions?.[0] ?? null)
const feeding = computed(() => store.intent?.state === 'printing' || store.intent?.state === 'preparing')
const editStart = ref(false)
const dryingUnit = ref<IntentUnit | null>(null)
const newSpool = computed(() => store.intent?.new_spool ?? null)
const carryOn = computed(() => units.value?.carry_on ?? null)
// Slots grouped by unit; an intent layer older than design/slots/ has no list: one grid, no unit line
const groups = computed(() => {
  const list = units.value?.list ?? []
  if (!list.length) return [{ unit: null as IntentUnit | null, spools: spools.value }]
  return list.map((u) => ({ unit: u as IntentUnit | null, spools: spools.value.filter((s) => u.slots.includes(s.slot)) }))
})
function unitNameOf(s: IntentSpool | null): string | null {
  if (!s) return null
  return units.value?.list?.find((u) => u.slots.includes(s.slot))?.name ?? null
}
function open(s: IntentSpool) {
  editStart.value = false
  editing.value = s
}
function openEdit(slot: number) {
  const s = spools.value.find((x) => x.slot === slot)
  if (!s) return
  editStart.value = true
  editing.value = s
}
// The card's second line: what's true of it, in a word or two, coloured when it matters
function metaOf(s: IntentSpool): { text: string; tone: string } | null {
  if (s.status === 'empty') return { text: 'empty', tone: '' }
  if (s.in_use) return { text: feeding.value ? 'feeding' : 'in use', tone: 'acc' }
  if (s.status === 'low') return { text: s.grams ? `${s.grams} g, low` : 'running low', tone: 'amb' }
  if (s.spare_for != null) return { text: 'spare', tone: 'grn' }
  if (s.grams) return { text: `${s.grams} g`, tone: '' }
  return null
}
function minutes(m: number): string {
  if (m < 60) return `${Math.max(1, m)} min`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} h ${r} min` : `${h} h`
}
function dryPct(u: IntentUnit): number {
  const d = u.drying
  if (!d || !d.minutes_total) return 0
  return Math.max(0, Math.min(100, ((d.minutes_total - d.minutes_left) / d.minutes_total) * 100))
}

function nameOf(s: IntentSpool): string {
  if (s.status === 'empty') return 'Empty'
  return s.name || 'Unknown spool'
}
</script>

<style scoped>
.materials { flex: 1; padding: calc(8 * var(--u) + 4px) calc(28 * var(--u) + 8px) calc(16 * var(--u) + 6px); overflow: auto; }
.head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: calc(4 * var(--u) + 2px); }
.head-right { display: flex; align-items: center; gap: calc(12 * var(--u) + 4px); }
.look { flex: none; font-size: calc(15 * var(--u) + 4px); padding: calc(8 * var(--u) + 3px) calc(14 * var(--u) + 5px); min-height: 40px; }
.notice {
  display: flex; align-items: center; gap: calc(14 * var(--u) + 6px);
  background: var(--a-tint-amber); border-radius: calc(16 * var(--u) + 6px);
  padding: calc(12 * var(--u) + 4px) calc(16 * var(--u) + 6px); margin-bottom: calc(12 * var(--u) + 4px);
}
.notice.head { flex-direction: column; align-items: stretch; }
.choices, .head-actions { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 4px); }
.head-actions .a-btn { flex: 0 1 auto; padding: calc(10 * var(--u) + 4px) calc(18 * var(--u) + 6px); font-size: calc(17 * var(--u) + 4px); }
.choice {
  appearance: none; font: inherit; font-weight: 600; cursor: pointer; color: var(--a-ink);
  display: inline-flex; align-items: center; gap: 8px;
  font-size: calc(15 * var(--u) + 4px); padding: calc(7 * var(--u) + 3px) calc(14 * var(--u) + 5px) calc(7 * var(--u) + 3px) calc(8 * var(--u) + 3px);
  min-height: 44px; border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-surface);
}
.choice .dot { width: 26px; height: 26px; border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); }
.notice-words { flex: 1; display: flex; flex-direction: column; gap: 2px; font-size: calc(14 * var(--u) + 5px); }
.notice-words span { color: var(--a-ink-2); }
.notice .a-btn { flex: none; padding: calc(10 * var(--u) + 4px) calc(18 * var(--u) + 6px); font-size: calc(17 * var(--u) + 4px); }
.title { font-size: calc(30 * var(--u) + 8px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(16 * var(--u) + 5px); margin: 0; }
.sub.away { margin: 0 0 calc(12 * var(--u) + 4px); }
.note { margin-top: calc(14 * var(--u) + 6px); color: var(--a-ink-3); max-width: 50ch; }
.unit + .unit { margin-top: calc(6 * var(--u) + 2px); }
.uh { display: flex; align-items: center; gap: calc(8 * var(--u) + 2px); min-height: 34px; margin-bottom: calc(2 * var(--u) + 2px);
      font-size: calc(13 * var(--u) + 2px); color: var(--a-ink-3); white-space: nowrap; }
.uname { font-size: calc(13 * var(--u) + 2px); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-ink-2); }
.drying { color: var(--a-ink-2); overflow: hidden; text-overflow: ellipsis; }
.drydot { width: 9px; height: 9px; border-radius: 50%; background: #e8743b; box-shadow: 0 0 0 4px rgba(232, 116, 59, 0.22); flex: none; }
.drybar { width: calc(90 * var(--u) + 20px); height: 6px; border-radius: 3px; background: var(--a-surface-2); overflow: hidden; flex: none; }
.drybar i { display: block; height: 100%; background: #e8743b; border-radius: 3px; }
.spacer { flex: 1; }
.unitbtn { flex: none; font-size: calc(12 * var(--u) + 3px); padding: 0 calc(10 * var(--u) + 3px); min-height: 32px; border-radius: 11px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: calc(10 * var(--u) + 2px); }
.slot {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer;
  background: var(--a-surface);
  border-radius: calc(14 * var(--u) + 4px);
  padding: calc(10 * var(--u) + 2px) calc(10 * var(--u) + 2px);
  display: flex; align-items: center; gap: calc(8 * var(--u) + 2px);
  min-height: calc(52 * var(--u) + 12px); min-width: 0;
}
.slot:active { transform: scale(0.98); }
.slot[disabled] { cursor: default; }
.away .slot[disabled] { opacity: 1 !important; cursor: default !important; }   /* read-only away, not broken */
.slot.inuse { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.slot.asked { outline: 2px solid var(--a-amber); outline-offset: -2px; }
.swatch {
  width: calc(28 * var(--u) + 6px); height: calc(28 * var(--u) + 6px); border-radius: 50%; flex: none;
  background: var(--c); border: 3px solid var(--a-swatch-edge); box-sizing: border-box;
}
.slot.empty .swatch, .swatch.unknown { background: transparent; border-style: dashed; border-color: var(--a-swatch-empty); }
.slot.low .swatch { border-color: var(--a-amber); }
.t { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.name { font-family: var(--a-display); font-weight: 700; font-size: calc(14 * var(--u) + 3px); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.slot.empty .name { color: var(--a-ink-3); }
.meta { font-size: calc(11 * var(--u) + 2.5px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta em { font-style: normal; font-weight: 600; }
.meta em.acc { color: var(--a-accent-text); }
.meta em.amb { color: var(--a-amber-text); }
.meta em.grn { color: var(--a-green-text); }
.setline { display: flex; align-items: center; gap: calc(12 * var(--u) + 4px); margin-top: calc(8 * var(--u) + 4px); }
.setline .w { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.setline b { font-size: calc(14 * var(--u) + 3px); font-weight: 600; }
.setline .w span { font-size: calc(11 * var(--u) + 3px); color: var(--a-ink-3); }
.choice.plain { padding-left: calc(14 * var(--u) + 5px); }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
/* Phones: each unit a list, one slot per row */
@media (max-width: 599px) {
  .grid { grid-template-columns: 1fr; gap: 0; background: var(--a-surface); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); }
  .slot { border-radius: 0; min-height: 56px; padding: 8px 14px; background: none; border-top: 1px solid var(--a-line); gap: 12px; }
  .slot:first-child { border-top: 0; }
  .slot.inuse, .slot.asked { outline: 0; }
  .swatch { width: 32px; height: 32px; }
  .name { font-size: 16px; }
  .meta { font-size: 13px; }
  .uh { font-size: 13px; min-height: 32px; }
  .uname { font-size: 12px; }
  .drybar { display: none; }
  .head { margin-bottom: 12px; flex-wrap: wrap; row-gap: 6px; }
  .head-right { margin-left: auto; }
  .setline b { font-size: 15px; }
  .setline .w span { font-size: 13px; }
}
</style>
