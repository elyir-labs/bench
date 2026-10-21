<template>
  <!-- The chamber light's switch (design/chamber-light/, A): round on the camera picture, a pill in a bar -->
  <button
    v-if="light"
    class="light" :class="[variant, { on: light.on }]"
    :aria-label="light.ask ? 'Which light lights the bed?' : light.on ? 'Turn the light off' : 'Turn the light on'"
    :aria-pressed="light.ask ? undefined : light.on"
    :disabled="store.busyAction === 'light_on' || store.busyAction === 'light_off'"
    @click.stop="tap"
  >
    <span class="i" v-html="BULB"></span>
    <span v-if="variant === 'pill'">{{ light.on ? 'Light on' : 'Light' }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import { BULB, lightAskOpen } from '@/intent/light'

withDefaults(defineProps<{ variant?: 'round' | 'pill' }>(), { variant: 'round' })

const store = useIntentStore()
const light = computed(() => store.intent?.light ?? null)

function tap() {
  if (!light.value) return
  if (light.value.ask) {
    lightAskOpen.value = true
    return
  }
  store.act(light.value.on ? 'light_off' : 'light_on')
}
</script>

<style scoped>
.light { appearance: none; font: inherit; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.light .i :deep(svg) { display: block; width: 100%; height: 100%; }
.light[disabled] { opacity: 0.7; }
.round {
  position: absolute; left: 12px; bottom: 14px; z-index: 2;
  width: 46px; height: 46px; border-radius: 50%; border: 0;
  background: rgba(0, 0, 0, 0.55); color: #fff; backdrop-filter: blur(6px);
}
.round .i { width: 24px; height: 24px; }
.pill {
  gap: 6px; height: 34px; padding: 0 12px 0 9px; border-radius: 99px;
  border: 1px solid var(--a-line); background: transparent; color: var(--a-ink-2);
  font-size: 14px; font-weight: 600; white-space: nowrap;
}
.pill .i { width: 18px; height: 18px; }
.on { background: #f5c451; border-color: #f5c451; color: #1a1300; }
.round.on { box-shadow: 0 0 0 6px rgba(245, 196, 81, 0.25); }
</style>
