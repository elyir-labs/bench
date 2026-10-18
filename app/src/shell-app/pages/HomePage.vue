<template>
  <!-- design/printers-open/, A: a printer gets the whole window under the app's one bar; "‹ Printers" is the list,
       which on a laptop or tablet is the overview. One printer opens straight away. -->
  <PrinterPage v-if="id" :wide="wide" />
  <ListPage v-else :wide="wide" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { benches, listed, printers } from '../printers'
import { straightIn } from '../home'
import ListPage from './ListPage.vue'
import PrinterPage from './PrinterPage.vue'

const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id ? String(route.params.id) : null))

const media = window.matchMedia('(min-width: 900px)')
const wide = ref(media.matches)
const onWidth = () => { wide.value = media.matches }
media.addEventListener('change', onWidth)
onBeforeUnmount(() => media.removeEventListener('change', onWidth))

watch([id, listed, () => printers.length, () => benches.length], () => {
  const only = listed.value && !id.value ? straightIn(printers, benches.length) : null
  if (only) router.replace(`/p/${only}`)
}, { immediate: true })
</script>
