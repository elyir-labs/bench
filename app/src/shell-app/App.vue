<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { loadPrinters, watchNetwork } from './printers'
import { registerServiceWorker } from './push'
import { pending } from './look'
import { refreshAccount } from './account'
import { MODEL_EXT } from '@/look/read.ts'

const router = useRouter()

// models dropped anywhere on the app open on the Look page, together (design/look/)
const files = (e: DragEvent) => e.dataTransfer?.types.includes('Files')
function dragover(e: DragEvent) {
  if (files(e)) e.preventDefault()
}
function dropped(e: DragEvent) {
  if (!files(e)) return
  e.preventDefault()
  const fs = [...(e.dataTransfer?.files ?? [])].filter((x) => MODEL_EXT.test(x.name))
  if (!fs.length) return
  pending.value = fs
  if (router.currentRoute.value.path !== '/look') router.push('/look')
}

onMounted(() => {
  window.addEventListener('dragover', dragover)
  window.addEventListener('drop', dropped)
  loadPrinters()
  refreshAccount()
  watchNetwork()
  registerServiceWorker()
  // a tapped notification while the app is open: go there without a reload
  navigator.serviceWorker?.addEventListener('message', (ev) => {
    if (ev.data?.type !== 'printers:open') return
    const u = new URL(ev.data.target, location.origin)
    if (u.origin === location.origin) router.push(u.pathname + u.hash)
  })
})
</script>
