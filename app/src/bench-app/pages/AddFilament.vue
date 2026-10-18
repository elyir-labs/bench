<template>
  <!-- Add a filament (design/bench-material/, B): one of Orca's library, then its color; kept for every printer. -->
  <SliceSheet :open="open" title="Add a filament" sub="From Orca's library. It's added for every printer." wide @close="$emit('close')">
    <input v-model="q" class="search" type="search" :placeholder="total ? `Search ${total} filaments` : 'Search filaments'" aria-label="Search filaments" />
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <div class="found" role="radiogroup" aria-label="Filament">
      <button v-for="f in found" :key="f.preset" role="radio" :aria-checked="picked?.preset === f.preset" class="frow" :class="{ on: picked?.preset === f.preset }" @click="picked = f">
        <span class="t"><b>{{ filamentTitle(f) }}</b><span>{{ f.material }}</span></span>
        <span v-if="picked?.preset === f.preset" class="tick" aria-hidden="true">✓</span>
      </button>
      <p v-if="!found.length && !error" class="none">{{ q ? `Nothing called “${q}”.` : 'Looking…' }}</p>
    </div>
    <p class="lbl">Its color</p>
    <div class="colors" role="radiogroup" aria-label="Color">
      <button v-for="c in COLORS" :key="c.hex" role="radio" :aria-checked="color === c.hex" :aria-label="c.name" class="sw" :class="{ on: color === c.hex }"
              :style="{ background: c.hex }" @click="color = c.hex"></button>
      <label class="sw other" :class="{ on: !COLORS.some((c) => c.hex === color) }"><input v-model="color" type="color" aria-label="Another color" />Other</label>
    </div>
    <div class="go">
      <span class="what">{{ picked ? `${colorName(color) || 'This color'} ${filamentTitle(picked)}` : 'Pick one above' }}</span>
      <button class="a-btn accent" :disabled="!picked || busy" @click="add">{{ busy ? '…' : 'Add' }}</button>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import { COLORS } from '@/components/materials/palette'
import { colorName, filamentTitle, type MyFilament } from '../shelf'
import { addMine, searchLibrary, type LibraryFilament } from '../shelf-api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; added: [f: MyFilament] }>()
const q = ref('')
const found = ref<LibraryFilament[]>([])
const total = ref(0)
const picked = ref<LibraryFilament | null>(null)
const color = ref(COLORS[0].hex)
const busy = ref(false)
const error = ref<string | null>(null)

let timer = 0, asked = 0
async function search() {
  const mine = ++asked
  try {
    const r = await searchLibrary(q.value.trim())
    if (mine !== asked) return
    found.value = r.filaments
    total.value = r.total
    error.value = null
  } catch (e) {
    if (mine === asked) error.value = (e as Error).message
  }
}
watch(q, () => { window.clearTimeout(timer); timer = window.setTimeout(search, 200) })
watch(() => props.open, (o) => { if (o) { picked.value = null; error.value = null; search() } }, { immediate: true })

async function add() {
  if (!picked.value) return
  busy.value = true
  try {
    const f = await addMine({ preset: picked.value.preset, name: picked.value.name, brand: picked.value.brand,
                              material: picked.value.material, color: color.value.toUpperCase() })
    emit('added', f)
    emit('close')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.search { width: 100%; box-sizing: border-box; height: 48px; padding: 0 14px; border-radius: 14px; border: 1.5px solid var(--a-line); background: var(--a-surface); color: var(--a-ink); font: inherit; font-size: 17px; }
.found { display: grid; gap: 1px; margin-top: 12px; max-height: 260px; overflow: auto; border-radius: 14px; background: var(--a-line); }
.frow { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px; padding: 11px 14px; background: var(--a-surface); }
.frow.on { box-shadow: inset 0 0 0 2px var(--a-accent); }
.frow .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.frow .t b { font-size: 16px; } .frow .t span { font-size: 13px; color: var(--a-ink-3); }
.tick { color: var(--a-accent); font-weight: 800; }
.none { margin: 0; padding: 14px; background: var(--a-surface); color: var(--a-ink-3); font-size: 15px; }
.lbl { margin: 16px 0 8px; font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.colors { display: flex; flex-wrap: wrap; gap: 8px; }
.sw { width: 36px; height: 36px; border-radius: 50%; border: 2px solid var(--a-swatch-edge, rgba(0,0,0,.15)); cursor: pointer; padding: 0; }
.sw.on { outline: 3px solid var(--a-accent); outline-offset: 2px; }
.sw.other { width: auto; padding: 0 12px; display: inline-flex; align-items: center; gap: 6px; background: var(--a-surface); font-size: 14px; font-weight: 650; color: var(--a-ink-2); }
.sw.other input { width: 22px; height: 22px; border: 0; padding: 0; background: none; }
.go { display: flex; align-items: center; gap: 12px; margin-top: 18px; }
.what { flex: 1; color: var(--a-ink-3); font-size: 15px; }
.go .a-btn { flex: none; height: 50px; padding: 0 30px; border-radius: 99px; font-size: 18px; }
.err { margin: 8px 0 0; color: var(--a-red-text); font-size: 14px; }
</style>
