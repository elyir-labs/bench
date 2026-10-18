# Bench Cloud: the printer's side

Bench Cloud is Elyir Bench's paid service (`design/cloud/`, C, picked 11 October 2026): a backup of each printer every
night, and a new card bringing one back once the house's owner allows it. This file is the printer's side of it: what a
printer sends, when, and how a fresh card gets a backup back. The service itself is a separate, closed project.

## Rules

- **Control never moves to the cloud.** Nothing here starts, stops or changes a print. A printer prints the same with
  Bench Cloud off, unreachable or gone, and nothing at home ever waits for it.
- **The house has the plan; a person is its owner.** Owners sign in with Supabase Auth: an email code (sent through
  Postmark from hello@elyir.dev), no password; Bench Cloud checks each sign-in with Supabase, so "Sign out everywhere"
  stops a lost phone at once. Paired phones at home never sign in to anything.
- **A backup comes back only at home, and only with the owner.** The cloud accepts a restore request only from the
  internet connection the printer was last seen on, and gives the backup once an owner allows it: Allow on their phone,
  or the code from their email typed on the printer's screen.
- **One house never sees another's printers.** Houses can share a public address (carrier-grade NAT), so every call
  also carries `X-Bench-Home`: a hash of the router's hardware address (`home_mark()`, from `/proc/net/route` and
  `/proc/net/arp`). A printer's backups are listed, and may be asked for, only by a card with the same mark.

## Joining a house

An owner's phone, at home, asks the cloud for a one-time join token per printer and hands it to the printer's door:

    POST /door/cloud/join   {"join_token": "j_…", "api": "https://cloud.elyir.dev"}    (a paired phone, home only)
    GET  /door/cloud        → {"joined", "name", "house", "last"}

The door claims the printer (`POST {api}/v1/devices`) and keeps what it gets in `~/elyir-bench/state/cloud.json`
(mode 600): the cloud's address, the printer's device id and its token. `elyir-bench cloud join <token>` does the same
from a shell.

## The nightly backup

The intent component starts `elyir-bench cloud backup` on its own (no systemd unit, so no new sudo rule): once a day in
the small hours (2 to 6 am, printer time), or at any hour once the last one is two days old. It runs apart from
Moonraker, at low priority, and writes `~/elyir-bench/state/cloud-last.json`: when and how big, or why it didn't happen.

A backup has the shape Bring it over already reads from a file, plus the door's own files:

| In the `.tar.gz` | What |
| --- | --- |
| `printer_data/config/…` | the config folder, without Bring it over's own folders (an earlier config, a backup waiting) |
| `printer_data/database/moonraker-sql.db` | the database as the component exports it for Bring it over: logins and API key taken out |
| `elyir-bench-state/relay.json`, `elyir-bench-state/door/phones.json`, `elyir-bench-state/door/vapid.pem` | the name from away and the paired phones |

The cloud keeps the last seven per printer.

## Where the owner sees it

One Elyir account, in the Printers app (`design/one-cloud/`, A, picked 15 October 2026): the round button by the title
opens **You** at `printers.elyir.app/you` (sign in, the plan, each printer from away and its last backup with Download,
the phones and computers signed in, owners). A paired printer not in the house yet is added from there, at home, through
its own door. `cloud.elyir.dev` itself only sends a person there; its own page (`design/cloud-home/`) is gone. The same
account is meant for the Elyir home hub.

## Paying for the plan

The account is free; the plan is what's paid (`design/one-cloud/`, stage 3): monthly $5 or yearly $50 through Stripe's
own checkout page, opened from You (`POST {api}/v1/checkout`, which makes the house on the way). Stripe's signed events
turn the plan on, keep its period, and turn it off when it stops; a paid plan stays on three days past its period while
a renewal goes through. Manage opens Stripe's customer portal (`POST {api}/v1/billing`). Backups and carry tickets follow
the plan. Until Stripe is set up on Bench Cloud, `/v1/config` says `pay: null` and the plan is by tester invite only.

## From away: the plan carries the printer's name

Reaching a printer from away is part of the plan (`design/one-cloud/`, decided 14 October 2026). On joining and with
every nightly backup, a printer in a house whose plan includes it asks `POST {api}/v1/carry-ticket {"name"}` with its
device token, and takes the ticket to the relay with its own secret: `POST {relay_api}/houses/<name>/carry {"ticket"}`
(`installer/elyir_bench.py`, `cloud_carry`; on the relay, its payers). The ticket is signed with
a key Bench Cloud and the relay share; it is good for an hour and carries the name about a month ahead, never shortening
a longer grant, so a plan that stops simply runs out and the name stays the printer's. The result is kept with the last
backup (`elyir-bench cloud status`, `last.carry`). Away, the Printers app says "At home only" for a printer out of reach
when the signed-in account's plan is off.

## What it's doing

Each printer tells Bench Cloud how it is (it fed the old owner's page, `design/cloud-home/`, and is kept for what comes
next: a new phone that already knows the printers, the virtual Bench Box). The intent component
sends `POST {api}/v1/status` every 5 minutes, or within 30 s of saying something new: its state and phase, the intent's
headline and detail, the job's name and progress, when it's done (epoch seconds), and its address from away (the
relay name, for Open). Nothing else: no files, no camera, no relay secret. A failed try waits its turn like a good one.

## Bringing a backup back (Bring it over's fourth source)

On a fresh card, `elyir-bench bring scan` also asks the cloud (`GET {api}/v1/restore/offers`) for backups of printers last
seen on this internet connection, and lists each as a source of kind `cloud` ("Your Bench Cloud backup", with the
owner's phone name and masked email for the screen). A card already in a house doesn't ask. A cloud that can't be
reached hides nothing else.

A cloud source can't be planned until it's allowed. The app's actions, each an `elyir-bench bring` run:

| Action | Run | Then |
| --- | --- | --- |
| `bring_cloud_ask {id}` | `cloud-ask <id>` | `bring.cloud.state` is `waiting`; the component runs `cloud-check` every 3 s by itself |
| `bring_cloud_email` | `cloud-email` | the owner's email gets a code (`bring.cloud.emailed`) |
| `bring_cloud_code {code}` | `cloud-code <code>` | six digits; allowed when right |
| (by itself) | `cloud-check` | `allowed`, `refused` or `expired` |

Once allowed, the backup is written to `config/elyir-bench-bring/<name>-bench-cloud.tar.gz`, the card takes the printer's
place in the house (its new device token in `cloud.json`; the old card's token stops working), the door's files are put
back where none are, and the scan runs again: `bring.cloud.file` names the backup file's source, which is planned and
brought over like any other.

## Settings

`cloud_api` in `elyir-bench.conf` points a printer at another Bench Cloud (default `https://cloud.elyir.dev`).

## Not yet

A Bench Box's own backup (and with it the box's lost-phone steps, C-box-lost), moving the owner after a lost phone from a
printer's screen (the cloud's `/v1/recover` is ready), payments, Face ID as the owner's shortcut, and push for the Allow
card (the owner's phone asks every 15 s while the app is open).

## The screens (design/cloud/ C, built 12 October 2026)

- **Bring it over:** the backup leads the list ("Your Bench Cloud backup", `sourceRows`); picking it shows the owner
  screen (`screenFor` → `cloud`): Allow on the owner's phone, or Send the code and type it (the panel's keypad, the
  phone's field). Allowed, the backup file is planned like any other. Words in `app/src/intent/bring.ts`.
- **Care (a phone at home):** the Bench Cloud card (`components/cloud/CloudCard.vue`, words in `app/src/cloud.ts`): Turn
  on (email and tester invite, the invite checked first; then Supabase's code), Add <printer> once the owner is signed in
  on this page, a second owner by email (they sign in themselves). The owner's Supabase session is kept per page address
  (`localStorage`) and refreshed before it runs out, so each printer's page asks for one email code.
- **The Allow card:** `asks.ts` also asks Bench Cloud for restore asks when an owner is signed in here; `AskCard` shows
  "Allow Workshop's backup onto a new card?", at home or away.

## A staging printer

Staging is a second Bench Cloud with its own Printers app (`cloud-staging.elyir.app`, `printers-staging.elyir.app`; how
it's run is in Bench Cloud's own repository). A printer joins it with two lines in `elyir-bench.conf`, then `elyir-bench
apply`:

```ini
cloud_api = https://cloud-staging.elyir.app
printers_app = https://printers-staging.elyir.app
```

`printers_app` lets staging's Printers app call and frame the printer (production's still can) and makes its pairing
code open that app (`door.py --printers-app`). The app's staging build is `STAGE=staging scripts/publish-shell.sh`. The
relay is shared: a staging printer's name is carried by staging's own key there.

