<template>
  <!-- On the rail (design/small-screens/, B) the top line opens what no longer fits beside it -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && intent" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="intent.printer.name">
          <header class="head">
            <h2 class="a-display">{{ intent.printer.name }}</h2>
            <LightButton v-if="intent.light" variant="pill" />
            <button class="a-btn ghost done" @click="$emit('close')">Done</button>
          </header>
          <Vitals :intent="intent" tiles />
          <SpoolRow :spools="intent.spools" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import LightButton from '@/components/light/LightButton.vue'
import SpoolRow from '@/components/now/SpoolRow.vue'
import Vitals from '@/components/now/Vitals.vue'

defineProps<{ open: boolean }>()
defineEmits<{ close: [] }>()

const store = useIntentStore()
const intent = computed(() => store.intent)
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 40; background: var(--a-bg); display: flex; }
.sheet { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: calc(10 * var(--u)); padding: calc(10 * var(--u)) calc(20 * var(--u)); overflow-y: auto; }
.head { display: flex; align-items: center; gap: calc(12 * var(--u)); }
.head h2 { margin: 0 auto 0 0; font-size: calc(30 * var(--u)); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.done { flex: none; font-size: calc(20 * var(--u) + 3px); padding-block: 6px; }
</style>
