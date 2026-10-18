<template>
  <!-- A phone away that isn't paired yet sees only this. The panel's "Add a phone" QR code
       opens /pair#CODE here; the code stays in the fragment so it never reaches a log. -->
  <main class="pair">
    <div class="box">
      <div class="mark" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg></div>

      <!-- iPhone in Safari: pair inside the Home Screen app, which may not share Safari's cookies -->
      <template v-if="installFirst">
        <h1 class="a-display">Add the printer to your Home Screen</h1>
        <ol class="steps">
          <li>Tap <b>Share</b>, then <b>Add to Home Screen</b>.</li>
          <li>Open the printer from your Home Screen.</li>
          <li>Type this code there<template v-if="!code">, from the printer's screen</template>:</li>
        </ol>
        <p v-if="code" class="code a-num">{{ pretty(code) }}</p>
        <p class="sub">That way notifications reach this iPhone. The code works once, for ten minutes.</p>
        <button class="link" @click="installFirst = false">Just use Safari, without notifications</button>
      </template>

      <template v-else>
        <h1 class="a-display">Pair with the printer</h1>
        <p class="sub">On the printer's screen, go to <b>Care</b>, then <b>Phones</b>, then <b>Add a phone</b>, and type the code it shows.</p>
        <form @submit.prevent="submit">
          <label>
            <span>Code</span>
            <input v-model="code" class="a-num codein" inputmode="text" autocapitalize="characters" autocomplete="one-time-code"
                   spellcheck="false" maxlength="9" placeholder="ABCD-EFGH" required />
          </label>
          <label>
            <span>Name for this {{ kind }}</span>
            <input v-model="name" maxlength="40" required />
          </label>
          <p v-if="error" class="err">{{ error }}</p>
          <button class="a-btn accent" type="submit" :disabled="busy || !ready">{{ busy ? 'Pairing…' : 'Pair' }}</button>
        </form>
      </template>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { guessDeviceName, pair } from '@/door'

const emit = defineEmits<{ (e: 'paired'): void }>()

const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const standalone = window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
const installFirst = ref(isIOS && !standalone)

const fromLink = decodeURIComponent(window.location.hash.slice(1)).replace(/[^a-z0-9]/gi, '').toUpperCase()
const code = ref(fromLink)
const name = ref(guessDeviceName())
const kind = /iPhone|Android.*Mobile/.test(navigator.userAgent) ? 'phone' : 'device'
const busy = ref(false)
const error = ref<string | null>(null)

const pretty = (c: string) => c.replace(/[^a-z0-9]/gi, '').toUpperCase().replace(/^(.{4})(.+)$/, '$1-$2')
const ready = computed(() => code.value.replace(/[^a-z0-9]/gi, '').length >= 8 && name.value.trim().length > 0)

async function submit() {
  busy.value = true
  error.value = null
  try {
    await pair(code.value, name.value.trim())
    history.replaceState(null, '', '/')   // drop the used code from the address
    emit('paired')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.pair {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px 20px calc(24px + var(--safe-b));
  box-sizing: border-box;
  background: var(--a-bg);
  color: var(--a-ink);
  font-family: var(--a-font);
  -webkit-font-smoothing: antialiased;
  text-align: left;
}
.box { width: 100%; max-width: 420px; }
.mark { width: 44px; height: 44px; color: var(--a-accent); margin-bottom: 18px; }
.mark svg { width: 100%; height: 100%; display: block; }
h1 { font-size: 30px; margin: 0 0 10px; color: var(--a-ink); }
.sub { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0 0 20px; }
.sub b, .steps b { color: var(--a-ink); }
.steps { list-style: decimal; margin: 0 0 16px; padding-left: 1.3em; font-size: 18px; line-height: 1.5; color: var(--a-ink-2); }
.steps li { margin: 0 0 6px; color: var(--a-ink-2); }
.code { font-size: 40px; font-weight: 700; letter-spacing: 0.08em; margin: 4px 0 18px; color: var(--a-ink); }
form { display: flex; flex-direction: column; gap: 14px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
input {
  font: inherit; font-size: 20px; font-weight: 500; color: var(--a-ink);
  background: var(--a-surface); border: 1px solid var(--a-line); border-radius: 14px;
  padding: 14px 16px; outline: none; user-select: text; -webkit-user-select: text;
}
input:focus { border-color: var(--a-accent); }
.codein { font-size: 26px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.err { color: var(--a-red-text); font-size: 16px; margin: 0; }
form .a-btn { flex: none; margin-top: 6px; font-size: 19px; padding: 16px 20px; border-radius: 16px; }
.link { appearance: none; background: none; border: 0; padding: 8px 0; font: inherit; font-size: 16px; font-weight: 600; color: var(--a-accent-text); cursor: pointer; }
</style>
