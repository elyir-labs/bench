<template>
  <!-- Dry a unit's spools (design/slots/, B). One dryer per unit, so its slots dry together; the
       intent layer works out the heat from what's inside. The time can change. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="unit" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Dry ${unit.name}`">
          <h2 class="a-display">Dry {{ unit.name === 'Filament unit' ? 'the spools' : unit.name.replace(/^Unit /, 'unit ') }}</h2>
          <p class="sub">{{ unit.slots.length > 1 ? `Its dryer warms all ${words(unit.slots.length)} slots.` : 'Its dryer warms the spool.' }}</p>
          <div class="facts">
            <span class="k">Inside</span>
            <span class="v inside">
              <span class="minis">
                <span v-for="s in inside" :key="s.slot" class="sw" :class="{ empty: s.status === 'empty' }" :style="{ '--c': s.color || 'transparent' }"></span>
              </span>
              <span class="names">{{ unit.dry.names.length ? names : 'Nothing loaded' }}</span>
            </span>
            <span class="k">Heat</span>
            <span class="v"><b class="a-num">{{ unit.dry.temp }}°</b>, {{ unit.dry.why }}</span>
            <span class="k">For</span>
            <span class="v time">
              <span class="stepper">
                <button :disabled="hours <= 1" aria-label="Less time" @click="hours--">−</button>
                <b class="a-num">{{ hours }} h</b>
                <button :disabled="hours >= 12" aria-label="More time" @click="hours++">+</button>
              </span>
              <span class="hint a-num">{{ hours === unit.dry.hours ? cap(unit.dry.hours_why) + '. ' : '' }}Done at {{ doneAt }}.</span>
            </span>
          </div>
          <div class="actions">
            <button class="a-btn ghost" @click="$emit('close')">Back</button>
            <button class="a-btn accent" :disabled="!!store.busyAction" @click="start">{{ store.busyAction === 'dry_unit' ? '…' : 'Start drying' }}</button>
          </div>
          <p v-if="store.actionError" class="err">{{ store.actionError }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentUnit } from '@/intent/types'

const props = defineProps<{ unit: IntentUnit | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const hours = ref(4)
watch(() => props.unit, (u) => { if (u) hours.value = u.dry.hours }, { immediate: true })

const inside = computed(() => (store.intent?.spools ?? []).filter((s) => props.unit?.slots.includes(s.slot)))
const names = computed(() => {
  const n = [...new Set(props.unit?.dry.names ?? [])]
  return n.length > 2 ? `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}` : n.join(' and ')
})
const doneAt = computed(() => new Date(Date.now() + hours.value * 3600e3).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }))
const words = (n: number) => ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'][n] ?? String(n)
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)

async function start() {
  if (!props.unit) return
  await store.act('dry_unit', { unit: props.unit.index, hours: hours.value })
  if (!store.actionError) emit('close')
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; padding: calc(14 * var(--u) + 6px);
}
.sheet {
  background: var(--a-surface); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow);
  max-width: 720px; width: 100%; max-height: 100%; overflow: auto;
  padding: calc(18 * var(--u) + 6px) calc(22 * var(--u) + 6px);
}
h2 { font-size: calc(24 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(14 * var(--u) + 4px); margin: 4px 0 calc(12 * var(--u) + 4px); }
.facts { display: grid; grid-template-columns: auto 1fr; gap: calc(8 * var(--u) + 2px) calc(14 * var(--u) + 4px); align-items: center;
         font-size: calc(14 * var(--u) + 3px); color: var(--a-ink-2); }
.facts .k { color: var(--a-ink-3); }
.facts b { color: var(--a-ink); font-weight: 600; }
.inside, .time { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-width: 0; }
.minis { display: flex; gap: 6px; }
.sw { width: 24px; height: 24px; border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); box-sizing: border-box; }
.sw.empty { background: transparent; border-style: dashed; border-color: var(--a-swatch-empty); }
.stepper { display: inline-flex; align-items: center; border: 1px solid var(--a-line); border-radius: 14px; overflow: hidden; }
.stepper button { appearance: none; border: 0; background: none; color: var(--a-ink-2); font: inherit; font-size: 22px; min-width: 46px; height: 44px; cursor: pointer; }
.stepper button[disabled] { opacity: 0.35; cursor: default; }
.stepper b { display: grid; place-items: center; height: 44px; padding: 0 14px; border-inline: 1px solid var(--a-line); font-size: calc(15 * var(--u) + 3px); }
.hint { font-size: calc(12 * var(--u) + 3px); color: var(--a-ink-3); }
.actions { display: flex; justify-content: flex-end; gap: calc(10 * var(--u) + 4px); margin-top: calc(16 * var(--u) + 4px); }
.actions .a-btn { padding: calc(10 * var(--u) + 4px) calc(18 * var(--u) + 6px); font-size: calc(16 * var(--u) + 4px); flex: none; }
.err { color: var(--a-red-text, var(--a-red)); margin: 8px 0 0; font-size: 15px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; }
}
</style>
