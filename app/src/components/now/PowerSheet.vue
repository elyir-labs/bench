<template>
  <!-- Care's Turn off and Restart ask once (design/power/, A): what will happen, and from a phone, that only
       someone at the printer can switch it on again. The printer then waits for the nozzle; Now shows that. -->
  <SliceSheet :open="kind !== null" :title="words.title" :sub="words.body" @close="$emit('close')">
    <p v-if="words.note" class="note">{{ words.note }}</p>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <div class="acts">
      <button class="a-btn ghost" :disabled="working" @click="$emit('close')">Keep it on</button>
      <button class="a-btn accent" :disabled="working" @click="go">{{ working ? '…' : words.confirm }}</button>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import { useIntentStore } from '@/intent/store'
import { sheetWords, type PowerKind } from '@/intent/power'
import { isPanel } from '@/theme'

const props = defineProps<{ kind: PowerKind | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const router = useRouter()
const working = ref(false)
const error = ref<string | null>(null)
watch(() => props.kind, () => { error.value = null; working.value = false })

const words = computed(() => {
  const i = store.intent
  return sheetWords(props.kind ?? 'off', i?.printer.name || 'The printer', i?.printer.nozzle.temperature ?? 0,
    i?.power?.cool_to ?? 50, isPanel)
})

async function go() {
  if (!props.kind) return
  working.value = true
  await store.act(props.kind === 'off' ? 'power_off' : 'power_restart')
  working.value = false
  if (store.actionError) { error.value = store.actionError; return }
  emit('close')
  router.push('/')   // Now shows the wait
}
</script>

<style scoped>
.note { margin: -4px 0 14px; font-size: 15px; font-weight: 600; color: var(--a-amber-text); }
.err { margin: 0 0 12px; font-size: 14px; color: var(--a-red-text, #c0392b); }
.acts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.acts .a-btn { height: 54px; font-size: 18px; border-radius: 18px; }
</style>
