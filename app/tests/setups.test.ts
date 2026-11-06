// Pins /setups, picked on 28 October 2026 (design/setups/, A): the two setups side by side with the table that tells
// them apart, the side view at the top of Z, and a recipe each. Where the splitter sits is the difference: A's hub on the
// toolhead, B's splitters on the frame with one tube to the toolhead.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const read = (f: string) => readFileSync(new URL(`../demo/${f}`, import.meta.url), 'utf8')
const page = read('setups.html')
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

test('the first screen compares the two, and the table says where each sits and how high it goes', () => {
  const table = text(page.slice(page.indexOf('<table>'), page.indexOf('</table>')))
  for (const row of ['Slots', 'Into the printer', 'Where it sits', 'Top of Z', 'You buy', 'You print']) assert.ok(table.includes(row), row)
  assert.match(table, /On the toolhead: in place of the ECAS coupler, two M3 screws/)
  assert.match(table, /On the frame: at the back, top center, with one PTFE tube to the stock ECAS/)
  assert.match(table, /can stop short of the top/)
  assert.match(table, /All the way up/)
})

test('the side view comes before the recipes, and each recipe has its own link', () => {
  const at = (s: string) => page.indexOf(s)
  assert.ok(at('id="top-of-z"') > 0 && at('id="top-of-z"') < at('id="anycubic-hub"') && at('id="anycubic-hub"') < at('id="bambu-splitters"'))
  assert.equal((page.match(/<svg class="zside"/g) ?? []).length, 2)
  for (const id of ['anycubic-hub', 'bambu-splitters']) assert.match(page, new RegExp(`href="#${id}"`))
})

test("B's pictures show the splitters on the frame, and every picture is there", () => {
  const b = page.slice(page.indexOf('id="bambu-splitters"'))
  assert.match(b, /src="shots\/setups-bambu-frame\.webp"/)
  assert.match(page.slice(0, page.indexOf('id="top-of-z"')), /setups-bambu-frame\.webp/)
  for (const [, src] of page.matchAll(/src="(shots\/[^"]+)"/g)) assert.ok(existsSync(new URL(`../demo/${src}`, import.meta.url)), src)
})

test('both setups come in through the printed rear vent', () => {
  assert.match(page, /<th scope="row">Into the printer<\/th><td colspan="2">Both: through our printed rear vent/)
  const at = (s: string) => page.indexOf(s)
  assert.ok(at('id="top-of-z"') < at('id="at-the-back"') && at('id="at-the-back"') < at('id="anycubic-hub"'))
  for (const id of ['anycubic-hub', 'bambu-splitters']) {
    const r = page.slice(at(`id="${id}"`), page.indexOf('</section>', at(`id="${id}"`)))
    assert.match(r, /<li class="add"><b>Through the rear vent<\/b>/, id)
    assert.match(r, /<b>The rear vent<\/b>: printed, one hole per tube <span class="pill coming">Coming<\/span>/, id)
  }
})

test('both recipes name the PTFE (3 mm inside, 4 mm outside) and the back-off (50 mm)', () => {
  for (const id of ['anycubic-hub', 'bambu-splitters']) {
    const r = page.slice(page.indexOf(`id="${id}"`), page.indexOf('</section>', page.indexOf(`id="${id}"`)))
    assert.match(r, /3 mm inside and 4 mm outside/, id)
    assert.match(r, /<b>Back-off:<\/b> 50 mm on this Stealthburner/, id)
  }
})

test('two ACE Pros keep the label /units gives them, and /units opens the page', () => {
  assert.match(page, /Two ACE Pros<\/b> on one printer, slots 1 to 8 <span class="pill new">New · help us test it<\/span>/)
  assert.match(read('units.html'), /href="setups">The two setups<\/a>/)
  assert.match(readFileSync(new URL('../vite.demo.config.ts', import.meta.url), 'utf8'), /'setups\.html'/)
})
