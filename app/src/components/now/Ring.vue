<template>
  <div class="ring" :style="{ '--v': value, '--c': color, '--ci': ink ?? 'var(--a-accent-ink)' }">
    <div class="face">
      <!-- face: a drawing in place of the object (the head while changing filament) -->
      <div v-if="$slots.face" class="drawn"><slot name="face" /></div>
      <!-- art: a picture that fills the face (design/now-illustrated/, A) -->
      <div v-else-if="$slots.art" class="art"><slot name="art" /></div>
      <ObjectImage v-else-if="image !== undefined" :src="image" :alt="alt" round class="img" />
      <div v-else class="center">
        <div class="num a-display a-num"><slot /></div>
        <div class="lbl">{{ label }}</div>
      </div>
    </div>
    <div v-if="image !== undefined || $slots.face || $slots.art" class="pill a-num"><slot /></div>
  </div>
</template>

<script setup lang="ts">
import ObjectImage from './ObjectImage.vue'
// ink: text colour on the progress pill, matching `color`
defineProps<{ value: number; label: string; color: string; ink?: string; image?: string | null; alt?: string }>()
</script>

<style scoped>
.ring {
  --size: calc(196 * var(--u) + 34px);
  width: var(--size);
  height: var(--size);
  border-radius: 50%;
  background: conic-gradient(var(--c) calc(var(--v) * 360deg), var(--a-surface-2) 0);
  display: grid;
  place-items: center;
  transition: background 800ms linear;
  position: relative;
}
.face {
  width: calc(100% - (18 * var(--u) + 6px));
  height: calc(100% - (18 * var(--u) + 6px));
  border-radius: 50%;
  background: var(--a-bg);
  display: grid;
  place-items: center;
  overflow: hidden;
}
.img { width: 100%; height: 100%; }
.drawn { width: 62%; height: 62%; }
.art { width: 100%; height: 100%; }
.center { display: flex; flex-direction: column; align-items: center; justify-content: center; }
.num { font-size: calc(48 * var(--u) + 10px); font-weight: 700; letter-spacing: -0.03em; line-height: 1; }
.num :deep(small), .num small { font-size: 0.45em; font-weight: 600; color: var(--a-ink-2); margin-left: 2px; }
.lbl { font-size: calc(14 * var(--u) + 4px); color: var(--a-ink-3); margin-top: 6px; }
.pill {
  position: absolute;
  bottom: calc(-4 * var(--u));
  left: 50%;
  transform: translateX(-50%);
  background: var(--c);
  color: var(--ci);
  font-weight: 700;
  font-size: calc(17 * var(--u) + 5px);
  padding: calc(4 * var(--u) + 2px) calc(12 * var(--u) + 4px);
  border-radius: 99px;
  box-shadow: 0 0 0 4px var(--a-bg);
  white-space: nowrap;
}
.pill :deep(small), .pill small { font-size: 0.75em; font-weight: 700; }
</style>
