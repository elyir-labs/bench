# The door: reaching a printer from anywhere

The door lets a phone reach its printer from outside the house: watch the print, get told when the
printer needs you, pause or stop it. It is part of Elyir Bench and needs nothing else. A printer
with the door turned off works exactly as before, on the home Wi-Fi only.

## Rules

- **Elyir Bench stands alone.** Nothing here imports, assumes or mentions any other product. The
  relay is reached only through its public protocols: frp for the tunnel, and a small HTTP API to
  claim a name. Bringing your own relay and domain is a setting, not a fork.
- **The relay never sees inside.** It routes each connection by the name in the TLS handshake and
  forwards bytes. TLS ends on the printer, which holds the only key for its name.
- **Moonraker is never on the internet.** Phones away talk to the door, and the door passes on
  only what it allows: watching, and a short list of actions. Everything else is refused before
  it reaches Moonraker.
- **Being on the internet gets nobody anything.** Only a paired phone gets past the app's own
  files, and a phone is paired by somebody standing at the printer, **or invited by someone already
  paired** (a Bench Box's guests, below; design/bench-remote/, C, 9 October 2026). The risk that
  adds, plainly: an invite link forwarded before it's opened lets in whoever opens it. That's why a link
  works once, stops working a day after it's made if nobody opened it, watching only is the default,
  the guest's name shows on the box with who invited them, and Remove ends it at once.
- **The home Wi-Fi is unchanged.** nginx on port 8088 keeps serving the app and Moonraker to the
  house as before. The door adds a public name and a name at home; it takes nothing away.

## Shape

```
phone ──https──▶ relay (routes by name, cannot read) ──▶ frpc on the Pi
                                                          │ PROXY header + raw TLS
                                                          ▼
                                   Caddy 127.0.0.1:9443  (the printer's certificate, TLS-ALPN-01)
                                                          │ http
                                                          ▼
                                   door 127.0.0.1:8089   (the away listener: pairing, gate, push)
                                     │ app files            │ allowed calls only
                                     ▼                      ▼
                                   nginx :8088            Moonraker :7125

panel / Wi-Fi ──▶ nginx :8088 ──/door/──▶ door 127.0.0.1:8090 (the home listener)
```

Which listener a request arrives on is the whole of how the door knows where it came from. The
away listener is only ever reached through Caddy, so everything on it is from outside; the home
listener is only reached through nginx, so everything on it is from the house. No header is
trusted for that.

## Pieces on the printer

| Piece | What it is | Where |
|---|---|---|
| `elyir-bench-door` | the door service (Python, aiohttp, pywebpush) | `~/elyir-bench/current/door/`, venv in `~/elyir-bench/venv` |
| `elyir-bench-caddy` | Caddy 2.11.4, the away listener and the certificate | binary in `~/elyir-bench/bin/`, config rendered by the installer |
| `elyir-bench-frpc` | frpc 0.71.0, the tunnel | binary in `~/elyir-bench/bin/` |
| name and secret | the claim on the relay | `~/elyir-bench/state/relay.json`, mode 0600 |
| phones, push keys | who is paired, their subscriptions, the VAPID key | `~/elyir-bench/state/door/` |

Secrets never go in `~/printer_data/config`, because people back that folder up to git.

## Settings

In `elyir-bench.conf`, `[elyir-bench]`:

```
remote: off            # off | relay | own
remote_name: p-k7qx2mna  # the name to claim; the address is <name>.<zone>. New printers get p- and eight
                        # characters from the machine id and board serial (public_name()), never the hostname:
                        # names go into public DNS and the certificate logs
# own relay only:
#relay_addr: relay.example.net
#relay_zone: example.net
```

`relay` uses the hosted relay at `elyir.app`: the installer claims the name through
`https://api.elyir.app`, keeps the secret it is given, and the relay carries the printer once the
operator has granted it. `own` points frpc at your own frps and domain; its token is set with
`elyir-bench remote token <token>` so it stays out of the settings file.

An invite code (minted by the relay's operator) is a grant made ahead of time, so
nobody waits on the operator. It goes in at install (`install.sh --invite <code>`, which runs
`elyir-bench apply --invite <code>`) or any time after with `elyir-bench remote invite <code>`. Either way
it waits in `relay.json` until the relay answers. Brought later, it goes to the name the printer
already holds; if the relay let that name go (unapproved for a day), the printer claims it again with
the code. A code the relay refuses never costs the name: the printer says why and claims without it.
`remote invite` runs only the door's steps, so it is safe mid-print.

## What a phone away may do

Calls over Moonraker's websocket, by method:

- **Watching:** `server.connection.identify`, `server.info`, `printer.info`, `printer.intent`,
  `printer.intent.events`, `printer.intent.check_print`, `printer.objects.list`,
  `printer.objects.query`, `printer.objects.subscribe`, `server.history.list`,
  `server.files.list`, `server.files.get_directory` (the Print tab's library, browse only),
  `server.files.metadata`, `server.webcams.list`, and `server.database.get_item` in the
  `elyir-bench` and `maintenance` namespaces.
- **Acting:** `printer.intent.action` with one of `pause`, `resume`, `cancel`, `cool_down`,
  `swap_slot`, `dismiss_swap`, `care_later`, `help`, `skip_part`, `change_good` and `change_more` (the
  colour check, on the camera), and `colour_choose` at a colour-change pause only with `how: keep`, or
  `how: switch` once the app's extra confirmation sent `away_ok: true`. Putting a spool in (`put_in`,
  `swap`) needs hands and stays at the printer. Turning the printer off or restarting it (`power_off`,
  `power_restart`, `power_keep`, `power_now`, `power_retry`) is allowed too: it still waits for the nozzle to cool,
  and the app says that only someone at the printer can switch it on again (design/power/).

Over plain HTTP: thumbnails under `/server/files/gcodes/**/.thumbs/`, and the camera under
`/webcam/`. Notifications from Moonraker are passed on only for the kinds the app reads.

Not from away, on purpose: starting a print, heating, moving, G-code, files, spools and anything
under `machine.*`. Each of those either needs a person at the printer (is the bed clear, is the
spool really loaded) or could do harm with nobody there. Saying "the bed is clear" or "I wiped the
bed" is a claim about the physical printer, so `taken_off` and `care_done` wait for the panel too.

## Pairing

A phone is paired at the printer. On the panel, Care, Phones, Add a phone shows a QR code for ten
minutes. It holds `https://<name>.<zone>/pair#<code>`; the code is in the fragment so it never
reaches a log. The phone opens it, names itself, and is given a cookie for the printer's name
(HttpOnly, Secure, SameSite=Lax). A computer types the eight-letter code instead. Each code works
once. Wrong codes are counted per address, five in ten minutes.

The panel lists every phone and removes one with a tap; removal takes effect at once.

**Invited, on a Bench Box.** The box's own door (docs/bench.md, "From away") pairs phones at the box the same way, and
also lets a phone already paired with it, or the box's own screen, send an invite: a link
`https://<box>/join#<code>`, one use, a day to open it. Whoever opens it gives a name and becomes a guest (a `Phones`
record with `kind: guest`, `reach`, `until`, `invited_by`): `reach: watch` gets the watching calls only
(`allowed_call(..., act=False)`), `step_in` the away list above; `until` is a day or a week from the invite, or none
until removed, and `Phones.identify` refuses a guest past it. Guests can't invite anyone, add to the queue or change
anything on the bench. A printer's own door has no invites.

## Push

The four routes the app already uses: `GET /door/push/key`, `POST /door/push/subscribe`,
`DELETE /door/push/subscribe`, `GET /door/push/me`, all on the away listener and all for paired
phones only.

The door follows Moonraker's `notify_elyir_bench_event` and catches up through
`printer.intent.events` after a reconnect, using `boot` as the only resync signal. Each event is
sent to every subscribed phone whose kinds include it (no `kinds` means all, including kinds added
later), with `Urgency` from the event, `Topic` from its tag, and a TTL by kind. Low and very-low
events are held overnight in each phone's own time zone and sent in the morning while still
within their TTL; high is never held. Subscriptions the push service says are gone (404 or 410)
are dropped.

The door writes the number of phones that will hear `finished` to Moonraker's database,
`elyir-bench` / `phones`, on every change and on every reconnect; the Finished screen only promises
to tell your phone when that number is above zero.

## Home first

A phone at home talks to the printer directly; the relay is only for when it is away. Each printer
has a second name that spells its LAN address, `192-0-2-73.workshop.home.elyir.app`. The relay's DNS
server answers it with that address (only for names it carries, only private addresses), and the
printer proves the name over DNS-01 through the relay's API with the same secret it claimed its public
name with, so the private key never leaves the printer. Caddy serves it on port 443 of the Wi-Fi, in
front of the door's home listener (127.0.0.1:8091). `elyir-bench-homecert.timer` runs `elyir-bench
homecert` every 15 minutes: it follows the LAN address, gets a new certificate when the name moves,
renews within 30 days of expiry, and writes the current name to `~/elyir-bench/state/home.json`, which
the door reads fresh for every `/door/me`. A DHCP reservation for the printer saves the churn.

At home a paired phone gets everything the panel can do, starting prints included; away it gets the
short list above. Only the DNS lookup touches the relay, and it is cached. A router that drops private
answers (rebind protection) or iCloud Private Relay leaves a phone on the relay at home, quietly.

## A new name

A printer's public name ends up in public DNS and the certificate logs, so new printers get one that says nothing
about them (`public_name()`: `p-` and eight characters). A printer that has a readable name moves like this:

1. Set `remote_name` to the new name (on the printer: `elyir-bench public-name`, or any free name) and apply. The
   new name is claimed and kept in `state/relay-next.json`; the printer goes on answering the old one.
2. Once the relay carries the new name (a grant, or the house's Bench Cloud plan, which apply asks for), the next
   apply switches: the old claim moves to `state/relay-former.json`, `remote_former` and `printer_id` are set to the
   old name, and `elyir-bench-frpc-former.service` keeps a tunnel open for it, with Caddy holding its certificate.
3. Phones need nothing. The next time each one opens the printer it arrives on the old name (its saved name at home
   no longer answers, so it falls back to the public one), and `/door/me` tells it the new addresses, which the
   Printers app saves. The printer's id, the phone's token and its notifications are unchanged.
4. `elyir-bench remote phones` lists each phone and the name it last came in on. When none is on the old name, clear
   `remote_former` and apply: the second tunnel goes.

**Never release the old name on the relay**, and don't stop it: a phone that still had it saved would send its
token to whoever claimed it next. It stays granted, with no tunnel. Certificates already issued for the old name
stay in the public logs.

## One app for every printer

The shell at `https://printers.elyir.app` holds every printer a phone is paired with, and loads each
printer's own screens from that printer in a frame, so the screens always match the printer's version.
It tries each printer's home name first (about 1.5 s) and falls back to its public name.

- **Tokens, not cookies.** The two names are two origins, so the shell keeps the token `POST
  /door/pair` returns and sends it as `Authorization: Bearer`, as the websocket subprotocol
  `elyir-bench-token.<token>` (the door selects `elyir-bench`), or, for `<img>` on the camera and
  thumbnails only, as `?access_token=`. The printer's own app keeps using its cookie.
- **CORS** only for the shell's origins; preflights answer `Access-Control-Allow-Private-Network`.
  Chrome also asks the person for local-network access; the shell treats no as "use the public name".
- **Framing:** the printer's files carry `Content-Security-Policy: frame-ancestors 'self'` and the shell.
- **One push subscription for every printer.** The shell makes one P-256 key on the phone and sends it
  with the subscription to each printer (`vapid` in `POST /door/push/subscribe`); the door signs that
  phone's pushes with it. It lives only in that phone's record (0600) and goes when the phone is
  removed; a new key replaces the old. Payloads carry `printer` so a tap opens the right one. The
  consequence, stated plainly: any printer a phone is paired with can send that phone any notification.
- **Adding a printer:** `/door/pair/new` also returns `shell_url`, which the panel's QR code shows.
  Printers can also scan that code itself (Add, then Scan the printer's code), which pairs the
  installed app directly; on an iPhone that matters, because the Camera app opens it in Safari.

## Lessons from the printers

Two things that went wrong on workshop and studio on 2 October 2026, kept here so they stay fixed:

- **The token never goes past the door.** `?access_token=` (images only) is how a phone proves
  itself to the door, nothing more. Moonraker reads a query parameter of that name as its own login,
  so passing it on made Moonraker refuse thumbnails and write the token to `moonraker.log`.
  `forward_query()` drops it before anything is forwarded to Moonraker or the camera; a test pins it.
- **A new release restarts the door.** The door's unit runs `current/door/door.py`, so after a
  release switch nothing on disk differs and the installer's check used to pass while the old code
  kept running. `DoorServices` now asks for one restart per switch. After changing the door, check
  that `systemctl show elyir-bench-door -p ActiveEnterTimestamp` moved.

## Printers the box speaks for

A printer with no Pi of its own (an Anycubic Kobra with Rinkhals, docs/bench.md) gets its door on the Bench Box, one per
printer (`bench/doors.py`): the same `door.py`, its own state and three loopback ports (from 8200, four per printer), in
front of that printer's stand-in, which publishes the intent and `notify_elyir_bench_event` as a printer's Moonraker does.
Its public name is claimed with its own secret (`state/bench/standins/<id>/relay.json`, 0600), its own frpc logs in as that
name, and one Caddy for all of them holds each name's certificate on 127.0.0.1:9444. The installer gives a Bench Box Caddy
and frpc whatever its own `remote` says. It opens by itself when the Kobra is added, as a printer's door
does at install (`remote: relay`, the default), and the app's secure link and Finish setting up work as on any printer. An
invite code goes in with `POST /bench/p/<id>/remote {"invite": "…"}`. Its name at home spells the box's address and is
kept the same way as a printer's (lego through the relay, every 15 minutes), served by the same Caddy on 443.

The box's own public name (design/bench-remote/, docs/bench.md "From away") is claimed and tunnelled the same way, with its
own secret (`state/bench/box/relay.json`), as one more site on the same Caddy, in front of the box's away listener
(127.0.0.1:8189) rather than a door per printer: it passes each printer's away list on and adds nothing to it.

Tried 6 October 2026 against a simulated Kobra with a stand-in relay: paired from the Kobra's screen on the box, watched
through its away listener (G-code refused from away), and a problem on the printer reached the door as a push to send.

## Living with a hub

Nothing here knows about any hub. A home system that wants the printer pairs with it like a phone
does and reads the same events. If it then sends the alerts itself, it is the one that decides not
to send twice.
