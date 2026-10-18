<template>
  <!-- An invite link, opened anywhere (design/bench-remote/, C-guest-open): who invited you, what you can do and until
       when, your name, and in. The code stays in the fragment, so it never reaches a log. -->
  <section class="way">
    <div class="box">
      <span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="8" height="9" rx="1.5"/><rect x="13" y="4" width="8" height="9" rx="1.5"/><rect x="8" y="14.5" width="8" height="6.5" rx="1.5"/></svg></span>
      <p class="eyebrow">Elyir Bench</p>
      <template v-if="look">
        <h1 class="a-display">{{ joinTitle(look) }}</h1>
        <div class="card">
          <span class="row"><span class="chip"><svg viewBox="0 0 24 24" aria-hidden="true" v-html="look.reach === 'watch' ? EYE : LOCK"></svg>{{ card!.chip }}</span>
            <span class="until">{{ card!.until }}</span></span>
          <p>{{ card!.line }}</p>
        </div>
        <form @submit.prevent="submit">
          <label><span>Your name</span><input v-model="name" maxlength="40" autocomplete="given-name" required /></label>
          <p v-if="error" class="err" role="alert">{{ error }}</p>
          <button class="a-btn accent" type="submit" :disabled="busy || !name.trim()">{{ busy ? 'Opening…' : 'Open the bench' }}</button>
        </form>
        <p class="foot">{{ joinFoot(look) }}</p>
      </template>
      <template v-else-if="error">
        <h1 class="a-display">This link doesn't work any more.</h1>
        <p class="sub">{{ error }} An invite works once, and unopened it stops working after a day. Ask the person who sent it for a new one.</p>
      </template>
      <p v-else class="sub">Opening the invite…</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { joinCard, joinFoot, joinTitle, type Look } from '../away'
import { checkHere, join, lookAt } from '../here'
import { startBench } from '../live'
import { EYE, LOCK } from './AwayChip.vue'

const router = useRouter()
const code = decodeURIComponent(location.hash.slice(1))
const look = ref<Look | null>(null)
const card = computed(() => (look.value ? joinCard(look.value, new Date()) : null))
const name = ref('')
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  if (!code) { error.value = 'This link has no invite in it.'; return }
  try {
    look.value = await lookAt(code)
  } catch (e) {
    error.value = (e as Error).message
  }
})

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await join(code, name.value.trim())
    history.replaceState(null, '', '/')            // the used code out of the address
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
.box { width: 100%; max-width: 440px; display: grid; gap: 0; }
.mark { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 16%, transparent); }
.mark svg { width: 28px; height: 28px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; }
.eyebrow { margin: 22px 0 6px; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
h1 { margin: 0 0 18px; font-size: 30px; line-height: 1.12; letter-spacing: -.02em; text-wrap: balance; }
.sub { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0; }
.card { background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); padding: 16px 18px; display: grid; gap: 10px; margin-bottom: 22px; }
.card .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.card p { margin: 0; color: var(--a-ink-2); font-size: 16px; line-height: 1.45; }
.chip { display: inline-flex; align-items: center; gap: 7px; padding: 4px 12px; border-radius: 999px; font-size: 15px; font-weight: 650;
        background: color-mix(in srgb, var(--a-accent) 16%, transparent); color: var(--a-accent-text); }
.chip svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linejoin: round; }
.until { color: var(--a-ink-3); font-size: 15px; }
form { display: grid; gap: 14px; }
label { display: grid; gap: 8px; font-size: 15px; font-weight: 650; color: var(--a-ink-2); }
input { font: inherit; font-size: 19px; font-weight: 500; color: var(--a-ink); background: var(--a-surface); border: 1.5px solid var(--a-line);
        border-radius: 14px; padding: 13px 16px; outline: none; user-select: text; -webkit-user-select: text; }
input:focus { border-color: var(--a-accent); }
form .a-btn { height: 54px; border-radius: 999px; font-size: 18px; font-weight: 650; }
.err { color: var(--a-red-text); font-size: 15px; margin: 0; }
.foot { margin: 16px 0 0; color: var(--a-ink-3); font-size: 14px; line-height: 1.45; }
</style>
