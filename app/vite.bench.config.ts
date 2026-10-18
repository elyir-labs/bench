// The Bench Box's screen (design/bench-box/, D): every printer in the house, on the box's own display and on
// phones at home. A separate build from the printer app, like the Printers app: `npm run dev:bench`
// (localhost:5174) and `npm run build:bench` -> dist-bench/. Each printer's own screens open in a frame in
// bench chrome (?embed=1&chrome=bench), so the box draws one top row and the sections.
//
// The list of printers is the box's (GET /bench/printers). In dev, BENCH_PRINTERS names a JSON file of
// [{id, name, moonraker, app}]: the simulators, and the printer app's dev server that draws each one.

import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { readFileSync, readdirSync } from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SHARED = ['fonts', 'icons']   // from public/, served at the same paths as on the printer

function shared(): Plugin {
  const files = SHARED.flatMap((dir) => readdirSync(path.resolve(__dirname, 'public', dir)).map((f) => `${dir}/${f}`))
  return {
    name: 'elyir-bench-bench-shared',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const p = (req.url ?? '').split('?')[0].replace(/^\//, '')
        if (p === 'bench/printers' && process.env.BENCH_PRINTERS && !process.env.BENCH_URL) {
          res.setHeader('Content-Type', 'application/json')
          return res.end(readFileSync(process.env.BENCH_PRINTERS))
        }
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

export default defineConfig({
  root: path.resolve(__dirname, 'bench'),
  // its own dependency cache: beside the printer app's dev server (which draws each printer's screens in
  // the frames), a shared one is re-optimized by each in turn and every load fails with 504 Outdated Optimize Dep
  cacheDir: path.resolve(__dirname, 'node_modules/.vite-bench'),
  plugins: [vue(), shared()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: { outDir: path.resolve(__dirname, 'dist-bench'), emptyOutDir: true },
  // BENCH_URL: the box's own service (bench/bench_service.py) behind /bench, as nginx does on a box
  server: { port: 5174, strictPort: true, proxy: process.env.BENCH_URL ? { '/bench': { target: process.env.BENCH_URL, ws: true } } : undefined },
})
