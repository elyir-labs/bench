// Elyir Bench's site is bench.elyir.com (design/site, U1). The addresses it had before forward there, same path,
// except /install: every `curl -fsSL https://bench.elyir.dev/install | sh` already posted keeps getting the script
// itself (functions/install.js), never a redirect. bench.elyir.dev moved for good (301); elyir.dev and www will be
// the company's, so they forward for now (302) and no browser keeps that. elyir.pages.dev is left alone.
const HOME = 'bench.elyir.com'
const FORWARD = { 'bench.elyir.dev': 301, 'elyir.dev': 302, 'www.elyir.dev': 302 }

export async function onRequest({ request, next }) {
  const url = new URL(request.url)
  const status = FORWARD[url.hostname]
  if (!status || url.pathname === '/install') return next()
  url.protocol = 'https:'
  url.hostname = HOME
  return Response.redirect(url.href, status)
}
