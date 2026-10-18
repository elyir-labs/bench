<template>
  <div class="obj" :class="{ empty: !src || failed, round }">
    <img v-if="src && !failed" :src="src" :alt="alt" @error="failed = true" draggable="false" />
    <svg v-else viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Zm0 2.2 5.6 3.1L12 11.5 6.4 8.3 12 5.2ZM6 10l5 2.8v5.6L6 15.6V10Zm12 0v5.6l-5 2.8v-5.6l5-2.8Z" fill="currentColor"/>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ src?: string | null; alt?: string; round?: boolean }>()
const failed = ref(false)
watch(() => props.src, () => { failed.value = false })
</script>

<style scoped>
.obj {
  position: relative;
  overflow: hidden;
  background: radial-gradient(120% 100% at 50% 20%, var(--a-obj-hi), var(--a-obj-lo) 70%);
  display: grid;
  place-items: center;
}
.obj img { width: 100%; height: 100%; object-fit: contain; display: block; }
.obj svg { width: 40%; height: 40%; color: var(--a-obj-icon); }
.obj.round { border-radius: 50%; }
</style>
