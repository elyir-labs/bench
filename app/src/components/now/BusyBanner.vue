<template>
  <!-- Why this page's actions are unavailable right now, in one sentence, before anything else.
       Panel only: phones have the Now bar and wider screens keep Now on screen, so nothing to point back to. -->
  <div v-if="text && layout === 'panel'" class="banner" :class="'is-' + state" role="status">
    <span class="dot" aria-hidden="true"></span>
    <span>{{ text }}</span>
    <router-link to="/" class="link">See Now</router-link>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import { layout } from '@/shell/useLayout'

// `then`: what becomes possible again, e.g. "pick the next print"
const props = defineProps<{ then: string }>()
const store = useIntentStore()
const state = computed(() => store.intent?.state ?? 'ready')
const text = computed(() => {
  const job = store.intent?.job?.name
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
  switch (state.value) {
    case 'preparing': case 'printing': return `${job ? `Printing ${job}` : 'Printing'}. ${cap(props.then)} when it's done.`
    case 'needs_you': return 'The printer needs you first.'
    case 'finished': return `Take the finished print off the bed, then ${props.then}.`
    case 'problem': return 'Sort out the problem first.'
    default: return ''
  }
})
</script>

<style scoped>
.banner {
  display: flex; align-items: center; gap: calc(10 * var(--u) + 4px);
  padding: calc(10 * var(--u) + 4px) calc(14 * var(--u) + 5px);
  border-radius: calc(12 * var(--u) + 4px);
  background: var(--a-surface);
  color: var(--a-ink-2);
  font-size: calc(15 * var(--u) + 5px);
  margin-bottom: calc(12 * var(--u) + 4px);
}
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--a-accent); flex: none; }
.is-needs_you .dot { background: var(--a-amber); }
.is-problem .dot { background: var(--a-red); }
.is-finished .dot { background: var(--a-green); }
.link { margin-left: auto; color: var(--a-accent-text); text-decoration: none; font-weight: 600; white-space: nowrap; }
</style>
