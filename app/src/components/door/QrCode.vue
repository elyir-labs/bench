<template>
  <!-- Always dark on white with a quiet zone, whatever the theme: that's what phone cameras read best. -->
  <svg class="qr" :viewBox="`0 0 ${box} ${box}`" role="img" :aria-label="label" shape-rendering="crispEdges">
    <rect width="100%" height="100%" fill="#fff" />
    <path :d="path" fill="#000" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { encode } from 'uqr'

// ecc H when a mark covers the middle (the first Wi-Fi's codes, design/setup/): it still scans
const props = withDefaults(defineProps<{ value: string; label?: string; ecc?: 'L' | 'M' | 'Q' | 'H' }>(), { ecc: 'M' })
const QUIET = 3   // modules of white around the code

const qr = computed(() => encode(props.value, { ecc: props.ecc, border: 0 }))
const box = computed(() => qr.value.size + QUIET * 2)
const path = computed(() => {
  let d = ''
  qr.value.data.forEach((row, y) => row.forEach((on, x) => {
    if (on) d += `M${x + QUIET} ${y + QUIET}h1v1h-1z`
  }))
  return d
})
</script>

<style scoped>
.qr { display: block; width: 100%; height: auto; border-radius: 12px; }
</style>
