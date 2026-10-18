# How it prints, from the box's shelf (contract)

design/bench-how/, A, picked on 6 October 2026. A model on the Bench Box's shelf gets the printer's own
choices under Print on: **It's for**, **Supports**, **Brim** and **Changed** (Every setting behind it). What's chosen is
kept with the model on the shelf, so printing it again, queuing it and Whichever is free first all print it the same
way, on any printer. Each printer's own kept settings for that purpose ("Yours", from its Print) still sit underneath.

The box's slicer already takes all of it (`POST /slice`: `purpose`, `supports`, `kept`, `settings`, a `brim` per
part; slicer/slice_service.py). Today `bench/shelf.py` `_slice()` sends only the parts and the material.

## The model's `how`

Every item from `GET /bench/shelf` carries `how`, filled with defaults when the model has none yet:

```json
"how": {
  "purpose": "everyday",          // draft | everyday | display | strong
  "supports": null,               // normal | tree | off; null = the printer's usual
  "brim": null,                   // auto | none | ears | all; null = each part's own (what it last printed with)
  "settings": {}                  // Orca key -> value (strings), laid over the printer's own
}
```

Words and ids are the printer app's (`app/src/slice/plan.ts`: `PURPOSES`, `KIND_WORDS`, `BRIM_WORDS`; the purposes'
labels and summaries come from the slicer's options).

## Box API (bench/shelf.py)

| Call | Does |
|---|---|
| `PUT /bench/shelf/{id}/how` `{purpose?, supports?, brim?, settings?}` | Changes what's given, saves, returns the item. `settings` merges: a key set to `null` is removed. Values are checked (unknown purpose, kind or brim: 400 in words); setting values are strings, keys `[a-z0-9_]+`. |
| `POST /bench/shelf/{id}/slice` `{printer, copies, material, color, slot, how?}` | As today, sliced with the model's `how`. An optional `how` (same shape, partial) is laid over it **for this slice only and not saved**: the purpose sheet uses it to price the other purposes. |
| `GET /bench/slice-options` | The box slicer's `GET /slice/options`, passed through (purposes with labels and summaries, `editable`). |
| `GET /bench/usual/{printer}` | That printer's own, from its Moonraker (`elyir-bench` / `slice_usual`): `{supports, purposes}`, with `supports` falling back to the kind its process preset prints (the slicer's printer entry), else `normal`. |

What `_slice()` sends to the slicer, for printer P:

- `purpose`: `how.purpose`.
- `supports`: `how.supports`, else P's usual (above).
- `kept`: P's `slice_usual.purposes[purpose]` (P's own "Yours"), read from P's Moonraker; looked at again after a
  minute; missing or unreachable = `{}` (never fails a slice).
- `settings`: `how.settings` (the model's own win over P's kept, as on a printer's Print).
- each part's `brim`: `how.brim` when set, else the part's own as today.

The queue (`bench/bench_queue.py`) slices through `_slice()`, so a queued print uses the model's `how` as it stands when
the box sets it up. `send_job` writes the `how` it was sliced with into the item's `last` (`last.how`).

## The model page (app/src/bench-app/pages/ModelPage.vue)

Under Print on: "HOW IT PRINTS · kept with this model", four tiles in two columns (one on a phone):

| Tile | Value | Line |
|---|---|---|
| It's for | the purpose's label | its summary |
| Supports | Normal / Tree / Off | the kind's row words; when `null`: the usual's label, "`<Printer>`'s usual" |
| Brim | All round / Corners only / None / Orca's own | its short line; when `null`: "Each part's own" |
| Changed | "Nothing", or the one setting ("Walls 4"), or "3 settings" | "Every setting" as a link |

Each opens a sheet:

- **It's for**: the four purposes with time and grams for the printer Print on would use now ("Times are for Desk,
  where it would go now."). The chosen one comes from the page's own setup; the other three are sliced with a `how`
  override when the sheet opens and dropped (DELETE) when it closes. No printer can take it: no times, still pickable.
- **Supports**: Normal, Tree, Off with `KIND_WORDS` lines, and "`<Printer>`'s usual" (null) on top.
- **Brim**: Each part's own (null), All round, Corners only, None, with `BRIM_WORDS` lines.
- **Every setting**: the slicer's `editable` list (number with steps, or choice). A set value shows as the model's;
  "Back to the printer's own" removes it. Changes save at once (`PUT …/how`).

The page sets the model up for the picked printer as soon as it opens and whenever `how`, copies, filament or the
printer change (once the taps stop), so the line under the buttons says "About 1 h 12 min · 21 g on Desk". Print on
reuses that setup when nothing changed since (the setup key includes `how`). Footer: "Kept with `<model>`: next time,
and on whichever printer takes it, it prints this way." The line under the buttons is no longer cut off by the tab bar.

## Tests

- `bench/tests/test_shelf.py`: `how` defaults and PUT (merge, null removes, bad values 400); `_slice` sends purpose,
  supports (set, and null falling back to the printer's usual), kept from the printer's Moonraker, settings, brim per
  part; an override isn't saved; `last.how`; the queue slices with `how`.
- `app/tests/bench-shelf.test.ts` (or a new `bench-how.test.ts`): the tiles' words from a `how` (pure helpers in
  `src/bench-app/how.ts`).
