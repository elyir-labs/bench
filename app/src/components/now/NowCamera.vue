<template>
  <!-- Now's hero when the printer has a camera: the live picture where the ring would be.
       The object shrinks to a chip on the video, progress runs along its bottom edge. -->
  <div class="nowcam">
    <CameraView
      :camera="camera"
      :tone="tone"
      :progress="progress"
      expandable
      @expand="cameraOpen = true"
      @failed="emit('failed')"
      @click="cameraOpen = true"
    >
      <span v-if="pill" class="chip a-num">
        <ObjectImage v-if="thumb !== undefined" :src="thumb" :alt="alt" round class="chip-img" />
        <span>{{ pill }}</span>
      </span>
    </CameraView>
  </div>
</template>

<script setup lang="ts">
import CameraView from '@/components/camera/CameraView.vue'
import ObjectImage from './ObjectImage.vue'
import { cameraOpen } from '@/camera/viewer'
import type { Camera } from '@/camera/cameras'

withDefaults(defineProps<{
  camera: Camera
  tone?: 'accent' | 'amber' | 'red' | 'green' | 'none'
  progress?: number | null
  thumb?: string | null
  alt?: string
  pill?: string
}>(), { tone: 'none', progress: null, pill: '' })
const emit = defineEmits<{ failed: [] }>()
</script>

<style scoped>
.nowcam { width: 100%; border-radius: 20px; overflow: hidden; box-shadow: var(--a-card-shadow); cursor: zoom-in; }
.nowcam :deep(.cam) { border-radius: 20px; }
.chip {
  position: absolute; right: 10px; bottom: 14px;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 12px 4px 4px; border-radius: 99px;
  background: rgba(255, 255, 255, 0.92); color: #0b0e13;
  font-weight: 700; font-size: 15px;
}
.chip-img { width: 32px; height: 32px; }
</style>
