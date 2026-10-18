// Where this app's own server paths are. On a printer: the root. Opened through a Bench Box from away, the box serves
// a printer's screens under /screens/<id>/ and says so in the page (bench/away.py), so its door, slicer, websocket, camera
// and routes all live there (docs/bench.md, "From away").
export const BASE: string = (window as { __ELYIR_BENCH_BASE__?: string }).__ELYIR_BENCH_BASE__ ?? ''
