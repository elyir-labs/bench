<template>
  <!-- Which side down: each side a picture of the part lying so, with what touches and its rough supports
       (design/orientation/). Only the one down now has a real time. -->
  <div class="opts">
    <button v-for="o in tiles" :key="o.key" class="opt lay" :class="{ on: o.on }" @click="$emit('pick', o.normal)">
      <ModelPicture :tris="o.tris" :color="color" :alt="o.title" plate class="tile" />
      <span class="t"><b>{{ o.title }}<i v-for="tag in o.tags" :key="tag" class="tag">{{ tag }}</i></b><span>{{ o.note }}</span></span>
      <span v-if="o.on && time" class="tm a-num"><b>{{ time }}</b><span>{{ timeNote }}</span></span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw } from 'vue'
import { layOn } from '@/slice/stl'
import type { SideOption } from '@/slice/sides'
import ModelPicture from './ModelPicture.vue'

const props = withDefaults(defineProps<{ options: SideOption[]; file: Float32Array; color: string; time?: string; timeNote?: string }>(),
  { time: '', timeNote: 'the plate' })
defineEmits<{ pick: [normal: number[] | null] }>()

const tiles = computed(() => props.options.map((o) => ({ ...o, tris: o.normal ? markRaw(layOn(props.file, o.normal)) : props.file })))
</script>

<style scoped>
.opts { display: grid; gap: 9px; }
.opt { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 14px; background: var(--a-surface); border-radius: 18px; padding: 13px 14px; border: 2px solid transparent; box-shadow: var(--a-card-shadow); }
.opt.on { border-color: var(--a-accent); }
.opt.lay { padding: 10px 12px 10px 10px; }
.opt:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.opt .tile { width: 104px; height: 78px; border-radius: 12px; flex: none; }
.opt .t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.opt .t b { font-size: 18px; }
.opt .t span { font-size: 13.5px; color: var(--a-ink-3); line-height: 1.3; }
.opt .t b .tag { white-space: nowrap; display: inline-block; font-style: normal; font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-accent-text); margin-left: 8px; vertical-align: 2px; }
.opt .tm { text-align: right; display: grid; gap: 1px; flex: none; }
.opt .tm b { font-size: 17px; }
.opt .tm span { font-size: 13px; color: var(--a-ink-3); }
</style>
