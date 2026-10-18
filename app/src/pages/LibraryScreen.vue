<template>
  <!-- Everything on the printer (design/print-library/, B): back, the title with its count, search,
       one-tap filters that never scroll away, and every file, newest first. Part of Print: the tabs stay. -->
  <section ref="page" class="lib" :class="{ compact, away: door.away }">
    <div class="head">
      <div class="trow">
        <button class="back" aria-label="Back to Print" @click="router.push('/print')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
        </button>
        <template v-if="!searching || compact">
          <h1 class="a-display title">Everything on {{ printer }}</h1>
          <span v-if="!compact && lib.loaded.value" class="cnt a-num">{{ count }}</span>
          <span class="grow"></span>
          <button v-if="!compact && !door.away" class="ico" aria-label="Search" @click="openSearch">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5l5 5" /></svg>
          </button>
        </template>
        <template v-else>
          <label class="search inline">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5l5 5" /></svg>
            <input ref="field" v-model="query" type="search" :placeholder="`Search ${total} files`" enterkeyhint="search" />
          </label>
          <span v-if="lib.loaded.value" class="cnt a-num">{{ count }}</span>
          <button class="ico" aria-label="Close search" @click="closeSearch">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </template>
      </div>
      <BusyBanner then="pick the next print" />
      <p v-if="door.away" class="awayline">These are the files on {{ printer }}. Start one at the printer, where you can check the bed is clear.</p>
      <label v-else-if="compact" class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5l5 5" /></svg>
        <input v-model="query" type="search" :placeholder="`Search ${total} files`" enterkeyhint="search" />
      </label>
      <div class="chips" role="toolbar" aria-label="Filters">
        <button
          v-for="c in chipList" :key="c.id" class="chip" :class="{ on: filter === c.id }" :aria-pressed="filter === c.id"
          @click="filter = filter === c.id ? null : c.id"
        >
          <svg v-if="c.folder" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5a1.5 1.5 0 0 1 1.5-1.5h4.2l2 2.2H19a1.5 1.5 0 0 1 1.5 1.5V17.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z" /></svg>
          {{ c.label }}<span v-if="c.count != null" class="n a-num">{{ c.count }}</span>
        </button>
      </div>
      <p v-if="compact && lib.loaded.value" class="ln">{{ line }}</p>
    </div>

    <div v-if="visible.length" class="grid">
      <FileTile
        v-for="(f, i) in visible" :key="f.filename"
        :item="f" :check="checks[f.filename]" where="library" :now="now" :printer="printer"
        :removed="removed.has(f.filename)" :disabled="inert"
        @open="open(f, i)"
      />
    </div>
    <p v-else-if="lib.loaded.value" class="none">{{ none }}</p>

    <FileSheet :item="opened" :at="openedAt" :check="opened ? checks[opened.filename] : null" :printer="printer" @close="opened = null" @refused="c => (refusal = c)" />
    <PrintCheckSheet :check="refusal" @close="refusal = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import BusyBanner from '@/components/now/BusyBanner.vue'
import PrintCheckSheet from '@/components/print/PrintCheckSheet.vue'
import FileTile from '@/components/print/FileTile.vue'
import FileSheet from '@/components/print/FileSheet.vue'
import { useLibrary } from '@/print/useLibrary'
import { chips, countLabel, emptyLine, filtered, listLine, type Filter, type Item } from '@/print/library'
import { door } from '@/door'
import { layout } from '@/shell/useLayout'

const store = useIntentStore()
const router = useRouter()
const lib = useLibrary()
const printer = computed(() => store.intent?.printer?.name || 'the printer')
const compact = computed(() => layout.value === 'compact')
const inert = computed(() => store.intent?.state !== 'ready')
const checks = computed(() => lib.checks.value)
const removed = computed(() => lib.removed.value)
const now = computed(() => lib.now.value)

const filter = ref<Filter>(null)
const query = ref('')
const searching = ref(false)
const field = ref<HTMLInputElement | null>(null)
async function openSearch() {
  searching.value = true
  await nextTick()
  field.value?.focus()
}
function closeSearch() {
  searching.value = false
  query.value = ''
}

// a new filter or search starts at the top, under the header
const page = ref<HTMLElement | null>(null)
watch([filter, query], () => page.value?.scrollTo({ top: 0 }))

const total = computed(() => lib.library.value.length)
const chipList = computed(() => chips(lib.items.value))
const matching = computed(() => filtered(lib.items.value, filter.value, query.value, checks.value))
const visible = computed(() => lib.withRemoved(matching.value))
const count = computed(() => countLabel(matching.value.length, total.value, filter.value, query.value))
const line = computed(() => listLine(matching.value.length, filter.value, query.value))
const none = computed(() => emptyLine(filter.value, query.value, printer.value))

const opened = ref<Item | null>(null)
const openedAt = ref(-1)
const refusal = ref<PrintCheck | null>(null)
function open(i: Item, index: number) {
  if (inert.value) return
  opened.value = i
  openedAt.value = index
}
</script>

<style scoped>
.lib { flex: 1; padding: 0 calc(28 * var(--u) + 8px) calc(16 * var(--u) + 6px); overflow: auto; }
/* the header, filters and count never scroll away */
.head { position: sticky; top: 0; z-index: 2; background: color-mix(in srgb, var(--a-bg) 94%, transparent); backdrop-filter: blur(8px); padding: calc(8 * var(--u) + 4px) 0 16px; }
.compact .head { padding-bottom: 0; }
.trow { display: flex; align-items: center; gap: 14px; min-height: calc(21 * var(--u) + 27px); }
.title { font-size: calc(21 * var(--u) + 11px); margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.cnt { color: var(--a-ink-3); font-size: 18px; white-space: nowrap; }
.grow { flex: 1; }
.back, .ico {
  appearance: none; cursor: pointer; flex: none; display: grid; place-items: center; border-radius: 50%;
  width: calc(26 * var(--u) + 22px); height: calc(26 * var(--u) + 22px);
  background: var(--a-ghost-bg); border: 1px solid var(--a-line); color: var(--a-ink);
}
.back svg, .ico svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.ico svg { stroke-width: 2.2; }
.back:focus-visible, .ico:focus-visible, .chip:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.awayline { font-size: calc(5 * var(--u) + 10px); color: var(--a-ink-2); line-height: 1.35; margin: 8px 0 0; max-width: 60ch; }
.search {
  display: flex; align-items: center; gap: 9px; height: 44px; padding: 0 14px; border-radius: 14px;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-ink-3); margin: 12px 0 10px;
}
.search.inline { flex: 1; margin: 0; height: 48px; border-radius: 24px; }
.search svg { width: 18px; height: 18px; flex: none; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; }
.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font: inherit; font-size: 16px; color: var(--a-ink); }
.search.inline input { font-size: 19px; }
.search input::placeholder { color: var(--a-ink-3); }
.chips {
  display: flex; gap: calc(1 * var(--u) + 7px); overflow-x: auto; scrollbar-width: none; margin-top: 12px;
  -webkit-mask-image: linear-gradient(90deg, #000 92%, transparent); mask-image: linear-gradient(90deg, #000 92%, transparent);
}
.chips::-webkit-scrollbar { display: none; }
.compact .chips { margin-top: 0; margin-right: calc(-28 * var(--u) - 8px); padding-right: 22px; }
.chip {
  appearance: none; cursor: pointer; font: inherit; flex: none; white-space: nowrap;
  display: inline-flex; align-items: center; gap: calc(2 * var(--u) + 5px);
  height: calc(21 * var(--u) + 23px); padding: 0 calc(10.5 * var(--u) + 6.5px); border-radius: 99px;
  font-weight: 600; font-size: calc(8 * var(--u) + 9px);
  border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2);
}
.chip.on { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }
.chip svg { width: calc(8 * var(--u) + 10px); height: calc(8 * var(--u) + 10px); fill: none; stroke: currentColor; stroke-width: 2; stroke-linejoin: round; }
.chip .n { opacity: 0.7; }
.ln { font-size: 13px; color: var(--a-ink-3); margin: 12px 0 8px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: calc(13 * var(--u) + 3px); padding-top: 2px; }
.compact .grid { grid-template-columns: 1fr 1fr; }
.none { color: var(--a-ink-2); font-size: calc(17 * var(--u) + 3px); margin: 24px 0 0; max-width: 40ch; line-height: 1.35; }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
</style>
