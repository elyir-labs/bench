import { defineConfig, mergeConfig, type Plugin } from 'vite'
import { cpSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import base from './vite.config'

// The web demo: the app plus a pretend printer that runs in the browser (demo/sim-worker.js runs
// simulator/sim.py and the real intent engine in Pyodide). Static files only, so any static host
// will do: `npm run build:demo`, then serve dist-demo/.
//
//   dist-demo/index.html      the front page (demo/front.html, design/site B): what it is, install, try, plans
//   dist-demo/try.html        the showcase at /try: the 7" panel and a phone side by side, one printer
//   dist-demo/write.html      the form a printer's code opens at /write (design/report/, B)
//   dist-demo/testers.html    asking to test, and the steps once invited, at /testers (design/testers/, B)
//   dist-demo/units.html      for filament unit owners, at /units; slicing.html at /slicing; box.html (the Bench Box) at /box
//                             (design/site-features/, B)
//   dist-demo/app/            the app, built with VITE_DEMO=1 (src/demo/socket.ts)
//   dist-demo/sim-worker.js   the printer; pyodide/ and py/ beside it
//   dist-demo/install         install/install.sh, for `curl -fsSL https://bench.elyir.com/install | sh`

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, 'dist-demo')
const ROOT = path.resolve(__dirname, '..')
// DEMO_STDLIB=module: for hosts that don't serve .zip files (claude.ai artifacts); see sim-worker.js
const STDLIB_MODULE = process.env.DEMO_STDLIB === 'module'

function demoFiles(): Plugin {
  const copy = (from: string, to: string) => {
    mkdirSync(path.dirname(path.join(OUT, to)), { recursive: true })
    cpSync(path.resolve(ROOT, from), path.join(OUT, to), { recursive: true })
  }
  return {
    name: 'elyir-bench-demo-files',
    apply: 'build',
    closeBundle() {
      // a printer's own files from public/: the demo has no printer to point at and no push to receive
      for (const f of ['config.json', 'elyir-bench.yaml', 'sw.js', 'vite.svg']) rmSync(path.join(OUT, 'app', f), { force: true })
      // the pages are written as artifact pages (no skeleton of their own); a plain static host needs one
      const skeleton = (f: string) => '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
        + '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + readFileSync(path.resolve(ROOT, `app/demo/${f}`), 'utf8')
      writeFileSync(path.join(OUT, 'index.html'), skeleton('front.html'))
      writeFileSync(path.join(OUT, 'try.html'), skeleton('showcase.html'))
      writeFileSync(path.join(OUT, 'write.html'), skeleton('write.html'))
      for (const f of ['testers.html', 'units.html', 'slicing.html', 'box.html']) writeFileSync(path.join(OUT, f), skeleton(f))
      for (const f of ['advanced.html', 'camera.webp', 'camera.jpg', '_headers', 'shots']) copy(`app/demo/${f}`, f)
      const worker = readFileSync(path.resolve(ROOT, 'app/demo/sim-worker.js'), 'utf8')
      writeFileSync(path.join(OUT, 'sim-worker.js'), STDLIB_MODULE ? worker.replace('const STDLIB_MODULE = false', 'const STDLIB_MODULE = true') : worker)
      for (const f of ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'pyodide-lock.json']) {
        copy(`app/node_modules/pyodide/${f}`, `pyodide/${f}`)
      }
      const zip = path.resolve(ROOT, 'app/node_modules/pyodide/python_stdlib.zip')
      rmSync(path.join(OUT, 'pyodide/python_stdlib.zip'), { force: true })
      rmSync(path.join(OUT, 'pyodide/python_stdlib.js'), { force: true })
      if (STDLIB_MODULE) {   // the standard library as a module, not a .zip (sim-worker.js says why)
        writeFileSync(path.join(OUT, 'pyodide/python_stdlib.js'), `export default '${readFileSync(zip).toString('base64')}'\n`)
      } else {
        copy('app/node_modules/pyodide/python_stdlib.zip', 'pyodide/python_stdlib.zip')
      }
      // Every module the simulator is made of, and the list the worker loads: a module added to simulator/ comes along
      // by itself (setup_card.py and slicer_profile.py were left out once, and the demo didn't start, 5 October 2026)
      const py: [string, string][] = []
      for (const f of readdirSync(path.join(ROOT, 'simulator')).filter((n) => n.endsWith('.py')).sort()) {
        copy(`simulator/${f}`, `py/simulator/${f}`)
        py.push([`simulator/${f}`, `/sim/simulator/${f}`])
      }
      for (const f of ['elyir_bench_intent.py', 'filament_units.py', 'unit_check.py', 'unit_setup.py', 'elyir_bench_care.py']) {
        copy(`printer/${f}`, `py/printer/${f}`)
        py.push([`printer/${f}`, `/sim/printer/${f}`])
      }
      // the unit setup's catalog and board scan are the installer's (one table); the demo calls only those
      copy('installer/elyir_bench.py', 'py/installer/elyir_bench.py')
      py.push(['installer/elyir_bench.py', '/sim/installer/elyir_bench.py'])
      copy('app/demo/bridge.py', 'py/bridge.py')
      py.push(['bridge.py', '/sim/simulator/bridge.py'])
      writeFileSync(path.join(OUT, 'py/files.json'), JSON.stringify(py) + '\n')
      // the bootstrap a printer is installed with; _headers serves it as text
      copy('install/install.sh', 'install')
      // and the page a browser gets at the same address (functions/install.js), its table of boards from the
      // list the command checks with (install/boards.json, written by `elyir-bench boards`)
      const boards: Record<string, string>[] = JSON.parse(readFileSync(path.resolve(ROOT, 'install/boards.json'), 'utf8'))
      const esc = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      const box = (t: string) => t.replace('Bench Box', '<a href="box">Bench Box</a>')
      const cell = (k: string, v: string) => v ? `<span role="cell"><span class="k">${k}: </span>${box(esc(v))}</span>` : '<span role="cell" class="blank"></span>'
      const rows = boards.map((r) => `      <div class="row" role="row"><span role="cell"><b>${esc(r.board)}</b>${r.system ? `<small>${esc(r.system)}</small>` : ''}</span>`
        + cell('The screen', r.screen) + cell('Slicing on the printer', r.slicing)
        + `<span role="cell" class="get ${r.verdict}">${esc(r.get)}${r.note ? `<small>${esc(r.note)}</small>` : ''}</span></div>`).join('\n')
      const install = readFileSync(path.resolve(ROOT, 'app/demo/install.html'), 'utf8')
      if (!install.includes('<!-- boards:')) throw new Error('demo/install.html lost its <!-- boards --> line')
      mkdirSync(path.join(OUT, 'pages'), { recursive: true })
      writeFileSync(path.join(OUT, 'pages/install.html'), '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
        + '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + install.replace(/^<!-- boards:.*-->$/m, rows))
      for (const f of readdirSync(path.join(ROOT, 'simulator/thumbs'))) copy(`simulator/thumbs/${f}`, `thumbs/${f}`)
    },
  }
}

export default mergeConfig(base, defineConfig({
  base: './',
  define: { 'import.meta.env.VITE_DEMO': JSON.stringify('1') },
  build: { outDir: 'dist-demo/app', emptyOutDir: true },
  plugins: [demoFiles()],
}))
