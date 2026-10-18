<template>
  <div class="door" role="dialog" aria-label="Advanced">
    <iframe :src="url" title="Advanced" allow="fullscreen" referrerpolicy="no-referrer"></iframe>
    <button class="done a-btn accent" @click="$emit('close')">Done</button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'

defineProps<{ url: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

// Advanced closes itself after ten idle minutes. We can't see activity inside
// the frame, so idle here means nothing touched the frame's surroundings; a
// tap anywhere on the frame's page restarts the timer via focus/blur events.
const IDLE_MS = 10 * 60 * 1000
let timer = 0
function arm() {
  window.clearTimeout(timer)
  timer = window.setTimeout(() => emit('close'), IDLE_MS)
}
function onActivity() { arm() }

onMounted(() => {
  arm()
  window.addEventListener('blur', onActivity)   // focus moved into the iframe
  window.addEventListener('focus', onActivity)
  window.addEventListener('pointerdown', onActivity)
})
onBeforeUnmount(() => {
  window.clearTimeout(timer)
  window.removeEventListener('blur', onActivity)
  window.removeEventListener('focus', onActivity)
  window.removeEventListener('pointerdown', onActivity)
})
</script>

<style scoped>
.door {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: var(--a-bg);
}
.door iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
.done {
  position: absolute;
  right: calc(20 * var(--u) + 8px);
  bottom: calc(20 * var(--u) + 8px + var(--safe-b));
  flex: none;
  padding: 12px 26px;
  font-size: 17px;
  border-radius: 99px;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.5);
  z-index: 1;
}
</style>
