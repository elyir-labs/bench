<template>
  <!-- "Away" while at home (design/printers-away/, A + B): what away means, look on this Wi-Fi, and what to check when
       the printer isn't found. The note says when one is. -->
  <Teleport to="body">
    <div v-if="awaySheet.open" class="scrim" @click.self="close">
      <div class="sheet" role="dialog" aria-modal="true" :aria-label="title">
        <h3>{{ title }}</h3>
        <template v-if="awaySheet.state === 'notfound'">
          <div class="why">
            <div><b>Is this {{ device }} on the house Wi-Fi?</b><span>Mobile data or a guest network can't see the printer.</span></div>
            <div><b>Did your browser ask about devices on your network?</b><span>Allow it for {{ site }}, in the browser's site settings if you said no.</span></div>
          </div>
          <p class="body">{{ stillAway(names) }}</p>
          <button class="a-btn accent big" @click="look">Look again</button>
          <button class="a-btn ghost big" @click="close">Not now</button>
        </template>
        <template v-else>
          <p class="body">From here you can watch, pause and stop. Starting prints, heating and changing spools need the same Wi-Fi as the printer.</p>
          <p class="body">The app looks on this Wi-Fi every 30 seconds by itself.</p>
          <button class="a-btn accent big" :disabled="awaySheet.state === 'looking'" @click="look">
            <span v-if="awaySheet.state === 'looking'" class="spin" aria-hidden="true"></span>
            {{ awaySheet.state === 'looking' ? 'Looking on this Wi-Fi…' : "I'm home: look on this Wi-Fi" }}
          </button>
          <button class="a-btn ghost big" @click="close">OK</button>
        </template>
      </div>
    </div>
  </Teleport>
  <Transition name="toast">
    <div v-if="foundNote" class="toast" role="status"><i aria-hidden="true"></i>{{ foundNote }}</div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { awaySheet, foundNote, lookFor } from './home-look'
import { printerById } from './printers'
import { awayTitle, notFoundTitle, stillAway } from './reach'

const names = computed(() => awaySheet.ids.map((id) => printerById(id)?.name).filter((n): n is string => !!n))
const title = computed(() => (awaySheet.state === 'notfound' ? notFoundTitle(names.value) : awayTitle(names.value)))
const device = /iPad|Tablet/i.test(navigator.userAgent) ? 'tablet' : /Mobi|Android/i.test(navigator.userAgent) ? 'phone' : 'computer'
const site = location.host

function look() { lookFor(awaySheet.ids, true) }
function close() { if (awaySheet.state !== 'looking') awaySheet.open = false }

const SHOW_MS = 4000
let timer = 0
watch(foundNote, (w) => {
  window.clearTimeout(timer)
  if (w) timer = window.setTimeout(() => { foundNote.value = '' }, SHOW_MS)
})
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, 0.45); display: flex; align-items: flex-end; justify-content: center; }
.sheet {
  width: min(480px, 100%); box-sizing: border-box; background: var(--a-surface); color: var(--a-ink); font-family: var(--a-font);
  border-radius: 22px 22px 0 0; box-shadow: var(--a-card-shadow);
  padding: 22px 20px calc(18px + env(safe-area-inset-bottom, 0px)); display: flex; flex-direction: column; gap: 12px;
}
@media (min-width: 600px) {
  .scrim { align-items: center; }
  .sheet { border-radius: 22px; padding-bottom: 20px; }
}
h3 { margin: 0; font-size: 22px; line-height: 1.25; text-wrap: balance; overflow-wrap: anywhere; }
.body { margin: 0; color: var(--a-ink-2); font-size: 16px; line-height: 1.45; }
.why { display: flex; flex-direction: column; gap: 8px; }
.why div { display: flex; flex-direction: column; gap: 3px; padding: 12px 14px; border-radius: 14px; background: var(--a-bg); }
.why b { font-size: 16px; }
.why span { color: var(--a-ink-3); font-size: 14px; line-height: 1.4; }
.big { width: 100%; min-height: 50px; font-size: 17px; display: inline-flex; align-items: center; justify-content: center; gap: 10px; }
.spin { width: 16px; height: 16px; border-radius: 50%; border: 2.5px solid currentColor; border-right-color: transparent; animation: spin .8s linear infinite; flex: none; }
@keyframes spin { to { transform: rotate(360deg); } }

/* above a printer's own tabs */
.toast {
  position: fixed; z-index: 70; left: 50%; transform: translateX(-50%); bottom: calc(84px + env(safe-area-inset-bottom, 0px));
  width: min(460px, calc(100% - 24px)); box-sizing: border-box; display: flex; align-items: center; gap: 10px;
  padding: 14px 16px; border-radius: 14px; background: var(--a-ink); color: var(--a-bg);
  font-family: var(--a-font); font-size: 15px; font-weight: 600; line-height: 1.4; box-shadow: var(--a-card-shadow);
}
.toast i { width: 9px; height: 9px; border-radius: 50%; background: var(--a-green); flex: none; }
.toast-enter-active, .toast-leave-active { transition: opacity 160ms ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; }
</style>
