<template>
  <!-- A printer with two lights asks once which one lights the bed (design/chamber-light/, A): try each, pick one -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="lightAskOpen && ask" class="scrim" @click.self="lightAskOpen = false">
        <div class="sheet" role="dialog" aria-modal="true" aria-label="Which light lights the bed?">
          <header class="head">
            <div class="title">
              <h2 class="a-display">Which one lights the bed?</h2>
              <p class="sub">{{ name }} has {{ ask.length }} lights. Try each one, then pick the one that lights the bed.</p>
            </div>
            <button class="a-btn ghost small" @click="lightAskOpen = false">Not now</button>
          </header>
          <div class="rows">
            <div v-for="o in ask" :key="o.name" class="row" :class="{ on: o.on }">
              <span class="ic" v-html="BULB"></span>
              <span class="t"><b>{{ o.label }}</b><span class="a-num">{{ o.name.split(' ').slice(1).join(' ') }}</span></span>
              <span class="btns">
                <button class="a-btn ghost small" :disabled="o.on || store.busyAction !== null" @click="store.act('light_try', { name: o.name })">
                  {{ o.on ? 'On now' : 'Try it' }}
                </button>
                <button class="a-btn accent small" :disabled="store.busyAction !== null" @click="pick(o.name)">This one</button>
              </span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentStore } from '@/intent/store'
import { BULB, lightAskOpen } from '@/intent/light'

const store = useIntentStore()
const ask = computed(() => store.intent?.light?.ask ?? null)
const name = computed(() => store.intent?.printer?.name ?? 'This printer')

async function pick(obj: string) {
  await store.act('light_pick', { name: obj })
  lightAskOpen.value = false
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(10 * var(--u) + 4px); }
.sheet { background: var(--a-bg); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 620px; width: 100%; max-height: 100%; overflow: auto; padding: calc(14 * var(--u) + 6px) calc(16 * var(--u) + 6px); }
.head { display: flex; align-items: flex-start; gap: calc(8 * var(--u) + 2px); }
.title { flex: 1; min-width: 0; }
h2 { font-size: calc(22 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); margin: 4px 0 0; }
.a-btn.small { flex: none; min-height: 44px; padding: 0 calc(12 * var(--u) + 6px); font-size: calc(12 * var(--u) + 4px); }
.rows { display: grid; gap: calc(8 * var(--u) + 4px); margin-top: calc(12 * var(--u) + 4px); }
.row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: calc(8 * var(--u) + 4px); padding: calc(10 * var(--u) + 4px) calc(12 * var(--u) + 4px); border-radius: calc(14 * var(--u) + 6px); background: var(--a-surface); }
.ic { width: calc(28 * var(--u) + 16px); height: calc(28 * var(--u) + 16px); border-radius: calc(8 * var(--u) + 6px); background: var(--a-surface-2); color: var(--a-ink-2); display: grid; place-items: center; }
.ic :deep(svg) { width: 60%; height: 60%; }
.row.on .ic { background: #f5c451; color: #1a1300; }
.t { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.t b { font-size: calc(14 * var(--u) + 5px); font-weight: 600; }
.t span { font-size: calc(10 * var(--u) + 4.5px); color: var(--a-ink-3); overflow-wrap: anywhere; }
.btns { display: flex; gap: 8px; }
@media (max-width: 480px) {
  .btns { grid-column: 1 / -1; justify-content: flex-end; }
}
</style>
