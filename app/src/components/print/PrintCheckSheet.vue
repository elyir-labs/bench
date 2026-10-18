<template>
  <!-- a file that changes colour on a printer with a unit plans it first (design/colour-change/, C) -->
  <ColourPlanSheet v-if="check?.colour" :check="check" @close="$emit('close')" />
  <Teleport v-else to="body">
    <Transition name="sheet">
      <div v-if="check && !check.ok" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="check.headline">
          <div class="needs" aria-hidden="true">
            <span v-for="(m, i) in check.missing.slice(0, 3)" :key="i" class="need">
              <span class="swatch" :style="{ '--c': m.color || 'transparent' }"></span>
              <span class="mat">{{ m.material }}</span>
            </span>
          </div>
          <div class="words">
            <h2 class="a-display headline">{{ check.headline }}</h2>
            <p class="detail">{{ check.detail }}</p>
            <div class="actions">
              <button
                v-for="a in check.actions"
                :key="a.id"
                class="a-btn"
                :class="a.primary ? 'accent' : 'ghost'"
                :disabled="!!store.busyAction"
                @click="run(a)"
              >{{ a.label }}</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { IntentAction, PrintCheck } from '@/intent/types'
import ColourPlanSheet from './ColourPlanSheet.vue'

defineProps<{ check: PrintCheck | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const router = useRouter()

async function run(a: IntentAction) {
  if (a.id === 'open_materials') {
    emit('close')
    router.push('/materials')
    return
  }
  await store.act(a)
  emit('close')
  if (a.id === 'start_file' || a.id === 'confirm_spool') router.push('/')
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: calc(16 * var(--u) + 8px);
}
.sheet {
  background: var(--a-surface);
  border-radius: calc(22 * var(--u) + 8px);
  box-shadow: var(--a-card-shadow);
  max-width: 760px; width: 100%;
  display: flex; align-items: center; gap: calc(24 * var(--u) + 8px);
  padding: calc(24 * var(--u) + 10px);
}
.needs { display: flex; gap: calc(12 * var(--u) + 4px); flex: none; }
.need { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.swatch {
  width: calc(64 * var(--u) + 20px); height: calc(64 * var(--u) + 20px); border-radius: 50%;
  background: var(--c); border: 4px dashed var(--a-amber); box-sizing: border-box;
}
.mat { font-weight: 700; font-size: calc(13 * var(--u) + 4px); color: var(--a-ink-2); letter-spacing: 0.04em; }
.words { flex: 1; min-width: 0; }
.headline { font-size: calc(26 * var(--u) + 8px); margin: 0 0 6px; line-height: 1.1; }
.detail { color: var(--a-ink-2); font-size: calc(15 * var(--u) + 5px); margin: 0 0 calc(16 * var(--u) + 6px); line-height: 1.35; }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); flex-wrap: wrap; }
.actions .a-btn { flex: 1 1 auto; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }

@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { flex-direction: column; align-items: stretch; border-radius: 22px 22px 0 0; }
  .needs { justify-content: center; }
}
</style>
