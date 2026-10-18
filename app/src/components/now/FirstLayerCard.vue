<template>
  <!-- First layer (design/first-layer/, "At the end"): a question with two answers, on Now -->
  <div class="keep" role="group" :aria-label="card.headline">
    <b>{{ card.headline }}</b>
    <span>{{ card.detail }}</span>
    <div v-if="actions.length" class="row2">
      <button
        v-for="a in actions"
        :key="a.id"
        class="a-btn"
        :class="a.primary ? 'accent' : 'ghost'"
        :disabled="store.busyAction !== null"
        @click="store.act(a)"
      >{{ store.busyAction === a.id ? '…' : a.label }}</button>
    </div>
    <span v-else class="at-printer">Answer this at the printer.</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentAction } from '@/intent/types'
import { allowedHere } from '@/door'

const props = defineProps<{ card: { headline: string; detail: string; actions: IntentAction[] } }>()
const store = useIntentStore()
const actions = computed(() => props.card.actions.filter((a) => allowedHere(a.id)))
</script>

<style scoped>
.keep { background: var(--a-surface); border-radius: calc(14 * var(--u) + 6px); padding: calc(12 * var(--u) + 4px) calc(14 * var(--u) + 4px); box-shadow: var(--a-card-shadow); display: grid; gap: 4px; margin-top: calc(16 * var(--u) + 6px); max-width: 460px; text-align: left; }
.keep b { font-size: calc(15 * var(--u) + 5px); line-height: 1.25; }
.keep span { font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-2); line-height: 1.35; }
.row2 { display: flex; gap: 10px; margin-top: 10px; }
.row2 .a-btn { flex: 1; min-height: calc(38 * var(--u) + 12px); font-size: calc(13 * var(--u) + 4px); border-radius: 15px; padding: 0 12px; }
.at-printer { color: var(--a-ink-3) !important; margin-top: 6px; }
</style>
