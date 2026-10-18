<template>
  <!-- The panel's own keyboard (design/setup/ s-here): a touchscreen kiosk has none. Letters, then numbers and
       the common symbols, then the rest, so any Wi-Fi password can be typed. A USB keyboard works too. -->
  <div class="kb" role="group" aria-label="Keyboard">
    <div v-for="(row, i) in rows" :key="layer + i" class="row">
      <button v-for="k in row" :key="k" type="button" :class="['key', { fn: FN.has(k), go: k === GO, on: k === SHIFT && shift }]"
              :style="k === SPACE ? 'flex: 1; max-width: none' : ''" :disabled="k === GO && !canGo"
              @pointerdown.prevent @click="press(k)">{{ label(k) }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{ modelValue: string; action: string; canGo?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'go'): void }>()

const SHIFT = '⇧', BACK = '⌫', SPACE = ' ', GO = '⏎', TO_NUM = '123', TO_SYM = '#+=', TO_ABC = 'ABC'
const FN = new Set([SHIFT, BACK, TO_NUM, TO_SYM, TO_ABC])
const LAYERS: Record<'abc' | 'num' | 'sym', string[][]> = {
  abc: [[...'qwertyuiop'], [...'asdfghjkl'], [SHIFT, ...'zxcvbnm', BACK], [TO_NUM, SPACE, GO]],
  num: [[...'1234567890'], [...'-/:;()$&@"'], [TO_SYM, ...".,?!'", BACK], [TO_ABC, SPACE, GO]],
  sym: [[...'[]{}#%^*+='], [...'_\\|~<>€£¥•'], [TO_NUM, ...".,?!'", BACK], [TO_ABC, SPACE, GO]],
}
const layer = ref<'abc' | 'num' | 'sym'>('abc')
const shift = ref(false)
const rows = computed(() => LAYERS[layer.value])
const canGo = computed(() => props.canGo ?? true)

function label(k: string): string {
  if (k === GO) return props.action
  if (k === SPACE) return 'space'
  return layer.value === 'abc' && shift.value && k.length === 1 ? k.toUpperCase() : k
}

function press(k: string): void {
  const v = props.modelValue
  if (k === SHIFT) shift.value = !shift.value
  else if (k === BACK) emit('update:modelValue', v.slice(0, -1))
  else if (k === TO_NUM) layer.value = 'num'
  else if (k === TO_SYM) layer.value = 'sym'
  else if (k === TO_ABC) layer.value = 'abc'
  else if (k === GO) emit('go')
  else {
    emit('update:modelValue', v + label(k))
    shift.value = false   // one capital, as on a phone
  }
}
</script>

<style scoped>
.kb { display: grid; gap: calc(7 * var(--u) + 1px); padding: calc(10 * var(--u)) calc(12 * var(--u)) calc(12 * var(--u)); background: var(--a-surface); }
.row { display: flex; gap: calc(6 * var(--u) + 1px); justify-content: center; }
.key {
  appearance: none; border: 0; margin: 0; flex: 0 1 calc(70 * var(--u)); max-width: calc(70 * var(--u));
  height: calc(50 * var(--u)); min-height: 40px; border-radius: calc(9 * var(--u));
  background: var(--a-surface-2); color: var(--a-ink); font: 500 calc(22 * var(--u)) var(--a-font); cursor: pointer;
}
.key.fn { flex-basis: calc(96 * var(--u)); max-width: calc(110 * var(--u)); font-size: calc(17 * var(--u)); font-weight: 650; color: var(--a-ink-2); background: var(--a-bg); }
.key.on { background: var(--a-ink); color: var(--a-bg); }
.key.go { flex-basis: calc(150 * var(--u)); max-width: calc(170 * var(--u)); background: var(--a-accent); color: var(--a-accent-ink); font-weight: 650; font-size: calc(18 * var(--u)); }
.key.go[disabled] { opacity: .45; }
.key:active { filter: brightness(1.25); }
.key:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
</style>
