<template>
  <!-- "What is it?" when the new filament isn't one of the quick answers. Nothing moves until it's answered. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" aria-label="What is the new filament?">
          <div class="top">
            <span class="swatch big" :class="{ empty: !color }" :style="{ '--c': color || 'transparent' }"></span>
            <div class="title">
              <h2 class="a-display">What is it?</h2>
              <p class="sub">The material sets the temperature it's pushed through at.</p>
            </div>
          </div>
          <div class="label">Material</div>
          <div class="mats" role="radiogroup" aria-label="Material">
            <button
              v-for="m in MATERIALS"
              :key="m"
              class="chip"
              :class="{ on: material === m }"
              role="radio"
              :aria-checked="material === m"
              @click="material = m"
            >{{ m }}</button>
          </div>
          <div class="label">Color</div>
          <div class="colors" role="radiogroup" aria-label="Color">
            <button
              v-for="c in COLORS"
              :key="c.hex"
              class="swatch pick"
              :class="{ on: color === c.hex }"
              :style="{ '--c': c.hex }"
              :aria-label="c.name"
              role="radio"
              :aria-checked="color === c.hex"
              @click="color = c.hex"
            ></button>
          </div>
          <div class="actions">
            <button class="a-btn ghost" @click="$emit('close')">Back</button>
            <button class="a-btn accent" :disabled="!material || !!store.busyAction" @click="save">{{ store.busyAction ? '…' : 'That\'s it' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { COLORS, MATERIALS } from '@/components/materials/palette'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const material = ref<string | null>(null)
const color = ref<string | null>(null)
watch(() => props.open, (o) => { if (o) { material.value = null; color.value = null } })

async function save() {
  if (!material.value) return
  await store.act('change_what', { material: material.value, color: color.value })
  if (!store.actionError) emit('close')
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: calc(14 * var(--u) + 6px);
}
.sheet {
  background: var(--a-surface);
  border-radius: calc(22 * var(--u) + 8px);
  box-shadow: var(--a-card-shadow);
  max-width: 720px; width: 100%;
  max-height: 100%; overflow: auto;
  padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px);
}
.top { display: flex; align-items: center; gap: calc(14 * var(--u) + 4px); margin-bottom: calc(6 * var(--u) + 2px); }
.title h2 { font-size: calc(22 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); margin: 2px 0 0; }
.label { font-size: calc(11 * var(--u) + 4px); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-ink-3); margin: calc(8 * var(--u) + 2px) 0 calc(5 * var(--u) + 2px); }
.swatch { border-radius: 50%; background: var(--c); border: 3px solid var(--a-swatch-edge); box-sizing: border-box; flex: none; }
.swatch.big { width: calc(40 * var(--u) + 12px); height: calc(40 * var(--u) + 12px); }
.swatch.big.empty { border-style: dashed; border-color: var(--a-swatch-empty); }
.colors { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 3px); }
.swatch.pick { appearance: none; padding: 0; cursor: pointer; width: calc(30 * var(--u) + 10px); height: calc(30 * var(--u) + 10px); min-width: 40px; min-height: 40px; }
.swatch.pick.on { outline: 3px solid var(--a-accent); outline-offset: 3px; }
.mats { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 4px); }
.chip {
  appearance: none; font: inherit; font-weight: 700; cursor: pointer;
  font-size: calc(15 * var(--u) + 4px); letter-spacing: 0.03em;
  padding: calc(7 * var(--u) + 3px) calc(14 * var(--u) + 5px); min-height: 42px;
  border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2);
}
.chip.on { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); margin-top: calc(14 * var(--u) + 4px); align-items: center; }
.actions .a-btn { padding: calc(10 * var(--u) + 4px) calc(16 * var(--u) + 6px); font-size: calc(18 * var(--u) + 4px); flex: 0 1 220px; }
.actions .a-btn.accent { flex: 1 1 260px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; }
}
</style>
