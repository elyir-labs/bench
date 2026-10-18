// bench.elyir.com/install, one address for two readers (Cloudflare Pages Functions; wrangler picks up this
// folder when `pages deploy` runs in app/). A browser asks for HTML and gets the install page
// (demo/install.html, built to pages/install.html); curl asks for anything and gets install/install.sh,
// which `curl -fsSL https://bench.elyir.com/install | sh` pipes to sh. The two must never swap: a script that
// came back as HTML would be run by sh, so only an explicit text/html gets the page.
// _headers doesn't reach a Function's responses, so the type and caching are set here too.
export async function onRequest({ request, env, next }) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return next()
  const page = (request.headers.get('Accept') || '').includes('text/html')
  const res = page ? await env.ASSETS.fetch(new Request(new URL('/pages/install', request.url), { method: request.method }))
    : await next()
  const out = new Response(res.body, res)
  if (res.ok) {
    out.headers.set('Content-Type', page ? 'text/html; charset=utf-8' : 'text/plain; charset=utf-8')
    out.headers.set('Cache-Control', 'no-cache')
  }
  out.headers.append('Vary', 'Accept')
  return out
}
