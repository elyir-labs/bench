# The filament-unit service

Bench's own driver for filament units (design/ace-driver/, A). It owns each unit's port, keeps what the unit can't
remember, and answers the printer code over a Unix socket. The printer code reads its state through
`printer/filament_units.py`, the same model it uses for KlipperACE and Happy Hare.

- `service.py`: the service. `python3 service.py --socket ~/printer_data/comms/elyir-units.sock --state ~/printer_data/config/elyir-units.json`
- `ace_link.py`: one ACE Pro over USB, for asyncio.
- `toolchange.py`: tool changes, the quiet pause. `moonraker.py`: the service's line to Moonraker, as an agent.
- `klipper/elyir_units.cfg`: what Klipper needs (the sensor's push, ELYIR_TOOL, T0..T7); the installer fills in the pin.
- `pretend_ace.py`: a pretend ACE Pro on a pseudo-terminal, for tests and the simulator.
- `pretend_printer.py`: a pretend printer for tool changes: a little Moonraker, the extruder, its sensor and the filament path.
- `ace-protocol.md`: the ACE Pro's wire protocol, written from the captures in `captures/` (tools in `tools/`).
  Clean room: nothing here comes from another ACE project's code, and every protocol fact cites a capture.

The simulator runs it on two pretend units: `python3 simulator/sim.py --units service`.

Tests: `cd units && python3 -m pytest -q tests` (needs pytest-asyncio).

Settings live in the state file under "settings" (toolchange.py's DEFAULTS): the printer's own before and after
macros, the distances (sensor to nozzle, back to park) and speeds.

On a printer it comes with every release; the installer's "filament units" step (`installer/elyir_bench.py`,
`FilamentUnits`) switches it on. `filament_units: auto` (the default) drives an ACE Pro that KlipperACE doesn't, once
Klipper knows the extruder's filament sensor; a printer on KlipperACE is asked once at an apply from a terminal.
`elyir` switches it on in KlipperACE's place (its includes commented out with a mark, its slot in the head and
untagged spools carried over), `klipperace` puts everything back, and `elyir-bench remove` takes it off.
`units_sensor_pin` names the sensor's pin when Klipper's config doesn't. Not tried on hardware yet: two units on
one printer. See `docs/filament-units.md`.
