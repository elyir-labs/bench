import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import path from 'path'
import { fileURLToPath } from 'url'
import { readFileSync } from 'fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// The boot eye's first frame, inlined into index.html so it is on the panel before any script or
// font has loaded: the same picture Plymouth left on screen, which BootScreen.vue then takes over.
// src/boot/mark.json is the geometry for all three. The script decides whether to show it; the
// rule matches isPanel in src/theme.ts, including ?embed=1 (inside the Printers app) never being the
// panel (?boot=1 forces it, for screenshots).
function bootFrame(): Plugin {
  const m = JSON.parse(readFileSync(path.resolve(__dirname, 'src/boot/mark.json'), 'utf8'))
  const rgba = (c: number[]) => `rgba(${c.join(',')})`
  const [w, h] = m.design
  const [cx, cy] = m.center
  const frame = `<div id="boot-frame" hidden style="position:fixed;inset:0;z-index:9999;background:${m.colors.bg}">
<svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" style="display:block"><g transform="translate(${cx} ${cy})">
<circle r="${m.ring.r}" fill="none" stroke="${rgba(m.colors.track)}" stroke-width="${m.ring.stroke}"/>
<circle r="${m.ring.r}" fill="none" stroke="${m.colors.accent}" stroke-width="${m.ring.stroke}" stroke-linecap="round" pathLength="1" stroke-dasharray="${m.handoff} 1" transform="rotate(-90)"/>
<circle r="${m.pupil.r}" fill="${m.colors.accent}"/>
</g></svg></div>
<script>(function () {
  try {
    var q = new URLSearchParams(location.search), s = q.get('screen')
    // inside the Printers app (?embed=1) this is never the panel, even when served from localhost in a test
    var panel = q.get('embed') === '1' ? false : s ? s === 'panel' : ['localhost', '127.0.0.1', '::1', '[::1]'].indexOf(location.hostname) >= 0
    if (q.get('boot') === '1' || (panel && !sessionStorage.getItem('elyir-bench.booted'))) {
      document.documentElement.dataset.boot = '1'
      document.documentElement.style.background = '${m.colors.bg}'
      document.getElementById('boot-frame').hidden = false
    }
  } catch (e) {}
})()</script>`
  return {
    name: 'elyir-bench-boot-frame',
    transformIndexHtml: (html) => html.replace('<!-- elyir-bench:boot-frame -->', frame),
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    bootFrame(),
    vue({
      template: { transformAssetUrls }
    }),
    quasar({
      sassVariables: path.resolve(__dirname, './src/styles/quasar-variables.scss')
    })
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 3000,
    // The door (pairing, Web Push) is same-origin on a printer; in dev, tools/push-dev.py stands in
    proxy: {
      '/door': process.env.DOOR_URL || 'http://127.0.0.1:7180',
      // The slicing service (slicer/slice_service.py); on a printer, nginx sends /slice to it
      '/slice': process.env.SLICER_URL || 'http://127.0.0.1:8095',
      // A new printer's first Wi-Fi (setup/wifi_setup.py --fake on a laptop)
      '/wifi': process.env.WIFI_URL || 'http://127.0.0.1:8097',
    }
  }
})
