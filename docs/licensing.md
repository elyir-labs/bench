# Licenses: keeping the code free to license

Elyir Bench is open source under the GNU Affero General Public License, version 3 only (AGPL-3.0-only;
decided 18 October 2026): anyone who runs a modified copy as a service for other people has to give
them the changes. `printer/printer_intent.py` and `printer/orca_profile.py` run inside Moonraker and
stay GPL-3.0-only (AGPL section 13 lets the two be combined). Elyir LLC also offers it under
commercial licenses (the CLA explains why). Both only work while every line here is Elyir LLC's own, contributed under the CLA, or under a
license that lets anyone use it any way they like. These are the rules that keep it that way.

## Libraries

- `scripts/license-check.py` checks every library the app and the door ship against
  `scripts/licenses.json`. CI runs it (the Licenses workflow) whenever the app's lockfile or the door's
  requirements change.
- **Allowed:** permissive licenses (MIT, BSD, Apache-2.0, ISC and the like) and MPL-2.0, whose
  copyleft stops at the library's own files.
- **Not allowed:** GPL, AGPL, LGPL, SSPL, BUSL, "non-commercial" licenses, and anything with no
  license found.
- **Exceptions:** only for a library that stays a separate, replaceable part, written into
  `licenses.json` with the reason. Today there is one: occt-import-js (LGPL-2.1), which loads in its
  own worker with its own `.wasm` file.
- Run it yourself: `python3 scripts/license-check.py` (installs the Python requirements into a
  throwaway venv, about 10 s), or `--python <interpreter>` to use an environment that already has them.

## Other people's programs, at arm's length

The installer downloads these onto the printer; none of their code is kept here.

| Program | License | How Elyir Bench touches it | Rule |
| --- | --- | --- | --- |
| Klipper | GPL-3.0 | Config files, G-code macros, commands | Never add Klipper extras (Python loaded into Klipper) to this repository: they would ship under the GPL |
| Moonraker | GPL-3.0 | `printer/printer_intent.py` is a Moonraker component and runs inside it | That file ships under the GPL with Moonraker, so keep it a thin adapter. The logic lives in `elyir_bench_intent.py`, which imports nothing from Moonraker |
| OrcaSlicer | AGPL-3.0 | Runs as its own program (`slicer/elyir_bench_slice.py` calls its command line) | Never import, link or copy its code or its profile files. Presets name Orca's own presets as parents (`inherits`) and hold only what differs. A patched Orca must have its patches published |
| KlipperACE (ACE units) | GPL-3.0 | G-code commands and the status it publishes through Moonraker | It was started by other developers and can never be relicensed, so never copy its code here |
| Mainsail | GPL-3.0 | The Advanced door opens it as its own site | Never copy Mainsail components into `app/` |

## Code from elsewhere

- Copy code from another project, an answer or a gist only when its license is on the allowed list,
  and keep its notice (add it to NOTICE).
- Outside contributions come in only through pull requests, after the CLA check.
