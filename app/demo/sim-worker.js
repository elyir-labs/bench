// The pretend printer for the web demo: Pyodide running simulator/sim.py and the real intent
// engine (printer/elyir_bench_intent.py) through bridge.py. No server anywhere.
//
// Each screen connects with a MessagePort ({t: 'connect'} carrying the port). Over a port:
//   screen -> worker  {t: 'rpc', text}                  a JSON-RPC request, as sent on Moonraker's websocket
//                     {t: 'ctl', id, op, arg}           scenarios | state | run <name> | insert <slot>
//   worker -> screen  {t: 'ws', text}                   a reply or a broadcast, as Moonraker would send it
//                     {t: 'ctl', id, result, error}
//                     {t: 'status', phase, detail}      loading | ready | error

import { loadPyodide } from './pyodide/pyodide.mjs'

// npm run build:demo sets this to true with DEMO_STDLIB=module, for hosts that don't serve .zip files
const STDLIB_MODULE = false

const ports = new Set()
let status = { t: 'status', phase: 'loading', detail: 'Starting Python' }
let bridge = null
const queue = []   // messages that arrived before the printer was up

function setStatus(phase, detail) {
  status = { t: 'status', phase, detail }
  for (const p of ports) p.postMessage(status)
}

function sendAll(text) {
  for (const p of ports) p.postMessage({ t: 'ws', text })
}

async function handle(port, m) {
  if (!bridge) { queue.push([port, m]); return }
  if (m.t === 'rpc') {
    const reply = await bridge.rpc(m.text)
    if (reply != null) port.postMessage({ t: 'ws', text: reply })
  } else if (m.t === 'ctl') {
    try {
      let result
      if (m.op === 'scenarios') result = bridge.scenarios()
      else if (m.op === 'state') result = bridge.state()
      else if (m.op === 'run') result = await bridge.run(String(m.arg))
      else if (m.op === 'insert') result = bridge.insert(Number(m.arg))
      else throw new Error(`unknown op ${m.op}`)
      port.postMessage({ t: 'ctl', id: m.id, result: JSON.parse(result) })
    } catch (e) {
      port.postMessage({ t: 'ctl', id: m.id, error: String(e?.message ?? e) })
    }
  }
}

function connect(port) {
  ports.add(port)
  port.onmessage = (ev) => handle(port, ev.data)
  port.postMessage(status)
}

self.onmessage = (ev) => {
  if (ev.data?.t === 'connect' && ev.ports[0]) connect(ev.ports[0])
}


async function boot() {
  const base = new URL('./', import.meta.url).href
  const params = new URL(import.meta.url).searchParams
  if (STDLIB_MODULE) {
    // Python's standard library as a JS module (base64 of python_stdlib.zip): claude.ai artifacts
    // don't serve .zip files. A blob: URL is refused where the page may connect only to itself, so
    // Pyodide's request for the zip is answered here from memory instead.
    const { default: stdlib } = await import('./pyodide/python_stdlib.js')
    const zip = Uint8Array.from(atob(stdlib), (c) => c.charCodeAt(0))
    const realFetch = self.fetch.bind(self)
    self.fetch = (input, init) => String(input?.url ?? input).endsWith('/python_stdlib.zip')
      ? Promise.resolve(new Response(zip, { headers: { 'Content-Type': 'application/zip' } }))
      : realFetch(input, init)
  }
  const errors = []   // Python's last words, for the message on screen if it doesn't start
  let pyodide
  try {
    pyodide = await loadPyodide({ stderr: (line) => errors.push(line) })
  } catch (e) {
    throw new Error(errors.at(-1) || String(e?.message ?? e))
  }
  setStatus('loading', 'Loading the printer')
  pyodide.FS.mkdirTree('/sim/simulator')
  pyodide.FS.mkdirTree('/sim/printer')
  // which Python files make the printer: written by the build (vite.demo.config.ts), so none is ever left out
  const PY = await fetch(new URL('py/files.json', base)).then((r) => {
    if (!r.ok) throw new Error(`py/files.json: ${r.status}`)
    return r.json()
  })
  const files = await Promise.all(PY.map(([src]) => fetch(new URL(`py/${src}`, base)).then((r) => {
    if (!r.ok) throw new Error(`${src}: ${r.status}`)
    return r.text()
  })))
  PY.forEach(([, dest], i) => pyodide.FS.writeFile(dest, files[i]))
  pyodide.runPython('import sys; sys.path.insert(0, "/sim/simulator")')
  const b = pyodide.pyimport('bridge')
  await b.start(base, (text) => sendAll(text), params.get('scenario') || 'day', Number(params.get('speed') || 4))
  bridge = b
  setStatus('ready', '')
  for (const [port, m] of queue.splice(0)) handle(port, m)
}

boot().catch((e) => {
  console.error(e)
  setStatus('error', String(e?.message ?? e))
})
