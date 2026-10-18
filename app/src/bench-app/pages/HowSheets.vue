<template>
  <!-- How it prints's four sheets (design/bench-how/, A): the model page's, and a bed's on the plan, which saves each
       change with every model on it. -->
  <!-- It's for: the four purposes, with a time each where the page has one (A-purpose) -->
  <HowSheet :open="open === 'purpose'" title="What's it for?" :model="name" :kept="kept" :sub="subs?.purpose" @close="$emit('close')">
    <button v-for="p in purposes" :key="p.id" class="pick" :class="{ on: p.id === how.purpose }" @click="$emit('change', { purpose: p.id })">
      <span class="t"><b>{{ p.label }}</b><span>{{ p.summary }}</span></span>
      <b class="tm a-num">{{ price?.(p.id) ?? '' }}</b>
      <svg class="check" viewBox="0 0 24 24" aria-hidden="true"><path v-if="p.id === how.purpose" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </button>
  </HowSheet>

  <!-- Supports: the printer's usual on top, then the three kinds (design/supports/'s words) -->
  <HowSheet :open="open === 'supports'" title="Supports" :model="name" :kept="kept" :sub="subs?.supports ?? 'Under the parts that hang out in the air.'"
            @close="$emit('close')">
    <button class="pick" :class="{ on: how.supports === null }" @click="$emit('change', { supports: null })">
      <span class="t"><b>{{ usualOf(printer) }}</b><span>{{ usual ? `${KIND_WORDS[usual].label}: ${KIND_WORDS[usual].line}` : 'Whatever the printer it goes to usually prints.' }}</span></span>
      <svg class="check" viewBox="0 0 24 24" aria-hidden="true"><path v-if="how.supports === null" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </button>
    <button v-for="k in SUPPORT_KINDS" :key="k" class="pick" :class="{ on: how.supports === k }" @click="$emit('change', { supports: k })">
      <span class="t"><b>{{ KIND_WORDS[k].label }}</b><span>{{ KIND_WORDS[k].line }}</span></span>
      <svg class="check" viewBox="0 0 24 24" aria-hidden="true"><path v-if="how.supports === k" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </button>
  </HowSheet>

  <!-- Brim (design/brim/'s words): each part's own, or one for every part; none ticked while a bed's models differ -->
  <HowSheet :open="open === 'brim'" title="Brim" :model="name" :kept="kept" :sub="subs?.brim ?? 'What holds the first layer down, round every part.'"
            @close="$emit('close')">
    <button class="pick" :class="{ on: !mixed && how.brim === null }" @click="$emit('change', { brim: null })">
      <span class="t"><b>Each part's own</b><span>What each part last printed with, else picked for it from how it stands.</span></span>
      <svg class="check" viewBox="0 0 24 24" aria-hidden="true"><path v-if="!mixed && how.brim === null" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </button>
    <button v-for="k in BRIMS" :key="k" class="pick" :class="{ on: !mixed && how.brim === k }" @click="$emit('change', { brim: k })">
      <span class="t"><b>{{ BRIM_WORDS[k].label }}</b><span>{{ BRIM_WORDS[k].line }}</span></span>
      <svg class="check" viewBox="0 0 24 24" aria-hidden="true"><path v-if="!mixed && how.brim === k" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
    </button>
  </HowSheet>

  <!-- Every setting (design/edit-settings/'s list): the model's own over the printer's -->
  <HowSheet :open="open === 'settings'" title="Every setting" :model="name" :kept="kept" @close="$emit('close')"
            :sub="subs?.settings ?? settingsSub">
    <p v-if="!editable.length" class="none muted">The box's slicer hasn't said which settings can change.</p>
    <div v-for="r in settingList" :key="r.key" class="set" :class="{ mine: r.mine }">
      <span class="t"><b>{{ r.label }}</b><span>{{ r.mine ? r.why : `${r.now} · ${r.why}` }}</span>
        <button v-if="r.mine" class="own" @click="$emit('change', { settings: { [r.key]: null } })">Back to the printer's own</button></span>
      <Stepper v-if="r.e.kind === 'number'" class="val" :value="r.steps!.at" :min="0" :max="r.steps!.last" :shown="r.now" :label="r.label"
               @change="(i: number) => $emit('change', { settings: { [r.key]: r.steps!.value(i) } })" />
      <div v-else class="choices" role="radiogroup" :aria-label="r.label">
        <button v-for="c in r.e.choices" :key="c[0]" role="radio" :aria-checked="c[0] === r.value" class="chip" :class="{ on: c[0] === r.value }"
                @click="$emit('change', { settings: { [r.key]: c[0] } })">{{ c[1] }}</button>
      </div>
    </div>
  </HowSheet>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BRIM_WORDS, KIND_WORDS, SUPPORT_KINDS, editWords, steps, type Editable, type Purpose, type SupportKind } from '@/slice/plan'
import Stepper from '@/components/slice/Stepper.vue'
import { settingRows, settingValue, usualOf, type BrimKind, type How, type HowChange, type Tile } from '../how'
import HowSheet from './HowSheet.vue'

const props = defineProps<{
  open: Tile['id'] | null
  how: How
  name: string
  kept?: string
  purposes: { id: Purpose; label: string; summary: string }[]
  editable: Editable[]
  usual: SupportKind | null
  printer: string | null
  values?: Record<string, string> | null
  price?: (p: Purpose) => string
  subs?: Partial<Record<Tile['id'], string>>
  mixed?: boolean
}>()
defineEmits<{ close: []; change: [c: HowChange] }>()

const BRIMS: BrimKind[] = ['all', 'ears', 'none']
const settingsSub = computed(() => `Laid over ${props.printer ? `${props.printer}'s` : "the printer's"} own. One set here is this model's, on any printer.`)

// each control starts from the model's own, else as the printer prints it (its setup's values)
const settingList = computed(() => {
  const by = Object.fromEntries(settingRows(props.editable, props.how, props.values, props.printer).map((r) => [r.key, r]))
  return props.editable.map((e) => {
    const value = settingValue(e, props.how, props.values)
    return { ...by[e.key], e, value, now: editWords(e, value), steps: e.kind === 'number' ? steps(e, value) : null }
  })
})
</script>

<style scoped>
.muted { color: var(--a-ink-3); }
.t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.t b { font-size: 21px; } .t span { color: var(--a-ink-3); font-size: 17px; }
.check { width: 28px; height: 28px; flex: none; fill: none; stroke: var(--a-accent); stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.pick:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
/* the sheets' rows (A-purpose) */
.pick { appearance: none; border: 0; border-top: 1px solid var(--a-line); width: 100%; font: inherit; color: inherit; text-align: left; cursor: pointer;
        display: grid; grid-template-columns: minmax(0, 1fr) auto 26px; gap: 14px; align-items: center; padding: 14px 22px; background: none; }
.pick.on { background: var(--a-tint-blue); }
.pick .t b { font-size: 20px; } .pick .t span { font-size: 15px; }
.pick .tm { font-size: 17px; color: var(--a-ink-2); white-space: nowrap; }
.pick .check { width: 24px; height: 24px; }
.none { margin: 0; padding: 14px 22px; border-top: 1px solid var(--a-line); font-size: 16px; }
.set { display: flex; align-items: center; gap: 14px; padding: 12px 22px; border-top: 1px solid var(--a-line); }
.set.mine { background: color-mix(in srgb, var(--a-amber) 14%, var(--a-surface)); }
.set .t b { font-size: 18px; } .set .t span { font-size: 14.5px; }
.set.mine .t span { color: var(--a-amber-text); font-weight: 650; }
.set .val :deep(b) { min-width: 76px; white-space: nowrap; }
.own { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; text-align: left; padding: 2px 0 0; justify-self: start; font-size: 14.5px; color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; }
.chip { display: inline-flex; align-items: center; gap: 8px; border: 0; border-radius: 999px; font: inherit; font-weight: 650; color: var(--a-ink-2); cursor: pointer; }
.choices { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; max-width: 58%; }
.choices .chip { padding: 7px 12px; font-size: 15px; background: var(--a-surface-2); }
.choices .chip.on { background: var(--a-ink); color: var(--a-bg); }
@media (max-width: 599px) {
  .t b { font-size: 17px; } .t span { font-size: 14px; }
  .pick { padding: 12px 16px; gap: 10px; } .pick .t b { font-size: 17px; } .pick .t span { font-size: 13.5px; } .pick .tm { font-size: 14px; }
  .set { padding: 10px 16px; flex-wrap: wrap; } .set .t b { font-size: 16px; } .set .t span { font-size: 13px; }
  .choices { max-width: none; justify-content: flex-start; }
}
</style>
