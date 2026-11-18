<template>
  <UsbSheet :sheet="shown" :stick-id="u?.id ?? null" :busy="busy" :error="error" @act="act" />
</template>

<script setup lang="ts">
// A USB stick in the Bench Box (design/usb/, 3 A): the box takes it for itself, and the Kobras' screens with it.
// Home only: the away listener never routes /bench/box.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UsbSheet from '@/components/usb/UsbSheet.vue'
import { usbUi } from '@/components/usb/usbUi'
import { usbSheet, usbTakeArgs, type UsbActKey, type UsbView } from '@/intent/usb'
import { boxPost, boxUsb } from '../box'
import { bench } from '../live'

const u = ref<UsbView | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const hidden = ref<string | null>(null)
const kobras = computed(() => bench.printers.some((x) => x.intent?.printer?.standin === 'bench'))
const sheet = computed(() => usbSheet(u.value, 'the Bench Box', { box: true, kobras: kobras.value, force: usbUi.force }))
const sheetKey = computed(() => (sheet.value ? `${u.value?.id}/${u.value?.take?.state ?? 'ask'}/${sheet.value.title}` : null))
const shown = computed(() => (sheet.value && sheetKey.value !== hidden.value ? sheet.value : null))

let timer = 0
async function look() {
  const got = await boxUsb()
  if (got !== undefined) u.value = got
}
onMounted(() => { void look(); timer = window.setInterval(look, 3000) })
onBeforeUnmount(() => window.clearInterval(timer))

watch(shown, (s) => {
  if (s && u.value && !u.value.seen && !u.value.take) void boxPost('usb', { action: 'seen' })
})

async function act(key: UsbActKey, ticks: Record<string, boolean>) {
  error.value = null
  if (key === 'hide') {
    hidden.value = sheetKey.value
    return
  }
  busy.value = true
  error.value = key === 'take' && u.value
    ? await boxPost('usb', { action: 'take', ...usbTakeArgs(u.value, ticks) })
    : await boxPost('usb', { action: 'skip' })
  busy.value = false
  if (!error.value) usbUi.force = false
  await look()
}
</script>
