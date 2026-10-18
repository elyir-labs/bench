<template>
  <!-- An on/off switch (design/slots/, B): the carry-on switch, feed assist. -->
  <button class="toggle" :class="{ on: modelValue }" role="switch" :aria-checked="modelValue" :aria-label="label"
          :disabled="disabled" @click="$emit('update:modelValue', !modelValue)"><i></i></button>
</template>

<script setup lang="ts">
defineProps<{ modelValue: boolean; label: string; disabled?: boolean }>()
defineEmits<{ 'update:modelValue': [boolean] }>()
</script>

<style scoped>
.toggle {
  appearance: none; border: 0; padding: 0; cursor: pointer; flex: none; position: relative;
  width: 50px; height: 30px; border-radius: 99px;
  background: var(--a-surface-2); transition: background 0.18s ease;
}
.toggle i {
  position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25); transition: transform 0.18s ease;
}
.toggle.on { background: var(--a-accent); }
.toggle.on i { transform: translateX(20px); }
.toggle[disabled] { opacity: 0.5; cursor: default; }
@media (prefers-reduced-motion: reduce) { .toggle, .toggle i { transition: none; } }
</style>
