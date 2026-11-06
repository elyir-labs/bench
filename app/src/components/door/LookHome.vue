<template>
  <!-- Under a "do this at the printer" line (design/printers-away/, B): away may only mean home didn't answer in time,
       so the Printers app around this frame looks again. Only there: a printer opened at its own address can't move home. -->
  <button v-if="door.away && shell.looksHome" class="look-home" :disabled="looking" @click="look">
    <span v-if="looking" class="spin" aria-hidden="true"></span>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
      <path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.6 16a5 5 0 0 1 6.8 0" /><circle cx="12" cy="19.5" r="1.2" fill="currentColor" stroke="none" />
    </svg>
    {{ looking ? 'Looking on this Wi-Fi…' : "I'm home: look on this Wi-Fi" }}
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { door } from '@/door'
import { askShellToLookHome, shell } from '@/auth'

const looking = ref(false)
async function look() {
  looking.value = true
  try { await askShellToLookHome() } finally { looking.value = false }
}
</script>

<style scoped>
.look-home {
  appearance: none; border: 0; font: inherit; cursor: pointer; align-self: flex-start;
  display: inline-flex; align-items: center; gap: 9px; min-height: 44px; padding: 0 18px; margin-top: 4px; border-radius: 99px;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-accent-text);
  font-weight: 650; font-size: 15.5px; white-space: nowrap;
}
.look-home[disabled] { cursor: default; }
.look-home svg { width: 18px; height: 18px; flex: none; }
.spin { width: 16px; height: 16px; border-radius: 50%; border: 2.5px solid currentColor; border-right-color: transparent; animation: spin .8s linear infinite; flex: none; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
