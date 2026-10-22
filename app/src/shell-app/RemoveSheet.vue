<template>
  <!-- Remove asks once (design/printers-remove/, every direction): off this phone, and this phone off the printer. -->
  <Teleport to="body">
    <div class="scrim" @click.self="!busy && emit('close')">
      <div class="sheet" role="dialog" aria-modal="true" :aria-label="words.title">
        <h3>{{ words.title }}</h3>
        <p class="body">{{ words.body }}</p>
        <div v-if="words.offer" class="offer">
          <span class="t"><b>{{ words.offer }}</b><span>{{ words.offerSub }}</span></span>
          <Toggle v-model="alsoOff" :label="words.offer" :disabled="busy" />
        </div>
        <p v-if="words.note" class="note">{{ words.note }}</p>
        <button class="a-btn red big" :disabled="busy" @click="go">{{ busy ? 'Removing…' : 'Remove' }}</button>
        <button class="a-btn ghost big" :disabled="busy" @click="emit('close')">Cancel</button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Toggle from '@/components/materials/Toggle.vue'
import type { LivePrinter } from './printers'
import { caseOf, sheetWords } from './remove'
import { removePrinter } from './removing'

const props = defineProps<{ p: LivePrinter }>()
const emit = defineEmits<{ close: []; done: [] }>()
// the case is fixed when the sheet opens, so the words don't change under a finger
const kind = caseOf(props.p)
const words = computed(() => sheetWords(props.p.name, kind))
const alsoOff = ref(true)
const busy = ref(false)

async function go() {
  busy.value = true
  try {
    await removePrinter(props.p, kind === 'reachable' && alsoOff.value)
    emit('done')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, 0.45); display: flex; align-items: flex-end; justify-content: center; }
.sheet {
  width: min(480px, 100%); box-sizing: border-box; background: var(--a-surface); color: var(--a-ink); font-family: var(--a-font);
  border-radius: 22px 22px 0 0; box-shadow: var(--a-card-shadow);
  padding: 22px 20px calc(18px + env(safe-area-inset-bottom, 0px)); display: flex; flex-direction: column; gap: 12px;
}
@media (min-width: 600px) {
  .scrim { align-items: center; }
  .sheet { border-radius: 22px; padding-bottom: 20px; }
}
h3 { margin: 0; font-size: 22px; line-height: 1.25; text-wrap: balance; overflow-wrap: anywhere; }
.body { margin: 0; color: var(--a-ink-2); font-size: 16px; line-height: 1.45; }
.offer { display: flex; align-items: center; gap: 14px; padding: 14px; border-radius: 14px; background: var(--a-bg); }
.offer .t { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.offer .t b { font-size: 16px; overflow-wrap: anywhere; }
.offer .t span { color: var(--a-ink-3); font-size: 14px; line-height: 1.4; }
.note { margin: 0; padding: 12px 14px; border-radius: 14px; background: var(--a-bg); color: var(--a-ink-2); font-size: 15px; line-height: 1.45; }
.big { width: 100%; min-height: 50px; font-size: 17px; }
</style>
