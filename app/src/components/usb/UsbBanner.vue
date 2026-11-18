<template>
  <!-- Over a print (design/usb/, 1 A): a line at the top, not a sheet, so the print stays in view -->
  <div class="usb-banner" role="status">
    <span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 3h8v6H8z" /><path d="M6.5 9h11v7.5a3 3 0 0 1-3 3h-5a3 3 0 0 1-3-3z" /></svg></span>
    <span class="t"><b>{{ banner.title }}</b><span>{{ banner.line }}</span></span>
    <button v-if="banner.act" class="a-btn ghost" :disabled="busy" @click="$emit('skip')">{{ banner.act }}</button>
  </div>
</template>

<script setup lang="ts">
import type { UsbBanner } from '@/intent/usb'

defineProps<{ banner: UsbBanner; busy?: boolean }>()
defineEmits<{ skip: [] }>()
</script>

<style scoped>
.usb-banner { display: flex; gap: 12px; align-items: center; margin: 8px 16px 0; padding: 8px 12px; border-radius: 16px;
              background: color-mix(in srgb, var(--a-accent) 12%, var(--a-surface));
              box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--a-accent) 45%, transparent); }
.mark { width: 36px; height: 36px; border-radius: 11px; flex: none; display: grid; place-items: center; color: var(--a-accent);
        background: color-mix(in srgb, var(--a-accent) 16%, transparent); }
.mark svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; }
.t { flex: 1; min-width: 0; }
.t b { display: block; font-size: 15px; }
.t span { display: block; font-size: 13.5px; color: var(--a-ink-2); }
.a-btn { flex: none; min-height: 44px; padding: 0 16px; border-radius: 999px; white-space: nowrap; font-size: 16px; }
</style>
