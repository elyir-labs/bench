<template>
  <!-- A file sent from the slicer and not printed yet, above Recent (design/print-library/, B). -->
  <button
    class="nc"
    :class="{ removed }"
    :disabled="disabled || removed"
    :aria-label="removed ? `${item.name}, removed` : item.name"
    @click="$emit('open', item)"
  >
    <span class="im">
      <ObjectImage :src="thumb" :alt="item.name" class="img" />
      <span v-if="!removed" class="colors" aria-hidden="true"><i v-for="(c, k) in colors" :key="k" :style="{ background: c }"></i></span>
    </span>
    <span class="tx">
      <small>{{ removed ? 'Removed' : sentLine(item, now) }}</small>
      <b>{{ item.name }}</b>
      <span v-if="removed">Removed from {{ printer }}</span>
      <span v-else-if="need" class="need">{{ need }}</span>
      <span v-else class="a-num">{{ metaLine(item) }}</span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ObjectImage from '@/components/now/ObjectImage.vue'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import { metaLine, sentLine, type Item } from '@/print/library'

const props = defineProps<{ item: Item; check?: PrintCheck | null; now: number; printer: string; removed?: boolean; disabled?: boolean }>()
defineEmits<{ open: [item: Item] }>()
const store = useIntentStore()
const thumb = computed(() => store.thumbOf({ filename: props.item.filename, metadata: props.item.meta } as any))
const colors = computed(() => (props.item.colors.length ? props.item.colors.slice(0, 3) : ['#666666']))
const need = computed(() => (props.check && !props.check.ok && !props.check.ask ? props.check.short ?? null : null))
</script>

<style scoped>
.nc {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; padding: 0;
  display: flex; height: calc(47 * var(--u) + 53px); min-width: 0;
  background: var(--a-surface); border-radius: calc(13 * var(--u) + 9px); overflow: hidden;
  box-shadow: var(--a-card-shadow); position: relative;
}
.nc:active { filter: brightness(1.15); }
.nc[disabled] { opacity: 0.55; cursor: default; }
.im { width: calc(16 * var(--u) + 108px); flex: none; position: relative; overflow: hidden; }
.img { position: absolute; inset: 0; width: 100%; height: 100%; }
.colors { position: absolute; top: 9px; right: 9px; display: flex; gap: 3px; }
.colors i { width: calc(8 * var(--u) + 8px); height: calc(8 * var(--u) + 8px); border-radius: 50%; border: 2px solid var(--a-swatch-empty); display: block; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
.tx { flex: 1; min-width: 0; padding: calc(5 * var(--u) + 8px) calc(5 * var(--u) + 11px) 0; display: flex; flex-direction: column; gap: 1px; }
.tx small { font-size: calc(7 * var(--u) + 8px); font-weight: 600; color: var(--a-accent-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tx b { font-family: var(--a-display); font-size: calc(10.5 * var(--u) + 11.5px); font-weight: 700; letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tx span { font-size: calc(8 * var(--u) + 8px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tx span.need { font-weight: 600; color: var(--a-amber-text); }
.nc.removed { background: transparent; box-shadow: none; outline: 2px dashed var(--a-swatch-empty); outline-offset: -2px; opacity: 1 !important; cursor: default !important; }
.nc.removed :deep(.obj) { background: transparent; }
.nc.removed :deep(img) { filter: grayscale(1); opacity: 0.14; }
.nc.removed small { color: var(--a-green-text); }
.nc.removed b { color: var(--a-ink-3); }
</style>
