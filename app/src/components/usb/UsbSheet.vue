<template>
  <!-- A USB stick (design/usb/, 1 A): asks over any screen, then its progress and what came of it -->
  <SliceSheet :open="!!sheet" :title="sheet?.title ?? ''" :sub="sheet?.line" eyebrow="USB stick" :amber="sheet?.tone === 'bad'"
              @close="dismiss">
    <template v-if="sheet">
      <p v-if="sheet.status" class="status"><span class="spin" aria-hidden="true"></span>{{ sheet.status }}</p>
      <span v-if="sheet.progress !== null" class="bar" aria-hidden="true"><i :style="{ width: sheet.progress * 100 + '%' }"></i></span>
      <div v-if="sheet.choices.length" class="choices">
        <button v-for="c in sheet.choices" :key="c.key" class="choice" :class="{ on: ticked(c) }" role="checkbox"
                :aria-checked="ticked(c)" @click="ticks[c.key] = !ticked(c)">
          <span class="box" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 12.5l4 4 8-9" /></svg></span>
          <span class="t"><b>{{ c.title }}</b><span>{{ c.line }}</span></span>
        </button>
      </div>
      <p v-if="sheet.small" class="small a-num">{{ sheet.small }}</p>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <div v-if="sheet.acts.length" class="acts" :class="{ one: sheet.acts.length === 1 }">
        <button v-for="a in sheet.acts" :key="a.key" class="a-btn" :class="a.go ? 'accent' : 'ghost'"
                :disabled="busy || (a.key === 'take' && sheet.choices.length > 0 && !anyTicked)"
                @click="$emit('act', a.key, { ...ticks })">{{ a.label }}</button>
      </div>
    </template>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import type { UsbActKey, UsbChoice, UsbSheet } from '@/intent/usb'

const props = defineProps<{ sheet: UsbSheet | null; stickId: string | null; busy?: boolean; error?: string | null }>()
const emit = defineEmits<{ act: [key: UsbActKey, ticks: Record<string, boolean>] }>()

const ticks = reactive<Record<string, boolean>>({})
watch(() => props.stickId, () => { for (const k of Object.keys(ticks)) delete ticks[k] })
const ticked = (c: UsbChoice) => (c.key in ticks ? ticks[c.key] : c.on)
const anyTicked = computed(() => (props.sheet?.choices ?? []).some(ticked))

// a tap beside the sheet: Not now while it asks, Done once it's finished, otherwise out of the way
function dismiss() {
  const keys = (props.sheet?.acts ?? []).map((a) => a.key)
  emit('act', keys.includes('skip') && !keys.includes('hide') ? 'skip' : keys.includes('close') ? 'close' : 'hide', { ...ticks })
}
</script>

<style scoped>
.status { margin: 0 0 12px; font-size: 15px; color: var(--a-ink-2); display: flex; align-items: center; gap: 10px; }
.spin { width: 18px; height: 18px; border-radius: 50%; border: 3px solid var(--a-surface-2); border-top-color: var(--a-accent); flex: none;
        animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.bar { display: block; height: 6px; border-radius: 3px; background: var(--a-surface-2); overflow: hidden; margin: 0 0 14px; }
.bar i { display: block; height: 100%; background: var(--a-accent); transition: width 0.4s ease; }
.choices { display: grid; gap: 8px; margin: 2px 0 12px; }
.choice { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; gap: 14px; align-items: center;
          background: var(--a-surface); border-radius: 14px; padding: 10px 14px; min-height: 56px; }
.choice:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.box { width: 28px; height: 28px; border-radius: 9px; border: 2px solid var(--a-ink-3); flex: none; display: grid; place-items: center; color: transparent; }
.choice.on .box { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-on-accent, #06121f); }
.box svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.t { min-width: 0; }
.t b { display: block; font-size: 16px; }
.t span { display: block; font-size: 14px; color: var(--a-ink-2); line-height: 1.3; overflow-wrap: anywhere; }
.small { margin: 0 0 4px; font-size: 12.5px; color: var(--a-ink-3); overflow-wrap: anywhere; }
.err { margin: 0 0 6px; font-size: 14px; color: var(--a-red); }
.acts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.acts.one { grid-template-columns: 1fr; }
.acts .a-btn { min-height: 52px; }
</style>
