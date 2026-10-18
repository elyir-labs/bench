# Hand test on Workshop: can the unit pull a slot back while paused, with another slot in the head?

Swapping the spool in a **full** slot at a colour-change pause (design/colour-change/, "Or put a different spool
in slot N") is built and switched off: `SLOT_SWAP_WHILE_PAUSED = False` in `printer/elyir_bench_intent.py`. It
needs the unit to pull one slot's filament back to its spool while a different slot's filament is loaded
through the hub into the head. Nobody has watched that on Workshop. Until this passes, the pause doesn't offer it.

The same session answers a second question the build raised: Workshop's `M600` (in the printer's own `filament.cfg`)
is `PAUSE` + `UNLOAD_FILAMENT`, so at the pause the extruder is empty while KlipperACE still thinks slot 1 is
loaded. Does `ACE_CHANGE_TOOL` still switch cleanly from there?

Everything below is typed into Mainsail's console. Slots in commands count from 0 (slot 1 on the screen is
`INDEX=0`). Have the Emergency Stop button in view.

## Set up

1. Red (or anything) in slot 1, a second spool in slot 2, both reading `ready`:
   `ACE_GET_STATUS` — note `selected_gate` and each slot's status.
2. Load slot 1 into the head: `ACE_CHANGE_TOOL TOOL=0`. Wait for `Load complete`.
3. Start a short print (a calibration cube is enough) and let it reach layer 2. Press **Pause** in Mainsail
   (or `PAUSE`). The head parks; the nozzle stays hot. This is the state the pause is in.

## A: pull slot 2 back while slot 1 is in the head

4. A short pull first: `ACE_RETRACT INDEX=1 LENGTH=50`
   - Watch: slot 2's spool turns backwards; the filament in the tube to the **head** (slot 1) does not move,
     and nothing clicks or grinds at the hub.
   - Console: no `ACE Error` line.
5. Then in the steps the engine uses: `ACE_RETRACT INDEX=1 LENGTH=300`, then `ACE_GET_STATUS`. Repeat until
   slot 2 reads `empty`. Write down the total length pulled (the engine gives up at 2400 mm).
6. Push slot 2's spool end back in until the unit grabs it; `ACE_GET_STATUS` should show it `ready` again
   without any command.
7. Check slot 1 is untouched: the extruder sensor still reads filament (`QUERY_FILAMENT_SENSOR SENSOR=...`
   or Mainsail's sensor panel), and `selected_gate` is still 0.
8. Carry on with `RESUME` and watch the next layer go down in slot 1's colour.

**Pass:** slot 2 read empty within 2400 mm, slot 1 never moved, no errors, and the print resumed cleanly.
Then set `SLOT_SWAP_WHILE_PAUSED = True` (and update `test_swapping_a_full_slot_at_the_pause_is_off_by_default`).

## B: switch after Workshop's M600 has unloaded the extruder

9. While still printing, send `M600`. It pauses and runs `UNLOAD_FILAMENT`; the extruder sensor should read
   empty while `ACE_GET_STATUS` still says `selected_gate: 0`.
10. `ACE_CHANGE_TOOL TOOL=1`. Watch the console for `Unloading tool 0`, `Feeding from gate`, `Feeding to nozzle`,
    the purge macro and `Load complete`. Does the unload step fail or time out because the extruder was
    already empty?
11. If it loaded: `RESUME`, and check the next layer is slot 2's colour.

**Pass:** the tool change finished by itself. If it didn't, the planned (automatic) switch will stop at
"Switching to ... didn't finish" on Workshop: change Workshop's `M600` to just `PAUSE` (the unit does the unloading),
which is the right macro on a printer with a unit anyway, and test again.

## Backing out safely, at any step

- A pull that goes wrong (noise at the hub, slot 1's tube moving): stop typing; push it back with
  `ACE_FEED INDEX=1 LENGTH=<the length pulled so far>`. `ACE_CANCEL_FEED` stops a feed that's still running.
- Don't `RESUME` unless the extruder sensor reads filament. If in doubt, **Cancel** the print in Mainsail:
  `CANCEL_PRINT` parks the head and turns the heaters off.
- Anything mechanical that won't stop: Mainsail's **Emergency Stop** (M112), then `FIRMWARE_RESTART`.
- Afterwards, `ACE_GET_STATUS` and `ACE_SET_GATE GATE=<the slot really in the head>` (or `GATE=-1` if none) so
  the printer's memory matches the head.
