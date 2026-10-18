<template>
  <!-- Pairing a phone with the box from away (design/bench-remote/, A): the box's Add a phone QR opens /pair#CODE here,
       or the code is typed. Away and not let in, every page is this one, with an invite link as the other way in. -->
  <section class="way">
    <form class="box" @submit.prevent="submit">
      <span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="8" height="9" rx="1.5"/><rect x="13" y="4" width="8" height="9" rx="1.5"/><rect x="8" y="14.5" width="8" height="6.5" rx="1.5"/></svg></span>
      <p class="eyebrow">Elyir Bench</p>
      <h1 class="a-display">{{ landing ? "This bench isn't open from here." : 'Pair this phone with the Bench Box' }}</h1>
      <p class="sub">{{ landing
        ? 'Someone at home can add this phone: on the Bench Box, Care, then Add a phone. Type the code it shows. Sent an invite link? Open the link itself.'
        : "On the Bench Box's screen: Care, then Add a phone. Type the code it shows." }}</p>
      <label><span>Code</span>
        <input v-model="code" class="a-num codein" inputmode="text" autocapitalize="characters" autocomplete="one-time-code"
               spellcheck="false" maxlength="9" placeholder="ABCD-EFGH" required /></label>
      <label><span>Name for this phone</span><input v-model="name" maxlength="40" placeholder="Alex's iPhone" required /></label>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <button class="a-btn accent" type="submit" :disabled="busy || !ready">{{ busy ? 'Pairing…' : 'Pair' }}</button>
      <p class="foot">It sees the whole bench from anywhere: every printer, its camera, the shelf. Starting a print waits for someone at home.</p>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { prettyCode } from '../away'
import { checkHere, pairBox } from '../here'
import { startBench } from '../live'

defineProps<{ landing?: boolean }>()
const router = useRouter()
const fromLink = location.pathname === '/pair' ? decodeURIComponent(location.hash.slice(1)) : ''
const code = ref(fromLink ? prettyCode(fromLink) : '')
const name = ref('')
const busy = ref(false)
const error = ref('')
const ready = computed(() => code.value.replace(/[^a-z0-9]/gi, '').length >= 8 && !!name.value.trim())

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await pairBox(code.value, name.value.trim())
    history.replaceState(null, '', '/')
    await checkHere()
    startBench()
    await router.replace('/')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.way { min-height: 100%; box-sizing: border-box; display: grid; justify-items: center; align-content: start; padding: 56px 24px 32px; }
.box { width: 100%; max-width: 440px; display: grid; gap: 14px; }
.mark { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 16%, transparent); }
.mark svg { width: 28px; height: 28px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; }
.eyebrow { margin: 8px 0 -8px; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
h1 { margin: 0; font-size: 30px; line-height: 1.12; letter-spacing: -.02em; text-wrap: balance; }
.sub { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0 0 6px; }
label { display: grid; gap: 8px; font-size: 15px; font-weight: 650; color: var(--a-ink-2); }
input { font: inherit; font-size: 19px; font-weight: 500; color: var(--a-ink); background: var(--a-surface); border: 1.5px solid var(--a-line);
        border-radius: 14px; padding: 13px 16px; outline: none; user-select: text; -webkit-user-select: text; }
input:focus { border-color: var(--a-accent); }
.codein { font-size: 24px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.err { color: var(--a-red-text); font-size: 15px; margin: 0; }
.box .a-btn { height: 54px; border-radius: 999px; font-size: 18px; font-weight: 650; margin-top: 4px; }
.foot { margin: 4px 0 0; color: var(--a-ink-3); font-size: 14px; line-height: 1.45; }
</style>
