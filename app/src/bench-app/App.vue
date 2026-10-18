<template>
  <div class="bench-app">
    <main class="page">
      <!-- away and not let in (no pairing, or a guest whose time ended): only the way in -->
      <PairPage v-if="landing" landing />
      <router-view v-else-if="here.checked" />
      <!-- design/loading/, A: the page's shape while the box says who this is -->
      <section v-else class="first"><BenchShape /></section>
    </main>
    <!-- one tab bar on every page, an opened printer too; not on the first run, nor on the way in -->
    <BenchTabs v-if="here.checked && !landing && !BARE.includes(route.path)" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BenchTabs from './pages/BenchTabs.vue'
import PairPage from './pages/PairPage.vue'
import BenchShape from './pages/BenchShape.vue'
import { here } from './here'

const BARE = ['/setup', '/join', '/pair']
const route = useRoute()
const landing = computed(() => here.checked && here.away && !here.paired && route.path !== '/join' && route.path !== '/pair')
</script>

<style>
html, body { margin: 0; background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font); -webkit-font-smoothing: antialiased; }
#app { height: 100dvh; }
.bench-app { height: 100%; display: flex; flex-direction: column; }
.bench-app > .page { flex: 1; min-height: 0; overflow: auto; }
.bench-app .first { box-sizing: border-box; padding: 76px 40px 28px; }
@media (max-width: 599px) { .bench-app .first { padding: 64px 16px 20px; } }
/* The box's buttons are given their height (a tile's Print a model, a sheet's answers): the label in the middle, and
   none of the shared button's top and bottom padding, which grows with the screen and pushed it down and the button
   taller (7 October, on a Mac). Every button here keeps the shared 48px minimum. Sheets render outside
   .bench-app, so this is for the whole page; this stylesheet is only the box's. */
:root .a-btn { display: inline-flex; align-items: center; justify-content: center; padding-top: 0; padding-bottom: 0; }
</style>
