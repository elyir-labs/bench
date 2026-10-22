// Pins the site's three features, picked on 22 October 2026 (design/site-features/, B): the hero sentence names them,
// three teasers sit under the hero, each a door to its own page (/units, /slicing, /box), and every claim carries one
// of three labels from the board's claims table.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (f: string) => readFileSync(new URL(`../demo/${f}`, import.meta.url), 'utf8')
const front = read('front.html')
const pages = { units: read('units.html'), slicing: read('slicing.html'), box: read('box.html') }
const build = readFileSync(new URL('../vite.demo.config.ts', import.meta.url), 'utf8')
const LABELS = ['Works today', 'New · help us test it', 'New', 'Coming', 'ACE Pro: works today']

test('the hero sentence names all three, and three teasers under it open their pages', () => {
  assert.match(front, /It slices on the printer, swaps spools on your ACE Pro, ERCF or Box Turtle, and asks when it needs you\./)
  const hero = front.slice(front.indexOf('<div class="hero">'), front.indexOf('<section'))
  const doors = [...hero.matchAll(/<a class="teaser" href="(\w+)">/g)].map((m) => m[1])
  assert.deepEqual(doors, ['units', 'slicing', 'box'])
  assert.ok(front.indexOf('<section id="try">') < front.indexOf('<section class="screens">'), 'the demo stays one scroll down')
})

test('every page has Units, Slicing and Bench Box in its nav, and the build writes the pages', () => {
  for (const html of [front, ...Object.values(pages), read('install.html'), read('testers.html')]) {
    const nav = html.slice(html.indexOf('<nav>'), html.indexOf('</nav>'))
    for (const [href, name] of [['units', 'Units'], ['slicing', 'Slicing'], ['box', 'Bench Box']]) assert.match(nav, new RegExp(`href="${href}"( aria-current="page")?>${name}</a>`), name)
  }
  for (const f of Object.keys(pages)) assert.ok(build.includes(`'${f}.html'`), `${f}.html is not built`)
})

test('every label is one of the three, and Now, Soon and Later are gone', () => {
  for (const html of [front, ...Object.values(pages)]) {
    for (const [, kind, text] of html.matchAll(/<span class="pill (\w+)">([^<]+)<\/span>/g)) {
      assert.ok(LABELS.includes(text), `"${text}" is not a label`)
      assert.equal(kind, text.startsWith('New') ? 'new' : text === 'Coming' ? 'coming' : 'ok', text)
    }
    assert.doesNotMatch(html, /class="pill (now|soon|later)"/)
  }
})

test('a new Pi is offered as /install offers it, and the Bench Box can be had now', () => {
  assert.ok(read('install.html').includes('elyir-bench-pi5.img.xz'))
  const card = front.slice(front.indexOf('A new Pi, or a fresh start') - 80, front.indexOf('A printer that can\'t run it'))
  assert.ok(card.includes('New · help us test it') && card.includes('href="install"'))
  const get = pages.box.slice(pages.box.indexOf('id="get"'), pages.box.indexOf('A box you can buy'))
  assert.ok(get.includes('New · help us test it') && get.includes('href="install"') && get.includes('href="testers"'))
  assert.match(pages.box, /A box you can buy[\s\S]*?Coming/)
  assert.match(pages.units, /Try an ERCF live <span class="pill coming">Coming<\/span>/)
})

test('the Bench Box is a capture of the Bench app, not a drawing, and nothing public says a price or date', () => {
  assert.match(pages.box, /src="shots\/box-dark\.jpg"/)
  assert.match(pages.box, /src="shots\/box-light\.jpg"/)
  for (const html of Object.values(pages)) assert.doesNotMatch(html, /\$\d|€\d|£\d|\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/)
})
