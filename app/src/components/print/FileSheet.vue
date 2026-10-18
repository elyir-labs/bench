<template>
  <!-- A file's sheet (design/print-library/, B): tapping a tile opens it, Print is the big button,
       "Remove from the printer" is quiet and red, under the picture, away from Print. Removing asks
       first. A past print whose file is gone gets its own honest sheet. Away it's browse-only. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="item" class="scrim" :class="{ compact }" :style="unit" @click.self="close">
        <!-- the file -->
        <div v-if="mode === 'file'" class="sheet fs" role="dialog" aria-modal="true" :aria-label="item.name">
          <div v-if="compact" class="grab" aria-hidden="true"></div>
          <div class="left">
            <div class="pic">
              <ObjectImage :src="thumb" :alt="item.name" class="img" />
              <span class="colors" aria-hidden="true"><i v-for="(c, k) in colors" :key="k" :style="{ background: c }"></i></span>
            </div>
            <button v-if="canRemove && !compact" class="quiet" :disabled="busy" @click="mode = 'confirm'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6" /></svg>Remove from the printer
            </button>
          </div>
          <div class="right">
            <h2 class="a-display">{{ item.name }}</h2>
            <span class="meta a-num">{{ metaLine(item) }}</span>
            <div v-for="(u, k) in uses" :key="k" class="fit" :class="{ no: u.loaded === false }">
              <i :style="{ background: u.color || 'transparent' }"></i>
              <span>{{ u.line }}</span>
              <svg v-if="u.loaded" class="ok" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <p class="hist">{{ hist.printed }}<template v-if="compact ? hist.fromShort : hist.from"><br v-if="!compact" /> {{ compact ? hist.fromShort : hist.from }}</template></p>
            <span class="grow"></span>
            <div v-if="away" class="awaynote">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.6"/></svg>
              <span>Start it at {{ printer }}, where you can check the bed is clear.</span>
            </div>
            <button v-else class="a-btn accent print" :disabled="busy || starting" @click="print">Print</button>
            <button v-if="canRemove && compact" class="quiet" :disabled="busy" @click="mode = 'confirm'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6" /></svg>Remove from the printer
            </button>
          </div>
          <button v-if="!compact" class="x" aria-label="Close" @click="close">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>

        <!-- are you sure / a file that's gone -->
        <div v-else class="sheet ask" :class="mode" role="alertdialog" aria-modal="true" :aria-label="headline">
          <div v-if="compact" class="grab" aria-hidden="true"></div>
          <div class="ask-row">
            <div class="pic small" :class="{ faded: mode === 'gone' }"><ObjectImage :src="thumb" :alt="item.name" class="img" /></div>
            <div class="words">
              <h2 class="a-display">{{ headline }}</h2>
              <p class="detail">{{ detail }}</p>
              <p v-if="error" class="error" role="alert">{{ error }}</p>
            </div>
          </div>
          <div class="actions">
            <template v-if="mode === 'confirm'">
              <button class="a-btn ghost" :disabled="working" @click="mode = 'file'">Keep it</button>
              <button class="a-btn red" :disabled="working || busy" @click="remove">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6" /></svg>Remove
              </button>
            </template>
            <template v-else>
              <button v-if="!away" class="a-btn ghost" :disabled="working" @click="forget">Remove from recent</button>
              <button class="a-btn accent" @click="close">OK</button>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
  <!-- Away from the printer's own screen, Print asks first (decided 2 October 2026, design/print-a-model/) -->
  <BedClearSheet :open="askBed" :printer="printer" :working="starting" @close="askBed = false" @confirm="startNow" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ObjectImage from '@/components/now/ObjectImage.vue'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import { needsSheet } from '@/intent/colour'
import { door } from '@/door'
import { layout } from '@/shell/useLayout'
import { unitFor } from '@/shell/layout'
import { useLibrary } from '@/print/useLibrary'
import BedClearSheet from '@/components/slice/BedClearSheet.vue'
import { isPanel } from '@/theme'
import { metaLine, sheetHistory, type Item } from '@/print/library'

const props = defineProps<{
  item: Item | null
  check?: PrintCheck | null
  printer: string
  /** Its place in the library as shown, so a removed tile drains exactly there. */
  at?: number
}>()
const emit = defineEmits<{ close: []; refused: [check: PrintCheck] }>()
const store = useIntentStore()
const router = useRouter()
const lib = useLibrary()

type Mode = 'file' | 'confirm' | 'gone'
const mode = ref<Mode>('file')
const error = ref<string | null>(null)
const working = ref(false)
const starting = ref(false)
const askBed = ref(false)
watch(() => props.item, i => {
  askBed.value = false
  mode.value = i && !i.onPrinter ? 'gone' : 'file'
  error.value = null
  working.value = false
  starting.value = false
}, { immediate: true })

const compact = computed(() => layout.value === 'compact')
// teleported out of the shell, so it takes the shell's type scale with it
const unit = computed(() => { const u = unitFor(layout.value); return u ? { '--u': u } : undefined })
const away = computed(() => door.away)
const busy = computed(() => store.intent?.state !== 'ready')
// Removing is at home only: the door refuses it from away, so it isn't offered there.
const canRemove = computed(() => !!props.item?.onPrinter && !away.value)
const thumb = computed(() => (props.item ? store.thumbOf({ filename: props.item.filename, metadata: props.item.meta } as any) : null))
const colors = computed(() => (props.item?.colors.length ? props.item.colors.slice(0, 4) : ['#666666']))
const hist = computed(() => (props.item ? sheetHistory(props.item, props.printer, lib.now.value) : { printed: '', from: '', fromShort: '' }))

/** Per filament: where it comes from, as the intent layer's check_print says. An older printer
 *  only says what's missing. */
const uses = computed(() => {
  const c = props.check
  if (c?.uses?.length) return c.uses
  if (c && !c.ok) return c.missing.map(m => ({ color: m.color, loaded: false as boolean | null, line: c.short ?? '' })).slice(0, 1)
  return []
})

const headline = computed(() => {
  const i = props.item
  if (!i) return ''
  return mode.value === 'gone' ? `${i.name} isn't on ${props.printer} anymore` : `Remove ${i.name} from ${props.printer}?`
})
const detail = computed(() => (mode.value === 'gone'
  ? "Someone removed the file, maybe from Advanced. Send it again from your slicer and it'll show up under New."
  : "The file is deleted from the printer. This can't be undone. To print it again, send it from your slicer."))

function close() {
  if (working.value) return
  emit('close')
}

function print() {
  if (!props.item || busy.value || away.value) return
  // at the printer you can see the bed; anywhere else, say it's clear first
  if (isPanel) void startNow()
  else askBed.value = true
}

async function startNow() {
  const i = props.item
  if (!i || busy.value || away.value) return
  starting.value = true
  const check = await store.requestPrint(i.filename)
  starting.value = false
  askBed.value = false
  emit('close')
  if (!needsSheet(check)) router.push('/')
  else emit('refused', check)
}

async function remove() {
  const i = props.item
  if (!i) return
  working.value = true
  error.value = await lib.remove(i, props.at ?? -1)
  working.value = false
  if (!error.value) emit('close')
}

async function forget() {
  const i = props.item
  if (!i) return
  working.value = true
  await lib.forget(i)
  working.value = false
  emit('close')
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(8, 12, 20, 0.42);
  display: flex; align-items: center; justify-content: center;
  padding: calc(20 * var(--u));
}
.sheet { background: var(--a-surface); border-radius: calc(30 * var(--u)); box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); width: 100%; position: relative; color: var(--a-ink); }
.pic { position: relative; border-radius: calc(20 * var(--u)); overflow: hidden; aspect-ratio: 4 / 3; }
.img { position: absolute; inset: 0; width: 100%; height: 100%; }
.colors { position: absolute; top: 14px; right: 14px; display: flex; gap: 4px; }
.colors i { width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--a-swatch-empty); display: block; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
h2 { margin: 0; font-weight: 700; letter-spacing: -0.025em; line-height: 1.1; }

/* the file */
.fs { max-width: calc(760 * var(--u)); display: grid; grid-template-columns: calc(290 * var(--u)) 1fr; gap: calc(26 * var(--u)); padding: calc(26 * var(--u)) calc(28 * var(--u)) calc(22 * var(--u)); }
.fs h2 { font-size: calc(34 * var(--u)); margin: 0 calc(56 * var(--u)) 4px 0; overflow-wrap: anywhere; }
.right { display: flex; flex-direction: column; min-width: 0; }
.meta { font-size: calc(20 * var(--u)); color: var(--a-ink-2); }
.fit { display: flex; align-items: center; gap: 10px; font-size: calc(18 * var(--u)); margin-top: calc(14 * var(--u)); }
.fit + .fit { margin-top: 6px; }
.fit i { width: calc(22 * var(--u)); height: calc(22 * var(--u)); border-radius: 50%; border: 2px solid var(--a-swatch-edge); flex: none; }
.fit.no { color: var(--a-amber-text); font-weight: 600; }
.fit.no i { border: 2px dashed var(--a-amber); }
.fit .ok { width: calc(20 * var(--u)); height: calc(20 * var(--u)); color: var(--a-green); flex: none; }
.hist { font-size: calc(17 * var(--u)); color: var(--a-ink-3); margin: calc(8 * var(--u)) 0 0; line-height: 1.35; }
.grow { flex: 1; min-height: calc(16 * var(--u)); }
.print { flex: none; width: 100%; min-height: calc(72 * var(--u)); padding: 0 28px; font-size: calc(25 * var(--u)); border-radius: calc(24 * var(--u)); }
.quiet {
  appearance: none; border: 0; background: none; cursor: pointer; font: inherit; font-weight: 600;
  display: inline-flex; align-items: center; gap: 8px; color: var(--a-red-text);
  font-size: calc(18 * var(--u)); height: calc(46 * var(--u)); padding: 0 8px; margin-top: calc(10 * var(--u));
}
.quiet svg, .a-btn svg { width: 1em; height: 1em; flex: none; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.quiet[disabled] { opacity: 0.5; cursor: default; }
.x {
  appearance: none; border: 0; cursor: pointer; position: absolute; top: calc(18 * var(--u)); right: calc(18 * var(--u));
  width: calc(48 * var(--u)); height: calc(48 * var(--u)); border-radius: 50%; display: grid; place-items: center;
  background: var(--a-surface-2); color: var(--a-ink-2);
}
.x svg { width: calc(20 * var(--u)); height: calc(20 * var(--u)); fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; }
.awaynote { display: flex; gap: 12px; align-items: center; padding: 14px 16px; border-radius: 16px; background: var(--a-surface-2); color: var(--a-ink-2); font-size: calc(17 * var(--u)); line-height: 1.3; }
.awaynote svg { width: 22px; height: 22px; flex: none; color: var(--a-ink-3); fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

/* are you sure / gone */
.ask { max-width: calc(660 * var(--u)); padding: calc(30 * var(--u)) calc(32 * var(--u)) calc(26 * var(--u)); }
.ask.confirm { max-width: calc(640 * var(--u)); }
.ask-row { display: flex; gap: calc(24 * var(--u)); align-items: center; }
.pic.small { width: calc(170 * var(--u)); height: calc(128 * var(--u)); aspect-ratio: auto; border-radius: calc(18 * var(--u)); flex: none; }
.pic.faded { filter: grayscale(1); opacity: 0.45; }
.ask h2 { font-size: calc(32 * var(--u)); text-wrap: balance; }
.detail { color: var(--a-ink-2); font-size: calc(19 * var(--u)); line-height: 1.35; margin: 8px 0 0; }
.error { color: var(--a-red-text); font-size: calc(17 * var(--u)); font-weight: 600; margin: 8px 0 0; }
.actions { display: flex; gap: 12px; margin-top: calc(24 * var(--u)); justify-content: flex-end; }
.actions .a-btn { flex: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: calc(58 * var(--u)); padding: 0 calc(26 * var(--u)); font-size: calc(22 * var(--u)); border-radius: calc(24 * var(--u)); }

/* a phone: the same, as a sheet from the bottom */
.scrim.compact { align-items: flex-end; padding: 0; }
.compact .sheet { border-radius: 28px 28px 0 0; max-width: none; box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.18); padding: 10px 22px calc(40px + env(safe-area-inset-bottom, 0px)); }
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
.compact .fs { display: block; }
.compact .pic { height: 176px; aspect-ratio: auto; border-radius: 18px; }
.compact .colors { top: 10px; right: 10px; }
.compact .colors i { width: 15px; height: 15px; border-width: 1.5px; }
.compact .fs h2 { font-size: 26px; margin: 14px 0 2px; letter-spacing: -0.02em; }
.compact .meta { font-size: 15px; }
.compact .fit { font-size: 15px; margin-top: 10px; }
.compact .fit i { width: 18px; height: 18px; }
.compact .fit .ok { width: 17px; height: 17px; }
.compact .hist { font-size: 14px; margin-top: 6px; }
.compact .grow { display: none; }
.compact .print { min-height: 54px; font-size: 18px; border-radius: 18px; margin-top: 16px; }
.compact .quiet { width: 100%; justify-content: center; height: 44px; font-size: 16px; margin-top: 6px; }
.compact .awaynote { font-size: 15px; margin-top: 16px; }
.compact .ask-row { flex-direction: column; align-items: stretch; gap: 16px; }
.compact .pic.small { width: 100%; height: 140px; }
.compact .ask h2 { font-size: 24px; }
.compact .detail { font-size: 16px; }
.compact .actions { flex-direction: column-reverse; gap: 8px; margin-top: 18px; }
.compact .actions .a-btn { width: 100%; min-height: 52px; font-size: 18px; border-radius: 18px; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }
</style>
