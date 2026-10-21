<template>
  <!-- The spools to paint or change color with (design/paint-and-height/): the plate's colors and the loaded ones
       as dots, then "Another", which opens the colors you'd swap in by hand. -->
  <div class="tray" role="radiogroup" :aria-label="label">
    <button v-for="(c, k) in choices" :key="k" type="button" class="d" :class="{ on: k === on }" role="radio" :aria-checked="k === on"
            @click="$emit('pick', k)">
      <i class="sw" :class="{ hand: c.hand }" :style="{ '--c': c.color || 'transparent' }"></i>{{ word(c) }}
    </button>
    <button type="button" class="d" :class="{ on: more }" :aria-expanded="more" @click="more = !more"><span class="more">+</span>Another</button>
  </div>
  <div v-if="more" class="hand">
    <p>Swapped in by hand: the print waits for it.</p>
    <div class="sws">
      <button v-for="c in COLORS" :key="c.hex" type="button" class="sw" :style="{ '--c': c.hex }" :aria-label="c.name"
              @click="$emit('hand', c.hex); more = false"></button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { COLORS } from '@/components/materials/palette'
import { colorWord, type PlateSpool } from '@/slice/colors'

const props = defineProps<{ choices: PlateSpool[]; on: number; label: string }>()
defineEmits<{ pick: [k: number]; hand: [hex: string] }>()
const more = ref(false)
// another material than the plate's is said: it may not stick to it
const word = (c: PlateSpool) => [c.color ? colorWord(c.color) : '', c.material !== props.choices[0]?.material || !c.color ? c.material : ''].filter(Boolean).join(' ')
</script>

<style scoped>
.tray { display: flex; gap: 10px; overflow-x: auto; padding: 4px 2px 6px; scrollbar-width: none; }
.d { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; display: grid; justify-items: center; gap: 5px; flex: none; width: 54px;
  font-size: 12px; font-weight: 600; color: var(--a-ink-3); line-height: 1.15; text-align: center; padding: 0; }
.d.on { color: var(--a-ink); }
.sw { display: block; width: 42px; height: 42px; border-radius: 50%; background: var(--c); border: 2.5px solid var(--a-swatch-edge); box-sizing: border-box; }
.sw.hand { border-style: dashed; border-color: var(--a-ink-2); }
.d.on .sw, .d.on .more { outline: 3px solid var(--a-accent); outline-offset: 3px; }
.more { width: 42px; height: 42px; border-radius: 50%; border: 2px dashed var(--a-ink-3); display: grid; place-items: center; font-size: 20px; color: var(--a-ink-3); box-sizing: border-box; }
.d:focus-visible { outline: none; }
.d:focus-visible .sw, .d:focus-visible .more { outline: 3px solid var(--a-accent); outline-offset: 3px; }
.hand p { margin: 8px 2px; font-size: 13px; color: var(--a-ink-3); }
.sws { display: flex; flex-wrap: wrap; gap: 8px; }
.sws .sw { appearance: none; width: 34px; height: 34px; cursor: pointer; padding: 0; }
</style>
