// The Printers app (the shell) at https://printers.elyir.app: every printer this phone is paired
// with, one notification subscription for all of them, and each printer's own screens in a frame.
// A separate build from the printer app: `npm run dev:shell` (localhost:5173, which the door
// allows) and `npm run build:shell` -> dist-shell/, published by scripts/publish-shell.sh.
//
// The relay serves it under a strict CSP (no inline script, no eval, nothing third-party), so this
// build keeps everything in hashed files and copies the fonts and icons it shares with the printer app.

import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { readFileSync, readdirSync } from 'fs'
import { fileURLToPath } from 'url'
import { noEval } from './src/look/occt-patch.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SHARED = ['fonts', 'icons']   // from public/, served at the same paths as on the printer

function sharedFiles(): Plugin {
  const files = SHARED.flatMap((dir) => readdirSync(path.resolve(__dirname, 'public', dir)).map((f) => `${dir}/${f}`))
  return {
    name: 'elyir-bench-shell-shared',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const p = (req.url ?? '').split('?')[0].replace(/^\//, '')
        if (!files.includes(p)) return next()
        res.setHeader('Content-Type', p.endsWith('.woff2') ? 'font/woff2' : p.endsWith('.png') ? 'image/png' : 'application/octet-stream')
        res.end(readFileSync(path.resolve(__dirname, 'public', p)))
      })
    },
    generateBundle() {
      for (const f of files) this.emitFile({ type: 'asset', fileName: f, source: readFileSync(path.resolve(__dirname, 'public', f)) })
    },
  }
}

// The STEP reader without `new Function`, so it runs under the relay's CSP (src/look/occt-patch.ts).
// transform covers the build; the esbuild plugin covers the dev server's pre-bundled copy.
const OCCT = /occt-import-js[\\/]dist[\\/]occt-import-js\.js$/
function occtNoEval(): Plugin {
  return { name: 'elyir-bench-occt-no-eval', enforce: 'pre', transform: (code, id) => (OCCT.test(id) ? noEval(code) : null) }
}
const occtNoEvalDev = {
  name: 'elyir-bench-occt-no-eval',
  setup(build: { onLoad: (o: { filter: RegExp }, cb: (a: { path: string }) => { contents: string; loader: 'js' }) => void }) {
    build.onLoad({ filter: OCCT }, (a) => ({ contents: noEval(readFileSync(a.path, 'utf8')), loader: 'js' }))
  },
}

export default defineConfig({
  root: path.resolve(__dirname, 'shell'),
  publicDir: path.resolve(__dirname, 'shell/public'),
  plugins: [vue(), sharedFiles(), occtNoEval()],
  optimizeDeps: { esbuildOptions: { plugins: [occtNoEvalDev] } },
  worker: { format: 'es', plugins: () => [occtNoEval()] },
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: {
    outDir: path.resolve(__dirname, 'dist-shell'),
    emptyOutDir: true,
    modulePreload: { polyfill: false },   // nothing inline; every browser it targets has modulepreload
  },
  server: { port: 5173, strictPort: true },
})
