<template>
  <!-- Spool tags (design/spool-tags/, round 1 C + round 2 A): hold a tag on the reader and this comes up, on any
       screen. Blank: which spool is it for. Written: what it says. The printer keeps the steps. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="sheet" class="scrim">
        <div class="sheet" :class="{ wide: sheet.step === 'library' }" role="dialog" aria-modal="true" :aria-label="title">

          <!-- which spool is this tag for -->
          <template v-if="sheet.step === 'which'">
            <div class="split">
              <div class="main">
                <span class="chipline">{{ chipLine(sheet.tag) }}</span>
                <h2 class="a-display">{{ sheet.over ? 'What should it say instead?' : 'Which spool is this tag for?' }}</h2>
                <div class="choices">
                  <button
                    v-for="(c, i) in quick" :key="c.kind + (c.slot ?? c.index)" class="choice" :class="{ first: i === 0 }"
                    :disabled="busy" @click="pickChoice(c)"
                  >
                    <i class="sw" :style="{ background: swatch(c.color) }"></i>
                    <span class="t"><b>{{ c.label }}</b><span>{{ c.sub }}</span></span>
                  </button>
                  <button class="choice" :disabled="busy" @click="send('tag_library')">
                    <i class="sw dashed"></i>
                    <span class="t"><b>Another spool</b><span>Search the filament library by brand</span></span>
                  </button>
                </div>
              </div>
              <TagArt class="art" :on="!!sheet.tag" />
            </div>
            <div class="acts end"><button class="a-btn ghost" @click="close">Not now</button></div>
          </template>

          <!-- the library -->
          <template v-else-if="sheet.step === 'library'">
            <div class="search">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4" /></svg>
              <input ref="field" v-model="q" type="search" placeholder="Brand, material or color" aria-label="Search filaments" />
              <button class="a-btn ghost small" @click="send('tag_back')">Back</button>
            </div>
            <div class="brands" role="radiogroup" aria-label="Brand">
              <button v-for="b in brandChips" :key="b" class="chip" :class="{ on: brand === b }" role="radio"
                      :aria-checked="brand === b" @click="brand = brand === b ? '' : b">{{ b }}</button>
            </div>
            <div class="results">
              <template v-if="!q && !brand && sheet.choices?.length">
                <p class="group">Here now</p>
                <div class="choices here">
                  <button v-for="c in sheet.choices" :key="c.kind + (c.slot ?? c.index)" class="choice" :disabled="busy" @click="pickChoice(c)">
                    <i class="sw" :style="{ background: swatch(c.color) }"></i>
                    <span class="t"><b>{{ c.label }}</b><span>{{ c.sub }}</span></span>
                  </button>
                </div>
                <p class="group">The library</p>
              </template>
              <p v-if="searching && !results.length" class="note">Looking…</p>
              <p v-else-if="!results.length" class="note">Nothing in the library matches. Try the brand alone, or the material.</p>
              <div v-for="p in results" :key="p.id" class="prod">
                <div class="pt"><b>{{ productName(p) }}</b><span>{{ p.brand }}<template v-if="p.nozzle"> · {{ p.nozzle[0] }}–{{ p.nozzle[1] }} °C</template></span></div>
                <div class="cols">
                  <button
                    v-for="c in p.colors.slice(0, 18)" :key="c.name" class="dot" :class="{ hit: c.hit }"
                    :style="{ background: swatch(c.hex) }" :aria-label="`${productName(p)} ${c.name}`" :title="c.name"
                    :disabled="busy" @click="pickProduct(p.id, c.name)"
                  ></button>
                  <em v-if="p.colors.length > 18">+{{ p.colors.length - 18 }}</em>
                </div>
              </div>
            </div>
          </template>

          <!-- ready to write -->
          <template v-else-if="sheet.step === 'write'">
            <div class="split">
              <div class="main">
                <div class="spoolhead">
                  <i class="sw big" :style="{ background: swatch(sheet.color) }"></i>
                  <div><h2 class="a-display">{{ sheet.label }}</h2><p class="sub">{{ fromWhere }}</p></div>
                </div>
                <div class="facts"><span v-for="f in sheet.facts" :key="f">{{ f }}</span></div>
                <div v-if="sheet.format_name" class="fmt">
                  <span>Writes as <b>{{ sheet.format_name }}</b><template v-if="sheet.readers"> · {{ sheet.readers }}</template></span>
                  <button class="link" :disabled="busy || !sheet.tag" @click="send('tag_formats')">Change</button>
                </div>
                <p v-if="sheet.waiting || !sheet.tag" class="note warn">Put the tag back on the reader, then Write.</p>
              </div>
              <TagArt class="art" :on="!!sheet.tag" />
            </div>
            <div class="acts">
              <button class="a-btn ghost" :disabled="sheet.writing" @click="send('tag_back')">Back</button>
              <span class="grow"></span>
              <button class="a-btn accent" :disabled="busy || sheet.writing || !sheet.tag" @click="send('tag_write')">
                {{ sheet.writing ? 'Writing…' : 'Write' }}
              </button>
            </div>
          </template>

          <!-- every format, and why not -->
          <template v-else-if="sheet.step === 'formats'">
            <h2 class="a-display">Write this tag as</h2>
            <p class="sub">It's {{ article(sheet.tag?.chip) }} {{ sheet.tag?.chip }}. One format fits on a tag at a time.</p>
            <div class="formats" role="radiogroup" aria-label="Format">
              <button
                v-for="f in sheet.formats" :key="f.id" class="fmtrow" role="radio" :aria-checked="f.id === sheet.format"
                :class="{ on: f.id === sheet.format, off: !!f.why_not }" :disabled="!!f.why_not || busy"
                @click="send('tag_format', { format: f.id })"
              >
                <i class="radio" :class="{ on: f.id === sheet.format }"></i>
                <span class="t"><b>{{ f.name }}</b><span>{{ f.why_not || f.readers }}</span></span>
              </button>
            </div>
            <div class="acts end"><button class="a-btn accent" @click="send('tag_back')">Done</button></div>
          </template>

          <!-- written -->
          <template v-else-if="sheet.step === 'written'">
            <div class="split">
              <div class="main">
                <div class="spoolhead">
                  <span class="ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
                  <div><h2 class="a-display">Tag written: {{ sheet.label }}</h2></div>
                </div>
                <div class="facts"><span v-for="f in sheet.facts" :key="f">{{ f }}</span></div>
                <p class="lead">Stick it on the side of the spool. {{ readersLine(sheet.format_name, sheet.readers) }}</p>
              </div>
              <TagArt class="art" done />
            </div>
            <div class="acts end"><button class="a-btn accent" @click="close">Done</button></div>
          </template>

          <!-- a written tag, read back -->
          <template v-else-if="sheet.step === 'read'">
            <div class="split">
              <div class="main">
                <div class="spoolhead">
                  <i class="sw big" :style="{ background: swatch(sheet.color) }"></i>
                  <div><h2 class="a-display">This tag says {{ sheet.label }}</h2><p class="sub">{{ sheet.format_name }} · {{ sheet.tag?.chip }}</p></div>
                </div>
                <div class="facts"><span v-for="f in sheet.facts" :key="f">{{ f }}</span></div>
              </div>
              <TagArt class="art" done />
            </div>
            <div class="acts">
              <button class="link" :disabled="busy" @click="send('tag_copy')">Copy onto a blank tag</button>
              <button class="link" :disabled="busy" @click="send('tag_rewrite')">Write something else on it</button>
              <span class="grow"></span>
              <button class="a-btn accent" @click="close">Done</button>
            </div>
          </template>

          <!-- copying: waiting for a blank tag -->
          <template v-else-if="sheet.step === 'copy'">
            <div class="split">
              <div class="main">
                <span class="chipline">Copying {{ sheet.label }}</span>
                <h2 class="a-display">Now hold a blank tag on the reader</h2>
                <p class="lead">Lift this one off first. The copy is written for the same spool, in the format that fits the new tag.</p>
              </div>
              <TagArt class="art" :on="false" />
            </div>
            <div class="acts end"><button class="a-btn ghost" @click="close">Cancel</button></div>
          </template>

          <!-- something Bench can't read -->
          <template v-else-if="sheet.step === 'unknown'">
            <span class="chipline">{{ sheet.tag?.chip }}</span>
            <h2 class="a-display">This tag has something else on it</h2>
            <p class="lead">Bench can't read what's written on it. Writing over it replaces that for good.</p>
            <div class="acts end">
              <button class="a-btn ghost" @click="close">Not now</button>
              <button class="a-btn accent" :disabled="busy" @click="send('tag_rewrite')">Write over it</button>
            </div>
          </template>

          <!-- the write didn't take -->
          <template v-else-if="sheet.step === 'failed'">
            <span class="chipline">{{ sheet.label }}</span>
            <h2 class="a-display">The tag wasn't written</h2>
            <p class="lead">{{ sheet.why }}</p>
            <div class="acts end">
              <button class="a-btn ghost" @click="close">Not now</button>
              <button class="a-btn accent" :disabled="busy || sheet.writing" @click="send('tag_write')">{{ sheet.writing ? 'Writing…' : 'Try again' }}</button>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { chipLine, productName, quickChoices, readersLine, swatch, type LibraryProduct, type TagChoice } from '@/intent/tags'
import TagArt from './TagArt.vue'

const store = useIntentStore()
const sheet = computed(() => store.intent?.tags?.sheet ?? null)
const busy = computed(() => store.busyAction !== null)
const quick = computed(() => quickChoices(sheet.value?.choices))
const title = computed(() => (sheet.value?.step === 'which' ? 'Which spool is this tag for?' : sheet.value?.label ?? 'Spool tag'))
const fromWhere = computed(() => {
  const src = (sheet.value?.spool as { source?: string } | undefined)?.source
  return src === 'library' ? 'From the filament library' : src === 'slot' ? 'As this printer knows it' : 'Written here before'
})

function send(id: string, args: Record<string, unknown> = {}) {
  void store.act(id, args)
}
function close() {
  send('tag_close')
}
function pickChoice(c: TagChoice) {
  send('tag_pick', c.kind === 'slot' ? { slot: c.slot } : { history: c.index })
}
function pickProduct(product: number, color: string) {
  send('tag_pick', { product, color })
}
function article(chip?: string) {
  return chip && /^[AEIOU]|^NTAG|^MIFARE/i.test(chip) ? 'an' : 'a'
}

// ---- the library: searched on the printer as you type ----
const q = ref('')
const brand = ref('')
const results = ref<LibraryProduct[]>([])
const brandChips = ref<string[]>([])
const searching = ref(false)
const field = ref<HTMLInputElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null
let asked = 0

async function search() {
  const n = ++asked
  searching.value = true
  try {
    const r = await store.call<{ results: LibraryProduct[]; brands: string[] | null }>(
      'printer.intent.filaments', { q: q.value, brand: brand.value })
    if (n !== asked) return
    results.value = r.results
    if (r.brands) brandChips.value = r.brands.slice(0, 8)
  } catch {
    if (n === asked) results.value = []
  } finally {
    if (n === asked) searching.value = false
  }
}
watch([q, brand], () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(search, 180)
})
watch(() => sheet.value?.step, (step) => {
  if (step === 'library') {
    q.value = ''
    brand.value = ''
    void search()
    void nextTick(() => { if (window.matchMedia('(pointer: fine)').matches) field.value?.focus() })
  }
})
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, 0.55); display: flex; align-items: flex-end; justify-content: center; }
.sheet { background: var(--a-bg); border-radius: calc(22 * var(--u) + 8px) calc(22 * var(--u) + 8px) 0 0; box-shadow: var(--a-card-shadow); width: 100%; max-width: 980px; max-height: 100%; overflow: auto; padding: calc(14 * var(--u) + 8px) calc(16 * var(--u) + 10px) calc(12 * var(--u) + 8px); }
.sheet.wide { height: 100%; border-radius: 0; display: flex; flex-direction: column; }
.split { display: flex; gap: calc(14 * var(--u) + 8px); align-items: center; }
.main { flex: 1; min-width: 0; }
.art { flex: none; width: calc(110 * var(--u) + 40px); }
h2 { font-size: calc(20 * var(--u) + 8px); line-height: 1.1; margin: 6px 0 0; text-wrap: balance; }
.sub { color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); margin: 2px 0 0; }
.lead { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 4px); margin: 12px 0 0; line-height: 1.4; }
.chipline { display: inline-block; font-size: calc(10 * var(--u) + 4px); color: var(--a-ink-3); background: var(--a-surface-2); border-radius: 99px; padding: 4px 10px; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: calc(6 * var(--u) + 4px); margin-top: calc(10 * var(--u) + 4px); }
.choice { appearance: none; border: 2px solid transparent; background: var(--a-surface); color: var(--a-ink); border-radius: calc(12 * var(--u) + 4px); padding: calc(8 * var(--u) + 4px) calc(10 * var(--u) + 4px); display: flex; align-items: center; gap: 12px; text-align: left; font: inherit; cursor: pointer; min-height: 56px; }
.choice.first { border-color: color-mix(in srgb, var(--a-accent) 55%, transparent); }
.choice:active { transform: scale(0.98); }
.t { display: flex; flex-direction: column; min-width: 0; }
.t b { font-size: calc(13 * var(--u) + 4px); }
.t span { font-size: calc(10 * var(--u) + 4px); color: var(--a-ink-3); }
.sw { width: calc(18 * var(--u) + 14px); height: calc(18 * var(--u) + 14px); border-radius: 50%; flex: none; border: 2px solid rgba(0, 0, 0, 0.3); }
.sw.big { width: calc(34 * var(--u) + 22px); height: calc(34 * var(--u) + 22px); }
.sw.dashed { border: 2px dashed var(--a-ink-3); background: transparent; }
.spoolhead { display: flex; align-items: center; gap: calc(10 * var(--u) + 6px); }
.spoolhead h2 { margin: 0; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: calc(8 * var(--u) + 4px); }
.facts span { background: var(--a-surface-2); color: var(--a-ink-2); border-radius: 99px; padding: 5px 12px; font-size: calc(10 * var(--u) + 4px); display: inline-flex; align-items: center; gap: 6px; }
.mini { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.fmt { display: flex; align-items: center; gap: 10px; margin-top: calc(8 * var(--u) + 6px); padding: 10px 14px; border-radius: 12px; background: var(--a-surface-2); font-size: calc(10 * var(--u) + 4px); color: var(--a-ink-2); }
.fmt b { color: var(--a-ink); }
.fmt span { flex: 1; min-width: 0; }
.link { appearance: none; border: 0; background: none; color: var(--a-accent-text, var(--a-accent)); font: inherit; font-weight: 650; font-size: calc(12 * var(--u) + 4px); cursor: pointer; padding: 8px 4px; min-height: 44px; }
.link:disabled { opacity: 0.5; }
.note { color: var(--a-ink-3); font-size: calc(11 * var(--u) + 4px); margin: 10px 0 0; }
.note.warn { color: var(--a-amber-text, var(--a-ink-2)); }
.acts { display: flex; align-items: center; gap: 10px; margin-top: calc(10 * var(--u) + 6px); }
.acts.end { justify-content: flex-end; }
.acts .a-btn { flex: none; width: auto; min-height: 52px; min-width: calc(80 * var(--u) + 40px); padding: 0 calc(16 * var(--u) + 10px); }
.grow { flex: 1; }
.ok { width: calc(30 * var(--u) + 20px); height: calc(30 * var(--u) + 20px); border-radius: 16px; display: grid; place-items: center; flex: none; background: color-mix(in srgb, var(--a-green, #3dd68c) 18%, transparent); color: var(--a-green, #3dd68c); }
.ok svg { width: 60%; height: 60%; fill: none; stroke: currentColor; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.formats { display: grid; grid-template-columns: 1fr 1fr; gap: 7px 10px; margin-top: 12px; }
.fmtrow { appearance: none; font: inherit; color: var(--a-ink); text-align: left; display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 12px; background: var(--a-surface); border: 2px solid transparent; cursor: pointer; min-height: 56px; }
.fmtrow.on { border-color: var(--a-accent); }
.fmtrow.off { opacity: 0.5; cursor: default; }
.radio { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--a-ink-3); flex: none; }
.radio.on { border: 7px solid var(--a-accent); }
.search { display: flex; align-items: center; gap: 10px; background: var(--a-surface); border: 1px solid var(--a-accent); border-radius: 14px; padding: 0 6px 0 14px; min-height: 52px; }
.search svg { width: 20px; height: 20px; fill: none; stroke: var(--a-ink-3); stroke-width: 2.4; stroke-linecap: round; flex: none; }
.search input { flex: 1; min-width: 0; appearance: none; border: 0; background: none; color: var(--a-ink); font: inherit; font-size: calc(14 * var(--u) + 5px); }
.search input:focus { outline: none; }
.a-btn.small { flex: none; width: auto; min-height: 42px; padding: 0 16px; }
.group { font-size: calc(9 * var(--u) + 4px); font-weight: 750; letter-spacing: 0.07em; text-transform: uppercase; color: var(--a-ink-3); margin: 6px 2px 8px; }
.choices.here { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); margin: 0 0 8px; }
.fmtrow .t span::first-letter { text-transform: uppercase; }
.brands { display: flex; gap: 8px; overflow-x: auto; padding: 10px 0; scrollbar-width: none; }
.chip { appearance: none; font: inherit; flex: none; height: 40px; padding: 0 16px; border-radius: 99px; border: 1px solid var(--a-line, rgba(127, 127, 127, 0.2)); background: var(--a-surface); color: var(--a-ink-2); font-weight: 650; font-size: calc(10 * var(--u) + 5px); cursor: pointer; }
.chip.on { background: var(--a-accent); color: #06121f; border-color: transparent; }
.results { flex: 1; overflow: auto; min-height: 0; }
.prod { display: flex; align-items: center; gap: 14px; background: var(--a-surface); border-radius: 14px; padding: 10px 14px; margin-bottom: 8px; }
.pt { width: 34%; flex: none; display: flex; flex-direction: column; min-width: 0; }
.pt b { font-size: calc(12 * var(--u) + 4px); }
.pt span { font-size: calc(10 * var(--u) + 3px); color: var(--a-ink-3); }
.cols { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.dot { appearance: none; width: 34px; height: 34px; border-radius: 50%; border: 2px solid rgba(0, 0, 0, 0.3); cursor: pointer; padding: 0; }
.dot.hit { outline: 3px solid var(--a-accent); outline-offset: 2px; }
.cols em { font-style: normal; font-size: 13px; color: var(--a-ink-3); }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .art { display: none; }
  .choices, .formats { grid-template-columns: 1fr; }
  .prod { flex-direction: column; align-items: flex-start; }
  .pt { width: auto; }
  .acts { flex-wrap: wrap; }
}
</style>
