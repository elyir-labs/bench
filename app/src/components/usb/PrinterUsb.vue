<template>
  <UsbBanner v-if="banner" :banner="banner" :busy="busy" @skip="act('skip', {})" />
  <UsbSheet :sheet="shown" :stick-id="u?.id ?? null" :busy="busy" :error="error" @act="act" />
</template>

<script setup lang="ts">
// A USB stick in this printer (design/usb/): the sheet over any screen at home, the line over a print, and the
// screen saying it saw the stick, so the installer doesn't update by itself as it does with no screen answering.
import { computed, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { allowedHere } from '@/door'
import { usbBanner, usbSheet, usbTakeArgs, type UsbActKey } from '@/intent/usb'
import UsbBanner from './UsbBanner.vue'
import UsbSheet from './UsbSheet.vue'
import { usbUi } from './usbUi'

const props = defineProps<{ name: string }>()
const store = useIntentStore()
const u = computed(() => store.intent?.usb ?? null)
const here = computed(() => allowedHere('usb_take'))
const printing = computed(() => {
  const i = store.intent
  return !!i?.job && ['preparing', 'printing', 'needs_you'].includes(i.state)
})
const opts = computed(() => ({ have: store.intent?.update?.version ?? null, printing: printing.value, force: usbUi.force }))
const sheet = computed(() => (here.value ? usbSheet(u.value, props.name, opts.value) : null))
const banner = computed(() => (here.value ? usbBanner(u.value, props.name, opts.value) : null))
const hidden = ref<string | null>(null)
const sheetKey = computed(() => (sheet.value ? `${u.value?.id}/${u.value?.take?.state ?? 'ask'}/${sheet.value.title}` : null))
const shown = computed(() => (sheet.value && sheetKey.value !== hidden.value ? sheet.value : null))
const busy = computed(() => !!store.busyAction?.startsWith('usb_'))
const error = ref<string | null>(null)

watch([shown, banner], () => {
  if ((shown.value || banner.value) && u.value && !u.value.seen && !u.value.take) void store.act('usb_seen')
})

async function act(key: UsbActKey, ticks: Record<string, boolean>) {
  error.value = null
  if (key === 'hide') {
    hidden.value = sheetKey.value
    return
  }
  if (key === 'take' && u.value) await store.act('usb_take', usbTakeArgs(u.value, ticks))
  else await store.act('usb_skip')
  error.value = store.actionError
  if (!error.value) usbUi.force = false
}
</script>
