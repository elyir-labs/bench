<template>
  <!-- After Remove (design/printers-remove/): what happened, and Undo while nothing changed on the printer. -->
  <Transition name="toast">
    <div v-if="removed" class="toast" role="status">
      <span class="w">{{ removed.words }}</span>
      <button v-if="removed.undo" class="undo" @click="undoRemove">Undo</button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { removed, undoRemove } from './removing'

const SHOW_MS = 6000
const LONGER_MS = 12000    // a sentence about the printer still knowing this phone takes longer to read
let timer = 0
watch(removed, (r) => {
  window.clearTimeout(timer)
  if (r) timer = window.setTimeout(() => { removed.value = null }, r.words.includes('Care') ? LONGER_MS : SHOW_MS)
})
</script>

<style scoped>
.toast {
  position: fixed; z-index: 70; left: 50%; transform: translateX(-50%); bottom: calc(18px + env(safe-area-inset-bottom, 0px));
  width: min(460px, calc(100% - 24px)); box-sizing: border-box; display: flex; align-items: center; gap: 12px;
  padding: 12px 12px 12px 16px; border-radius: 14px; background: var(--a-ink); color: var(--a-bg);
  font-family: var(--a-font); font-size: 15px; line-height: 1.4; box-shadow: var(--a-card-shadow);
}
.w { flex: 1; min-width: 0; }
.undo { appearance: none; border: 0; background: none; color: inherit; font: inherit; font-weight: 750; padding: 8px 10px; cursor: pointer; flex: none; }
.toast-enter-active, .toast-leave-active { transition: opacity 160ms ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; }
</style>
