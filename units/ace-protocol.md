# ACE Pro wire protocol (as observed)

Sources: captures in `captures/` from one ACE Pro (firmware V1.3.856) on a Klipper host, decoded with
`tools/decode.py` and `tools/timeline.py`. `idle` is 12 s of polling; `moves` and `probe` were taken
while the host sent each command below (`.markers` files say when); `direct` is our own client
(`tools/experiment.py` in the capture repo, ~/dev/elyir-ace) talking to the unit with Klipper stopped, plus the raw capture of Klipper reconnecting. Anything not seen on the wire is under
"Not yet observed" and must stay there until a capture shows it.

## Device

- USB `28e9:018a`, product string "ACE", a CDC ACM serial device (`/dev/ttyACM*`).
- Units can share a USB serial number, so `/dev/serial/by-id` can show one link for two units.
  Count devices on the bus instead.

## Framing

```
ff aa | len (u16, little-endian) | payload (len bytes, UTF-8 JSON) | crc (u16, little-endian) | fe
```

- The CRC is CRC-16/MCRF4XX (poly 0x1021, init 0xFFFF, reflected in and out, no final XOR) over the
  payload only. It matched 48 of 48 frames, both directions.
- Replies longer than 64 bytes arrive split across USB packets. Reassemble by the length field.

## Requests and replies

JSON-RPC-like. The host picks an integer `id` (a running counter in the capture) and the reply
echoes it.

```json
{"id": 33190, "method": "get_status"}
```

```json
{"id":33190,"result":{"status":"ready","dryer_status":{"status":"stop","target_temp":0,"duration":0,"remain_time":0},
 "temp":31,"enable_rfid":1,"fan_speed":7000,"feed_assist_count":4326,"cont_assist_time":0.0,
 "slots":[{"index":0,"status":"ready","sku":"","type":"","color":[0,0,0],"rfid":1}, ...]},
 "code":0,"msg":"success"}
```

- Request without `params` is accepted. The host's JSON had spaces; the unit's reply is compact.
- Reply envelope: `id`, `result`, `code`, `msg`. Success is `code` 0 with `msg` "success"
  (`drying` answers `msg` "drying"). An unknown method gets `code` 400, `msg` "InvalidCommand",
  `result` `{}` (probe).
- Commands are acknowledged at once (5-10 ms); the work happens afterwards and shows in `get_status`.

- An out-of-range slot (`feed_filament` index 9) gets **`code` 0** with `msg` "FORBIDDEN", so check
  `msg`, not just `code` (direct).
- Unknown params are ignored (`get_status` with `{"bogus":1}` answered normally). A frame with a bad
  CRC gets no reply at all (direct).
- Ids are the host's choice; the unit doesn't mind them restarting at 1 (direct, and KlipperACE's
  reconnect).

## Connecting

The host sends `get_info`, then starts polling `get_status`. Nothing else was sent when KlipperACE
connected (direct, raw capture after Klipper started).

## Methods seen

| method | params | reply `result` | source |
|---|---|---|---|
| `get_info` | none | `{"id":1,"slots":4,"model":"Anycubic Color Engine Pro","firmware":"V1.3.856","boot_firmware":"V1.0.1","structure_version":"0"}` | probe |
| `get_status` | none | see below | idle |
| `feed_filament` | `index`, `length` (mm), `speed` (80 seen) | `{}` | moves |
| `unwind_filament` | `index`, `length` (mm), `speed` (50 seen) | `{}` | moves |
| `start_feed_assist` | `index` | `{}` | moves |
| `stop_feed_assist` | `index` | `{"stop_status":"reset"}` | moves |
| `drying` | `temp` (°C), `fan_speed` (7000 seen), `duration` (minutes) | `{}`, `msg` "drying" | moves |
| `drying_stop` | none | `{}` | moves |
| `stop_feed_filament` | `index` | `{}` | direct |
| `stop_unwind_filament` | `index` | `{}` | direct |

### What `get_status` shows while working (moves)

- Feed 50 mm at 80: `status` busy, `action` "shifting" and the slot "shifting" (about 0.5 s), then
  "feeding", then ready about 2.5 s after the command. `feed_assist_count` reset to 0.
- Unwind 50 mm at 50: busy/"unwinding" straight away (the slot was already selected), `action`
  "ready" after 1.5 s, slot ready after 2.5 s.
- Start feed assist: "shifting" to that slot for about 0.5 s, then ready; `feed_assist_count` 1,
  `cont_assist_time` briefly 0.3.
- Drying 40 °C for 1 minute: `dryer_status` drying, target 40, duration 1, `remain_time` 60 counting
  down once a second, so **`remain_time` is seconds while `duration` is minutes**. After
  `drying_stop` it returned to stop / 0 / 0 / 0 within 1 s.
- Every move starts with a "shifting" phase, 0.2-0.4 s, even right after another move on the same
  slot (direct, polled every 60 ms).
- After `action` returns to "ready", the slot can stay "unwinding" for another ~1.3 s.
- `speed` is mm/s: unstopped 10/20/30 mm moves at speed 50 fit motion time = overhead + length / 49.6
  mm/s in both directions, almost exactly linear (stop_timing).
- Overhead while `action` shows the motion: unwind 0.33 s, feed 0.94 s. Watch `action` for the end of a
  move; `status` / the slot's own status stay busy 1-1.7 s longer.
- **Stops work, with one exception** (direct, stop_timing):
  - `stop_unwind_filament` sent 0.28 s into the motion of a 30 mm unwind: motion ended 0.36 s later,
    which is the 0.33 s overhead plus about 0.03 s. So the stop takes effect within about 30 ms (polling
    every ~30 ms) and the status lags it by the overhead. Estimated travel 15 mm of 30.
  - `stop_feed_filament` sent 0.28 s after `feeding` appeared on a 30 mm feed: motion ended after 1.05 s
    against 1.55 s unstopped, an estimated 5 mm of 30. The feed's extra overhead seems to come before
    the filament moves.
  - `stop_feed_filament` sent during `shifting` was ignored and the feed ran in full (direct). A
    driver must send the stop again once the motion state appears, or wait for it.
  - Distances are inferred from timing; the unit reports no position.
- `action` (str) only appears in the reply once the unit has done something; it was absent at idle
  before that.

### `get_status` result

| field | type | values seen |
|---|---|---|
| `status` | str | `ready`, `busy` |
| `temp` | int | 31 (°C, presumably the dryer chamber) |
| `enable_rfid` | int | 1 |
| `fan_speed` | int | 7000 |
| `feed_assist_count` | int | 4326 (constant while idle) |
| `cont_assist_time` | float | 0.0 |
| `dryer_status.status` | str | `stop`, `drying` |
| `action` | str | `shifting`, `feeding`, `unwinding`, `ready` (absent until the first command) |
| `dryer_status.target_temp`, `.duration`, `.remain_time` | int | 0 |
| `slots[]` | 4 objects | `index` 0-3 |
| `slots[].status` | str | `ready`, `shifting`, `feeding`, `unwinding` |
| `slots[].sku`, `.type` | str | `""`, or `AHPEGY-101` / `PETG` on a tagged spool |
| `slots[].color` | [r, g, b] | `[0,0,0]`, or `[117,120,123]` on a tagged spool |
| `slots[].rfid` | int | 1 (no tag read), 2 (tag read) |

## Timing

- The host polled every 0.500 s. The unit replied in 2.2-6.3 ms (median 3.9 ms).
- Every reply matched a request; the unit sent nothing unsolicited while idle.

## Seen on the real unit while driving it (18 October, `captures/2026-10-18-busy-probe.txt` and the first tool changes)

- A move sent while the unit is busy, including the second or so after the motor stops while `status` is still
  `busy`, comes back `code` 0, `msg` "FORBIDDEN". Wait for `status` `ready` before each move.
- `stop_feed_assist` can answer `msg` "" (empty) with `code` 0, and then the unit pulls the filament back a short
  way by itself: `shifting`, then the slot `unwinding` for about 0.6 s, then `ready`. While the extruder's gears
  still hold the filament that pull can't finish and the unit stays `busy` (over 20 s seen). Back the filament
  out of the head before stopping feed assist. But not the other way round either: with feed assist still on, the
  unit pushes while the extruder backs the filament out, and on Workshop the filament buckled and snapped in the
  splitter. Stop feed assist, then back out with the extruder at once; the unit's short pull finishes as the gears
  let go.
- The unit missed replies when a second request arrived while one was open (twice, each as a stop met a status
  poll). Send one request at a time.
- An unwind at 5 mm/s is accepted.

## Not yet observed

Needs captures while each happens on a real unit:

- Physical overshoot after a stop (needs the extruder sensor test), and `speed` limits.
- An RFID tag read as a spool goes in; a slot going empty.
- Error states (a jam, an empty slot) in `status` and `slots[].status`.
- A second unit on the same host.
