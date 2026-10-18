<template>
  <!-- One file on the shelf or in the library (design/print-library/, B). Tapping opens its sheet;
       nothing prints from here. A file that's gone says so; a removed one drains where it stood. -->
  <button
    class="tile"
    :class="{ first: again, gone: !item.onPrinter && !removed, removed }"
    :disabled="disabled || removed"
    :aria-label="removed ? `${item.name}, removed` : item.name"
    @click="$emit('open', item)"
  >
    <span class="im">
      <ObjectImage :src="thumb" :alt="item.name" class="img" />
      <span v-if="again && !removed" class="again">Print again</span>
      <span v-if="!removed" class="colors" aria-hidden="true"><i v-for="(c, k) in colors" :key="k" :style="{ background: c }"></i></span>
      <span v-if="removed" class="mark"><span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>Removed</span></span>
    </span>
    <span class="text">
      <span class="name">{{ item.name }}</span>
      <span v-if="removed" class="meta">Removed from {{ printer }}</span>
      <span v-else-if="!item.onPrinter" class="meta gone-words">Not on the printer anymore. Send it again from your slicer.</span>
      <span v-else class="meta a-num">{{ metaLine(item) }}</span>
      <span v-if="removed && where === 'library'" class="l3">&nbsp;</span>
      <span v-else-if="line" class="l3" :class="line.tone">{{ line.text }}</span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ObjectImage from '@/components/now/ObjectImage.vue'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import { metaLine, tileLine, type Item } from '@/print/library'

const props = defineProps<{
  item: Item
  check?: PrintCheck | null
  where: 'shelf' | 'library'
  now: number
  printer: string
  again?: boolean
  removed?: boolean
  disabled?: boolean
}>()
defineEmits<{ open: [item: Item] }>()
const store = useIntentStore()
const thumb = computed(() => store.thumbOf({ filename: props.item.filename, metadata: props.item.meta } as any))
const colors = computed(() => (props.item.colors.length ? props.item.colors.slice(0, 4) : ['#666666']))
const line = computed(() => (props.removed ? null : tileLine(props.item, props.check, props.where, props.now)))
</script>

<style scoped>
.tile {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer;
  background: var(--a-surface);
  border-radius: calc(18 * var(--u) + 6px);
  padding: 0;
  display: flex; flex-direction: column;
  overflow: hidden;
  position: relative;
  box-shadow: var(--a-card-shadow);
  min-width: 0;
  transition: background 0.4s ease, box-shadow 0.4s ease;
}
.tile:active { filter: brightness(1.15); }
.tile[disabled] { opacity: 0.55; cursor: default; }
.tile.first { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.im { position: relative; display: block; aspect-ratio: 16 / 10; overflow: hidden; }
.img { position: absolute; inset: 0; width: 100%; height: 100%; }
.again {
  position: absolute; top: calc(10 * var(--u) + 4px); left: calc(10 * var(--u) + 4px);
  background: var(--a-accent); color: var(--a-accent-ink);
  font-size: calc(12 * var(--u) + 4px); font-weight: 700; letter-spacing: 0.02em;
  padding: calc(4 * var(--u) + 2px) calc(10 * var(--u) + 4px); border-radius: 99px; white-space: nowrap;
}
.colors { position: absolute; top: calc(10 * var(--u) + 4px); right: calc(10 * var(--u) + 4px); display: flex; gap: 4px; }
.colors i { width: calc(14 * var(--u) + 6px); height: calc(14 * var(--u) + 6px); border-radius: 50%; border: 2px solid var(--a-swatch-empty); display: block; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
.text { display: flex; flex-direction: column; gap: calc(1 * var(--u) + 1px); padding: calc(8 * var(--u) + 4px) calc(16 * var(--u) + 3px) calc(8 * var(--u) + 7px); min-width: 0; }
.name { font-family: var(--a-display); font-weight: 700; font-size: calc(19 * var(--u) + 6px); letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { font-size: calc(12 * var(--u) + 5px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.l3 { font-size: calc(10 * var(--u) + 6px); font-weight: 600; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.l3.need { color: var(--a-amber-text); }
.l3.new { color: var(--a-accent-text); }

/* a past print whose file is gone: the picture fades, the words say so */
.tile.gone { background: color-mix(in srgb, var(--a-surface) 55%, transparent); box-shadow: none; outline: 2px dashed var(--a-line); outline-offset: -2px; }
.tile.gone :deep(img) { filter: grayscale(1); opacity: 0.32; }
.tile.gone .colors { opacity: 0.45; }
.tile.gone .name { color: var(--a-ink-2); }
.tile.gone .gone-words { white-space: normal; font-size: calc(10 * var(--u) + 5px); line-height: 1.3; color: var(--a-ink-2); }

/* removed in place: the tile drains and says so; the grid closes up once nobody's looking */
.tile.removed { background: transparent; box-shadow: none; outline: 2px dashed var(--a-swatch-empty); outline-offset: -2px; cursor: default; }
.tile.removed[disabled] { opacity: 1 !important; cursor: default !important; }
.tile.removed :deep(.obj) { background: transparent; }
.tile.removed :deep(img) { filter: grayscale(1); opacity: 0.14; }
.tile.removed :deep(svg) { opacity: 0.4; }
.tile.removed .name { color: var(--a-ink-3); }
.mark { position: absolute; inset: 0; display: grid; place-items: center; }
.mark span {
  display: inline-flex; align-items: center; gap: 8px;
  font-weight: 700; font-size: calc(12 * var(--u) + 8px); color: var(--a-ink-2);
  background: var(--a-surface); padding: 8px 16px 8px 12px; border-radius: 99px; box-shadow: var(--a-card-shadow);
}
.mark svg { width: calc(14 * var(--u) + 8px); height: calc(14 * var(--u) + 8px); color: var(--a-green); opacity: 1 !important; }
</style>
