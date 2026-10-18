<template>
  <!-- Up next under the spools when Ready, off the panel (design/ready-phone/, C). The rows are the
       Print tab's New card: a file opens its sheet, Care opens Care, Print a model opens Print a model. -->
  <div class="upnext">
    <button v-for="r in rows" :key="key(r)" class="un" :class="r.kind" @click="$emit('pick', r)">
      <span class="im">
        <span v-if="r.kind === 'care'" class="glyph" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-9-9.2C1.7 7.6 3.8 4.5 7 4.5c2 0 3.4 1.1 5 3 1.6-1.9 3-3 5-3 3.2 0 5.3 3.1 4 6.3-2 4.8-9 9.2-9 9.2z" /></svg>
        </span>
        <span v-else-if="r.kind === 'start'" class="glyph" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
        </span>
        <template v-else>
          <ObjectImage :src="thumb(r.item)" :alt="r.name" class="img" />
          <span class="colors" aria-hidden="true"><i v-for="(c, k) in colors(r.item)" :key="k" :style="{ background: c }"></i></span>
        </template>
      </span>
      <span class="tx">
        <small>{{ r.label }}</small>
        <b>{{ r.name }}</b>
        <span class="a-num">{{ r.meta }}</span>
      </span>
      <svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import ObjectImage from '@/components/now/ObjectImage.vue'
import { useIntentStore } from '@/intent/store'
import type { Item } from '@/print/library'
import type { UpRow } from '@/print/upnext'

defineProps<{ rows: UpRow[] }>()
defineEmits<{ pick: [row: UpRow] }>()
const store = useIntentStore()
const thumb = (i: Item) => store.thumbOf({ filename: i.filename, metadata: i.meta } as any)
const colors = (i: Item) => (i.colors.length ? i.colors.slice(0, 3) : ['#666666'])
const key = (r: UpRow) => (r.kind === 'care' ? `care:${r.care.id}` : r.kind === 'start' ? 'start' : `${r.kind}:${r.item.filename}`)
</script>

<style scoped>
.upnext { display: grid; gap: calc(6 * var(--u) + 6px); width: 100%; text-align: left; }
.un {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; padding: 0;
  display: flex; align-items: stretch; height: calc(47 * var(--u) + 53px); min-width: 0;
  background: var(--a-surface); border-radius: calc(13 * var(--u) + 9px); overflow: hidden; box-shadow: var(--a-card-shadow);
}
.un:active { filter: brightness(1.15); }
.im { width: calc(16 * var(--u) + 108px); flex: none; position: relative; overflow: hidden; }
.img { position: absolute; inset: 0; width: 100%; height: 100%; }
.colors { position: absolute; top: 9px; right: 9px; display: flex; gap: 3px; }
.colors i { width: calc(8 * var(--u) + 8px); height: calc(8 * var(--u) + 8px); border-radius: 50%; border: 2px solid var(--a-swatch-empty); display: block; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25); }
.glyph { position: absolute; inset: 0; display: grid; place-items: center; background: var(--a-surface-2); color: var(--a-ink-2); }
.care .glyph { background: color-mix(in srgb, var(--a-amber) 22%, var(--a-surface)); color: var(--a-amber-text); }
.start .glyph { background: var(--a-accent); color: var(--a-accent-ink); }
.glyph svg { width: 40%; height: 40%; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.tx { flex: 1; min-width: 0; padding: 0 calc(3 * var(--u) + 6px) 0 calc(5 * var(--u) + 11px); display: flex; flex-direction: column; justify-content: center; gap: 1px; }
.tx small { font-size: calc(7 * var(--u) + 8px); font-weight: 600; color: var(--a-accent-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.care .tx small { color: var(--a-amber-text); }
.start .tx small { color: var(--a-ink-3); }
.tx b { font-family: var(--a-display); font-size: calc(10.5 * var(--u) + 11.5px); font-weight: 700; letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tx span { font-size: calc(8 * var(--u) + 8px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chev { flex: none; align-self: center; width: 20px; height: 20px; margin-right: 12px; fill: none; stroke: var(--a-ink-3); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
</style>
