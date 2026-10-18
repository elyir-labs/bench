<template>
  <!-- design/one-cloud/, A: the Elyir account and its Bench Cloud plan -->
  <router-link to="/you" class="you" :aria-label="account.owner ? `You: ${account.owner.email}` : 'Sign in'">
    <span v-if="account.owner">{{ initial(account.owner.email) }}</span>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><circle cx="12" cy="8.5" r="3.8"/><path d="M4.5 20c1.2-3.8 4-5.5 7.5-5.5s6.3 1.7 7.5 5.5"/></svg>
  </router-link>
</template>

<script setup lang="ts">
import { account } from './account'
import { initial } from './you'
</script>

<style scoped>
.you { width: 40px; height: 40px; border-radius: 50%; flex: none; display: grid; place-items: center; text-decoration: none;
  font-family: var(--a-font); font-weight: 750; font-size: 17px; color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 14%, transparent); }
.you svg { width: 21px; height: 21px; }
</style>
