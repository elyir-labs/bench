<template>
  <section class="print" :class="{ away: door.away, compact }">
    <!-- The Print tab (design/print-library/, B "a shelf and a door", chosen 3 October 2026): a short
         shelf, New from the slicer above Recent, and "Everything on Workshop" beside the title and again at
         the end, which opens the library. Tapping a file opens its sheet; nothing prints on one tap. -->
    <div class="trow">
      <h1 class="a-display title">Print</h1>
      <router-link v-if="total" to="/print/library" class="every" :class="{ link: compact }">
        <template v-if="compact">Everything <span class="n a-num">{{ total }}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg></template>
        <template v-else>Everything on {{ printer }} <span class="n a-num">{{ total }}</span></template>
      </router-link>
    </div>
    <BusyBanner then="pick the next print" />
    <WarmStrip />
    <p class="sub away" v-if="door.away">These are your recent prints. Start one at the printer, where you can check the bed is clear.</p>

    <!-- Newer prints use other settings (design/getting-started/, c-slice-newer): one line, never a switch -->
    <NewerCard v-if="canSlice && offer" :offer="offer" :busy="newerBusy" :error="newerError" @use="useNewer" @keep="keepCurrent" />

    <!-- Print a model (design/print-a-model/): a phone or computer has files to pick, the panel doesn't.
         Not away yet: the door doesn't let /slice through. Not on a printer that doesn't slice.
         Slicing like their prints (docs/slicer-profile.md): the first time, it says what it found in their files
         first; when no file says how it was sliced, it says how to fix that instead of opening anything. -->
    <div v-if="canSlice && waits" class="add waits" role="note">
      <span class="plus" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg></span>
      <span class="add-t"><b>Print a model</b><span>{{ NONE_WORDS }}</span></span>
    </div>
    <label v-else-if="canSlice" class="add" :class="{ asking: slicing?.state === 'waiting' }" @click="onAdd">
      <input ref="fileIn" type="file" multiple accept=".stl,.obj,.step,.stp,.3mf" class="file-input" :disabled="slicing?.state === 'waiting'" @change="pickModel" />
      <span class="plus" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg></span>
      <span class="add-t"><b>Print a model</b><span v-if="slicing?.state === 'waiting'">{{ askingWords(slicing.name, printer) }}</span><span v-else>An STL or 3MF from your phone or computer, or a few to print together. <template v-if="learned(profile)">{{ LIKE_YOURS }}</template><template v-else>I'll set it up for {{ intent?.printer?.name || 'this printer' }}.</template></span></span>
    </label>

    <div v-if="lib.loaded.value && !total" class="empty">
      <div class="art" aria-hidden="true">
        <svg viewBox="0 0 120 80"><rect x="6" y="14" width="44" height="32" rx="5" fill="none" stroke="currentColor" stroke-width="3"/><path d="M20 54h16" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M58 30h22" stroke="var(--a-accent)" stroke-width="4" stroke-linecap="round"/><path d="M73 22l9 8-9 8" fill="none" stroke="var(--a-accent)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><path d="M90 8h22v22H90zM94 30v26h14V30" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M96 62h10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
      </div>
      <div>
        <h2 class="a-display">Nothing on {{ printer }} yet</h2>
        <p class="sub">Send a file from your slicer and it shows up here, under New.</p>
        <p class="hint">In OrcaSlicer or PrusaSlicer, choose Send and pick {{ printer }}.</p>
      </div>
    </div>

    <template v-if="shelf.fresh.length">
      <p class="sec">New <em>from your slicer</em></p>
      <div class="news">
        <NewCard
          v-for="f in shelf.fresh" :key="f.filename"
          :item="f" :check="checks[f.filename]" :now="now" :printer="printer"
          :removed="removed.has(f.filename)" :disabled="inert"
          @open="openFile"
        />
      </div>
    </template>

    <template v-if="shelf.recent.length">
      <p class="sec">Recent</p>
      <div class="grid">
        <FileTile
          v-for="(j, i) in shelf.recent" :key="j.filename"
          :item="j" :check="checks[j.filename]" where="shelf" :now="now" :printer="printer"
          :again="i === 0 && j.onPrinter" :removed="removed.has(j.filename)" :disabled="inert"
          @open="openFile"
        />
      </div>
    </template>

    <router-link v-if="total" to="/print/library" class="door">
      <span class="mini" aria-hidden="true"><ObjectImage v-for="p in shelf.peek" :key="p.filename" :src="thumbOf(p)" class="m" /></span>
      <span class="w"><b>Everything on {{ printer }}</b><span>{{ total }} {{ total === 1 ? 'file' : 'files' }}, newest first. Filter by what fits, what's new, how long.</span></span>
      <svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
    </router-link>

    <FileSheet :item="opened" :check="opened ? checks[opened.filename] : null" :printer="printer" @close="opened = null" @refused="c => (refusal = c)" />
    <PrintCheckSheet :check="refusal" @close="refusal = null" />
    <FoundSheet :open="sheet === 'found'" :view="foundSheet" :busy="!!useBusy" :error="sheetError" @close="sheet = null" @pick="pick" @others="sheet = 'list'" />
    <ProfilesSheet
      :open="sheet === 'list' || sheet === 'ask'" :view="listSheet" :back="sheet === 'list'" :busy="useBusy" :error="sheetError"
      @close="sheet = null" @back="sheet = 'found'" @use="useProfile"
    />
  </section>
</template>

<script setup lang="ts">
import WarmStrip from '@/components/warm/WarmStrip.vue'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import ObjectImage from '@/components/now/ObjectImage.vue'
import BusyBanner from '@/components/now/BusyBanner.vue'
import PrintCheckSheet from '@/components/print/PrintCheckSheet.vue'
import FileTile from '@/components/print/FileTile.vue'
import NewCard from '@/components/print/NewCard.vue'
import FileSheet from '@/components/print/FileSheet.vue'
import { useLibrary } from '@/print/useLibrary'
import type { Item } from '@/print/library'
import { door } from '@/door'
import { isPanel } from '@/theme'
import { layout } from '@/shell/useLayout'
import { begin, useMoonraker } from '@/slice/session'
import { slicerStatus } from '@/slice/api'
import { askingWords, type SlicerState } from '@/slice/elsewhere'
import FoundSheet from '@/components/profile/FoundSheet.vue'
import ProfilesSheet from '@/components/profile/ProfilesSheet.vue'
import NewerCard from '@/components/profile/NewerCard.vue'
import {
  LIKE_YOURS, NONE_WORDS, firstSheet, foundView, inUse, learned, listView, newerOffer, slicingWaits, type ProfileInfo,
} from '@/intent/profile'

const store = useIntentStore()
const router = useRouter()
const lib = useLibrary()
const intent = computed(() => store.intent)
const printer = computed(() => intent.value?.printer?.name || 'the printer')
const compact = computed(() => layout.value === 'compact')
const shelf = computed(() => lib.shelf.value)
const total = computed(() => shelf.value.total)
const checks = computed(() => lib.checks.value)
const removed = computed(() => lib.removed.value)
const now = computed(() => lib.now.value)
// whether something slices for this printer, here or elsewhere (design/slicing-elsewhere/, A)
const slicing = ref<SlicerState | null>(null)
if (!isPanel) void slicerStatus(true).then(v => { slicing.value = v })
// Busy: the tab is inert, as before. Away, tiles still open, to look (the sheet has no Print).
const inert = computed(() => intent.value?.state !== 'ready')

const opened = ref<Item | null>(null)
const refusal = ref<PrintCheck | null>(null)
function openFile(i: Item) {
  if (inert.value) return
  opened.value = i
}
const thumbOf = (i: Item) => store.thumbOf({ filename: i.filename, metadata: i.meta } as any)

// ---- Slicing like their prints (design/getting-started/ C; docs/slicer-profile.md) --------------------
// Where Print a model shows: a phone or computer, at home, with something that slices for this printer
const canSlice = computed(() => !isPanel && !door.away && !!slicing.value && slicing.value.state !== 'none' && slicing.value.state !== 'refused')
// What the printer learned from its own files; null on a printer that doesn't say (it slices as before)
const profile = ref<ProfileInfo | null>(null)
async function loadProfile() {
  if (isPanel || !store.connected) return
  try {
    profile.value = await store.call<ProfileInfo>('printer.intent.profile')
  } catch {
    profile.value = null
  }
}
watch(() => store.connected, (on) => { if (on) void loadProfile() }, { immediate: true })

const waits = computed(() => slicingWaits(profile.value))
const offer = computed(() => newerOffer(profile.value))
const loaded = computed(() => (intent.value?.spools ?? []).map((s) => s.material))
const sheet = ref<'found' | 'list' | 'ask' | null>(null)
const sheetError = ref<string | null>(null)
const useBusy = ref<string | null>(null)
const foundSheet = computed(() => {
  const p = inUse(profile.value)
  return profile.value && p ? foundView(profile.value, p, loaded.value) : null
})
const listSheet = computed(() => (profile.value ? listView(profile.value, printer.value) : null))
watch(sheet, () => { sheetError.value = null })

const fileIn = ref<HTMLInputElement | null>(null)
/** The first time (or when their files disagree), Print a model says what it slices like before the file. */
function onAdd(e: MouseEvent) {
  if (e.target === fileIn.value || slicing.value?.state === 'waiting') return   // the picker opening from Pick a model; or asking
  const first = firstSheet(profile.value)
  if (!first) return
  e.preventDefault()
  sheet.value = first
}

/** Pick a model: said once, then straight on to the file, inside the same tap (a browser only opens it from one). */
function pick() {
  if (profile.value) profile.value = { ...profile.value, told: true }
  sheet.value = null
  void store.act('profile_told')
  fileIn.value?.click()
}

/** Slice like that one: the printer writes its presets, then the found sheet says what it is now. */
async function useProfile(id: string) {
  const p = profile.value
  if (p && p.state !== 'ask' && id === p.using) { sheet.value = 'found'; return }
  sheetError.value = null
  useBusy.value = id
  await store.act('profile_use', { id })
  const failed = store.actionError
  await loadProfile()
  useBusy.value = null
  if (failed) { sheetError.value = failed; return }
  sheet.value = firstSheet(profile.value) === 'found' ? 'found' : null
}

const newerBusy = ref<'use' | 'keep' | null>(null)
const newerError = ref<string | null>(null)
async function newer(which: 'use' | 'keep') {
  const o = offer.value
  if (!o) return
  newerError.value = null
  newerBusy.value = which
  if (which === 'use') await store.act('profile_use', { id: o.id })
  else await store.act('profile_keep')
  const failed = store.actionError
  await loadProfile()
  newerBusy.value = null
  if (failed) newerError.value = failed
}
const useNewer = () => newer('use')
const keepCurrent = () => newer('keep')

function pickModel(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  useMoonraker(store.call)
  void begin(files, intent.value?.spools ?? [], intent.value?.printer?.name)
  router.push('/print/model')
}
</script>

<style scoped>
.print { flex: 1; padding: calc(8 * var(--u) + 4px) calc(28 * var(--u) + 8px) calc(16 * var(--u) + 6px); overflow: auto; }
.trow { display: flex; align-items: center; gap: 14px; min-height: calc(32 * var(--u) + 16px); }
.title { font-size: calc(30 * var(--u) + 8px); margin: 0; flex: 1; }
.every {
  display: inline-flex; align-items: center; gap: 8px; flex: none; text-decoration: none; white-space: nowrap;
  height: 48px; padding: 0 22px; border-radius: 24px; font-weight: 600; font-size: calc(16 * var(--u) + 4px);
  background: var(--a-ghost-bg); border: 1px solid var(--a-line); color: var(--a-ink-2);
}
.every .n { opacity: 0.6; }
.every.link { height: auto; padding: 6px 0; border: 0; background: none; color: var(--a-accent-text); font-size: 15px; gap: 2px; }
.every.link .n { margin-left: 4px; }
.every svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.sub { color: var(--a-ink-2); font-size: calc(17 * var(--u) + 5px); margin: 0; max-width: 40ch; line-height: 1.3; }
.sub.away { margin: calc(6 * var(--u) + 4px) 0 calc(12 * var(--u) + 4px); }
.sec { font-size: calc(4 * var(--u) + 9px); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--a-ink-3); margin: calc(5 * var(--u) + 13px) 0 calc(3 * var(--u) + 6px); display: flex; align-items: baseline; gap: 10px; }
.trow + .sec { margin-top: 12px; }
.sec em { font-style: normal; font-weight: 600; letter-spacing: 0; text-transform: none; font-size: calc(5 * var(--u) + 10px); }
.add {
  position: relative; display: flex; align-items: center; gap: 14px; cursor: pointer;
  background: var(--a-surface); border-radius: 20px; padding: 16px; margin: calc(12 * var(--u)) 0 calc(4 * var(--u));
  box-shadow: var(--a-card-shadow);
}
.add:focus-within { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.add.asking { opacity: .62; cursor: default; }
.add.waits { cursor: default; }
.add.waits .plus { background: var(--a-surface-2); color: var(--a-ink-3); }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.plus { width: 52px; height: 52px; border-radius: 16px; background: var(--a-accent); color: var(--a-accent-ink); display: grid; place-items: center; flex: none; }
.plus svg { width: 28px; height: 28px; }
.add-t { display: grid; gap: 1px; min-width: 0; }
.add-t b { font-size: 19px; }
.add-t span { font-size: 14px; color: var(--a-ink-3); line-height: 1.3; }
.news { display: grid; grid-template-columns: 1fr 1fr; gap: calc(13 * var(--u) + 3px); }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: calc(13 * var(--u) + 3px); }
.compact .news { grid-template-columns: 1fr; gap: 10px; }
.compact .grid { grid-template-columns: 1fr 1fr; }

/* the way into the library, at the end of the shelf */
.door {
  margin-top: calc(13 * var(--u) + 3px); display: flex; align-items: center; gap: 16px; height: calc(60 * var(--u) + 24px);
  padding: 0 calc(16 * var(--u) + 4px) 0 14px; border-radius: calc(13 * var(--u) + 9px);
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: inherit; text-decoration: none;
}
.mini { display: flex; flex: none; }
.mini .m { width: calc(64 * var(--u)); height: calc(56 * var(--u)); border-radius: 12px; border: 3px solid var(--a-surface); margin-left: calc(-18 * var(--u)); }
.mini .m:first-child { margin-left: 0; }
.door .w { flex: 1; display: grid; gap: 1px; min-width: 0; }
.door .w b { font-size: calc(16 * var(--u) + 7px); font-family: var(--a-display); }
.door .w span { font-size: calc(8 * var(--u) + 8px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chev { width: 26px; height: 26px; color: var(--a-ink-3); flex: none; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }

/* nothing on the printer */
.empty { display: flex; gap: calc(30 * var(--u)); align-items: center; margin-top: calc(26 * var(--u)); }
.empty .art {
  width: calc(232 * var(--u)); height: calc(190 * var(--u)); flex: none; border-radius: 24px;
  outline: 2px dashed var(--a-swatch-empty); outline-offset: -2px; display: grid; place-items: center; color: var(--a-ink-3);
}
.empty .art svg { width: calc(150 * var(--u)); }
.empty h2 { font-size: calc(32 * var(--u)); font-weight: 700; letter-spacing: -0.025em; margin: 0 0 8px; }
.empty .sub { font-size: calc(21 * var(--u)); }
.empty .hint { font-size: calc(17 * var(--u)); color: var(--a-ink-3); margin: 10px 0 0; }
.compact .empty { flex-direction: column; align-items: flex-start; }
.compact .empty .art { width: 100%; height: 150px; }
.compact .empty h2 { font-size: 24px; }
.compact .empty .sub { font-size: 17px; }
.compact .empty .hint { font-size: 14px; }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
</style>
