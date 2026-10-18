# Contributing to Elyir Bench

Thank you for looking. Elyir Bench is early and opinionated about how a printer should feel, so the
way work happens matters as much as the code.

## Draw before you build

Every screen a person sees is drawn before it is built:

1. **Today.** Capture how the screen looks and behaves now (the simulator makes this easy:
   `sim.py --scenario …`), and write down what is wrong with it in one or two sentences.
2. **Directions.** Draw two or three different answers (A, B, C), not variations of one. Panel
   (800x480), phone and laptop sizes where they differ. Say what each one gives up.
3. **Decide.** One direction is chosen, and why is written next to it. Open questions are listed
   rather than guessed.
4. **Build** the chosen direction, then put screenshots of what was built beside the drawing, so
   the record shows what was intended and what shipped.

Open an issue with the drawings (images or HTML, whatever you draw in) before sending a pull
request that changes what a person sees. Changes that a person never sees (fixes, tests,
hardware support, the installer) can go straight to a pull request.

## The rules the code keeps

- Every sentence a person reads is written in the intent layer (`printer/`), nowhere else. The
  app renders; it does not decide.
- One primary action per state. A second is allowed. A third is a bug.
- Subsystem names (macros, tool numbers, heater names) never reach the UI.
- Anything that throws away printed work is held, not tapped.
- When something went wrong on a real printer, the fix comes with a test that pins it.
- A new library must pass `scripts/license-check.py`, and nothing is copied from Klipper,
  Moonraker, OrcaSlicer or Mainsail. See [docs/licensing.md](docs/licensing.md).

## Tests

```bash
for d in printer door installer slicer; do (cd $d && python -m pytest -q tests); done
cd app && npm ci && npm test && npm run build
```

Python needs `aiohttp`, `pytest`, `pytest-asyncio` and `pywebpush`. The slicer has one test that
runs the real OrcaSlicer when it is installed; it is skipped otherwise.

## Contributor license agreement

Contributions are accepted under a contributor license agreement (CLA). You keep the copyright
in your contribution; the CLA gives the project the right to distribute it under the GPL and
also under other licenses, including commercial ones, so that Elyir Bench can be offered to companies
that cannot use GPL software. A pull request can be merged only once its author has agreed to
the CLA.

How you agree: the first time you open a pull request, a bot (CLA Assistant) asks you to agree in
the pull request itself, once. If you contribute as part of your job, your employer signs a company
version instead, once for everyone it names.

The agreements: [CLA.md](CLA.md) for individuals, [CLA-company.md](CLA-company.md) for companies.

> Both are drafts, being reviewed by a lawyer, and pull requests can't be signed yet. Until the
> draft notices are gone, please open an issue before starting on a large change.
