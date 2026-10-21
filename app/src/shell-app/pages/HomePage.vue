<template>
  <!-- design/printers-open/, A: a printer gets the whole window under the app's one bar; "‹ Printers" is the list,
       which on a laptop or tablet is the overview. One printer opens straight away. -->
  <PrinterPage v-if="kept.length" v-show="id" :wide="wide" :kept="kept" @drop="drop" />
  <ListPage v-if="!id" :wide="wide" />
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

// Printers opened lately stay loaded behind the one shown (and behind the list), so going back to one is instant: the
// newest first, a few on a laptop, fewer on a phone.
// kept stays in the order opened: moving a frame within the page reloads it.
const kept = ref<string[]>([])
let recent: string[] = []
const keep = computed(() => (wide.value ? 3 : 2))
watch([id, keep], () => {
  if (id.value) {
    recent = [id.value, ...recent.filter((k) => k !== id.value)]
    if (!kept.value.includes(id.value)) kept.value = [...kept.value, id.value]
  }
  recent = recent.slice(0, keep.value)
  kept.value = kept.value.filter((k) => recent.includes(k))
}, { immediate: true })
function drop(k: string) {
  if (k === id.value) return
  recent = recent.filter((x) => x !== k)
  kept.value = kept.value.filter((x) => x !== k)
}

watch([id, listed, () => printers.length, () => benches.length], () => {
  const only = listed.value && !id.value ? straightIn(printers, benches.length) : null
  if (only) router.replace(`/p/${only}`)
}, { immediate: true })
</script>
