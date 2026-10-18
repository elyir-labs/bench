<template>
  <!-- Turning Bench Cloud on (design/one-cloud/, stage 3): monthly or yearly through Stripe's own page when paying is open,
       a tester invite otherwise (or when asked for). -->
  <div class="picker">
    <template v-if="account.pay && !showInvite">
      <div class="seg" role="radiogroup" aria-label="Plan">
        <button v-for="p in PLANS" :key="p" type="button" class="seg-opt" :class="{ on: pick === p }" :aria-checked="pick === p"
                role="radio" @click="pick = p">{{ planName(p, account.pay) }}</button>
      </div>
      <button class="a-btn accent" :disabled="busy" @click="go(() => checkout(pick))">{{ busy ? '…' : turnOnLabel(pick, account.pay) }}</button>
      <p class="hint">{{ STOP_ANY }} <button type="button" class="link" @click="showInvite = true">{{ HAVE_INVITE }}</button></p>
    </template>
    <template v-else>
      <p class="hint">{{ PRICE }} {{ INVITE_HINT }}</p>
      <form class="picker" @submit.prevent="go(() => startHouse(invite))">
        <label class="field"><span>Tester invite code</span>
          <input v-model="invite" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="ABCD-2345" /></label>
        <button class="a-btn accent" :disabled="busy || !validInvite(invite)">{{ busy ? '…' : 'Turn on' }}</button>
      </form>
    </template>
    <p v-if="error" class="err">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { validInvite } from '@/cloud'
import { account, checkout, startHouse } from './account'
import { HAVE_INVITE, INVITE_HINT, PRICE, STOP_ANY, planName, turnOnLabel, type PaidPlan } from './you'

const PLANS: PaidPlan[] = ['monthly', 'yearly']
const pick = ref<PaidPlan>('yearly')
const showInvite = ref(false)
const invite = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function go(fn: () => Promise<void>): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await fn()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.picker { display: flex; flex-direction: column; gap: 14px; }
.hint { color: var(--a-ink-3); font-size: 15px; line-height: 1.4; margin: 0; }
.err { color: var(--a-red-text); font-size: 16px; margin: 0; }
.link { appearance: none; background: none; border: 0; padding: 0; font: inherit; font-weight: 600; color: var(--a-accent-text); cursor: pointer; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
input {
  font: inherit; font-size: 18px; font-weight: 500; color: var(--a-ink); background: var(--a-bg); border: 1px solid var(--a-line);
  border-radius: 14px; padding: 14px 16px; outline: none; user-select: text; -webkit-user-select: text;
}
input:focus { border-color: var(--a-accent); }
.seg { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; padding: 4px; gap: 4px; border-radius: 99px; background: var(--a-surface-2); }
.seg-opt { appearance: none; border: 0; font: inherit; height: 42px; border-radius: 99px; background: none; font-size: 15px; font-weight: 650; color: var(--a-ink-2); cursor: pointer; }
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
</style>
