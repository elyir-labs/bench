<template>
  <!-- Print, for a file that changes colour on a printer with a unit (design/colour-change/, C): what it starts
       with, and each change planned onto a loaded spool, so the unit does it with nobody there. The file's colour
       is picked when it names one (CReady); when it doesn't, it asks once and Print waits (CAsk). "Pause there and
       let me choose" plans a pause instead. The words are the intent layer's (check_print's colour). -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="check && s" class="scrim" :class="{ compact }" :style="unit" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="s.headline">
          <div v-if="compact" class="grab" aria-hidden="true"></div>
          <h2 class="a-display">{{ s.headline }}</h2>
          <p class="detail">{{ s.detail }}</p>
          <div class="rows">
            <div class="row">
              <span class="lab">{{ s.labels.start }}</span>
              <span class="sw" :class="{ missing: !s.start.loaded }" :style="{ '--c': s.start.color || 'transparent' }"></span>
              <span class="w"><b>{{ s.start.name }}</b><small :class="{ no: !s.start.loaded }">{{ s.start.line }}</small></span>
              <svg v-if="s.start.loaded" class="ok" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
            </div>
            <div v-for="(c, k) in s.changes" :key="k" class="row" :class="{ open: open(k) }">
              <span class="lab">{{ c.label }}</span>
              <div v-if="open(k)" class="chips" role="group" :aria-label="c.label">
                <button v-for="ch in choicesFor(s, picks, k)" :key="ch.slot" type="button" class="chip"
                        :class="{ differs: ch.differs, on: picks[k] === ch.slot }" :disabled="busy" @click="choose(k, ch)">
                  <span class="sw" :style="{ '--c': ch.color || 'transparent' }"></span>{{ ch.name }}<span class="n a-num">· {{ ch.slot + 1 }}</span>
                </button>
              </div>
              <template v-else-if="picks[k] === 'pause'">
                <span class="w"><b class="pause" :class="{ no: c.not_loaded }">{{ pickLine(s, k, 'pause') }}</b></span>
                <button type="button" class="link" :disabled="busy" @click="editing = k">{{ s.labels.change }}</button>
              </template>
              <template v-else>
                <span class="sw" :style="{ '--c': chosen(k)?.color || 'transparent' }"></span>
                <span class="w"><b>{{ chosen(k)?.name }}</b><small>{{ pickLine(s, k, picks[k]) }}</small></span>
                <button type="button" class="link" :disabled="busy" @click="editing = k">{{ s.labels.change }}</button>
              </template>
            </div>
            <p v-if="asking" class="ask" role="alert">
              <span>{{ asking.text }}</span>
              <button type="button" class="a-btn amber" :disabled="busy" @click="yes">{{ s.labels.yes }}</button>
            </p>
          </div>
          <p v-if="error" class="err" role="alert">{{ error }}</p>
          <div class="foot">
            <button type="button" class="link pauseall" :disabled="busy" @click="pauseAll">{{ s.labels.pause }}</button>
            <span class="grow"></span>
            <button type="button" class="a-btn ghost" :disabled="busy" @click="$emit('close')">{{ s.labels.back }}</button>
            <button type="button" class="a-btn accent" :disabled="busy || !canPrint(picks)" @click="print">{{ busy ? '…' : s.labels.print }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { ColourSheet, PrintCheck } from '@/intent/types'
import { canPrint, choicesFor, initialPicks, pickLine, planChanges, type PlanPick } from '@/intent/colour'
import { layout } from '@/shell/useLayout'
import { unitFor } from '@/shell/layout'

const props = defineProps<{ check: PrintCheck | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const router = useRouter()

const s = computed<ColourSheet | null>(() => props.check?.colour ?? null)
const picks = ref<PlanPick[]>([])
const sure = ref<number[]>([])
const editing = ref<number | null>(null)
const asking = ref<{ k: number; slot: number; text: string } | null>(null)
const error = ref<string | null>(null)
const busy = computed(() => !!store.busyAction)
watch(s, (v) => {
  picks.value = v ? initialPicks(v) : []
  sure.value = []
  editing.value = null
  asking.value = null
  error.value = null
}, { immediate: true })

const compact = computed(() => layout.value === 'compact')
const unit = computed(() => { const u = unitFor(layout.value); return u ? { '--u': u } : undefined })

const open = (k: number) => picks.value[k] === null || editing.value === k
const chosen = (k: number) => s.value?.choices.find((c) => c.slot === picks.value[k]) ?? null

function choose(k: number, ch: ColourSheet['choices'][number]) {
  if (ch.differs && !sure.value.includes(ch.slot)) {
    asking.value = { k, slot: ch.slot, text: ch.ask ?? '' }   // another material: asked once, never refused
    return
  }
  set(k, ch.slot)
}
function set(k: number, p: PlanPick) {
  const next = [...picks.value]
  next[k] = p
  picks.value = next
  editing.value = null
  asking.value = null
}
function yes() {
  const a = asking.value
  if (!a) return
  sure.value = [...sure.value, a.slot]
  set(a.k, a.slot)
}
function pauseAll() {
  picks.value = picks.value.map(() => 'pause')
  editing.value = null
  asking.value = null
}

async function print() {
  const f = props.check?.filename
  if (!f || !canPrint(picks.value)) return
  await store.act('print_planned', { filename: f, changes: planChanges(picks.value, sure.value) })
  if (store.actionError) {
    error.value = store.actionError
    return
  }
  emit('close')
  router.push('/')
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; padding: calc(16 * var(--u) + 6px);
}
.sheet {
  background: var(--a-surface); color: var(--a-ink); border-radius: calc(26 * var(--u) + 4px); box-shadow: var(--a-card-shadow);
  width: 100%; max-width: calc(756 * var(--u)); padding: calc(24 * var(--u) + 4px) calc(28 * var(--u)) calc(22 * var(--u));
}
h2 { margin: 0; font-size: calc(26 * var(--u) + 2px); line-height: 1.12; letter-spacing: -0.02em; }
.detail { margin: 6px 0 0; color: var(--a-ink-2); font-size: calc(16 * var(--u) + 1px); line-height: 1.38; }
.rows { display: flex; flex-direction: column; gap: calc(10 * var(--u)); margin-top: calc(14 * var(--u)); }
.row {
  display: flex; align-items: center; gap: calc(14 * var(--u)); min-height: calc(62 * var(--u));
  padding: calc(8 * var(--u)) calc(14 * var(--u)); border-radius: calc(14 * var(--u)); background: var(--a-surface-2);
}
.row.open { background: none; padding-left: calc(14 * var(--u)); padding-right: 0; align-items: flex-start; }
.row.open .lab { padding-top: calc(13 * var(--u)); }
.lab { flex: none; width: calc(118 * var(--u)); font-size: calc(13 * var(--u) + 1px); font-weight: 700; letter-spacing: .08em;
       text-transform: uppercase; color: var(--a-ink-3); }
.sw { flex: none; width: calc(32 * var(--u) + 2px); height: calc(32 * var(--u) + 2px); border-radius: 50%; background: var(--c);
      border: 3px solid var(--a-swatch-edge); box-sizing: border-box; }
.sw.missing { border: 3px dashed var(--a-amber); }
.w { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.w b { font-size: calc(17 * var(--u) + 1px); font-weight: 700; }
.w small { font-size: calc(13 * var(--u) + 1px); color: var(--a-ink-3); }
.w .no, .w b.pause.no { color: var(--a-amber-text); }
.w b.pause { font-weight: 600; font-size: calc(15 * var(--u) + 2px); }
.ok { width: calc(22 * var(--u)); height: calc(22 * var(--u)); fill: none; stroke: var(--a-green); stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; flex: none; }
.link { appearance: none; border: 0; background: none; padding: 6px 2px; cursor: pointer; font: inherit; font-size: calc(15 * var(--u) + 2px);
        color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; flex: none; }
.link[disabled] { opacity: .5; cursor: default; }
.chips { flex: 1; display: flex; flex-wrap: wrap; gap: calc(8 * var(--u)); }
.chip {
  appearance: none; font: inherit; cursor: pointer; color: var(--a-ink); display: inline-flex; align-items: center; gap: 8px;
  height: calc(42 * var(--u) + 2px); padding: 0 calc(14 * var(--u)) 0 calc(6 * var(--u)); border-radius: 99px;
  border: 1px solid var(--a-line); background: var(--a-surface); font-size: calc(16 * var(--u) + 1px); font-weight: 600; white-space: nowrap;
}
.chip .sw { width: calc(26 * var(--u) + 2px); height: calc(26 * var(--u) + 2px); border-width: 2px; }
.chip .n { color: var(--a-ink-3); font-weight: 500; }
.chip.differs { opacity: .55; }
.chip.on { border-color: var(--a-amber); box-shadow: 0 0 0 2px var(--a-amber); opacity: 1; }
.ask { display: flex; align-items: center; gap: 12px; margin: 0; padding: 10px 14px; border-radius: 14px;
       background: color-mix(in srgb, var(--a-amber) 16%, var(--a-surface)); color: var(--a-ink); font-size: calc(15 * var(--u) + 1px); }
.ask span { flex: 1; }
.ask .a-btn { flex: none; min-height: 40px; padding: 0 16px; }
.err { color: var(--a-red-text); margin: 10px 0 0; font-size: 14px; }
.foot { display: flex; align-items: center; gap: calc(12 * var(--u)); margin-top: calc(16 * var(--u)); }
.grow { flex: 1; }
.foot .a-btn { flex: none; min-height: calc(46 * var(--u) + 2px); padding: 0 calc(22 * var(--u)); font-size: calc(16 * var(--u) + 1px); border-radius: calc(14 * var(--u)); }

/* a phone: from the bottom, rows stacked */
.scrim.compact { align-items: flex-end; padding: 0; }
.compact .sheet { border-radius: 26px 26px 0 0; max-width: none; padding: 10px 20px calc(28px + env(safe-area-inset-bottom, 0px)); }
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
.compact h2 { font-size: 23px; }
.compact .detail { font-size: 15px; }
.compact .row { flex-wrap: wrap; row-gap: 6px; }
.compact .row.open { padding-left: 0; }
.compact .lab { width: 100%; font-size: 12px; }
.compact .row { padding: 10px 14px; border-radius: 14px; }
.compact .sw { width: 30px; height: 30px; }
.compact .w b { font-size: 16px; }
.compact .w small, .compact .w b.pause { font-size: 13px; }
.compact .ok { width: 20px; height: 20px; }
.compact .link { font-size: 15px; }
.compact .row:not(.open) .lab { width: auto; flex-basis: 100%; }
.compact .chip { height: 40px; font-size: 15px; }
.compact .foot { flex-wrap: wrap; }
.compact .pauseall { flex-basis: 100%; text-align: left; font-size: 15px; }
.compact .foot .a-btn { flex: 1; min-height: 50px; font-size: 17px; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }
</style>
