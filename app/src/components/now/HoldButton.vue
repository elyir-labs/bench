<template>
  <!-- An action that ends a print: it fills while held and only runs once full. Let go early and
       nothing happens but a hint. Works with touch, mouse and keyboard (hold Space or Enter). -->
  <button
    class="a-btn holdbtn"
    :class="{ holding, done }"
    :style="{ '--hold-ms': HOLD_MS + 'ms' }"
    :disabled="disabled"
    :aria-label="`${holdLabel(label)}: press and hold`"
    @pointerdown.prevent="start"
    @pointerup="stop"
    @pointerleave="stop"
    @pointercancel="stop"
    @keydown.space.prevent="keyStart"
    @keydown.enter.prevent="keyStart"
    @keyup.space="stop"
    @keyup.enter="stop"
    @contextmenu.prevent
    @click.prevent
  >
    <span class="fill" aria-hidden="true"></span>
    <span class="text">{{ busy ? '…' : hint ? (hintText ?? HOLD_HINT) : holdLabel(label) }}</span>
  </button>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { HOLD_HINT, HOLD_MS, holdLabel } from '@/intent/hold'

// hintText: what letting go early says, when it isn't stopping a print ("Keep holding to skip")
const props = defineProps<{ label: string; disabled?: boolean; busy?: boolean; hintText?: string }>()
const emit = defineEmits<{ run: [] }>()
const holding = ref(false)
const done = ref(false)
const hint = ref(false)
let timer = 0
let hintTimer = 0

function start() {
  if (props.disabled || holding.value) return
  holding.value = true
  hint.value = false
  window.clearTimeout(hintTimer)
  timer = window.setTimeout(() => {
    holding.value = false
    done.value = true
    navigator.vibrate?.(30)
    emit('run')
    window.setTimeout(() => (done.value = false), 600)
  }, HOLD_MS)
}
function keyStart(e: KeyboardEvent) { if (!e.repeat) start() }
function stop() {
  if (!holding.value) return
  holding.value = false
  window.clearTimeout(timer)
  hint.value = true
  window.clearTimeout(hintTimer)
  hintTimer = window.setTimeout(() => (hint.value = false), 2200)
}
onBeforeUnmount(() => { window.clearTimeout(timer); window.clearTimeout(hintTimer) })
</script>

<style scoped>
.holdbtn { position: relative; overflow: hidden; touch-action: none; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.fill {
  position: absolute; inset: 0; transform-origin: left center; transform: scaleX(0);
  background: color-mix(in srgb, var(--a-red) 34%, transparent); pointer-events: none;
}
.holding .fill { transform: scaleX(1); transition: transform var(--hold-ms) linear; }
.done .fill { transform: scaleX(1); background: color-mix(in srgb, var(--a-red) 55%, transparent); }
.text { position: relative; }
@media (prefers-reduced-motion: reduce) {
  /* no sweep: the button darkens while held instead, and still needs the full second */
  .holding .fill { transform: scaleX(1); transition: none; background: color-mix(in srgb, var(--a-red) 22%, transparent); }
}
</style>
