<template>
  <!-- Skip a part (design/skip-objects/, A): the map, a list under it, then a held red button. Tapping only
       picks; nothing is skipped until the hold fills. On the panel the map and the list sit side by side. -->
  <SliceSheet :open="open" :title="sel ? sel.label : finishedOrWhich" :sub="sub" :wide="wide" @close="emit('close')">
    <div class="wrapper" :class="{ wide }">
      <div class="mapbox">
        <PartsMap :parts="parts" :selected="sel?.name ?? null" :pickable="parts.can_skip" @pick="pick" />
        <span class="front">Front</span>
      </div>
      <div class="side">
        <div class="list">
          <button v-for="it in ordered" :key="it.name" type="button" class="pr" :class="[it.state, { on: it.name === sel?.name }]"
                  :disabled="it.state === 'skipped' || !parts.can_skip" @click="pick(it.name)">
            <span class="n a-num">{{ it.n }}</span>
            <span class="t"><b>{{ it.label }}</b><span>{{ it.state === 'printing' ? 'Printing now · ' : it.state === 'skipped' ? 'Skipped · ' : '' }}{{ it.where }}</span></span>
          </button>
        </div>
        <template v-if="sel && parts.can_skip">
          <p class="say">The other {{ parts.left - 1 }} carry on. A skipped part can't be put back; it stays as far as it got.</p>
          <HoldButton class="skip red" :label="`Skip ${lower(sel.label)}`" hint-text="Keep holding to skip" :busy="busy" @run="emit('skip', sel.name)" />
        </template>
        <p v-else-if="parts.can_skip" class="say">Tap the one that's failing, on the map or here.</p>
        <p v-else-if="!finished && parts.left === 1" class="say">Only one is left. To end it, stop the print.</p>
      </div>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { IntentParts } from '@/intent/types'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import HoldButton from './HoldButton.vue'
import PartsMap from './PartsMap.vue'

const props = defineProps<{ open: boolean; parts: IntentParts; printer: string; busy?: boolean; wide?: boolean; finished?: boolean }>()
const emit = defineEmits<{ close: []; skip: [name: string] }>()
const picked = ref<string | null>(null)
const sel = computed(() => props.parts.items.find(it => it.name === picked.value && it.state !== 'skipped') ?? null)
const finishedOrWhich = computed(() => (props.finished ? "What's on the plate" : props.parts.can_skip ? 'Which one is failing?' : 'The parts'))
const sub = computed(() => {
  if (sel.value) return sel.value.where.charAt(0).toUpperCase() + sel.value.where.slice(1) + '.'
  return `Seen from the front of ${props.printer}.` + (props.parts.items.some(it => it.state === 'printing') ? ' The blue one is printing now.' : '')
})
// the one printing now first, then front-left to back-right
const ordered = computed(() => [...props.parts.items].sort((a, b) => (a.state === 'printing' ? -1 : b.state === 'printing' ? 1 : a.n - b.n)))
function pick(name: string) { picked.value = picked.value === name ? null : name }
function lower(s: string) { return s.charAt(0).toLowerCase() + s.slice(1) }
watch(() => props.open, o => { if (!o) picked.value = null })
// skipped while the sheet is open: let go of it
watch(() => props.parts.skipped.length, () => { if (!sel.value) picked.value = null })
</script>

<style scoped>
.wrapper { display: grid; gap: 12px; }
.wrapper.wide { grid-template-columns: minmax(0, 300px) minmax(0, 1fr); align-items: start; }
.mapbox { position: relative; aspect-ratio: 1; border-radius: 18px; overflow: hidden; background: radial-gradient(circle at 50% 38%, var(--a-obj-hi), var(--a-obj-lo)); padding: 6px; }
.front { position: absolute; left: 50%; bottom: 8px; transform: translateX(-50%); font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--a-ink-3); background: color-mix(in srgb, var(--a-surface) 85%, transparent); padding: 3px 9px; border-radius: 99px; pointer-events: none; }
.side { display: grid; gap: 10px; align-content: start; min-width: 0; }
.list { display: grid; gap: 1px; background: var(--a-line); border-radius: 16px; overflow: auto; max-height: 280px; }
.wide .list { max-height: 190px; }
.pr { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 10px; background: var(--a-surface); padding: 9px 12px; }
.pr:disabled { cursor: default; }
.pr .n { width: 26px; height: 26px; border-radius: 50%; background: var(--a-surface-2); display: grid; place-items: center; font-size: 12.5px; font-weight: 700; flex: none; }
.pr .t { flex: 1; min-width: 0; display: grid; }
.pr .t b { font-weight: 600; font-size: 15.5px; }
.pr .t span { font-size: 12.5px; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pr.printing .n { background: var(--a-accent); color: var(--a-accent-ink); }
.pr.on { background: color-mix(in srgb, var(--a-red) 12%, var(--a-surface)); }
.pr.on .n { background: var(--a-red); color: #fff; }
.pr.skipped { color: var(--a-ink-3); }
.pr.skipped .t b { text-decoration: line-through; font-weight: 500; }
.pr:focus-visible { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.say { font-size: 14px; color: var(--a-ink-2); line-height: 1.35; margin: 2px 2px 0; }
.skip { width: 100%; height: 56px; border-radius: 18px; font-size: 18px; background: color-mix(in srgb, var(--a-red) 16%, var(--a-surface)); color: var(--a-red-text); border: 0; }
</style>
