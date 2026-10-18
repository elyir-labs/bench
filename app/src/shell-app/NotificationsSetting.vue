<template>
  <!-- Notifications on this phone or computer: moved from the list to You (design/printers-home/, A) -->
  <section class="settings">
    <div class="setting">
      <div class="text">
        <span class="name">Notifications</span>
        <span class="when">{{ pushLine }}</span>
      </div>
      <div class="seg" v-if="push.state === 'on' || push.state === 'off' || push.state === 'partial'" role="radiogroup" aria-label="Notifications">
        <button class="seg-opt" :class="{ on: push.state === 'off' }" :disabled="busy" @click="set(false)">Off</button>
        <button class="seg-opt" :class="{ on: push.state !== 'off' }" :disabled="busy" @click="set(true)">On</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { printers } from './printers'
import { disablePush, enablePush, pushState, type PushState } from './push'

const push = reactive<{ state: PushState | null; printers: Record<string, boolean> }>({ state: null, printers: {} })
const busy = ref(false)

async function refresh() {
  Object.assign(push, await pushState())
}
onMounted(refresh)
// once printers become reachable, their subscription status can be read
watch(() => printers.map((p) => p.reach).join(), refresh)

const pushLine = computed(() => {
  const missing = printers.filter((p) => p.base && !push.printers[p.id]).map((p) => p.name)
  switch (push.state) {
    case 'on': return 'Every printer tells this phone when a print is done or needs you.'
    case 'partial': return `On, except ${missing.join(' and ')}. Turn it on again to include ${missing.length > 1 ? 'them' : 'it'}.`
    case 'off': return 'Tell this phone when a print is done or needs you.'
    case 'needs-install': return 'To get them on this iPhone, tap Share, then Add to Home Screen, and open Printers from there.'
    case 'blocked': return 'Notifications are turned off for Printers in your settings.'
    case 'insecure': case 'unsupported': return "This browser can't show notifications."
    default: return 'Checking…'
  }
})

async function set(on: boolean) {
  busy.value = true
  try {
    await (on ? enablePush() : disablePush())
  } finally {
    await refresh()
    busy.value = false
  }
}
</script>

<style scoped>
.setting {
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 14px 16px; border-radius: 20px; background: var(--a-surface); box-shadow: var(--a-card-shadow);
}
.setting .text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.setting .name { font-size: 17px; font-weight: 650; }
.when { color: var(--a-ink-3); font-size: 14px; line-height: 1.35; }
.seg { display: flex; flex: none; padding: 4px; gap: 4px; border-radius: 99px; background: var(--a-surface-2); }
.seg-opt {
  appearance: none; border: 0; font: inherit; font-weight: 600; font-size: 15px;
  min-height: 40px; min-width: 64px; padding: 0 14px; border-radius: 99px;
  background: transparent; color: var(--a-ink-2); cursor: pointer;
}
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
</style>
