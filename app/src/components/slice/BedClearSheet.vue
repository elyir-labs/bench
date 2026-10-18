<template>
  <!-- Before a phone starts a print: is the bed clear? Decided on 2 October 2026
       (design/print-a-model/, "Is the bed clear?"). The camera shows the bed where there is one. -->
  <SliceSheet :open="open" eyebrow="Before it starts" amber :title="`Is ${printer}'s bed clear?`"
    :sub="`Take off the last print and anything else on the plate. ${printer} will move and heat up as soon as you say.`"
    @close="$emit('close')">
    <div v-if="camera && !camFailed" class="bed">
      <CameraView :camera="camera" watching @failed="camFailed = true" />
    </div>
    <div class="acts">
      <button class="a-btn accent" :disabled="working" @click="$emit('confirm')">{{ working ? 'Starting…' : 'It\'s clear, print' }}</button>
      <button class="a-btn ghost" :disabled="working" @click="$emit('close')">Not yet</button>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SliceSheet from './SliceSheet.vue'
import CameraView from '@/components/camera/CameraView.vue'
import { useCameras } from '@/camera/useCameras'

const props = defineProps<{ open: boolean; printer: string; working?: boolean }>()
defineEmits<{ close: []; confirm: [] }>()
const { cameras } = useCameras()
const camera = computed(() => cameras.value[0] ?? null)
const camFailed = ref(false)
watch(() => props.open, (o) => { if (o) camFailed.value = false })
</script>

<style scoped>
.bed { border-radius: 18px; overflow: hidden; margin-bottom: 16px; background: #000; }
.acts { display: grid; gap: 10px; }
.acts .a-btn { width: 100%; height: 54px; font-size: 18px; border-radius: 18px; }
</style>
